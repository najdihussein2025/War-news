from app.sources.services.cnrs_source import CNRSSourceProvider


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
