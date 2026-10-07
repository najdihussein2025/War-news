"""Export the southern exact-match gazetteer for DB-free summary tests."""
from __future__ import annotations
import json, sys
from pathlib import Path
import yaml
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from app.core.database import SessionLocal
from app.news.services.summaries.gazetteer import GazetteerSnapshot, build_gazetteer_snapshot

def main():
    with SessionLocal() as db:
        snapshot=build_gazetteer_snapshot(db)
        db.rollback()
    descriptor_path=Path("app/core/llm_knowledge/terminology/village_descriptors.yaml")
    descriptors=[x["term"] for x in yaml.safe_load(descriptor_path.read_text(encoding="utf-8"))]
    snapshot=GazetteerSnapshot(snapshot.names,descriptors)
    target=Path("tests/fixtures/summaries/gazetteer_snapshot.json")
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(snapshot.to_dict(),ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"wrote {target}: {len(snapshot.names)} names")
if __name__=="__main__": main()
