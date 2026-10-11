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
[ -s deploy/.build-code ] || (LC_ALL=C tr -dc 'a-z0-9' </dev/urandom | head -c 12 > deploy/.build-code)

ENV_FILE="$(mktemp)"
{
  grep -E '^(AZURE_OPENAI_BASE_URL|COURSEBOOK_[A-Z_]*MODEL)=' .env
  echo "AZURE_OPENAI_AUTH=managed-identity"
  echo "COURSEBOOK_BUILD_CODE=$(cat deploy/.build-code)"
} > "$ENV_FILE"

$SSH 'sudo mkdir -p /opt/coursebook && sudo chown azureuser: /opt/coursebook'
rsync -az --delete -e "ssh -i $KEY" \
  --exclude .venv --exclude .env --exclude 'deploy/.build-code' --exclude __pycache__ --exclude .pytest_cache \
  --exclude 'data/reference/repo' --exclude 'workspaces/' --exclude tmp \
  ./ "azureuser@$IP:/opt/coursebook/"
scp -q -i "$KEY" "$ENV_FILE" "azureuser@$IP:/tmp/coursebook.env" && rm -f "$ENV_FILE"
$SSH 'sudo install -m 600 -o azureuser /tmp/coursebook.env /etc/coursebook.env && rm /tmp/coursebook.env'
$SSH "bash /opt/coursebook/deploy/setup-vm.sh $HOST"
echo "Backend: https://$HOST"
