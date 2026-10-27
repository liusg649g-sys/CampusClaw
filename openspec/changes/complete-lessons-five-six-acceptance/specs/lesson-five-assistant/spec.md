## Purpose

规范CampusClaw现有第五课的教师智能体、独立技能和学生私有流式会话，使配置、检索范围、引用和文档入口具备可重复验收的行为边界，并保持第四课旧接口及真实用户数据兼容。

## ADDED Requirements

### Requirement: Teacher configuration and private conversations
The system SHALL enforce teacher-only writes, class-scoped unique agent/skill names, skill file validation, live bindings and private student conversations. Agent names MUST be at most 64 characters, roles 2000; skill source/name/triggers/body/subject MUST be at most 8000/32/120/2000/32 characters. Empty agent roles SHALL use defaults.

#### Scenario: Unauthorized and foreign resources
- **WHEN** a student writes teacher configuration or accesses foreign conversations
- **THEN** writes return 403 and foreign/nonexistent resources return identical 404 responses

#### Scenario: Live lexical route
- **WHEN** a question is submitted after a skill is disabled or unbound
- **THEN** only currently bound enabled skills participate, at most one wins, ties use lowest ID and zero scores select none

### Requirement: Bound retrieval and model context
The system SHALL authorize current class and live material bindings before ranking, take at most four relevant chunks, then filter by the selected skill's subject using material titles. Remaining citations MUST be numbered continuously. The system SHALL include six recent messages with 500-character limits, place roles and skills in system context and retrieval data in user context.

#### Scenario: Subject filter does not backfill
- **WHEN** the four highest authorized chunks are for another subject but a lower-ranked fifth chunk matches
- **THEN** citations are empty and no lower-ranked chunk is backfilled

#### Scenario: No retrieval hit
- **WHEN** no authorized chunk survives
- **THEN** the new agent flow still calls the model without fabricated references, while legacy knowledge-answer behavior remains unchanged

### Requirement: Incremental and documented responses
The system SHALL emit meta before incremental delta, persist before done and emit error on model failure. Agent questions MUST contain 2 to 500 characters; legacy promptId limits SHALL remain compatible. Stops SHALL preserve interrupted history. Both /swagger and /docs SHALL serve the same usable Swagger page.

#### Scenario: Agent metadata and interruption
- **WHEN** a new agent answer starts or is interrupted
- **THEN** meta identifies the agent, selected skill and citations, and an interrupted answer is not reported as complete

#### Scenario: Compatible Swagger routes
- **WHEN** a user opens /swagger, /swagger/ or /docs
- **THEN** the same OpenAPI-backed interface is returned
