from app.news.services.pipeline.pipeline_llm_workers import (
    _final_action_description,
)


def test_supported_cnrs_action_wins_over_condition_evidence_heuristic() -> None:
    result = _final_action_description(
        "غارة جوية قرب موقع القصف المدفعي",
        "Artillery Shelling",
        {
            "include": True,
            "location": "النبطية",
            "event_subtype": "artillery",
        },
    )

    assert result == "Artillery Shelling"


def test_non_cnrs_action_still_uses_condition_evidence_heuristic() -> None:
    result = _final_action_description(
        "غارة جوية على البلدة",
        "Unknown",
        None,
    )

    assert result == "Bombs"
