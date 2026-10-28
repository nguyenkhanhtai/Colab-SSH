"""Read and persist GitHub personal access tokens and auth mappings safely."""
from abc import ABC, abstractmethod
import json
from pathlib import Path
import re
from typing import Optional, Tuple

DEFAULT_AUTH = Path.home() / '.config/colab-ssh/auth.json'


class RepositoryIdentifier:
    """Parses and normalizes GitHub repository URLs (Single Responsibility: Repo identity)."""

    URL_PATTERN = re.compile(r'https://github\.com/([A-Za-z0-9_-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?')

    @classmethod
    def parse(cls, url: Optional[str]) -> Tuple[str, str]:
        if not url or not isinstance(url, str):
            raise ValueError('github_repository must be a GitHub HTTPS repository URL')
        match = cls.URL_PATTERN.fullmatch(url)
        if not match:
            raise ValueError('github_repository must be a GitHub HTTPS repository URL')
        return (match[1].lower(), match[2].lower())

    @classmethod
    def canonical_url(cls, owner: str, repository: str) -> str:
        return f'https://github.com/{owner}/{repository}'


class ITokenReader(ABC):
    """Interface for token readers (Interface Segregation / Dependency Inversion)."""

    @abstractmethod
    def read_token(self, path: Path | str) -> str:
        """Read and validate a token string from a path."""
        pass


class TokenFileReader(ITokenReader):
    """Reads personal access tokens from local files safely without exposing content on failure."""

    def read_token(self, path: Path | str) -> str:
        try:
            token = Path(path).expanduser().read_text().strip()
        except (OSError, UnicodeError):
            raise ValueError('Cannot read PAT file') from None
        if not token or any(c.isspace() for c in token):
            raise ValueError('PAT file must contain one non-empty token')
        return token


class CredentialManager:
    """Manages reading, resolving, and persisting repository credential mappings."""

    ALLOWED_KEYS = frozenset({'github_pat_file', 'github_repository', 'github_repositories'})

    def __init__(self, config_path: Optional[Path | str] = None, token_reader: Optional[ITokenReader] = None):
        self.config_path = Path(config_path or DEFAULT_AUTH).expanduser().resolve()
        self.token_reader = token_reader or TokenFileReader()

    def resolve_path(self, value: str) -> Path:
        """Resolve a relative or absolute PAT path against the auth config directory."""
        if not isinstance(value, str) or not value:
            raise ValueError('PAT mapping values must be file paths')
        source = Path(value).expanduser()
        if not source.is_absolute():
            source = self.config_path.parent / source
        return source

    def load_config(self) -> dict:
        """Load and parse the JSON auth config file."""
        try:
            config = json.loads(self.config_path.read_text())
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise ValueError('Cannot read auth config; expected a JSON object of credential file paths') from None
        if not isinstance(config, dict) or set(config) - self.ALLOWED_KEYS:
            raise ValueError('Auth config supports github_pat_file, github_repository and github_repositories')
        return config

    def resolve_token(self, repo_url: Optional[str] = None) -> str:
        """Resolve the matching PAT for the given repository URL."""
        config = self.load_config()
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
                key = RepositoryIdentifier.parse(repository)
                if key in normalized:
                    raise ValueError('github_repositories contains a duplicate repository')
                normalized[key] = self.resolve_path(pat_file)
            key = RepositoryIdentifier.parse(repo_url) if repo_url is not None else None
            if key in normalized:
                return self.token_reader.read_token(normalized[key])
        if 'github_repository' in config:
            if not isinstance(config['github_repository'], str):
                raise ValueError('github_repository must be a repository URL')
            expected = RepositoryIdentifier.parse(config['github_repository'])
            if repo_url is None or RepositoryIdentifier.parse(repo_url) != expected:
                return ''
        if config.get('github_pat_file'):
            return self.token_reader.read_token(self.resolve_path(config['github_pat_file']))
        return ''

    def save_mapping(self, repo_url: str, token: str) -> Path:
        """Persist a PAT mapping for repo_url in private configuration and return the PAT file path."""
        owner, repository = RepositoryIdentifier.parse(repo_url)
        self.config_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.config_path.parent.chmod(0o700)
        config = {}
        if self.config_path.exists():
            try:
                config = json.loads(self.config_path.read_text())
            except (OSError, UnicodeError, json.JSONDecodeError):
                raise ValueError('Cannot update auth config; expected a JSON object') from None
            if not isinstance(config, dict):
                raise ValueError('Cannot update auth config; expected a JSON object')
        if set(config) - self.ALLOWED_KEYS:
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
        pat_path = self.config_path.parent / filename
        pat_path.write_text(token + '\n')
        pat_path.chmod(0o600)
        mapping[RepositoryIdentifier.canonical_url(owner, repository)] = filename
        config['github_repositories'] = mapping
        temporary = self.config_path.with_suffix(self.config_path.suffix + '.tmp')
        temporary.write_text(json.dumps(config, indent=2, sort_keys=True) + '\n')
        temporary.chmod(0o600)
        temporary.replace(self.config_path)
        return pat_path


# Module-level backward compatibility facades
_default_token_reader = TokenFileReader()


def read_pat(path: Path | str) -> str:
    """Read a GitHub PAT from a file path."""
    return _default_token_reader.read_token(path)


def repository_id(url: str) -> Tuple[str, str]:
    """Parse a GitHub repository URL into (owner, repository) tuple."""
    return RepositoryIdentifier.parse(url)


def resolve_pat_file(config_path: Path, value: str) -> Path:
    """Resolve relative PAT path against config directory."""
    return CredentialManager(config_path).resolve_path(value)


def read_auth(path: Path | str, repo_url: Optional[str] = None) -> str:
    """Read auth config and resolve token for repository."""
    return CredentialManager(path).resolve_token(repo_url)


def save_pat_mapping(repo_url: str, token: str, path: Optional[Path | str] = None) -> Path:
    """Save token mapping for a repository URL."""
    return CredentialManager(path).save_mapping(repo_url, token)

