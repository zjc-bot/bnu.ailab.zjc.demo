# 项目交接说明（给外部协作者）

> 目的：让协作者基于**当前真实代码**工作，而不是文档旧快照。
> 事实来源：`git log`、实际源码、测试结果。最后核对：2026-11-27；当前交付覆盖 2026-11-27 总纲升级与 ECS 部署。**当前基线：register 全量 205 passed、部署专项 13 passed，webapp 离线自测 51 passed / 0 failed；register 9 个幂等迁移、代码切换和 webapp 安全配置已部署 ECS，生产最终 53 项验收通过。** 两服务 `.env` 哈希未变、保持单 worker 回环监听；register 备份 `/root/bnu-register-backups/20261127T051731Z`，webapp 备份 `/root/student-web-backups/20261127T052741Z`。真实浏览器视觉与完整登录态异常矩阵、CI、72h soak、恢复演练及公网开放仍未执行。
> 架构与决策见 `PROJECT_CHARTER.md`，操作红线见 `README.md` §4A/4B，当前实现与交付边界见本文 §1.11；§1.5 与 README §4C 仅为 2026-11-26 历史复审记录。
> **2026-11-19 交付原则**：安全稳定是底线；五子棋 AI、离线邀请、新手引导已实现并通过历史测试，但五子棋已于 2026-11-25 从生产下线。日常遵循“先本地实现与回归验证，生产变更先备份并经确认”。

---

## 1. 先说清楚：哪些"发现"已经不成立

此前基于文档旧快照提出的问题，以下**已修复**，请勿重复投入：

| 旧说法 | 当前实际 |
|---|---|
| 早期文档写 6 / 9 / 10 个 schema | 当前为 **18 个**；全量 `deploy.py` 按依赖遍历，增量脚本覆盖 9 个必要迁移，明确不执行含数据删除的 `schema_chat_migrate.sql` |
| 早期文档写 13 / 32 / 41 项测试 | **当前基线：2026-11-27 本地 register 205 passed，部署专项 13 passed**；使用 uv 临时依赖环境，未修改 requirements；本轮未触发 CI；生产 Python 3.10.12 编译与运行验收已通过 |
| Charter 说"无 WebSocket" | 已改：SSE（AI 流式）+ IM 轮询 + Socket.IO（对局，本地已实现）|
| 无右键菜单 | 已实现引用/转发/删除/多选；且额外加了「⋯」按钮入口（右键在触摸设备和部分浏览器不可靠）|
| SSRF、admin 白名单、headers、终局房间、认输覆盖、AI 扣费、未读误标、UA 转义、和棋、重置令牌竞态…… | 两轮审查共修 26 + 11 项，均已提交 |
| "归档失败只记日志不影响对局" | 旧实现会**紧接着无条件销毁房间**，棋谱 `moves` 永久丢失。2026-11-20 已修：成功才销毁，失败保留房间 24h + 完整着法写日志可补录，上线时幂等重试；详见 `PROJECT_CHARTER.md` §8.3 |
| "邀请持久化后接收方上线即可加入" | 房间在内存、邀请在 DB，进程重启后原会变成死邀请。2026-11-20 已修：`game:join` 凭有效邀请重建房间（校验归属/好友/会话） |

**结论**：文档曾落后于代码，现已同步。若你的信息来自更早的快照，请以本文件和源码为准。

### 1.1 2026-11-25 新增：研究成果展示页（公开门面）

- 新增公开路由 `GET /archive` → 渲染 `archive.html`（传 `csrf`、`logged`）；**根路径 `/` 行为保持不变**（未登录跳 `/register`、已登录跳 `/home`），`/archive` 仅作独立新增入口，不改动任何现有页面与路由。
- 纸片档案风格：8 张成果卡 + 5 张统计贴纸，含 Join in 按钮；数据为前端静态示例，替换真实研究资料只需改模板内的数据数组。
- 新增静态资源 `static/archive.css?v=1`、`static/archive.js?v=2` 与模板 `templates/archive.html`；点击卡片可展开详情（研究方法/发现/意义三段）。`archive.js` 经安全审查修复了 HTML 转义（XSS）、字段兜底与 DB 正文优先读取，版本递增为 2。
- **MySQL 数据层（2026-11-25 初版，已被 Phase 2 替代）**：`archive_api.py` 提供只读 `GET /api/archive.json`（已在 app.py 注册蓝图）；初版 `archive_data.py` 读 `research_achievement` 表，`schema_archive.sql` 为幂等建表脚本。**Phase 2 起已改读 `idea` 表 `published+public` 子集**，查询失败返回空结构，不再回退静态示例；历史表保留。
- **复用现有认证与路由，不新增数据库表、不改 schema、不动认证机制**。
- **状态：2026-11-25 已增量部署上线**：先在服务器备份代码（`/root/bnu-register-backups/20261125T050137Z/code.tar.gz`），再 SFTP 上传 6 个新文件、在服务器 app.py 精确插入 9 行（未覆盖含并行改动的本地 app.py），`py_compile` 通过后 `systemctl restart bnu-register`。核验：`/` 302→`/register`、`/archive` 200、`/api/archive.json` 200、`/register`/`/login` 200，错误日志无异常；仅一条预期 warning——应用账号 `studentapp` 无权读 `research_achievement` 表（表尚未建），API 已按设计回退 `source:static`。

### 1.2 2026-11-25 新增：项目主线转向 idea 社区 + 五子棋生产下线

- **主线转向**：hi 于 2026-11-25 拍板，以「idea 社区」为项目新主线——成员发布想法、收藏/点赞/评论讨论、AI 分类/摘要/去重、点作者加好友私聊协作、成果展示；好友 IM 与小鲸 AI 作为底层能力继续保留。统一以 `idea` 为内容对象，复用现有认证、好友、AI 能力，不新建独立系统。完整方案见工作区 `idea-community-architecture.md`；架构决策以 `PROJECT_CHARTER.md` §12 ADR 为准。
- **Phase 1 已部署并完成数据库建表（2026-11-25）**：新增 5 张表脚本 `schema_idea.sql`（idea / idea_favorite / idea_like / idea_comment / idea_ai_job）、`register/ideas/` 包（routes / store；ai_tasks 属 Phase 3 暂未建）、想法广场前端（3 模板 + `idea.css?v=1` / `idea.js?v=1`）。服务器备份（`/root/bnu-register-backups/20261125T060615Z/code.tar.gz`）后增量上传 9 个文件、app.py 接入蓝图、导航改造。
- **建表与授权（hi 授权，凭据仅进程内使用、未落盘）**：`school` 库已建 5 张表；应用账号实际为 `studentapp@127.0.0.1`（**不是** `@localhost`，首次 GRANT 因此报 1410），已授予 5 张表的 SELECT/INSERT/UPDATE/DELETE。
- **端到端验证中发现并修复 3 个真实 bug**：① `ideas/store.py` 自实现 `_config()` 默认 user 为空 → 环境变量缺失时误连 root（1045）；改为直接复用 `db.connect()` 保证配置单一来源。② `create_idea` 默认 `status='draft'` 而列表只查 `published` → 发布后广场看不到；在 `api_idea_create` 中 `setdefault('status','published')`。③ `.toast` 缺 `[hidden]{display:none}` 与宽度限制 → 错误提示撑成黑色大块；已修 CSS。另修了 app.py import 行重复注释。
- **最终验证**：本地 pytest **105 passed** 无回归、compileall / node --check / Jinja2 全过、安全扫描无敏感信息；服务器真实数据库全链路（发布→列表可见→标签筛选→收藏→点赞→评论→CSRF 拒绝 403→删除）全绿；浏览器截图确认 UI 正常（导航无对战、3 卡片渲染、toast 已修）；验证用示例数据已清理（表保留、数据 0 条）；服务器 7 条路由符合预期、错误日志 0。
- **领域头条（2026-11-25 用户要求，已上线）**：`/api/ideas/featured` 返回每个分类点赞最高的**已发布且对当前用户可见**的 idea。后端 `store.featured_by_category()` 用 MySQL 8.0 窗口函数 `ROW_NUMBER() OVER (PARTITION BY category ORDER BY like_count DESC, created_at DESC, id DESC)`，可见性 SQL 与 `list_ideas` 完全一致；非白名单/空分类在 Python 侧过滤，附 `category_label` 中文名。前端在想法广场 `page-head` 与筛选栏之间加「领域头条」区（`featured` / `featured-grid`），按赞数降序、`auto-fit minmax(210px,1fr)` 自适应列，卡片显示分类、标题、赞数、作者；无数据时整区隐藏。真实库验证：4 个领域各取最高赞（12/9/5/3），把最高赞设为 private 后陌生人自动看到该领域次高（4 赞），作者仍见 private，可见性正确。验证数据已清理、错误日志 0。
- **成果页链接修复（用户反馈，2026-11-25）**：① `/archive` 右下角"已有账号？登录"点不开——根因是 `.selected-line` 继承了参考项目说明文字的 `pointer-events: none`；已移除并加 hover 下划线。② 已登录用户点主站"成果"进入 `/archive` 后仍看到 Join in→注册、右下→登录，误以为被要求重新登录；现按 `logged` 分流：已登录时三个入口全部指向 `/ideas`（Join in 文案改为"进入想法广场"、右下角"已登录 · 进入社区"、上方"← 返回想法广场"），未登录时保持 Join in→`/register`、右下角"已有账号？登录"→`/login`、上方"← 返回站内"→`/`。同步修复工作区静态原型 `styles.css` 与 `archive-prototype/styles.css`。验证：匿名链接 `['/register','/','/login']`、已登录链接 `['/ideas','/ideas','/ideas']`、CSS 无 pointer-events:none、浏览器截图右下角两链接清晰可见、`/login` 200 且含登录表单。
- **五子棋生产已下线（2026-11-25）**：hi 判定五子棋"没啥用"，**只在服务器下线**——先备份代码（`/root/bnu-register-backups/20261125T055948Z/code.tar.gz`，含 `games-disabled/` 归档），再在服务器 app.py 的 `games_page` 插入 `abort(410)`、注释 `init_games(app)`，导航去掉对战入口；**不物理删除 `/opt/bnu-register/games/`**，代码完整保留在本地仓库，可随时恢复。核验：`/games` 登录后 410、未登录 302；其他路由正常。**不要删除本地 `games/` 代码。**
- **口径说明**：本文及总纲中涉及五子棋"已部署/在用"的历史描述，以 `PROJECT_CHARTER.md` §12 的 2026-11-25「五子棋生产下线」ADR 为准；idea 相关代码位于 `register/ideas/` 与 `register/schema_idea.sql`。

### 1.3 2026-11-25 Phase 2：数据同步、标签体系与命名调整

- **三项需求**：① 学习分享室（`/archive`）成果与领域头条同步、数据一致；② 标签可自定义、关键词搜索可管理、公开页导航标签 ≤10；③ 「研究档案室」→「学习分享室」（Learning Studio）、「想法广场」→「idea 广场」、「研究成果展示」→「公开分享的 idea」等命名与文案调整，补激励主标语「一个 idea 能创造世界」。另需解决公开内容可见范围矛盾（发布默认 `friends` 导致公开位看不到内容）。
- **架构决策（核心）**：`idea` 表为唯一事实来源；`/api/archive.json`（学习分享室 / 公开分享墙）与`/api/ideas/featured`（领域头条）共用同一条硬过滤 `status='published' AND visibility='public'`，**不带 viewer_id**；`friends/private/draft` 只留在登录态社区内部；**不做双表同步**，`research_achievement` 表暂留作历史兜底、不删。理由：此前 archive 读 `research_achievement`（无数据回退写死 8 条示例）、头条读 `idea`，双数据源必然不同步；且发布默认 `friends` 导致公开位看不到内容。统一口径同时解决“不同步”与“可见范围矛盾”，并从结构上杜绝 private 泄漏。配套：发布默认可见性改 `public`；公开 API 不返回作者 PII、`author_id`、`content_hash`、`ai_*` 等内部字段，但对已公开 idea 返回完整 `content` 供公开详情展示，卡片 `summary` 仍限制为 120 字；缓存 TTL 60s→30s 并支持写操作失效；`stats` 五项改为 SQL 实时计算（已参加人数、平台内发布的总 idea 数、累计点赞、累计收藏、讨论数）。详见 `PROJECT_CHARTER.md` §12 的 2026-11-25 ADR 与 2026-11-26 正文修正。
- **接口契约**：工作区 `api-contract.md`（约定 `/api/archive.json`、`/api/ideas/featured`、`/api/tags`、`/api/ideas`、`POST /api/ideas` 的请求/响应与公开字段白名单）；设计方案见工作区 `idea-sync-tags-rename-plan.md`。标签字典归 `register/schema_tags.sql` + `tag_dict` / `idea_tag` 两张表（详见总纲 §7.4）。
- **分工（T1–T6）**：T1 数据层统一（`archive_data.py` 改读 idea + 复用 `db.connect()`、`schema_idea.sql` 默认 public、新增 `schema_tags.sql`）；T2 标签与搜索（`ideas/store.py`、`ideas/routes.py`：字典下发、参数化 LIKE、≤10 导航、双写标签）；T3 头条口径（`featured_by_category` 去 viewer 参数、改 public-only，与 T2 同文件由主代理串行处理）；T4 前端与文案（`archive.js`、`idea.css/js`、模板改名与激励文案、静态版本号 bump）；T5 文档与 ADR（本文档、README、总纲）；T6 验证与部署（pytest、可见性矩阵、同步一致性、≤10 断言、XSS、截图、增量部署）。
- **验收项 V1–V15 摘要**：V1 发布 public idea 后 archive 与头条的标题/分类/标签 diff=0；V2 private/friends/draft 连续 ≥2 个 TTL 不出现在公开响应；V3 public ≤60s 必达且 `source='mysql'`；V4 撤回及时；V5 字段脱敏；V6 导航标签 ≤10（含「全部」）；V7 自定义标签可发布/可搜/进导航；V8 仅存在于标题或正文的关键词能命中且分页 total 一致；V9 0 条 public 时显示空态、不回退 8 条示例；V10 8 种纸片无空白；V11 自定义标签 XSS 转义；V12 运行时 grep「研究档案室」=0、静态版本号已 bump；V13 pytest 105+ 全绿、错误日志 0；V14 `stats` 五项与库查询逐项相等、0 条时全为 0；V15 主标语出现在 idea 广场与学习分享室头部。
- **状态：Phase 2 与 2026-11-26 复审修复已于 2026-11-26 晚间部署 ECS**。生产迁移、公开 API、路由、监听与日志基础验收通过；完整登录态可见性矩阵、真实浏览器交互和 2FA 异常路径仍待补验。

---

### 1.4 2026-11-25 Phase 2 收尾修复（账号页对战栏 / Socket.IO 残留）

- **账号页仍有「对战」**：`templates/profile.html` 的导航与「新手引导」里的整块「对战 · 五子棋」说明未随生产下线一起清理，用户点进账号页仍能看到。已删除该导航项与说明块，账号页导航统一为「消息 / idea / 学习分享室 / 账号」；常见问题里的「邀请没反应」也改为消息口径。核验：`/me` 页面 grep「对战 / 五子棋 / games_page」= 0。
- **Socket.IO 持续报错**：早前对服务器 `init_games(app)` 的注释被后续部署覆盖还原，旧标签页轮询 `/socket.io/` 触发 gunicorn WebSocket 升级失败、错误栈刷屏。改为**环境变量开关**：`GAMES_ENABLED=1` 或 pytest 环境才挂载 `init_games(app)`，生产 `.env` 未设该变量故默认关闭；`before_request` 对 `/socket.io/` 明确返回 410。游戏代码完整保留，本地 `pytest` 105 passed 无回归。核验：`/socket.io/` → 410，重启后日志无 traceback。
- **命名与文案**：主标语「一个 idea 能创造世界」；全站「研究档案室」→「学习分享室」(Learning Studio)、「想法」→「idea」、导航「成果」→「学习分享室」；静态版本号 bump 至 `archive.css?v=3` / `archive.js?v=4` / `idea.css?v=2` / `idea.js?v=3`（2026-11-26 为 idea 交互修复递增）。
- **前端 bug 修复**：`reset()` 曾回退写死 `BASE` 假数据（改为重新应用真实数据快照）、空态下 `step()` 的 `% 0` 与「01 / 00」计数、以及 4 处 XSS 转义缺口（详情 tags / nav data-cat / status class / d-kind）。`applyData()` 提升为全局函数，供 API 加载与复位共用。

### 1.5 2026-11-26 复审与本地修复（历史记录，晚间已部署）

> 以下“未修复”等表述是 2026-11-26 当时状态；2026-11-27 已由 §1.11 与总纲当前章节替代。

2026-11-26 当日先逐文件复审，再按授权修复后台 2FA、idea 数据与交互、增量部署，并补回归测试。**本地修复后已连接 ECS/MySQL，完成备份、迁移、上传与用户手动重启；未提交或推送。生产基础验收通过，但完整登录态与真实浏览器验收仍待补。**

| 等级 | 问题 | 2026-11-26 当日状态与证据 |
|---|---|---|
| 严重 | 后台邮件验证码可由客户端直接读取 | **已修复并部署**：`register/admin.py` 改为服务端随机挑战，仅存 `(token + code)` 的 SHA-256；Cookie 只持有挑战 token |
| 高 | 后台 2FA 可穷举且故障时静默降级 | **已修复并部署**：5 分钟有效、每挑战 5 次错误、每 IP 每小时 5 次发送；邮箱缺失、查询异常、邮件异常均拒绝登录；改密撤销该管理员全部会话与待验证挑战 |
| 高 | 更换 2FA 邮箱没有验证新邮箱 | **已修复并部署**：确认邮件发往新邮箱，`purpose=email` 的挑战一次性消费后才更新；确认前旧邮箱不变 |
| 中 | 后台会话不可服务端撤销、待验证 Cookie 可重放 | **已修复并部署**：后台会话存服务端并支持登出撤销；挑战一次性消费，陈旧 `aid/a2fa` Cookie 不再被接受 |
| 中 | 注册验证码尝试次数存在客户端 Cookie | **未修复**：`register/app.py` 的 `code_tries` 仍可随 Cookie 复制重置 |
| 中 | 图形验证码可无限签发并反复全表扫描 | **未修复**：`_captcha_store` 仍需签发频率、容量上限与增量/定时清理 |
| 中 | SSRF 地址段未排除 CGNAT | **未修复**：`_bad_ip()` 仍需显式排除 `100.64.0.0/10` 等非 global 地址并补测试 |
| 严重 | `webapp` 一键部署会破坏共享配置并改变暴露面 | **当日未修复（禁止在已有服务器执行）**：旧脚本会轮换共享 `studentapp` 密码、重置 `SECRET_KEY`、覆盖 Nginx/UFW 并回显凭据；2026-11-27 本地修复与复核状态见 §1.11 |
| 高 | `register` 增量脚本未覆盖 Phase 1/2 | **已修复并部署**：递归源文件清单覆盖 idea/tag/archive；迁移按依赖执行，授权覆盖全部业务表 |
| 高 | 增量脚本可能“假绿” | **已修复并部署**：远程命令检查退出码；迁移表列、权限、`.env` 哈希、依赖、服务、8081 纯回环监听、HTTP 与错误日志均断言，混合公网监听也会失败 |
| 高 | idea 广场分类、搜索、排序错误 | **已修复并部署**：分类读 `/api/categories`；`q` 与 `tag` 分离；hot/new 在服务端 SQL 排序；`idea.js?v=3` |
| 中 | idea 详情点赞/收藏后计数不刷新 | **已修复并部署**：读取 `data.idea`，按钮防重复点击，以响应中的服务端计数更新；刷新失败只提示计数未更新，不误报操作失败 |
| 中 | idea 列表竞态与重复翻页 | **已修复并部署**：递增请求序号忽略旧响应；加载中禁用“加载更多” |
| 中 | idea 发布/评论可重复提交 | **当日未修复**：当日只完成列表竞态与详情按钮防重；`idea.js` 的发布和评论提交仍需提交锁或幂等保护 |
| 中 | 分类长度与非对象 JSON 可触发 500 | **已修复并部署**：分类 30 字上限；创建/更新/评论拒绝非对象 JSON；标签数组元素也按中英文逗号展开，统一去重并限制 8 个 |
| 中 | 标签读写路径与字典状态不一致 | **已修复并部署**：active 标签统一进入关联、兼容串、搜索与公开导航；`casefold()` 去重，置顶/使用数/最近使用参与排序；`schema_tags.sql` 幂等回填历史逗号串且不重启 disabled 标签 |
| 中 | 删除 idea 残留标签关系；公开统计含非公开活动 | **已修复并部署**：删除显式清理 `idea_tag`；idea/点赞/收藏/讨论统计统一 `published+public`，活跃用户仍按全站 active 口径 |
| 中 | 学习分享室键盘、焦点与 API 故障处理不完整 | **未修复**：纸片键盘打开、方向键重复推进、焦点约束、HTTP 错误与窄屏缩放仍待处理 |
| 高 | 待归档游戏房间过期清理绕过恢复日志 | **既有问题，当日未改、当前仍未改**：`games/manager.py:86-88` 的 `get_room()` 超 24 小时直接删除，绕过 `sweep()` 的完整 moves 日志；`claim_archive()` 又直接读 `_rooms`。恢复游戏前统一清理路径并补过期测试 |
| 低 | 账号页删除 API Key 无二次确认 | **未修复**：`profile.html` 的 `data-confirm` 仍缺处理脚本 |
| 中 | `webapp` 客户端 IP 全部塌缩为回环地址 | **当日未修复**：Nginx XFF 为追加，应用层限流成为全局计数；2026-11-27 已改为 `$remote_addr` 覆盖并同步生产，详见 §1.11 |

**验证结果（2026-11-26 历史记录）**：新增 `register/tests/test_admin_2fa.py`、`test_ideas.py`、`test_archive_reliability.py`、`test_deploy_incremental.py`。从仓库根目录运行 `uv run --with-requirements register/requirements.txt python -m pytest register/tests -q`，**历史结果 131 passed**；当前基线已由 2026-11-27 的 198 passed（升级专项 103 passed）替代。Python 编译、全部 JS `node --check`、备份脚本 `bash -n`、`git diff --check` 通过；生产侧已实际执行标签回填迁移。ECS 基础验收：服务 active、仅 `127.0.0.1:8081` 监听、`.env` 哈希未变、关键路由状态正确、错误日志无 Traceback/CRITICAL，idea 43 公开 API 返回 1128 字完整正文。浏览器连接器仍不可用，未做真实浏览器验收；当日未触发 CI、未重跑 webapp selftest。

### 1.6 2026-11-26 晚间生产部署与学习分享室正文修复

- **备份与发布**：hi 明确要求检查并部署更新代码。先在 `/root/bnu-register-backups/20261126T123618Z/` 备份 `code.tar.gz`（28M）与 `school.sql.gz`（44K），再按 game → message → game_ai → admin_2fa → idea → tags 顺序执行 6 个幂等迁移，上传 84 个源码文件并用生产 Python 3.10.12 编译。为避免不必要扩权，本次保留原有 86 项表权限，没有按脚本设计扩展到 92 项。用户于 FinalShell 手动重启，服务启动时间 `2026-11-26 21:08:10 CST`。
- **正文问题根因**：公开 API 只投影 120 字 `summary`，前端又用空白 `method/finding/impact` 拼接静态占位区块，导致截图中的正文缺失、重复且像被截断。卡片摘要与详情正文被错误耦合。
- **修复**：`archive_data._to_item()` 同时返回完整 `content` 与 120 字 `summary`；`archive.js` 删除 `DETAILS` 假正文和三个占位区块，新增 `renderBody()`，先 HTML 转义再仅对 HTTP(S) URL 做 linkify，链接使用 `target="_blank" rel="noopener noreferrer"`；`archive.css` 增加 `white-space: pre-wrap` 与换行/链接样式。模板版本为 `archive.css?v=3` / `archive.js?v=4`。
- **生产核验**：服务 active；gunicorn 仍为 `--workers 1 --threads 4 --bind 127.0.0.1:8081`；`.env` SHA-256 保持 `607bf872…d032f`；关键路由、静态版本与生产编译通过；日志无 Traceback/CRITICAL；`/api/archive.json` 的 `source=mysql`，idea 43 的 `content` 长 1128 字、`summary` 长 120 字，包含论文链接与“我的思考”，占位文本已消失。
- **边界**：浏览器连接器返回 `BROWSER_CONNECTOR_WAITING`，因此未声称完成真实浏览器截图验收；完整登录态可见性矩阵、2FA 邮件/异常路径、CI 与 webapp selftest 仍待补。未提交或推送 Git。此前部署异常曾回显一次数据库凭据，代码已修复并补回归，建议 hi 尽快轮换该凭据。

### 1.7 2026-11-26 idea 编辑与内容治理规划（历史设计，已由 2026-11-27 实现）

- **需求**：管理员可撤销任意 public/friends/private idea，并设计合理管理界面；先规划、查资料、更新文档，想法成熟后再改代码。
- **现状结论**：后台已有单类管理员、服务端可撤销会话、邮箱 2FA 和 CSRF，但没有 idea 内容入口、业务审计或恢复语义。`idea.status` 的 `archived` 属于作者生命周期，不能复用为平台撤销；广场、分类、标签、头条与 archive 均需同步增加治理过滤。
- **推荐方案**：独立 `moderation_state=active/revoked` 与 `row_version`；软撤销保留正文、互动和标签；状态变更与 append-only `idea_moderation_log` 同事务；提交后失效 archive 缓存并通知作者，原规划邮件失败可重试（**2026-11-27 当前仅留痕，人工重试尚未实现**）。默认非作者 404、作者本人只读、private 仅管理员元数据可见；一期只做单条撤销/恢复，不做批量/RBAC/举报工单/私密正文查看。
- **配套编辑**：补 `GET /ideas/<id>/edit` 与详情入口，复用现有表单/PUT；版本冲突返回 409；内容字段变化清空旧 AI 摘要；标签未变不重复同步。
- **文档位置**：完整状态矩阵、DDL、路由、UI、事务、测试、部署回滚与待确认项见 `PROJECT_CHARTER.md` §9C；README §4 已同步。
- **历史边界（2026-11-26）**：当日未创建迁移、未改业务代码、未连接服务器、未部署。§9C.10 的核心默认值确认前不进入实施；2026-11-27 的本地实现与待验收状态见 §1.11。

### 1.8 2026-11-26 个人主页与我的收藏设计及网页说明（历史设计，已由 2026-11-27 实现）

- **需求**：增加个人主页，集中查看自己发布的 idea 及每条获赞/收藏量，并在同页提供“我的收藏”；参考成熟设计，找出问题与升级点。
- **现状结论**：`/home` 是消息页、`/me` 是账号设置；没有个人内容主页。`GET /api/ideas?author=<uid>` 只返回 published，不能展示草稿/归档/private。收藏只有切换与单条状态查询；`idea_favorite` 已有 `created_at`，但无列表接口和文件夹模型。
- **推荐方案**：新增登录态 `/profile`，默认“我发布的 / 我的收藏”双视图；自己的 API 只取 session uid。我的 idea 展示全部 active 状态与全站累计互动；收藏按 `favorited_at` 倒序，并必须按当前 viewer 重新判定可见性，items 与 total 同条件。权限变化后隐藏但保留关系，恢复权限可重新出现。
- **安全边界**：收藏关系不授权读取；private/draft/archived/未来 revoked 不进入非作者列表或总数。个人 API `no-store`。现有 toggle 可见性检查与写入跨连接，实施时改同事务锁行复核。
- **扩展边界**：一期不做公开作者页、命名收藏夹、分享或置顶。公开作者页未来只返回 id/昵称/头像和当前可见的 published+active 内容；先解决删用户遗留 idea 的策略。
- **设计依据**：GitHub 个人页置顶与 Stars 列表、Apple Maps 收藏集合、NN/g tabs、W3C WAI-ARIA Tabs。完整线框、权限矩阵、API、索引、移动端/无障碍与验收清单见 `PROJECT_CHARTER.md` §9D。
- **历史边界（2026-11-26）**：当日只更新设计文档与账号页「网页使用说明」，未实现个人主页业务功能、未创建迁移、未连接 ECS、未部署、未提交或推送；§9D.12 确认前不进入功能实施。2026-11-27 已本地实现，状态见 §1.11。

### 1.9 2026-11-26 分类体系标准化升级（历史设计，已由 2026-11-27 实现）

- **需求与截图结论**：idea 广场截图显示“材料与传感”，该名称是 `CATEGORY_LABELS['mat']` 的中文展示，不是自定义分类；截图不能单独证明数据库存的是中文值还是 code。
- **真实根因**：`register/ideas/routes.py` 的 `_validate()` 允许任意 ≤30 字分类；`templates/idea_form.html` 是自由文本 + datalist；`ideas/store.py` 的 `list_categories()` 从可见 idea 的 distinct 值动态生成筛选项。FFT 选到 mat 是选择/数据问题，不存在自动语义分类。
- **升级方案**：固定 `ai / edu / bio / energy / math / other` 六类与顺序；发布/编辑改为固定 select；创建/更新 API 服务端拒绝未知 code；`GET /api/categories` 返回固定六类；细分主题走标签。抽取单一分类常量源，避免 routes/store/archive 映射漂移，详见 `PROJECT_CHARTER.md` §9E。
- **迁移边界**：先备份并导出 distinct 分类、数量与示例 id；已知六个 code 不动；中文别名显式映射；未知值保留原值后迁 `other` 或先人工核对；不按标题自动猜测。2026-11-27 已确认数学分类使用 `math`；FFT 可使用 `math + FFT/DFT/分治思想`，`signal` 不单独扩类。
- **历史边界（2026-11-26）**：当日只更新总纲、README、交接文档和账号页「网页使用说明」的升级任务；未改分类业务校验、未创建迁移、未连接 ECS、未部署、未提交或推送。§9E.6 确认前不进入实施；2026-11-27 已本地实现，状态见 §1.11。

### 1.10 2026-11-26 idea 关键词支持作者昵称（历史本地实现记录）

- **需求**：在 idea 广场用昵称作为关键词搜索，并加入升级内容。
- **改造前现状**：`GET /api/ideas?q=` 只匹配标题、正文、兼容标签串与 active 标签字典；`app_user.nickname` 已在卡片展示，但未进入搜索条件。计数 SQL 尚未 join `app_user`，页面标签也未声明昵称搜索。
- **实现**：复用当前关键词框，`q` 采用 OR 同时匹配标题、正文、标签和当前作者昵称；trim、去通配符、部分匹配，输入上限统一为 60 字。不新增匿名用户搜索、作者自动补全或“仅该作者”控件。
- **安全边界**：列表与 `COUNT(*)` 已同步 join `app_user` 并保持同一 `published` 与 public/friends/private 可见性谓词；昵称条件只能缩小结果。只搜索昵称，不搜索或返回学号、真实姓名、邮箱；入口保持登录态。
- **SQL 参数**：关键词参数由 5 个扩到 6 个，两条 SQL 同步；继续参数化并清理 `%` / `_` / 反斜杠，避免 LIKE 通配或转义歧义。`%昵称%` 通常用不上昵称唯一索引，本轮不加冗余索引或迁移。
- **历史验证（2026-11-26）**：当时全量 **133 项 pytest** 通过，专项覆盖 API q 透传、两条 SQL 同步 join、6 个关键词参数、通配符与反斜杠清理、60 字截断和可见性谓词；登录态 HTTP 页面/API 冒烟与部署清单 dry-run 通过。当前基线已由 2026-11-27 的 205 passed 替代；真实 MySQL 执行计划、完整可见性矩阵与浏览器交互仍待补验。
- **历史边界（2026-11-26）**：当日已完成本地代码、测试、总纲、README、交接文档与账号页说明更新；未创建迁移、未连接 ECS、未部署、未提交或推送。完整方案见 `PROJECT_CHARTER.md` §9F；2026-11-27 状态见 §1.11。

### 1.11 2026-11-27 当前实现、测试与交付边界

- **功能**：固定六类 `ai/edu/bio/energy/math/other`，历史未知值保留 `category_legacy` 后归 `other`；昵称搜索；作者编辑必须 `row_version`，冲突 409；内容字段变化清空 AI 派生物。
- **治理**：独立 `moderation_state=active/revoked`；撤销作者只读、非作者不可见，private 后台不展示标题/正文/标签，仅展示处置所需元数据（作者昵称/邮箱仍向已认证管理员展示，最小化范围待复核）；append-only `idea_moderation_log` 与 `request_id + 载荷指纹` 幂等；后台单条撤销/恢复、查看审计及 `no-store`；公开读取统一 active 过滤并失效缓存，通知失败留痕。
- **治理未完成项**：独立 restore/notify/audit 路由、人工通知重试、完整 ID 输入确认、恢复时 `content_hash` 一致性拒绝尚未实现；同请求重放不会补发失败通知，不得把原规划写成已交付。
- **个人与并发**：登录态 `/profile` 的“我发布的 / 我的收藏”，`?view=favorites` 可直达，个人响应 `private, no-store`；收藏按当前权限重算。点赞/收藏/评论与删号共享用户行锁；删号同事务清互动并重算计数，有 idea 的作者拒绝删号以避免孤儿。
- **安全与交互**：注册验证码服务端邮箱/IP/challenge 限流与原子消费；图形验证码频率/容量/增量清理；SSRF 拒绝非 global/CGNAT、IPv6，IP pin 且保留 Host/SNI/证书校验、禁代理和重定向；学习分享室键盘/焦点/错误/窄屏修复；后台 2FA 邮箱确认和账号 Key 删除确认。
- **迁移**：新增 `schema_category.sql`、`schema_moderation.sql`、`schema_profile.sql`；空库 schema 顺序修复；增量迁移精确校验列与索引，审计表只授 SELECT/INSERT。
- **验证**：当前 register 全量 **205 passed**，部署专项 **13 passed**，webapp 离线自测 **51 passed / 0 failed**；已重跑 Python/Shell/JS 语法检查、增量部署 `--dry-run` 与 diff whitespace 检查。9 个迁移已在生产副本隔离库重复演练，并完成生产迁移、精确列/索引/权限校验及 53 项生产验收；webapp 生产 `nginx -t`、监听与 HTTP 验收通过。这些结果不替代浏览器与异常路径验收。
- **边界**：本轮 register 与 webapp 已部署 ECS，`.env` 哈希未变。真实视觉截图、完整登录态异常矩阵、CI、72h soak、HTTPS/公网开放与备份恢复演练仍未执行。

## 2. 当前真实开放问题（按优先级）

### P0 — 公网开放前阻断项

1. **真实浏览器与异常路径未验收**：本轮生产部署、迁移和 53 项验收已完成；公网开放前仍须完成完整登录态矩阵、真实浏览器，以及邮件收码、2FA 过期/重放/换邮箱和 DB/邮件故障 fail-closed 验收。
2. **公网化未完成**：HTTPS、安全组放行、72h soak 与备份恢复演练均未执行，保持仅 SSH 隧道。
3. **SSH 密钥轮换未执行**：仍需单独确认；部署过程未轮换现有密钥与共享数据库凭据。

### 历史阻塞项（已解除，仅保留审计记录）

**2.1 本地代码与服务器不同步（已解除）**
- 原问题：用户实测消息右键无效，弹出浏览器原生菜单；根因是代码只在本地 `D:/MySQL`，服务器 `/opt/bnu-register` 仍是旧版。**这是运维同步问题，不是代码缺陷。**
- 处置：hi 授权后先做代码 + 数据库备份（`/root/bnu-register-backups/20261119T104436Z/`：`code.tar.gz` + `school.sql.gz`），再执行 `deploy_incremental.py`，`DEPLOY_EXIT=0`。
- 核验：服务 `active`、监听 `127.0.0.1:8081`；`/login`、`/register`、`/captcha.png`、`/static/game.js`、`/static/socket.io/socket.io.min.js` 均 200，`/games` 302（未登录跳转，符合预期）；`journalctl` 错误日志无；部署代码标记齐全。
- **`.env` mtime 前后一致**，未重新生成 `SECRET_KEY`，已存 BYOK Key 未受影响。

**2.2 增量部署脚本曾遗漏数据库迁移（已修且已在服务器验证）**
- 原问题：`deploy_incremental.py` 只传代码不执行 `schema_message_v2.sql`。新 `db.py` 的 SELECT 含 `quote_id/deleted_by_a/deleted_by_b/forward_from`，老表无这些列 → 同步后消息页 500。全量 `deploy.py` 会重置 `SECRET_KEY`（BYOK Key 永久报废），不能用于救场。
- 修复：消息表 4 列迁移纳入增量脚本；新增 `schema_game_ai.sql`（`game_invite` 表、`game_record` 的 AI 标识与可空 `conv_id`），上传代码前校验表、列与可空性，缺失即中止。
- 已在服务器实跑并校验：`game_invite` / `ai_difficulty` / `conv_id nullable` = `1,1,1`，`game_invite` 授权 = `1`。
- 首次尝试因 `mysql -p` 的 warning 混入校验结果，在**上传代码之前**按设计中止，未污染服务器；改为 `MYSQL_PWD` 环境变量 + 只取结果末行后重跑成功。凭据仅在进程环境变量中，未落盘、未入库。

### P1 — 产品决策（Mochi 已定案）

**2.3 `neko-world-complete-starter`（Mochi）保持独立，仅作参考**
- 2026-11-19 ADR 已明确：不整合、不替换小鲸。现有 `register/` 的小鲸人设、对话与像素场景继续保留；starter 是独立参考项目，不进入运行时、不共享其 Soul/数据库设计。
- 此项不再是待拍板阻塞。未来若变更定位，必须先新增 ADR，再评估 UI、身份与数据模型，不能直接合并两个项目。

### P2 — 工程缺口

| 问题 | 证据 | 建议 |
|---|---|---|
| 无自动备份/异地备份/恢复演练 | 已有 `register/deploy/backup_mysql.sh` 与增量部署本地备份，但无调度 | 上线前建定时 mysqldump + 异地存储 + 恢复演练 |
| 真实 MySQL 空库顺序未验 | 9 个生产迁移与隔离生产副本重复演练已通过；未验证全新空库初始化 | 在隔离 MySQL 8.0 验证全部 schema 顺序与审计权限 |
| 浏览器与登录态未验 | 本轮未做真实浏览器和完整可见性矩阵 | 在 SSH 隧道内回归桌面/窄屏/键盘、治理只读、private 脱敏、收藏权限与 2FA 异常 |
| 依赖审计与解释器漂移 | 本地/CI Python 3.13，生产 3.10.12；CI audit 非阻断 | 固定生产解释器并跑兼容测试；依赖审计按高危分级 |
| 测试覆盖仍需扩展 | 当前 register 205 passed、部署专项 13 passed；webapp 离线自测 51 passed / 0 failed；未跑 CI | 触发 CI；生产 Python 3.10.12 复跑；补真实邮件与 DB 异常路径 |
| 内存限流与验证码存储不支持多 worker | 部分状态在进程内；图形验证码已有频率/容量/清理，注册尝试在数据库 | 保持单 worker；扩容前迁 Redis/数据库并验证清理与容量 |
| 服务器 SSH 密钥未轮换 | 总纲标“待 hi 拍板” | 安排轮换并更新部署脚本；部署客户端校验 known_hosts，停用 `AutoAddPolicy` |
| BYOK SSRF 已部署，业务回归待补 | 已拒绝非 global/CGNAT/IPv6，pin IP 并保留 Host/SNI/证书、禁代理/重定向 | 补真实上游回归；系统默认上游限制为可信管理员配置 |
| 学习分享室真实交互未验 | 键盘、焦点、API 错误与窄屏已本地修复 | 真实浏览器、键盘-only 与减少动画验收 |
| 治理功能与原规划有差距 | 当前仅 `/admin/ideas`、详情与 `/moderate`；独立 restore/notify/audit、人工通知重试、完整 ID 确认、恢复 content_hash 校验未实现 | 按 §9C 的当前边界验收；失败通知目前只留痕，重放不补发 |
| 个人主页真实权限未验 | `/profile` 双视图已部署，个人 API no-store | 验证 items/total 同谓词、权限变化隐藏/恢复、revoked 只读；公开作者页/命名收藏夹后置 |
| 分类迁移已执行 | 固定六类与 `category_legacy` 已部署，生产分类宽度与历史归一化校验通过 | 补完整可见性矩阵与浏览器验收；不按标题猜测 |
| 昵称搜索已部署，业务回归待补 | `q` 匹配标题/正文/标签/当前昵称，生产文件哈希与本地一致 | 补真实 MySQL 执行计划、完整权限矩阵与浏览器验收 |
| webapp 补丁与 IP 口径 | 补丁与 Nginx 模板已同步生产，离线 selftest 51 项通过；回环监听、`nginx -t` 与 HTTP 验收通过 | 继续核验真实 IP 日志与限流；现有服务器禁止重跑初始化脚本 |

### P3 — 信息项

- 域名已买且**已完成 ICP 备案**；项目仍不公网开放，只走 SSH 隧道，安全组仅放行 22。这是刻意的安全姿态。
- `bnuailab.conf` 是**公网化预置模板，未启用**。里面 XFF 覆盖、Upgrade、HTTPS 相关配置当前不生效。

---

## 3. 必要提示（务必遵守）

### 安全红线

1. **禁止在已有数据的服务器上重跑全量 `register/deploy/deploy.py`** —— 每次生成新 `SECRET_KEY` 覆盖 `.env`，导致 session 全失效、已存 BYOK API Key **永久无法解密**。日常更新只用 `deploy_incremental.py`。
2. **禁止在已有服务器重跑 `webapp/deploy/deploy.py` 或 `install.sh`** —— 旧脚本会轮换共享 `studentapp` 密码、重置 webapp `SECRET_KEY`、改 Nginx/UFW 并回显凭据；现脚本已改为无 `--force` 的空环境初始化与写前熔断，但部署后环境必然触发拒绝。已有服务器仍禁止执行，更新必须先设计保留现有配置的增量流程。
3. **`register/deploy/deploy_incremental.py` 已完成本地加固；本次按等价分步流程发布** —— 先 `--dry-run` 核对源文件与迁移，生产执行需单独授权。脚本保留 `.env`、不修改 systemd/Nginx，也不会执行含数据删除的 `schema_chat_migrate.sql`；其默认全业务表 CRUD 授权范围大于最小权限，已有服务器应逐项核对，不盲目扩权。
4. **ICP 备案 + HTTPS 之前，不要开放任何公网端口**。当前明文 HTTP 靠 SSH 隧道加密。
5. **凭据不落盘**：密钥/密码只从环境变量读，不写进代码或提交。
6. **ProxyFix 信任链三前提**：gunicorn 只 bind `127.0.0.1:8081`；nginx 唯一公网入口且 XFF 用 `$remote_addr` **覆盖**（非追加）；中间只有一层代理。任一变化会让 admin 白名单与限流静默失效。

### 操作约束

6. **gunicorn 保持 `--workers 1`**：限流字典、验证码、2FA 挑战/会话、登录失败计数、对局房间都在进程内存，加 worker 会全部失效。扩容前先迁外部存储。
7. **schema 迁移不能乱序**：首次建站由 `deploy.py` 保证 `schema.sql` → `schema_idea.sql` → `schema_tags.sql` 优先，再执行分类/治理/个人页等迁移；增量脚本按 game → message → game_ai → admin_2fa → idea → tags → category → moderation → profile 顺序执行并精确校验列/索引。`schema_chat_migrate.sql` 会删除重复好友申请，增量流程明确不执行它。本轮尚未在真实 MySQL 验证空库与重复迁移。
8. **头像目录属主必须 `regweb`**：全量部署后补 `chown -R regweb:regweb /opt/bnu-register/var`，否则上传静默失败。
9. **改静态文件必须递增模板 `?v=N`**：否则浏览器用缓存旧代码。当前值见 `README.md §4A`。
10. **CRLF 文件（home.html、app.py）用编辑器逐处改**，别用 Python 脚本批量重写（会把 CRLF 换成 LF，产生整文件噪音 diff）。

### 协作约定

11. **新功能进 `register/`**，游戏代码进 `register/games/`，禁止新建无语义目录。
12. **改架构先改 `PROJECT_CHARTER.md`**，记录决策再动代码。
13. **删除前先备份、先列表、先确认**，移到回收站，不永久删除。
14. **学习分享室数据与 UI**：页面结构在 `templates/archive.html`，交互与样式在 `static/archive.*`，公开数据由 `archive_data.py` 从 `idea` 表 `published + public + moderation_state='active'` 子集读取（active 治理过滤于 2026-11-27 加入并已部署）；不得回退写死的示例数据。改静态文件时记得递增模板里的 `?v=N`。
15. **idea 相关代码集中在 `register/ideas/` 与对应 schema**：分类常量在 `ideas/constants.py`，治理在 `ideas/moderation.py`，个人页脚本为 `static/content_profile.js`；不要散落到 `app.py` 或 `static/` 根。Phase 1/2 是 2026-11-26 历史生产版本，2026-11-27 升级已部署并验收。**五子棋不要删除本地 `games/` 代码**；生产下线只禁用服务器入口，不物理删除目录。
16. **标签字典归 `register/schema_tags.sql` + `tag_dict` / `idea_tag` 两张表**（Phase 2）：active 标签是关联、兼容串、搜索与公开导航的规范读路径，后端参数化 LIKE 覆盖 `title/content/tag.name/当前作者 nickname`；`idea.tags` 仅为兼容保留。**公开口径任何改动必须同时检查「领域头条」与「学习分享室 / 公开分享墙」两侧，禁止重新引入双数据源**——两者必须共用 `idea` 表 `published+public+moderation_state='active'` 的同一硬过滤（不带 `viewer_id`；active 为 2026-11-27 新增并已部署）；`friends/private/draft/revoked` 只留在登录态社区内部或作者只读视图。公开 API 一律走字段白名单，禁止重新回退写死的示例数据。

---

## 4. 协作方式建议

- 协作者做架构评判时，请以**源码 + git 历史**为依据，不要仅凭文档快照——本项目文档曾落后于代码，现已修正，但旧快照仍在流传。
- 现有 AI 流式通道是 SSE，情绪标记（`[[emo:xxx]]`）已驱动前端小鲸换表情（`im.js reactMood()`）。若设计 avatar 事件，应**扩展现有 SSE**，不要为每句话另发 AI 请求，也不要把 Socket.IO 挪作通用推送通道——它只负责对局。
- 每次交付后请明确标注"已修/待办"，避免反复报同一问题。

---

## 5. 快速自查命令

```bash
cd D:/MySQL
uv run --with-requirements register/requirements.txt pytest register/tests/ -q  # 205 passed
uv run --with-requirements webapp/requirements.txt python webapp/tests/selftest.py  # 51 passed / 0 failed
python -m compileall -q register webapp scripts
for file in register/static/*.js; do node --check "$file" || exit 1; done
bash -n register/deploy/backup_mysql.sh
bash -n webapp/deploy/install.sh
git status --short                 # 核对本次允许范围；已有业务代码改动勿误覆盖
```

部署（需 `MYSQL_PW` 与服务器备份确认；2026-11-27 升级已完成备份、迁移、切换和 53 项生产验收；后续更新仍须 dry-run、备份并单独授权）：

```bash
MYSQL_PW=xxx python register/deploy/deploy_incremental.py
```
