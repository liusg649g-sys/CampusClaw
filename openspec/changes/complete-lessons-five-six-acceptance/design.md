## Context

See proposal.md. Existing standard-library backend, SQLite and JSON stores remain. Only class-knowledge-base has a main spec; new deltas describe existing lesson-five/six contracts and measured corrections. Current Docker named pipe is absent; default sandbox blocks localhost sockets, ordinary-user isolated tests require normal process access, not administrator rights.

## Goals / Non-Goals

Goals: smallest fixes to verified tutorial gaps; repeatable evidence; preserve promptId behavior and historical data. Non-goals: other projects, class-seven work, database replacement, destructive deployment, secret changes.

## Decisions

- Add /swagger aliases in existing handler and both proxy configurations rather than redirecting to an unrelated app.
- Authorize bindings before search, request four chunks, then filter titles and reindex references. Do not change fourth-lesson knowledge-answer semantics.
- Preserve immediate initial meta and existing tool_status; add cumulative meta after each outcome so tools appear before正文 without delaying first-byte metadata. UI replaces source/status containers keyed by audit ID to avoid duplicate sources.
- Check entire bounded MCP output for instructions and credentials before truncating safe text to a valid UTF-8 boundary. Existing response-size caps remain.
- No schema migration. Completed audit finalization remains host-internal and is allowed exactly once; no client update/delete interface. Success summaries contain safe result size only. Record the difference from latest course append-only wording explicitly rather than pretending existing reservation/finalization is literal append-only.
- Browser fixtures get configurable independent report directories; never overwrite stage reports. Mock and real local MCP remain labeled.

## Risks / Trade-offs

- Additional meta may surprise clients assuming only one → preserve all prior fields and add a client idempotency test.
- Post-ranking subject filtering can produce fewer references → this is intended by tutorial; no backfill.
- Docker or paid API unavailable → leave explicit acceptance tasks incomplete, keep local isolated evidence.

## Migration Plan

Back up using existing read-only backup utility; change source only. No real service restart in this task without verified safe need. Validate on temporary services and databases. Rollback concerns only changed source; do not reset Git or restore a real DB to undo source fixes.
