# CampusClaw 独立 MCP 工具服务器

仅使用 Python 3.10+ 标准库。不会导入主后端，不读取业务 SQLite、材料或真实 `.env`，不由现有一键启动器管理。只监听 `127.0.0.1`，默认8090，不提供 Nginx 入口。

在项目根目录 PowerShell 启动（已有 Python 路径不同则替换可执行文件路径）：

```powershell
$secret = Read-Host '输入独立 MCP 专用令牌（16至256位，无空格ASCII字符）' -AsSecureString
$env:MCP_AUTH_TOKEN = [System.Net.NetworkCredential]::new('', $secret).Password
try {
    python .\mcp-server\server.py --port 8090
} finally {
    Remove-Item Env:MCP_AUTH_TOKEN -ErrorAction SilentlyContinue
    $secret = $null
}
```

前台进程用 Ctrl+C 停止。缺少或无效令牌时启动退出码1，不占监听端口。不要复用主系统 Token Secret。示例只设置当前 PowerShell 进程环境，不修改系统环境，不将令牌放到命令参数或脚本中。

接口：`GET /health` 返回 `{"status":"ok"}`。`POST /mcp` 需要 `Authorization: Bearer <专用令牌>`、`Content-Type: application/json`；客户端按规范发送 `Accept: application/json, text/event-stream`。不带 Origin 的服务器端客户端允许访问；带 Origin 时只允许当前端口的 localhost/127.0.0.1 同源地址。Host 同样仅允许这两个地址和实际端口，不开放 CORS。

协议版本 `2025-03-26`。采用无状态 Streamable HTTP JSON 响应分支，无 MCP 会话 ID，不保存握手状态；initialize 协商版本，未知版本返回本服务支持版本，由客户端决定是否继续。兼容老师“initialize 后直接 tools/list”的调用方式，不强制通知才能发现。通知返回202空正文；GET /mcp 在认证后返回405（不提供服务器推送 SSE）。支持最多20项批量请求，初始化不得出现在批量中。没有 resources/prompts、订阅、取消、远端通知或客户端回调能力。

握手示例：

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"campusclaw","version":"1"}}}
```

后续通知 `{"jsonrpc":"2.0","method":"notifications/initialized"}`，再发送 `{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}`。

工具结果均为 MCP `content:[{type:"text",text:...}], isError:false`，text 中是可解析 JSON。示例：

```json
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"calculator","arguments":{"expression":"2*(3+4)"}}}
```

对应成功响应：

```json
{"jsonrpc":"2.0","id":3,"result":{"content":[{"type":"text","text":"{\"value\": 14.0}"}],"isError":false}}
```

| 工具 | 参数 | 结果 text 中 JSON |
|---|---|---|
| formula_hint | query：1~500字非空问题 | hint：按关键词返回公式/步骤，不计算最终题目答案 |
| calculator | expression：1~200字符，十进制数字、空格、+ - * /、括号 | value：确定性数值；无变量、函数、幂、取模或代码执行 |
| unit_convert | value：有限数字，绝对值≤1e12；from_unit、to_unit | value、unit、factor；类型不兼容或结果越界报工具错误 |

支持 mm/cm/m/km；mg/g/kg；ms/s/min/h。不支持温度，因此不存在温标偏移处理声明。calculator AST最多64节点、递归及括号最多16层，每个数值/中间结果绝对值≤1e12；Decimal以32位精度计算，JSON数值为浮点输出，不能作为无限精度计算器。

解析错误 -32700，无效请求 -32600，未知方法 -32601，非法参数/未知工具 -32602，内部错误 -32603。除零、不兼容单位、计算越界等实际工具失败使用 result.isError=true。认证失败是HTTP401，拒绝来源403，超长正文413，错误Content-Type为415。协议请求错误通常HTTP200带JSON-RPC error；JSON解析失败HTTP400。每个请求正文最多16KiB，读取超时5秒。

测试：`python mcp-server/run_tests.py`。随机回环端口，临时生成令牌，测试真正运行工具与 HTTP，不使用模型或 Mock 工具执行。独立报告在 `apitest/reports/lesson6-stage1/`，不覆盖第5课报告。测试结束关闭自建服务器。

后续集成可复用 `tools.DEFINITIONS`、`tools.invoke()`、`tools.call_result()`、`server.dispatch()`；跨进程主后端应通过 HTTP 握手/发现/调用，不直接引入本工具模块替代 MCP 调用。主后端现已实现服务器登记、连接缓存、tool@server技能绑定、受限模型调用循环和审计；其验收边界见根目录阶段报告。独立工具测试不等同真实模型联合验收或Docker运行成功。
