# MinerU Pipeline Markdown Table Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in custom-pipeline Parser setting that converts MinerU HTML tables into compact Markdown before chunking and tokenization.

**Architecture:** Put the structural HTML-to-Markdown converter in a focused `rag.flow.parser` module that depends only on BeautifulSoup. Gate it from the custom pipeline PDF Parser using `parse_method`, `output_format`, and `normalize_mineru_tables_to_markdown`; expose the same boolean in the pipeline Parser form and serialized DSL. The shared `deepdoc` MinerU adapter and built-in dataset parsers remain unchanged.

**Tech Stack:** Python 3.13, BeautifulSoup 4, pytest, React 18, TypeScript, React Hook Form, Zod, Jest.

## Global Constraints

- The serialized field name is exactly `normalize_mineru_tables_to_markdown` in Python, TypeScript, form state, and pipeline DSL.
- The field defaults to `false`; missing fields preserve existing behavior.
- Conversion runs only for MinerU PDF parsing whose Parser `output_format` is `markdown` and whose opt-in field is true.
- Built-in dataset parsing, non-MinerU parsers, JSON output, and existing pipelines remain unchanged.
- Empty cells and genuine empty columns are preserved.
- `rowspan` and `colspan` expand to a rectangular grid with the source value only in the first occupied coordinate and empty cells elsewhere.
- Converter failures log a warning without full document content and preserve the original block.
- Do not modify `deepdoc/parser/mineru_parser.py` for this feature.

---

## File Structure

- Create `rag/flow/parser/mineru_table_markdown.py`: isolated HTML-table detection, grid expansion, Markdown rendering, and opt-in predicate.
- Create `test/unit_test/rag/flow/parser/test_mineru_table_markdown.py`: converter and gating regression tests using the supplied CAN-table shape.
- Modify `rag/flow/parser/parser.py`: invoke the converter only at the custom pipeline Markdown-output boundary.
- Modify `web/src/pages/agent/form/parser-form/pdf-form-fields.tsx`: render the MinerU-only experimental switch.
- Modify `web/src/pages/agent/form/parser-form/index.tsx`: validate and initialize the boolean form field.
- Modify `web/src/pages/agent/constant/pipeline.tsx`: default new pipeline PDF Parser setup to `false`.
- Create `web/src/pages/agent/form/parser-form/pdf-form-fields.test.tsx`: test MinerU method recognition used to control switch visibility.
- Modify `web/src/locales/en.ts` and `web/src/locales/zh.ts`: add label and tooltip copy.
- Modify `docs/guides/agent/agent_component_reference/parser.md`: document the custom-pipeline-only option and its A/B testing purpose.

---

### Task 1: Structural MinerU HTML Table Converter

**Files:**
- Create: `rag/flow/parser/mineru_table_markdown.py`
- Create: `test/unit_test/rag/flow/parser/test_mineru_table_markdown.py`

**Interfaces:**
- Consumes: `text: str` containing ordinary text, entity-escaped HTML, or one or more HTML tables.
- Produces: `normalize_mineru_html_tables(text: str) -> str`, which preserves surrounding text and replaces each table with Markdown.
- Produces: `should_normalize_mineru_tables(parse_method: str, output_format: str, enabled: bool) -> bool`, used by Task 2.

- [ ] **Step 1: Write failing tests for signature tables, captions, empty columns, and gating**

```python
from rag.flow.parser.mineru_table_markdown import (
    normalize_mineru_html_tables,
    should_normalize_mineru_tables,
)


def test_signature_table_uses_synthetic_empty_header():
    source = """<table>
    <tr><td>拟制：</td><td>蓝林虹</td><td>日期：</td><td>2024.03.19</td></tr>
    <tr><td>审核：</td><td>张海东</td><td>日期：</td><td>2024.03.19</td></tr>
    </table>"""

    assert normalize_mineru_html_tables(source) == """|  |  |  |  |
| --- | --- | --- | --- |
| 拟制： | 蓝林虹 | 日期： | 2024.03.19 |
| 审核： | 张海东 | 日期： | 2024.03.19 |"""


def test_caption_header_and_real_empty_column_are_preserved():
    source = """前言
    <table><caption>1、主机最大支持CAN扩展资源注：①经典系列</caption>
    <tr><th></th><th>E400B</th><th>E401B</th><th>E500B</th><th></th><th>E501B</th></tr>
    <tr><td>IA321A</td><td>2</td><td></td><td>1</td><td></td><td>2 ①</td></tr>
    </table>
    后文"""

    result = normalize_mineru_html_tables(source)

    assert result.startswith("前言\n\n1、主机最大支持CAN扩展资源注：①经典系列\n\n")
    assert "|  | E400B | E401B | E500B |  | E501B |" in result
    assert "| IA321A | 2 |  | 1 |  | 2 ① |" in result
    assert result.endswith("\n\n后文")


def test_normalization_gate_is_pipeline_mineru_markdown_only():
    assert should_normalize_mineru_tables("model@instance@MinerU", "markdown", True)
    assert not should_normalize_mineru_tables("model@instance@MinerU", "json", True)
    assert not should_normalize_mineru_tables("DeepDOC", "markdown", True)
    assert not should_normalize_mineru_tables("model@instance@MinerU", "markdown", False)
```

- [ ] **Step 2: Run the new test module and verify RED**

Run:

```powershell
& 'D:\Anaconda\python.exe' -m pytest test\unit_test\rag\flow\parser\test_mineru_table_markdown.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'rag.flow.parser.mineru_table_markdown'`.

- [ ] **Step 3: Implement the minimal structural converter**

Implement `rag/flow/parser/mineru_table_markdown.py` with:

```python
import html
import logging
import re

from bs4 import BeautifulSoup, NavigableString, Tag

LOGGER = logging.getLogger(__name__)
_TABLE_RE = re.compile(r"<\s*table\b", re.IGNORECASE)


def should_normalize_mineru_tables(parse_method: str, output_format: str, enabled: bool) -> bool:
    method = str(parse_method or "").strip().lower()
    return bool(enabled) and output_format == "markdown" and (method == "mineru" or method.endswith("@mineru"))


def _span(value: object) -> int:
    try:
        return max(1, int(str(value)))
    except (TypeError, ValueError):
        return 1


def _cell_text(cell: Tag) -> str:
    for br in cell.find_all("br"):
        br.replace_with("<br>")
    value = cell.get_text(" ", strip=True)
    value = re.sub(r"\s*<br>\s*", "<br>", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value.replace("|", r"\|")


def _table_grid(table: Tag) -> tuple[list[list[str]], int | None]:
    rows: list[list[str]] = []
    active: dict[int, tuple[int, str]] = {}
    header_index: int | None = None
    for row_tag in table.find_all("tr"):
        row: list[str] = []
        column = 0

        def consume_active() -> None:
            nonlocal column
            while column in active:
                remaining, value = active[column]
                row.append(value)
                if remaining <= 1:
                    del active[column]
                else:
                    active[column] = (remaining - 1, "")
                column += 1

        consume_active()
        cells = row_tag.find_all(["th", "td"], recursive=False)
        if header_index is None and any(cell.name == "th" for cell in cells):
            header_index = len(rows)
        for cell in cells:
            consume_active()
            value = _cell_text(cell)
            rowspan = _span(cell.get("rowspan"))
            colspan = _span(cell.get("colspan"))
            for offset in range(colspan):
                row.append(value if offset == 0 else "")
                if rowspan > 1:
                    active[column + offset] = (rowspan - 1, "")
            column += colspan
        consume_active()
        rows.append(row)
    width = max((len(row) for row in rows), default=0)
    return [row + [""] * (width - len(row)) for row in rows], header_index


def _pipe_row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _table_to_markdown(table: Tag) -> str:
    caption = table.caption.get_text(" ", strip=True) if table.caption else ""
    rows, header_index = _table_grid(table)
    if not rows or not rows[0]:
        return table.get_text(" ", strip=True)
    width = len(rows[0])
    if header_index is None:
        rendered = [_pipe_row([""] * width), _pipe_row(["---"] * width)]
        rendered.extend(_pipe_row(row) for row in rows)
    else:
        header = rows[header_index]
        data = rows[:header_index] + rows[header_index + 1 :]
        rendered = [_pipe_row(header), _pipe_row(["---"] * width)]
        rendered.extend(_pipe_row(row) for row in data)
    table_markdown = "\n".join(rendered)
    return f"{caption}\n\n{table_markdown}" if caption else table_markdown


def normalize_mineru_html_tables(text: str) -> str:
    if not text:
        return ""
    decoded = html.unescape(text)
    if not _TABLE_RE.search(decoded):
        return text
    try:
        soup = BeautifulSoup(decoded, "html.parser")
        for table in list(soup.find_all("table")):
            table.replace_with(NavigableString(_table_to_markdown(table)))
        result = soup.get_text()
        result = re.sub(r"[ \t]+\n", "\n", result)
        result = re.sub(r"\n{3,}", "\n\n", result)
        return result.strip()
    except Exception:
        LOGGER.warning("Failed to normalize a MinerU HTML table block; preserving original content", exc_info=True)
        return text
```

- [ ] **Step 4: Add edge-case tests and verify they fail before completing behavior**

Add tests for entity-escaped markup, multiple tables, literal `a < b`, `|`, `<br>`, malformed/empty tables, and this merged-cell grid:

```python
def test_rowspan_and_colspan_expand_to_empty_coordinates():
    source = """<table>
    <tr><th rowspan="2">Model</th><th colspan="2">CAN</th></tr>
    <tr><th>A</th><th>B</th></tr>
    <tr><td>X</td><td>1</td><td>2</td></tr>
    </table>"""

    assert normalize_mineru_html_tables(source) == """| Model | CAN |  |
| --- | --- | --- |
|  | A | B |
| X | 1 | 2 |"""
```

Run the same targeted pytest command. Expected: at least one new edge-case test fails for the intended missing behavior, not an import or syntax error.

- [ ] **Step 5: Complete the helper while keeping the public interfaces unchanged**

Adjust the internal grid and fragment-walking helpers so all edge-case tests pass. Keep `normalize_mineru_html_tables()` and `should_normalize_mineru_tables()` as the only public functions in Task 1 and do not add dependencies; Task 2 adds the third public bbox helper required by the Parser integration.

- [ ] **Step 6: Run focused tests and commit**

Run:

```powershell
& 'D:\Anaconda\python.exe' -m pytest test\unit_test\rag\flow\parser\test_mineru_table_markdown.py -q
```

Expected: all tests pass.

Commit:

```powershell
git add rag/flow/parser/mineru_table_markdown.py test/unit_test/rag/flow/parser/test_mineru_table_markdown.py
git commit -m "feat(flow): normalize MinerU tables as markdown"
```

---

### Task 2: Opt-In Custom Pipeline Parser Integration

**Files:**
- Modify: `rag/flow/parser/parser.py`
- Modify: `test/unit_test/rag/flow/parser/test_mineru_table_markdown.py`

**Interfaces:**
- Consumes: `normalize_mineru_html_tables(text: str) -> str` and `should_normalize_mineru_tables(parse_method: str, output_format: str, enabled: bool) -> bool` from Task 1.
- Produces: opted-in MinerU Markdown Parser output whose table bbox text is Markdown before document assembly.

- [ ] **Step 1: Write a failing bbox-normalization integration test**

Write the test first against the wished-for `normalize_mineru_table_bboxes(bboxes: list[dict]) -> list[dict]` API:

```python
def test_normalize_bboxes_copies_records_and_changes_only_table_markup():
    original = [
        {"text": "Title", "layout_type": "title"},
        {"text": "<table><tr><td>A</td><td>B</td></tr></table>", "layout_type": "table"},
    ]

    normalized = normalize_mineru_table_bboxes(original)

    assert normalized[0] == original[0]
    assert normalized[1]["text"] == "|  |  |\n| --- | --- |\n| A | B |"
    assert original[1]["text"].startswith("<table>")
```

- [ ] **Step 2: Run the focused test and verify RED**

Run the Task 1 pytest command. Expected: import fails because `normalize_mineru_table_bboxes` does not yet exist.

- [ ] **Step 3: Implement bbox copying and wire the Parser gate**

Implement the helper with shallow record copies:

```python
def normalize_mineru_table_bboxes(bboxes: list[dict]) -> list[dict]:
    normalized = []
    for bbox in bboxes:
        item = dict(bbox)
        text = item.get("text")
        if isinstance(text, str):
            item["text"] = normalize_mineru_html_tables(text)
        normalized.append(item)
    return normalized
```

In `rag/flow/parser/parser.py`, import the three helpers and apply them immediately before the existing PDF output-format branch:

```python
if should_normalize_mineru_tables(
    parse_method,
    conf.get("output_format", ""),
    conf.get("normalize_mineru_tables_to_markdown", False),
):
    bboxes = normalize_mineru_table_bboxes(bboxes)
```

Do not put the gate in `deepdoc` and do not apply it to JSON output.

- [ ] **Step 4: Run focused tests and static checks**

Run:

```powershell
& 'D:\Anaconda\python.exe' -m pytest test\unit_test\rag\flow\parser\test_mineru_table_markdown.py -q
& 'D:\Anaconda\python.exe' -m compileall -q rag\flow\parser\mineru_table_markdown.py rag\flow\parser\parser.py
```

Expected: pytest passes and compileall produces no output.

- [ ] **Step 5: Commit**

```powershell
git add rag/flow/parser/parser.py rag/flow/parser/mineru_table_markdown.py test/unit_test/rag/flow/parser/test_mineru_table_markdown.py
git commit -m "feat(flow): gate MinerU markdown normalization"
```

---

### Task 3: Pipeline Parser Form Setting

**Files:**
- Modify: `web/src/pages/agent/form/parser-form/pdf-form-fields.tsx`
- Modify: `web/src/pages/agent/form/parser-form/index.tsx`
- Modify: `web/src/pages/agent/constant/pipeline.tsx`
- Create: `web/src/pages/agent/form/parser-form/pdf-form-fields.test.tsx`
- Modify: `web/src/locales/en.ts`
- Modify: `web/src/locales/zh.ts`

**Interfaces:**
- Consumes: dynamic MinerU parse-method strings whose lower-case value is either `mineru` or ends in `@mineru`.
- Produces: `normalize_mineru_tables_to_markdown: boolean` in the Parser PDF setup serialized by existing form-change and DSL logic.

- [ ] **Step 1: Write the failing parse-method visibility test**

Export a pure predicate from `pdf-form-fields.tsx` and test the wished-for API:

```tsx
import { isMinerUParseMethod } from './pdf-form-fields';

describe('isMinerUParseMethod', () => {
  it('recognizes direct and provider-backed MinerU values only', () => {
    expect(isMinerUParseMethod('MinerU')).toBe(true);
    expect(isMinerUParseMethod('mineru-from-env@instance@MinerU')).toBe(true);
    expect(isMinerUParseMethod('DeepDOC')).toBe(false);
    expect(isMinerUParseMethod(undefined)).toBe(false);
  });
});
```

- [ ] **Step 2: Install frontend dependencies if absent and verify RED**

If `web/node_modules` is absent, run `npm install` from `web/`. Then run:

```powershell
npm test -- --runTestsByPath src/pages/agent/form/parser-form/pdf-form-fields.test.tsx --coverage=false
```

Expected: test compilation fails because `isMinerUParseMethod` is not exported.

- [ ] **Step 3: Add schema/defaults and the MinerU-only switch**

Add to the Parser Zod item schema and appended defaults:

```tsx
normalize_mineru_tables_to_markdown: z.boolean().optional(),
```

```tsx
normalize_mineru_tables_to_markdown: false,
```

Add the same `false` default to the PDF entry in `initialParserValues`.

In `pdf-form-fields.tsx`, import `Switch`, export:

```tsx
export function isMinerUParseMethod(value: unknown): boolean {
  const method = String(value ?? '').trim().toLowerCase();
  return method === 'mineru' || method.endsWith('@mineru');
}
```

When `isMinerUParseMethod(parseMethod)` is true, render:

```tsx
<RAGFlowFormItem
  name={buildFieldNameWithPrefix(
    'normalize_mineru_tables_to_markdown',
    prefix,
  )}
  label={t('flow.normalizeMineruTablesToMarkdown')}
  tooltip={t('flow.normalizeMineruTablesToMarkdownTip')}
  horizontal
  labelClassName="w-full"
  valueClassName="w-8"
>
  {(field) => (
    <Switch
      checked={Boolean(field.value)}
      onCheckedChange={field.onChange}
    />
  )}
</RAGFlowFormItem>
```

- [ ] **Step 4: Add exact English and Chinese copy**

Under each locale's `flow` section, add:

```tsx
normalizeMineruTablesToMarkdown: 'Convert MinerU tables to Markdown',
normalizeMineruTablesToMarkdownTip:
  'Experimental. In this custom pipeline only, convert MinerU HTML tables to compact Markdown before chunking and model processing.',
```

```tsx
normalizeMineruTablesToMarkdown: '将 MinerU 表格转换为 Markdown',
normalizeMineruTablesToMarkdownTip:
  '实验功能。仅在当前自定义流水线中，将 MinerU HTML 表格转换为紧凑的 Markdown，再进行分块和模型处理。',
```

- [ ] **Step 5: Run focused frontend tests, formatting, and type checking**

Run from `web/`:

```powershell
npm test -- --runTestsByPath src/pages/agent/form/parser-form/pdf-form-fields.test.tsx --coverage=false
npm run format:check -- --ignore-unknown src/pages/agent/form/parser-form/pdf-form-fields.tsx src/pages/agent/form/parser-form/pdf-form-fields.test.tsx src/pages/agent/form/parser-form/index.tsx src/pages/agent/constant/pipeline.tsx src/locales/en.ts src/locales/zh.ts
npm run type-check
```

Expected: focused Jest test passes, Prettier reports all listed files formatted, and TypeScript exits successfully.

- [ ] **Step 6: Commit**

```powershell
git add web/src/pages/agent/form/parser-form/pdf-form-fields.tsx web/src/pages/agent/form/parser-form/pdf-form-fields.test.tsx web/src/pages/agent/form/parser-form/index.tsx web/src/pages/agent/constant/pipeline.tsx web/src/locales/en.ts web/src/locales/zh.ts
git commit -m "feat(web): configure MinerU markdown tables"
```

---

### Task 4: Documentation and Final Verification

**Files:**
- Modify: `docs/guides/agent/agent_component_reference/parser.md`

**Interfaces:**
- Consumes: the exact UI field and behavior implemented in Tasks 1–3.
- Produces: user guidance for enabling the option in one custom pipeline and comparing enabled/disabled runs.

- [ ] **Step 1: Document the setting beside the MinerU custom-pipeline instructions**

After the existing custom ingestion pipeline MinerU selection step, add:

```markdown
#### Normalize MinerU tables for model processing

In a custom ingestion pipeline, enable **Convert MinerU tables to Markdown** in the PDF Parser to replace MinerU's HTML table markup with compact Markdown before chunking and model processing. The option is disabled by default and affects only that pipeline, so you can duplicate a pipeline and compare enabled and disabled runs. Empty cells and columns are retained; merged HTML cells are expanded into a rectangular Markdown grid.
```

- [ ] **Step 2: Run all focused backend tests and source checks**

```powershell
& 'D:\Anaconda\python.exe' -m pytest test\unit_test\rag\flow\parser\test_mineru_table_markdown.py -q
& 'D:\Anaconda\python.exe' -m compileall -q rag\flow\parser\mineru_table_markdown.py rag\flow\parser\parser.py
git diff --check
```

Expected: tests pass, compileall is silent, and `git diff --check` is silent.

- [ ] **Step 3: Run focused frontend verification**

From `web/`:

```powershell
npm test -- --runTestsByPath src/pages/agent/form/parser-form/pdf-form-fields.test.tsx --coverage=false
npm run type-check
```

Expected: Jest and TypeScript pass.

- [ ] **Step 4: Inspect the final diff for scope**

```powershell
git status --short
git diff --stat HEAD~3
git diff HEAD~3 -- deepdoc/parser/mineru_parser.py
```

Expected: only planned files are changed, and the final command has no output because the shared MinerU adapter was not modified.

- [ ] **Step 5: Commit documentation**

```powershell
git add docs/guides/agent/agent_component_reference/parser.md
git commit -m "docs: explain MinerU pipeline markdown option"
```

- [ ] **Step 6: Record final evidence**

```powershell
git status --short --branch
git log -5 --oneline
```

Expected: clean worktree on the current branch, with the design commit followed by converter, integration, frontend, and documentation commits.
