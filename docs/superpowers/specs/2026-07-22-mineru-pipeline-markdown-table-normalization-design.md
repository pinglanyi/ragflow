# MinerU Pipeline Markdown Table Normalization Design

## Goal

Add an opt-in table-normalization setting to the custom ingestion pipeline's PDF Parser configuration. When a pipeline uses MinerU and enables the setting, HTML tables returned by MinerU are converted into compact, standard Markdown tables before the Parser output reaches chunking and tokenization.

The change is intended for independent A/B testing. Built-in dataset parsing, existing pipelines, and custom pipelines that do not enable the setting must retain their current behavior.

## Problem

MinerU returns table blocks as HTML, including `<table>`, `<caption>`, `<tr>`, `<th>`, and `<td>`. RAGFlow renders that HTML correctly, but the same markup is passed to downstream language-model processing when a custom pipeline requests Markdown output. Large tables therefore contain substantial tag noise.

The existing `MinerUParser._sanitize_section_text()` is not suitable for this use case. It removes tags with regular expressions and can collapse adjacent cells; for example, `<td>Alpha</td><td>Beta</td>` becomes `AlphaBeta`. Once cell boundaries are removed, downstream code cannot recover the table structure.

## Scope

### Included

- An opt-in MinerU table-normalization field in the custom ingestion pipeline Parser's PDF setup.
- Backend configuration validation and propagation for that field.
- Conversion of MinerU HTML table blocks into Markdown in the custom pipeline Parser path.
- Preservation of surrounding text, captions, cell order, empty cells, and empty columns.
- Deterministic handling of merged cells, malformed HTML, and Markdown-special characters.
- Focused backend and frontend tests for the new behavior and its disabled state.
- User-facing field copy or documentation sufficient to identify the setting as pipeline-local and experimental.

### Excluded

- Changing the output of built-in dataset parsers.
- Changing `MinerUParser` globally.
- Converting tables produced by parsers other than MinerU.
- Adding a general-purpose Code or MarkdownNormalizer pipeline component.
- Reconstructing table structure from already flattened plain text.
- Removing genuinely empty columns detected by MinerU.

## Approaches Considered

### Parser-local opt-in setting — selected

The custom pipeline's Parser already owns parser selection and final output formatting. A MinerU-specific opt-in field keeps the behavior local to the selected pipeline DSL and performs normalization before Chunker and Tokenizer consume the result. It adds a small, explicit surface and supports direct A/B testing by toggling one setting or duplicating the pipeline.

### Dedicated MarkdownNormalizer component

A separate component would make the transformation visible on the canvas and reusable for other HTML sources. It would also require a new backend component, schemas, registration, frontend node, form, DSL support, and connection rules. That scope is not justified for a MinerU-only experiment.

### Global MinerU parser change

Changing `MinerUParser` would be the smallest code diff, but it would affect built-in parsing and every MinerU consumer. This conflicts with the isolation requirement.

## Configuration

The PDF Parser setup gains a boolean MinerU-specific field named `normalize_mineru_tables_to_markdown`. The same identifier is used consistently in the backend, frontend form state, and serialized pipeline DSL.

The field:

- defaults to `false` so existing DSL documents retain current behavior;
- is meaningful only when `parse_method` resolves to MinerU;
- is exposed in the custom ingestion pipeline Parser form near the MinerU settings;
- does not alter non-MinerU parsers even if present in imported DSL;
- is applied only when the Parser emits Markdown.

The UI label should state that the operation converts MinerU HTML tables to Markdown for downstream model processing. It should be presented as experimental during the initial A/B testing period.

## Architecture and Data Flow

```text
File
  -> custom pipeline Parser
       -> MinerU remote API
       -> MinerU sections represented as shared bbox records
       -> optional MinerU HTML-table normalization
       -> Markdown Parser output
  -> Chunker
  -> Tokenizer
  -> later model/indexing stages
```

The conversion belongs in `rag/flow/parser`, not `deepdoc/parser/mineru_parser.py`. The flow Parser knows both the selected parser and the requested final output format, so it can apply the opt-in behavior without changing the shared MinerU adapter.

A focused helper will accept a text block and return normalized Markdown. It will parse HTML structurally with the repository's existing BeautifulSoup dependency. Regular expressions may be used only for lightweight detection or final whitespace cleanup, not for reconstructing table structure.

For MinerU Markdown output with the option enabled, each bbox text value is passed through the helper before the document-level Markdown string is assembled. Non-table fragments pass through unchanged.

## Conversion Rules

### Table detection and surrounding content

- Convert complete `<table>...</table>` elements, including entity-escaped table markup after safe HTML entity decoding.
- Preserve text before, between, and after tables in source order.
- Do not reinterpret literal comparison text such as `a < b` as a table.
- Multiple tables in one block are converted independently.

### Captions

- Emit each `<caption>` as a plain Markdown paragraph immediately before its table.
- Preserve the caption text and inline content while removing HTML-only presentation markup.
- Separate the caption and table with one blank line.

### Rows and cells

- Preserve source row order.
- Treat both `<th>` and `<td>` as cells.
- Preserve empty cells and columns, including the narrow empty column shown in the supplied CAN expansion-module example.
- Normalize insignificant leading/trailing whitespace while preserving meaningful inline text.
- Convert `<br>` inside a cell to `<br>` so the content remains within one Markdown table row.
- Escape literal `|` characters as `\|` and normalize embedded newlines so they cannot break the pipe-table structure.

### Header selection

- If the source has a header row containing `<th>`, use that row as the Markdown header.
- If no row contains `<th>`, emit a synthetic empty header with the calculated column count, followed by the separator row, then emit every source row as data. This keeps signature and metadata tables from incorrectly promoting their first row to field names.
- Pad short rows with empty cells to the table's calculated width.

### Merged cells

Markdown pipe tables do not support `rowspan` or `colspan`. Normalize merged HTML cells into a rectangular grid:

- place the original cell value in the first occupied coordinate;
- fill additional coordinates covered by the span with empty cells;
- account for active row spans when positioning cells in later rows;
- reject non-positive or invalid span values as `1`.

This preserves table shape without inventing duplicate semantic values.

### Malformed input

- Use tolerant HTML parsing so recoverable MinerU fragments still convert.
- If a detected table cannot yield any rows or cells, fall back to readable text extracted from that element.
- If conversion of an individual block raises unexpectedly, log a warning with block context and retain the original block rather than failing the whole document.
- Do not log full document contents.

## Example

Input:

```html
<table>
<tr><td>拟制：</td><td>蓝林虹</td><td>日期：</td><td>2024.03.19</td></tr>
<tr><td>审核：</td><td>张海东</td><td>日期：</td><td>2024.03.19</td></tr>
</table>
```

Output:

```markdown
|  |  |  |  |
| --- | --- | --- | --- |
| 拟制： | 蓝林虹 | 日期： | 2024.03.19 |
| 审核： | 张海东 | 日期： | 2024.03.19 |
```

For the larger CAN resource table, the caption becomes a paragraph, its `<th>` row becomes the Markdown header, and every empty cell remains represented by adjacent pipe delimiters.

## Compatibility

- The new setting defaults to disabled.
- Existing pipeline DSL without the field produces byte-for-byte equivalent Parser content for this behavior.
- Built-in dataset parsing remains on its current path.
- MinerU JSON output remains unchanged.
- MinerU Markdown output changes only for a custom pipeline whose Parser explicitly enables the setting.
- Other parser implementations remain unchanged.

## Testing

### Unit tests for the converter

- Converts the supplied signature table into Markdown with a synthetic empty header.
- Converts the supplied CAN table with caption, header cells, Unicode circled digits, dash characters, empty cells, and the genuine empty column.
- Decodes entity-escaped table markup.
- Preserves multiple tables and surrounding text in order.
- Escapes pipe characters and keeps `<br>` content inside a cell.
- Produces a rectangular grid for `rowspan` and `colspan`.
- Tolerates malformed table fragments and empty tables.
- Leaves non-table text unchanged.

### Parser integration tests

- MinerU + Markdown + option enabled emits Markdown tables and no `<tr>`, `<td>`, or `<th>` tags.
- MinerU + Markdown + option disabled retains current output.
- MinerU + JSON ignores the option.
- Non-MinerU + Markdown ignores the option.
- A conversion failure preserves original content and records a warning.

### Frontend tests

- The pipeline Parser form serializes and restores the boolean field.
- The setting is shown only in the relevant MinerU PDF configuration context.
- Existing pipeline configuration without the field initializes it to `false`.

## Success Criteria

- The supplied CAN document is emitted by the opted-in custom pipeline as compact Markdown tables without table-tag noise.
- Empty cells and columns visible in the source table remain represented.
- Downstream Chunker and Tokenizer receive the Markdown form.
- Toggling the option off restores current behavior for A/B comparison.
- Existing built-in and custom pipeline behavior is unchanged by default.
- Focused backend and frontend tests pass.
