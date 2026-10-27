## Why

第五、六课已有增量成果，但尚缺对应规约，并与2026-10-27公开教程的Swagger入口、检索过滤顺序和工具流式元数据存在差异。需要保留已有实现，补齐可验证差异，重新验收而非沿用历史通过数。

## What Changes

- 记录既有智能体、技能、会话与MCP安全边界，补全验收场景。
- 兼容/swagger及/docs；绑定材料内先取前4条，再按技能学科过滤。
- 首个meta保持即时返回；调用后追加累计tool_calls的meta，并保留tool_status兼容事件。
- 工具安全检查后截断过长数据；保证前端元数据更新不重复引用/状态。
- 重跑隔离自动化与浏览器；真实模型和Docker按实际环境记录，不虚报成功。

## Capabilities

### New Capabilities
- `lesson-five-assistant`: 将已有智能体、技能、私有会话及RAG/SSE行为纳入规约，修复入口和过滤顺序。
- `lesson-six-tool-orchestration`: 将已有MCP发现、候选集、模型循环、安全及审计纳入规约，补齐meta工具状态。

### Modified Capabilities

无。class-knowledge-base为第四课旧检索规约，本轮保持其无命中语义，不将第五课模型回退强加给旧接口。

## Impact

仅本项目backend、frontend、Nginx配置、隔离测试与文档；不改真实.env、现有数据库结构或其他项目。Docker不可用时保留阻塞，不提权或重置。
