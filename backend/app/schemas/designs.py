from typing import Optional

from pydantic import BaseModel

from .requirements import DocumentOut


class BoundingBox(BaseModel):
    top: float
    left: float
    bottom: float
    right: float


class AlignmentFindingOut(BaseModel):
    id: str
    requirement_item_id: Optional[str] = None
    requirement_external_id: Optional[str] = None
    issue: str
    recommendation: str
    bounding_box: Optional[BoundingBox] = None
    resolution_status: str

    model_config = {"from_attributes": True}


class AlignmentReportOut(BaseModel):
    id: str
    page: int
    status: str
    findings: list[AlignmentFindingOut]

    model_config = {"from_attributes": True}


class DesignDetail(BaseModel):
    document: DocumentOut
    requirements_document_id: Optional[str] = None
    reports: list[AlignmentReportOut]


class DesignIngestResponse(BaseModel):
    document: DocumentOut
    pages_indexed: int
    screens_checked: int
    aligned_count: int
    partial_count: int
    misaligned_count: int


class FindingStatusUpdate(BaseModel):
    status: str  # "resolved" | "dismissed" | "open"
