"""Shared loader for the summary-bulletin corpus used by the invariant tests."""
import json
from functools import lru_cache
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from app.news.services.summaries.gazetteer import GazetteerSnapshot
from app.news.services.summaries.headers import default_header_dictionary
from app.news.services.summaries.parser import parse_summary
from app.news.services.summaries.window import resolve_window

ROOT = Path("tests/fixtures/summaries")
CORPUS = Path("recon_output/summary_bulletins.jsonl")
CORPUS_SIZE = 221


@lru_cache(maxsize=None)
def lexicon():
    return yaml.safe_load(Path("app/core/llm_knowledge/terminology/summary_location_lexicon.yaml").read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def gazetteer():
    return GazetteerSnapshot.from_dict(json.loads((ROOT / "gazetteer_snapshot.json").read_text(encoding="utf-8")))


def corpus_rows():
    if not CORPUS.exists():
        pytest.skip("recon corpus not present")
    rows = [json.loads(line) for line in CORPUS.open(encoding="utf-8")]
    assert len(rows) == CORPUS_SIZE
    return rows


def parse_row(row, gaz=None, headers=None):
    gaz = gaz or gazetteer()
    headers = headers or _headers()
    window = resolve_window(row["text"], datetime.fromisoformat(row["message_datetime"]))
    return parse_summary(row["text"], gaz, headers, lexicon(), window.anchor_date)


@lru_cache(maxsize=None)
def _headers():
    return default_header_dictionary()
