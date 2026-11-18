import os
import sys

import paramiko

HOST = "47.118.28.10"
USER = "root"
KEY = os.path.expanduser("~/.ssh/id_rsa")


def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    pkey = paramiko.RSAKey.from_private_key_file(KEY)
    c.connect(
        HOST,
        port=22,
        username=USER,
        pkey=pkey,
        timeout=20,
        banner_timeout=30,
        auth_timeout=30,
        allow_agent=False,
        look_for_keys=False,
    )
    return c


def run(c, cmd):
    _, out, err = c.exec_command(cmd, timeout=40)
    o = out.read().decode("utf-8", "replace").strip()
    e = err.read().decode("utf-8", "replace").strip()
    return (o + ("\n" + e if e else "")).strip()


def main():
    try:
        c = connect()
    except Exception as e:
        print("KEY_LOGIN_FAIL:", type(e).__name__, e)
        return 2
    print("KEY_LOGIN_OK")
    print("HOSTNAME:", run(c, "hostname"))
    print("OS:", run(c, "grep -E '^(NAME|VERSION_ID)=' /etc/os-release 2>/dev/null | tr '\\n' ' '"))

    print("SSHD_EFFECTIVE:")
    print(run(c, "sshd -T 2>/dev/null | grep -E '^(pubkeyauthentication|passwordauthentication|permitrootlogin|allowtcpforwarding|allowagentforwarding) '"))

    print("MYSQLD:", run(c, "systemctl is-active mysqld 2>/dev/null"), "/", run(c, "systemctl is-enabled mysqld 2>/dev/null"))
    print("LISTEN:")
    print(run(c, "ss -lntp 2>/dev/null | grep -E ':3306|:33060'"))
    print("MYSQL_VER:", run(c, "mysql --version 2>/dev/null || echo absent"))
    print("DB_VER:", run(c, "mysql -uroot -N -e 'select version()' 2>&1"))
    print("BIND:", run(c, "grep -rhE '^[[:space:]]*bind-address' /etc/my.cnf /etc/mysql/my.cnf /etc/mysql/mysql.conf.d/*.cnf /etc/mysql/conf.d/*.cnf 2>/dev/null | tr '\\n' ' '"))
    print("USERS:")
    print(run(c, "mysql -uroot -N -e \"select user,host,plugin from mysql.user\" 2>&1 | head -20"))
    print("FIREWALL:", run(c, "systemctl is-active firewalld 2>/dev/null; firewall-cmd --list-ports 2>/dev/null | tr '\\n' ' '"))
    c.close()
    return 0


sys.exit(main())
