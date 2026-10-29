"""Capture VS Code preferences and prepare development tools on a Colab VM."""
import argparse
from io import BytesIO
import json
from pathlib import Path
import re
import shlex
import subprocess
import tarfile
from typing import Any, Dict, List, Optional

from colab_session.resources import read_resource

PROFILE = Path.home() / '.config/colab-ssh/environment.json'


class JSONCParser:
    """Parses JSON with comments and trailing commas (Single Responsibility: JSONC parsing)."""

    COMMENT_PATTERN = re.compile(r'("(?:\\.|[^"\\])*"|//[^\n]*|/\*[\s\S]*?\*/)')
    COMMA_PATTERN = re.compile(r'("(?:\\.|[^"\\])*"|,\s*(?=[}\]]))')

    @classmethod
    def parse(cls, text: str) -> Any:
        clean = cls.COMMENT_PATTERN.sub(lambda m: m[0] if m[0].startswith('"') else '', text)
        clean = cls.COMMA_PATTERN.sub(lambda m: m[0] if m[0].startswith('"') else '', clean)
        return json.loads(clean)


class VSCodeProfileManager:
    """Manages capturing local settings/extensions and registering remote extensions."""

    ALLOWED_SETTINGS = frozenset({
        'files.autoSave', 'files.autoSaveDelay', 'files.trimTrailingWhitespace',
        'files.insertFinalNewline', 'files.trimFinalNewlines', 'files.eol',
        'editor.tabSize', 'editor.insertSpaces', 'editor.detectIndentation',
        'editor.formatOnSave', 'editor.formatOnPaste', 'editor.defaultFormatter',
        'editor.wordWrap', 'editor.rulers', 'editor.renderWhitespace',
        'editor.minimap.enabled', 'editor.bracketPairColorization.enabled'
    })

    DEFAULT_EXTENSIONS = ('openai.chatgpt', 'google.google-antigravity')

    @classmethod
    def capture(cls, home: Optional[Path] = None, profile_path: Optional[Path] = None) -> Dict[str, Any]:
        home_path = Path.home() if home is None else Path(home)
        target_profile = profile_path or PROFILE
        source = home_path / '.config/Code/User/settings.json'
        settings = JSONCParser.parse(source.read_text()) if source.exists() else {}
        remote = {k: v for k, v in settings.items() if k in cls.ALLOWED_SETTINGS}
        installed = home_path / '.vscode/extensions/extensions.json'
        extensions = []
        if installed.exists():
            extensions = [item.get('identifier', {}).get('id', '')
                          for item in json.loads(installed.read_text())]
        extensions = sorted({e for e in extensions if re.fullmatch(r'[\w-]+\.[\w.-]+', e)
                             and not e.startswith(('ms-vscode-remote.', 'ms-vscode.remote-'))})
        for e in cls.DEFAULT_EXTENSIONS:
            if e not in extensions:
                extensions.append(e)
        profile = {'tools': ['codex', 'antigravity'], 'extensions': extensions,
                   'remote_settings': remote}
        target_profile.parent.mkdir(parents=True, exist_ok=True)
        target_profile.write_text(json.dumps(profile, indent=2, ensure_ascii=False) + '\n')
        return profile

    @classmethod
    def load(cls, profile_path: Optional[Path] = None) -> Dict[str, Any]:
        target = profile_path or PROFILE
        return json.loads(target.read_text()) if target.exists() else cls.capture(profile_path=target)

    @classmethod
    def register_extensions(cls, profile: Dict[str, Any], home: Optional[Path] = None) -> None:
        home_path = Path.home() if home is None else Path(home)
        path = home_path / '.config/Code/User/settings.json'
        text = path.read_text() if path.exists() else '{}'
        settings = JSONCParser.parse(text)
        previous = settings.get('remote.SSH.defaultExtensions', [])
        if not isinstance(previous, list):
            raise ValueError('remote.SSH.defaultExtensions must be an array')
        extensions = list(dict.fromkeys(previous + profile['extensions']))
        if extensions == previous:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        backup = path.with_name('settings.colab-session.backup.jsonc')
        if not backup.exists():
            backup.write_text(text)
            backup.chmod(0o600)
        settings['remote.SSH.defaultExtensions'] = extensions
        path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + '\n')


class EnvironmentScriptGenerator:
    """Generates remote python setup code to run on Colab VM."""

    @staticmethod
    def remote_code() -> str:
        return read_resource("scripts", "setup_environment.py")


class ContextSynchronizer:
    """Discovers and synchronizes local AI assistant context to the remote VM."""

    SECRET_FILENAMES = frozenset({'auth.json', 'credentials.json', 'mcp_oauth_tokens.json', '.env'})

    @staticmethod
    def context_paths(home: Optional[Path | str] = None) -> List[Path]:
        home_path = Path.home() if home is None else Path(home)
        candidates = [
            home_path / '.codex/AGENTS.md',
            home_path / '.codex/skills',
            home_path / '.codex/sessions',
            home_path / '.codex/archived_sessions',
            home_path / '.gemini/GEMINI.md',
            home_path / '.gemini/antigravity-cli/skills',
            home_path / '.gemini/antigravity/conversations',
            home_path / '.gemini/antigravity-ide/conversations',
        ]
        return [path for path in candidates if path.exists()]

    @classmethod
    def sync_context(cls, ssh: List[str], home: Optional[Path | str] = None) -> List[str]:
        home_path = Path.home() if home is None else Path(home)
        paths = cls.context_paths(home_path)
        if not paths:
            return []
        archive = BytesIO()

        def safe_member(info):
            basename = Path(info.name).name.lower()
            if (info.issym() or info.islnk() or basename in cls.SECRET_FILENAMES or basename.endswith('.pat')
                    or '/.system/' in '/' + info.name or info.name.endswith('/.system')):
                return None
            return info

        with tarfile.open(fileobj=archive, mode='w:gz') as bundle:
            for path in paths:
                bundle.add(path, arcname=path.relative_to(home_path), filter=safe_member)
        subprocess.run([*ssh, 'mkdir -p /root && tar -xzf - -C /root'], input=archive.getvalue(), check=True)
        return [str(path.relative_to(home_path)) for path in paths]


def read_jsonc(text: str) -> Any:
    return JSONCParser.parse(text)


def capture() -> Dict[str, Any]:
    return VSCodeProfileManager.capture(profile_path=PROFILE)


def load_profile() -> Dict[str, Any]:
    return VSCodeProfileManager.load(profile_path=PROFILE)


def register_extensions(profile: Dict[str, Any]) -> None:
    VSCodeProfileManager.register_extensions(profile)


def remote_code() -> str:
    return EnvironmentScriptGenerator.remote_code()


def apply(ssh: List[str], profile: Dict[str, Any]) -> None:
    subprocess.run([*ssh, 'python3 -c ' + shlex.quote(remote_code())],
                   input=json.dumps(profile), text=True, check=True)


def context_paths(home: Optional[Path | str] = None) -> List[Path]:
    return ContextSynchronizer.context_paths(home)


def sync_context(ssh: List[str], home: Optional[Path | str] = None) -> List[str]:
    return ContextSynchronizer.sync_context(ssh, home)

