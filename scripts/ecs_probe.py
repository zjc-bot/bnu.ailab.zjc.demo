import os
import sys

import paramiko

HOST = "47.118.28.10"
USER = "root"
PUB = open(os.path.expanduser("~/.ssh/id_rsa.pub")).read().strip()
KEYBODY = PUB.split()[1]


def connect(pwd):
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(
        HOST,
        port=22,
        username=USER,
        password=pwd,
        timeout=20,
        banner_timeout=30,
        auth_timeout=30,
        allow_agent=False,
        look_for_keys=False,
    )
    return c


def run(c, cmd):
    _, out, err = c.exec_command(cmd, timeout=30)
    o = out.read().decode("utf-8", "replace").strip()
    e = err.read().decode("utf-8", "replace").strip()
    return (o + ("\n" + e if e else "")).strip()


def main():
    pwd = sys.argv[1]
    try:
        c = connect(pwd)
    except paramiko.AuthenticationException:
        print("AUTH_FAIL")
        return 2
    except Exception as e:
        print("CONN_FAIL:", type(e).__name__, e)
        return 3

    print("LOGIN_OK")
    print("HOSTNAME:", run(c, "hostname"))

    install = (
        "mkdir -p ~/.ssh && chmod 700 ~/.ssh && touch ~/.ssh/authorized_keys && "
        f"grep -qF '{KEYBODY}' ~/.ssh/authorized_keys || echo '{PUB}' >> ~/.ssh/authorized_keys; "
        "chmod 600 ~/.ssh/authorized_keys; "
        f"grep -cF '{KEYBODY}' ~/.ssh/authorized_keys"
    )
    print("AUTHORIZED_KEYS_COUNT:", run(c, install))

    print("SSHD_CONFIG:")
    print(run(c, "grep -nE '^[[:space:]]*(PubkeyAuthentication|PasswordAuthentication|PermitRootLogin|AllowTcpForwarding)' /etc/ssh/sshd_config /etc/ssh/sshd_config.d/*.conf 2>/dev/null"))

    print("MYSQLD_SERVICE:", run(c, "systemctl is-active mysqld mysql mariadb 2>/dev/null | tr '\\n' ' '"))
    print("MYSQLD_ENABLED:", run(c, "systemctl is-enabled mysqld mysql mariadb 2>/dev/null | tr '\\n' ' '"))

    print("LISTEN_3306:")
    print(run(c, "ss -lntp 2>/dev/null | grep -E ':3306' || echo 'NOT_LISTENING_3306'"))

    print("LISTEN_ANY_MYSQL:")
    print(run(c, "ss -lntp 2>/dev/null | grep -i mysql || echo 'none'"))

    print("MYSQL_VERSION:", run(c, "mysql --version 2>/dev/null || echo 'client_absent'"))

    print("BIND_ADDRESS:")
    print(run(c, "grep -rhE '^[[:space:]]*bind-address' /etc/my.cnf /etc/mysql/ 2>/dev/null || echo 'default(127.0.0.1)'"))

    print("MYSQL_USERS:")
    print(run(c, "mysql -uroot -N -e \"select user,host,plugin from mysql.user\" 2>&1 | head -20"))

    print("OS:", run(c, "cat /etc/os-release 2>/dev/null | grep -E '^(NAME|VERSION_ID)=' | tr '\\n' ' '"))
    print("UPTIME:", run(c, "uptime -p 2>/dev/null"))

    c.close()
    return 0


sys.exit(main())
