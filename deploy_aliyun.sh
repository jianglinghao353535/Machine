#!/usr/bin/env bash
# 在阿里云 ECS Ubuntu 22.04 上执行此脚本完成完整部署
set -e
APP_DIR="/opt/factory-parts"
NGINX_CONF="/etc/nginx/sites-available/factory-parts"

echo "===== 1. 安装基础依赖 ====="
apt update -y
apt install -y git python3 python3-venv python3-pip nginx

echo "===== 2. 拉取项目代码 ====="
if [ -d "$APP_DIR/.git" ]; then
    cd "$APP_DIR" && git pull origin main
else
    rm -rf "$APP_DIR"
    git clone https://github.com/jianglinghao353535/Machine.git "$APP_DIR"
fi

echo "===== 3. 安装Python依赖 ====="
cd "$APP_DIR"
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q

echo "===== 4. 写入环境变量 ====="
if [ ! -f "$APP_DIR/.env" ]; then
cat > "$APP_DIR/.env" << 'EOF'
SECRET_KEY=change-this-to-a-long-random-string-for-production
FLASK_DEBUG=0
SESSION_COOKIE_SECURE=0
PORT=5000
EOF
fi

echo "===== 5. 初始化数据库 ====="
cd "$APP_DIR"
source .venv/bin/activate
python3 -c "from app import app, init_db; init_db(); print('数据库OK')"

echo "===== 6. 配置 systemd 服务 ====="
DEPLOY_USER="${SUDO_USER:-$USER}"
cat > /etc/systemd/system/factory-parts.service << EOF
[Unit]
Description=Factory Parts Flask Service
After=network.target

[Service]
Type=simple
User=$DEPLOY_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/.venv/bin/gunicorn -w 2 -b 127.0.0.1:5000 wsgi:application
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable factory-parts
systemctl restart factory-parts

echo "===== 7. 配置 Nginx 反向代理 ====="
cat > "$NGINX_CONF" << 'EOF'
server {
    listen 80;
    server_name 47.103.214.140;
    client_max_body_size 50M;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
        proxy_connect_timeout 10s;
    }
}
EOF

ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/factory-parts
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl restart nginx && systemctl enable nginx

echo ""
echo "============================================"
echo "  部署完成！"
echo "  访问地址: http://47.103.214.140"
echo "  默认账号: admin / admin123"
echo "  查看服务: systemctl status factory-parts"
echo "============================================"
