# 项目速查

> 面向北师大 AI Lab 的 Flask Web 系统集合，部署于阿里云 ECS，MySQL 8.0 后端。
> **项目主线为「idea 社区」**（发布 idea / 收藏讨论 / AI 辅助 / 好友协作 / 公开分享的 idea）；**五子棋已从生产下线，代码本地保留、可回滚**。
> **架构与决策的唯一事实来源是 [`PROJECT_CHARTER.md`](PROJECT_CHARTER.md)**，本文只做导航、操作红线与上手，冲突时以总纲为准。
> 最后核对：2026-11-27。**当前交付基线**：总纲升级内容已部署 ECS，本地 register 全量 **205 passed**，部署专项 **13 passed**，webapp 离线自测 **51 passed / 0 failed**。register 已按 9 个幂等迁移完成生产迁移、备份、切换与 53 项验收，webapp 已完成最小增量同步；两服务 `.env` 哈希未变、仍为单 worker 回环监听。真实浏览器视觉与完整登录态异常矩阵、CI、72h soak、恢复演练及公网开放仍未执行。

---

## 1. 了解

**项目主线（2026-11-25 起）**：以「idea 社区」为核心——成员发布 idea、收藏/点赞/评论讨论，AI 辅助分类/摘要/去重，点作者加好友私聊协作，公开分享的 idea 在学习分享室（公开分享墙）对外展示；好友 IM 与小鲸 AI 作为底层能力保留。统一以 `idea` 为内容对象，复用现有认证、好友与 AI，不新建独立系统。**2026-11-26 历史生产版本**包含 Phase 1/2 与当日复审修复，已完成备份、迁移、上传、重启和基础验收。**2026-11-27 本轮升级**已在主树完成六类分类、昵称搜索、作者并发编辑、独立治理与审计、后台单条撤销/恢复、个人主页/收藏、互动/删号行锁、AI 派生物失效、验证码与 SSRF 加固、分享室交互修复、后台 2FA 邮箱确认与 Key 删除确认、空库 schema 顺序及精确迁移校验，并已部署 ECS。**五子棋已在生产下线**（代码本地保留，详见总纲 §12 ADR）。完整方案见工作区 `idea-community-architecture.md`。

> **交付原则（2026-11-19）**：安全稳定是底线，同时完成总纲中已明确的核心功能——五子棋 AI 对战、离线邀请、新手引导已落地并完成服务器增量部署核验；后续游戏经 hi 拍板暂缓。不无边界扩张；先本地实现与回归验证，生产变更另行确认。

业务域：

| 目录 | 是什么 | 状态 |
|---|---|---|
| `webapp/` | 学生信息管理（CRUD + 统计） | 稳定，仅做安全修复 |
| `register/` | 注册与社区：实名注册、好友 IM、小鲸对话、管理后台、**idea 社区**、学习分享室（公开分享墙）；五子棋已生产下线（代码保留） | 主演进主体；2026-11-27 升级已部署并通过生产验收 |
| `neko-world-complete-starter/` | 独立的 AI companion starter（自带 README / `.env.example`） | 参考项目，勿混改 |
| `sql/` `scripts/` `backup/` | 建表/导入脚本、ECS 运维工具、密钥与数据备份 | 支撑 |

**技术栈**：Python 3.13（本地 / CI）· **Python 3.10.12（生产 `/opt/bnu-register/venv`）** · Flask 3.0.3 · PyMySQL 1.1.1 · gunicorn 22.0.0（单 worker）· 阿里云 ECS · Socket.IO 4.8.1。

> ⚠️ **本地/CI 与生产解释器版本不一致**：选依赖版本前必须核对生产的 `requires_python` 与 cp310 wheel 是否存在，否则会出现「CI 装得上、生产装不上」。例如 Pillow 13.0.0 要求 `>=3.11`，生产 3.10 无法安装，故 `register/requirements.txt` 固定为 `12.3.0`（3.10 可用的最高版）；详见 §4A。

### 当前安全姿态（重要 · 2026-11-27 更新）

- **ICP 备案已完成**，`bnuailab.tech` 的 A 记录已解析到 `47.118.28.10`。
- **公网化进行中，尚未开放**：ECS 安全组仍仅放行 22 端口，80/443 不通；访问仍只通过 SSH 隧道。不要提前认为站已上线。
- `register/deploy/bnuailab.conf` 是原 HTTP 预置模板（未启用）；HTTPS 版模板见 `register/deploy/bnuailab.conf HTTPS版.template`（含 443、HSTS、Upgrade、XFF 覆盖）。
- **公网化前置清单**（详见工作区 `公网化整改操作手册.md`）：① 申请 SSL 证书并配 443；② 安全组限源 IP 灰度放行 80/443；③ 复核本轮已部署的安全升级与代理信任链；④ 复核管理员 2FA 邮箱与真实邮件收码；⑤ 本机 DNS 换 114（阿里云 223.5.5.5 对该域解析超时）。
- **生产历史状态（2026-11-26 21:08）**：已部署服务端哈希挑战、错误/发送限制、一次性消费、可撤销会话与换邮箱确认；基础核验通过，`.env` SHA-256 未变。**本轮（2026-11-27）已部署**注册验证码服务端邮箱/IP/challenge 限流与原子消费、图形验证码频率/容量/增量清理、SSRF 非 global/CGNAT/IPv6 拒绝与 IP pin/Host/SNI/证书/禁代理重定向等加固。真实邮件收码、异常路径和登录态完整验收仍未全部完成，公网开放前必须补齐。
- **HTTPS 仍未配置，公网仍未开放**；公网化前不要录入真实个人信息，上线必须走 HTTPS。

各子系统的详细说明见 `webapp/README.md`（安全设计、部署、运维命令齐全）。

---

## 2. 怎么访问

双击项目根目录下的批处理文件，它会自动建立 SSH 隧道并打开浏览器：

| 入口 | 本地地址 | 说明 |
|---|---|---|
| `打开学生管理.bat` | `http://127.0.0.1:8080` | 学生信息管理 |
| `打开注册系统.bat` | `http://127.0.0.1:8082/register` | 注册与社区（本地 8082 → 服务器 8081）；原 `/games` 对战大厅**已下线**（服务器入口禁用，代码本地保留） |
| idea 广场 | `http://127.0.0.1:8082/ideas` | idea 广场；Phase 1/2 与 2026-11-26 筛选、排序、标签修复已部署 |
| 学习分享室（新增） | `http://127.0.0.1:8082/archive` | **学习分享室（公开分享墙，数据与领域头条同源）**，公开可访问；**根路径 `/` 行为不变**（未登录仍跳 `/register`、已登录跳 `/home`） |

双击 `打开注册系统.bat` 后，可在 `http://127.0.0.1:8082/archive` 查看学习分享室。Phase 2 已把公开数据源统一为 `idea` 表的 `published + public` 子集；2026-11-27 版本额外过滤 `moderation_state='active'`，治理升级已部署。数据库不可用时返回空结构，不再回退写死的示例卡片。生产 `/api/archive.json` 已验收返回 `source=mysql` 与 3 条公开数据。

关闭窗口即断开隧道、页面失效。手动等价命令：

```bash
ssh -N -L 8080:127.0.0.1:8080 root@47.118.28.10   # 学生管理
ssh -N -L 8082:127.0.0.1:8081 root@47.118.28.10   # 注册系统
```

前提：本机 SSH 私钥可用，服务器安全组仅放行 22。

### 生产拓扑与当前服务

当前没有面向公网的 Web 入口。浏览器先连接本机回环端口，再由 SSH 加密隧道转发到服务器回环端口：

```text
浏览器 → 127.0.0.1:8082 → SSH 隧道 → 127.0.0.1:8081 → bnu-register
浏览器 → 127.0.0.1:8080 → SSH 隧道 → 127.0.0.1:8080 → student-web
```

| 组件 | 生产路径 / 监听 | 运行身份 | 说明 |
|---|---|---|---|
| `bnu-register` | `/opt/bnu-register` · `127.0.0.1:8081` | `regweb` | Gunicorn `--workers 1 --threads 4`；会话、验证码与限流状态在进程内，禁止直接增加 worker |
| `student-web` | `/opt/student-web` · `127.0.0.1:8080` | `studentweb` | Gunicorn `--workers 1 --threads 8`；仅回环访问 |
| Nginx | 主站与 `student-web` 站点均绑定回环 | 系统服务 | 生产模板已统一使用 `$remote_addr` 覆盖 XFF；`nginx -t` 已通过 |
| MySQL | `127.0.0.1:3306` | MySQL 服务 | Web 应用使用 `studentapp@127.0.0.1` 最小权限账号，不使用 root |

**2026-11-27 发布结果**：register 完成 9 个幂等迁移、代码/数据库备份、分阶段切换与 53 项最终验收；webapp 完成应用与 Nginx 最小增量同步。两服务 `.env` 的 SHA-256 均未变化，未轮换共享数据库密码或 `SECRET_KEY`，未修改安全组，也未重新执行全量初始化安装。

**回滚资产**：register 备份位于 `/root/bnu-register-backups/20261127T051731Z`，旧代码保留在 `/opt/bnu-register-rollback-4497d88fdaef`；webapp 最终备份位于 `/root/student-web-backups/20261127T052741Z`。这些备份尚未做恢复演练，不能把“备份存在”等同于“恢复已验证”。

---

## 3. 目录地图

```
D:/MySQL/
├── PROJECT_CHARTER.md      总纲（唯一事实来源，先读这个）
├── README.md               本文件：5 分钟速查
├── webapp/                 学生信息管理  → 详见 webapp/README.md
├── register/               注册与社区（演进主体）
│   ├── app.py              路由入口
│   ├── db.py               数据访问层
│   ├── admin.py            管理后台蓝图
│   ├── schema*.sql         18 个基础/增量脚本（含幂等迁移）
│   ├── games/              对战子系统：生产已下线，源码保留
│   ├── tests/              pytest 回归测试
│   ├── templates/          Jinja2 模板（home.html 等）
│   │   ├── archive.html    学习分享室（公开分享墙）
│   │   └── ideas_*.html    idea 广场、发布与详情
│   ├── static/             JS/CSS；im.js 为当前 IM 入口
│   │   ├── archive.css     公开分享墙样式（?v=4）
│   │   ├── archive.js      公开分享墙脚本（?v=5）
│   │   ├── idea.css        idea 页面样式（?v=5）
│   │   ├── idea.js         idea 页面脚本（?v=4）
│   │   └── content_profile.js 我的主页脚本（?v=3）
│   ├── archive_api.py      公开只读 API 蓝图（GET /api/archive.json）
│   ├── archive_data.py     公开数据层（读取 idea 的 published+public+active 子集）
│   ├── ideas/              idea 社区路由、数据访问、分类常量与治理服务
│   │   ├── constants.py    固定六类 code / 中文名 / 顺序的单一事实来源
│   │   └── moderation.py   单条撤销/恢复、版本校验与 append-only 审计
│   ├── schema_idea.sql     idea 社区 5 张表（含治理、版本与分类原值字段）
│   ├── schema_tags.sql     标签字典与 idea-标签关联
│   ├── schema_category.sql 固定六类与 category_legacy 历史分类迁移
│   ├── schema_moderation.sql 独立治理字段与 append-only 审计表
│   ├── schema_profile.sql  个人主页/收藏排序索引
│   └── deploy/             ECS 部署脚本（全量 / 增量 / nginx 模板）
├── sql/                    数据脚本（含真实学生数据，归档后不再改）
├── scripts/                Windows 本地运维（ECS 探针等）
├── backup/                 密钥与备份（含敏感文件，禁止外传）
├── _ref/                   评审与整改方案归档（只读参考，不参与运行时）
│   ├── 架构评审报告.md       2026-11-25 架构评审：问题分级与改进建议
│   ├── 域名访问诊断报告.md    bnuailab.tech 打不开的根因与安全隐患
│   ├── 公网化整改操作手册.md  证书 / 安全组 / nginx / SSRF / 二次认证 操作清单
│   └── 宝塔面板404诊断.md     /firewall/overview 404 的原因与两层防火墙辨析
└── 打开*.bat               SSH 隧道入口
```

> `_ref/` 内的方案文档是**参考件，不是事实来源**；架构决策仍以 `PROJECT_CHARTER.md` 为准，方案落地状态以源码与 pytest 为准。

**准入规则**：新功能进 `register/`；游戏代码只进 `register/games/`；禁止新建 `temp/`、`new/`、`copy/` 等无语义目录。详见总纲 §4。

---

## 4. 当前状态

### 已完成

> **五子棋说明（2026-11-25 决策，已执行）**：以下五子棋相关条目均为**历史交付记录**——五子棋已在生产下线，代码完整保留在本地仓库、可随时恢复，不物理删除 `games/` 目录。以总纲 §12 ADR 为准。

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
- **生产依赖同步（2026-11-19，选项 1）**：服务器已装 Pillow `12.3.0`（3.10 可用的最高版）；当日无数据库迁移，故按增量脚本第 3–7 步做等价最小同步，跳过 DB 步骤。
- **对局归档可靠性与状态机修复（2026-11-20）**：归档失败不再静默销毁房间（保留 `moves` 唯一副本 + 完整着法写日志可人工补录），上线/刷新邀请时自动补偿重试，成功后才释放房间；未归档房间禁止被覆盖开新局，`sweep` 也不会清理它们。房间因重启消失时凭 `game_invite` 重建并校验邀请归属/好友关系/会话，消除死邀请；已落子的活跃棋盘不再被重新邀请复用；认输/AI 异常收局同样纳入归档流程。AI 困难档搜索加节点预算，避免一次落子长占线程。新增 15 项回归，累计 **90 项 pytest**（8 个文件）全过；**2026-11-20 20:10 已增量部署生产**，`.env` 未变、服务 active、路由与静态资源全通。
- 基础 SQL 参数化、Jinja2 转义、CSRF、安全响应头已具备；**2026-11-27 本轮安全与功能升级已完成本地回归与生产部署验收**。真实浏览器、完整登录态异常路径、定时备份与恢复演练仍是残留风险，不能概括为“全部安全”。
- **学习分享室与 idea 社区**：`GET /archive` 渲染 `archive.html`，`GET /api/archive.json` 提供公开只读数据；公开数据源统一为 `idea` 表 `published + public + active` 子集，并增加标签字典、关键词搜索和公开字段白名单。公开详情返回完整 `content`，卡片只展示 120 字 `summary`；占位“研究方法/发现/意义”已删除。
- **安全、idea 与学习分享室修复（2026-11-26，历史生产交付）**：后台 2FA 改为服务端哈希挑战、5 分钟有效、单挑战最多 5 次错误、IP 限发、一次性消费、可撤销会话与换邮箱确认，改密同时撤销该管理员全部待验证挑战；idea 修复输入校验、标签字典、历史标签回填、公开统计、筛选竞态和分页；学习分享室修复完整正文投影与安全正文渲染。**历史测试结果：131 passed**；ECS 完成备份、6 个幂等迁移、代码上传、生产 Python 3.10 编译和重启后基础验收。
- **总纲升级与 bug 修复（2026-11-27，已部署）**：固定 `ai/edu/bio/energy/math/other`，未知历史分类保留 `category_legacy` 后归 `other`；昵称搜索；作者编辑 `row_version` 乐观并发；独立 `moderation_state`、append-only `idea_moderation_log`、`request_id + 载荷指纹` 幂等；后台单条撤销/恢复与 `no-store`，撤销作者只读、非作者不可见、private 后台不展示标题/正文/标签，仅展示处置所需元数据；登录态 `/profile` 与 `?view=favorites`；点赞/收藏/评论/删号共享用户行锁，删号同事务清互动并重算计数；内容变化清空 AI 派生物；注册验证码与图形验证码资源加固；SSRF 边界与连接 pin；分享室键盘/焦点/错误/窄屏修复；后台 2FA 邮箱确认与账号 Key 删除确认；空库 schema 顺序与增量精确列/索引校验。**当前基线：全量 205 passed，部署专项 13 passed。**

### 当前交付 / 待验收（2026-11-27）

1. **本轮功能已实现并部署**：§4「已完成」列出六类分类、昵称搜索、并发编辑、治理、个人主页、互动/删号一致性、验证码、SSRF、分享室与后台交互、空库/迁移校验；本地 register **205 passed**、部署专项 **13 passed**，生产最终验收 **53 项通过**。
2. **生产迁移与回滚备份已完成**：9 个幂等迁移按依赖执行，并在隔离库重复演练；register 备份 `/root/bnu-register-backups/20261127T051731Z`，webapp 最终备份 `/root/student-web-backups/20261127T052741Z`。旧 register 版本保留在 `/opt/bnu-register-rollback-4497d88fdaef`。
3. **真实浏览器与异常路径仍未做**：需补完整登录态可见性矩阵、真实邮件/2FA 异常路径及桌面/窄屏/键盘交互；本地 mock 浏览器仅完成结构、DOM 与交互冒烟。
4. **交付门槛未完成**：CI、72h soak、备份恢复演练、HTTPS/公网开放均未执行；公网保持关闭。
5. **webapp 安全补丁已同步生产**：XFF 覆盖、回环监听、写前熔断、无 `--force`、强制验收均已落实；生产 `nginx -t`、模板一致性、监听与 HTTP 响应验收通过。已有服务器继续禁止重跑初始化脚本。
6. **Mochi starter 已定案**：按 2026-11-19 ADR 保持独立，仅作参考，不整合、不替换小鲸；不再是产品阻塞项。若未来改变定位，须新 ADR。
7. **服务器 SSH 密钥轮换**：尚未执行，需 hi 拍板。
8. **后续游戏暂缓**：中国象棋 / 国际象棋 / UNO 不扩张；五子棋生产下线、源码保留。AI 结构化任务、公开作者页、命名收藏夹与置顶内容仍后置。

### 4C. 2026-11-26 复审与修复状态（历史生产记录）

> 本节保留 2026-11-26 实际发生的问题、修复和部署证据，不代表 2026-11-27 当前代码状态；后续状态以 §4D 为准。

> 2026-11-26 当日已连接 ECS/MySQL，完成备份、6 个幂等迁移、代码上传、生产编译和用户手动重启；**未提交或推送**。基础生产验收通过，但未完成真实浏览器、完整登录态可见性矩阵和 2FA 异常路径验收。

| 等级 | 问题 | 状态 / 证据与影响 |
|---|---|---|
| 严重 | 后台邮件验证码存入 Flask 默认会话 Cookie | **已修复并部署**：`register/admin.py` 改为服务端随机挑战与 SHA-256 哈希；验证码不再进入 Cookie，服务端后台会话可撤销 |
| 高 | 后台 2FA 缺少错误次数限制，数据库异常会降级为仅密码，换邮箱不验证新邮箱 | **已修复并部署**：5 分钟有效、单挑战 5 次错误、每 IP 每小时 5 次发送；邮箱/数据库/邮件异常 fail-closed；新邮箱确认前保留旧值；改密撤销该管理员全部会话与挑战 |
| 严重 | `webapp` 一键部署脚本不可用于已有服务器 | **2026-11-26 历史状态：未修复；2026-11-27 已修复、复核并同步生产模板**：`deploy.py` 与 `install.sh` 现为无 `--force` 的空环境初始化，写前只读熔断；不轮换共享密码、不重置 `SECRET_KEY`、不改 UFW、不回显凭据。已有服务器仍禁止执行，日常更新须走保留配置的增量流程 |
| 高 | `register` 增量部署清单落后于 Phase 1/2，且失败不一定中止 | **已加固并按等价分步流程部署**：递归上传清单覆盖 idea/tag/archive，按依赖执行幂等迁移，先备份；远程退出码、表列、`.env` 哈希、依赖、服务、8081 纯回环监听、HTTP 与错误日志均有断言。本次为避免不必要扩权，保留原有 86 项表权限 |
| 高 | idea 广场筛选、搜索、排序与详情计数存在确定性功能错误 | **本地已修复**：分类改读 `/api/categories`，关键词与精确标签分离，服务端 hot/new 排序，请求序号防竞态、分页防重复，详情按 `data.idea` 更新计数 |
| 中 | idea 输入校验与数据库结构不一致 | **本地已修复**：分类限制 30 字；创建/更新/评论拒绝非对象 JSON；标签类型、长度、数量与大小写重复均有校验 |
| 中 | 标签字典尚未成为唯一读路径 | **2026-11-26 本地已修复并部署**：仅 active 标签进入关联、兼容串、搜索与公开导航；迁移幂等回填历史 `idea.tags`，不重启停用标签；删除 idea 清理关联；当日公开统计过滤 `published+public`，2026-11-27 再增加 `moderation_state='active'`，已部署 |
| 中 | 学习分享室正文被截断并用空白字段拼占位详情 | **已修复并部署**：公开 API 同时返回卡片 `summary` 与完整 `content`；前端只渲染完整正文，保留换行并仅对 HTTP(S) 链接做安全 linkify；当日生产静态版本为 `archive.js?v=4` / `archive.css?v=3`，2026-11-27 当前本地版本已升至 `archive.js?v=5` / `archive.css?v=4` |
| 中 | 学习分享室键盘、焦点与 API 故障处理不完整 | **2026-11-26 历史状态：未修复**；2026-11-27 已本地修复并通过回归，真实浏览器待验 |
| 高 | 待归档游戏房间超过 24 小时后可能无日志丢失 | **既有问题，2026-11-26 当日未改、当前仍未改**：`register/games/manager.py:86-88` 的 `get_room()` 直接删除过期房间，绕过 `sweep()` 的完整棋谱错误日志；`claim_archive()` 也绕过了 `get_room()` 的过期检查。恢复游戏前应统一过期清理并补测试 |
| 中 | 验证码资源与尝试次数限制可被规避/放大 | **2026-11-26 历史状态：未修复**；2026-11-27 已本地实现服务端邮箱/IP/challenge 限流、原子消费及图形验证码频率/容量/增量清理，待真实 MySQL 验收 |
| 中 | `webapp` 代理后所有客户端 IP 都变为 `127.0.0.1` | **2026-11-26 历史状态：未修复；2026-11-27 已修复并同步生产**：两套 Nginx 模板均用 `proxy_set_header X-Forwarded-For $remote_addr` 覆盖上游头；selftest 与生产 `nginx -t`、监听、HTTP 验收通过 |
| 中 | 备份、恢复与解释器一致性仍不完整 | **部分修复**：增量部署增加部署前代码/数据库备份及完整性断言；仍无定时/异地备份和恢复演练，生产 3.10.12 与本地/CI 版本漂移未消除 |

**历史实际验证（2026-11-26）**：Python `compileall`、全部 JS `node --check`、备份脚本 `bash -n`、`git diff --check` 通过；`uv run --with-requirements register/requirements.txt python -m pytest register/tests -q` 为 **历史结果 131 passed**，覆盖 admin 2FA、idea/archive、部署清单和既有模块。生产侧完成 `/root/bnu-register-backups/20261126T123618Z/` 代码与数据库备份，执行 game → message → game_ai → admin_2fa → idea → tags 六个幂等迁移，上传 84 个源码文件并用 Python 3.10.12 编译通过；用户于 21:08 手动重启。核验服务 active、仅 `127.0.0.1:8081` 监听、`.env` SHA-256 未变、关键路由状态正确、日志无 Traceback/CRITICAL，`/api/archive.json` 的 idea 43 返回 1128 字完整正文。浏览器连接器仍不可用，未声称完成真实浏览器验收；完整登录态可见性矩阵与 2FA 异常路径仍待补验。

### 4D. 2026-11-27 当前交付状态与残留风险

| 事项 | 当前事实 | 下一步 |
|---|---|---|
| 代码与测试 | 主树本地实现；register 全量 **205 passed**，部署专项 **13 passed** | 保持单 worker；后续变更继续回归 |
| 数据库 | 9 个幂等迁移已执行并通过列、索引、分类与精确表权限校验；隔离生产副本演练重复执行通过 | 继续验证并发、缓存与审计业务语义 |
| 内容治理 | 独立 active/revoked、`row_version`、append-only 审计与请求幂等、单条后台撤销/恢复已部署；private 后台不展示标题/正文/标签，仅展示处置所需元数据 | 真实 MySQL 审计权限、并发、缓存、private 元数据最小化与浏览器验收 |
| 个人内容 | `/profile` 双视图、`?view=favorites` 直达、`private, no-store`；互动与删号按用户行锁串行并重算计数，已部署 | 并发与完整可见性矩阵验收 |
| 安全 | 注册/图形验证码、SSRF 与后台交互加固已部署 | 真实邮件、异常路径、SSRF 回归与浏览器验收 |
| webapp | 安全补丁与 Nginx 模板已同步生产，离线自测 **51 通过 / 0 失败**；回环监听、`nginx -t`、HTTP 与 `.env` 哈希验收通过 | 后续变更继续走最小增量；现有服务器禁止重跑初始化脚本 |
| 运维交付 | 生产备份与自动回滚链路已验证；未触发 CI、未做 72h soak、备份恢复演练、HTTPS 或公网开放 | 全部完成并单独授权后方可公网化 |

### 已知限制

- 项目按**对外产品**标准验收（稳定长跑、可恢复、可监控），不因当前规模小降级；质量门槛见总纲 §10.1。
- 当前 HTTP 明文传输（靠 SSH 隧道加密）。公网化前必须上 HTTPS，不要录入真实个人信息。
- CI 只做回归测试、静态检查和非阻断依赖审计，不部署。历史 run `44518300890` 曾总体 Success；**2026-11-27 当前本地 register 基线为 205 passed（部署专项 13 passed），webapp 离线自测 51 通过 / 0 失败；本轮未触发 CI、未做真实浏览器视觉验收与完整登录态异常路径验收**。2026-11-26 的 131 passed 与生产基础验收是历史结果，详见 §4C/4D。
- 已有安全备份脚本，但**尚无定时调度、异地存储与恢复演练**；四个高频 GET 轮询路径已于 2026-11-27 停止写访问日志并随本轮部署同步。
- gunicorn 单 worker；内存限流不支持多 worker 扩容。

完整风险清单见总纲 §11。

---

## 4A. 操作红线（动手前必读）

这几条踩过坑或会造成不可恢复损失，优先级高于具体操作方式。

| 红线 | 后果 | 正确做法 |
|---|---|---|
| **禁止在已有数据的服务器上重跑 `register/deploy/deploy.py`** | 每次生成新 `SECRET_KEY` 并覆盖 `.env` → 全部 session 失效、已存 BYOK API Key **永久无法解密** | 更新走增量链路；换 `SECRET_KEY` = 已存密钥报废 |
| **禁止在已有服务器重跑 `webapp/deploy/deploy.py` 或 `install.sh`** | 旧脚本会轮换共享 `studentapp` 密码与 `SECRET_KEY`、覆盖 Nginx/UFW 并回显凭据；现脚本虽已改为空环境写前熔断，但部署后环境必然触发拒绝 | 只用于确认过的空环境；已有服务器禁止执行，日常更新必须设计保留 `.env`、数据库账号、systemd/Nginx 与监听方式的增量流程 |
| **增量更新仍需先审查并保留配置** | `deploy_incremental.py` 已覆盖 Phase 2 与失败断言；本次按等价分步流程完成生产发布，但脚本的一体化授权范围仍大于最小权限 | 后续先 `--dry-run` 审查清单与迁移；生产执行需单独授权并提供 `MYSQL_PW`，保留 `.env`、systemd/Nginx 和现有最小权限，不得推定未经验证即上线 |
| **`schema_chat_migrate.sql` 会删数据** | 删除重复的 `friend_request`（每组只留最小 id）再加唯一约束 | 执行前先备份该表；迁移顺序为 `schema.sql` 优先、其余按文件名排序 |
| **头像目录属主必须是 `regweb`** | 全量 `deploy.py` 只做 `chown -R root:root`，之后上传头像会静默失败 | 部署后补 `chown -R regweb:regweb /opt/bnu-register/var` |
| **gunicorn 保持 `--workers 1`** | 限流字典、验证码、登录失败计数、对局房间都在进程内存，加 worker 会全部失效 | 扩容前先迁到 Redis 等外部存储 |
| **改静态文件必须递增模板里的 `?v=N`** | 浏览器继续用缓存旧代码 | 2026-11-27 当前模板值：`style.css?v=11`、`im.css?v=10`、`im.js?v=10`、`game.js?v=5`、`app.js?v=5`、`avatar-crop.js?v=3`、`favicon.svg?v=1`、`archive.css?v=4`、`archive.js?v=5`、`idea.css?v=5`、`idea.js?v=4`、`content_profile.js?v=3`；其中 idea 资源版本已随分类、治理、编辑与个人页升级递增；`im.js` 内还硬编码一份鲸鱼头像版本号 |
| **改模板 / CRLF 文件用编辑器逐处改，别用 Python 脚本批量重写** | `newline=''` 会把 CRLF 换成 LF，产生整文件噪音 diff | `home.html`、`app.py` 是 CRLF，需按字节或标记处理 |

### 环境变量与常用命令

**register**：`SECRET_KEY`（必填，缺失拒绝启动）、`DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME`、`SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASS/SMTP_FROM_NAME`、`SITE_URL`（重置邮件链接，默认 `http://127.0.0.1:8082`）、`AI_MODEL`、`AI_BASE_URL`、`AI_API_KEY`、`COOKIE_SECURE`。
**webapp**：`SECRET_KEY`、`COOKIE_SECURE`、`APP_USER`、`APP_PASSWORD_HASH`、`DB_*`。
部署脚本另用 `DEPLOY_HOST`、`MYSQL_PW`、`DB_PW`；SSH key 固定读 `~/.ssh/id_rsa`。

> `register/.env.example` 已入库（仅键名与安全示例，`SECRET_KEY` / `DB_PASSWORD` / `SMTP_PASS` / `AI_API_KEY` 留空）；真实 `.env` 不入库，换服务器按模板手工建。

```bash
# 本地开发（register，端口 8081）
cd D:/MySQL/register && SECRET_KEY=xxx python app.py

# 本地回归：使用 uv 临时依赖环境，不修改 requirements；2026-11-27 当前基线 205 passed
uv run --with-requirements register/requirements.txt python -m pytest register/tests -q
uv run --with-requirements webapp/requirements.txt python webapp/tests/selftest.py  # 51 通过 / 0 失败

# 部署：register 全量仅首次建站；先审查增量清单，生产执行需另行授权
python register/deploy/deploy_incremental.py --dry-run
MYSQL_PW=xxx DB_PW=yyy python register/deploy/deploy.py
MYSQL_PW=xxx python register/deploy/deploy_incremental.py

# 服务与日志
systemctl status bnu-register && journalctl -u bnu-register -f
```

---

## 4B. 公网化前置清单（ICP 备案完成后才做）

备案前**都不需要做，也不要提前开放端口**。备案后若决定开放，按顺序落实：

1. **上 HTTPS**：当前明文传输，不要在 HTTP 下录入真实个人信息。
2. **复核 ProxyFix 信任链**：`x_for=1` 生效的三前提是——① gunicorn 只 bind `127.0.0.1:8081`；② nginx 唯一公网入口，三处 XFF 用 `$remote_addr` **覆盖**（禁止 `$proxy_add_x_forwarded_for` 追加）；③ 中间只有一层代理。前面加 CDN/SLB 必须同步调大 `x_for`，否则 admin 白名单与登录限流静默失效。**"隔离破则白名单破"**；register 与 webapp 生产模板已统一为 XFF 覆盖与回环监听。
3. **复核 SSRF 边界**：本轮已拒绝非 global/CGNAT 与 IPv6，使用 IP pin 并保留 Host/SNI/证书校验、禁代理和重定向，并已部署。系统默认 AI 上游仍需限制为管理员可信配置。
4. **后台 2FA 继续验收**：2026-11-26 历史版本已部署服务端挑战与限制；本轮后台邮箱确认和账号 Key 删除确认已部署。真实邮件、旧 Cookie、撤销与异常路径验收完成前不得公网开放。五子棋已下线，原生 WebSocket 不再是公网化前置项。
5. **补齐备份与恢复**：增量脚本会在服务器本地备份，但仍无定时调度、异地存储和恢复演练；部署前应确认最新备份可用。
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
