from __future__ import annotations

import argparse
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.actions.news import FilterRelevanceAction
from app.core.config import settings
from app.core.ollama_client import OllamaChatClient
from app.dtos.news import (
    ExtractionResult,
    FilterPendingMessagesData,
    MatchResultDTO,
    RelevanceClassificationResult,
)
from app.interfaces.repositories import RawMessageRepositoryInterface
from app.interfaces.services import KeywordPrefilterInterface
from app.models.news import MessageStatus, RawMessage
from app.services.news.ollama_relevance_classifier_service import (
    OllamaRelevanceClassifierService,
)

DEFAULT_SAMPLES_DIR = PROJECT_ROOT / "scripts" / "llm-testing" / "samples"
EXPECTED_SAMPLE_NAMES = (
    "sample_1_relevant.txt",
    "sample_2_irrelevant_shipping.txt",
    "sample_3_irrelevant_taiwan.txt",
    "sample_4_irrelevant_trump.txt",
    "sample_5_relevant_ied_army.txt",
    "sample_6_relevant_car_strike.txt",
    "sample_7_hard_negative_gaza_1.txt",
    "sample_8_hard_negative_gaza_2.txt",
    "sample_9_hard_negative_earthquake.txt",
)


@dataclass(frozen=True)
class LiveCheckRecord:
    filename: str
    result: RelevanceClassificationResult
    elapsed_seconds: float


class AlwaysCandidateKeywordPrefilter(KeywordPrefilterInterface):
    def has_candidate_keywords(self, text: str) -> bool:
        return True


class LiveCheckRawMessageRepository(RawMessageRepositoryInterface):
    def __init__(self, messages: list[RawMessage]) -> None:
        self._messages = messages
        self.records: list[LiveCheckRecord] = []
        self._started_at_by_id: dict[int, float] = {}
        for message in self._messages:
            self._started_at_by_id[message.id] = time.perf_counter()

    def get_pending_unfiltered_batch(self, limit: int) -> list[RawMessage]:
        return self._messages[:limit]

    def get_pending_extraction_batch(self, limit: int) -> list[RawMessage]:
        return []

    def save_filter_result(
        self,
        message: RawMessage,
        result: RelevanceClassificationResult,
        new_status: MessageStatus,
        needs_review: bool = False,
    ) -> None:
        message.filter_result = result.model_dump(mode="json")
        message.filter_result["needs_review"] = needs_review
        message.status = new_status
        message.low_confidence_relevance = needs_review
        started_at = self._started_at_by_id.get(message.id, time.perf_counter())
        self.records.append(
            LiveCheckRecord(
                filename=str(message.external_message_id),
                result=result,
                elapsed_seconds=time.perf_counter() - started_at,
            )
        )

    def save_extraction_result(
        self,
        message: RawMessage,
        result: ExtractionResult,
        audited_candidates: list[dict[str, object]],
    ) -> None:
        raise NotImplementedError("Extraction is outside this live relevance check.")

    def get_parsed_by_id(self, raw_message_id: int) -> RawMessage | None:
        raise NotImplementedError("Matching is outside this live relevance check.")

    def save_match_result(
        self,
        message: RawMessage,
        result: MatchResultDTO,
    ) -> None:
        raise NotImplementedError("Matching is outside this live relevance check.")

    def save_error(self, message: RawMessage, error_message: str) -> None:
        raise RuntimeError(f"{message.external_message_id}: {error_message}")

    def rollback(self) -> None:
        return


def _sample_sort_key(path: Path) -> list[int | str]:
    return [
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r"(\d+)", path.name)
    ]


def _load_messages(
    samples_dir: Path,
    require_expected_names: bool,
) -> list[RawMessage]:
    if require_expected_names:
        missing = [
            sample_name
            for sample_name in EXPECTED_SAMPLE_NAMES
            if not (samples_dir / sample_name).is_file()
        ]
        if missing:
            joined_missing = ", ".join(missing)
            raise RuntimeError(
                f"Missing expected sample file(s) in {samples_dir}: {joined_missing}"
            )
        sample_paths = [samples_dir / sample_name for sample_name in EXPECTED_SAMPLE_NAMES]
    else:
        sample_paths = sorted(samples_dir.glob("*.txt"), key=_sample_sort_key)
        if not sample_paths:
            raise RuntimeError(f"No .txt sample files found in {samples_dir}")

    messages: list[RawMessage] = []
    for index, sample_path in enumerate(sample_paths, start=1):
        messages.append(
            RawMessage(
                id=index,
                source_id=0,
                external_message_id=sample_path.name,
                raw_text=sample_path.read_text(encoding="utf-8"),
                raw_payload={},
                status=MessageStatus.pending,
            )
        )
    return messages


def _build_action(repository: LiveCheckRawMessageRepository) -> FilterRelevanceAction:
    client = OllamaChatClient(
        base_url=settings.ollama_base_url,
        api_key=settings.ollama_api_key,
        model=settings.ollama_model,
        timeout_seconds=settings.ollama_timeout_seconds,
    )
    return FilterRelevanceAction(
        raw_messages=repository,
        classifier=OllamaRelevanceClassifierService(client),
        keyword_prefilter=AlwaysCandidateKeywordPrefilter(),
    )


def _print_record(record: LiveCheckRecord) -> None:
    confidence = record.result.confidence
    print(f"=== {record.filename} ===")
    print(f"verdict: {record.result.verdict.value}")
    print(f"confidence: {confidence}")
    print(f"reasoning: {record.result.reasoning}")
    print(f"backend: {record.result.backend}")
    print(f"elapsed_seconds: {record.elapsed_seconds:.2f}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run live relevance classification against sample text files."
    )
    parser.add_argument(
        "--samples-dir",
        type=Path,
        default=None,
        help=(
            "Directory containing .txt sample files. If omitted, the script uses "
            "the original nine llm-testing sample filenames."
        ),
    )
    args = parser.parse_args()

    require_expected_names = args.samples_dir is None
    samples_dir = (args.samples_dir or DEFAULT_SAMPLES_DIR).resolve()
    messages = _load_messages(
        samples_dir=samples_dir,
        require_expected_names=require_expected_names,
    )
    repository = LiveCheckRawMessageRepository(messages)
    action = _build_action(repository)

    print(f"Samples: {samples_dir}")
    print(f"Ollama model: {settings.ollama_model}")
    print()

    summary = action.execute(FilterPendingMessagesData(batch_size=len(messages)))
    for record in repository.records:
        _print_record(record)

    print("Summary")
    print(f"processed: {summary.processed}")
    print(f"relevant: {summary.relevant}")
    print(f"rejected: {summary.rejected}")
    print(f"uncertain: {summary.uncertain}")
    print(f"errored: {summary.errored}")
    print(f"classifier_calls_made: {summary.classifier_calls_made}")


if __name__ == "__main__":
    main()
