# Python functional parity design

The user authorizes implementing the remaining inventory gaps while preserving existing custom features. Work proceeds by independently testable subsystems, against upstream `f2e618aed`, without importing the Go runtime or changing production accounts.

## Compatibility contract

Keep Agentic Search levels 1–4, ordinary/streamed answers, Tree/Wiki/Graph tools, full/smart parsing, template editing, GPU OCR, workers 6–8 and namespaced Redis queues. Do not commit the concurrent navigation-tree edits. New model fallback is opt-in; absent configuration must retain the original model path. No live schema migration or new infrastructure.

## Subprojects

1. Parser/storage parity: Docling options flow from saved parser configuration or environment to every remote request; explicit false takes precedence and unset values preserve server defaults. Normalize leading Unicode BOMs without removing internal text. Confirm SDK-based S3/OSS copy escaping before changing it. Compare MinerU, DOCX and media-context paths with upstream fixtures.
2. Network-tool parity: audit MCP token exposure, execution-time targets and redirects. Preserve supported user credentials and private-host opt-in while preventing managed tokens from being returned to clients.
3. Conversation/workflow parity: implement explicitly configured tenant-scoped fallback models, preserving tool binding, usage accounting and stream semantics. Never replay a partially emitted response. Compare parser selection, workflow references, validation and recovery before changing behavior.
4. Task/Wiki/index parity: reproduce cancellation/retry, naming/link/storage, permissions and index differences with focused tests. Changes are local to the owning implementation; existing paths are not replaced merely to match Go structure.

## Acceptance

Every code change has a reproduced failing case followed by focused passing tests. Run original custom-feature regressions before delivery. Record implemented, already equivalent, unverified and blocked cases separately in the dated comparison report. Mocked provider tests do not constitute live acceptance. Optional database engines require their own service integration evidence.
