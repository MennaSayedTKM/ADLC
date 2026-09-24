"""
config.py
Loads config.yaml once and exposes settings as a simple namespace.
All other modules import from here instead of hardcoding values.
"""

from pathlib import Path
import yaml

_CONFIG_PATH = Path(__file__).parent / "config.yaml"

with open(_CONFIG_PATH) as f:
    _cfg = yaml.safe_load(f)


def _require(key: str):
    if key not in _cfg:
        raise KeyError(f"Missing required key '{key}' in config.yaml")
    return _cfg[key]


# Storage
DB_PATH = str(_require("db_path"))

# Reranker
RERANKER = str(_require("reranker")).strip()

# Retrieval
TOP_K = int(_require("top_k"))
MMR_LAMBDA = float(_require("mmr_lambda"))
RERANK_TOP_N = int(_require("rerank_top_n"))

# Ingestion
PDF_DPI = int(_require("pdf_dpi"))
MAX_TILE_PX = int(_require("max_tile_px"))

# Answer synthesis
ANSWER_MODEL = str(_require("answer_model"))
CROP_MIN_PX = int(_require("crop_min_px"))

# Requirements extraction (text-based, via Claude)
EXTRACTION_MODEL = str(_require("extraction_model"))
EXTRACTION_MAX_TOKENS = int(_require("extraction_max_tokens"))

# Design alignment check
ALIGNMENT_MODEL = str(_require("alignment_model"))
ALIGNMENT_IMAGE_DETAIL = str(_require("alignment_image_detail"))
ALIGNMENT_MAX_TOKENS = int(_require("alignment_max_tokens"))
ALIGNMENT_MAX_STORIES_INLINE = int(_require("alignment_max_stories_inline"))

# Requirements intake — image resources
INTAKE_IMAGE_MODEL = str(_require("intake_image_model"))
INTAKE_IMAGE_DETAIL = str(_require("intake_image_detail"))
INTAKE_IMAGE_MAX_TOKENS = int(_require("intake_image_max_tokens"))

# GPT-4o cost estimation
GPT4O_INPUT_COST_PER_MILLION = float(_require("gpt4o_input_cost_per_million"))
GPT4O_OUTPUT_COST_PER_MILLION = float(_require("gpt4o_output_cost_per_million"))

# Claude cost estimation
CLAUDE_INPUT_COST_PER_MILLION = float(_require("claude_input_cost_per_million"))
CLAUDE_OUTPUT_COST_PER_MILLION = float(_require("claude_output_cost_per_million"))
