from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel

from .requirements import DocumentOut, RequirementItemOut

UxPromptMode = Literal["foundation", "new_feature", "edit_existing"]


class StyleBriefIO(BaseModel):
    """
    The PM's visual brief. Every field is optional — blanks fall back to
    defaults at generation time (see ai/text/ux_prompt_generator.py).
    design_tokens_summary is normally written by a Foundation generation, but
    the PM may paste one in (e.g. from a design system built elsewhere).
    """

    reference_brand: Optional[str] = None
    primary_color: Optional[str] = None
    tone: Optional[str] = None
    appearance: Optional[Literal["light", "dark", "both"]] = None
    platform: Optional[Literal["web", "mobile", "both"]] = None
    brand_notes: Optional[str] = None
    design_tokens_summary: Optional[str] = None


class EpicWithStories(BaseModel):
    epic: RequirementItemOut
    stories: list[RequirementItemOut]


class UxPromptSources(BaseModel):
    """What the UI/UX Prompts tab can generate from right now."""

    document: Optional[DocumentOut] = None  # latest APPROVED requirements version; null if none yet
    epics: list[EpicWithStories] = []
    suggested_mode: UxPromptMode = "foundation"
    has_design_system: bool = False  # a design tokens summary is saved for this project
    style_brief: StyleBriefIO = StyleBriefIO()
    soft_char_limit: int


class UxPromptOut(BaseModel):
    id: str
    document_id: str
    epic_item_id: str
    epic_external_id: str
    epic_title: str
    story_ids: list[str]
    story_external_ids: list[str]
    mode: UxPromptMode
    style_brief: Optional[dict] = None
    prompt_text: str
    edited_text: Optional[str] = None
    is_stale: bool
    char_count: int  # of the text the PM would copy (edited_text if present)
    soft_char_limit: int
    created_at: datetime
    updated_at: datetime


class UxPromptEditUpdate(BaseModel):
    # null resets to the generated text
    edited_text: Optional[str] = None
