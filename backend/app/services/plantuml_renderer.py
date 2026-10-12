"""
plantuml_renderer.py
Renders PlantUML text to PNG by running PlantUML locally (`java -jar
plantuml.jar`) — never an outside rendering service, so story content stays
inside our infrastructure.

Optional by design: when Java or the jar isn't installed, is_available() is
False and callers simply leave diagrams out. Output is cached on disk by the
hash of the PlantUML text, so re-exporting an unchanged document renders
nothing.
"""

import hashlib
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from config import JAVA_COMMAND, PLANTUML_DPI, PLANTUML_JAR, PLANTUML_RENDER_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DATA_DIR = Path(os.environ["TKMIND_DATA_DIR"]) if "TKMIND_DATA_DIR" in os.environ else _REPO_ROOT / "data"


def text_hash(plantuml: str) -> str:
    return hashlib.sha256(f"{PLANTUML_DPI}\n{plantuml}".encode("utf-8")).hexdigest()


def _jar_path() -> Optional[Path]:
    # PLANTUML_JAR in the environment wins; set but blank disables rendering
    # (the test suite does this so it never depends on a local Java install).
    configured = os.environ["PLANTUML_JAR"] if "PLANTUML_JAR" in os.environ else PLANTUML_JAR
    if not configured.strip():
        return None
    path = Path(configured)
    return path if path.is_absolute() else _REPO_ROOT / path


def is_available() -> bool:
    jar = _jar_path()
    return jar is not None and jar.is_file() and shutil.which(JAVA_COMMAND) is not None


def _cache_dir() -> Path:
    d = _DATA_DIR / "diagrams"
    d.mkdir(parents=True, exist_ok=True)
    return d


def render_png_many(plantuml_texts: list[str]) -> dict[str, bytes]:
    """{plantuml text: PNG bytes} for every text that rendered. One PlantUML
    process for all uncached texts (JVM start-up dominates a single render).
    A text that fails to render is simply absent from the result."""
    if not plantuml_texts or not is_available():
        return {}

    cache = _cache_dir()
    out: dict[str, bytes] = {}
    pending: dict[str, str] = {}  # hash -> text
    for text in dict.fromkeys(plantuml_texts):
        h = text_hash(text)
        cached = cache / f"{h}.png"
        if cached.is_file():
            out[text] = cached.read_bytes()
        else:
            pending[h] = text
    if not pending:
        return out

    with tempfile.TemporaryDirectory(prefix="plantuml_") as tmp:
        tmp_dir = Path(tmp)
        for h, text in pending.items():
            (tmp_dir / f"{h}.puml").write_text(text, encoding="utf-8")
        cmd = [
            JAVA_COMMAND,
            "-Djava.awt.headless=true",
            "-jar",
            str(_jar_path()),
            "-tpng",
            "-charset",
            "UTF-8",
            "-nometadata",
            *[str(tmp_dir / f"{h}.puml") for h in pending],
        ]
        # SANDBOX: diagram text can't read local files via !include etc.
        env = {**os.environ, "PLANTUML_SECURITY_PROFILE": "SANDBOX"}
        try:
            result = subprocess.run(
                cmd, capture_output=True, timeout=PLANTUML_RENDER_TIMEOUT_SECONDS, env=env, check=False
            )
            if result.returncode != 0:
                logger.warning("PlantUML exited %s: %s", result.returncode, result.stderr[-500:])
        except (subprocess.TimeoutExpired, OSError) as e:
            logger.warning("PlantUML render failed: %s", e)
            return out

        for h, text in pending.items():
            png = tmp_dir / f"{h}.png"
            if png.is_file() and png.stat().st_size > 0:
                data = png.read_bytes()
                (cache / f"{h}.png").write_bytes(data)
                out[text] = data
            else:
                logger.warning("PlantUML produced no image for diagram %s", h[:12])
    return out
