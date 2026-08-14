from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import settings
from app.core.ollama_client import OllamaChatClient
from app.dtos.news import ExtractionResult
from app.services.news.ollama_extraction_service import OllamaExtractionService

DEFAULT_SAMPLES_DIR = (
    PROJECT_ROOT / "scripts" / "phase2-extraction-testing" / "sample_texts"
)


def _sample_sort_key(path: Path) -> list[int | str]:
    return [
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r"(\d+)", path.name)
    ]


def _load_sample_paths(samples_dir: Path) -> list[Path]:
    sample_paths = sorted(samples_dir.glob("*.txt"), key=_sample_sort_key)
    if not sample_paths:
        raise RuntimeError(f"No .txt sample files found in {samples_dir}")
    return sample_paths


def _build_service() -> OllamaExtractionService:
    client = OllamaChatClient(
        base_url=settings.ollama_base_url,
        api_key=settings.ollama_api_key,
        model=settings.extraction_ollama_model,
        timeout_seconds=settings.ollama_timeout_seconds,
    )
    return OllamaExtractionService(client)


def _categories_output(result: ExtractionResult) -> str:
    if not result.categories:
        return "none"
    return json.dumps(result.model_dump(mode="json")["categories"], ensure_ascii=False)


def _print_result(
    filename: str,
    result: ExtractionResult,
    elapsed_seconds: float,
) -> None:
    print(f"=== {filename} ===")
    print(f"village: {result.village}")
    print(f"action_description: {result.action_description}")
    print(f"categories: {_categories_output(result)}")
    print(f"elapsed_seconds: {elapsed_seconds:.2f}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run live extraction against sample text files."
    )
    parser.add_argument(
        "--samples-dir",
        type=Path,
        default=DEFAULT_SAMPLES_DIR,
        help="Directory containing .txt sample files.",
    )
    args = parser.parse_args()

    samples_dir = args.samples_dir.resolve()
    sample_paths = _load_sample_paths(samples_dir)
    service = _build_service()

    print(f"Samples: {samples_dir}")
    print(f"Ollama model: {settings.extraction_ollama_model}")
    print()

    for index, sample_path in enumerate(sample_paths, start=1):
        started_at = time.perf_counter()
        result = service.extract(
            post_text=sample_path.read_text(encoding="utf-8"),
            raw_message_id=index,
        )
        _print_result(
            filename=sample_path.name,
            result=result,
            elapsed_seconds=time.perf_counter() - started_at,
        )


if __name__ == "__main__":
    main()
