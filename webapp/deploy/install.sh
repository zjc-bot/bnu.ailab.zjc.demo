#!/usr/bin/env bash
# ============================================================
# 学生信息管理 Web 应用 —— 部署脚本（Ubuntu 22.04 / root 执行）
#
# 仅用于确认过的空环境；已有部署配置即熔断，不提供 --force 绕过。
# 凭据由受保护的环境变量传入，不回显、不写命令行：
#   MYSQL_PW       MySQL root 密码（预检并创建数据库专用账号）
#   DB_PASSWORD    数据库专用账号密码
#   WEB_PASSWORD   网页登录密码
# 可选环境变量：
#   WEB_USER       登录用户名，默认 admin
# ============================================================
set -euo pipefail
set +x

APP_DIR=/opt/student-web
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ $EUID -ne 0 ]]; then
  echo "请用 root 执行" >&2
  exit 1
fi

if [[ $# -gt 0 ]]; then
  echo "本脚本不支持 --force；只允许在确认过的空环境部署。" >&2
  exit 1
fi

echo "==> 0/8 只读预检（任何写操作前熔断）"
existing=()
for path in \
  /opt/student-web /opt/student-web/.env \
  /opt/bnu-register /opt/bnu-register/.env \
  /etc/systemd/system/student-web.service \
  /etc/systemd/system/student-web.service.d \
  /etc/systemd/system/bnu-register.service \
  /etc/systemd/system/bnu-register.service.d \
  /lib/systemd/system/student-web.service \
  /lib/systemd/system/bnu-register.service; do
  if [[ -e "$path" || -L "$path" ]]; then
    existing+=("$path")
  fi
done
for path in /etc/nginx/conf.d/*.conf /etc/nginx/sites-enabled/* \
  /etc/nginx/sites-available/* /www/server/panel/vhost/nginx/*.conf; do
  case "$path" in
    /etc/nginx/sites-enabled/default|/etc/nginx/sites-available/default) continue ;;
  esac
  if [[ -e "$path" || -L "$path" ]]; then
    existing+=("$path")
  fi
done
for user in studentweb regweb; do
  if id -u "$user" >/dev/null 2>&1; then
    existing+=("system user: $user")
  fi
done

if [[ ${#existing[@]} -gt 0 ]]; then
  echo "熔断：检测到已有部署配置，拒绝破坏性初始化：" >&2
  printf '  - %s\n' "${existing[@]}" >&2
  echo "请对现有环境使用经审核的增量部署；不会轮换共享密码、重置 SECRET_KEY、覆盖 Nginx 或修改防火墙。" >&2
  exit 1
fi

MYSQL_PW="${MYSQL_PW:?必须提供 MYSQL_PW（用于数据库只读预检）}"

if ! db_count=$(MYSQL_PWD="$MYSQL_PW" mysql -uroot -N -B \
  -e "SELECT COUNT(*) FROM mysql.user WHERE User='studentapp'" 2>/dev/null); then
  echo "熔断：无法确认 studentapp 数据库用户状态，拒绝部署。" >&2
  exit 1
fi
if [[ ! "$db_count" =~ ^[0-9]+$ ]] || [[ "$db_count" -gt 0 ]]; then
  echo "熔断：studentapp 数据库用户已存在或状态未知，拒绝轮换共享密码。" >&2
  exit 1
fi

DB_PASSWORD="${DB_PASSWORD:?必须提供 DB_PASSWORD（数据库专用账号密码）}"
WEB_USER="${WEB_USER:-admin}"
WEB_PASSWORD="${WEB_PASSWORD:?必须提供 WEB_PASSWORD（网页登录密码）}"
export -n MYSQL_PW DB_PASSWORD WEB_PASSWORD

echo "==> 1/8 创建最小权限数据库账号 studentapp"
db_pw_sql=${DB_PASSWORD//\\/\\\\}
db_pw_sql=${db_pw_sql//\'/\\\'}
if ! MYSQL_PWD="$MYSQL_PW" mysql -uroot 2>/dev/null <<SQL
CREATE USER 'studentapp'@'127.0.0.1' IDENTIFIED BY '$db_pw_sql';
GRANT SELECT, INSERT, UPDATE, DELETE ON school.student TO 'studentapp'@'127.0.0.1';
ALTER USER 'studentapp'@'127.0.0.1' WITH MAX_USER_CONNECTIONS 20;
FLUSH PRIVILEGES;
SQL
then
  echo "熔断：studentapp 初始化失败，拒绝继续（未回显凭据）。" >&2
  exit 1
fi
unset db_pw_sql MYSQL_PW

echo "==> 2/8 创建专用系统用户（不可登录、无家目录）"
if ! id -u studentweb >/dev/null 2>&1; then
  useradd --system --no-create-home --shell /usr/sbin/nologin studentweb
  echo "    已创建 studentweb"
else
  echo "    studentweb 已存在，跳过"
fi

echo "==> 3/8 复制代码到 $APP_DIR（root 所有，应用只读）"
mkdir -p "$APP_DIR"
cp -r "$SRC_DIR/app.py" "$SRC_DIR/db.py" "$SRC_DIR/requirements.txt" "$APP_DIR/"
rm -rf "$APP_DIR/templates" "$APP_DIR/static"
cp -r "$SRC_DIR/templates" "$SRC_DIR/static" "$APP_DIR/"
chown -R root:root "$APP_DIR"
chmod -R u+rwX,go-w,go+rX "$APP_DIR"
find "$APP_DIR" -type d -exec chmod 755 {} \;

echo "==> 4/8 建立 Python 虚拟环境"
if ! dpkg -s python3-venv >/dev/null 2>&1; then
  apt-get update -qq
  apt-get install -y -qq python3-venv python3-pip
fi
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install -q --upgrade pip
"$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"
echo "    依赖安装完成"

echo "==> 5/8 生成 .env（权限 600，属主 studentweb）"
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

echo "==> 6/8 安装 systemd 服务"
install -m 644 "$SRC_DIR/deploy/student-web.service" /etc/systemd/system/student-web.service
systemctl daemon-reload
systemctl enable --now student-web >/dev/null
sleep 2
systemctl is-active --quiet student-web && echo "    服务已启动" || {
  echo "    启动失败，请查看：journalctl -u student-web -n 40 --no-pager"
  exit 1
}

echo "==> 7/8 配置 nginx 反向代理"
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
  echo "    nginx 配置检查失败，请手动执行 nginx -t 查看" >&2
  exit 1
fi

echo "==> 8/8 本机防火墙（只读，不修改）"
echo "    安装脚本不修改防火墙规则；端口策略由运维人员显式确认。"

echo
echo "=============================="
echo " 部署完成"
echo " 登录用户名：$WEB_USER"
echo " 访问方式：SSH 隧道 http://127.0.0.1:8080（不对公网开放）"
echo "=============================="
echo "提示：本脚本不放行任何公网端口；按当前 SSH 隧道方案保持 80 / 3306 关闭。"
