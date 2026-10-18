"""
jira_adf.py
Markdown -> Atlassian Document Format (ADF), the rich-text format Jira's REST
API v3 takes for descriptions. Covers the Markdown our own text uses — coding
prompts, development story descriptions — not all of CommonMark: headings,
paragraphs, bullet and numbered lists (nested by indentation), `- [ ]`
checklists, fenced code blocks, pipe tables, block quotes, rules, and inline
bold / italic / code / links. Anything else comes through as plain text, so
nothing is lost.

Checklist items become "☐ text" list items rather than Jira action items:
action items are tied to the person viewing, and these are a developer's own
steps.
"""

import re
from typing import Any

Node = dict[str, Any]

_FENCE = re.compile(r"^\s*```\s*([\w+#.-]*)\s*$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_RULE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
_LIST_ITEM = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
_TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_QUOTE = re.compile(r"^\s*>\s?(.*)$")
_CHECKBOX = re.compile(r"^\[([ xX])\]\s+")
_INLINE = re.compile(
    r"`(?P<code>[^`]+)`"
    r"|\*\*(?P<bold>.+?)\*\*"
    r"|__(?P<bold2>.+?)__"
    r"|(?<![\w*])\*(?!\s)(?P<em>.+?)(?<!\s)\*(?![\w*])"
    r"|(?<!\w)_(?!\s)(?P<em2>.+?)(?<!\s)_(?!\w)"
    r"|\[(?P<label>[^\]]+)\]\((?P<href>https?://[^)\s]+)\)"
)


def markdown_to_adf(markdown: str) -> Node:
    return {"version": 1, "type": "doc", "content": _blocks(markdown.replace("\r\n", "\n").split("\n"))}


def _blocks(lines: list[str]) -> list[Node]:
    out: list[Node] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue

        fence = _FENCE.match(line)
        if fence:
            body: list[str] = []
            i += 1
            while i < len(lines) and not _FENCE.match(lines[i]):
                body.append(lines[i])
                i += 1
            i += 1  # the closing fence (or past the end)
            code: Node = {"type": "codeBlock", "content": [{"type": "text", "text": "\n".join(body)}] if any(body) else []}
            if fence.group(1):
                code["attrs"] = {"language": fence.group(1)}
            out.append(code)
            continue

        heading = _HEADING.match(line)
        if heading:
            out.append({"type": "heading", "attrs": {"level": len(heading.group(1))}, "content": _inline(heading.group(2))})
            i += 1
            continue

        if _RULE.match(line):
            out.append({"type": "rule"})
            i += 1
            continue

        if line.lstrip().startswith("|") and i + 1 < len(lines) and _TABLE_SEPARATOR.match(lines[i + 1]):
            rows = [line]
            i += 2
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                rows.append(lines[i])
                i += 1
            out.append(_table(rows))
            continue

        if _QUOTE.match(line):
            quoted: list[str] = []
            while i < len(lines) and _QUOTE.match(lines[i]):
                quoted.append(_QUOTE.match(lines[i]).group(1))
                i += 1
            inner = [b for b in _blocks(quoted) if b["type"] in ("paragraph", "bulletList", "orderedList", "codeBlock")]
            out.append({"type": "blockquote", "content": inner or [_paragraph("")]})
            continue

        if _LIST_ITEM.match(line):
            items: list[tuple[int, bool, int, str]] = []
            while i < len(lines):
                item = _LIST_ITEM.match(lines[i])
                if item:
                    marker = item.group(2)
                    ordered = marker[0].isdigit()
                    items.append((len(item.group(1).expandtabs(4)), ordered, int(marker[:-1]) if ordered else 1, item.group(3)))
                    i += 1
                elif lines[i].strip() and lines[i].startswith((" ", "\t")) and items:
                    indent, ordered, number, text = items[-1]  # a wrapped continuation line
                    items[-1] = (indent, ordered, number, f"{text} {lines[i].strip()}")
                    i += 1
                elif not lines[i].strip() and i + 1 < len(lines) and _LIST_ITEM.match(lines[i + 1]):
                    i += 1  # a blank line between items of the same list
                else:
                    break
            j = 0
            while j < len(items):
                node, j = _list(items, j)
                out.append(node)
            continue

        paragraph = [line.strip()]
        i += 1
        while i < len(lines) and lines[i].strip() and not _starts_block(lines, i):
            paragraph.append(lines[i].strip())
            i += 1
        out.append(_paragraph(" ".join(paragraph)))
    return out


def _starts_block(lines: list[str], i: int) -> bool:
    line = lines[i]
    return bool(
        _FENCE.match(line)
        or _HEADING.match(line)
        or _RULE.match(line)
        or _QUOTE.match(line)
        or _LIST_ITEM.match(line)
        or (line.lstrip().startswith("|") and i + 1 < len(lines) and _TABLE_SEPARATOR.match(lines[i + 1]))
    )


def _list(items: list[tuple[int, bool, int, str]], i: int) -> tuple[Node, int]:
    """One list starting at items[i]; deeper-indented items nest under the item before them."""
    base_indent, ordered, number, _ = items[i]
    node: Node = {"type": "orderedList" if ordered else "bulletList", "content": []}
    if ordered:
        node["attrs"] = {"order": number}
    while i < len(items):
        indent, item_ordered, _, text = items[i]
        if indent < base_indent:
            break
        if indent > base_indent:
            nested, i = _list(items, i)
            if node["content"]:
                node["content"][-1]["content"].append(nested)
            else:
                node["content"].append({"type": "listItem", "content": [_paragraph(""), nested]})
            continue
        if item_ordered != ordered:
            break
        node["content"].append({"type": "listItem", "content": [_paragraph(_checkbox(text))]})
        i += 1
    return node, i


def _checkbox(text: str) -> str:
    box = _CHECKBOX.match(text)
    if not box:
        return text
    return ("☑ " if box.group(1).lower() == "x" else "☐ ") + text[box.end():]


def _table(rows: list[str]) -> Node:
    def cells(row: str) -> list[str]:
        row = row.strip()
        if row.startswith("|"):
            row = row[1:]
        if row.endswith("|"):
            row = row[:-1]
        return [c.strip() for c in row.split("|")]

    header, *body = [cells(r) for r in rows]
    width = len(header)

    def row_node(values: list[str], cell_type: str) -> Node:
        values = (values + [""] * width)[:width]
        return {"type": "tableRow", "content": [{"type": cell_type, "content": [_paragraph(v)]} for v in values]}

    return {
        "type": "table",
        "attrs": {"isNumberColumnEnabled": False, "layout": "default"},
        "content": [row_node(header, "tableHeader")] + [row_node(r, "tableCell") for r in body],
    }


def _paragraph(text: str) -> Node:
    content = _inline(text)
    return {"type": "paragraph", "content": content} if content else {"type": "paragraph"}


def _inline(text: str, marks: tuple[Node, ...] = ()) -> list[Node]:
    """Text nodes with marks. A code mark only combines with a link in ADF, so
    code inside bold or italic keeps just the code mark."""
    nodes: list[Node] = []
    pos = 0
    for m in _INLINE.finditer(text):
        if m.start() > pos:
            nodes.append(_text(text[pos:m.start()], marks))
        if m.group("code") is not None:
            link = tuple(mark for mark in marks if mark["type"] == "link")
            nodes.append(_text(m.group("code"), link + ({"type": "code"},)))
        elif m.group("bold") is not None or m.group("bold2") is not None:
            nodes.extend(_inline(m.group("bold") or m.group("bold2"), marks + ({"type": "strong"},)))
        elif m.group("em") is not None or m.group("em2") is not None:
            nodes.extend(_inline(m.group("em") or m.group("em2"), marks + ({"type": "em"},)))
        else:
            nodes.extend(_inline(m.group("label"), marks + ({"type": "link", "attrs": {"href": m.group("href")}},)))
        pos = m.end()
    if pos < len(text):
        nodes.append(_text(text[pos:], marks))
    return [n for n in nodes if n["text"]]


def _text(text: str, marks: tuple[Node, ...]) -> Node:
    node: Node = {"type": "text", "text": text}
    if marks:
        node["marks"] = list(marks)
    return node


def adf_text_length(doc: Node) -> int:
    """Characters of text in a document — what Jira's description limit counts."""
    if doc.get("type") == "text":
        return len(doc.get("text", ""))
    return sum(adf_text_length(child) for child in doc.get("content", []))
