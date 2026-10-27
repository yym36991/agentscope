# -*- coding: utf-8 -*-
"""Artifact export service (architecture.md §9, M5): md → docx / xlsx.

The stage agents deliver Markdown; the platform's deliverable formats
are Word for documents (PRD / test cases / reports — §13 decision 1)
and Excel for the list-shaped ones (function-point and budget tables).
This module is the "自建件" §8.1 lists: AgentScope has no document
generation, so L1 renders the stored artifact bytes itself.

The Markdown subset is what the seeded agents actually emit — headings,
paragraphs, bold/inline-code, bullet and numbered lists, pipe tables,
fenced code, blockquotes, horizontal rules. Anything else degrades to a
plain paragraph rather than failing the export.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

# ---------------------------------------------------------------------------
# Markdown → block list
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_ULIST_RE = re.compile(r"^[-*+]\s+(.*)$")
_OLIST_RE = re.compile(r"^\d+[.、)]\s+(.*)$")
_HR_RE = re.compile(r"^(-{3,}|\*{3,}|_{3,})$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}.*\|")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")


@dataclass
class Block:
    kind: str  # heading | para | list | table | code | quote | hr
    level: int = 0
    text: str = ""
    ordered: bool = False
    items: list[str] | None = None
    header: list[str] | None = None
    rows: list[list[str]] | None = None


def _split_table_row(line: str) -> list[str]:
    """`| a | b |` → ['a', 'b'] (leading/trailing pipes dropped)."""
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [c.strip().replace(r"\|", "|") for c in stripped.split("|")]


def parse_markdown(md: str) -> list[Block]:
    """Split artifact Markdown into renderable blocks."""
    blocks: list[Block] = []
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.lstrip().startswith("```"):
            fence = []
            i += 1
            while i < len(lines) and not lines[i].lstrip().startswith("```"):
                fence.append(lines[i])
                i += 1
            i += 1  # closing fence
            blocks.append(Block("code", text="\n".join(fence)))
            continue
        if (m := _HEADING_RE.match(line)) :
            blocks.append(Block("heading", level=len(m.group(1)), text=m.group(2)))
            i += 1
            continue
        if _HR_RE.match(line.strip()):
            blocks.append(Block("hr"))
            i += 1
            continue
        if line.strip().startswith("|") and i + 1 < len(lines) and _TABLE_SEP_RE.match(lines[i + 1]):
            header = _split_table_row(line)
            i += 2
            rows: list[list[str]] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(_split_table_row(lines[i]))
                i += 1
            blocks.append(Block("table", header=header, rows=rows))
            continue
        if (m := _ULIST_RE.match(line)) or (m := _OLIST_RE.match(line)):
            ordered = bool(_OLIST_RE.match(line))
            items = [m.group(1)]  # type: ignore[union-attr]
            i += 1
            while i < len(lines):
                nxt = lines[i]
                if (m2 := _ULIST_RE.match(nxt)) and not ordered:
                    items.append(m2.group(1))
                elif (m2 := _OLIST_RE.match(nxt)) and ordered:
                    items.append(m2.group(1))
                else:
                    break
                i += 1
            blocks.append(Block("list", ordered=ordered, items=items))
            continue
        if line.strip().startswith(">"):
            quote = [line.strip().lstrip(">").strip()]
            i += 1
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip().lstrip(">").strip())
                i += 1
            blocks.append(Block("quote", text="\n".join(q for q in quote if q)))
            continue
        blocks.append(Block("para", text=line.strip()))
        i += 1
    return blocks


def _inline_plain(text: str) -> str:
    """Strip inline markers for plain-text cells (xlsx / table bodies)."""
    text = _LINK_RE.sub(r"\1（\2）", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    return text.replace("`", "")


# ---------------------------------------------------------------------------
# docx
# ---------------------------------------------------------------------------

_INLINE_TOKEN_RE = re.compile(r"(\*\*.+?\*\*|`[^`]+`|\[[^\]]+\]\([^)\s]+\))")


def _set_east_asian(doc: Document) -> None:
    """Base fonts that render CJK correctly (Calibri + 微软雅黑)."""
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10.5)
    normal.element.get_or_add_rPr().get_or_add_rFonts().set(
        qn("w:eastAsia"), "微软雅黑"
    )
    for name in ("Title", "Heading 1", "Heading 2", "Heading 3", "Heading 4"):
        style = doc.styles[name]
        style.element.get_or_add_rPr().get_or_add_rFonts().set(
            qn("w:eastAsia"), "微软雅黑"
        )


def _add_runs(paragraph, text: str) -> None:
    """Add text with **bold** / `code` / [link](url) rendered."""
    for token in _INLINE_TOKEN_RE.split(text):
        if not token:
            continue
        if token.startswith("**") and token.endswith("**"):
            run = paragraph.add_run(token[2:-2])
            run.bold = True
        elif token.startswith("`") and token.endswith("`"):
            run = paragraph.add_run(token[1:-1])
            run.font.name = "Consolas"
        elif token.startswith("["):
            m = re.match(r"\[([^\]]+)\]\(([^)]+)\)", token)
            if m:
                paragraph.add_run(f"{m.group(1)}（{m.group(2)}）")
            else:
                paragraph.add_run(token)
        else:
            paragraph.add_run(token)


def md_to_docx(title: str, meta: list[str], md: str) -> bytes:
    """Render one artifact's Markdown into a Word document."""
    doc = Document()
    _set_east_asian(doc)
    doc.add_heading(title, 0)
    meta_para = doc.add_paragraph()
    meta_para.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run = meta_para.add_run(" ｜ ".join(meta))
    run.font.size = Pt(9)
    run.font.color.rgb = RGBColor(0x66, 0x66, 0x66)
    for block in parse_markdown(md):
        if block.kind == "heading":
            doc.add_heading(block.text, min(block.level, 4))
        elif block.kind == "para":
            _add_runs(doc.add_paragraph(), block.text)
        elif block.kind == "list":
            for item in block.items or []:
                _add_runs(doc.add_paragraph(style="List Bullet" if not block.ordered else "List Number"), item)
        elif block.kind == "quote":
            para = doc.add_paragraph()
            _add_runs(para, block.text.replace("\n", " "))
            for r in para.runs:
                r.italic = True
                r.font.color.rgb = RGBColor(0x59, 0x59, 0x59)
        elif block.kind == "code":
            para = doc.add_paragraph()
            run = para.add_run(block.text)
            run.font.name = "Consolas"
            run.font.size = Pt(9)
        elif block.kind == "table":
            table = doc.add_table(rows=1, cols=len(block.header or []))
            table.style = "Table Grid"
            for idx, cell_text in enumerate(block.header or []):
                cell = table.rows[0].cells[idx]
                para = cell.paragraphs[0]
                run = para.add_run(_inline_plain(cell_text))
                run.bold = True
            for row in block.rows or []:
                cells = table.add_row().cells
                for idx, cell_text in enumerate(row[: len(cells)]):
                    cells[idx].paragraphs[0].add_run(_inline_plain(cell_text))
        elif block.kind == "hr":
            doc.add_paragraph("─" * 40).runs[0].font.color.rgb = RGBColor(
                0xCC, 0xCC, 0xCC
            )
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# xlsx
# ---------------------------------------------------------------------------


def _sheet_name(raw: str, used: set[str]) -> str:
    """Excel sheet names: ≤31 chars, no []:*?/\\, unique."""
    name = re.sub(r"[\[\]:*?/\\]", "-", raw).strip() or "表格"
    name = name[:31]
    base, n = name, 2
    while name in used:
        suffix = f"({n})"
        name = base[: 31 - len(suffix)] + suffix
        n += 1
    used.add(name)
    return name


def md_to_xlsx(title: str, meta: list[str], md: str) -> bytes:
    """Render one artifact's Markdown into a workbook.

    Every table becomes its own worksheet (named after the nearest
    preceding heading); non-table content is listed on a leading
    “说明” sheet. List-shaped artifacts (function-point details, budget
    tables) are the target shape — a table-free document exports as one
    description sheet.
    """
    wb = Workbook()
    info = wb.active
    info.title = "说明"
    info["A1"] = title
    info["A1"].font = Font(bold=True, size=14)
    row = 3
    for line in meta:
        info.cell(row=row, column=1, value=line).font = Font(
            color="FF666666", size=9
        )
        row += 1
    row += 1

    used_names: set[str] = {"说明"}
    pending_heading = title
    for block in parse_markdown(md):
        if block.kind == "heading":
            pending_heading = block.text
            info.cell(row=row, column=1, value=block.text).font = Font(bold=True)
            row += 1
        elif block.kind == "table":
            sheet = wb.create_sheet(_sheet_name(pending_heading, used_names))
            for c, cell_text in enumerate(block.header or [], start=1):
                cell = sheet.cell(row=1, column=c, value=_inline_plain(cell_text))
                cell.font = Font(bold=True)
            for r, row_cells in enumerate(block.rows or [], start=2):
                for c, cell_text in enumerate(row_cells, start=1):
                    sheet.cell(
                        row=r, column=c, value=_inline_plain(cell_text)
                    )
            sheet.freeze_panes = "A2"
            for c in range(1, len(block.header or []) + 1):
                width = 8
                for r in range(1, len(block.rows or []) + 2):
                    val = sheet.cell(row=r, column=c).value
                    if val:
                        # CJK chars count double in Excel's width units.
                        text = str(val)
                        width = max(
                            width,
                            min(40, len(text) + sum(1 for ch in text if ord(ch) > 0x2E80) + 2),
                        )
                sheet.column_dimensions[get_column_letter(c)].width = width
            info.cell(
                row=row, column=1, value=f"◆ 表格「{pending_heading}」→ 工作表"
            ).font = Font(color="FF1F7AC2")
            row += 1
        elif block.kind == "para":
            info.cell(row=row, column=1, value=_inline_plain(block.text))
            row += 1
        elif block.kind == "list":
            for idx, item in enumerate(block.items or [], start=1):
                mark = f"{idx}. " if block.ordered else "• "
                info.cell(row=row, column=1, value=mark + _inline_plain(item))
                row += 1
        elif block.kind == "quote":
            info.cell(row=row, column=1, value="“" + _inline_plain(block.text) + "”")
            row += 1
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
