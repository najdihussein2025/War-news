from pathlib import Path


def test_summary_intake_stays_strict_and_never_imports_legacy_matcher():
    source = Path("app/news/services/summaries/intake_service.py").read_text(encoding="utf-8").lower()
    forbidden = ("matching_service", "_collapse_fuzzy_area_locations", "_collapse_plain_between_targets", "similarity", "trigram")
    assert not any(term in source for term in forbidden)


def test_tier1_worker_routes_summaries_before_extraction():
    source = Path("app/news/services/pipeline/pipeline_llm_workers.py").read_text(encoding="utf-8")
    assert "route_summary" in source
    assert source.index("route_summary") < source.index("classifier.extract_tier1")
    assert "NotImplementedError" not in source
