#!/bin/bash
# First-boot bootstrap for the ADLC embedding server (AWS Deep Learning Base
# GPU AMI - NVIDIA driver preinstalled). Rendered by infra/adlc_stack.py:
# server.py and requirements.txt from embed_server/ are inlined base64 below,
# so this box never needs access to the private GitHub repo. Changing either
# file replaces the instance on the next `pulumi up` (it holds no data).
set -euxo pipefail
exec > >(tee -a /var/log/adlc-embed-bootstrap.log) 2>&1

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3-venv

id embed || useradd --system --create-home --home-dir /opt/embed --shell /bin/bash embed
install -d -o embed -g embed /opt/embed/app /opt/embed/hf-cache

base64 -d > /opt/embed/app/server.py <<'EOF'
__SERVER_PY_B64__
EOF
base64 -d > /opt/embed/app/requirements.txt <<'EOF'
__REQUIREMENTS_B64__
EOF
chown -R embed:embed /opt/embed/app

sudo -u embed -H bash -c 'cd /opt/embed/app && python3 -m venv .venv && .venv/bin/pip install -q --upgrade pip && .venv/bin/pip install -q -r requirements.txt'

cat > /etc/systemd/system/adlc-embed.service <<'EOF'
[Unit]
Description=ADLC embedding server (Qwen3-VL-Embedding-2B-vdr)
After=network-online.target
Wants=network-online.target

[Service]
User=embed
WorkingDirectory=/opt/embed/app
Environment=HF_HOME=/opt/embed/hf-cache
ExecStart=/opt/embed/app/.venv/bin/uvicorn server:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10
TimeoutStartSec=900

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now adlc-embed
