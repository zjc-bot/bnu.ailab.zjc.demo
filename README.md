# D:/MySQL — 项目速查

> 面向北师大 AI Lab 的 Flask Web 系统集合，部署于阿里云 ECS，MySQL 8.0 后端。
> **架构与决策的唯一事实来源是 [`PROJECT_CHARTER.md`](PROJECT_CHARTER.md)**，本文只做导航、操作红线与上手，冲突时以总纲为准。
> 最后核对：2026-11-19。

---

## 1. 一分钟了解

目录名 `D:/MySQL` 只表示"与 MySQL 相关"，**不是 MySQL 源码**。业务域：

| 目录 | 是什么 | 状态 |
|---|---|---|
| `webapp/` | 学生信息管理（CRUD + 统计） | 稳定，仅做安全修复 |
| `register/` | 注册与社区：实名注册、好友 IM、小鲸对话、管理后台、五子棋对战 | 主演进主体 |
| `neko-world-complete-starter/` | 独立的 AI companion starter（自带 README / `.env.example`） | 参考项目，勿混改 |
| `sql/` `scripts/` `backup/` | 建表/导入脚本、ECS 运维工具、密钥与数据备份 | 支撑 |

**技术栈**：Python 3.13 · Flask 3.0.3 · PyMySQL 1.1.1 · gunicorn 22.0.0（单 worker）· 阿里云 ECS · Socket.IO 4.8.1。

### 当前安全姿态（重要）

- 域名已购买，但**尚未 ICP 备案**；项目**不公网开放**——这是刻意保持的安全姿态，不要提前开放端口。
- 访问**只通过 SSH 隧道**；ECS 安全组仅放行 22 端口。
- `register/deploy/bnuailab.conf` 是**备案后公网化的预置模板（未启用）**；其中的 `listen 80`、XFF 覆盖、`/socket.io` Upgrade 等配置当前不生效。
- 下方 §7 的"公网化前置清单"在备案完成前**都不需要做，也不要提前做**。

各子系统的详细说明见 `webapp/README.md`（安全设计、部署、运维命令齐全）。

---

## 2. 怎么访问

双击项目根目录下的批处理文件，它会自动建立 SSH 隧道并打开浏览器：

| 入口 | 本地地址 | 说明 |
|---|---|---|
| `打开学生管理.bat` | `http://127.0.0.1:8080` | 学生信息管理 |
| `打开注册系统.bat` | `http://127.0.0.1:8082/register` | 注册与社区（本地 8082 → 服务器 8081），含 `/games` 对战大厅 |

关闭窗口即断开隧道、页面失效。手动等价命令：

```bash
ssh -N -L 8080:127.0.0.1:8080 root@47.118.28.10   # 学生管理
ssh -N -L 8082:127.0.0.1:8081 root@47.118.28.10   # 注册系统
```

前提：本机 SSH 私钥可用，服务器安全组仅放行 22。

---

## 3. 目录地图

```
D:/MySQL/
├── PROJECT_CHARTER.md      总纲（唯一事实来源，先读这个）
├── README.md               本文件：5 分钟速查
├── webapp/                 学生信息管理  → 详见 webapp/README.md
├── register/               注册与社区（演进主体）
│   ├── app.py              路由入口（约 1494 行）
│   ├── db.py               数据访问层（约 880 行）
│   ├── admin.py            管理后台蓝图（约 609 行）
│   ├── schema*.sql         9 个分模块脚本（含 2 个幂等迁移）
│   ├── games/              对战子系统：Socket.IO 事件 + 房间 + 服务端规则
│   ├── tests/              4 个测试文件，32 项 pytest
│   ├── templates/          Jinja2 模板（home.html 等）
│   ├── static/             JS/CSS；im.js 为当前 IM 入口
│   └── deploy/             ECS 部署脚本（全量 / 增量 / nginx 模板）
├── sql/                    数据脚本（含真实学生数据，归档后不再改）
├── scripts/                Windows 本地运维（ECS 探针等）
├── backup/                 密钥与备份（含敏感文件，禁止外传）
├── _ref/                   设计参考素材（当前为空）
└── 打开*.bat               SSH 隧道入口
```

**准入规则**：新功能进 `register/`；游戏代码只进 `register/games/`；禁止新建 `temp/`、`new/`、`copy/` 等无语义目录。详见总纲 §4。

---

## 4. 当前状态

### 已完成

- **Phase 0 地基**（提交 `476e4a6`）：私钥备份移出到回收站、明文密码改环境变量、`SECRET_KEY` 缺失拒绝启动、schema 全部纳入部署、admin 白名单封堵 XFF 伪造、git 仓库初始化。
- **AI 聊天记录导出**：`/api/chat/export?format=md|json`，小鲸会话头部有下载按钮，可导出全部对话。
- **Phase 2/3 五子棋本地全链路**：Socket.IO 实时通道 + 服务端权威规则引擎 + 邀请/落子/终局/归档 + `/games` 对战大厅；好友对战（PvP）是主线。
- **代码审查修复 + 复审**（2026-11-19）：两轮共修 26 项，含 admin 白名单反代失效、webapp 增删改必失败、base_url SSRF、终局房间复用、AI 失败扣费、未读误标、重置令牌竞态等；32 项测试全过。
- 修复 AI 对话 `add_message` 重名致命 Bug（现已改名 `add_chat_message` / `add_im_message`）。
- 移除浮动桌宠形象，保留小鲸导览员人设与聊天头像。
- **消息页界面改版**：会话/好友两个 Tab 合并为一个联系人列表（小鲸置顶 + 好友申请 + 好友会话）；小鲸聊天区新增**无边界像素蓝天白云场景**——天空渐变从聊天区顶部一路延伸到场景带（颜色精确衔接、无分界线），角色随 AI 回复的情绪标记换表情（happy/sad/angry/surprised/sleep/neutral）。场景纯 CSS 渲染，不依赖图片素材；已用 Playwright 实机截图验证。
- **修复新好友首条消息发不出**：点开无会话好友时幂等建会话（`POST /api/conversations`，仅好友、CSRF 保护），此前 `activeConv=0` 会让首条消息被拦截且丢失输入。
- **用户头像**：上传/裁剪/删除全链路，含 `avatar_url` 列与幂等迁移；用户自助删除、管理员删用户时均清理磁盘文件。
- **游戏骨架链路修复**：邀请即建房（原 `create_room` 只在测试调用）、终局快照含 result、sid 映射支持多标签页。
- **服务端权威校验**：`games/rules/` 五子棋规则层，客户端只提交坐标、棋盘由服务端派生，杜绝伪造棋盘（含和棋判定）。
- **IM 消息交互**：右键引用 / 转发 / 删除（个人视图软删除）+ 多选批量（上限 50），设计见总纲 §9B；41 项测试全过。
- SQL 注入、XSS、CSRF、会话固定、CSV 注入均已防护，安全响应头齐全。

### 进行中 / 待决策

1. **服务器 SSH 密钥轮换**（Phase 0 未完事项）：项目内私钥副本已移走，但服务器上的密钥对尚未轮换，需 hi 拍板后操作。
2. **Phase 2 生产切换**：Socket.IO 本地已完整（含服务端权威校验），但 gevent worker 与 nginx Upgrade 需 hi 拍板后才动服务器。当前同步 worker 下 WebSocket 退化为 HTTP 长轮询（对战仍可用）。**AI 对手、离线邀请、其余游戏规则未实现**；备案且公网化前不必切换，详见总纲 §9 Phase 2。
3. **AI 游戏对手**：方向已定（可选增强，好友对战是主线），设计见总纲 §8.1.1。

### 已知限制

- 项目按**对外产品**标准验收（稳定长跑、可恢复、可监控），不因当前规模小降级；质量门槛见总纲 §10.1。
- 当前 HTTP 明文传输（靠 SSH 隧道加密）。公网化前必须上 HTTPS，不要录入真实个人信息。
- git 仓库已建，无 CI；register 已有 **32 项 pytest**（4 个文件，单元 + Socket.IO 集成），但尚未进流水线。
- 无定时备份；IM 每 2 秒轮询会写访问日志（待优化）。
- gunicorn 单 worker；内存限流不支持多 worker 扩容。

完整风险清单见总纲 §11。

---

## 4A. 操作红线（动手前必读）

这几条踩过坑或会造成不可恢复损失，优先级高于具体操作方式。

| 红线 | 后果 | 正确做法 |
|---|---|---|
| **禁止在已有数据的服务器上重跑 `deploy.py`** | 每次生成新 `SECRET_KEY` 并覆盖 `.env` → 全部 session 失效、已存 BYOK API Key **永久无法解密** | 更新一律用 `deploy_incremental.py`；换 `SECRET_KEY` = 已存密钥报废 |
| **`schema_chat_migrate.sql` 会删数据** | 删除重复的 `friend_request`（每组只留最小 id）再加唯一约束 | 执行前先备份该表；迁移顺序为 `schema.sql` 优先、其余按文件名排序 |
| **头像目录属主必须是 `regweb`** | 全量 `deploy.py` 只做 `chown -R root:root`，之后上传头像会静默失败 | 部署后补 `chown -R regweb:regweb /opt/bnu-register/var` |
| **gunicorn 保持 `--workers 1`** | 限流字典、验证码、登录失败计数、对局房间都在进程内存，加 worker 会全部失效 | 扩容前先迁到 Redis 等外部存储 |
| **改静态文件必须递增模板里的 `?v=N`** | 浏览器继续用缓存旧代码 | 当前值：`style.css?v=9`、`im.css?v=3`、`im.js?v=5`、`game.js?v=2`、`app.js?v=4`、`avatar-crop.js?v=2`；`im.js` 内还硬编码一份鲸鱼头像版本号 |
| **改模板 / CRLF 文件用编辑器逐处改，别用 Python 脚本批量重写** | `newline=''` 会把 CRLF 换成 LF，产生整文件噪音 diff | `home.html`、`app.py` 是 CRLF，需按字节或标记处理 |

### 环境变量与常用命令

**register**：`SECRET_KEY`（必填，缺失拒绝启动）、`DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME`、`SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASS/SMTP_FROM_NAME`、`SITE_URL`（重置邮件链接，默认 `http://127.0.0.1:8082`）、`AI_MODEL`、`AI_BASE_URL`、`AI_API_KEY`、`COOKIE_SECURE`。
**webapp**：`SECRET_KEY`、`COOKIE_SECURE`、`APP_USER`、`APP_PASSWORD_HASH`、`DB_*`。
部署脚本另用 `DEPLOY_HOST`、`MYSQL_PW`、`DB_PW`；SSH key 固定读 `~/.ssh/id_rsa`。

> `register/.gitignore` 为 `.env.example` 留了例外，但仓库里**尚无该文件**；换服务器重建环境时按上表手工建 `.env`。

```bash
# 本地开发（register，端口 8081）
cd D:/MySQL/register && SECRET_KEY=xxx python app.py

# 测试：register 32 项 / webapp 16 项自检（后者不连库）
cd D:/MySQL/register && pytest
python D:/MySQL/webapp/tests/selftest.py

# 部署：全量仅首次建站；日常更新用增量
MYSQL_PW=xxx DB_PW=yyy python register/deploy/deploy.py
MYSQL_PW=xxx python register/deploy/deploy_incremental.py

# 服务与日志
systemctl status bnu-register && journalctl -u bnu-register -f
```

---

## 4B. 公网化前置清单（ICP 备案完成后才做）

备案前**都不需要做，也不要提前开放端口**。备案后若决定开放，按顺序落实：

1. **上 HTTPS**：当前明文传输，不要在 HTTP 下录入真实个人信息。
2. **复核 ProxyFix 信任链**：`x_for=1` 生效的三前提是——① gunicorn 只 bind `127.0.0.1:8081`；② nginx 唯一公网入口，三处 XFF 用 `$remote_addr` **覆盖**（禁止 `$proxy_add_x_forwarded_for` 追加）；③ 中间只有一层代理。前面加 CDN/SLB 必须同步调大 `x_for`，否则 admin 白名单与登录限流静默失效。**"隔离破则白名单破"**，建议叠加 admin 账号 + 二次认证做纵深防御。
3. **彻底修 DNS 重绑定**：`_base_url_safe()` 只在校验时解析一次 DNS，`requests.post` 会重新解析，仍可"校验公网、连接内网"；彻底修需 pin IP（自定义 adapter + Host 头 + server_hostname）。
4. **切原生 WebSocket**（若要真 WS）：`GeventWebSocketWorker -w 1 --timeout 0` + nginx `/socket.io` Upgrade/Connection 头与 3600s 超时。当前同步 worker 下退化为长轮询，对战可用但开销大。
5. **部署前手动备份**：当前无自动备份，增量脚本的前置条件就是"已做代码 + 数据库备份"。
6. **nginx 关键配置**：`/static/` 设 `no-store`、`/avatar/` 设 `max-age=86400`（URL 带随机串）、server_name 精确匹配防 Host 攻击。模板见 `register/deploy/bnuailab.conf`。

---

## 5. 开发约定（摘要）

完整版见总纲 §6、§10。以下是最容易踩的几条：

1. **凭据不落盘**：密钥/密码只从环境变量读，不写进代码或提交。
2. **SECRET_KEY 必须外部注入**：缺失时拒绝启动，不得回退随机值（否则 session 失效、BYOK 密钥损坏）。
3. **SQL 参数化**：一律 `%s` 占位符；排序列走白名单。
4. **删除前先列表说明 → 移入回收站 → 小批量验证**，禁止永久删除。
5. **换行符陷阱**：`register/templates/home.html` 与 `app.py` 为 CRLF，普通文本编辑按 LF 匹配会失败，需按字节或标记处理。
6. **改架构先改总纲**：任何目录、技术选型、模块变更，先在 `PROJECT_CHARTER.md` 记录决策，再动代码。

---

## 6. 路线图与游戏规划

五阶段路线图（严格串行，未完成前阶段不启动下阶段），详见总纲 §9：

```
Phase 0  地基：安全红线 + 部署修复
Phase 1  骨架：配置集中 + 连接池 + pytest
Phase 2  实时通道：Socket.IO + gevent 单 worker
Phase 3  第一款游戏：五子棋
Phase 4  扩展：象棋/国象/UNO + 备份监控
```

**游戏子系统**（总纲 §8）：在 `register/games/` 独立实现，复用现有好友关系、会话、消息与登录态。规则引擎为**服务端自研 Python**（`games/rules/gomoku.py`）；早期调研的 narabe / xiangqi.js / chess.js 等前端引擎已弃用——服务端权威校验要求规则在服务端，前端引擎防不住伪造棋盘。**好友对战（PvP）是主线、默认模式；AI 对战（PvE，小鲸当对手）只是可选增强，不强制每种游戏都做**（详见 §8.1.1）。明确排除 SQLAlchemy 重写、微服务、Docker/K8s。

---

## 7. 需要 hi 拍板的事项

按总纲 §13：

0. ~~AI 对话去留~~ **已定案**：保留 AI，且让小鲸当游戏对手；聊天记录可导出。
1. 是否接受 Phase 0 密钥轮换（会使现有 SSH 连接需重新配置）？
2. 对战邀请：复用 `message` 表加类型，还是独立 `game_invite` 表？暂定复用。
3. ~~初始化 git~~ 已完成。
4. ~~五子棋 AI 陪练~~ **已定案**：AI 对战是可选增强，好友对战是主线；PvP 先做通，AI 对手可延后（见 §8.1.1）。
