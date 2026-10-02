FROM python:3.12-slim

# Prevent Python bytecode and buffer output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    COLAB_SSH_HOST=0.0.0.0 \
    COLAB_SSH_PORT=6767

# Install system dependencies (SSH client, git, curl, ca-certificates)
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-client \
    git \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy repository files
COPY . /app

# Install project and dependencies
RUN pip install --no-cache-dir -e . && \
    chmod +x /app/entrypoint.sh

# Expose web dashboard port
EXPOSE 6767

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["colab-ssh-server"]
