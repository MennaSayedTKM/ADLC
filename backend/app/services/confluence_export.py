"""
confluence_export.py
Publishes an approved requirements version to Confluence as its own page —
one page per approved version, never overwritten, so a Confluence link
handed to a stakeholder keeps showing exactly what was approved even after
a later version exists. The page is the stakeholder-facing business
requirements document: it renders the same BusinessDocument
(business_document.py) as pdf_export.generate_business_pdf(), emitted as
Confluence storage-format XHTML instead of a reportlab flowable list.

Page hierarchy: one "index" page per project (created once, on first
publish, and reused after — its id/url are cached on Project.
confluence_metadata), with every version page created as its child. When a
version supersedes an already-published one, both pages get a short info
panel linking to the other, so a reader lands on the right one either way.
"""

from typing import Optional

from ..db.models import Document, Project
from .business_document import BusinessDocument, BusinessRequirement
from .confluence_client import ConfluenceClient

_PRIORITY_COLOUR = {"High": "Red", "Medium": "Yellow", "Low": "Grey"}
_STATUS_COLOUR = {"Draft": "Grey", "In Review": "Yellow", "Approved": "Green"}

# Same palette as pdf_export.py's business-document styles, so the
# Confluence page reads as the same document as the PDF export.
_ACCENT_COLOUR = "#4f46e5"  # pdf_export._ACCENT
_LABEL_COLOUR = "#8a92a0"  # pdf_export._FAINT


def _escape(text: str) -> str:
    """Confluence storage format is XHTML — same three characters as any XML body."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _table(headers: list[str], rows: list[list[str]]) -> str:
    """`rows` cells are already-escaped XHTML."""
    head = "".join(f"<th>{_escape(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _muted(text: str) -> str:
    return f'<p><span style="color:{_LABEL_COLOUR};">{_escape(text)}</span></p>'


def _status_macro(text: str, colour: str) -> str:
    return (
        '<ac:structured-macro ac:name="status">'
        f'<ac:parameter ac:name="colour">{colour}</ac:parameter>'
        f'<ac:parameter ac:name="title">{_escape(text)}</ac:parameter>'
        "</ac:structured-macro>"
    )


def _info_panel(html_body: str) -> str:
    return f'<ac:structured-macro ac:name="info"><ac:rich-text-body>{html_body}</ac:rich-text-body></ac:structured-macro>'


def index_page_title(project: Project) -> str:
    return f"{project.name} — Requirements"


def version_page_title(bdoc: BusinessDocument) -> str:
    suffix = f" (Approved {bdoc.approved_on})" if bdoc.approved_on else ""
    return f"{bdoc.title} v{bdoc.version}{suffix}"


def build_index_page_html(project: Project) -> str:
    return (
        f"<p>Approved requirements versions for <strong>{_escape(project.name)}</strong>. "
        "Each version below is its own page and is never edited after publishing — "
        "editing requirements in TKMiND and re-approving produces a new version and a new "
        "page here, linked from its predecessor.</p>"
        '<ac:structured-macro ac:name="children" />'
    )


def build_version_page_html(
    bdoc: BusinessDocument,
    supersedes_url: Optional[str] = None,
    superseded_by_url: Optional[str] = None,
) -> str:
    parts: list[str] = []

    if superseded_by_url:
        parts.append(
            _info_panel(
                f'<p><strong>This version has been superseded.</strong> '
                f'<a href="{superseded_by_url}">View the current approved version</a>.</p>'
            )
        )
    if supersedes_url:
        parts.append(
            _info_panel(f'<p>This version supersedes <a href="{supersedes_url}">the previous approved version</a>.</p>')
        )

    # Document control
    parts.append(
        _table(
            ["Version", "Status", "Approved", "Source material", "Generated"],
            [
                [
                    str(bdoc.version),
                    _status_macro(bdoc.status.upper(), _STATUS_COLOUR.get(bdoc.status, "Grey")),
                    _escape(bdoc.approved_on or "—"),
                    _escape(bdoc.source_filename),
                    _escape(bdoc.generated_on),
                ]
            ],
        )
    )
    parts.append('<ac:structured-macro ac:name="toc"><ac:parameter ac:name="maxLevel">2</ac:parameter></ac:structured-macro>')

    # 1. Overview & scope
    parts.append("<h1>1. Overview and Scope</h1>")
    parts.append("<h2>1.1 Purpose</h2>")
    parts.append(f"<p>{_escape(bdoc.purpose)}</p>")
    parts.append("<h2>1.2 In scope</h2>")
    parts.append(
        _table(
            ["Section", "Capability area", "Requirements"],
            [[f"2.{a.number}", _escape(a.title), str(len(a.requirements))] for a in bdoc.areas],
        )
    )
    parts.append("<h2>1.3 Out of scope</h2>")
    if bdoc.out_of_scope:
        parts.append(
            _table(
                ["Related to", "Excluded from this version"],
                [[x.requirement_ref, _escape(x.text)] for x in bdoc.out_of_scope],
            )
        )
    else:
        parts.append(_muted("No items have been explicitly excluded."))

    # 2. Business requirements
    parts.append("<h1>2. Business Requirements</h1>")
    for area in bdoc.areas:
        heading = f"2.{area.number} {_escape(area.title)}"
        if area.source_reference:
            heading += f' <span style="color:{_LABEL_COLOUR};font-size:0.7em;font-weight:normal;">(source §{_escape(area.source_reference)})</span>'
        parts.append(f'<h2><span style="color:{_ACCENT_COLOUR};">{heading}</span></h2>')
        if not area.requirements:
            parts.append(_muted("No requirements recorded for this area."))
        for req in area.requirements:
            parts.append(_requirement_html(req))

    # 3. Assumptions & dependencies
    parts.append("<h1>3. Assumptions and Dependencies</h1>")
    for label, notes, empty in (
        ("3.1 Assumptions", bdoc.assumptions, "No assumptions were stated."),
        ("3.2 Dependencies", bdoc.dependencies, "No dependencies were stated."),
    ):
        parts.append(f"<h2>{label}</h2>")
        if notes:
            parts.append(
                _table(["Capability area", "Detail"], [[_escape(n.area), _escape(n.text)] for n in notes])
            )
        else:
            parts.append(_muted(empty))

    # 4. Open issues
    parts.append("<h1>4. Open Issues Requiring Stakeholder Input</h1>")
    if bdoc.open_issues:
        parts.append(
            "<p>The points below were not fully defined in the source material. "
            "A stakeholder decision is needed on each before or during delivery.</p>"
        )
        parts.append(
            _table(
                ["#", "Priority", "Issue", "Where it arises"],
                [
                    [
                        f"I-{i}",
                        _status_macro(issue.priority, _PRIORITY_COLOUR[issue.priority]),
                        _escape(issue.description),
                        _escape(issue.location),
                    ]
                    for i, issue in enumerate(bdoc.open_issues, start=1)
                ],
            )
        )
    else:
        parts.append(_muted("There are no open issues for this version."))

    # 5. Version history
    parts.append("<h1>5. Version History</h1>")
    parts.append(
        _table(
            ["Version", "Status", "Date"],
            [[str(v.version), _escape(v.status), _escape(v.date)] for v in bdoc.version_history],
        )
    )

    # 6. Sign-off
    parts.append("<h1>6. Stakeholder Sign-off</h1>")
    parts.append(
        "<p>By signing below, stakeholders confirm that the business requirements in "
        f"version {bdoc.version} of this document are complete and correct.</p>"
    )
    parts.append(_table(["Name", "Role", "Signature", "Date"], [["", "", "", ""] for _ in range(4)]))

    return "\n".join(parts)


def _requirement_html(req: BusinessRequirement) -> str:
    rows = [
        ("Stakeholder", req.stakeholder),
        ("Requirement", req.statement),
        ("Business value", req.business_value),
        ("Description", req.description),
    ]
    body = "".join(
        f'<tr><th style="width:160px;">{label}</th><td>{_escape(value)}</td></tr>'
        for label, value in rows
        if value
    )
    if req.acceptance_criteria:
        items = "".join(f"<li>{_escape(ac)}</li>" for ac in req.acceptance_criteria)
        body += f'<tr><th style="width:160px;">Acceptance criteria</th><td><ul>{items}</ul></td></tr>'
    ref = f' <span style="color:{_LABEL_COLOUR};font-size:0.8em;font-weight:normal;">Ref {_escape(req.source_id)}</span>'
    title = f"<h3>{_escape(req.ref)}&nbsp;&nbsp;{_escape(req.title)}{ref}</h3>"
    return title + (f"<table><tbody>{body}</tbody></table>" if body else "")


def _unused_title(client: ConfluenceClient, title: str) -> str:
    """`title`, or `title (2)`, `title (3)`, … if taken. A published version
    page is never overwritten, so a same-titled page (e.g. the same version
    published from another TKMiND environment) is left alone and the new
    page gets a numbered title instead."""
    candidate, n = title, 1
    while client.find_page_by_title(candidate) is not None:
        n += 1
        candidate = f"{title} ({n})"
    return candidate


def ensure_index_page(session, client: ConfluenceClient, project: Project) -> dict:
    """Finds or creates the project's Confluence index page once and caches
    its id/url on Project.confluence_metadata; every later publish reuses
    the cached page rather than looking it up again. An index page with the
    same title may already exist — e.g. the project was published from
    another TKMiND environment — and is adopted rather than duplicated
    (Confluence rejects duplicate titles): it's only a container listing
    its child version pages, so sharing it is harmless."""
    meta = project.confluence_metadata or {}
    if meta.get("index_page_id"):
        return meta

    title = index_page_title(project)
    page = client.find_page_by_title(title) or client.create_page(title, build_index_page_html(project))
    meta = {"index_page_id": page["id"], "index_page_url": client.page_url(page)}
    project.confluence_metadata = meta
    session.flush()
    return meta


def publish_requirements_version(
    session,
    client: ConfluenceClient,
    project: Project,
    previous_document: Optional[Document],
    bdoc: BusinessDocument,
) -> dict:
    """Publishes `bdoc` as a new child page under the project's index page,
    linking it with `previous_document`'s own Confluence page (if any) in
    both directions. Returns {"page_id", "page_url"}."""
    index_meta = ensure_index_page(session, client, project)

    supersedes_url = None
    previous_page_id = None
    if previous_document is not None:
        previous_meta = (previous_document.type_metadata or {}).get("confluence")
        if previous_meta:
            previous_page_id = previous_meta["page_id"]
            supersedes_url = previous_meta["page_url"]

    body_html = build_version_page_html(bdoc, supersedes_url=supersedes_url)
    page = client.create_page(
        _unused_title(client, version_page_title(bdoc)), body_html, parent_id=index_meta["index_page_id"]
    )
    page_url = client.page_url(page)

    if previous_page_id:
        # The old page keeps its own original body untouched — only prepend
        # a "superseded by" banner, rather than re-deriving its content from
        # `bdoc`, which belongs to the NEW version being published here, not
        # the one being superseded.
        current = client.get_page(previous_page_id)
        old_body = current["body"]["storage"]["value"]
        banner = _info_panel(
            f'<p><strong>This version has been superseded.</strong> '
            f'<a href="{page_url}">View the current approved version</a>.</p>'
        )
        client.update_page(
            previous_page_id,
            current["title"],
            banner + old_body,
            next_version=current["version"]["number"] + 1,
        )

    return {"page_id": page["id"], "page_url": page_url}
