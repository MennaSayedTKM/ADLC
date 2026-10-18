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

# Embeddings
EMBED_PROVIDER = str(_require("embed_provider")).strip()
BEDROCK_EMBED_MODEL = str(_require("bedrock_embed_model"))
BEDROCK_REGION = str(_require("bedrock_region"))
EMBED_DIMENSION = int(_require("embed_dimension"))

# Answer synthesis
ANSWER_MODEL = str(_require("answer_model"))
CROP_MIN_PX = int(_require("crop_min_px"))

# Requirements extraction (text-based, via Claude)
EXTRACTION_MODEL = str(_require("extraction_model"))
EXTRACTION_MAX_TOKENS = int(_require("extraction_max_tokens"))
EPIC_TARGET_MIN_STORIES = int(_require("epic_target_min_stories"))
EPIC_TARGET_MAX_STORIES = int(_require("epic_target_max_stories"))
EPIC_CONSOLIDATION_MIN_EPICS = int(_require("epic_consolidation_min_epics"))
EXTRACTION_SINGLE_PASS_MAX_TOKENS = int(_require("extraction_single_pass_max_tokens"))
EXTRACTION_PART_MAX_TOKENS = int(_require("extraction_part_max_tokens"))
EXTRACTION_PART_CONCURRENCY = int(_require("extraction_part_concurrency"))
EXTRACTION_SECTION_CATEGORIES = [str(c) for c in _require("extraction_section_categories")]

# Design alignment check
ALIGNMENT_MODEL = str(_require("alignment_model"))
ALIGNMENT_IMAGE_DETAIL = str(_require("alignment_image_detail"))
ALIGNMENT_MAX_TOKENS = int(_require("alignment_max_tokens"))
ALIGNMENT_MAX_STORIES_INLINE = int(_require("alignment_max_stories_inline"))

# Requirements intake — image resources
INTAKE_IMAGE_MODEL = str(_require("intake_image_model"))
INTAKE_IMAGE_DETAIL = str(_require("intake_image_detail"))
INTAKE_IMAGE_MAX_TOKENS = int(_require("intake_image_max_tokens"))

# UI/UX prompt generation
UX_PROMPT_MODEL = str(_require("ux_prompt_model"))
UX_PROMPT_MAX_TOKENS = int(_require("ux_prompt_max_tokens"))
UX_PROMPT_SOFT_CHAR_LIMIT = int(_require("ux_prompt_soft_char_limit"))
UX_SCREENSHOT_MODEL = str(_require("ux_screenshot_model"))
UX_SCREENSHOT_DETAIL = str(_require("ux_screenshot_detail"))
UX_SCREENSHOT_MAX_TOKENS = int(_require("ux_screenshot_max_tokens"))

# Reference-site style extraction
STYLE_FETCH_TIMEOUT_SECONDS = float(_require("style_fetch_timeout_seconds"))
STYLE_FETCH_MAX_BYTES = int(_require("style_fetch_max_bytes"))
STYLE_FETCH_MAX_STYLESHEETS = int(_require("style_fetch_max_stylesheets"))
STYLE_FETCH_MAX_REDIRECTS = int(_require("style_fetch_max_redirects"))
STYLE_FETCH_USER_AGENT = str(_require("style_fetch_user_agent"))


# Use-case diagrams
USE_CASE_MODEL = str(_require("use_case_model"))
USE_CASE_MAX_TOKENS = int(_require("use_case_max_tokens"))
USE_CASE_CONCURRENCY = int(_require("use_case_concurrency"))
PLANTUML_JAR = str(_require("plantuml_jar"))
JAVA_COMMAND = str(_require("java_command"))
PLANTUML_RENDER_TIMEOUT_SECONDS = int(_require("plantuml_render_timeout_seconds"))
PLANTUML_DPI = int(_require("plantuml_dpi"))

# Development stories and coding prompts
DEV_STORY_MODEL = str(_require("dev_story_model"))
DEV_STORY_MAX_TOKENS = int(_require("dev_story_max_tokens"))
TECH_PROFILE_MODEL = str(_require("tech_profile_model"))
TECH_PROFILE_MAX_TOKENS = int(_require("tech_profile_max_tokens"))
TECH_PROFILE_MAX_DOCUMENT_CHARS = int(_require("tech_profile_max_document_chars"))
CODING_PROMPT_MODEL = str(_require("coding_prompt_model"))
CODING_PROMPT_REGION = str(_require("coding_prompt_region"))
CODING_PROMPT_ROLE_ARN = str(_require("coding_prompt_role_arn") or "").strip()
CODING_PROMPT_EFFORT = str(_require("coding_prompt_effort"))
CODING_PROMPT_MAX_TOKENS = int(_require("coding_prompt_max_tokens"))
CODING_PROMPT_TECH_DOCUMENT_CHARS = int(_require("coding_prompt_tech_document_chars"))
CODING_PROMPT_INPUT_COST_PER_MILLION = float(_require("coding_prompt_input_cost_per_million"))
CODING_PROMPT_OUTPUT_COST_PER_MILLION = float(_require("coding_prompt_output_cost_per_million"))

# GPT-4o cost estimation
GPT4O_INPUT_COST_PER_MILLION = float(_require("gpt4o_input_cost_per_million"))
GPT4O_OUTPUT_COST_PER_MILLION = float(_require("gpt4o_output_cost_per_million"))

# Cohere Embed v4 (Bedrock) cost estimation
COHERE_EMBED_TEXT_COST_PER_MILLION = float(_require("cohere_embed_text_cost_per_million"))
COHERE_EMBED_IMAGE_COST_PER_MILLION = float(_require("cohere_embed_image_cost_per_million"))

# Claude cost estimation
CLAUDE_INPUT_COST_PER_MILLION = float(_require("claude_input_cost_per_million"))
CLAUDE_OUTPUT_COST_PER_MILLION = float(_require("claude_output_cost_per_million"))
