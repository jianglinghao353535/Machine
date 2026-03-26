#!/usr/bin/env bash
set -e

APP_DIR="/opt/factory-parts"
PYTHON_BIN="python3"
VENV_DIR="$APP_DIR/.venv"
SERVICE_FILE="/etc/systemd/system/factory-parts.service"
DEPLOY_USER="${SUDO_USER:-$USER}"

sudo mkdir -p "$APP_DIR"
sudo cp -r . "$APP_DIR"
sudo chown -R "$DEPLOY_USER":"$DEPLOY_USER" "$APP_DIR"

cd "$APP_DIR"
$PYTHON_BIN -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"
pip install --upgrade pip
pip install -r requirements.txt

if [ ! -f .env ]; then
  cat > .env << 'EOF'
SECRET_KEY=change-this-to-a-long-random-string
FLASK_DEBUG=0
SESSION_COOKIE_SECURE=0
PORT=5000
# DATABASE_URL=sqlite:////opt/factory-parts/factory.db
EOF
fi

sudo bash -c "cat > $SERVICE_FILE" << 'EOF'
[Unit]
Description=Factory Parts Flask Service
After=network.target

[Service]
Type=simple
User=__DEPLOY_USER__
WorkingDirectory=/opt/factory-parts
EnvironmentFile=/opt/factory-parts/.env
ExecStart=/opt/factory-parts/.venv/bin/gunicorn -w 2 -b 0.0.0.0:5000 wsgi:application
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo sed -i "s/__DEPLOY_USER__/$DEPLOY_USER/g" "$SERVICE_FILE"

sudo systemctl daemon-reload
sudo systemctl enable factory-parts
sudo systemctl restart factory-parts
sudo systemctl status factory-parts --no-pager

echo "部署完成：服务名 factory-parts，端口 5000"
