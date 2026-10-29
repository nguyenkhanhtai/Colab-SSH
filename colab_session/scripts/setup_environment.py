import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

profile = json.load(sys.stdin)
home = Path.home()
env = {**os.environ, "PATH": str(home / '.local/bin') + ':' + os.environ.get('PATH', '')}
urls = {
    'codex': ('codex', 'https://chatgpt.com/codex/install.sh'),
    'antigravity': ('agy', 'https://antigravity.google/cli/install.sh')
}

for tool in profile['tools']:
    binary, url = urls[tool]
    if not shutil.which(binary, path=env['PATH']):
        with tempfile.TemporaryDirectory(prefix='colab-tools-') as tmp:
            installer = Path(tmp) / 'install.sh'
            subprocess.run(
                ['curl', '--fail', '--silent', '--show-error', '--location',
                 '--retry', '2', '--max-time', '120', url, '-o', str(installer)],
                check=True
            )
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

candidates = sorted((home / '.vscode-server').glob('**/bin/code-server'))
if candidates:
    for extension in profile['extensions']:
        subprocess.run(
            [str(candidates[-1]), '--install-extension', extension,
             '--extensions-dir', str(home / '.vscode-server/extensions')],
            check=True,
            env=env
        )
else:
    print('Extensions will install on the first VS Code Remote-SSH connection.')

print('Environment ready. Sign in with: codex login --device-auth; agy')

