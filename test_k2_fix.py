#!/usr/bin/env python3
"""Quick test of K2 claim selection fix."""
import sys
sys.path.insert(0, '/app')

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.news.models import Base
from app.news.models.incident import Incident
from app.news.services.incident_details.incident_casualty_recompute import validate_incident_casualty_sources, resolve_casualty_selection

# Connect to test database
engine = create_engine("postgresql://postgres:postgres@war-news-db/war_news_test")
Base.metadata.create_all(engine)

with Session(engine) as db:
    # Test incident 1a5b73de-fb96-4c4a-ae64-7f71b73c9a12
    incident = db.query(Incident).filter_by(id="1a5b73de-fb96-4c4a-ae64-7f71b73c9a12").first()
    if not incident:
        print("Incident not found!")
        sys.exit(1)

    print(f"Testing incident: {incident.id}")
    print(f"Current values: deaths={incident.deaths}, injuries={incident.injuries}")
    print(f"Details: female_d={incident.detail.female_d if incident.detail else None}, "
          f"children_d={incident.detail.children_d if incident.detail else None}")

    validation = validate_incident_casualty_sources(db, incident)
    print(f"\nFound {len(validation.claims)} claims:")
    for i, claim in enumerate(validation.claims):
        print(f"  Claim {i}: deaths={claim.values.get('deaths')}, injuries={claim.values.get('injuries')}, "
              f"source_id={claim.raw_message_id}, is_health_ministry={claim.is_health_ministry}")

    values, conflict, selection = resolve_casualty_selection(validation, incident.village_id)
    print(f"\nResolved values:")
    print(f"  deaths={values['deaths']}, injuries={values['injuries']}")
    print(f"  female_d={values['detail.female_d']}, children_d={values['detail.children_d']}")
    print(f"  female_i={values['detail.female_i']}, children_i={values['detail.children_i']}")

    if conflict:
        print(f"\nConflicts: {conflict}")

    print(f"\nSelection:")
    for side, sel_info in selection.items():
        print(f"  {side}:")
        print(f"    rule: {sel_info['selection_rule']}")
        print(f"    source_id: {sel_info['source_id']}")
        print(f"    claim: {sel_info['claim_text'][:80]}...")
