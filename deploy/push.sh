#!/usr/bin/env bash
# Copy the code and the built book to the VM, write its environment, (re)run setup.
# The Azure key never leaves this Mac: the VM signs in to Azure OpenAI with its managed identity.
# Usage: bash deploy/push.sh            (from the repo root)
set -euo pipefail
IP="${COURSEBOOK_VM_IP:-20.230.94.107}"
HOST="${IP//./-}.sslip.io"
KEY="$HOME/.ssh/coursebook_vm"
SSH="ssh -i $KEY -o StrictHostKeyChecking=accept-new azureuser@$IP"

# access code for starting builds on the public site (kept only in this file and on the VM)
[ -s deploy/.build-code ] || openssl rand -hex 6 > deploy/.build-code

ENV_FILE="$(mktemp)"
{
  grep -E '^(AZURE_OPENAI_BASE_URL|COURSEBOOK_[A-Z_]*MODEL)=' .env
  echo "AZURE_OPENAI_AUTH=managed-identity"
  echo "COURSEBOOK_BUILD_CODE=$(cat deploy/.build-code)"
  # YouTube blocks cloud servers: caption and playlist requests go through a residential proxy.
  # deploy/.proxy.env (never committed) holds WEBSHARE_PROXY_USERNAME / WEBSHARE_PROXY_PASSWORD.
  if [ -f deploy/.proxy.env ]; then grep -E '^(WEBSHARE_PROXY_USERNAME|WEBSHARE_PROXY_PASSWORD|COURSEBOOK_PROXY_URL)=' deploy/.proxy.env || true; fi
} > "$ENV_FILE"
# YouTube asks cloud servers to sign in: a cookies.txt from a spare YouTube account (never committed) unlocks captions.
if [ -s deploy/.youtube-cookies.txt ]; then echo "COURSEBOOK_YT_COOKIES=/home/azureuser/.coursebook/youtube-cookies.txt" >> "$ENV_FILE"
else echo "warning: no deploy/.youtube-cookies.txt; new builds on the server will be blocked by YouTube at 'Collect captions'" >&2; fi

$SSH 'sudo mkdir -p /opt/coursebook && sudo chown azureuser: /opt/coursebook'
rsync -az --delete -e "ssh -i $KEY" \
  --exclude .venv --exclude .env --exclude 'deploy/.build-code' --exclude __pycache__ --exclude .pytest_cache \
  --exclude 'data/reference/repo' --exclude 'workspaces/' --exclude 'deploy/showcase' --exclude 'deploy/.proxy.env' --exclude 'deploy/.youtube-cookies.txt' --exclude tmp \
  ./ "azureuser@$IP:/opt/coursebook/"
scp -q -i "$KEY" "$ENV_FILE" "azureuser@$IP:/tmp/coursebook.env" && rm -f "$ENV_FILE"
$SSH 'sudo install -m 600 -o azureuser /tmp/coursebook.env /etc/coursebook.env && rm /tmp/coursebook.env'
if [ -s deploy/.youtube-cookies.txt ]; then
  $SSH 'mkdir -p ~/.coursebook && chmod 700 ~/.coursebook'
  scp -q -i "$KEY" deploy/.youtube-cookies.txt "azureuser@$IP:.coursebook/youtube-cookies.txt"
  $SSH 'chmod 600 ~/.coursebook/youtube-cookies.txt'
fi
$SSH "bash /opt/coursebook/deploy/setup-vm.sh $HOST"
echo "Backend: https://$HOST"
