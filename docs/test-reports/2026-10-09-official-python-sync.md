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

## Follow-up after worker recovery (16:00 CST onward)

- Deployed version verified as `03e661531`. Worker logs report ingestion ready and one GPU. LiteLLM's remote price-map timeout falls back to local data and does not stop startup.
- Ordinary TXT document completes parsing/embedding/indexing with one chunk. Full multimodal PNG completes with one chunk, 767 recorded tokens, and a successful job status. Smart PNG fails after router TEXT chooses a picture whose base OCR was intentionally skipped; no base text exists. Fix: only retain TEXT routes when nonempty base text exists; otherwise generate archived multimodal Markdown.
- Nonstream Agentic Search now generates an answer without provider errors. The tested product question lacks sufficient retrieved wiring evidence, so no supported wiring instructions or citations are claimed. SSE emits answer deltas but fails at termination because the new generator's final packet deliberately has an empty answer. Fix: assemble visible deltas (excluding progress/thinking) for the final response and conversation persistence, applying the same citation normalization as the generator.
- Isolated Wiki template `1024e004c3b711f1b0978b23be6ef9f1` was created and edited through the browser. Reopening confirms the edited global-rules marker. Screenshot saved in local task artifacts.
- Python built-in dataset settings omitted the template selector and schema field. Added template multiselection, create/edit links, and preservation of scalar/list IDs when saving. Tree provides summarization/claim prompts; Wiki provides entity/concept specifications and blueprint/instruction fields. Existing documents without per-document template overrides inherit dataset settings for Wiki generation. Structural compilation still requires document parsing to produce its compiled source rows.
- User's Skill log reports an old `model___provider@default@provider` embedding reference. Add recovery only for the same named model under the owned provider, with a unique instance match and normal model-ID authorization/status validation. Existing original model records, including disabled/unsupported records, cannot be rebound by this compatibility path. Do not choose a different default embedding model.
- Local focused verification: 121 tests passed, including routing, Agentic APIs/tools, multimodal archive/orchestration, legacy model resolution, and Wiki dataset template inheritance. Four changed frontend files transpile; actual Zod schema reproduces lost scalar/list template IDs before the fix and retains both after it. Full frontend dependency installation/build and deployed new UI behavior remain unverified.

Pending: deploy the new fixes, verify smart parsing and SSE final event, test template selection/save in the deployed dataset UI and repeat Skill generation with its original embedding model. Overall acceptance remains incomplete.

## Deployed acceptance checks (16:25-16:39 CST)

- API reports deployed `c1ec3897e`. Nonstream Agentic Search returns an answer; SSE terminates with a nonempty final event rather than an error.
- Smart PNG retry `badce883a1664cc7ba862a1abb103d93` completes with one chunk (archive reused). Both full/smart chunk APIs return the expected 128 Hz and 24 V. Agentic Search answers those parameters correctly and cites both image documents.
- Browser verifies dataset template binding survives Save and reload, and its Edit button opens the selected template. Wiki global rules, a new entity specification, concept definition, and blueprint instruction were modified, saved and reopened with the expected values.
- Created isolated Tree group `643866b2c3bb11f1a4265d989bff8df3`; edited Global rules, Summarization prompt and Claim extraction prompt, saved and reopened successfully. Bound Wiki and Tree together; both selections persist after reload. Template proof screenshots are saved in the local task artifacts.
- Isolated Wiki task `7b2701b2c3bb11f1a4265d989bff8df3` finishes in 22.5 seconds with eight pages. Isolated Skill task `cc77b39ec3bc11f1a4265d989bff8df3` finishes in 21.6 seconds with three top-level skills from three synthetic documents.
- User screenshot reports another Wiki task at 16:28:56 failing on an existing legacy suffixed model. The queried product KB still points to an older 15:38 task, so these task identities are not yet matched. Requested the failing page URL and worker traceback/executor status. Do not claim that screenshot's failure is resolved remotely.
- Added a regression for an active original suffixed model under a renamed instance: resolve its unique original ID and validate normal model status/type instead of rejecting existence. Disabled, wrong-type or ambiguous originals still fail without switching to a bare model. Local focused suite: 124 passed. This follow-up compatibility change requires deployment before remote verification.

Acceptance scope: template frontend editing/persistence, isolated Wiki/Skill generation, ordinary/full/smart parsing, and Agentic Search answer flow pass the checks above. The user's separate failing Wiki task, broad document-format coverage and disabled write tools remain unverified.

## Failing task identified and template execution follow-up

- User supplied actual failing KB `a69cec7697ba11f1aee541181c4bf5ba`, owned by tenant `43fce43a649e11f187291de151a38e91`. The provided test account receives `no authorization`; no access checks were bypassed.
- User worker log identifies task `a9fbe52ac3bb11f1a4265d989bff8df3` on local `common_5` PID 3052620, with legacy embedding name and empty `tenant_embd_id`. Its rejection occurs in the original-existence guard; `bb3665448` replaces that guard with validated resolution of the unique original model. Remote confirmation is pending deployment and access.
- Active foreign executor is container `docker-ragflow-gpu-1` (`f4003e4d3cfa`) using RAGFlow v0.25.4. It shares Redis queues, but did not execute the logged failing task. Its actual GPU configuration has not been verified. Changed executor warning to stop asserting CPU use from the executor name alone.
- Runtime Wiki prompt logs revealed a second caller issue: task `parser_config` is the sample document's configuration, while the dataset template selection lives in `kb_parser_config`. Corrected the Wiki caller to pass the dataset configuration and corrected document structure compilation to inherit dataset templates, preserving explicit document overrides. Wiki mode resolution uses the same merged configuration.
- Added failing-then-passing caller regressions for Wiki selection and Tree document compilation. The earlier successful eight-page Wiki generation proves the generation engine works, but used built-in prompts; custom prompt execution must be retested after this follow-up deployment. Frontend edit/save persistence remains verified independently.
