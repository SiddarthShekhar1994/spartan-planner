"""backend/services/text_extraction.py: file sniffing, PDF and Word text, and text cleanup."""

from __future__ import annotations

import io
import tempfile
import time
import zipfile

import docx
import pytest
from pypdf import PageObject, PdfReader, PdfWriter

from backend.config import Settings
from backend.errors import AppError

PDF_HEAD = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
ZIP_HEAD = b"PK\x03\x04\x14\x00\x06\x00"

DOCX_HEADER = "CS 101 · Fall 2026 · Dr. Rivera"
DOCX_BLOCKS = [
    "CS 101: Introduction to Programming",
    "Quiz 1 is on Thursday, September 10, at the start of class.",
    [
        ["Week", "Date", "Due", "Notes"],
        ["Week 9", "Oct 19", "Homework 4 due", None],  # "Homework 4 due" spans the last two columns
        ["Week 11", "Nov 2", "Lecture", "Bring a laptop"],
    ],
    "The final exam is Monday, December 14, 9:45–12:00, in our usual room.",
]


def pdf_bytes(writer: PdfWriter) -> bytes:
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def docx_bytes(document) -> bytes:
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def merged_columns_docx(rows: int, cols: int = 10) -> bytes:
    """A table whose first row starts a vertical merge in every column that covers every row below."""
    document = docx.Document()
    document.add_paragraph("CS 101 schedule")
    table = document.add_table(rows=rows, cols=cols)
    for row_index, tr in enumerate(table._tbl.tr_lst):
        for col_index, tc in enumerate(tr.tc_lst):
            if row_index == 0:
                tc.p_lst[0].add_r().text = f"Week {col_index}"
            tc.vMerge = "restart" if row_index == 0 else "continue"
    return docx_bytes(document)


def assert_unreadable(text_extraction, data: bytes, kind: str) -> None:
    with pytest.raises(AppError) as caught:
        text_extraction.extract_text(io.BytesIO(data), kind)
    assert caught.value.code == "unreadable_file"
    assert caught.value.status == 422


# ---------------------------------------------------------------------------
# detect_kind
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("filename", "head", "expected"),
    [
        ("syllabus.pdf", PDF_HEAD, "pdf"),
        ("SYLLABUS.PDF", PDF_HEAD, "pdf"),
        ("My Syllabus (final).Pdf", PDF_HEAD, "pdf"),
        ("syllabus.pdf", b"\x00" * 500 + PDF_HEAD, "pdf"),  # %PDF- may come after some junk
        ("syllabus.docx", ZIP_HEAD, "docx"),
        ("Syllabus.DOCX", ZIP_HEAD, "docx"),
        ("syllabus.pdf", b"x" * 1024 + PDF_HEAD, None),  # only the first 1024 bytes count
        ("syllabus.pdf", b"This is plain text, not a PDF.", None),
        ("syllabus.pdf", ZIP_HEAD, None),
        ("syllabus.pdf", b"", None),
        ("syllabus.docx", PDF_HEAD, None),
        ("syllabus.docx", b"xx" + ZIP_HEAD, None),  # must start with the zip signature
        ("syllabus.docx", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", None),  # old binary .doc content
        ("syllabus.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", None),
        ("syllabus.txt", PDF_HEAD, None),
        ("syllabus.pdf.exe", PDF_HEAD, None),
        ("syllabus", PDF_HEAD, None),
        ("", PDF_HEAD, None),
        (None, PDF_HEAD, None),
    ],
)
def test_detect_kind(text_extraction, filename, head, expected):
    assert text_extraction.detect_kind(filename, head) == expected


def test_detect_kind_on_the_real_fixtures(text_extraction, sample_pdf_bytes, make_docx):
    assert text_extraction.detect_kind("cs101.pdf", sample_pdf_bytes[:1024]) == "pdf"
    assert text_extraction.detect_kind("cs101.docx", make_docx(["Hello"])[:1024]) == "docx"


# ---------------------------------------------------------------------------
# extract_text: PDF
# ---------------------------------------------------------------------------
def test_pdf_fixture_text(text_extraction, sample_pdf_bytes):
    text = text_extraction.extract_text(io.BytesIO(sample_pdf_bytes), "pdf")
    assert isinstance(text, str)
    assert "Quiz 1 is on Thursday, September 10" in text
    assert "Homework 4 due" in text
    assert "Fall 2026" in text


def test_pdf_pages_are_joined_with_a_blank_line(text_extraction, sample_pdf_bytes, fixture_pdf_page_text):
    writer = PdfWriter(clone_from=io.BytesIO(sample_pdf_bytes))
    writer.append(io.BytesIO(sample_pdf_bytes))
    two_pages = pdf_bytes(writer)
    text = text_extraction.extract_text(io.BytesIO(two_pages), "pdf")
    assert text == fixture_pdf_page_text + "\n\n" + fixture_pdf_page_text


def test_blank_pdf_gives_empty_text(text_extraction, blank_pdf_bytes):
    assert text_extraction.extract_text(io.BytesIO(blank_pdf_bytes), "pdf") == ""


def test_permission_locked_pdf_is_read_with_the_empty_password(text_extraction, sample_pdf_bytes):
    writer = PdfWriter(clone_from=io.BytesIO(sample_pdf_bytes))
    writer.encrypt(user_password="", owner_password="owner-secret", algorithm="AES-256")
    text = text_extraction.extract_text(io.BytesIO(pdf_bytes(writer)), "pdf")
    assert "Quiz 1 is on Thursday, September 10" in text


def test_password_protected_pdf_is_unreadable(text_extraction, sample_pdf_bytes):
    writer = PdfWriter(clone_from=io.BytesIO(sample_pdf_bytes))
    writer.encrypt(user_password="open-sesame", owner_password="owner-secret", algorithm="AES-256")
    assert_unreadable(text_extraction, pdf_bytes(writer), "pdf")


@pytest.mark.parametrize(
    "make_corrupt",
    [
        lambda pdf: PDF_HEAD + b"this is not really a pdf " * 40,
        lambda pdf: pdf[: len(pdf) // 2],
        lambda pdf: pdf[:1000],
        lambda pdf: b"%PDF-1.7\n%%EOF\n",
    ],
    ids=["junk-after-header", "truncated-half", "truncated-start", "header-only"],
)
def test_corrupt_pdf_is_unreadable(text_extraction, sample_pdf_bytes, make_corrupt):
    assert_unreadable(text_extraction, make_corrupt(sample_pdf_bytes), "pdf")


def test_pdf_whose_pages_repeat_one_huge_stream_stops_at_the_cap(text_extraction, shared_stream_pdf_bytes, monkeypatch):
    """A few KB of PDF whose 30 pages all draw one ~100,000-character stream: reading stops at the cap."""
    page_lengths: list[int] = []
    original_extract_text = PageObject.extract_text

    def counting_extract_text(self, *args, **kwargs):
        text = original_extract_text(self, *args, **kwargs)
        page_lengths.append(len(text))
        return text

    monkeypatch.setattr(PageObject, "extract_text", counting_extract_text)
    assert len(shared_stream_pdf_bytes) < 20_000
    with pytest.raises(AppError) as caught:
        text_extraction.extract_text(io.BytesIO(shared_stream_pdf_bytes), "pdf")
    assert caught.value.code == "text_too_long"
    assert caught.value.status == 413
    page_count = len(PdfReader(io.BytesIO(shared_stream_pdf_bytes)).pages)
    assert sum(page_lengths) > text_extraction.MAX_PDF_TEXT_CHARS  # it really went over the cap...
    assert len(page_lengths) < page_count  # ...and stopped there instead of reading every page
    assert sum(page_lengths[:-1]) <= text_extraction.MAX_PDF_TEXT_CHARS


def test_pdf_text_cap_is_far_above_the_route_limit(text_extraction, tmp_path):
    """No real syllabus reaches the cap: the route already refuses text over max_text_chars."""
    settings = Settings(anthropic_api_key=None, claude_model="claude-haiku-5-5", database_path=tmp_path / "x.db")
    assert text_extraction.MAX_PDF_TEXT_CHARS >= 5 * settings.max_text_chars


# ---------------------------------------------------------------------------
# extract_text: DOCX
# ---------------------------------------------------------------------------
def test_docx_text_has_header_paragraphs_and_table_rows_in_order(text_extraction, make_docx):
    text = text_extraction.extract_text(io.BytesIO(make_docx(DOCX_BLOCKS, header=DOCX_HEADER)), "docx")
    lines = text.splitlines()
    assert "Week 9 | Oct 19 | Homework 4 due" in lines
    assert "Week | Date | Due | Notes" in lines
    assert "Week 11 | Nov 2 | Lecture | Bring a laptop" in lines
    order = [
        text.index(DOCX_HEADER),
        text.index("CS 101: Introduction to Programming"),
        text.index("Quiz 1 is on Thursday, September 10, at the start of class."),
        text.index("Week | Date | Due | Notes"),
        text.index("Week 9 | Oct 19 | Homework 4 due"),
        text.index("Week 11 | Nov 2 | Lecture | Bring a laptop"),
        text.index("The final exam is Monday, December 14, 9:45–12:00, in our usual room."),
    ]
    assert order == sorted(order)


def test_docx_merged_cell_is_counted_once(text_extraction, make_docx):
    text = text_extraction.extract_text(io.BytesIO(make_docx(DOCX_BLOCKS, header=DOCX_HEADER)), "docx")
    assert text.count("Week 9 | Oct 19 | Homework 4 due") == 1
    assert text.count("Homework 4 due") == 1
    assert "Homework 4 due | Homework 4 due" not in text


def test_docx_vertically_merged_cell_repeats_on_each_row(text_extraction):
    document = docx.Document()
    rows = [["Week", "Date", "Due"], ["Week 9", "Oct 19", "Homework 4 due"], ["", "Oct 21", "Quiz 3"]]
    table = document.add_table(rows=len(rows), cols=3)
    for row_index, values in enumerate(rows):
        for col_index, value in enumerate(values):
            table.cell(row_index, col_index).text = value
    table.cell(1, 0).merge(table.cell(2, 0))  # "Week 9" covers both rows
    text = text_extraction.extract_text(io.BytesIO(docx_bytes(document)), "docx")
    assert text.splitlines() == ["Week | Date | Due", "Week 9 | Oct 19 | Homework 4 due", "Week 9 | Oct 21 | Quiz 3"]


def test_docx_big_vertically_merged_table_is_read_quickly(text_extraction):
    """Every cell below the first row continues a vertical merge. python-docx's row.cells took about
    16 seconds on this 200-row table (4x more for each doubling); one pass over the XML takes well under 1."""
    data = merged_columns_docx(200)
    started = time.perf_counter()
    text = text_extraction.extract_text(io.BytesIO(data), "docx")
    elapsed = time.perf_counter() - started
    week_row = " | ".join(f"Week {col}" for col in range(10))
    assert text.splitlines() == ["CS 101 schedule"] + [week_row] * 200
    assert elapsed < 5, f"reading the merged table took {elapsed:.1f} s"


def test_docx_cell_claiming_a_huge_column_span_is_read_quickly(text_extraction):
    document = docx.Document()
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Week 9"
    table.cell(0, 1).text = "Homework 4 due"
    table._tbl.tr_lst[0].tc_lst[0].grid_span = 1_000_000_000  # python-docx's row.cells looped once per column
    started = time.perf_counter()
    text = text_extraction.extract_text(io.BytesIO(docx_bytes(document)), "docx")
    elapsed = time.perf_counter() - started
    assert text == "Week 9 | Homework 4 due"
    assert elapsed < 5, f"reading the table took {elapsed:.1f} s"


def test_docx_first_page_header_is_read(text_extraction):
    document = docx.Document()
    section = document.sections[0]
    section.different_first_page_header_footer = True
    section.first_page_header.is_linked_to_previous = False
    section.first_page_header.paragraphs[0].text = "CS 146: Data Structures, Fall 2026"
    document.add_paragraph("Midterm 1 is on Wednesday, October 14.")
    text = text_extraction.extract_text(io.BytesIO(docx_bytes(document)), "docx")
    assert text.splitlines() == ["CS 146: Data Structures, Fall 2026", "Midterm 1 is on Wednesday, October 14."]


def test_docx_first_page_header_comes_before_the_running_header(text_extraction):
    document = docx.Document()
    section = document.sections[0]
    section.different_first_page_header_footer = True
    section.first_page_header.is_linked_to_previous = False
    section.first_page_header.paragraphs[0].text = "CS 146: Data Structures, Fall 2026"
    section.header.is_linked_to_previous = False
    section.header.paragraphs[0].text = "CS 146 · Dr. Rivera"
    document.add_paragraph("Midterm 1 is on Wednesday, October 14.")
    text = text_extraction.extract_text(io.BytesIO(docx_bytes(document)), "docx")
    assert text.splitlines() == [
        "CS 146: Data Structures, Fall 2026",
        "CS 146 · Dr. Rivera",
        "Midterm 1 is on Wednesday, October 14.",
    ]


def test_docx_first_page_setting_without_a_first_page_header_adds_nothing(text_extraction):
    document = docx.Document()
    document.sections[0].different_first_page_header_footer = True
    document.add_paragraph("Midterm 1 is on Wednesday, October 14.")
    text = text_extraction.extract_text(io.BytesIO(docx_bytes(document)), "docx")
    assert text == "Midterm 1 is on Wednesday, October 14."


def test_docx_without_a_header_starts_with_the_body(text_extraction, make_docx):
    text = text_extraction.extract_text(io.BytesIO(make_docx(DOCX_BLOCKS)), "docx")
    assert text.strip().startswith("CS 101: Introduction to Programming")
    assert DOCX_HEADER not in text


def test_empty_docx_gives_no_text(text_extraction, make_docx):
    assert text_extraction.extract_text(io.BytesIO(make_docx([])), "docx").strip() == ""


def test_corrupt_docx_is_unreadable(text_extraction):
    assert_unreadable(text_extraction, ZIP_HEAD + b"not really a zip file" * 20, "docx")


def test_truncated_docx_is_unreadable(text_extraction, make_docx):
    data = make_docx(DOCX_BLOCKS)
    assert_unreadable(text_extraction, data[: len(data) // 2], "docx")


def test_zip_that_is_not_a_word_file_is_unreadable(text_extraction):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("notes.txt", "Quiz 1 is on Thursday, September 10.")
    assert_unreadable(text_extraction, buffer.getvalue(), "docx")


# ---------------------------------------------------------------------------
# extract_text works on the object the route actually passes: a spooled temp file
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("kind", ["pdf", "docx"])
def test_extract_text_reads_a_spooled_upload(text_extraction, spool_dir, sample_pdf_bytes, make_docx, kind):
    data = sample_pdf_bytes if kind == "pdf" else make_docx(DOCX_BLOCKS)
    with tempfile.SpooledTemporaryFile(max_size=1024) as upload:  # small max_size: rolls over to a real file
        upload.write(data)
        upload.seek(0)
        text = text_extraction.extract_text(upload, kind)
    assert "Quiz 1 is on Thursday, September 10" in text
    assert list(spool_dir.iterdir()) == []


# ---------------------------------------------------------------------------
# normalize_text
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("a\r\nb\rc", "a\nb\nc"),
        ("a\x00b", "ab"),
        ("line one   \nline two  ", "line one\nline two"),
        ("a\n\n\nb", "a\n\nb"),
        ("a\n\n\n\n\n\nb", "a\n\nb"),
        ("a\n\nb", "a\n\nb"),
        ("a\n   \n  \nb", "a\n\nb"),  # blank lines made only of spaces count as blank
        ("a\r\n\r\n\r\n\r\nb", "a\n\nb"),
        ("\n\n   text   \n\n", "text"),
        ("first\n   second", "first\n   second"),  # leading spaces inside the text stay
        ("", ""),
    ],
    ids=repr,
)
def test_normalize_text(text_extraction, raw, expected):
    assert text_extraction.normalize_text(raw) == expected


def test_normalize_text_keeps_every_other_character(text_extraction):
    kept = (
        "Essay 1, “Why Programs Fail,” — due Oct 2 at noon\tsharp · café​"
        " Dec 7–11 page one\x0cpage two   end"
    )
    assert text_extraction.normalize_text(kept) == kept


def test_normalize_text_on_the_fixture(text_extraction, sample_syllabus_text):
    normalized = text_extraction.normalize_text(sample_syllabus_text)
    assert normalized == sample_syllabus_text.strip()  # the fixture is already clean apart from its final newline
    assert text_extraction.normalize_text(normalized) == normalized


def test_normalize_text_is_idempotent_on_messy_text(text_extraction):
    messy = "  Title  \r\n\r\n\r\n\r\nLine\x00 two   \r\n\n\n\nEnd  \n\n"
    once = text_extraction.normalize_text(messy)
    assert once == "Title\n\nLine two\n\nEnd"
    assert text_extraction.normalize_text(once) == once


# ---------------------------------------------------------------------------
# meaningful_length
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", 0),
        ("   \n\t  ", 0),
        ("a b\nc", 3),
        ("Quiz 1 is on\nThursday", 17),
        ("a b　c", 3),
    ],
    ids=repr,
)
def test_meaningful_length_counts_non_whitespace(text_extraction, text, expected):
    assert text_extraction.meaningful_length(text) == expected
