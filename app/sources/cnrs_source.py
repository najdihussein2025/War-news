from typing import Any

import httpx

from app.core.config import settings
from app.interfaces.source_provider import SourceProvider


class CNRSSourceProvider(SourceProvider):
    def __init__(self, config: dict[str, Any] | None, api_key: str) -> None:
        self.config = config or {}
        self.api_key = api_key

    def fetch_batch(
        self,
        cursor: str | None,
        limit: int = 500,
    ) -> tuple[list[dict], str | None, bool]:
        params: dict[str, Any] = {
            "after_id": cursor or 0,
            "limit": limit,
        }

        if self.config.get("model_backend") == "local_llm":
            params["model_backend"] = "local_llm"

        response = httpx.get(
            settings.cnrs_api_base_url,
            params=params,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=30.0,
        )

        if response.status_code != 200:
            raise RuntimeError(
                "CNRS API request failed "
                f"with status {response.status_code}: {response.text}"
            )

        payload = response.json()
        records = payload.get("data", [])
        next_cursor = payload.get("next_cursor")
        has_more = bool(payload.get("has_more", False))

        normalized_items = [self._normalize_record(record) for record in records]
        return (
            normalized_items,
            str(next_cursor) if next_cursor is not None else None,
            has_more,
        )

    @staticmethod
    def _normalize_record(record: dict[str, Any]) -> dict[str, Any]:
        # CNRS also has a field named "external_id" such as "twitter:1812";
        # raw_messages.external_message_id must use CNRS's numeric "id" instead.
        return {
            "external_message_id": str(record["id"]),
            "raw_text": record.get("post_text"),
            "raw_payload": record,
            "message_datetime": record.get("post_date"),
        }
