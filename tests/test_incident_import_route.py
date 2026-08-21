from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import app.api.incidents_router as incidents_router_module
from app.api.deps import require_super_admin
from app.core.database import get_db
from app.main import app
from app.news.dtos import WorkbookImportSummaryDTO


@pytest.fixture
def client() -> TestClient:
    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[require_super_admin] = lambda: SimpleNamespace(id=uuid4())
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_incident_import_endpoint_returns_summary(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Service:
        def __init__(self, _db) -> None:
            pass

        def import_workbook(self, stream, *, created_by):
            assert created_by is not None
            assert stream.read(4)
            stream.seek(0)
            return WorkbookImportSummaryDTO(
                processed=2,
                succeeded=1,
                failed=1,
                row_errors=[{"row": 4, "error": "ValueError: bad row"}],
            )

    monkeypatch.setattr(incidents_router_module, "IncidentWorkbookService", _Service)

    response = client.post(
        "/api/incidents/import",
        files={"file": ("incidents.xlsx", BytesIO(b"test"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "processed": 2,
        "succeeded": 1,
        "failed": 1,
        "row_errors": [{"row": 4, "error": "ValueError: bad row"}],
    }


def test_incident_import_endpoint_rejects_non_xlsx_files(client: TestClient) -> None:
    response = client.post(
        "/api/incidents/import",
        files={"file": ("incidents.csv", BytesIO(b"bad"), "text/csv")},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Upload an .xlsx workbook."}
