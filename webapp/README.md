# 学生信息管理 Web 应用

基于 Flask + MySQL 的 CRUD 管理页。当前生产仅通过 SSH 隧道访问，不直接面向公网；按最小权限原则设计。

> **部署红线（2026-11-27 复审补充）**：已有服务器仍禁止重跑 `deploy/deploy.py` 或 `deploy/install.sh`。两者现已改为空环境初始化：写操作前只读预检，发现既有应用、`.env`、register/webapp 服务、自定义 Nginx 站点、系统用户或 `studentapp` 数据库账号即非零熔断，且不支持 `--force`。补丁不会轮换共享数据库密码、重置 register `SECRET_KEY`、修改 UFW 或回显凭据；Nginx 模板只绑定回环 80。日常更新仍须使用经审核的增量流程。

## 目录结构

```
webapp/
├── app.py                        路由、认证、CSRF、限流、安全响应头
├── db.py                         数据访问，全部参数化查询
├── requirements.txt
├── templates/
│   ├── login.html                登录页
│   └── index.html                管理页
├── static/
│   ├── style.css
│   └── app.js                    前端逻辑（无内联脚本，符合 CSP）
├── deploy/
│   ├── deploy.py                 一键部署脚本（本地执行）
│   ├── install.sh                服务器端安装脚本
│   ├── student-web.service       systemd 单元（含沙箱加固）
│   ├── nginx-bt-student-web.conf 宝塔面板 nginx 配置
│   ├── nginx-student-web.conf    标准 nginx 配置
│   └── create_app_user.sql       最小权限数据库账号
└── tests/
    └── selftest.py               本地自测（不连数据库）
```

## 访问方式：SSH 隧道（当前配置）

公网 80 已关闭，应用只监听回环，必须通过 SSH 隧道访问：

```
本地 8080  ──SSH──▶  服务器 127.0.0.1:80 (nginx) ──▶ 127.0.0.1:8080 (gunicorn)
```

双击 `D:\MySQL\打开学生管理.bat`，它会建立隧道并自动打开浏览器。
关闭窗口即断开。手动等价命令：

```bash
ssh -N -L 8080:127.0.0.1:80 root@47.118.28.10
```

好处：公网只暴露 22 一个端口；传输全程 SSH 加密，密码不再明文；不需要域名和证书。

## 端口与暴露面

| 组件 | 监听 | 是否对公网 |
|---|---|---|
| nginx | `127.0.0.1:80` | 否，仅回环 |
| gunicorn | `127.0.0.1:8080` | 否，仅回环 |
| MySQL | `127.0.0.1:3306` / `33060` | 否，仅回环 |
| sshd | `0.0.0.0:22` | 是（仅密钥认证 + fail2ban） |

安全组只需放行 **22**，80 / 8080 / 3306 一律关闭。

如需恢复公网访问，必须先配置受信任 HTTPS 证书、443 监听与 `COOKIE_SECURE=1`，再经单独授权调整安全组；不得只把 `listen 127.0.0.1:80` 改回公网 `listen 80`。


## 安全设计

### 1. 数据库权限

Web 应用不使用 root，而是专用账号 `studentapp@127.0.0.1`：

```
GRANT SELECT, INSERT, UPDATE, DELETE ON school.student
```

- 只覆盖一张表，只有四个 DML 权限
- 无 `DROP` / `ALTER` / `CREATE` / `GRANT` / `FILE` / `SUPER`
- 含义：即使应用被完全攻破，攻击者也删不掉库、改不了表结构、读不到服务器文件
- `MAX_USER_CONNECTIONS 20`，防止应用异常时耗尽数据库连接

### 2. 进程权限

- 应用以 `studentweb` 系统用户运行：`--system --no-create-home --shell /usr/sbin/nologin`，无法登录
- 代码目录属主 root，应用只读，被入侵后无法篡改自身代码
- `.env`（含数据库密码）权限 600，属主 studentweb

### 3. systemd 沙箱

`student-web.service` 中启用：`NoNewPrivileges`、`PrivateTmp`、`PrivateDevices`、
`ProtectSystem=strict`、`ProtectHome`、`RestrictAddressFamilies`、`SystemCallFilter`、
`CapabilityBoundingSet=`（清空所有 capability）。

效果：即使进程被拿下，也无法提权、无法写系统目录、无法碰其他进程数据。

### 4. 应用层

| 威胁 | 措施 |
|---|---|
| SQL 注入 | 全部参数化查询；排序字段走 `SORTABLE` 白名单；`LIKE` 通配符转义 |
| XSS | Jinja2 自动转义；前端全部用 `textContent`，不拼 `innerHTML`；CSP 禁内联脚本 |
| CSRF | 会话内一次性 token，写操作校验，`hmac.compare_digest` 常量时间比较 |
| 暴力破解 | 同 IP 5 次失败锁定 5 分钟；Nginx 侧限制并发。两套 Nginx 模板全部用 `$remote_addr` 覆盖 XFF，避免应用层来源 IP 塌缩；生产模板已同步并完成 `nginx -t`、监听与 HTTP 验收 |
| 会话固定 | 登录成功后 `session.clear()` 重新签发 |
| 点击劫持 | `X-Frame-Options: DENY` + `frame-ancestors 'none'` |
| 信息泄露 | 全局异常处理不回显堆栈；隐藏 `X-Powered-By` / `server_tokens off` |
| 请求放大 | `MAX_CONTENT_LENGTH=256KB`，nginx `client_max_body_size 256k` |

### 6. 代理客户端 IP：已修复并同步生产

原 `deploy/nginx-bt-student-web.conf` 使用 `X-Forwarded-For $proxy_add_x_forwarded_for` 追加值，配合 `ProxyFix(x_for=1)` 会取到 Nginx 自身的 `127.0.0.1`，使登录失败计数成为全局限流。

- 2026-11-27 两套 Nginx 模板的全部反代位置已改用 `$remote_addr` **覆盖** XFF；
- Gunicorn 继续只绑定 `127.0.0.1:8080`，代理链仍只有一层；
- 生产 Nginx 已与本地加固模板逐字一致，`nginx -t`、回环监听、登录页与 API 鉴权响应均验收通过。

### 7. 密码存储

登录密码用 Werkzeug `scrypt`（N=32768, r=8, p=1）哈希，不存明文。

修改密码：

```bash
/opt/student-web/venv/bin/python -c \
  "from werkzeug.security import generate_password_hash as g; print(g('新密码'))"
```

把输出替换 `.env` 里的 `APP_PASSWORD_HASH`，然后 `systemctl restart student-web`。

## 运维命令

```bash
systemctl status student-web          # 状态
systemctl restart student-web         # 重启
journalctl -u student-web -n 50 -f    # 实时日志
tail -f /www/wwwlogs/student-web.log  # 访问日志（宝塔环境）
```

## 已知限制

**当前公网未开放，HTTP 明文仅存在于 SSH 隧道内部。** 登录密码和会话 Cookie 不会以明文经过公网链路；若以后要恢复公网访问，必须先配置受信任的 HTTPS 证书，不能直接按初始化脚本开放 80。

遇到以下任一情况应尽快补齐 HTTPS 与公网化安全整改：

- 要长期直接公网使用这套系统
- 要录入真实学生数据（涉及个人信息保护）
- 多人直接从公网访问

公网化前还必须确认安全组、Nginx 回环监听、Cookie `Secure` 与代理信任链。**2026-11-27 本地 `python webapp/tests/selftest.py` 为 51 通过 / 0 失败**，覆盖 XFF、回环监听、预检熔断和部署验收失败路径；生产已同步应用与 Nginx 加固配置，并完成 `nginx -t`、服务、监听、HTTP 响应与 `.env` 哈希验收。未执行空环境初始化安装。
