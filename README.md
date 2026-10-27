# CampusClaw

本分支保留原有材料、知识库和登录接口，仅补充 GitHub 隐私修复；没有把第五、六课功能合并进旧版 main。

第五、六课已验收版本请使用 [codex/stage-acceptance-20261027](https://github.com/liusg649g-sys/CampusClaw/tree/codex/stage-acceptance-20261027)，固定交付提交为 `1fb1e261d1d434cb4359e1fec48437b46f7e61e7`。其源码、Markdown/HTML/PDF 验收报告保持不变。

## 账号与运行

- 不提供共享默认口令。新建私有教师账号时，从启动进程环境变量 `CAMPUSCLAW_INITIAL_TEACHER_PASSWORD` 读取初始口令；未配置则安全随机生成。
- 账号仅保存在本机私有 `backend/teacher_account.json`，已有账号不会被初始化逻辑覆盖，启动日志不输出密码。
- main 的 Python 程序不会自动读取 `.env`；`.env.example` 只提供变量名称，应由启动终端安全注入，切勿把真实值写进源码、脚本、截图或报告。
- Python 后端仍监听 `127.0.0.1:5000`，Nginx 入口仍为 8080。运行方式见 `README.txt`，本轮没有启动或重启真实服务。

## 隐私修复与历史限制

已移除当前文档、默认账号代码和日志中的固定口令；测试改用临时账号文件及随机凭据。真实环境配置、账号、日志、临时目录、数据库、材料和浏览器抓包不应提交。

**本次为普通追加提交，不会抹除历史。** 旧 main 提交仍有原默认口令；不能把删除当前文件中的内容当作已撤销旧凭据。现有账号是否仍使用该值未读取或验证，应按可能暴露处理。轮换与历史清理步骤见 [隐私修复记录及方案](GITHUB_PRIVACY_REMEDIATION.md)，未经确认不重写历史或强推。
