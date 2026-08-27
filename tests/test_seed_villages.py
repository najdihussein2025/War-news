from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from openpyxl import Workbook

from app.core.seeds import seed_villages as seed_villages_module


class _ScalarsResult:
    def __init__(self, values):
        self._values = values

    def all(self):
        return self._values


class _StubSession:
    def __init__(self, existing_villages):
        self.existing_villages = existing_villages
        self.added = []
        self.committed = 0

    def scalars(self, stmt):
        return _ScalarsResult(self.existing_villages)

    def add(self, item):
        self.added.append(item)

    def commit(self):
        self.committed += 1


def test_load_villages_prefers_updated_excel_place_name(tmp_path: Path, monkeypatch) -> None:
    workbook_path = tmp_path / "ACS_Villages_Updated.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(
        [
            "KADA_NAME",
            "MOH_NAME",
            "TOWNNAME",
            "الإسم",
            "Name",
            "MOHAFAZAH",
            "ACS_CODE",
            "ACS_NAME",
            "CAD_NAME_1",
            "C_Ref_name",
            "C_ref_Ar",
            "Caza",
            "Mohafaza",
            "MohafazaAr",
            "Caza_Ara",
        ]
    )
    sheet.append(
        [
            "Beirut",
            "Beirut",
            "Ain el Mraisse",
            "عين المريسة",
            "Ain el Mraisse",
            "بيروت",
            10110,
            "Aain el-Mraisse fonciere",
            "Ain el-Mreisse",
            "Old English Ref",
            "عين المريسه",
            "Beirut",
            "Beirut",
            "بيروت",
            "بيروت",
        ]
    )
    workbook.save(workbook_path)

    monkeypatch.setattr(seed_villages_module, "VILLAGES_XLSX_PATH", workbook_path)
    monkeypatch.setattr(seed_villages_module, "VILLAGES_JSON_PATH", tmp_path / "Villages.json")

    rows = seed_villages_module._load_villages()

    assert rows == [
        {
            "acs_code": 10110,
            "acs_name": "Aain el-Mraisse fonciere",
            "cad_name": "Ain el-Mreisse",
            "ref_name_en": "Ain el Mraisse",
            "ref_name_ar": "عين المريسة",
            "caza_en": "Beirut",
            "caza_ar": "بيروت",
            "mohafaza_en": "Beirut",
            "mohafaza_ar": "بيروت",
            "coord_x": None,
            "coord_y": None,
        }
    ]


def test_seed_villages_updates_existing_rows_without_clearing_coordinates(
    monkeypatch,
) -> None:
    existing = SimpleNamespace(
        acs_code=10110,
        acs_name="old acs",
        cad_name="old cad",
        ref_name_en="old en",
        ref_name_ar="old ar",
        caza_en="old caza en",
        caza_ar="old caza ar",
        mohafaza_en="old moh en",
        mohafaza_ar="old moh ar",
        coord_x=123.45,
        coord_y=678.9,
    )
    session = _StubSession([existing])

    monkeypatch.setattr(
        seed_villages_module,
        "_load_villages",
        lambda: [
            {
                "acs_code": 10110,
                "acs_name": "new acs",
                "cad_name": "new cad",
                "ref_name_en": "new en",
                "ref_name_ar": "عين المريسة",
                "caza_en": "Beirut",
                "caza_ar": "بيروت",
                "mohafaza_en": "Beirut",
                "mohafaza_ar": "بيروت",
                "coord_x": None,
                "coord_y": None,
            }
        ],
    )

    inserted, updated, skipped = seed_villages_module.seed_villages(session)

    assert (inserted, updated, skipped) == (0, 1, 0)
    assert existing.acs_name == "new acs"
    assert existing.ref_name_ar == "عين المريسة"
    assert existing.coord_x == 123.45
    assert existing.coord_y == 678.9
    assert session.added == []
    assert session.committed == 1
