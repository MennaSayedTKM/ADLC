"""
business_document.py
Reshapes an approved requirements version into a stakeholder-facing business
requirements document — the default layout for both the PDF export and the
Confluence page. The delivery-team layout (stories, Given/When/Then
scenarios, error messages) is still available as the PDF's "delivery" format.

Built only from what the PM approved: no AI call, nothing added that wasn't
reviewed. The only rewriting is mechanical — a story's "As a [role], I want
[capability], so that [benefit]" description is restated in the third person
("A startup must be able to ...", "The startup can ..."). When a description
doesn't follow that template it's shown verbatim instead of guessed at.

Format-neutral on purpose: pdf_export.py and confluence_export.py each render
the same BusinessDocument, so the two outputs can't drift apart in content.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from ..db.models import Document, Gap, Project, RequirementItem

_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}

_USER_STORY = re.compile(
    r"^\s*as\s+(?P<article>an?|the)?\s*(?P<role>.+?),\s*"
    r"I\s+(?P<verb>want|need|would\s+like|can|should\s+be\s+able)\s+(?P<capability>.+?)"
    r"(?:,?\s+so\s+that\s+(?P<benefit>.+?))?\s*\.?\s*$",
    re.IGNORECASE | re.DOTALL,
)

# First-person -> third-person, applied after the story's subject has been
# substituted. Present-tense verbs agree with "they" exactly as with "I",
# so only am/was/I'm need their own forms.
_PRONOUNS = [
    (re.compile(r"\bI am\b"), "they are"),
    (re.compile(r"\bI'm\b"), "they're"),
    (re.compile(r"\bI was\b"), "they were"),
    (re.compile(r"\bI\b"), "they"),
    (re.compile(r"\bmyself\b"), "themselves"),
    (re.compile(r"\bmine\b"), "theirs"),
    (re.compile(r"\bmy\b"), "their"),
    (re.compile(r"\bMy\b"), "Their"),
    (re.compile(r"\bme\b"), "them"),
]


@dataclass
class BusinessRequirement:
    ref: str  # "BR-1.2" — position in this document
    source_id: str  # "S4" — the story's id in TKMiND, for traceability
    title: str
    stakeholder: Optional[str] = None
    statement: Optional[str] = None  # "A startup must be able to ..."
    business_value: Optional[str] = None  # "The startup can ..."
    description: Optional[str] = None  # verbatim fallback when the template didn't parse
    acceptance_criteria: list[str] = field(default_factory=list)


@dataclass
class CapabilityArea:
    number: int
    title: str
    source_reference: Optional[str]
    requirements: list[BusinessRequirement]


@dataclass
class ScopeExclusion:
    requirement_ref: str
    text: str


@dataclass
class AreaNote:
    area: str
    text: str


@dataclass
class OpenIssue:
    priority: str  # "High" / "Medium" / "Low"
    description: str
    location: str


@dataclass
class VersionEntry:
    version: int
    status: str
    date: str


@dataclass
class BusinessDocument:
    project_name: str
    version: int
    status: str
    approved_on: Optional[str]
    source_filename: str
    generated_on: str
    purpose: str
    areas: list[CapabilityArea]
    out_of_scope: list[ScopeExclusion]
    assumptions: list[AreaNote]
    dependencies: list[AreaNote]
    open_issues: list[OpenIssue]
    version_history: list[VersionEntry]

    @property
    def title(self) -> str:
        return f"{self.project_name} — Business Requirements"

    @property
    def requirement_count(self) -> int:
        return sum(len(a.requirements) for a in self.areas)


def build_business_document(
    project: Project,
    document: Document,
    epics: list[RequirementItem],
    stories: list[RequirementItem],
    gaps: list[Gap],
    version_chain: Optional[list[Document]] = None,
) -> BusinessDocument:
    """`epics`/`stories` must already exclude pending/dismissed AI
    suggestions. `version_chain` is every version up to and including
    `document`, oldest first; defaults to just `document`."""
    stories_by_epic: dict[Optional[str], list[RequirementItem]] = {}
    for s in stories:
        stories_by_epic.setdefault(s.parent_id, []).append(s)

    groups: list[tuple[str, Optional[str], list[RequirementItem], Optional[RequirementItem]]] = [
        (e.text, e.source_reference, stories_by_epic.get(e.id, []), e) for e in epics
    ]
    epic_ids = {e.id for e in epics}
    orphans = [s for s in stories if s.parent_id not in epic_ids]
    if orphans:
        groups.append(("Other requirements", None, orphans, None))

    areas: list[CapabilityArea] = []
    out_of_scope: list[ScopeExclusion] = []
    assumptions: list[AreaNote] = []
    dependencies: list[AreaNote] = []

    for number, (title, source_ref, area_stories, epic) in enumerate(groups, start=1):
        requirements = []
        for n, story in enumerate(area_stories, start=1):
            req = _requirement_from_story(f"BR-{number}.{n}", story)
            for ac in story.acceptance_criteria or []:
                if ac.get("out_of_scope"):
                    out_of_scope.append(ScopeExclusion(req.ref, ac["text"]))
                else:
                    req.acceptance_criteria.append(ac["text"])
            requirements.append(req)
        areas.append(CapabilityArea(number, title, source_ref, requirements))
        if epic is not None:
            assumptions += [AreaNote(title, a) for a in epic.assumptions or []]
            dependencies += [AreaNote(title, d) for d in epic.dependencies or []]

    open_issues = [
        OpenIssue(
            priority=g.severity.title(),
            description=g.description,
            location=g.location or (f"Page {g.page}" if g.page is not None else "—"),
        )
        for g in sorted(
            (g for g in gaps if g.status == "open"), key=lambda g: _SEVERITY_ORDER[g.severity]
        )
    ]

    approved_on = (
        format_date(document.updated_at)
        if document.approval_status == "approved" and document.updated_at
        else None
    )
    chain = version_chain or [document]
    version_history = [
        VersionEntry(
            version=d.version,
            status=d.approval_status.replace("_", " ").title(),
            date=format_date(d.updated_at) if d.updated_at else "—",
        )
        for d in chain
    ]

    doc = BusinessDocument(
        project_name=project.name,
        version=document.version,
        status=document.approval_status.replace("_", " ").title(),
        approved_on=approved_on,
        source_filename=document.source_filename,
        generated_on=format_date(datetime.now(timezone.utc)),
        purpose="",
        areas=areas,
        out_of_scope=out_of_scope,
        assumptions=assumptions,
        dependencies=dependencies,
        open_issues=open_issues,
        version_history=version_history,
    )
    doc.purpose = _purpose(doc)
    return doc


def _purpose(doc: BusinessDocument) -> str:
    approval = f", approved on {doc.approved_on}" if doc.approved_on else ""
    areas = len(doc.areas)
    reqs = doc.requirement_count
    text = (
        f"This document sets out the business requirements for {doc.project_name} "
        f"(version {doc.version}{approval}). It covers {areas} capability "
        f"area{'' if areas == 1 else 's'} and {reqs} business requirement{'' if reqs == 1 else 's'}, "
        "together with the scope boundaries, assumptions and dependencies they rely on"
    )
    if doc.open_issues:
        n = len(doc.open_issues)
        text += f", and {n} open issue{'' if n == 1 else 's'} that need{'s' if n == 1 else ''} stakeholder input"
    return text + ". Detailed acceptance scenarios for the delivery team are maintained separately."


def _requirement_from_story(ref: str, story: RequirementItem) -> BusinessRequirement:
    req = BusinessRequirement(ref=ref, source_id=story.external_id, title=story.text)
    if not story.description:
        return req

    m = _USER_STORY.match(story.description)
    if not m:
        req.description = story.description.strip()
        return req

    article = (m.group("article") or "").lower()
    role = m.group("role").strip()
    verb = " ".join(m.group("verb").lower().split())
    capability = m.group("capability").strip().rstrip(".")
    benefit = (m.group("benefit") or "").strip().rstrip(".")

    subject = f"{article} {role}" if article else role
    definite = f"the {role}" if article else role

    # "I can X" / "I should be able to X" / "I want to X" all describe an
    # ability; "I want/need [something]" describes a thing the role requires.
    if verb == "should be able" and capability.lower().startswith("to "):
        capability = capability[3:]
        verb = "can"
    elif verb != "can" and re.match(r"(?i)^(to\s+|be\s+able\s+to\s+)", capability):
        capability = re.sub(r"(?i)^(be\s+able\s+)?to\s+", "", capability)
        verb = "can"

    req.stakeholder = _capitalize(role)
    if verb == "can":
        req.statement = f"{_capitalize(subject)} must be able to {_third_person(capability)}."
    else:
        req.statement = f"{_capitalize(subject)} requires {_third_person(capability)}."
    if benefit:
        req.business_value = _capitalize(_third_person(benefit, subject=definite)) + "."
    return req


def _third_person(text: str, subject: Optional[str] = None) -> str:
    """Restate first-person story text in the third person. When `subject`
    is given, the first "I" becomes that subject ("the startup") and later
    ones become "they"."""
    if subject:
        text = re.sub(r"\bI am\b", f"{subject} is", text, count=1)
        text = re.sub(r"\bI'm\b", f"{subject} is", text, count=1)
        text = re.sub(r"\bI was\b", f"{subject} was", text, count=1)
        if subject not in text:
            text = re.sub(r"\bI\b", subject, text, count=1)
    for pattern, replacement in _PRONOUNS:
        text = pattern.sub(replacement, text)
    return text


def _capitalize(text: str) -> str:
    return text[:1].upper() + text[1:]


def format_date(dt) -> str:
    # %-d (no leading zero) is Unix-only strftime; substitute the day
    # directly instead so this works on Windows too.
    return dt.strftime(f"%B {dt.day}, %Y")
