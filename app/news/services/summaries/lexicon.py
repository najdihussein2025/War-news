"""Shared summary location lexicon (loaded once)."""
from __future__ import annotations

from pathlib import Path

import yaml

LEXICON_PATH = (
    Path(__file__).resolve().parents[3] / "core" / "llm_knowledge" / "terminology" / "summary_location_lexicon.yaml"
)
LEXICON = yaml.safe_load(LEXICON_PATH.read_text(encoding="utf-8"))
