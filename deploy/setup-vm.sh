#!/usr/bin/env bash
# One-time setup of the Coursebook server on a fresh Ubuntu 24.04 VM (run on the VM as azureuser).
#   - ffmpeg, Chrome (vector diagrams), Quarto + TinyTeX (PDF), uv + Python deps incl. CPU torch (run-code)
#   - systemd service `coursebook` on 127.0.0.1:8800, Caddy in front with automatic HTTPS
# Usage: bash setup-vm.sh <public-hostname>     e.g. 20-230-94-107.sslip.io
set -euo pipefail
HOST="${1:?public hostname, e.g. 20-230-94-107.sslip.io}"
QUARTO_VERSION=1.10.19

sudo apt-get update -q
sudo apt-get install -yq ffmpeg git curl gnupg debian-keyring debian-archive-keyring apt-transport-https

if ! command -v caddy >/dev/null; then
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key | sudo gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  sudo apt-get update -q && sudo apt-get install -yq caddy
fi
if ! command -v google-chrome >/dev/null; then
  curl -fsSLo /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
  sudo apt-get install -yq /tmp/chrome.deb
fi
if ! command -v quarto >/dev/null; then
  curl -fsSLo /tmp/quarto.deb "https://github.com/quarto-dev/quarto-cli/releases/download/v${QUARTO_VERSION}/quarto-${QUARTO_VERSION}-linux-amd64.deb"
  sudo apt-get install -yq /tmp/quarto.deb
fi
quarto install tinytex --no-prompt --quiet || true
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

cd /opt/coursebook
uv sync --locked --group listings

sudo tee /etc/systemd/system/coursebook.service >/dev/null <<UNIT
[Unit]
Description=Coursebook app
After=network-online.target

[Service]
User=azureuser
WorkingDirectory=/opt/coursebook
EnvironmentFile=/etc/coursebook.env
Environment=PATH=/home/azureuser/.local/bin:/home/azureuser/.TinyTeX/bin/x86_64-linux:/usr/local/bin:/usr/bin:/bin
ExecStart=/home/azureuser/.local/bin/uv run --locked --group listings coursebook app --port 8800
Restart=on-failure

[Install]
WantedBy=multi-user.target
UNIT

sudo tee /etc/caddy/Caddyfile >/dev/null <<CADDY
${HOST} {
	encode gzip
	reverse_proxy 127.0.0.1:8800
}
CADDY

sudo systemctl daemon-reload
sudo systemctl enable --now coursebook
sudo systemctl restart coursebook caddy
sleep 3
curl -fsS http://127.0.0.1:8800/api/books/config && echo && echo "Coursebook is up: https://${HOST}"
