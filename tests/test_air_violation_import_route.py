from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import app.api.news_router as news_router_module
from app.api.deps import require_admin, require_super_admin
from app.core.database import get_db
from app.main import app
from app.news.dtos import WorkbookImportSummaryDTO


@pytest.fixture
def client() -> TestClient:
    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[require_super_admin] = lambda: SimpleNamespace(id=uuid4())
    app.dependency_overrides[require_admin] = lambda: SimpleNamespace(id=uuid4())
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_air_violation_import_endpoint_returns_summary(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Service:
        def __init__(self, _db) -> None:
            pass

        def import_workbook(self, stream):
            assert stream.read(4)
            stream.seek(0)
            return WorkbookImportSummaryDTO(
                processed=1,
                succeeded=1,
                failed=0,
                row_errors=[],
            )

    monkeypatch.setattr(news_router_module, "AirViolationWorkbookService", _Service)

    response = client.post(
        "/api/air-violations/import",
        files={"file": ("air-violations.xlsx", BytesIO(b"test"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "processed": 1,
        "succeeded": 1,
        "skipped": 0,
        "failed": 0,
        "row_errors": [],
    }


def test_air_violation_import_endpoint_rejects_non_xlsx_files(client: TestClient) -> None:
    response = client.post(
        "/api/air-violations/import",
        files={"file": ("air-violations.csv", BytesIO(b"bad"), "text/csv")},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Upload an .xlsx workbook."}


def test_khabar_import_accepts_geojson_and_default_date(client, monkeypatch):
    class _Service:
        def __init__(self, db):
            pass

        def import_file(self, stream, filename, default_date):
            assert filename == 'news.geojson'
            assert default_date.isoformat() == '2026-09-07'
            assert stream.read() == b'[]'
            return WorkbookImportSummaryDTO(processed=0, succeeded=0, failed=0, row_errors=[])

    monkeypatch.setattr(news_router_module, 'AirViolationKhabarImportService', _Service)
    response = client.post('/api/air-violations/import-khabar',
        data={'default_date': '2026-09-07'},
        files={'file': ('news.geojson', BytesIO(b'[]'), 'application/json')})
    assert response.status_code == 200
    assert response.json()['succeeded'] == 0


def test_khabar_import_requires_default_date(client):
    response = client.post('/api/air-violations/import-khabar',
        files={'file': ('news.json', BytesIO(b'[]'), 'application/json')})
    assert response.status_code == 422
