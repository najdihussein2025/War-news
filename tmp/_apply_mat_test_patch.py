from pathlib import Path

TARGET = Path("tests/test_incident_materialization_service.py")
text = TARGET.read_text(encoding="utf-8")

if "merges_without_re_score" in text:
    print("already patched")
    raise SystemExit(0)

# Replace both old confident_duplicate tests (high + insufficient) with one.
old_start = "def test_fast_path_confident_duplicate_merges_when_score_high()"
old_end = "def test_terminalized_message_leaves_stage_timestamps_null()"

if old_start not in text:
    raise SystemExit("old test block not found")

new = '''def test_fast_path_confident_duplicate_merges_without_re_score() -> None:
    """DuplicateComparisonService confident verdict merges; DedupMatchingService
    is used only for merge mechanics — find_best_match is never consulted."""
    existing = SimpleNamespace(id=uuid4(), raw_message_id=999)
    dedup = _DedupServiceStub(existing=existing, score=0.10)  # type: ignore[arg-type]
    duplicate_matches: list[dict] = []
    db = _SessionStub()
    service = IncidentMaterializationService(db, dedup_service=dedup)  # type: ignore[arg-type]
    representative = _representative()

    service.process_fast_path(
        representative,
        SimpleNamespace(
            incidents=SimpleNamespace(
                create_fast_path_duplicate_match=lambda **kwargs: duplicate_matches.append(
                    kwargs
                )
            ),
            decide_for_village=lambda **_kwargs: SimpleNamespace(
                outcome=FastPathDedupOutcome.confident_duplicate,
                representative_raw_message_id=999,
                canonical_incident_id=existing.id,
                canonical_incident=existing,
                similarity_score=0.91,
                similarity_method="text",
            ),
        ),
    )

    assert len(dedup.merge_calls) == 1
    assert dedup.merge_calls[0][0] is existing
    assert representative.status == MessageStatus.materialized
    assert representative.materialized_at is not None
    assert representative.fast_path_completed_at is not None
    assert len(duplicate_matches) == 1
    assert duplicate_matches[0]["status"].value == "confirmed_duplicate"
    assert duplicate_matches[0]["similarity_score"] == 0.91


'''

s = text.index(old_start)
e = text.index(old_end)
TARGET.write_text(text[:s] + new + text[e:], encoding="utf-8")
print("patched materialization tests")
