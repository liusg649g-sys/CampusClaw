# 第五、六课功能与验收边界

## 第五课

教师可在本班管理多个独立智能体、角色提示词、独立技能及材料绑定；技能支持粘贴和UTF-8文件上传。源文保留在source_text，解析列保存在skills，未将原prompts重命名。学生创建绑定agentId的私有会话；旧promptId会话仍兼容。

每轮只在绑定且启用技能内做关键词子串计分，零分不选、同分低编号，只选一个。完整技能正文与名称进入system；资料范围用于检索过滤，工具字段用于可选工具授权。技能不是可执行脚本。

新智能体每轮先检索本班当前有效绑定材料，取前4片后按技能学科标题过滤，不补回第5片；资料作为不可信数据放user，每片最多800字。最多6条近期消息窗口（含本轮用户消息），历史每条500字。零命中仍调用模型、不造引用。旧knowledge/answer和promptId零命中维持不调用模型的旧行为。

SSE为meta、delta、done、error，支持中断、历史和来源查看。Swagger同时支持/swagger与/docs。所有权限由服务端实施，跨班资源与不存在按一致规则处理。

## 第六课

独立mcp-server提供Bearer鉴权的JSON-RPC initialize、通知、tools/list、tools/call和最小健康接口。真实工具包括formula_hint、安全calculator和unit_convert，不执行任意代码或Shell。

教师登记稳定服务器标识、连接和发现；缓存整体替换，断开即失效，重启不会信任历史连接状态。技能可声明knowledge_search与tool@server-key，保存和逐次执行均校验所属班级、连接、发现清单及参数Schema。

模型只提出tool_calls，后端授权后带私有认证调用MCP。结果检查后以role:tool回传；默认最多4轮/8次执行。最终回答另走stream请求。工具状态以累计meta.tool_calls和兼容tool_status在正文前返回，审计按班级隔离。

knowledge_search为内置标记；新智能体前置RAG不依赖模型是否选它，也不发往独立MCP。仅三种安全工具允许执行，不宣称支持任意外发或写入工具。

## 证据

`submission/evidence/` 为本轮合成素材下实际构造的LLM JSON body、Mock响应和真实本地MCP交换。不会上传私有材料或完整运行日志。主报告解释五个阶段验收问题及当前测试统计。

真实模型API、Docker容器运行及真人同伴复核尚未验证；Mock决策不代表真实模型自主选工具已通过。学期项目中的公网部署和后续作业批改/错题流程不是本轮已完成声明。
