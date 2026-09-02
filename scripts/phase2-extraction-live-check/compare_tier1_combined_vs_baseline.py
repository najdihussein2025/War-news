"""Compare Tier-1 baseline (2 LLM calls) vs combined (1 call) on gold answer_key samples."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import app.accounts.models  # noqa: F401
import app.logs.models  # noqa: F401
import app.sources.models  # noqa: F401

from app.core.config import settings
from app.core.ollama_client import OllamaChatClient
from app.llm.services.ollama_extraction_service import OllamaExtractionService
from app.llm.services.ollama_presence_gate_service import OllamaPresenceGateService

ANSWER_KEY_PATH = (
    PROJECT_ROOT
    / "scripts"
    / "phase2-extraction-testing"
    / "answer_key.json"
)
SAMPLE_TEXTS_DIR = ANSWER_KEY_PATH.parent / "sample_texts"

ANSWER_KEY_CATEGORY_ALIASES = {
    "army": "lebanese_army",
}


def _map_answer_key_category(key: str) -> str:
    return ANSWER_KEY_CATEGORY_ALIASES.get(key, key)


def _load_text(sample: dict) -> str:
    sample_id = sample["sample_id"]
    sample_path = SAMPLE_TEXTS_DIR / f"sample_{sample_id}.txt"
    if sample_path.exists():
        return sample_path.read_text(encoding="utf-8").strip()
    return str(sample.get("khabar_text") or "").strip()


def _expected_categories(sample: dict) -> set[str]:
    expected = sample.get("expected") or {}
    categories = expected.get("categories") or {}
    return {_map_answer_key_category(key) for key in categories.keys()}


def _expected_casualties(sample: dict) -> dict[str, float]:
    mapping = {
        "Total_D": "total_deaths",
        "Total_Inj": "total_injuries",
        "Death": "deaths",
        "Injuries": "injuries",
    }
    output: dict[str, float] = {}
    for key, value in (sample.get("expected") or {}).get("casualties", {}).items():
        mapped = mapping.get(key)
        if mapped and isinstance(value, (int, float)):
            output[mapped] = float(value)
    return output


def _score_presence(expected: set[str], got: set[str]) -> tuple[int, int, int]:
    correct = len(expected & got)
    missed = len(expected - got)
    false_added = len(got - expected)
    return correct, missed, false_added


def _score_casualties(expected: dict[str, float], got) -> tuple[int, int]:
    exact = 0
    mismatch = 0
    got_dict = got.model_dump(mode="python") if got is not None else {}
    for key, expected_value in expected.items():
        actual = got_dict.get(key)
        if actual == expected_value:
            exact += 1
        else:
            mismatch += 1
    return exact, mismatch


def _build_service() -> OllamaExtractionService:
    client = OllamaChatClient(
        base_url=settings.ollama_base_url,
        api_key=settings.ollama_api_key,
        model=settings.extraction_ollama_model,
        timeout_seconds=settings.extraction_llm_timeout_seconds,
    )
    return OllamaExtractionService(
        client=client,
        presence_gate=OllamaPresenceGateService(client),
    )


def _run_mode(
    service: OllamaExtractionService,
    samples: list[dict],
    *,
    combined: bool,
) -> dict:
    settings.tier1_use_combined_presence_extraction = combined
    presence_stats = Counter()
    casualty_stats = Counter()
    per_sample: list[dict] = []

    for sample in samples:
        sample_id = sample["sample_id"]
        post_text = _load_text(sample)
        result = service.extract_tier1(post_text, raw_message_id=sample_id)
        expected_categories = _expected_categories(sample)
        got_categories = {key.value for key in result.presence_category_keys}
        correct, missed, false_added = _score_presence(
            expected_categories,
            got_categories,
        )
        presence_stats["correct"] += correct
        presence_stats["missed"] += missed
        presence_stats["false_added"] += false_added

        expected_casualties = _expected_casualties(sample)
        exact, mismatch = _score_casualties(expected_casualties, result.casualties)
        casualty_stats["exact"] += exact
        casualty_stats["mismatch"] += mismatch

        per_sample.append(
            {
                "sample_id": sample_id,
                "expected_categories": sorted(expected_categories),
                "got_categories": sorted(got_categories),
                "missed": sorted(expected_categories - got_categories),
                "false_added": sorted(got_categories - expected_categories),
            }
        )

    return {
        "mode": "combined" if combined else "baseline",
        "llm_calls_per_message": 1 if combined else 2,
        "samples": len(samples),
        "presence": dict(presence_stats),
        "casualties": dict(casualty_stats),
        "per_sample": per_sample,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare Tier-1 baseline vs combined extraction accuracy."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of answer_key samples (default: all)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ANSWER_KEY_PATH.parent / "tier1_combined_comparison.json",
    )
    args = parser.parse_args()

    samples = json.loads(ANSWER_KEY_PATH.read_text(encoding="utf-8"))
    if args.limit is not None:
        samples = samples[: args.limit]

    service = _build_service()
    baseline = _run_mode(service, samples, combined=False)
    combined = _run_mode(service, samples, combined=True)

    report = {
        "sample_count": len(samples),
        "baseline": baseline,
        "combined": combined,
        "call_count_reduction_pct": round(
            (1 - combined["llm_calls_per_message"] / baseline["llm_calls_per_message"])
            * 100,
            1,
        ),
    }
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Samples: {len(samples)}")
    print(
        f"Baseline presence correct/missed/false_added: "
        f"{baseline['presence'].get('correct', 0)}/"
        f"{baseline['presence'].get('missed', 0)}/"
        f"{baseline['presence'].get('false_added', 0)}"
    )
    print(
        f"Combined presence correct/missed/false_added: "
        f"{combined['presence'].get('correct', 0)}/"
        f"{combined['presence'].get('missed', 0)}/"
        f"{combined['presence'].get('false_added', 0)}"
    )
    print(
        f"Baseline casualties exact/mismatch: "
        f"{baseline['casualties'].get('exact', 0)}/"
        f"{baseline['casualties'].get('mismatch', 0)}"
    )
    print(
        f"Combined casualties exact/mismatch: "
        f"{combined['casualties'].get('exact', 0)}/"
        f"{combined['casualties'].get('mismatch', 0)}"
    )
    print(f"Call-count reduction: {report['call_count_reduction_pct']}%")
    print(f"Report written to: {args.output}")


if __name__ == "__main__":
    main()
