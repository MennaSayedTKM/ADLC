"""
common.py
Shared pieces for the text-based extraction modules — a vendor-neutral usage
shape so the rest of the pipeline (cost logging in particular) doesn't need
to know whether a given call went to Claude or (elsewhere, unchanged) GPT-4o.
"""

from dataclasses import dataclass


@dataclass
class Usage:
    prompt_tokens: int
    completion_tokens: int
