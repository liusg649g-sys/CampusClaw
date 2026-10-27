## Purpose

规范CampusClaw已有独立MCP服务和主后端工具编排，确保模型决策与宿主授权分离，教师配置、工具发现、逐次执行、工具消息、调用上限、审计和流式状态能按第五六课边界核验，而不混淆Mock与真实模型证据。

## ADDED Requirements

### Requirement: Discovered tools and live authorization
The system SHALL authenticate MCP JSON-RPC initialization, discovery and calls, expose at least two deterministic tools, and permit only teacher class-scoped management. Skills SHALL reference only currently discovered tools on connected servers in their class. Tokens MUST NOT be returned to frontend or logs.

#### Scenario: Disconnect invalidates tools
- **WHEN** the server is disconnected, changed or deleted
- **THEN** cached tools cease authorization immediately and attempts are denied rather than reported successful

### Requirement: Model decisions and bounded execution
The system SHALL send only selected-skill candidates to the model, validate each proposed call and its schema again, and send checked results as untrusted tool messages. Round/count/time/parameter/result limits SHALL apply. Safe long results SHALL be truncated only after injection and credential checks.

#### Scenario: Long malicious tail
- **WHEN** an overlong result contains an injected instruction or credential after the truncation boundary
- **THEN** the whole result is rejected rather than truncating away evidence before validation

#### Scenario: Multiple calls and limits
- **WHEN** the model requests multiple rounds or exceeds quotas
- **THEN** only authorized in-quota executions run and the model can complete using existing data

### Requirement: Observable safe tool metadata
The system SHALL emit cumulative meta.tool_calls after actual call outcomes and before text deltas, omit tool_calls when none occurred, and retain compatible tool_status events. The frontend SHALL render repeated metadata idempotently. Audit outcomes SHALL identify class/user/conversation/server/tool/round/time/status and safe summary without raw credentials.

#### Scenario: Tool outcome precedes answer
- **WHEN** a real local MCP call completes during a Mock model test
- **THEN** a meta event contains its reference/status before the first delta, tool_status stays compatible, and history agrees with audit

### Requirement: Honest isolated acceptance
The system SHALL keep tests isolated from real user data and other projects, preserve existing data, and distinguish mock models, real local MCP, real models and container execution.

#### Scenario: Environment blocked
- **WHEN** Engine or paid model configuration is unavailable
- **THEN** the report records the exact blocker and continues independent tests without claiming the blocked acceptance passed
