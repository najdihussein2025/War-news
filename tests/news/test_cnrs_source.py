from unittest.mock import MagicMock, patch

from app.sources.services.cnrs_source import CNRS_MAX_PAGE_SIZE, CNRSSourceProvider


def test_normalize_record_maps_cnrs_metadata_present_in_any_feed_variant() -> None:
    record = {
        "id": 123,
        "source_platform": "twitter",
        "source_name": "example_handle",
        "post_text": "Post text",
        "post_date": "2026-08-13T10:20:30+00:00",
        "include": False,
        "confidence": 0.72,
        "event_domain": "security",
        "is_realtime": True,
    }

    normalized = CNRSSourceProvider._normalize_record(record)

    assert normalized["origin_platform"] == "twitter"
    assert normalized["origin_account"] == "example_handle"
    assert normalized["cnrs_classification"] == {
        "include": False,
        "confidence": 0.72,
        "event_domain": "security",
        "is_realtime": True,
    }


def test_normalize_record_leaves_absent_cnrs_metadata_null() -> None:
    normalized = CNRSSourceProvider._normalize_record(
        {
            "id": 456,
            "post_text": "Post text",
            "post_date": None,
        }
    )

    assert normalized["origin_platform"] is None
    assert normalized["origin_account"] is None
    assert normalized["cnrs_classification"] is None


def test_fetch_batch_calls_llm_filtered_posts_and_caps_page_size() -> None:
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "data": [
            {
                "id": 10,
                "post_text": "hi",
                "post_date": "2026-08-24T10:00:00+00:00",
                "include": True,
            }
        ],
        "next_cursor": 10,
        "has_more": True,
    }

    with patch("app.sources.services.cnrs_source.httpx.get", return_value=response) as get:
        with patch(
            "app.sources.services.cnrs_source.settings.cnrs_api_base_url",
            "https://lebanon.cnrs.edu.lb/api/v1/llm-filtered-posts",
        ):
            provider = CNRSSourceProvider(
                config={"model_backend": "local_llm"},
                api_key="token",
            )
            items, next_cursor, has_more = provider.fetch_batch(cursor="5", limit=5000)

    assert next_cursor == "10"
    assert has_more is True
    assert items[0]["external_message_id"] == "10"
    assert get.call_args.args[0] == "https://lebanon.cnrs.edu.lb/api/v1/llm-filtered-posts"
    assert get.call_args.kwargs["params"] == {
        "after_id": "5",
        "limit": CNRS_MAX_PAGE_SIZE,
    }
    assert "model_backend" not in get.call_args.kwargs["params"]
    assert get.call_args.kwargs["headers"]["Authorization"] == "Bearer token"
