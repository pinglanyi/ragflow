# Compile existing chunks, then build dataset structures

The approved entry point builds Graph, Mind map and Timeline from existing,
available source chunks. It does not parse files, run OCR, replace source chunks,
or change parser configuration. Existing template groups take precedence; missing
kinds use editable tenant-owned copies of the built-in templates.

One dataset operation serializes document preparation and shares each source
stream across requested templates. Model concurrency is bounded. Successful
document/template results are checkpointed against source content, configuration
and model identity; retries reuse unchanged results. Failed or cancelled work
does not receive a completion checkpoint or start dataset aggregation.

1. Add dependency-light orchestration regressions (failure, reuse, cancellation).
2. Implement source-only compilation using the existing compiler and merger.
3. Wire the isolated queue and expose a Python frontend action for all three.
4. Run focused Python/frontend checks; commit and push only this change.

Live acceptance after deployment must verify generated contents and source chunk
counts/IDs, including retries and edits. Local checks do not substitute for it.
