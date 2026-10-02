#!/bin/sh
set -e

# Setup SSH directory and ensure proper permissions
mkdir -p /root/.ssh
chmod 700 /root/.ssh 2>/dev/null || true

# Auto-generate ed25519 SSH key if not present
if [ ! -f /root/.ssh/id_ed25519 ]; then
    echo "[Colab-SSH] Generating default SSH key (/root/.ssh/id_ed25519)..."
    ssh-keygen -t ed25519 -N "" -f /root/.ssh/id_ed25519 -C "colab-ssh-docker" >/dev/null 2>&1 || true
fi

# Fix permissions on SSH keys if writable
chmod 600 /root/.ssh/id_* 2>/dev/null || true
chmod 644 /root/.ssh/*.pub 2>/dev/null || true

# Ensure config directories exist
mkdir -p /root/.config/colab-cli /root/.config/colab-ssh/logs /root/.config/colab-ssh/ssh

# Display Colab login warning if config is not yet mounted/logged in
if [ ! -f /root/.config/colab-cli/sessions.json ]; then
    if [ "$1" = "colab-ssh-server" ] || [ "$1" = "colab-ssh" ]; then
        echo "[Colab-SSH] Notice: Colab CLI not yet configured. Run 'colab login' if sessions fail to provision."
    fi
fi

exec "$@"
