# 项目交接说明（给外部协作者）

> 目的：让协作者基于**当前真实代码**工作，而不是文档旧快照。
> 事实来源：`git log`、实际源码、`pytest` 结果。最后核对：2026-11-19；核心功能提交 `8766e26` 已推送 `origin/main`，以 `git log -1` 和 GitHub Actions run `44507640518` 为准。
> 架构与决策见 `PROJECT_CHARTER.md`，操作红线见 `README.md §4A/§4B`。
> **2026-11-19 交付原则**：安全稳定是底线；五子棋 AI、离线邀请、新手引导已实现、通过 75 项测试，并完成服务器增量部署与核验；后续游戏经 hi 拍板暂缓。日常仍遵循"先本地实现与回归验证，生产变更先备份并经确认"。

---

## 1. 先说清楚：哪些"发现"已经不成立

此前基于文档旧快照提出的问题，以下**已修复**，请勿重复投入：

| 旧说法 | 当前实际 |
|---|---|
| 早期文档写 6 / 9 / 10 个 schema | 当前为 **11 个**（含 4 个幂等迁移），deploy 的 `glob` 全量执行 |
| 早期文档写 13 / 32 / 41 项测试 | 当前为 **90 项 pytest**（8 文件），本地全过（含 24 项头像上传加固 + 15 项归档可靠性回归）|
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
- **MySQL 数据层（新增，纯增量）**：`archive_api.py` 提供只读 `GET /api/archive.json`（已在 app.py 注册蓝图）；`archive_data.py` 从环境变量 `DB_*` 读 `research_achievement` 表，**凭据缺失或查询失败时返回空数组**，前端自动保留静态示例数据；`schema_archive.sql` 为幂等建表脚本（`CREATE TABLE IF NOT EXISTS`，不影响现有表）。当前未配置凭据 → API 返回 `source:static`。
- **复用现有认证与路由，不新增数据库表、不改 schema、不动认证机制**。
- **状态：2026-11-25 已增量部署上线**：先在服务器备份代码（`/root/bnu-register-backups/20261125T050137Z/code.tar.gz`），再 SFTP 上传 6 个新文件、在服务器 app.py 精确插入 9 行（未覆盖含并行改动的本地 app.py），`py_compile` 通过后 `systemctl restart bnu-register`。核验：`/` 302→`/register`、`/archive` 200、`/api/archive.json` 200、`/register`/`/login` 200，错误日志无异常；仅一条预期 warning——应用账号 `studentapp` 无权读 `research_achievement` 表（表尚未建），API 已按设计回退 `source:static`。

### 1.2 2026-11-25 新增：项目主线转向 idea 社区 + 五子棋生产下线

- **主线转向**：hi 于 2026-11-25 拍板，以「idea 社区」为项目新主线——成员发布想法、收藏/点赞/评论讨论、AI 分类/摘要/去重、点作者加好友私聊协作、成果展示；好友 IM 与小鲸 AI 作为底层能力继续保留。统一以 `idea` 为内容对象，复用现有认证、好友、AI 能力，不新建独立系统。完整方案见工作区 `idea-community-architecture.md`；架构决策以 `PROJECT_CHARTER.md` §12 ADR 为准。
- **Phase 1 已部署（2026-11-25）**：新增 5 张表脚本 `schema_idea.sql`（idea / idea_favorite / idea_like / idea_comment / idea_ai_job）、`register/ideas/` 包（routes / store；ai_tasks 属 Phase 3 暂未建）、想法广场前端（3 模板 + `idea.css?v=1` / `idea.js?v=1`）。本地验证：编译通过、Jinja2 模板通过、mock 路由 10/10 通过、现有 pytest 102 passed 无回归、安全扫描无 SQL 拼接与敏感信息。服务器备份（`/root/bnu-register-backups/20261125T060615Z/code.tar.gz`）后增量上传 9 个文件、app.py 接入蓝图、导航改造，`py_compile` 通过、服务 active；未登录访问 `/ideas` 302、`/api/ideas` 401 符合预期。**数据库表尚未创建**（需 MySQL 凭据授权，见 §13），因此登录后列表为空、发布会失败——这是待办，不是 bug。
- **五子棋生产已下线（2026-11-25）**：hi 判定五子棋"没啥用"，**只在服务器下线**——先备份代码（`/root/bnu-register-backups/20261125T055948Z/code.tar.gz`，含 `games-disabled/` 归档），再在服务器 app.py 的 `games_page` 插入 `abort(410)`、注释 `init_games(app)`，导航去掉对战入口；**不物理删除 `/opt/bnu-register/games/`**，代码完整保留在本地仓库，可随时恢复。核验：`/games` 登录后 410、未登录 302；其他路由正常。**不要删除本地 `games/` 代码。**
- **口径说明**：本文及总纲中涉及五子棋"已部署/在用"的历史描述，以 `PROJECT_CHARTER.md` §12 的 2026-11-25「五子棋生产下线」ADR 为准；idea 相关代码位于 `register/ideas/` 与 `register/schema_idea.sql`。

---

## 2. 当前真实开放问题（按优先级）

### P0 — 原阻塞项，2026-11-19 已全部解除

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

### P1 — 产品决策阻塞

**2.3 `neko-world-complete-starter`（Mochi）与现有小鲸的关系未定**
- 现状：项目内有一个独立 AI companion starter（20 个文件，自带 README，定位是"functional starter, not production-secure multi-user product"）。现有 `register/` 的 AI 人设、对话、对战、像素场景全部基于"小鲸"。
- 未决：Mochi 是替换小鲸形象、与之并存、还是仅作参考？
- 影响：直接决定 UI、身份设定、Soul 系统与数据库设计。
- 建议：产品方先拍板，再决定是否集成。**不要盲目合并两个项目**——现有 `register/` 成熟度远高于 starter。

### P2 — 工程缺口

| 问题 | 证据 | 建议 |
|---|---|---|
| 无自动备份 | 已有 `register/deploy/backup_mysql.sh`，但无调度 | 上线前建定时 mysqldump + 异地存储 + 恢复演练 |
| 依赖漏洞与生产解释器漂移 | 本地/CI 为 Python 3.13，**生产 venv 为 3.10.12**；Pillow 13.0.0 要求 `>=3.11`，故固定 `12.3.0` | 已改用应用层加固压缩攻击面，并在 README §1 记录版本差异；要修完剩余 36 条 Pillow 告警须先升级生产 Python，需 hi 拍板 |
| Node.js 20 action 弃用 | 已升级到 node24 版 action（checkout v7.0.1 / setup-python v7.1.0 / setup-node v7.1.0），run `44513024675` 起警告消失 | 无需跟进 |
| audit job 长期红 | `pip-audit` 仍有 51 条（Pillow 36 + Flask / cryptography / pytest 15），按 `continue-on-error` 不阻断 | 建议改成分级（高危才失败），避免长期红灯钝化告警 |
| 生产同步 worker，WebSocket 退化长轮询 | `deploy.py` gthread worker | 待拍板后切 `GeventWebSocketWorker` + nginx Upgrade |
| 服务器 SSH 密钥未轮换 | 总纲标"待 hi 拍板" | 安排轮换并更新部署脚本 |
| DNS 重绑定仅部分缓解 | `_base_url_safe()` 校验时解析一次，`requests.post` 重新解析 | 公网化前 pin IP（自定义 adapter + Host 头 + server_hostname）|

### P3 — 信息项

- 域名已买但**未 ICP 备案**，项目**不公网开放**，只走 SSH 隧道，安全组仅 22 端口。这是刻意的安全姿态。
- `bnuailab.conf` 是**备案后公网化的预置模板，未启用**。里面 XFF 覆盖、Upgrade、HTTPS 相关配置当前不生效。

---

## 3. 必要提示（务必遵守）

### 安全红线

1. **禁止在已有数据的服务器上重跑全量 `deploy.py`** —— 每次生成新 `SECRET_KEY` 覆盖 `.env`，导致 session 全失效、已存 BYOK API Key **永久无法解密**。日常更新只用 `deploy_incremental.py`。
2. **ICP 备案 + HTTPS 之前，不要开放任何公网端口**。当前明文 HTTP 靠 SSH 隧道加密。
3. **凭据不落盘**：密钥/密码只从环境变量读，不写进代码或提交。
4. **ProxyFix 信任链三前提**：gunicorn 只 bind `127.0.0.1:8081`；nginx 唯一公网入口且 XFF 用 `$remote_addr` **覆盖**（非追加）；中间只有一层代理。任一变化会让 admin 白名单与限流静默失效。

### 操作约束

5. **gunicorn 保持 `--workers 1`**：限流字典、验证码、登录失败计数、对局房间都在进程内存，加 worker 会全部失效。扩容前先迁外部存储。
6. **schema 迁移不能乱序**：`schema.sql` 优先，其余按文件名排序。`schema_chat_migrate.sql` 会删除重复好友申请（每组留最小 id），执行前先备份。
7. **头像目录属主必须 `regweb`**：全量部署后补 `chown -R regweb:regweb /opt/bnu-register/var`，否则上传静默失败。
8. **改静态文件必须递增模板 `?v=N`**：否则浏览器用缓存旧代码。当前值见 `README.md §4A`。
9. **CRLF 文件（home.html、app.py）用编辑器逐处改**，别用 Python 脚本批量重写（会把 CRLF 换成 LF，产生整文件噪音 diff）。

### 协作约定

10. **新功能进 `register/`**，游戏代码进 `register/games/`，禁止新建无语义目录。
11. **改架构先改 `PROJECT_CHARTER.md`**，记录决策再动代码。
12. **删除前先备份、先列表、先确认**，移到回收站，不永久删除。
13. **成果展示页数据与 UI 集中在 `templates/archive.html` + `static/archive.*`**：当前为前端静态示例数据，换真实研究资料只需改模板内的数据数组（不动后端 / DB）；改这些静态文件时记得递增模板里的 `?v=N`。
14. **idea 相关代码集中在 `register/ideas/` 与 `register/schema_idea.sql`**（Phase 1 新增、未部署）：新功能照此归位，不要散落到 `app.py` 或 `static/` 根。**五子棋不要删除本地 `games/` 代码**——用户明确要求代码保留在本地仓库、可随时恢复；生产下线只禁用服务器入口，不物理删除目录。

---

## 4. 协作方式建议

- 协作者做架构评判时，请以**源码 + git 历史**为依据，不要仅凭文档快照——本项目文档曾落后于代码，现已修正，但旧快照仍在流传。
- 现有 AI 流式通道是 SSE，情绪标记（`[[emo:xxx]]`）已驱动前端小鲸换表情（`im.js reactMood()`）。若设计 avatar 事件，应**扩展现有 SSE**，不要为每句话另发 AI 请求，也不要把 Socket.IO 挪作通用推送通道——它只负责对局。
- 每次交付后请明确标注"已修/待办"，避免反复报同一问题。

---

## 5. 快速自查命令

```bash
cd D:/MySQL
pytest register/tests/ -q          # 应 90 passed
python -m compileall -q register webapp scripts
node --check register/static/im.js
node --check register/static/game.js
python webapp/tests/selftest.py
bash -n register/deploy/backup_mysql.sh
git status --short                 # 提交后应为空
```

部署（需 `MYSQL_PW` 与服务器备份确认；本轮已实跑验证，日常更新沿用此链路）：

```bash
MYSQL_PW=xxx python register/deploy/deploy_incremental.py
```
