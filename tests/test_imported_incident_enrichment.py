from __future__ import annotations

from types import SimpleNamespace

from app.news.services import imported_incident_enrichment as enrichment


class _SessionContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


def test_enrich_imported_incidents_runs_each_pipeline_step(monkeypatch) -> None:
    calls: list[tuple[str, int]] = []

    monkeypatch.setattr(
        enrichment,
        "run_tier1_extraction_for_message",
        lambda raw_id: calls.append(("extract", raw_id)),
    )
    monkeypatch.setattr(enrichment, "SessionLocal", _SessionContext)
    monkeypatch.setattr(
        enrichment,
        "build_match_incident_action",
        lambda _db: SimpleNamespace(
            execute=lambda raw_id: calls.append(("match", raw_id))
        ),
    )
    monkeypatch.setattr(
        enrichment,
        "run_tier2_detail_fill_for_message",
        lambda raw_id: calls.append(("details", raw_id)),
    )

    enrichment.enrich_imported_incidents([41, 42])

    assert calls == [
        ("extract", 41),
        ("match", 41),
        ("details", 41),
        ("extract", 42),
        ("match", 42),
        ("details", 42),
    ]


def test_enrichment_failure_does_not_block_later_rows(monkeypatch) -> None:
    extracted: list[int] = []
    detailed: list[int] = []

    def extract(raw_id: int) -> None:
        extracted.append(raw_id)
        if raw_id == 41:
            raise RuntimeError("temporary LLM failure")

    monkeypatch.setattr(enrichment, "run_tier1_extraction_for_message", extract)
    monkeypatch.setattr(enrichment, "SessionLocal", _SessionContext)
    monkeypatch.setattr(
        enrichment,
        "build_match_incident_action",
        lambda _db: SimpleNamespace(execute=lambda _raw_id: None),
    )
    monkeypatch.setattr(
        enrichment,
        "run_tier2_detail_fill_for_message",
        lambda raw_id: detailed.append(raw_id),
    )

    enrichment.enrich_imported_incidents([41, 42])

    assert extracted == [41, 42]
    assert detailed == [42]
