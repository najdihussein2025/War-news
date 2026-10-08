from pathlib import Path


def test_summary_intake_stays_strict_and_never_imports_legacy_matcher():
    source = Path("app/news/services/summaries/intake_service.py").read_text(encoding="utf-8").lower()
    forbidden = ("matching_service", "_collapse_fuzzy_area_locations", "_collapse_plain_between_targets", "similarity", "trigram")
    assert not any(term in source for term in forbidden)


def test_live_mode_is_explicitly_guarded_before_tier1():
    source = Path("app/news/services/pipeline/pipeline_llm_workers.py").read_text(encoding="utf-8")
    assert "SUMMARY_FLOW_MODE=live is not available" in source
    assert "intake_summary" in source
