"""Read local credential files without exposing their contents in logs."""
import json
from pathlib import Path
import re

DEFAULT_AUTH = Path(__file__).resolve().parent / '.local/auth.json'


def read_pat(path):
    try:
        token = Path(path).expanduser().read_text().strip()
    except (OSError, UnicodeError):
        raise ValueError('Cannot read PAT file') from None
    if not token or any(c.isspace() for c in token):
        raise ValueError('PAT file must contain one non-empty token')
    return token


def repository_id(url):
    match = re.fullmatch(r'https://github\.com/([A-Za-z0-9_-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?', url)
    if not match:
        raise ValueError('github_repository must be a GitHub HTTPS repository URL')
    return (match[1].lower(), match[2].lower())


def read_auth(path, repo_url=None):
    path = Path(path).expanduser().resolve()
    try:
        config = json.loads(path.read_text())
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ValueError('Cannot read auth config; expected a JSON object of credential file paths') from None
    if not isinstance(config, dict) or set(config) - {'github_pat_file', 'github_repository'}:
        raise ValueError('Auth config supports github_pat_file and github_repository')
    if 'github_repository' in config:
        if not isinstance(config['github_repository'], str):
            raise ValueError('github_repository must be a repository URL')
        expected = repository_id(config['github_repository'])
        if repo_url is None or repository_id(repo_url) != expected:
            return ''
    if config.get('github_pat_file'):
        if not isinstance(config['github_pat_file'], str):
            raise ValueError('github_pat_file must be a file path')
        source = Path(config['github_pat_file']).expanduser()
        if not source.is_absolute():
            source = path.parent / source
        return read_pat(source)
    return ''
