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
