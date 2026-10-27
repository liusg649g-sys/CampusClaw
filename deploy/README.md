# Compose 部署与恢复操作

这是补充部署方式，不替代 Windows 根目录的启停 bat。2026-10-22 仅通过 Compose CLI 配置校验；当前 Docker Engine 未运行，以下容器操作尚未实测。不要把本机真实数据库或 `.env` 挂入测试容器。

## 独立启动和停止

在项目根目录执行，`python` 指 Python 3.12。配置目录必须不存在；生成器拒绝覆盖。选择用户私有目录，Windows 请确认 NTFS ACL 仅授权本人和 Docker 所需账户；程序不会修改系统 ACL。POSIX 私有父目录权限 0700，secret 文件可由容器非 root 用户读取。文件式 Compose secrets 不是主机上的加密保险箱。

```powershell
python deploy/init_config.py --output deploy/.local --port 18080
docker compose --env-file deploy/.local/compose.env -f compose.yaml config --quiet
docker compose --env-file deploy/.local/compose.env -f compose.yaml build
docker compose --env-file deploy/.local/compose.env -f compose.yaml up -d --wait --wait-timeout 180
docker compose --env-file deploy/.local/compose.env -f compose.yaml ps
```

浏览器访问 http://127.0.0.1:18080/ 。新卷教师用户名 `teacher`，初始密码在私有 `secrets/teacher_password` 文件中，用本地编辑器查看，勿粘贴到日志。18080 用于隔离验证；Compose 自身默认 8080，可在此独立配置中调整，但不能与本机已占用的 8080 冲突，也不要用 8081。

教师在本班 MCP 管理区域登记稳定标识（如 `mcp-local`）、**地址 `http://mcp:8090`**，令牌使用同一配置目录的 `secrets/mcp_auth_token`，连接后查看工具。`mcp` 是容器网络内服务名；不要填写宿主机 `127.0.0.1:8090`。浏览器仅访问 Nginx，主后端和 MCP 均不发布宿主机端口，Nginx `/mcp` 返回 404。

```powershell
docker compose --env-file deploy/.local/compose.env -f compose.yaml logs --tail 80 backend mcp nginx
docker compose --env-file deploy/.local/compose.env -f compose.yaml stop
docker compose --env-file deploy/.local/compose.env -f compose.yaml start
```

只操作该配置中的随机项目名；停止保留命名卷，不使用删除卷命令。重启后 MCP 状态必须重新握手，历史 connected 不是当前可用证据。诊断先看 `ps` 和健康状态，再查日志；密钥错误不得靠删除数据库解决。模型未配置时网站和管理可使用，AI 请求明确不可用。

## 配置边界

| 配置 | 位置及作用 |
|---|---|
| 签名密钥 | `secrets/token_secret`，稳定 HMAC 签名，不与 MCP 共用 |
| MCP 服务认证 | `secrets/mcp_auth_token`，仅 MCP 和教师登记时后端使用，不回显 |
| MCP 密文加密 | `secrets/mcp_encryption_key`，Base64url 编码 32 字节 AES-GCM 密钥；缺失/错误启动失败 |
| 首次教师密码 | `secrets/teacher_password`，只初始化空卷账号，已有账号不覆盖 |
| 模型设置 | compose.env 的 CHAT_BASE_URL / CHAT_MODEL；密钥仅 `secrets/chat_api_key` |
| 向量设置 | EMBEDDING_BASE_URL / EMBEDDING_MODEL / EMBEDDING_DIM；密钥仅 `secrets/embedding_api_key` |
| 数据根目录 | 容器固定 `/data`，挂独立命名卷；SQLite、teacher_account.json、materials.json、knowledge_chunks.json、material_files 都在其中 |
| MCP 地址许可 | 容器固定精确允许 `http://mcp:8090`；本机模式保持原回环限制 |

空白模型 secret 表示功能未配置；必需的认证/加密 secret 不允许为空。不要将模型密钥写入 Compose 环境、Dockerfile 或真实 `.env`。只编辑本次独立 secret 文件，保留私有目录权限。所有模型配置均显式传入，不自动读取真实 `.env`。

Windows 默认继续 DPAPI，Linux 容器使用 PyCA cryptography AES-256-GCM（随机 nonce、认证标签、固定 AAD、密文版本前缀）。两者不会自动互解或自动迁移。加密密钥备份必须与数据备份分开、安全保存；丢失密钥无法恢复令牌。已有教师账号 JSON 的密码存储沿用原架构，并未改造成密码哈希系统，因此卷和备份仍需严格访问控制。

## 一致备份和空卷恢复

以下 `$backupDir` 必须是新建的用户私有绝对目录。先停**该 Compose 项目**的后端，防止 SQLite 与 JSON/材料跨文件变化；MCP/Nginx 和本机业务服务不需要停止。备份使用 SQLite backup API、integrity_check 和 SHA-256 清单，而非复制正在写入的数据库。

```powershell
$backupDir = (Resolve-Path 'deploy/.local-backups').Path
docker compose --env-file deploy/.local/compose.env -f compose.yaml stop backend
docker compose --env-file deploy/.local/compose.env -f compose.yaml run --rm --no-deps --volume "${backupDir}:/backup" --entrypoint python backend /app/deploy/backup_data.py backup --data /data --archive /backup/business-01.zip --offline-confirmed
docker compose --env-file deploy/.local/compose.env -f compose.yaml start backend
```

先创建 `deploy/.local-backups` 再 Resolve-Path；在 Linux 上须授权 UID 10001 写入此专用目录。目标 zip 必须不存在。备份只包含业务数据，不含密钥；单独安全备份对应 secret。

恢复先复制**非秘密配置文件**为 `restore.env`，只将项目名改成全新的项目名、端口改成空闲端口，secret 路径仍引用原备份匹配的密钥。这样产生新空卷，不覆盖当前卷：

```powershell
docker compose --env-file deploy/.local/restore.env -f compose.yaml run --rm --no-deps --volume "${backupDir}:/backup:ro" --entrypoint python backend /app/deploy/backup_data.py restore --data /data --archive /backup/business-01.zip --offline-confirmed
docker compose --env-file deploy/.local/restore.env -f compose.yaml up -d --wait
```

恢复验证归档路径、文件摘要和 SQLite 完整性，非空目录拒绝恢复。核对账号、班级、材料下载、会话、令牌解密；失败保留原项目及原卷。此流程已在临时目录测试，容器卷恢复尚未验证。

## AES 密钥轮换与未来迁移

仅用于已采用 AES-GCM 的独立卷：停止对应后端，安全生成新的 32 字节 Base64url 密钥文件，不覆盖旧密钥。将旧/新密钥目录只读挂入 `/rotation`，备份目录可写挂入 `/backup`，执行：

```powershell
# 在 compose run 中使用与上面相同的 --env-file、--no-deps 和 --entrypoint python，另加专用目录挂载
# 后端容器中的命令：
# /app/deploy/rotate_mcp_key.py --database /data/assistant.sqlite3 --backup /backup/before-key-rotation.sqlite3 --old-key-file /rotation/old --new-key-file /rotation/new --offline-confirmed
```

工具先验证旧密钥、备份 SQLite，再在事务内重新加密并验证，清除工具缓存和连接状态；失败回滚。成功后才将该环境的活动 secret 替换为新密钥，再启动后端。保留旧库备份和旧密钥；回滚到新空卷使用旧库及旧密钥，不覆盖线上卷。真实密钥轮换本次未执行。

将来从 Windows 迁移必须另行授权：离线一致备份、校验副本、在原 Windows 用户上下文解密副本里的 DPAPI 令牌并用目标 AES 密钥加密，或在目标逐一重新登记令牌；不能直接复制 DPAPI 密文。还要单独导出浏览器 localStorage 的班级/作业等旧前端数据；这些并不在服务端卷中。先在新项目验收，保留原 Windows 数据和启动方式供回滚，本阶段没有实现自动迁移。

## 本次可重复验证

```powershell
python deploy/validate_compose.py --env-file deploy/.local/compose.env --output temp/compose-normalized.json
# 若本机未装容器专用 cryptography，使用已存在的隔离依赖目录或独立虚拟环境，不修改全局环境
$env:PYTHONPATH="$PWD/temp/lesson6-stage4-deps"
python apitest/run_all.py --report-dir apitest/reports/lesson6-stage4-rerun
```

部署测试需要 Docker CLI/Compose 和锁定版本的 cryptography；CLI 校验无需 Engine，但不能代替容器验收。生产镜像只安装 requirements-deploy.txt，临时测试依赖不进镜像。Python/Nginx 基础镜像版本标签尚未锁 digest，构建前需结合目标平台固定经过验证的 digest。
