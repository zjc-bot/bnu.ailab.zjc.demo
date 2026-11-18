#!/usr/bin/env bash
# ============================================================
# 学生信息管理 Web 应用 —— 部署脚本（Ubuntu 22.04 / root 执行）
#
# 用法：
#   sudo DB_PASSWORD='xxx' WEB_PASSWORD='yyy' bash deploy/install.sh
#
# 可选环境变量：
#   WEB_USER       登录用户名，默认 admin
#   APP_PORT       应用端口，默认 8080（仅监听 127.0.0.1）
# ============================================================
set -euo pipefail

APP_DIR=/opt/student-web
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

DB_PASSWORD="${DB_PASSWORD:?必须提供 DB_PASSWORD（数据库专用账号密码）}"
WEB_USER="${WEB_USER:-admin}"
WEB_PASSWORD="${WEB_PASSWORD:?必须提供 WEB_PASSWORD（网页登录密码）}"

if [[ $EUID -ne 0 ]]; then
  echo "请用 root 执行" >&2
  exit 1
fi

echo "==> 1/7 创建专用系统用户（不可登录、无家目录）"
if ! id -u studentweb >/dev/null 2>&1; then
  useradd --system --no-create-home --shell /usr/sbin/nologin studentweb
  echo "    已创建 studentweb"
else
  echo "    studentweb 已存在，跳过"
fi

echo "==> 2/7 复制代码到 $APP_DIR（root 所有，应用只读）"
mkdir -p "$APP_DIR"
cp -r "$SRC_DIR/app.py" "$SRC_DIR/db.py" "$SRC_DIR/requirements.txt" "$APP_DIR/"
rm -rf "$APP_DIR/templates" "$APP_DIR/static"
cp -r "$SRC_DIR/templates" "$SRC_DIR/static" "$APP_DIR/"
chown -R root:root "$APP_DIR"
chmod -R u+rwX,go-w,go+rX "$APP_DIR"
find "$APP_DIR" -type d -exec chmod 755 {} \;

echo "==> 3/7 建立 Python 虚拟环境"
if ! dpkg -s python3-venv >/dev/null 2>&1; then
  apt-get update -qq
  apt-get install -y -qq python3-venv python3-pip
fi
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install -q --upgrade pip
"$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"
echo "    依赖安装完成"

echo "==> 4/7 生成 .env（权限 600，属主 studentweb）"
SECRET=$(openssl rand -hex 32)
HASH=$(WEB_PASSWORD="$WEB_PASSWORD" "$APP_DIR/venv/bin/python" -c \
  "import os;from werkzeug.security import generate_password_hash as g;print(g(os.environ['WEB_PASSWORD']))")

umask 077
cat > "$APP_DIR/.env" <<ENVEOF
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=studentapp
DB_PASSWORD=$DB_PASSWORD
DB_NAME=school
SECRET_KEY=$SECRET
APP_USER=$WEB_USER
APP_PASSWORD_HASH=$HASH
COOKIE_SECURE=0
ENVEOF
chown studentweb:studentweb "$APP_DIR/.env"
chmod 600 "$APP_DIR/.env"

echo "==> 5/7 安装 systemd 服务"
install -m 644 "$SRC_DIR/deploy/student-web.service" /etc/systemd/system/student-web.service
systemctl daemon-reload
systemctl enable --now student-web >/dev/null
sleep 2
systemctl is-active --quiet student-web && echo "    服务已启动" || {
  echo "    启动失败，请查看：journalctl -u student-web -n 40 --no-pager"
  exit 1
}

echo "==> 6/7 配置 nginx 反向代理"
if [ -d /www/server/panel/vhost/nginx ]; then
  echo "    检测到宝塔面板，使用其 vhost 目录"
  install -m 644 "$SRC_DIR/deploy/nginx-bt-student-web.conf" \
    /www/server/panel/vhost/nginx/student-web.conf
else
  if ! command -v nginx >/dev/null 2>&1; then
    apt-get install -y -qq nginx
  fi
  mkdir -p /etc/nginx/conf.d
  cat > /etc/nginx/conf.d/00-limit.conf <<'LIMEOF'
limit_req_zone $binary_remote_addr zone=login_zone:10m rate=10r/m;
limit_req_zone $binary_remote_addr zone=api_zone:10m rate=60r/m;
LIMEOF
  install -m 644 "$SRC_DIR/deploy/nginx-student-web.conf" /etc/nginx/conf.d/student-web.conf
  rm -f /etc/nginx/sites-enabled/default
fi

if nginx -t >/dev/null 2>&1; then
  systemctl reload nginx && echo "    nginx 已重载"
else
  echo "    nginx 配置检查失败，请手动执行 nginx -t 查看"
fi

echo "==> 7/7 本机防火墙（如启用 ufw）"
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
  ufw allow 22/tcp >/dev/null
  ufw allow 80/tcp >/dev/null
  echo "    ufw 已放行 22 / 80"
else
  echo "    ufw 未启用，跳过（依赖阿里云安全组）"
fi

echo
echo "=============================="
echo " 部署完成"
echo " 登录用户名：$WEB_USER"
echo " 访问地址：http://<ECS公网IP>/"
echo "=============================="
echo "提示：仍需在阿里云安全组放行 TCP 80，3306 保持关闭。"
