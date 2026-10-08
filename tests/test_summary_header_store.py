"""Admin-learned header mappings are read after the YAML dictionary (scratch DB)."""
from __future__ import annotations

import pytest

from app.news.models.summary_bulletin import SummaryHeaderMapping
from app.news.services.summaries.header_store import header_dictionary_for_session
from app.news.services.summaries.headers import default_header_dictionary
from tests.summary_db import build_world


@pytest.fixture
def world():
    w = build_world()
    yield w
    w.session.rollback()
    w.session.close()


def test_learned_mapping_resolves_an_unknown_header(world):
    assert default_header_dictionary().resolve("عناوين مجهولة")[0] is None
    world.session.add(SummaryHeaderMapping(header_text_normalized="عناوين مجهولة", condition_ids=[world.condition["Bombs"]]))
    world.session.flush()
    entry, _ = header_dictionary_for_session(world.session).resolve("عناوين مجهولة")
    assert entry is not None and entry.status == "approved"
    assert entry.condition_ids == (world.condition["Bombs"],)


def test_approved_yaml_entry_wins_over_a_learned_mapping(world):
    yaml_entry, _ = default_header_dictionary().resolve("قصف مدفعي")
    world.session.add(SummaryHeaderMapping(header_text_normalized="قصف مدفعي", condition_ids=[999]))
    world.session.flush()
    entry, _ = header_dictionary_for_session(world.session).resolve("قصف مدفعي")
    assert entry.condition_ids == yaml_entry.condition_ids != (999,)


def test_missing_table_falls_back_to_yaml(world):
    class Broken:
        def begin_nested(self):
            raise RuntimeError("relation summary_header_mappings does not exist")

    assert header_dictionary_for_session(Broken()).entries == default_header_dictionary().entries
