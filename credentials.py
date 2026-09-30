"""Read local credential files without exposing their contents in logs."""
import json
from pathlib import Path
import re

DEFAULT_AUTH = Path.home() / '.config/colab-ssh/auth.json'


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


def resolve_pat_file(config_path, value):
    if not isinstance(value, str) or not value:
        raise ValueError('PAT mapping values must be file paths')
    source = Path(value).expanduser()
    if not source.is_absolute():
        source = config_path.parent / source
    return source


def read_auth(path, repo_url=None):
    path = Path(path).expanduser().resolve()
    try:
        config = json.loads(path.read_text())
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ValueError('Cannot read auth config; expected a JSON object of credential file paths') from None
    allowed = {'github_pat_file', 'github_repository', 'github_repositories'}
    if not isinstance(config, dict) or set(config) - allowed:
        raise ValueError('Auth config supports github_pat_file, github_repository and github_repositories')
    if 'github_repositories' in config:
        if 'github_repository' in config:
            raise ValueError('github_repository cannot be combined with github_repositories')
        mapping = config['github_repositories']
        if not isinstance(mapping, dict):
            raise ValueError('github_repositories must map repository URLs to PAT files')
        normalized = {}
        for repository, pat_file in mapping.items():
            if not isinstance(repository, str):
                raise ValueError('github_repositories keys must be repository URLs')
            key = repository_id(repository)
            if key in normalized:
                raise ValueError('github_repositories contains a duplicate repository')
            normalized[key] = resolve_pat_file(path, pat_file)
        key = repository_id(repo_url) if repo_url is not None else None
        if key in normalized:
            return read_pat(normalized[key])
    if 'github_repository' in config:
        if not isinstance(config['github_repository'], str):
            raise ValueError('github_repository must be a repository URL')
        expected = repository_id(config['github_repository'])
        if repo_url is None or repository_id(repo_url) != expected:
            return ''
    if config.get('github_pat_file'):
        return read_pat(resolve_pat_file(path, config['github_pat_file']))
    return ''


def save_pat_mapping(repo_url, token, path=None):
    path = Path(path or DEFAULT_AUTH).expanduser().resolve()
    owner, repository = repository_id(repo_url)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    config = {}
    if path.exists():
        try:
            config = json.loads(path.read_text())
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise ValueError('Cannot update auth config; expected a JSON object') from None
        if not isinstance(config, dict):
            raise ValueError('Cannot update auth config; expected a JSON object')
    allowed = {'github_pat_file', 'github_repository', 'github_repositories'}
    if set(config) - allowed:
        raise ValueError('Cannot update auth config with unsupported fields')
    mapping = config.get('github_repositories', {})
    if not isinstance(mapping, dict):
        raise ValueError('github_repositories must map repository URLs to PAT files')
    if 'github_repository' in config:
        legacy_file = config.get('github_pat_file')
        if legacy_file:
            mapping[config['github_repository']] = legacy_file
        config.pop('github_repository')
        config.pop('github_pat_file', None)
    filename = f'github-{owner}-{repository}.pat'
    pat_path = path.parent / filename
    pat_path.write_text(token + '\n')
    pat_path.chmod(0o600)
    mapping[f'https://github.com/{owner}/{repository}'] = filename
    config['github_repositories'] = mapping
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(config, indent=2, sort_keys=True) + '\n')
    temporary.chmod(0o600)
    temporary.replace(path)
    return pat_path
