# 项目交接说明（给外部协作者）

> 目的：让协作者基于**当前真实代码**工作，而不是文档旧快照。
> 事实来源：`git log`、实际源码、`pytest` 结果。最后核对：2026-11-19，HEAD=`acf0b9a`。
> 架构与决策见 `PROJECT_CHARTER.md`，操作红线见 `README.md §4A/§4B`。

---

## 1. 先说清楚：哪些"发现"已经不成立

此前基于文档旧快照提出的问题，以下**已修复**，请勿重复投入：

| 旧说法 | 当前实际 |
|---|---|
| Charter 写 6 个 schema、README 写 9 个 | 已统一为 10 个（新增 3 个幂等迁移），deploy 的 `glob` 全量执行 |
| Charter 13 项测试、README 32 项 | 已统一为 **41 项 pytest**（4 文件），`pytest` 全过 |
| Charter 说"无 WebSocket" | 已改：SSE（AI 流式）+ IM 轮询 + Socket.IO（对局，本地已实现）|
| 无右键菜单 | 已实现引用/转发/删除/多选；且额外加了「⋯」按钮入口（右键在触摸设备和部分浏览器不可靠）|
| SSRF、admin 白名单、headers、终局房间、认输覆盖、AI 扣费、未读误标、UA 转义、和棋、重置令牌竞态…… | 两轮审查共修 26 + 11 项，均已提交 |

**结论**：文档曾落后于代码，现已同步。若你的信息来自更早的快照，请以本文件和源码为准。

---

## 2. 当前真实开放问题（按优先级）

### P0 — 阻塞性

**2.1 本地代码与服务器不同步**
- 现象：用户实测消息右键无效，弹出的是浏览器原生菜单。
- 根因：代码只在本地 `D:/MySQL`，服务器 `/opt/bnu-register` 仍是旧版。我从未执行部署。
- 证据：所有修复仅在本地 git；`deploy_incremental.py` 是唯一同步路径。
- 下一步：需 `MYSQL_PW` + 服务器已备份确认，执行增量部署。**注意：这是运维动作，不是代码问题。**

**2.2 增量部署脚本曾遗漏数据库迁移（已修，但需部署验证）**
- 原问题：`deploy_incremental.py` 只传代码不执行 `schema_message_v2.sql`。新 `db.py` 的 SELECT 含 `quote_id/deleted_by_a/deleted_by_b/forward_from`，老表无这些列 → 同步后消息页 500。全量 `deploy.py` 会重置 `SECRET_KEY`（BYOK Key 永久报废），不能用于救场。
- 已修（提交 `acf0b9a`）：迁移纳入增量脚本，上传代码前校验 4 列存在，缺失即中止。
- 待验证：这个修复本身**尚未在服务器跑过**，需随 2.1 一起验证。

### P1 — 产品决策阻塞

**2.3 `neko-world-complete-starter`（Mochi）与现有小鲸的关系未定**
- 现状：项目内有一个独立 AI companion starter（20 个文件，自带 README，定位是"functional starter, not production-secure multi-user product"）。现有 `register/` 的 AI 人设、对话、对战、像素场景全部基于"小鲸"。
- 未决：Mochi 是替换小鲸形象、与之并存、还是仅作参考？
- 影响：直接决定 UI、身份设定、Soul 系统与数据库设计。
- 建议：产品方先拍板，再决定是否集成。**不要盲目合并两个项目**——现有 `register/` 成熟度远高于 starter。

### P2 — 工程缺口

| 问题 | 证据 | 建议 |
|---|---|---|
| 无自动备份 | README/总纲均标"备份仍缺" | 上线前建定时 mysqldump + 异地存储 + 恢复演练 |
| 无 CI | 全库无 workflow 配置 | 最小 CI：提交跑 `pytest` + `node --check` + `py_compile` |
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

---

## 4. 协作方式建议

- 协作者做架构评判时，请以**源码 + git 历史**为依据，不要仅凭文档快照——本项目文档曾落后于代码，现已修正，但旧快照仍在流传。
- 现有 AI 流式通道是 SSE，情绪标记（`[[emo:xxx]]`）已驱动前端小鲸换表情（`im.js reactMood()`）。若设计 avatar 事件，应**扩展现有 SSE**，不要为每句话另发 AI 请求，也不要把 Socket.IO 挪作通用推送通道——它只负责对局。
- 每次交付后请明确标注"已修/待办"，避免反复报同一问题。

---

## 5. 快速自查命令

```bash
cd D:/MySQL
pytest register/tests/ -q          # 应 41 passed
python -m py_compile register/app.py register/db.py
node --check register/static/im.js
git status --short                 # 应为空
```

部署（需 `MYSQL_PW` 与服务器备份确认）：

```bash
MYSQL_PW=xxx python register/deploy/deploy_incremental.py
```
