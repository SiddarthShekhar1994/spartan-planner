"""Turn an uploaded PDF or Word file into plain text, and tidy text before Claude reads it.

Any parser failure becomes ``AppError("unreadable_file")``. Only the exception's class name is
logged, never its message, because parser messages can quote the file's contents.
"""

from __future__ import annotations

import logging
import re
import zipfile
from collections.abc import Iterable, Iterator
from typing import Any, BinaryIO, Literal

import docx
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph
from pypdf import PdfReader

from backend.errors import AppError

logger = logging.getLogger("spartan.text_extraction")

FileKind = Literal["pdf", "docx"]

PDF_PAGE_SEPARATOR = "\n\n"
CELL_SEPARATOR = " | "
# Stop reading a PDF once its text passes this many characters. It is far above the route's
# 150,000-character limit, so no real syllabus reaches it, and it stops a small PDF whose pages
# all share one big content stream from building tens of millions of characters.
MAX_PDF_TEXT_CHARS = 1_000_000
# A .docx is a zip archive. Refuse one that would unpack to more than this, so a small upload
# can't expand into gigabytes of memory (a "zip bomb"). A real syllabus unpacks to a few MB.
MAX_DOCX_UNPACKED_BYTES = 50 * 1024 * 1024

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
# python-docx only reads paragraphs, tables and runs that sit directly in their parent, so text
# inside these wrappers would be skipped. They are lifted out (in memory only) before reading:
# content controls (sdt), custom XML, smart tags, tracked insertions and moves, simple fields
# such as a date field, and bidirectional-text runs.
_SDT = _W + "sdt"
_SDT_CONTENT = _W + "sdtContent"
_LIFT_TAGS = tuple(_W + tag for tag in ("customXml", "smartTag", "ins", "moveTo", "fldSimple", "dir", "bdo"))
# Tracked deletions and moved-away text are not part of the document as it reads now.
_DROP_TAGS = tuple(_W + tag for tag in ("del", "moveFrom"))

_EXTRA_BLANK_LINES = re.compile(r"\n{3,}")


def detect_kind(filename: str | None, head: bytes) -> FileKind | None:
    """The file's kind when its name and its first bytes agree, else None."""
    name = (filename or "").strip().lower()
    if name.endswith(".pdf") and b"%PDF-" in head[:1024]:
        return "pdf"
    if name.endswith(".docx") and head.startswith(b"PK\x03\x04"):
        return "docx"
    return None


def extract_text(fileobj: BinaryIO, kind: FileKind) -> str:
    """All the text in the file, or "" when it has none (a scan, say). The caller decides what to do."""
    readers = {"pdf": _pdf_text, "docx": _docx_text}
    reader = readers.get(kind)
    if reader is None:
        raise ValueError(f"unsupported file kind: {kind!r}")
    try:
        fileobj.seek(0)
        text = reader(fileobj)
    except AppError:
        raise
    except Exception as exc:  # parsers raise many unrelated types on damaged or locked files
        logger.warning("file_unreadable kind=%s error=%s", kind, type(exc).__name__)
        raise AppError("unreadable_file") from None
    return text if text.strip() else ""


def normalize_text(text: str) -> str:
    """Line endings to LF, no NUL characters, no trailing spaces, at most one blank line in a row."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    # Split and rstrip instead of a regex: a regex like [ \t]+$ backtracks badly on long space runs.
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = _EXTRA_BLANK_LINES.sub("\n\n", text)
    return text.strip()


def meaningful_length(text: str) -> int:
    """How many non-whitespace characters the text has."""
    return sum(1 for ch in text if not ch.isspace())


# --- PDF ----------------------------------------------------------------------------------------
def _pdf_text(fileobj: BinaryIO) -> str:
    # The constructor already tries the empty password, so files that are only permission-locked
    # open; a file that needs a real password fails on the first page with FileNotDecryptedError.
    reader = PdfReader(fileobj)
    parts: list[str] = []
    total = 0
    for page in reader.pages:
        text = page.extract_text() or ""
        total += len(text) + len(PDF_PAGE_SEPARATOR)
        if total > MAX_PDF_TEXT_CHARS:
            raise AppError("text_too_long")
        parts.append(text)
    return PDF_PAGE_SEPARATOR.join(parts)


# --- Word (.docx) -------------------------------------------------------------------------------
def _docx_text(fileobj: BinaryIO) -> str:
    _check_unpacked_size(fileobj)
    document = docx.Document(fileobj)
    lines: list[str] = []
    if len(document.sections) > 0:
        section = document.sections[0]
        # A "Different First Page" header comes first, then the running header.
        headers = [section.first_page_header] if section.different_first_page_header_footer else []
        headers.append(section.header)
        for header in headers:
            # Only the first section's own headers. Checked before touching .part, which would
            # otherwise add an empty header definition.
            if not header.is_linked_to_previous:
                _lift_wrapped_content(header.part.element)
                lines.extend(_block_lines(header.iter_inner_content()))
    _lift_wrapped_content(document.element)
    lines.extend(_block_lines(document.iter_inner_content()))
    return "\n".join(lines)


def _check_unpacked_size(fileobj: BinaryIO) -> None:
    with zipfile.ZipFile(fileobj) as archive:  # leaves fileobj open
        unpacked = sum(info.file_size for info in archive.infolist())
    fileobj.seek(0)
    if unpacked > MAX_DOCX_UNPACKED_BYTES:
        logger.warning("file_unreadable kind=docx error=unpacked_too_large")
        raise AppError("unreadable_file")


def _is_properties(element: Any) -> bool:
    return isinstance(element.tag, str) and element.tag.endswith("Pr")


def _lift_wrapped_content(root: Any) -> None:
    """Move the content of wrapper elements up into their parent, in document order."""
    for element in list(root.iter(_SDT, *_LIFT_TAGS, *_DROP_TAGS)):
        parent = element.getparent()
        if parent is None:
            continue
        if element.tag in _DROP_TAGS:
            parent.remove(element)
            continue
        if element.tag == _SDT:
            content = element.find(_SDT_CONTENT)
            children = list(content) if content is not None else []
        else:
            children = [child for child in element if not _is_properties(child)]
        for child in children:
            element.addprevious(child)
        parent.remove(element)


def _block_lines(blocks: Iterable[Paragraph | Table]) -> Iterator[str]:
    for block in blocks:
        if isinstance(block, Table):
            yield from _table_lines(block)
        else:
            yield block.text


def _table_lines(table: Table) -> Iterator[str]:
    """One line per row, cells joined with " | "."""
    # One pass over the table's XML. python-docx's row.cells walks up the column, one row at a
    # time, for every vertically merged cell, which gets slow fast on a big merged table.
    # Merged cells read as before: a horizontally merged cell is one <w:tc> spanning several grid
    # columns, so it counts once, and a vertically merged cell repeats its text on every row it
    # covers, read from the <w:tc> where the merge starts (the one above it, or that one's start).
    above: dict[int, Any] = {}  # grid column -> the <w:tc> whose text the cell starting there shows
    for tr in table._tbl.tr_lst:
        texts: list[str] = []
        shown: dict[int, Any] = {}
        previous_tc = None
        offset = tr.grid_before
        for tc in tr.tc_lst:
            root = above.get(offset, tc) if tc.vMerge == "continue" else tc
            shown[offset] = root
            offset += tc.grid_span
            if root is previous_tc:
                continue
            previous_tc = root
            texts.append(_cell_text(_Cell(root, table)))
        above = shown
        yield CELL_SEPARATOR.join(texts)


def _cell_text(cell: _Cell) -> str:
    """A cell's paragraphs (and any table nested in it) on one line, so each row stays one line."""
    parts: list[str] = []
    for block in cell.iter_inner_content():
        if isinstance(block, Table):
            parts.extend(_table_lines(block))
        else:
            parts.append(block.text)
    # split() also folds line breaks inside the cell; it runs in linear time on any input.
    return " ".join(" ".join(parts).split())
