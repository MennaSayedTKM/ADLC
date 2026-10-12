"""
use_case_diagrams.py
A UML use-case diagram for every story in an exported business requirements
document (PDF and Confluence). Generated automatically at export time, with
no review step, and cached so each distinct story is only ever sent to the
model once:

  story content ──▶ model returns structured actors / use cases (advisory)
                ──▶ build_plantuml() writes the diagram text
                ──▶ PlantUML renders it to PNG locally

The cache key is a hash of the story's content plus the system name, not the
item id. A new requirements version copies unchanged stories under new ids
(they reuse the cached spec); an edited story hashes differently, so it is
regenerated.

Best effort throughout: if PlantUML/Java isn't installed nothing is generated
(and no tokens are spent); if the model call fails for a story, a plain
actor → use case diagram is drawn from the story's own "As a… I want…" text.
An export never fails because of a diagram.
"""

import hashlib
import json
import logging
import re
import textwrap
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

from sqlalchemy.orm import Session

from ai.text.use_case_generator import generate_use_case_spec
from config import (
    GPT4O_INPUT_COST_PER_MILLION,
    GPT4O_OUTPUT_COST_PER_MILLION,
    PLANTUML_DPI,
    USE_CASE_CONCURRENCY,
    USE_CASE_MODEL,
)

from ..db.models import AiCall, Document, Project, RequirementItem, UseCaseDiagram
from . import plantuml_renderer
from .business_document import _USER_STORY

logger = logging.getLogger(__name__)

_MAX_SECONDARY_ACTORS = 3
_MAX_RELATED_USE_CASES = 4
_LABEL_MAX_CHARS = 80
_LABEL_WRAP_WIDTH = 26


# ── story -> spec ──────────────────────────────────────────────────────────

def story_payload(story: RequirementItem) -> dict[str, Any]:
    """Exactly what the model sees (and what the cache key is derived from)."""
    return {
        "title": story.text,
        "description": story.description or "",
        "acceptance_criteria": [
            {"text": ac["text"], "out_of_scope": bool(ac.get("out_of_scope"))}
            for ac in story.acceptance_criteria or []
        ],
        "scenarios": [
            {"title": sc.get("title", ""), "given": sc.get("given", ""), "when": sc.get("when", ""), "then": sc.get("then", "")}
            for sc in story.scenarios or []
        ],
        "error_handling": [eh.get("condition", "") for eh in story.error_handling or []],
    }


def content_hash(payload: dict[str, Any], system_name: str) -> str:
    raw = json.dumps({"system": system_name, "story": payload}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _clean_list(values, limit: int, exclude: set[str]) -> list[str]:
    out: list[str] = []
    for v in values or []:
        text = " ".join(str(v).split())
        key = text.lower()
        if text and key not in exclude:
            exclude.add(key)
            out.append(text)
        if len(out) == limit:
            break
    return out


def normalise_spec(spec: dict[str, Any]) -> dict[str, Any]:
    primary = " ".join(str(spec.get("primary_actor", "")).split()) or "User"
    main = " ".join(str(spec.get("main_use_case", "")).split())
    seen = {primary.lower(), main.lower()}
    return {
        "primary_actor": primary,
        "secondary_actors": _clean_list(spec.get("secondary_actors"), _MAX_SECONDARY_ACTORS, {primary.lower()}),
        "main_use_case": main,
        "includes": _clean_list(spec.get("includes"), _MAX_RELATED_USE_CASES, seen),
        "extends": _clean_list(spec.get("extends"), _MAX_RELATED_USE_CASES, seen),
    }


def fallback_spec(story: RequirementItem) -> dict[str, Any]:
    """Plain actor → use case, from the story's own text; no model involved."""
    m = _USER_STORY.match(" ".join((story.description or "").split()))
    if m:
        role = m.group("role").strip()
        capability = re.sub(r"(?i)^(be\s+able\s+to\s+|to\s+)", "", m.group("capability").strip()).rstrip(".")
        return normalise_spec(
            {
                "primary_actor": role[:1].upper() + role[1:],
                "main_use_case": capability[:1].upper() + capability[1:],
            }
        )
    return normalise_spec({"primary_actor": "User", "main_use_case": story.text})


# ── spec -> PlantUML ───────────────────────────────────────────────────────

def _label(text: str) -> str:
    """A string safe inside a PlantUML double-quoted name: no quotes,
    backslashes or control characters (so model output can't inject
    directives), shortened, and wrapped with PlantUML's \\n."""
    cleaned = " ".join(re.sub(r'[\x00-\x1f"\\]', " ", str(text)).split())
    if len(cleaned) > _LABEL_MAX_CHARS:
        cleaned = cleaned[: _LABEL_MAX_CHARS - 1].rstrip() + "…"
    return "\\n".join(textwrap.wrap(cleaned, _LABEL_WRAP_WIDTH)) or "?"


def build_plantuml(spec: dict[str, Any], system_name: str) -> str:
    spec = normalise_spec(spec)
    lines = [
        "@startuml",
        f"skinparam dpi {PLANTUML_DPI}",
        "skinparam shadowing false",
        "skinparam backgroundColor white",
        "skinparam ArrowColor #565e6b",
        "skinparam actor {",
        "  BorderColor #1f2430",
        "  BackgroundColor white",
        "}",
        "skinparam usecase {",
        "  BackgroundColor #eef0ff",
        "  BorderColor #4f46e5",
        "}",
        "skinparam rectangle {",
        "  BorderColor #8a92a0",
        "  BackgroundColor white",
        "}",
        "left to right direction",
        f'actor "{_label(spec["primary_actor"])}" as A0',
    ]
    for i, name in enumerate(spec["secondary_actors"], start=1):
        lines.append(f'actor "{_label(name)}" as A{i}')
    lines.append(f'rectangle "{_label(system_name)}" {{')
    lines.append(f'  usecase "{_label(spec["main_use_case"])}" as UC0')
    related = [("include", t) for t in spec["includes"]] + [("extend", t) for t in spec["extends"]]
    for i, (_, text) in enumerate(related, start=1):
        lines.append(f'  usecase "{_label(text)}" as UC{i}')
    lines.append("}")
    lines.append("A0 --> UC0")
    for i in range(1, len(spec["secondary_actors"]) + 1):
        lines.append(f"UC0 -- A{i}")
    for i, (kind, _) in enumerate(related, start=1):
        # UML: the base use case points at what it includes; an extension
        # points at the use case it extends.
        lines.append(f"UC0 ..> UC{i} : <<include>>" if kind == "include" else f"UC{i} ..> UC0 : <<extend>>")
    lines.append("@enduml")
    return "\n".join(lines) + "\n"


# ── orchestration ──────────────────────────────────────────────────────────

def _estimate_cost(usage) -> float:
    return round(
        (usage.prompt_tokens / 1_000_000) * GPT4O_INPUT_COST_PER_MILLION
        + (usage.completion_tokens / 1_000_000) * GPT4O_OUTPUT_COST_PER_MILLION,
        6,
    )


def ensure_diagrams(
    session: Session,
    document: Document,
    project: Project,
    stories: list[RequirementItem],
    llm_client: Optional[Any],
) -> dict[str, bytes]:
    """{story item id: PNG bytes} for the stories that could be drawn. Empty
    when PlantUML isn't available. With no `llm_client`, stories not already
    cached get the plain fallback diagram."""
    if not stories or not plantuml_renderer.is_available():
        return {}

    system_name = project.name
    payloads = {s.id: story_payload(s) for s in stories}
    hashes = {s.id: content_hash(payloads[s.id], system_name) for s in stories}

    specs: dict[str, dict[str, Any]] = {
        row.content_hash: row.spec
        for row in session.query(UseCaseDiagram).filter(UseCaseDiagram.content_hash.in_(set(hashes.values()))).all()
    }

    to_generate: dict[str, RequirementItem] = {}
    if llm_client is not None:
        for s in stories:
            if hashes[s.id] not in specs:
                to_generate.setdefault(hashes[s.id], s)

    if to_generate:
        def generate(item: RequirementItem):
            return generate_use_case_spec(payloads[item.id], system_name, llm_client, USE_CASE_MODEL)

        with ThreadPoolExecutor(max_workers=max(1, USE_CASE_CONCURRENCY)) as pool:
            futures = {h: pool.submit(generate, item) for h, item in to_generate.items()}
        for h, future in futures.items():
            try:
                raw_spec, usage = future.result()
            except Exception as e:  # one bad story must not sink the export
                logger.warning("Use-case generation failed for a story (%s); using the plain diagram", e)
                continue
            spec = normalise_spec(raw_spec)
            specs[h] = spec
            session.add(UseCaseDiagram(content_hash=h, spec=spec, plantuml=build_plantuml(spec, system_name)))
            session.add(
                AiCall(
                    document_id=document.id,
                    project_id=project.id,
                    call_type="use_case_diagram",
                    model=USE_CASE_MODEL,
                    input_tokens=usage.prompt_tokens,
                    output_tokens=usage.completion_tokens,
                    estimated_cost_usd=_estimate_cost(usage),
                )
            )
        session.flush()

    text_by_story = {
        s.id: build_plantuml(specs.get(hashes[s.id]) or fallback_spec(s), system_name) for s in stories
    }
    pngs = plantuml_renderer.render_png_many(list(text_by_story.values()))
    return {item_id: pngs[text] for item_id, text in text_by_story.items() if text in pngs}
