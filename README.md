# D:/MySQL — 项目速查

> 面向北师大 AI Lab 的 Flask Web 系统集合，部署于阿里云 ECS，MySQL 8.0 后端。
> **项目主线为「idea 社区」**（发布 idea / 收藏讨论 / AI 辅助 / 好友协作 / 公开分享的 idea）；**五子棋已从生产下线，代码本地保留、可回滚**。
> **架构与决策的唯一事实来源是 [`PROJECT_CHARTER.md`](PROJECT_CHARTER.md)**，本文只做导航、操作红线与上手，冲突时以总纲为准。
> 最后核对：2026-11-19。

---

## 1. 一分钟了解

目录名 `D:/MySQL` 只表示"与 MySQL 相关"，**不是 MySQL 源码**。

**项目主线（2026-11-25 起）**：以「idea 社区」为核心——成员发布 idea、收藏/点赞/评论讨论，AI 辅助分类/摘要/去重，点作者加好友私聊协作，公开分享的 idea 在学习分享室（公开分享墙）对外展示；好友 IM 与小鲸 AI 作为底层能力保留。统一以 `idea` 为内容对象，复用现有认证、好友与 AI，不新建独立系统。**Phase 1 进行中，尚未部署**；**五子棋已在生产下线**（代码本地保留，详见总纲 §12 ADR）。完整方案见工作区 `idea-community-architecture.md`。

> **交付原则（2026-11-19）**：安全稳定是底线，同时完成总纲中已明确的核心功能——五子棋 AI 对战、离线邀请、新手引导已落地并完成服务器增量部署核验；后续游戏经 hi 拍板暂缓。不无边界扩张；先本地实现与回归验证，生产变更另行确认。

业务域：

| 目录 | 是什么 | 状态 |
|---|---|---|
| `webapp/` | 学生信息管理（CRUD + 统计） | 稳定，仅做安全修复 |
| `register/` | 注册与社区：实名注册、好友 IM、小鲸对话、管理后台、**idea 社区（进行中）**、学习分享室（公开分享墙）；五子棋已生产下线（代码保留） | 主演进主体；idea 社区 **Phase 1 进行中（未部署）**；学习分享室已于 2026-11-25 增量部署上线 |
| `neko-world-complete-starter/` | 独立的 AI companion starter（自带 README / `.env.example`） | 参考项目，勿混改 |
| `sql/` `scripts/` `backup/` | 建表/导入脚本、ECS 运维工具、密钥与数据备份 | 支撑 |

**技术栈**：Python 3.13（本地 / CI）· **Python 3.10.12（生产 `/opt/bnu-register/venv`）** · Flask 3.0.3 · PyMySQL 1.1.1 · gunicorn 22.0.0（单 worker）· 阿里云 ECS · Socket.IO 4.8.1。

> ⚠️ **本地/CI 与生产解释器版本不一致**：选依赖版本前必须核对生产的 `requires_python` 与 cp310 wheel 是否存在，否则会出现「CI 装得上、生产装不上」。例如 Pillow 13.0.0 要求 `>=3.11`，生产 3.10 无法安装，故 `register/requirements.txt` 固定为 `12.3.0`（3.10 可用的最高版）；详见 §4A。

### 当前安全姿态（重要 · 2026-11-25 更新）

- **ICP 备案已完成**，`bnuailab.tech` 的 A 记录已解析到 `47.118.28.10`。
- **公网化进行中，尚未开放**：ECS 安全组仍仅放行 22 端口，80/443 不通；访问仍只通过 SSH 隧道。不要提前认为站已上线。
- `register/deploy/bnuailab.conf` 是原 HTTP 预置模板（未启用）；HTTPS 版模板见 `register/deploy/bnuailab.conf HTTPS版.template`（含 443、HSTS、Upgrade、XFF 覆盖）。
- **公网化前置清单**（详见工作区 `公网化整改操作手册.md`）：① 申请 SSL 证书并配 443；② 安全组限源 IP 灰度放行 80/443；③ 部署 SSRF pin IP 修复与 admin 二次认证；④ 给管理员配二次认证邮箱；⑤ 本机 DNS 换 114（阿里云 223.5.5.5 对该域解析超时）。
- 代码侧 SSRF pin IP、admin 邮件二次认证已**增量部署到生产**（2026-11-25 13:53，`DEPLOY_EXIT=0`）；备份 → `schema_admin_2fa.sql` 幂等迁移 → 上传 → 重启 → 路由验证全通过，`.env` mtime 未变（`SECRET_KEY` 未重置）、服务 active、错误日志无。管理员 `zjcyyds` 的二次认证邮箱已设为 `151675235@qq.com`（邮件可达性已从服务器实测）。**HTTPS 仍未配置，公网仍未开放**。
- 公网化前不要录入真实个人信息；上线必须走 HTTPS。

各子系统的详细说明见 `webapp/README.md`（安全设计、部署、运维命令齐全）。

---

## 2. 怎么访问

双击项目根目录下的批处理文件，它会自动建立 SSH 隧道并打开浏览器：

| 入口 | 本地地址 | 说明 |
|---|---|---|
| `打开学生管理.bat` | `http://127.0.0.1:8080` | 学生信息管理 |
| `打开注册系统.bat` | `http://127.0.0.1:8082/register` | 注册与社区（本地 8082 → 服务器 8081）；原 `/games` 对战大厅**已下线**（服务器入口禁用，代码本地保留） |
| idea 广场（Phase 1） | `http://127.0.0.1:8082/ideas` | idea 广场，**Phase 1 进行中、尚未部署**（当前访问不可用） |
| 学习分享室（新增） | `http://127.0.0.1:8082/archive` | **学习分享室（公开分享墙，数据与领域头条同源）**，公开可访问；**根路径 `/` 行为不变**（未登录仍跳 `/register`、已登录跳 `/home`） |

双击 `打开注册系统.bat` 后，可在 `http://127.0.0.1:8082/archive` 查看学习分享室（公开分享墙，纸片档案风格；当前 API 因数据库账号无权读新表而降级为静态示例数据）。

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
│   ├── schema*.sql         11 个分模块脚本（含 4 个幂等迁移）
│   ├── games/              对战子系统：Socket.IO 事件 + 房间 + 服务端规则
│   ├── tests/              8 个测试文件，90 项 pytest
│   ├── templates/          Jinja2 模板（home.html 等）
│   │   └── archive.html    研究成果展示页（公开门面，静态示例数据）
│   ├── static/             JS/CSS；im.js 为当前 IM 入口
│   │   ├── archive.css     成果展示页样式（?v=1）
│   │   └── archive.js      成果展示页脚本（?v=1，点击卡片展开详情；优先读 /api/archive.json）
│   ├── archive_api.py      研究成果只读 API 蓝图（GET /api/archive.json）
│   ├── archive_data.py     研究成果数据层（无 DB 凭据时返回空，前端自动降级静态数据）
│   └── schema_archive.sql  新增表 research_achievement（幂等，可单独执行，不影响现有表）
│   └── deploy/             ECS 部署脚本（全量 / 增量 / nginx 模板）
├── sql/                    数据脚本（含真实学生数据，归档后不再改）
├── scripts/                Windows 本地运维（ECS 探针等）
├── backup/                 密钥与备份（含敏感文件，禁止外传）
├── _ref/                   评审与整改方案归档（只读参考，不参与运行时）
│   ├── 架构评审报告.md       2026-11-25 架构评审：问题分级与改进建议
│   ├── 域名访问诊断报告.md    bnuailab.tech 打不开的根因与安全隐患
│   └── 公网化整改操作手册.md  证书 / 安全组 / nginx / SSRF / 二次认证 操作清单
└── 打开*.bat               SSH 隧道入口
```

> `_ref/` 内的方案文档是**参考件，不是事实来源**；架构决策仍以 `PROJECT_CHARTER.md` 为准，方案落地状态以源码与 pytest 为准。

**准入规则**：新功能进 `register/`；游戏代码只进 `register/games/`；禁止新建 `temp/`、`new/`、`copy/` 等无语义目录。详见总纲 §4。

---

## 4. 当前状态

### 已完成

> **五子棋说明（2026-11-25 决策，待执行）**：以下五子棋相关条目均为**历史交付记录**——按 hi 拍板，五子棋"没啥用"，**只在服务器下线**（先备份代码，再禁用 `/games` 路由与 Socket.IO 事件注册、导航去掉对战入口），**代码完整保留在本地仓库、可随时恢复**，不物理删除 `games/` 目录。以总纲 §12 ADR 为准。

- **Phase 0 地基**（提交 `476e4a6`）：私钥备份移出到回收站、明文密码改环境变量、`SECRET_KEY` 缺失拒绝启动、schema 全部纳入部署、admin 白名单封堵 XFF 伪造、git 仓库初始化。
- **AI 聊天记录导出**：`/api/chat/export?format=md|json`，小鲸会话头部有下载按钮，可导出全部对话。
- **Phase 2/3 五子棋本地全链路**：Socket.IO 实时通道 + 服务端权威规则引擎 + 邀请/落子/终局/归档 + `/games` 对战大厅；好友对战（PvP）是主线。
- **代码审查修复 + 复审**（2026-11-19）：两轮共修 26 项，含 admin 白名单反代失效、webapp 增删改必失败、base_url SSRF、终局房间复用、AI 失败扣费、未读误标、重置令牌竞态等；当时 32 项测试全过。
- 修复 AI 对话 `add_message` 重名致命 Bug（现已改名 `add_chat_message` / `add_im_message`）。
- 移除浮动桌宠形象，保留小鲸导览员人设与聊天头像。
- **消息页界面改版**：会话/好友两个 Tab 合并为一个联系人列表（小鲸置顶 + 好友申请 + 好友会话）；小鲸聊天区新增**无边界像素蓝天白云场景**——天空渐变从聊天区顶部一路延伸到场景带（颜色精确衔接、无分界线），角色随 AI 回复的情绪标记换表情（happy/sad/angry/surprised/sleep/neutral）。场景纯 CSS 渲染，不依赖图片素材；已用 Playwright 实机截图验证。
- **修复新好友首条消息发不出**：点开无会话好友时幂等建会话（`POST /api/conversations`，仅好友、CSRF 保护），此前 `activeConv=0` 会让首条消息被拦截且丢失输入。
- **用户头像**：上传/裁剪/删除全链路，含 `avatar_url` 列与幂等迁移；用户自助删除、管理员删用户时均清理磁盘文件。
- **游戏骨架链路修复**：邀请即建房（原 `create_room` 只在测试调用）、终局快照含 result、sid 映射支持多标签页。
- **服务端权威校验**：`games/rules/` 五子棋规则层，客户端只提交坐标、棋盘由服务端派生，杜绝伪造棋盘（含和棋判定）。
- **IM 消息交互**：右键引用 / 转发 / 删除（个人视图软删除）+ 多选批量（上限 50），设计见总纲 §9B。
- **五子棋 AI 对战**：简单 / 普通 / 困难三档本地策略，必胜必堵优先；AI 只选择合法着法，仍经服务端规则层校验，不调用外部模型。
- **离线对战邀请**：`game_invite` 表持久化 1 小时，接收方上线后在「对战」页查看、接受或拒绝；过期邀请会自动收口。
- **一次性新手引导**：消息页无联系人、小鲸入口、对战页、首手落子、AI 对话满 3 轮导出提示，均可跳过且用 localStorage 记录。
- **安全运行保障**：`.env.example`、最小 CI、MySQL 无密码落盘备份脚本、幂等数据库迁移与增量部署校验。
- **服务器增量部署（2026-11-19）**：备份 → 迁移 → 授权 → 上传 → 重启 → 验证全通过；服务 `active`、`.env` 未变、路由全通、错误日志无。凭据仅用进程环境变量，未入库。
- **头像上传应用层加固（2026-11-19，选项 3）**：两处上传接口在交给 Pillow 之前先按文件头白名单（JPEG / PNG / WebP）识别真实格式、二次确认 Pillow 选中的插件、`load()` 之前限 4000 万像素；PSD / TIFF / BMP / GIF / PDF 等载荷进不了原生解析器。新增 24 项回归，累计 75 项。
- **生产依赖同步（2026-11-19，选项 1）**：服务器已装 Pillow `12.3.0`（3.10 可用的最高版）；本轮无数据库迁移，故按增量脚本第 3–7 步做等价最小同步，跳过 DB 步骤。
- **对局归档可靠性与状态机修复（2026-11-20）**：归档失败不再静默销毁房间（保留 `moves` 唯一副本 + 完整着法写日志可人工补录），上线/刷新邀请时自动补偿重试，成功后才释放房间；未归档房间禁止被覆盖开新局，`sweep` 也不会清理它们。房间因重启消失时凭 `game_invite` 重建并校验邀请归属/好友关系/会话，消除死邀请；已落子的活跃棋盘不再被重新邀请复用；认输/AI 异常收局同样纳入归档流程。AI 困难档搜索加节点预算，避免一次落子长占线程。新增 15 项回归，累计 **90 项 pytest**（8 个文件）全过；**2026-11-20 20:10 已增量部署生产**，`.env` 未变、服务 active、路由与静态资源全通。
- SQL 注入、XSS、CSRF、会话固定、CSV 注入均已防护，安全响应头齐全；`register` 现有 **90 项 pytest**（8 个文件）全过。
- **研究成果展示页（2026-11-25，已增量部署上线）**：新增公开路由 `GET /archive` 渲染 `archive.html`（传 `csrf`、`logged`），纸片档案风格 8 张成果卡 + 5 张统计贴纸（含 Join in 按钮与展开详情），数据为前端静态示例；**根路径 `/` 行为不变**（未登录跳 `/register`、已登录跳 `/home`），`/archive` 为独立新增入口，复用现有认证、不新增 DB 表、不改任何现有页面。

### 进行中 / 待决策

1. **服务器 SSH 密钥轮换**（Phase 0 未完事项）：项目内私钥副本已移走，但服务器上的密钥对尚未轮换，需 hi 拍板后操作。
2. ~~本地代码增量部署~~ **已完成（2026-11-19）**：备份后执行 `deploy_incremental.py`，迁移与授权校验通过、服务与路由正常、`.env` 未变。后续日常更新沿用该脚本，仍需先备份与提供 `MYSQL_PW`。
3. **Phase 2 生产切换**：gevent worker 与 nginx Upgrade 需 hi 拍板后动服务器。当前同步 worker 下 WebSocket 退化为 HTTP 长轮询（对战仍可用）；备案且公网化前不必切换，详见总纲 §9 Phase 2。
4. **Mochi starter 定位**：替换、并存或仅作参考，需产品决策；当前保持独立，不整合。
5. ~~后续游戏~~ **已拍板暂缓**：中国象棋 / 国际象棋 / UNO 等不在本轮扩张，待 hi 明确恢复后再实现，避免影响已跑通的核心链路（2026-11-25 起随五子棋生产下线整体搁置）。
6. **idea 社区（项目新主线，Phase 1 进行中）**：新增 5 张表（`register/schema_idea.sql`：`idea` / `idea_favorite` / `idea_like` / `idea_comment` / `idea_ai_job`）、`register/ideas/` 包与 idea 广场前端；**尚未部署**，先在本地跑通。建表授权与 AI Key 策略待 hi 拍板（总纲 §13 第 7、8 项）。详见工作区 `idea-community-architecture.md`。
7. **Phase 2：数据同步、标签体系与命名调整（2026-11-25，进行中）**：把学习分享室（`/api/archive.json`）与领域头条（`/api/ideas/featured`）统一到 `idea` 表 `published+public` 的同一硬过滤（不带 `viewer_id`），新增 `tag_dict` / `idea_tag` 与 `register/schema_tags.sql`、关键词参数化 LIKE 搜索、公开页导航标签后端硬保证 ≤10；并完成「研究档案室→学习分享室（Learning Studio）/ 想法广场→idea 广场 / 研究成果展示→公开分享的 idea」命名与文案调整，页面主标语「一个 idea 能创造世界」。接口契约见工作区 `api-contract.md`、方案见 `idea-sync-tags-rename-plan.md`，架构决策见总纲 §12 的 2026-11-25 ADR，分工与验收 V1–V15 摘要见 `HANDOFF.md` §1.3。**状态：Phase 2 进行中，代码已提交、待部署验收**（T6 部署与验收由主代理稍后执行）。

### 已知限制

- 项目按**对外产品**标准验收（稳定长跑、可恢复、可监控），不因当前规模小降级；质量门槛见总纲 §10.1。
- 当前 HTTP 明文传输（靠 SSH 隧道加密）。公网化前必须上 HTTPS，不要录入真实个人信息。
- CI 已实跑 6 次（最新 run `44518300890` 总体 Success），主回归 job 全绿（75 项 pytest）；Node.js 20 action 弃用警告已通过升级到 node24 版 action 消除；依赖审计 job 按设计非阻断失败。本地 `pytest` 75 项与 webapp 自检同步通过。
- 已有安全备份脚本，但**尚无定时调度、异地存储与恢复演练**；IM 每 2 秒轮询仍会写访问日志（待优化）。
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
| **改静态文件必须递增模板里的 `?v=N`** | 浏览器继续用缓存旧代码 | 当前值：`style.css?v=11`、`im.css?v=10`、`im.js?v=10`、`game.js?v=5`、`app.js?v=5`、`avatar-crop.js?v=3`、`favicon.svg?v=1`、`archive.css?v=2`、`archive.js?v=3`、`idea.css?v=2`、`idea.js?v=2`（archive 两项为 2026-11-25 成果页上线时新增；本次 Phase 2 一并 bump：archive.css 1→2、archive.js 2→3、idea.css 1→2、idea.js 1→2）；`im.js` 内还硬编码一份鲸鱼头像版本号 |
| **改模板 / CRLF 文件用编辑器逐处改，别用 Python 脚本批量重写** | `newline=''` 会把 CRLF 换成 LF，产生整文件噪音 diff | `home.html`、`app.py` 是 CRLF，需按字节或标记处理 |

### 环境变量与常用命令

**register**：`SECRET_KEY`（必填，缺失拒绝启动）、`DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME`、`SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASS/SMTP_FROM_NAME`、`SITE_URL`（重置邮件链接，默认 `http://127.0.0.1:8082`）、`AI_MODEL`、`AI_BASE_URL`、`AI_API_KEY`、`COOKIE_SECURE`。
**webapp**：`SECRET_KEY`、`COOKIE_SECURE`、`APP_USER`、`APP_PASSWORD_HASH`、`DB_*`。
部署脚本另用 `DEPLOY_HOST`、`MYSQL_PW`、`DB_PW`；SSH key 固定读 `~/.ssh/id_rsa`。

> `register/.env.example` 已入库（仅键名与安全示例，`SECRET_KEY` / `DB_PASSWORD` / `SMTP_PASS` / `AI_API_KEY` 留空）；真实 `.env` 不入库，换服务器按模板手工建。

```bash
# 本地开发（register，端口 8081）
cd D:/MySQL/register && SECRET_KEY=xxx python app.py

# 测试：register 90 项 / webapp 16 项自检（后者不连库）
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

**游戏子系统**（总纲 §8）：在 `register/games/` 独立实现，复用现有好友关系、会话、消息与登录态。规则引擎为**服务端自研 Python**（`games/rules/gomoku.py`）；早期调研的 narabe / xiangqi.js / chess.js 等前端引擎已弃用——服务端权威校验要求规则在服务端，前端引擎防不住伪造棋盘。**好友对战（PvP）是主线、默认模式；五子棋 AI 对战（PvE，小鲸当对手）已实现，其余游戏的 AI 对手不强制**（详见 §8.1.1）。明确排除 SQLAlchemy 重写、微服务、Docker/K8s。

---

## 7. 需要 hi 拍板的事项

按总纲 §13：

0. ~~AI 对话去留~~ **已定案**：保留 AI，且让小鲸当游戏对手；聊天记录可导出。
1. 是否接受 Phase 0 密钥轮换（会使现有 SSH 连接需重新配置）？
2. ~~对战邀请数据结构~~ **已落地**：采用独立 `game_invite` 表，避免把机器 JSON 混进普通 IM 文本；1 小时过期、接受/拒绝状态可追溯。
3. ~~初始化 git / CI 首次实跑~~ **已完成**：提交已推送 `origin/main`，Actions run `44507640518` 总体 Success；依赖审计 job 非阻断失败。
4. ~~五子棋 AI 陪练~~ **已实现**：简单 / 普通 / 困难三档，服务端本地策略；好友对战仍是主线（见 §8.1.1）。
