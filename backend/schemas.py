"""Data shapes shared by the extraction service, the database layer, and the API.

Three stages:
1. ``ModelOutput`` / ``ModelItem``: exactly what Claude returns (this is the structured-output schema).
2. ``CleanItem`` / ``ExtractionResult``: after our own rules in ``services/postprocess.py``.
3. ``*Out`` / ``*Response``: what the API sends to the browser.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from backend.prompts import V1_FIELD_DESCRIPTIONS

ITEM_TYPES: tuple[str, ...] = ("exam", "quiz", "project", "essay", "homework", "reading", "other")
ItemType = Literal["exam", "quiz", "project", "essay", "homework", "reading", "other"]


def _normalize_type(value: object) -> object:
    """Accept "Exam" or " quiz " from the model; anything unknown becomes "other"."""
    if isinstance(value, str):
        cleaned = value.strip().lower()
        return cleaned if cleaned in ITEM_TYPES else "other"
    return value


LenientItemType = Annotated[ItemType, BeforeValidator(_normalize_type)]


# ---------------------------------------------------------------------------
# 1. What Claude returns. Field descriptions are sent to the model as part of the schema, so
#    their text lives with the prompts in backend/prompts.py (V1_FIELD_DESCRIPTIONS).
#    No numeric or length constraints here: the API drops them from the schema and
#    Pydantic would then reject the whole reply. Range checks live in postprocess.py.
# ---------------------------------------------------------------------------
class ModelItem(BaseModel):
    title: str = Field(description=V1_FIELD_DESCRIPTIONS["title"])
    type: LenientItemType = Field(description=V1_FIELD_DESCRIPTIONS["type"])
    due_date: str | None = Field(description=V1_FIELD_DESCRIPTIONS["due_date"])
    date_text: str | None = Field(description=V1_FIELD_DESCRIPTIONS["date_text"])
    weight: float | None = Field(description=V1_FIELD_DESCRIPTIONS["weight"])
    source_text: str = Field(description=V1_FIELD_DESCRIPTIONS["source_text"])
    date_was_ambiguous: bool = Field(description=V1_FIELD_DESCRIPTIONS["date_was_ambiguous"])


class ModelOutput(BaseModel):
    class_name: str | None = Field(description=V1_FIELD_DESCRIPTIONS["class_name"])
    term: str | None = Field(description=V1_FIELD_DESCRIPTIONS["term"])
    items: list[ModelItem]


# ---------------------------------------------------------------------------
# 2. After our rules. This is what gets stored.
# ---------------------------------------------------------------------------
class CleanItem(BaseModel):
    title: str
    type: ItemType
    due_date: str | None  # YYYY-MM-DD, or None when the student must pick the day
    date_text: str | None
    weight: float | None
    source_text: str
    date_was_ambiguous: bool
    source_verified: bool


class ExtractionResult(BaseModel):
    class_name: str | None
    items: list[CleanItem]
    model: str
    prompt_version: str


# ---------------------------------------------------------------------------
# 3. API shapes (snake_case, real booleans, ISO strings).
# ---------------------------------------------------------------------------
class ItemOut(BaseModel):
    id: int
    syllabus_id: int
    title: str
    type: ItemType
    due_date: str | None
    date_text: str | None
    weight: float | None
    source_text: str
    date_was_ambiguous: bool
    source_verified: bool
    status: str
    created_at: str


class SyllabusOut(BaseModel):
    id: int
    class_name: str
    filename: str | None
    created_at: str
    item_count: int
    dated_count: int
    needs_date_count: int
    unverified_count: int


class UploadResponse(BaseModel):
    syllabus: SyllabusOut
    items: list[ItemOut]


class SyllabusResponse(BaseModel):
    syllabus: SyllabusOut


class SyllabusListResponse(BaseModel):
    syllabi: list[SyllabusOut]


class ItemListResponse(BaseModel):
    items: list[ItemOut]


class RenameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    class_name: str
