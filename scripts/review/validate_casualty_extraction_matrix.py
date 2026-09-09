"""Exercise real Tier-1 extraction against varied, synthetic bulletin shapes."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

sys.stdout.reconfigure(encoding="utf-8")

from app.core.config import settings
from app.core.ollama_client import OllamaChatClient
from app.core.text_normalization import normalize_arabic_text
from app.llm.services.ollama_extraction_service import OllamaExtractionService


@dataclass(frozen=True)
class Case:
    name: str
    text: str
    expected_targets: dict[str, tuple[int | None, int | None]]
    expected_root: tuple[int | None, int | None] | None = None
    single_village_fallback: bool = False


CASES = (
    Case(
        name="inline_singular_and_arabic_indic",
        text=(
            "أفاد الدفاع المدني بأن الغارة على بلدة ياطر أدت إلى شهيد، "
            "بينما سقط ٤ جرحى في بلدة حداثا."
        ),
        expected_targets={"ياطر": (1, None), "حداثا": (None, 4)},
    ),
    Case(
        name="plural_deaths_and_singular_injury",
        text=(
            "استهدفت غارتان بلدتي حولا ومركبا؛ في حولا 3 شهداء، "
            "أما مركبا فسجلت جريحا واحدا."
        ),
        expected_targets={"حولا": (3, None), "مركبا": (None, 1)},
    ),
    Case(
        name="target_without_own_count",
        text=(
            "تعرضت بلدتا الجبين وطيرحرفا للقصف؛ أسفر القصف في طيرحرفا "
            "عن جريحين، فيما لم ترد حصيلة عن الجبين."
        ),
        expected_targets={"الجبين": (None, None), "طيرحرفا": (None, 2)},
    ),
    Case(
        name="dash_separator_and_mixed_digits",
        text="ميس الجبل - شهيدان؛ بليدا - ١٥ جريحا.",
        expected_targets={"ميس الجبل": (2, None), "بليدا": (None, 15)},
    ),
    Case(
        name="prose_without_location_separator",
        text=(
            "أصيب 2 في شقرا بعد غارة، وفي وقت لاحق أفيد عن شهيدة "
            "في مجدل سلم نتيجة غارة أخرى."
        ),
        expected_targets={"شقرا": (None, 2), "مجدل سلم": (1, None)},
    ),
    Case(
        name="vague_unallocated_casualties",
        text=(
            "طالت الغارات العديسة والطيبة وسقط ضحايا وأصيب عدد من الأشخاص "
            "من دون توزيع بحسب البلدة."
        ),
        expected_targets={"العديسة": (None, None), "الطيبة": (None, None)},
        expected_root=(None, None),
    ),
    Case(
        name="single_village_uses_root_fallback",
        text="أدت غارة على بلدة كونين إلى شهيد و5 جرحى.",
        expected_targets={"كونين": (1, 5)},
        expected_root=(1, 5),
        single_village_fallback=True,
    ),
    Case(
        name="bulletin_total_without_breakdown",
        text=(
            "أعلنت الوزارة سقوط 3 شهداء في اعتداءات طالت حانين وبرعشيت "
            "وكونين، من دون توزيع الحصيلة على البلدات."
        ),
        expected_targets={
            "حانين": (None, None),
            "برعشيت": (None, None),
            "كونين": (None, None),
        },
        expected_root=(3, None),
    ),
)


def _normalized_counts(values: dict[str, tuple[int | None, int | None]]):
    return {normalize_arabic_text(name): counts for name, counts in values.items()}


def main() -> int:
    summary = {"processed": 0, "succeeded": 0, "failed": 0}
    client = OllamaChatClient(
        base_url=settings.ollama_base_url,
        api_key=settings.ollama_api_key,
        model=settings.extraction_ollama_model,
        timeout_seconds=settings.extraction_llm_timeout_seconds,
        max_request_retries=settings.extraction_llm_request_retries,
        retry_backoff_seconds=settings.extraction_llm_retry_backoff_seconds,
    )
    service = OllamaExtractionService(client)

    for case in CASES:
        summary["processed"] += 1
        try:
            result = service.extract_tier1(case.text)
            root = (result.casualties.deaths, result.casualties.injuries)
            actual = {
                normalize_arabic_text(entry.village): (
                    entry.deaths,
                    entry.injuries,
                )
                for entry in result.village_roles
                if entry.role.value == "target"
            }
            if case.single_village_fallback and len(actual) == 1:
                village = next(iter(actual))
                per_village = actual[village]
                actual[village] = (
                    per_village[0] if per_village[0] is not None else root[0],
                    per_village[1] if per_village[1] is not None else root[1],
                )

            expected = _normalized_counts(case.expected_targets)
            errors = []
            if actual != expected:
                errors.append(f"targets expected={expected!r} actual={actual!r}")
            if case.expected_root is not None and root != case.expected_root:
                errors.append(
                    f"root expected={case.expected_root!r} actual={root!r}"
                )
            if errors:
                raise AssertionError("; ".join(errors))

            summary["succeeded"] += 1
            status = "passed"
            error = None
        except Exception as exc:
            summary["failed"] += 1
            result = locals().get("result")
            status = "failed"
            error = f"{type(exc).__name__}: {exc}"

        print(
            json.dumps(
                {
                    "case": case.name,
                    "status": status,
                    "error": error,
                    "model_output": (
                        result.model_dump(mode="json")
                        if result is not None
                        else None
                    ),
                },
                ensure_ascii=False,
            )
        )
        result = None

    print(json.dumps(summary, sort_keys=True))
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
