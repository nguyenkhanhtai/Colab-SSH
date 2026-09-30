"""Capture VS Code preferences and prepare development tools on a Colab VM."""
import argparse
from io import BytesIO
import json
from pathlib import Path
import re
import shlex
import subprocess
import tarfile

PROFILE = Path.home() / '.config/colab-ssh/environment.json'


def read_jsonc(text):
    # Preserve strings while stripping JSONC comments and trailing commas.
    pattern = r'("(?:\\.|[^"\\])*"|//[^\n]*|/\*[\s\S]*?\*/)'
    clean = re.sub(pattern, lambda m: m[0] if m[0].startswith('"') else '', text)
    clean = re.sub(r'("(?:\\.|[^"\\])*"|,\s*(?=[}\]]))',
                   lambda m: m[0] if m[0].startswith('"') else '', clean)
    return json.loads(clean)


def capture():
    source = Path.home() / '.config/Code/User/settings.json'
    settings = read_jsonc(source.read_text()) if source.exists() else {}
    # User interface preferences remain local. Copy portable editor/file behavior.
    allowed = {'files.autoSave', 'files.autoSaveDelay', 'files.trimTrailingWhitespace',
               'files.insertFinalNewline', 'files.trimFinalNewlines', 'files.eol',
               'editor.tabSize', 'editor.insertSpaces', 'editor.detectIndentation',
               'editor.formatOnSave', 'editor.formatOnPaste', 'editor.defaultFormatter',
               'editor.wordWrap', 'editor.rulers', 'editor.renderWhitespace',
               'editor.minimap.enabled', 'editor.bracketPairColorization.enabled'}
    remote = {k: v for k, v in settings.items() if k in allowed}
    installed = Path.home() / '.vscode/extensions/extensions.json'
    extensions = []
    if installed.exists():
        extensions = [item.get('identifier', {}).get('id', '')
                      for item in json.loads(installed.read_text())]
    extensions = sorted({e for e in extensions if re.fullmatch(r'[\w-]+\.[\w.-]+', e)
                         and not e.startswith(('ms-vscode-remote.', 'ms-vscode.remote-'))})
    for e in ['openai.chatgpt', 'google.google-antigravity']:
        if e not in extensions:
            extensions.append(e)
    profile = {'tools': ['codex', 'antigravity'], 'extensions': extensions,
               'remote_settings': remote}
    PROFILE.parent.mkdir(parents=True, exist_ok=True)
    PROFILE.write_text(json.dumps(profile, indent=2, ensure_ascii=False) + '\n')
    return profile


def load_profile():
    return json.loads(PROFILE.read_text()) if PROFILE.exists() else capture()


def register_extensions(profile):
    path = Path.home() / '.config/Code/User/settings.json'
    text = path.read_text() if path.exists() else '{}'
    settings = read_jsonc(text)
    previous = settings.get('remote.SSH.defaultExtensions', [])
    if not isinstance(previous, list):
        raise ValueError('remote.SSH.defaultExtensions must be an array')
    extensions = list(dict.fromkeys(previous + profile['extensions']))
    if extensions == previous:
        return
    # Backup full JSONC, retaining all other settings in the replacement JSON.
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = path.with_name('settings.colab-session.backup.jsonc')
    if not backup.exists():
        backup.write_text(text)
        backup.chmod(0o600)
    settings['remote.SSH.defaultExtensions'] = extensions
    path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + '\n')


def remote_code():
    return r'''import json, os, shutil, subprocess, sys, tempfile
from pathlib import Path
profile = json.load(sys.stdin)
home = Path.home()
env = {**os.environ, "PATH": str(home / '.local/bin') + ':' + os.environ.get('PATH', '')}
urls = {'codex': ('codex', 'https://chatgpt.com/codex/install.sh'),
        'antigravity': ('agy', 'https://antigravity.google/cli/install.sh')}
for tool in profile['tools']:
    binary, url = urls[tool]
    if not shutil.which(binary, path=env['PATH']):
        with tempfile.TemporaryDirectory(prefix='colab-tools-') as tmp:
            installer = Path(tmp) / 'install.sh'
            subprocess.run(['curl', '--fail', '--silent', '--show-error', '--location',
                            '--retry', '2', '--max-time', '120', url, '-o', str(installer)], check=True)
            command = ['bash', str(installer)]
            if tool == 'antigravity':
                command += ['--skip-aliases']
            subprocess.run(command, check=True, env=env)
    binary_path = shutil.which(binary, path=env['PATH'])
    if not binary_path:
        raise RuntimeError(f'{binary} missing after installation')
    subprocess.run([binary_path, '--version'], check=True, env=env)
line = 'export PATH="$HOME/.local/bin:$PATH"'
for name in ['.profile', '.bashrc']:
    path = home / name
    text = path.read_text() if path.exists() else ''
    if line not in text:
        path.write_text(text.rstrip() + '\n' + line + '\n')
settings_path = home / '.vscode-server/data/Machine/settings.json'
settings_path.parent.mkdir(parents=True, exist_ok=True)
if settings_path.exists():
    existing = settings_path.read_text()
    backup = settings_path.with_suffix('.before-colab.jsonc')
    if not backup.exists():
        backup.write_text(existing)
    try:
        settings = json.loads(existing)
    except json.JSONDecodeError:
        raise RuntimeError('Remote settings contain JSONC; merge the profile manually to preserve them')
else:
    settings = {}
settings.update(profile['remote_settings'])
settings_path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + '\n')
# Install now if VS Code Server already exists; otherwise defaultExtensions handles first connection.
candidates = sorted((home / '.vscode-server').glob('**/bin/code-server'))
if candidates:
    for extension in profile['extensions']:
        subprocess.run([str(candidates[-1]), '--install-extension', extension,
                        '--extensions-dir', str(home / '.vscode-server/extensions')], check=True, env=env)
else:
    print('Extensions will install on the first VS Code Remote-SSH connection.')
print('Environment ready. Sign in with: codex login --device-auth; agy')
'''


def apply(ssh, profile):
    subprocess.run([*ssh, 'python3 -c ' + shlex.quote(remote_code())],
                   input=json.dumps(profile), text=True, check=True)


def context_paths(home=None):
    home = Path.home() if home is None else Path(home)
    candidates = [
        home / '.codex/AGENTS.md',
        home / '.codex/skills',
        home / '.codex/sessions',
        home / '.codex/archived_sessions',
        home / '.gemini/GEMINI.md',
        home / '.gemini/antigravity-cli/skills',
        home / '.gemini/antigravity/conversations',
        home / '.gemini/antigravity-ide/conversations',
    ]
    return [path for path in candidates if path.exists()]


def sync_context(ssh, home=None):
    home = Path.home() if home is None else Path(home)
    paths = context_paths(home)
    if not paths:
        return []
    archive = BytesIO()

    def safe_member(info):
        basename = Path(info.name).name.lower()
        secrets = {'auth.json', 'credentials.json', 'mcp_oauth_tokens.json', '.env'}
        if (info.issym() or info.islnk() or basename in secrets or basename.endswith('.pat')
                or '/.system/' in '/' + info.name or info.name.endswith('/.system')):
            return None
        return info

    with tarfile.open(fileobj=archive, mode='w:gz') as bundle:
        for path in paths:
            bundle.add(path, arcname=path.relative_to(home), filter=safe_member)
    subprocess.run([*ssh, 'mkdir -p /root && tar -xzf - -C /root'], input=archive.getvalue(), check=True)
    return [str(path.relative_to(home)) for path in paths]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', action='store_true', help='Refresh profile from local VS Code')
    parser.add_argument('--register', action='store_true', help='Register automatic remote extensions locally')
    parser.add_argument('--session', help='Apply profile to an existing session')
    args = parser.parse_args()
    profile = capture() if args.capture else load_profile()
    if args.register:
        register_extensions(profile)
    if args.session:
        from setup_ssh import configure
        import shutil
        cli = shutil.which('colab')
        if not cli:
            parser.error('Run with uv run setup_environment.py')
        config, alias = configure(args.session, cli)
        apply(['ssh', '-F', str(config), '-o', 'BatchMode=yes', alias], profile)
    print(f'Profile: {PROFILE}\nTools: {", ".join(profile["tools"])}\nExtensions: {len(profile["extensions"])}')


if __name__ == '__main__':
    main()
