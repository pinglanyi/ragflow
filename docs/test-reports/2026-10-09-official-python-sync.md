# Official Python sync — 2026-10-09

- Custom base: `ca045b55e` on `chunk-mm`.
- Official integration target: `322aba7d4` (2026-09-28), before Python removal began at `562e02184`.
- Latest official main `3cdb3cac6` removes the Python backend; user selected the last complete Python main instead of Go migration.
- Preserve stateless/SSE Agentic Search, seven native tools, authorized dataset routing, source-order iteration, bounded unseen retrieval, multimodal parsing/archiving, rewind fixes, and navigation/skill fallback behavior.
- Keep Python deployment mode, custom Redis port, and LibreOffice image rendering dependencies.
- Integrate official compilation template/prompt management and updated frontend alongside the base extensions.
- Remove the replaced internal agent/registry/pipeline architecture; keep the custom source inspection API on the new runtime.

## Verification status

Python syntax scan completed without errors. Focused undefined-name/redefinition checks completed during integration. Full regression runs and frontend build are not completed. Dependency setup encountered mirror/network delays. The user explicitly requested pushing first and testing after remote startup; this commit is not a claim of successful runtime verification.

## Remote follow-up

Rebuild the application from this source and install updated locked dependencies. Start in Python mode (`API_PROXY_SCHEME=python`). Verify authentication, model connection, ordinary uploads, multimodal document parsing and archives, all seven Agentic Search tools, stateless/SSE search, existing KB navigation/skill pages, no-pipeline Wiki generation, and compilation-template prompt editing/persistence. No production databases or documents were modified during this merge.

## Remote regression follow-up (15:51–15:56 CST)

- Frontend login, home, model settings, dataset settings, and the reported compilation route load after dependency installation/restart. Full frontend build remains unverified.
- API ping and dependency health checks pass. Both custom navigation and official nav routes register after resolving duplicate endpoint names (`3f10ed7a4`).
- Five Agentic Search read tools (search/open/read/grep/navigate) succeed against the existing product KB; excluding previously returned IDs yields different chunks. Invalid inputs and unauthorized dataset IDs are rejected. Ingest/delete are disabled by deployment configuration; write functionality has not passed end-to-end verification.
- Stateless and SSE search first failed because the synthetic dialog lacked `rerank_candidates_count`; fixed in `c9f607145`, with 78 focused API/service tests passing. Remote restart confirms the missing-field error is gone.
- Answer generation then failed with LiteLLM provider inference for `qwen3.6-35b-a3b`. DashScope compatible endpoints now use explicit `openai/` routing while native endpoints retain `dashscope/`. Six focused routing tests reproduce the old failure and pass after the fix. Remote answer generation needs another deployment/retest.
- Latest local run: 97 passed, one runtime smoke test blocked by the local test interpreter lacking Torch. Six routing and 78 Agentic API/service tests are included in the passing count. Broader earlier multimodal/retrieval suite had fixture/dependency failures and is not claimed passing.
- Vision model connectivity succeeds. Synthetic PNG uploads in full/smart mode return 202 and task status endpoints work, but both tasks remain queued with zero chunks. The ordinary TXT upload is queued too. No completed parsing/archive/retrieval round-trip has been verified.
- Server evidence confirms CUDA is visible and the ORT CUDA library loads. All three local worker processes exit during import with `ModuleNotFoundError: rapidfuzz`; the dependency is already declared as `rapidfuzz==3.14.5`. Redis reports an active external executor. Its runtime/device is not verified. Repair the worker environment and inspect the external deployment before changing queue ownership.
- Test mutations: created isolated KB `Codex回归测试_20261009` (`a81bb3ccc3b411f1b10aef18bd592ce8`) with one synthetic TXT and two synthetic PNGs. Also started the previously empty product KB Wiki generation task while exercising its Generate button; completion is unverified. No existing source documents were deleted.

Overall status: NOT a complete acceptance pass. Worker recovery, successful full/smart parsing and archives, generated ordinary/SSE answers, and prompt edit persistence remain outstanding.
