#!/bin/bash
# First-boot bootstrap for the ADLC app server (Ubuntu 24.04).
# Rendered by infra/adlc_stack.py, which fills in the double-underscore placeholders.
# Installs nginx + Python + Node, mounts the persistent data volume, installs
# the adlc-deploy script and runs it (retrying until the GitHub deploy key
# has been added to the repository).
set -euxo pipefail
exec > >(tee -a /var/log/adlc-bootstrap.log) 2>&1

REGION="__REGION__"
PARAM_PREFIX="__PARAM_PREFIX__"
REPO="__REPO__"
BRANCH="__BRANCH__"
DATA_VOLUME_ID="__DATA_VOLUME_ID__"
DATA_MOUNT=/srv/adlc-data

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3.12-venv python3-pip git nginx curl unzip
curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
apt-get install -y nodejs

# AWS CLI v2 (reads secrets from SSM Parameter Store)
curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip
unzip -q -o /tmp/awscliv2.zip -d /tmp
/tmp/aws/install --update
rm -rf /tmp/aws /tmp/awscliv2.zip

# --- Persistent data volume (SQLite DB, FAISS index, tiles, uploads) --------
# Attached by Pulumi right after the instance is created, so wait for it.
DEV="/dev/disk/by-id/nvme-Amazon_Elastic_Block_Store_${DATA_VOLUME_ID//-/}"
for _ in $(seq 1 90); do [ -e "$DEV" ] && break; sleep 10; done
[ -e "$DEV" ] || { echo "Data volume $DATA_VOLUME_ID never attached"; exit 1; }
blkid "$DEV" || mkfs.ext4 -L adlc-data "$DEV"   # format only if brand new
mkdir -p "$DATA_MOUNT"
UUID=$(blkid -s UUID -o value "$DEV")
grep -q "$UUID" /etc/fstab || echo "UUID=$UUID $DATA_MOUNT ext4 defaults,nofail 0 2" >> /etc/fstab
mount -a

# --- Service user + GitHub deploy key ---------------------------------------
id adlc || useradd --system --create-home --home-dir /opt/adlc --shell /bin/bash adlc
chmod 755 /opt/adlc   # nginx (www-data) serves frontend/dist from inside it
install -d -m 700 -o adlc -g adlc /opt/adlc/.ssh
aws ssm get-parameter --region "$REGION" --name "$PARAM_PREFIX/github_deploy_key" \
  --with-decryption --query Parameter.Value --output text > /opt/adlc/.ssh/id_ed25519
ssh-keyscan -t ed25519 github.com > /opt/adlc/.ssh/known_hosts
chmod 600 /opt/adlc/.ssh/id_ed25519
chown -R adlc:adlc /opt/adlc/.ssh "$DATA_MOUNT"

cat > /etc/adlc.env <<EOF
REGION=$REGION
PARAM_PREFIX=$PARAM_PREFIX
REPO=$REPO
BRANCH=$BRANCH
DATA_MOUNT=$DATA_MOUNT
EOF

# --- adlc-deploy: pull latest code, refresh .env, install, migrate, restart --
cat > /usr/local/bin/adlc-deploy <<'DEPLOY'
#!/bin/bash
# Deploys the latest commit of $BRANCH. Safe to re-run: sudo adlc-deploy
set -euo pipefail
source /etc/adlc.env
APP_DIR=/opt/adlc/app
as_adlc() { sudo -u adlc -H bash -c "$*"; }

if [ ! -d "$APP_DIR/.git" ]; then
  as_adlc "git clone --branch $BRANCH git@github.com:$REPO.git $APP_DIR"
else
  as_adlc "cd $APP_DIR && git fetch origin $BRANCH && git reset --hard origin/$BRANCH"
fi
ln -sfn "$DATA_MOUNT" "$APP_DIR/data"

# .env from SSM: every parameter under $PARAM_PREFIX/env/ becomes NAME=value
TMP=$(mktemp)
aws ssm get-parameters-by-path --region "$REGION" --path "$PARAM_PREFIX/env/" --with-decryption \
  --query 'Parameters[].[Name,Value]' --output text |
  while IFS=$'\t' read -r name value; do echo "${name##*/}=${value}"; done > "$TMP"
install -o adlc -g adlc -m 600 "$TMP" "$APP_DIR/.env"
rm -f "$TMP"

as_adlc "cd $APP_DIR && { [ -d .venv ] || python3.12 -m venv .venv; } && .venv/bin/pip install -q --upgrade pip && .venv/bin/pip install -q -r backend/requirements.txt"
as_adlc "cd $APP_DIR/frontend && npm ci --no-audit --no-fund && npm run build"

# Single-writer SQLite: stop the backend while migrations run.
systemctl stop adlc-backend || true
as_adlc "cd $APP_DIR/backend && ../.venv/bin/alembic upgrade head"
systemctl start adlc-backend
systemctl reload nginx
echo "ADLC deployed: $(as_adlc "cd $APP_DIR && git log -1 --format='%h %s'")"
DEPLOY
chmod 755 /usr/local/bin/adlc-deploy

# --- Backend service (one worker: single-writer SQLite + in-process FAISS) --
cat > /etc/systemd/system/adlc-backend.service <<'EOF'
[Unit]
Description=ADLC backend (FastAPI)
After=network-online.target
Wants=network-online.target
RequiresMountsFor=/srv/adlc-data

[Service]
User=adlc
WorkingDirectory=/opt/adlc/app
ExecStart=/opt/adlc/app/.venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8080 --workers 1 --proxy-headers
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable adlc-backend

# --- nginx: static frontend + /api/ proxy (prefix stripped, like Vite dev) --
cat > /etc/nginx/sites-available/adlc <<'EOF'
server {
    listen 80 default_server;
    server_name _;
    client_max_body_size 100m;

    root /opt/adlc/app/frontend/dist;
    index index.html;

    location / {
        try_files $uri /index.html;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8080/;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto;
    }
}
EOF
ln -sfn /etc/nginx/sites-available/adlc /etc/nginx/sites-enabled/adlc
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable nginx
systemctl restart nginx

# --- First deploy. Retries for up to 2 hours: the clone fails until the
# deploy key (stack output githubDeployPublicKey) is added on GitHub.
set +e
for attempt in $(seq 1 120); do
  if /usr/local/bin/adlc-deploy; then
    echo "First deploy succeeded on attempt $attempt"
    exit 0
  fi
  echo "Deploy attempt $attempt failed - has the deploy key been added on GitHub? Retrying in 60s"
  sleep 60
done
echo "First deploy never succeeded. Fix the cause, then run: sudo adlc-deploy"
