import json
from datetime import datetime
from pathlib import Path
import yaml
from app.news.services.summaries.gazetteer import GazetteerSnapshot
from app.news.services.summaries.headers import default_header_dictionary
from app.news.services.summaries.parser import parse_summary
from app.news.services.summaries.window import resolve_window

ROOT=Path('tests/fixtures/summaries')
def test_approved_golden_fixtures():
    gaz=GazetteerSnapshot.from_dict(json.loads((ROOT/'gazetteer_snapshot.json').read_text(encoding='utf-8')))
    lex=yaml.safe_load(Path('app/core/llm_knowledge/terminology/summary_location_lexicon.yaml').read_text(encoding='utf-8'))
    files=sorted((ROOT/'approved').glob('*.json')); assert files
    for path in files:
        case=json.loads(path.read_text(encoding='utf-8')); result=parse_summary(case['raw_text'],gaz,default_header_dictionary(),lex)
        window=resolve_window(case['raw_text'],datetime.fromisoformat(case['posted_at']))
        actual={(i.condition_id,i.primary_village.name_ar,i.secondary_village.name_ar if i.secondary_village else None,tuple(i.qualifiers),i.reported_count) for i in result.items}
        expected={(i['condition_id'],i['primary'],i.get('secondary'),tuple(i.get('qualifiers',[])),i.get('reported_count',1)) for i in case['expected']['items']}
        assert actual==expected,path
        assert window.start.isoformat()==case['expected']['window']['start'] and window.end.isoformat()==case['expected']['window']['end']
        assert list(result.leftover_tokens)==case['expected']['leftover_tokens'] and result.auto_acceptable==case['expected']['auto_acceptable']
