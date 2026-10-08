"""Add-only LLM cross-check: every proposal is re-verified in code."""
from __future__ import annotations

import asyncio
import inspect
import json
from datetime import date, datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from app.core.ollama_client import OllamaChatClient, OllamaChatMessage
from app.news.models.summary_bulletin import (
    SummaryItemOrigin,
    SummaryResolution,
    SummaryReviewTask,
    SummaryStatus,
)
from app.news.services.summaries import crosscheck_service as cc
from app.news.services.summaries import intake_service
from app.news.services.summaries.dtos import VillageRef
from app.news.services.summaries.gazetteer import GazetteerSnapshot
from app.news.services.summaries.headers import default_header_dictionary

BULLETIN = "ملخص الاعتداءات\nالغارات:\n- كفرا\n- صديقين\n- بين الخيام وميفدون"
GAZETTEER = GazetteerSnapshot({
    "كفرا": [VillageRef(1, "كفرا", "Bint Jubail")],
    "صديقين": [VillageRef(2, "صديقين", "Sour")],
    "الخيام": [VillageRef(3, "الخيام", "Marjaayoun")],
    "ميفدون": [VillageRef(4, "ميفدون", "Nabatiye")],
})
HEADERS = default_header_dictionary()
# What the parser already extracted: strike (46) at village 1 and 2.
PARSED = (
    cc.ParserPair("الغارات", "كفرا", 46, 1, None),
    cc.ParserPair("الغارات", "صديقين", 46, 2, None),
)


class _Client:
    def __init__(self, response=None, error: Exception | None = None):
        self.response, self.error, self.calls = response, error, []

    def chat(self, messages, response_format="json", temperature=None):
        self.calls.append((messages, response_format, temperature))
        if self.error:
            raise self.error
        return self.response if isinstance(self.response, str) else json.dumps(self.response, ensure_ascii=False)


def run(client, *, enabled=True, pairs=PARSED, text=BULLETIN, known=()):
    return asyncio.run(cc.crosscheck_summary(
        text, pairs, gazetteer=GAZETTEER, headers=HEADERS, anchor_date=date(2026, 10, 8),
        client=client, enabled=enabled, known_unresolved=known,
    ))


def proposal(header="الغارات", location="بين الخيام وميفدون", evidence="- بين الخيام وميفدون"):
    return {"header": header, "location": location, "evidence_span": evidence}


def test_valid_addition_is_accepted_with_strict_resolution():
    result = run(_Client({"missing": [proposal()]}))
    assert result.error is None and result.called
    assert len(result.accepted) == 1 and not result.review
    item = result.accepted[0].item
    assert item.primary_village.id == 3 and item.secondary_village.id == 4  # one "between" item
    assert result.accepted[0].evidence_span in BULLETIN


def test_non_verbatim_evidence_is_dropped():
    result = run(_Client({"missing": [proposal(evidence="بين الخيام و ميفدون")]}))  # spacing changed
    assert result.accepted == [] and result.review == [] and result.dropped == {"evidence_not_verbatim": 1}


def test_location_not_inside_evidence_is_dropped():
    result = run(_Client({"missing": [proposal(location="كفركلا", evidence="- بين الخيام وميفدون")]}))
    assert result.accepted == [] and result.dropped == {"location_not_in_evidence": 1}


def test_invented_village_is_never_accepted():
    text = BULLETIN + "\n- قرية وهمية"
    result = run(_Client({"missing": [proposal(location="قرية وهمية", evidence="- قرية وهمية")]}), text=text)
    assert result.accepted == []
    assert [r.reason for r in result.review] == ["unresolved_location"]


def test_unknown_header_goes_to_review():
    text = BULLETIN + "\nعناوين مجهولة:\n- كفرا"
    result = run(_Client({"missing": [proposal(header="عناوين مجهولة", location="كفرا", evidence="- كفرا")]}), text=text)
    assert result.accepted == [] and [r.reason for r in result.review] == ["unknown_header"]


def test_duplicate_of_a_parser_item_is_dropped():
    result = run(_Client({"missing": [proposal(location="كفرا", evidence="- كفرا")]}))
    assert result.accepted == [] and result.review == [] and result.dropped == {"duplicate_of_parser_item": 1}


def test_place_already_in_review_is_not_reported_twice():
    result = run(_Client({"missing": [proposal(location="قرية وهمية", evidence="قرية وهمية")]}),
                 text=BULLETIN + "\nقرية وهمية", known=["قرية وهمية"])
    assert result.accepted == [] and result.review == [] and result.dropped == {"already_in_review": 1}


def test_llm_cannot_remove_or_modify_parser_items():
    pairs = tuple(PARSED)
    client = _Client({"missing": [], "remove": ["كفرا"], "items": [{"header": "x"}], "replace": {"كفرا": "x"}})
    result = run(client, pairs=pairs)
    assert pairs == PARSED and result.accepted == [] and result.review == []
    assert not hasattr(result, "removed")


def test_timeout_keeps_parser_result():
    result = run(_Client(error=httpx.ReadTimeout("slow")))
    assert result.accepted == [] and result.error.startswith("crosscheck skipped: ReadTimeout")


def test_connection_error_keeps_parser_result():
    result = run(_Client(error=httpx.ConnectError("down")))
    assert result.accepted == [] and "ConnectError" in result.error


@pytest.mark.parametrize("bad", ["not json", "[]", '{"missing": "x"}', "{}"])
def test_invalid_json_keeps_parser_result(bad):
    result = run(_Client(response=bad))
    assert result.accepted == [] and result.error and result.error.startswith("crosscheck skipped")


def test_disabled_setting_never_calls_the_model():
    client = _Client({"missing": [proposal()]})
    result = run(client, enabled=False)
    assert client.calls == [] and not result.called and result.accepted == []


def test_client_is_called_with_schema_and_zero_temperature():
    client = _Client({"missing": []})
    run(client)
    messages, response_format, temperature = client.calls[0]
    assert response_format == cc.RESPONSE_SCHEMA and temperature == 0.0
    assert messages[0].role == "system" and BULLETIN in messages[1].content
    assert "طيران مسير" in messages[0].content and "بين X و Y" in messages[0].content


def test_wrapper_signature_matches_ollama_client():
    """The service calls chat(messages, response_format=..., temperature=...): pin it to the real wrapper."""
    signature = inspect.signature(OllamaChatClient.chat)
    signature.bind(object(), [OllamaChatMessage("user", "x")], response_format=cc.RESPONSE_SCHEMA, temperature=0.0)
    init = inspect.signature(OllamaChatClient.__init__)
    init.bind(object(), base_url="u", api_key=None, model="m", timeout_seconds=1)
    client = cc.build_crosscheck_client()
    assert client.model == cc.settings.summary_crosscheck_model


def test_accepted_items_are_appended_once_to_the_misses_file(tmp_path):
    result = run(_Client({"missing": [proposal()]}))
    path = tmp_path / "misses.jsonl"
    cc.record_parser_misses(42, result.accepted, path=path)
    cc.record_parser_misses(42, result.accepted, path=path)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["message_id"] == 42 and rows[0]["location"] == "بين الخيام وميفدون"
    assert rows[0]["header"] == "الغارات" and rows[0]["evidence"] == "- بين الخيام وميفدون"


# ---- wired into intake (fake session, real parser) ---------------------------------------

class _Session:
    def __init__(self): self.added = []
    def add(self, obj): self.added.append(obj)
    def flush(self): pass
    def scalar(self, *_a, **_k): return None


def _intake(monkeypatch, crosscheck_result):
    monkeypatch.setattr(intake_service, "detect_summary", lambda text: SimpleNamespace(is_summary=True))
    monkeypatch.setattr(intake_service, "build_gazetteer_snapshot", lambda session: GAZETTEER)
    monkeypatch.setattr(intake_service, "header_dictionary_for_session", lambda session: HEADERS)
    monkeypatch.setattr(intake_service, "record_parser_misses", lambda *a, **k: None)

    async def fake(*_a, **_k):
        return crosscheck_result
    monkeypatch.setattr(intake_service, "crosscheck_summary", fake)
    session = _Session()
    message = SimpleNamespace(
        id=11, raw_text=BULLETIN, source_id=1, source_name="قناة",
        message_datetime=datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc), received_at=None,
    )
    result = asyncio.run(intake_service.intake_summary(session, message))
    return result, session


def test_intake_persists_accepted_llm_items_with_origin(monkeypatch):
    accepted = run(_Client({"missing": [proposal(location="كفرا", evidence="- كفرا")]}), pairs=()).accepted
    parser_only = cc.CrosscheckResult()
    _res, base = _intake(monkeypatch, parser_only)
    base_items = [o for o in base.added if hasattr(o, "evidence_span")]
    extra = cc.CrosscheckResult(accepted=[cc.AcceptedAddition("الغارات", "الخيام", "- بين الخيام وميفدون", accepted[0].item)])
    result, session = _intake(monkeypatch, extra)
    items = [o for o in session.added if hasattr(o, "evidence_span")]
    llm = [i for i in items if i.origin == SummaryItemOrigin.llm_crosscheck]
    assert len(items) == len(base_items) + 1 and len(llm) == 1
    assert llm[0].resolution == SummaryResolution.resolved and llm[0].evidence_span == "- بين الخيام وميفدون"
    assert [i for i in items if i.origin == SummaryItemOrigin.parser], "parser items are untouched"
    assert result.outcome in {"parsed", "needs_review"}


def test_intake_sends_llm_review_reasons_to_the_single_task(monkeypatch):
    review = cc.CrosscheckResult(review=[cc.ReviewAddition("unknown_header", "عناوين مجهولة", "كفرا", "- كفرا")])
    result, session = _intake(monkeypatch, review)
    tasks = [o for o in session.added if isinstance(o, SummaryReviewTask)]
    assert result.outcome == "needs_review" and len(tasks) == 1
    assert any(r["type"] == "unknown_header" and r.get("origin") == "llm_crosscheck" for r in tasks[0].reasons)


def test_intake_survives_a_crosscheck_error(monkeypatch):
    failed = cc.CrosscheckResult(error="crosscheck skipped: ReadTimeout: slow", called=True)
    result, session = _intake(monkeypatch, failed)
    summary = session.added[0]
    assert result.outcome in {"parsed", "needs_review"} and summary.status != SummaryStatus.failed
    assert summary.last_error == "crosscheck skipped: ReadTimeout: slow"
