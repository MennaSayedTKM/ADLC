"""
pdf_export.py
Renders an approved requirements version to PDF in one of two layouts:

- generate_business_pdf(): the default, stakeholder-facing business
  requirements document (see business_document.py) — scope, numbered
  business requirements, assumptions, open issues, sign-off.
- generate_requirements_pdf(): the delivery-team layout — epics, stories,
  acceptance criteria, Given/When/Then scenarios and error handling.

Generated on demand, not cached at approval time — regenerating each time
means it always reflects the current gap-resolution state rather than a
stale snapshot from the moment of approval.
"""

import io

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    KeepTogether,
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from ..db.models import Document, Gap, Project, RequirementItem
from .business_document import BusinessDocument, format_date

_STYLES = getSampleStyleSheet()
_TITLE = ParagraphStyle("TKMindTitle", parent=_STYLES["Title"], spaceAfter=4)
_META = ParagraphStyle(
    "TKMindMeta", parent=_STYLES["Normal"], textColor=colors.HexColor("#565e6b"), spaceAfter=18
)
_EPIC_HEADING = ParagraphStyle(
    "TKMindEpicHeading",
    parent=_STYLES["Heading2"],
    textColor=colors.HexColor("#4f46e5"),
    spaceBefore=18,
    spaceAfter=8,
)
_STORY_HEADING = ParagraphStyle(
    "TKMindStoryHeading",
    parent=_STYLES["Heading3"],
    spaceBefore=10,
    spaceAfter=4,
    alignment=TA_LEFT,
)
_BODY = ParagraphStyle("TKMindBody", parent=_STYLES["Normal"], spaceAfter=4)
_AC_LABEL = ParagraphStyle(
    "TKMindAcLabel",
    parent=_STYLES["Normal"],
    fontSize=8,
    textColor=colors.HexColor("#8a92a0"),
    spaceBefore=4,
)
_SCENARIO_TITLE = ParagraphStyle(
    "TKMindScenarioTitle",
    parent=_STYLES["Normal"],
    fontName="Helvetica-Bold",
    spaceBefore=6,
)
_SCENARIO_STEP = ParagraphStyle(
    "TKMindScenarioStep",
    parent=_STYLES["Normal"],
    leftIndent=10,
    spaceAfter=1,
)
_SECTION_HEADING = ParagraphStyle(
    "TKMindSectionHeading",
    parent=_STYLES["Heading1"],
    spaceBefore=24,
    spaceAfter=10,
)
_TABLE_CELL = ParagraphStyle(
    "TKMindTableCell",
    parent=_STYLES["Normal"],
    fontSize=9,
    leading=12,
)

_SEVERITY_HEX = {"high": "#b91c1c", "medium": "#b45309", "low": "#565e6b"}
_SEVERITY_COLOR = {k: colors.HexColor(v) for k, v in _SEVERITY_HEX.items()}


def generate_requirements_pdf(
    project: Project,
    document: Document,
    epics: list[RequirementItem],
    stories: list[RequirementItem],
    gaps: list[Gap],
) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=0.9 * inch,
        rightMargin=0.9 * inch,
        topMargin=0.9 * inch,
        bottomMargin=0.9 * inch,
        title=f"{project.name} — Requirements v{document.version}",
    )

    story_flow: list = []
    story_flow.append(Paragraph(f"{project.name}", _TITLE))
    story_flow.append(Paragraph(f"Requirements — version {document.version}", _STYLES["Heading2"]))

    approved_on = _format_date(document.updated_at) if document.updated_at else "—"
    meta_lines = [
        f"Source document: {document.source_filename}",
        f"Status: {document.approval_status.replace('_', ' ').title()}",
        f"Approved: {approved_on}" if document.approval_status == "approved" else "",
        f"Exported: {_now_str()}",
    ]
    story_flow.append(Paragraph("<br/>".join(line for line in meta_lines if line), _META))

    stories_by_epic: dict[str, list[RequirementItem]] = {}
    for s in stories:
        stories_by_epic.setdefault(s.parent_id, []).append(s)

    for epic in epics:
        heading = f"{epic.external_id} — {_escape(epic.text)}"
        if epic.source_reference:
            heading += f" <font size=8 color='#8a92a0'>[{_escape(epic.source_reference)}]</font>"
        story_flow.append(Paragraph(heading, _EPIC_HEADING))
        epic_stories = stories_by_epic.get(epic.id, [])
        if not epic_stories:
            story_flow.append(Paragraph("<i>No stories under this epic.</i>", _BODY))
            continue
        for s in epic_stories:
            story_flow.append(Paragraph(f"{s.external_id}. {_escape(s.text)}", _STORY_HEADING))
            if s.description:
                story_flow.append(Paragraph(_escape(s.description), _BODY))
            if s.acceptance_criteria:
                story_flow.append(Paragraph("ACCEPTANCE CRITERIA", _AC_LABEL))
                story_flow.append(
                    ListFlowable(
                        [
                            ListItem(
                                Paragraph(
                                    _escape(ac["text"]) + (" <i>(Out of Scope)</i>" if ac.get("out_of_scope") else ""),
                                    _BODY,
                                )
                            )
                            for ac in s.acceptance_criteria
                        ],
                        bulletType="bullet",
                        leftIndent=18,
                    )
                )
            if s.scenarios:
                story_flow.append(Paragraph(f"SCENARIOS ({len(s.scenarios)})", _AC_LABEL))
                for sc in s.scenarios:
                    title = _escape(sc["title"])
                    if sc.get("source_reference"):
                        title += f" <font size=8 color='#8a92a0'>[{_escape(sc['source_reference'])}]</font>"
                    story_flow.append(Paragraph(title, _SCENARIO_TITLE))
                    story_flow.append(Paragraph(f"<b>Given</b> {_escape(sc['given'])}", _SCENARIO_STEP))
                    story_flow.append(Paragraph(f"<b>When</b> {_escape(sc['when'])}", _SCENARIO_STEP))
                    story_flow.append(Paragraph(f"<b>Then</b> {_escape(sc['then'])}", _SCENARIO_STEP))
            if s.error_handling:
                story_flow.append(Paragraph(f"ERROR HANDLING ({len(s.error_handling)})", _AC_LABEL))
                story_flow.append(
                    ListFlowable(
                        [
                            ListItem(
                                Paragraph(
                                    f"<b>{_escape(eh['condition'])}</b> → {_escape(eh['message'])}",
                                    _BODY,
                                )
                            )
                            for eh in s.error_handling
                        ],
                        bulletType="bullet",
                        leftIndent=18,
                    )
                )

    open_gaps = [g for g in gaps if g.status == "open"]
    if open_gaps:
        story_flow.append(Paragraph("Open Gaps at Export Time", _SECTION_HEADING))
        story_flow.append(
            Paragraph(
                "These were flagged during extraction and had not been resolved or dismissed "
                "when this PDF was generated.",
                _META,
            )
        )
        rows = [["Severity", "Location", "Description"]]
        for g in sorted(open_gaps, key=lambda g: {"high": 0, "medium": 1, "low": 2}[g.severity]):
            location = g.location or (f"p.{g.page}" if g.page is not None else "—")
            rows.append(
                [
                    g.severity.title(),
                    Paragraph(_escape(location), _TABLE_CELL),
                    Paragraph(_escape(g.description), _TABLE_CELL),
                ]
            )
        table = Table(rows, colWidths=[0.9 * inch, 1.1 * inch, 3.9 * inch])
        table.setStyle(
            TableStyle(
                [
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#d0d5dd")),
                    ("LINEBELOW", (0, 1), (-1, -1), 0.5, colors.HexColor("#e4e7ec")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
                + [
                    ("TEXTCOLOR", (0, i), (0, i), _SEVERITY_COLOR[open_gaps[i - 1].severity])
                    for i in range(1, len(rows))
                ]
            )
        )
        story_flow.append(table)

    story_flow.append(Spacer(1, 0.3 * inch))
    doc.build(story_flow)
    return buf.getvalue()


_INK = colors.HexColor("#1f2430")
_MUTED = colors.HexColor("#565e6b")
_FAINT = colors.HexColor("#8a92a0")
_RULE = colors.HexColor("#d0d5dd")
_HAIRLINE = colors.HexColor("#e4e7ec")
_TINT = colors.HexColor("#f4f5f8")
_ACCENT = colors.HexColor("#4f46e5")

_BRD_TITLE = ParagraphStyle("BrdTitle", parent=_STYLES["Title"], alignment=TA_LEFT, spaceAfter=2)
_BRD_SUBTITLE = ParagraphStyle(
    "BrdSubtitle", parent=_STYLES["Normal"], fontSize=13, leading=16, textColor=_MUTED, spaceAfter=18
)
# keepWithNext so a heading never sits alone at the bottom of a page.
_BRD_H1 = ParagraphStyle(
    "BrdH1",
    parent=_STYLES["Heading1"],
    fontSize=15,
    leading=19,
    textColor=_INK,
    spaceBefore=20,
    spaceAfter=8,
    keepWithNext=1,
)
_BRD_H2 = ParagraphStyle(
    "BrdH2",
    parent=_STYLES["Heading2"],
    fontSize=12,
    leading=15,
    textColor=_ACCENT,
    spaceBefore=14,
    spaceAfter=6,
    keepWithNext=1,
)
_BRD_BODY = ParagraphStyle("BrdBody", parent=_STYLES["Normal"], fontSize=10, leading=14, spaceAfter=6)
_BRD_CELL = ParagraphStyle("BrdCell", parent=_STYLES["Normal"], fontSize=9, leading=12.5)
_BRD_CELL_LABEL = ParagraphStyle("BrdCellLabel", parent=_BRD_CELL, textColor=_MUTED)
_BRD_CELL_HEAD = ParagraphStyle("BrdCellHead", parent=_BRD_CELL, fontName="Helvetica-Bold")
_BRD_REQ_TITLE = ParagraphStyle(
    "BrdReqTitle", parent=_STYLES["Normal"], fontName="Helvetica-Bold", fontSize=10, leading=13
)
_BRD_REQ_REF = ParagraphStyle(
    "BrdReqRef", parent=_STYLES["Normal"], fontSize=8, leading=13, textColor=_FAINT, alignment=TA_RIGHT
)
_BRD_NOTE = ParagraphStyle("BrdNote", parent=_BRD_BODY, textColor=_MUTED, fontSize=9, leading=12.5)

# Usable frame width: page minus 0.9" margins minus the frame's own 6pt padding each side.
_PAGE_WIDTH = letter[0] - 1.8 * inch - 12


def generate_business_pdf(bdoc: BusinessDocument) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=0.9 * inch,
        rightMargin=0.9 * inch,
        topMargin=0.9 * inch,
        bottomMargin=0.9 * inch,
        title=f"{bdoc.title} v{bdoc.version}",
    )

    def footer(canvas, _doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(_FAINT)
        canvas.drawString(0.9 * inch, 0.55 * inch, f"{bdoc.title} · Version {bdoc.version}")
        canvas.drawRightString(letter[0] - 0.9 * inch, 0.55 * inch, f"Page {canvas.getPageNumber()}")
        canvas.restoreState()

    flow: list = [
        Paragraph(_escape(bdoc.project_name), _BRD_TITLE),
        Paragraph("Business Requirements Document", _BRD_SUBTITLE),
        _key_value_table(
            [
                ("Version", str(bdoc.version)),
                ("Status", bdoc.status),
                ("Approved", bdoc.approved_on or "—"),
                ("Source material", bdoc.source_filename),
                ("Generated", bdoc.generated_on),
            ]
        ),
    ]

    # 1. Overview & scope
    flow.append(Paragraph("1. Overview and Scope", _BRD_H1))
    flow.append(Paragraph("1.1 Purpose", _BRD_H2))
    flow.append(Paragraph(_escape(bdoc.purpose), _BRD_BODY))
    flow.append(Paragraph("1.2 In scope", _BRD_H2))
    flow.append(
        _grid(
            ["Section", "Capability area", "Requirements"],
            [
                [f"2.{a.number}", _escape(a.title), str(len(a.requirements))]
                for a in bdoc.areas
            ],
            [0.8 * inch, _PAGE_WIDTH - 1.9 * inch, 1.1 * inch],
        )
    )
    flow.append(Paragraph("1.3 Out of scope", _BRD_H2))
    if bdoc.out_of_scope:
        flow.append(
            _grid(
                ["Related to", "Excluded from this version"],
                [[x.requirement_ref, _escape(x.text)] for x in bdoc.out_of_scope],
                [1.0 * inch, _PAGE_WIDTH - 1.0 * inch],
            )
        )
    else:
        flow.append(Paragraph("No items have been explicitly excluded.", _BRD_NOTE))

    # 2. Business requirements. Headings ride inside the first requirement's
    # KeepTogether — reportlab's keepWithNext won't bind to a KeepTogether,
    # so this is what stops a heading being stranded at the foot of a page.
    lead: list = [Paragraph("2. Business Requirements", _BRD_H1)]
    for area in bdoc.areas:
        heading = f"2.{area.number} {_escape(area.title)}"
        if area.source_reference:
            heading += f" <font size=8 color='#8a92a0'>(source §{_escape(area.source_reference)})</font>"
        lead.append(Paragraph(heading, _BRD_H2))
        if not area.requirements:
            flow.extend(lead + [Paragraph("No requirements recorded for this area.", _BRD_NOTE)])
            lead = []
        for req in area.requirements:
            flow.append(KeepTogether(lead + [_requirement_block(req), Spacer(1, 8)]))
            lead = []
    flow.extend(lead)

    # 3. Assumptions & dependencies
    flow.append(Paragraph("3. Assumptions and Dependencies", _BRD_H1))
    for label, notes, empty in (
        ("3.1 Assumptions", bdoc.assumptions, "No assumptions were stated."),
        ("3.2 Dependencies", bdoc.dependencies, "No dependencies were stated."),
    ):
        flow.append(Paragraph(label, _BRD_H2))
        if notes:
            flow.append(
                _grid(
                    ["Capability area", "Detail"],
                    [[_escape(n.area), _escape(n.text)] for n in notes],
                    [1.9 * inch, _PAGE_WIDTH - 1.9 * inch],
                )
            )
        else:
            flow.append(Paragraph(empty, _BRD_NOTE))

    # 4. Open issues
    flow.append(Paragraph("4. Open Issues Requiring Stakeholder Input", _BRD_H1))
    if bdoc.open_issues:
        flow.append(
            Paragraph(
                "The points below were not fully defined in the source material. "
                "A stakeholder decision is needed on each before or during delivery.",
                _BRD_BODY,
            )
        )
        rows = [
            [
                f"I-{i}",
                f"<font color='{_SEVERITY_HEX[issue.priority.lower()]}'><b>{issue.priority}</b></font>",
                _escape(issue.description),
                _escape(issue.location),
            ]
            for i, issue in enumerate(bdoc.open_issues, start=1)
        ]
        flow.append(
            _grid(
                ["#", "Priority", "Issue", "Where it arises"],
                rows,
                [0.45 * inch, 0.75 * inch, _PAGE_WIDTH - 2.7 * inch, 1.5 * inch],
            )
        )
    else:
        flow.append(Paragraph("There are no open issues for this version.", _BRD_NOTE))

    # 5. Version history
    flow.append(Paragraph("5. Version History", _BRD_H1))
    flow.append(
        _grid(
            ["Version", "Status", "Date"],
            [[str(v.version), v.status, v.date] for v in bdoc.version_history],
            [1.0 * inch, 1.6 * inch, _PAGE_WIDTH - 2.6 * inch],
        )
    )

    # 6. Sign-off
    flow.append(
        KeepTogether(
            [
                Paragraph("6. Stakeholder Sign-off", _BRD_H1),
                Paragraph(
                    "By signing below, stakeholders confirm that the business requirements "
                    f"in version {bdoc.version} of this document are complete and correct.",
                    _BRD_BODY,
                ),
                _grid(
                    ["Name", "Role", "Signature", "Date"],
                    [["", "", "", ""] for _ in range(4)],
                    [1.7 * inch, 1.5 * inch, _PAGE_WIDTH - 4.3 * inch, 1.1 * inch],
                    row_height=0.42 * inch,
                ),
            ]
        )
    )

    doc.build(flow, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


def _requirement_block(req) -> Table:
    """One boxed block per requirement: a tinted [title | Ref S4] header,
    then [label | value] rows. reportlab tables share one set of column
    widths, so the header is a nested table spanning both columns."""
    header = Table(
        [
            [
                Paragraph(f"{req.ref}&nbsp;&nbsp;{_escape(req.title)}", _BRD_REQ_TITLE),
                Paragraph(f"Ref {req.source_id}", _BRD_REQ_REF),
            ]
        ],
        colWidths=[_PAGE_WIDTH - 0.9 * inch - 14, 0.9 * inch],
    )
    header.setStyle(
        TableStyle(
            [
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )

    body: list[list] = [[header, ""]]
    details = [
        ("Stakeholder", req.stakeholder),
        ("Requirement", req.statement),
        ("Business value", req.business_value),
        ("Description", req.description),
    ]
    for label, value in details:
        if value:
            body.append([Paragraph(label, _BRD_CELL_LABEL), Paragraph(_escape(value), _BRD_CELL)])
    if req.acceptance_criteria:
        body.append(
            [
                Paragraph("Acceptance criteria", _BRD_CELL_LABEL),
                ListFlowable(
                    [ListItem(Paragraph(_escape(ac), _BRD_CELL)) for ac in req.acceptance_criteria],
                    bulletType="bullet",
                    leftIndent=10,
                    bulletFontSize=7,
                ),
            ]
        )

    block = Table(body, colWidths=[1.3 * inch, _PAGE_WIDTH - 1.3 * inch])
    block.setStyle(
        TableStyle(
            [
                ("SPAN", (0, 0), (1, 0)),
                ("BACKGROUND", (0, 0), (-1, 0), _TINT),
                ("BOX", (0, 0), (-1, -1), 0.6, _RULE),
                ("LINEBELOW", (0, 0), (-1, 0), 0.6, _RULE),
                ("LINEBELOW", (0, 1), (-1, -2), 0.4, _HAIRLINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return block


def _key_value_table(pairs: list[tuple[str, str]]) -> Table:
    table = Table(
        [[Paragraph(k, _BRD_CELL_LABEL), Paragraph(_escape(v), _BRD_CELL)] for k, v in pairs],
        colWidths=[1.4 * inch, _PAGE_WIDTH - 1.4 * inch],
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("LINEABOVE", (0, 0), (-1, 0), 0.6, _RULE),
                ("LINEBELOW", (0, -1), (-1, -1), 0.6, _RULE),
                ("LINEBELOW", (0, 0), (-1, -2), 0.4, _HAIRLINE),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return table


def _grid(headers: list[str], rows: list[list[str]], col_widths: list[float], row_height=None) -> Table:
    data = [[Paragraph(h, _BRD_CELL_HEAD) for h in headers]] + [
        [Paragraph(cell, _BRD_CELL) for cell in row] for row in rows
    ]
    table = Table(
        data,
        colWidths=col_widths,
        rowHeights=[None] + [row_height] * len(rows) if row_height else None,
        repeatRows=1,
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _TINT),
                ("LINEBELOW", (0, 0), (-1, 0), 0.8, _RULE),
                ("LINEBELOW", (0, 1), (-1, -1), 0.4, _HAIRLINE),
                ("BOX", (0, 0), (-1, -1), 0.6, _RULE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def _now_str() -> str:
    from datetime import datetime, timezone

    return _format_date(datetime.now(timezone.utc))


_format_date = format_date


def _escape(text: str) -> str:
    """reportlab Paragraph markup treats <, >, & as tags/entities."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
