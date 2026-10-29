"""Custom exception hierarchy for Colab SSH operations."""


class ColabSessionError(Exception):
    """Base exception for all Colab SSH operations."""
    pass


class SessionNotFoundError(ColabSessionError, RuntimeError):
    """Raised when a requested Colab session is not found or inactive."""
    pass


class SessionProvisioningError(ColabSessionError, RuntimeError):
    """Raised when provisioning a new Colab runtime fails."""
    pass


class GpuAllocationError(ColabSessionError, RuntimeError):
    """Raised when the requested GPU/accelerator is unavailable or fails verification."""
    pass


class PreflightValidationError(ColabSessionError, ValueError):
    """Raised when job requirements (command, script, session, paths) fail pre-flight validation."""
    pass


class RemoteExecutionError(ColabSessionError, RuntimeError):
    """Raised when executing a remote job or command on Colab fails."""
    pass


class DriveNotMountedError(ColabSessionError, RuntimeError):
    """Raised when an operation requires Google Drive but Drive is not mounted."""
    pass


class BackupError(ColabSessionError, RuntimeError):
    """Raised when backup creation or workspace restoration fails."""
    pass


class RemoteTreeError(ColabSessionError, RuntimeError):
    """Raised when remote directory tree inspection fails."""
    pass
