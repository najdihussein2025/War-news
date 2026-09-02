"""Compare Tier-2 baseline (N category calls) vs batched (1 call) on gold samples."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import app.accounts.models  # noqa: F401
import app.logs.models  # noqa: F401
import app.sources.models  # noqa: F401

from app.core.config import settings
from app.core.ollama_client import OllamaChatClient
from app.llm.dtos import ExtractionCategoryKey
from app.llm.services.ollama_category_detail_service import OllamaCategoryDetailService
from app.llm.services.ollama_extraction_service import OllamaExtractionService
from app.llm.services.ollama_presence_gate_service import OllamaPresenceGateService

ANSWER_KEY_PATH = (
    PROJECT_ROOT / "scripts" / "phase2-extraction-testing" / "answer_key.json"
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


def _expected_categories(sample: dict) -> list[ExtractionCategoryKey]:
    expected = sample.get("expected") or {}
    categories = expected.get("categories") or {}
    keys: list[ExtractionCategoryKey] = []
    for key in categories.keys():
        mapped = _map_answer_key_category(key)
        keys.append(ExtractionCategoryKey(mapped))
    return keys


def _category_snapshot(categories) -> dict[str, dict]:
    output: dict[str, dict] = {}
    for key, value in categories.items():
        output[key.value if hasattr(key, "value") else str(key)] = {
            "did": value.did,
            "name": value.name,
            "casualties": value.casualties.model_dump(mode="python")
            if value.casualties
            else None,
            "vehicles": value.vehicles.model_dump(mode="python")
            if value.vehicles
            else None,
        }
    return output


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
        category_detail=OllamaCategoryDetailService(client),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--output",
        type=Path,
        default=ANSWER_KEY_PATH.parent / "tier2_batched_comparison.json",
    )
    args = parser.parse_args()

    samples = json.loads(ANSWER_KEY_PATH.read_text(encoding="utf-8"))
    samples = [s for s in samples if _expected_categories(s)]
    if args.limit is not None:
        samples = samples[: args.limit]

    service = _build_service()
    per_sample = []
    baseline_calls = 0
    batched_calls = 0
    field_matches = 0
    field_total = 0

    for sample in samples:
        keys = _expected_categories(sample)
        post_text = _load_text(sample)
        sample_id = sample["sample_id"]

        settings.tier2_use_batched_category_detail = False
        baseline = service.extract_tier2_details(
            post_text,
            keys,
            raw_message_id=sample_id,
        )
        baseline_calls += len(keys)

        settings.tier2_use_batched_category_detail = True
        batched = service.extract_tier2_details(
            post_text,
            keys,
            raw_message_id=sample_id,
        )
        batched_calls += 1 if keys else 0

        baseline_snap = _category_snapshot(baseline)
        batched_snap = _category_snapshot(batched)
        for category in keys:
            key = category.value
            field_total += 1
            if baseline_snap.get(key) == batched_snap.get(key):
                field_matches += 1

        per_sample.append(
            {
                "sample_id": sample_id,
                "category_count": len(keys),
                "baseline_categories": baseline_snap,
                "batched_categories": batched_snap,
            }
        )

    report = {
        "samples_with_categories": len(samples),
        "avg_categories_per_sample": (
            sum(len(_expected_categories(s)) for s in samples) / len(samples)
            if samples
            else 0
        ),
        "baseline_llm_calls": baseline_calls,
        "batched_llm_calls": batched_calls,
        "field_level_agreement": f"{field_matches}/{field_total}",
        "field_level_agreement_pct": round(
            (field_matches / field_total * 100) if field_total else 0.0,
            1,
        ),
        "per_sample": per_sample,
    }
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
