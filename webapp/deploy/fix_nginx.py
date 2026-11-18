"""修复 nginx 配置并更新应用代码，然后重启验证。"""

import os
import sys

import paramiko

HOST = "47.118.28.10"
USER = "root"
KEY = os.path.expanduser("~/.ssh/id_rsa")

LOCAL = r"D:\MySQL\webapp"


def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(
        HOST,
        port=22,
        username=USER,
        pkey=paramiko.RSAKey.from_private_key_file(KEY),
        timeout=20,
    )
    return c


def run(c, cmd, timeout=120):
    _, out, err = c.exec_command(cmd, timeout=timeout)
    o = out.read().decode("utf-8", "replace")
    e = err.read().decode("utf-8", "replace")
    return (o + e).strip(), out.channel.recv_exit_status()


def step(title, cmd, c, timeout=120):
    print(f"\n== {title}")
    o, rc = run(c, cmd, timeout)
    for line in o.splitlines():
        if line.strip():
            print("   " + line.rstrip())
    print("   rc =", rc)
    return rc


c = connect()
print("SSH 已连接")

print("\n== 上传更新后的 app.py")
sftp = c.open_sftp()
sftp.put(os.path.join(LOCAL, "app.py"), "/opt/student-web/app.py")
sftp.put(
    os.path.join(LOCAL, "deploy", "nginx-student-web.conf"),
    "/tmp/student-web.conf",
)
sftp.put(
    os.path.join(LOCAL, "deploy", "install.sh"),
    "/tmp/install.sh",
)
sftp.close()
print("   完成")

step("修正属主与权限", "chown root:root /opt/student-web/app.py && chmod 644 /opt/student-web/app.py", c)

step("创建 conf.d 并安装限流配置", r"""mkdir -p /etc/nginx/conf.d && cat > /etc/nginx/conf.d/00-limit.conf <<'EOF'
limit_req_zone $binary_remote_addr zone=login_zone:10m rate=10r/m;
limit_req_zone $binary_remote_addr zone=api_zone:10m rate=60r/m;
EOF
echo written""", c)

step(
    "安装站点配置",
    "install -m 644 /tmp/student-web.conf /etc/nginx/conf.d/student-web.conf && echo ok",
    c,
)

step("移除默认站点（软链接）", "rm -f /etc/nginx/sites-enabled/default; ls /etc/nginx/sites-enabled/ 2>/dev/null | wc -l", c)

step("nginx 配置语法检查", "nginx -t 2>&1", c)

step("重启服务", "systemctl restart student-web && sleep 2 && systemctl is-active student-web", c)
step("重载 nginx", "systemctl reload nginx && sleep 1 && systemctl is-active nginx", c)

step("本机验证首页跳转", "curl -s -o /dev/null -w 'code=%{http_code} loc=%{redirect_url} size=%{size_download}\\n' http://127.0.0.1/", c)
step("本机验证登录页", "curl -s -o /dev/null -w 'code=%{http_code} size=%{size_download}\\n' http://127.0.0.1/login", c)
step("登录页内容抽样", "curl -s http://127.0.0.1/login | grep -oE '<title>[^<]*</title>|学生信息管理' | head -3", c)

step("应用连通数据库检查", "journalctl -u student-web -n 5 --no-pager --since '1 min ago'", c)

c.close()
print("\n完成")
