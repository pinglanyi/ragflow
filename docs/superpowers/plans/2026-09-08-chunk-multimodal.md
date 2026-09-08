# Chunk multimodal parser implementation

Goal: transform existing RAGFlow chunk screenshots into searchable Markdown before embedding, with portable durable archives.

Approved scope: current Python ingestion path; optional dataset/document configuration; OpenAI-compatible local vLLM or commercial vision endpoint from tenant model settings. Text is transcribed faithfully, figures described, tables flattened with inherited merged values. No automatic paid fallback.

1. Implement an isolated parser and filesystem archive under `rag/svr/chunk_multimodal.py`. Persist PNG, request metadata (no credentials), every raw response, validated Markdown, and per-run source mappings. Content/config SHA256 identifies cache entries; chunk indices and counts never identify entries. Writes are atomic; invalid results are archived but never cached as success.
2. Invoke it in `build_chunks` before upload, keywords, and embedding. Regenerate token fields, retain screenshots and positions, reject chunks missing screenshots instead of silently calling text a visual parse. Configuration uses `parser_config.multimodal` and document values override KB values.
3. Add shared frontend options with schema/type support in dataset and document settings. Use tenant vision model selector, editable prompt, output limit, model revision and cache reuse toggle. Existing chunk Markdown renderer remains the display path.
4. Test content identity across changed chunk ordering/count, configuration invalidation, failed/truncated/HTML/ragged output archival, successful reuse and atomic publication. Document archive sync and server acceptance steps.

Archive location: `RAGFLOW_MULTIMODAL_ARCHIVE_DIR`, default `data/multimodal_archive` relative to worker directory. All workers must share a persistent directory. Sync only trusted administrator-managed archives; never include API keys. Reuse requires exact PNG/config identity, not guessed overlap between changed crops. Embeddings are regenerated from cached Markdown.

## Implementation verification

- Implemented on `feat/chunk-multimodal-archive` in the requested checkout.
- Both the default refactored Python executor (`TE_RUN_MODE=0`) and the alternative executor call the shared module. Original figure enhancement is bypassed for opted-in PDF parsing.
- 16 focused tests pass, including default executor orchestration, configuration inheritance, image request serialization, screenshot deduplication, archive export/import, failed refresh preservation and invalid/truncated response retention.
- Twelve touched TypeScript files passed compiler syntax diagnostics. Python syntax and diff whitespace checks passed.
- Full frontend type-check/build and live Ubuntu API/worker/model acceptance remain environment checks: this checkout has no frontend node_modules and no live model endpoint was exercised. No deployed service was restarted.
- Operator instructions: `docs/chunk-multimodal-parser.md`.
