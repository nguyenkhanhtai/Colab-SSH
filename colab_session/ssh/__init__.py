"""SSH configuration and proxying module."""
from colab_session.ssh.config import (
    CONFIG_HOME,
    SSHConfigManager,
    SSHNaming,
    alias_for,
    config_for,
    configure,
    install,
    reconcile,
    remove,
)
from colab_session.ssh.proxy import (
    SessionProxyValidator,
    SSHProxyCommandBuilder,
    command as proxy_command,
    validate as validate_proxy,
)

__all__ = [
    "CONFIG_HOME",
    "SSHConfigManager",
    "SSHNaming",
    "SessionProxyValidator",
    "SSHProxyCommandBuilder",
    "alias_for",
    "config_for",
    "configure",
    "install",
    "reconcile",
    "remove",
    "proxy_command",
    "validate_proxy",
]

