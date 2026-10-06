from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from .requirements import DocumentOut, RequirementItemOut

UxPromptMode = Literal["foundation", "new_feature", "edit_existing"]


class ReferenceStyleIO(BaseModel):
    """
    One reference website and the style tags read from it (see
    services/style_reference.py). The PM can edit style_tags before saving,
    so it stays a free-form dict.
    """

    url: str
    title: Optional[str] = None
    note: Optional[str] = None  # what to take from this site, e.g. "overall feel", "navigation"
    theme_color: Optional[str] = None
    style_tags: dict[str, Any] = Field(default_factory=dict)
    stylesheets_read: int = 0
    notes: list[str] = Field(default_factory=list)
    fetched_at: Optional[str] = None


class StyleBriefIO(BaseModel):
    """
    The PM-editable part of the project's platform brief. Every field is
    optional and a field left out of a request is left unchanged. The system
    also keeps sitemap / component_names / feature_map on the project's brief,
    but those are written by blueprint generation, never through this model.
    """

    vision: Optional[str] = None
    target_users: Optional[str] = None
    reference_brand: Optional[str] = None
    primary_color: Optional[str] = None
    tone: Optional[str] = None
    appearance: Optional[Literal["light", "dark", "both"]] = None
    platform: Optional[Literal["web", "mobile", "both"]] = None
    brand_notes: Optional[str] = None
    reference_styles: Optional[list[ReferenceStyleIO]] = None
    design_tokens_summary: Optional[str] = None


class StyleExtractRequest(BaseModel):
    url: str


class VisionDraftOut(BaseModel):
    vision: str
    target_users: str


class EpicWithStories(BaseModel):
    epic: RequirementItemOut
    stories: list[RequirementItemOut]


class ScreenIO(BaseModel):
    name: str
    route: str
    purpose: str = ""


class RegistryScreen(ScreenIO):
    owner: str  # "Platform" or the epic's external id


class IntegrationIO(BaseModel):
    with_epic: str
    how: str


class FeatureRelation(BaseModel):
    epic_external_id: str
    depends_on: list[str] = []
    integrates: list[IntegrationIO] = []


class SitemapItem(BaseModel):
    epic_external_id: str
    label: str
    route: str
    status: Literal["placeholder", "designed"] = "placeholder"


class UxPromptSources(BaseModel):
    """What the UI/UX Prompts tab can generate from right now."""

    document: Optional[DocumentOut] = None  # latest APPROVED requirements version; null if none yet
    epics: list[EpicWithStories] = []
    suggested_mode: UxPromptMode = "foundation"
    has_blueprint: bool = False
    blueprint_prompt_id: Optional[str] = None
    # Epics in the approved version that the blueprint has no navigation slot for
    # (added since it was generated) — regenerate the blueprint to add them.
    epics_missing_from_blueprint: list[str] = []
    has_design_system: bool = False  # a design tokens summary is saved for this project
    feature_map: list[FeatureRelation] = []
    suggested_order: list[str] = []  # epic external ids, dependencies first
    sitemap: list[SitemapItem] = []
    registry: list[RegistryScreen] = []
    style_brief: dict[str, Any] = {}
    soft_char_limit: int


class UxPromptOut(BaseModel):
    id: str
    document_id: str
    epic_item_id: Optional[str] = None  # null for the platform blueprint
    epic_external_id: Optional[str] = None
    epic_title: Optional[str] = None
    story_ids: list[str]
    story_external_ids: list[str]
    mode: UxPromptMode
    style_brief: Optional[dict] = None
    screens: list[ScreenIO] = []
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
