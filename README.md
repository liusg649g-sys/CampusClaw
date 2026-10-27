# CampusClaw

面向教师与学生的班级教学应用：材料上传与知识库检索、可配置学习智能体、独立 Skill、多轮 SSE 会话，以及受权限和审计约束的 MCP 工具接入。

[阶段性验收报告](STAGE_ACCEPTANCE_REPORT.md) · [HTML报告](STAGE_ACCEPTANCE_REPORT.html) · [PDF报告](output/pdf/STAGE_ACCEPTANCE_REPORT.pdf) · [五项公开合成证据](submission/evidence/) · [第五、六课功能说明](docs/LESSON5_6_SUMMARY.md)

## 技术栈与范围

- Python 3.12 标准库 HTTP 后端、SQLite、JSON/材料文件存储。
- 原生 HTML/JavaScript 教师与学生界面；Nginx 反向代理。
- OpenAI兼容 Chat Completions/Embedding 网关；独立 MCP JSON-RPC HTTP 服务。
- Docker Compose 是补充部署方案；本轮未完成真实容器验收。
- 确定性验证使用 **Mock LLM传输 + 真实本地MCP**，不宣称真实模型调用已通过。

## Windows 本机运行

1. 安装 Python 3.12 和 Nginx，将 `.env.example` 复制为本地 `.env`；按需要填写路径及模型配置。
2. 双击根目录 `启动CampusClaw.bat`，成功后访问 <http://127.0.0.1:8080/assistant.html>；Swagger为 `/swagger`，旧 `/docs` 兼容。
3. 教师初始用户名为 `teacher`。**不提供固定初始口令**：空数据目录首次初始化时使用本地配置 `CAMPUSCLAW_INITIAL_TEACHER_PASSWORD`，未设置则随机生成；账号信息仅存本机私有 `backend/teacher_account.json`。已有账号文件不覆盖，密码不写日志。
4. 结束使用时运行 `停止CampusClaw.bat`。它仅管理本项目启动并记录身份的进程。

直接运行 `python backend/server.py` 时需由终端显式提供环境变量，程序不会主动读取真实 `.env`。本机后端只监听127.0.0.1:5000；不要将调试服务直接暴露到公网。

模型配置为空时管理页面仍可使用，模型请求返回明确配置错误。不要将API Key、登录Bearer或MCP令牌粘贴到GitHub、报告或截图。

## 隔离验证

```powershell
python apitest/run_all.py --report-dir apitest/reports/current
python apitest/export_submission_evidence.py
python apitest/site_route_check.py
```

完整部署测试包含AES-GCM，需要按 `requirements-deploy.txt` 在独立虚拟环境中安装依赖。独立MCP可执行 `python mcp-server/run_tests.py`。报告与临时账号被忽略；公开证据导出器只允许合成JSON body，不导出认证头或数据库。

浏览器fixture需要Node、Playwright及可用Chrome/Edge。`CAMPUSCLAW_PLAYWRIGHT_MODULE`、`CAMPUSCLAW_BROWSER_EXE`可指向本机已有安装。fixture每次随机生成测试口令，仅通过子进程环境传给浏览器，不把口令写入源码。现有本地验收站的私有账号文件不会随仓库发布。

## 教师与学生操作

教师登录后先在服务端准备班级、学生及成员关系，再在智能体管理中建立多个助手，创建/上传技能文件，分别绑定本班技能和材料。学生仅能选择本班启用助手并创建私有会话。技能开关和绑定变更在下一次提问立即生效。

教师MCP管理登记服务器、连接并发现工具，再将 `calculator@server-key` 等引用写入技能。只有命中技能、当前连接和参数校验均通过时才执行；模型提出意图，后端负责授权和调用。当前执行白名单为formula_hint、calculator、unit_convert。

## Compose 与持久化

详见 [部署说明](deploy/README.md) 和 [运行与安全边界](docs/OPERATIONS.md)。默认只发布Nginx回环端口8080；隔离测试可选18080，不占用8081。backend/mcp不发布宿主机端口，数据位于独立命名卷/data。**配置校验通过不等于容器运行通过**。

Windows令牌继续使用DPAPI；Linux容器使用固定版本cryptography的AES-GCM，密钥缺失时关闭而非明文降级。不要直接迁移Windows DPAPI密文到Linux。

## 文档与隐私

本仓库提交源码、规约、空白配置示例和人工选择的公开合成证据。真实 `.env`、账号、数据库、材料、日志、备份、临时验收截图和浏览器抓包均不提交；详见 [提交隐私审计](SUBMISSION_PRIVACY_AUDIT.md)。旧教师账号存储格式沿用兼容实现，须保护本地文件访问权限；学生密码由PBKDF2保存。

本次交付使用独立净化快照分支，保留原main与未提交工作，不强推或改写原历史。历史本地交付记录不作为公开证据。课程后续公开部署、真实模型及真人同伴复核的未完成项均在阶段报告中明确列出。
