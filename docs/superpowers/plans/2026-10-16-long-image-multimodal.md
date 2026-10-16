# Long-image multimodal parsing

Approved behavior: preserve the existing prompts and source document identity;
tile oversized images without downscaling, parse every tile, aggregate results
and actual token usage, and keep cancellation and archive reuse working.

1. Add renderer tests for long/wide images, full pixel coverage and original
   page/position locators. Bound tile dimensions and encoded PNG bytes.
2. Add parser tests for bounded request batches, mixed routing decisions,
   ordered merged Markdown, usage aggregation, cache reuse and cancellation.
3. Implement source-preserving tiles and bounded batches. Archive each batch
   separately and reference all parts from the parent Chunk. Never classify a
   whole Chunk as TEXT unless every batch was classified as TEXT.
4. Run the isolated renderer/parser suites. Verify prompt constants unchanged.
5. Push chunk-mm using the designated SSH key. Deploy only while no parsing
   tasks are active; retest the previously failing PDF and inspect its archives.
