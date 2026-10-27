# 运行、安全与报告导出

## 本机运行

参见根README。`.env.example`全部秘密字段为空，复制到本地`.env`后配置；不把本地文件复制回仓库。Windows启动器只加载白名单变量，签名密钥首次生成后保留，重复启动不更换。真实账号文件存在时不会用新默认值覆盖。

新初始化使用显式本地初始密码或随机密码，启动日志不显示密码。初始化账号文件和SQLite仅本机私有保管；学生密码使用随机salt的PBKDF2。旧教师JSON格式保留兼容，不将其误称为加密账号保险箱。

独立MCP通过进程环境MCP_AUTH_TOKEN启动，默认回环8090；不要复用应用签名密钥。模型Key只在网关请求认证头中使用。错误/日志不输出Key、认证令牌或完整异常堆栈。

## Compose

按deploy/README.md生成独立私有配置、项目名和secret文件，只有Nginx发布回环入口。不要挂载真实Windows业务目录进行测试，不使用删除数据卷命令，不清理其他项目。后端通过精确允许的http://mcp:8090访问工具；浏览器访问的是Nginx宿主机端口。

本轮Engine不可用，因此未进行构建/启动/卷持久化的实际验收。密钥加解密、备份恢复在临时数据下测试，不能等同Linux容器运行成功。

## 真实模型验证

本轮未读取真实.env或调用付费模型。若以后验证，应在独立测试进程安全注入CHAT_BASE_URL、CHAT_MODEL、CHAT_API_KEY，使用兼容tools/tool_calls及流式Chat Completions的模型，明确费用授权后仅做最小请求。分别记录基础API、真实MCP、模型自主选择及联合结果，禁止把正确数值答案单独当作工具调用证据。

## PDF/HTML导出

在虚拟环境按requirements-report.txt安装报告依赖，然后：

```powershell
python scripts/export_acceptance_report.py
```

输入STAGE_ACCEPTANCE_REPORT.md；输出同名HTML及output/pdf/STAGE_ACCEPTANCE_REPORT.pdf。HTML为本地样式，不依赖CDN；PDF生成后需确认中文、表格、代码换行和页码。项目所附PDF为已验证的公开报告，不包含临时日志或私有账号截图。
