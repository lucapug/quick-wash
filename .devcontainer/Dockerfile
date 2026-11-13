FROM mcr.microsoft.com/devcontainers/typescript-node:1-20-bookworm

# Base della factory V1: node (immagine base + feature), python3, gh CLI.
# Gli esecutori (opencode, pi, prime-agent) NON si installano qui ma in
# scripts/setup-executors.sh al postCreate: i runtime degli agenti cambiano
# ritmo molto piu' veloce della cache delle immagini.
# Rimossa la toolchain DSH (V0): la factory V1 usa opencode/pi/prime-agent.

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    curl \
    git \
    tar \
    jq \
    ca-certificates \
    gnupg \
    && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
    && apt-get update \
    && apt-get install -y gh \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

USER node
WORKDIR /workspace

# Autostart runner al boot del container (approvato utente 13/11, checkpoint
# §12.4): ENTRYPOINT detached/idempotente, skip sicuro se runner/.env assenti,
# execa il CMD originale — la topologia del container non cambia.
COPY .devcontainer/scripts/autostart-runner.sh /usr/local/bin/autostart-runner.sh
ENTRYPOINT ["sh", "/usr/local/bin/autostart-runner.sh"]

CMD ["sleep", "infinity"]
