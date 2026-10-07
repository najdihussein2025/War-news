"""Generate idempotent SQL only from explicitly approved alias proposals."""
import csv,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from app.news.services.summaries.normalize import normalize_token
def q(v): return "'"+str(v).replace("'","''")+"'"
def main():
 rows=list(csv.DictReader(Path('recon_output/alias_proposals.csv').open(encoding='utf-8-sig')))
 approved=[r for r in rows if r['approve'].strip().lower()=='yes' and r['recommended_id']]
 sql=['BEGIN;']
 for r in approved:
  sql.append(f"INSERT INTO village_location_aliases (alias_text, alias_normalized, village_id, note, requires_geo_context, is_active) VALUES ({q(r['unresolved_text'])}, {q(normalize_token(r['unresolved_text']))}, {int(r['recommended_id'])}, {q(r['place_detail'] or r['notes'])}, false, true) ON CONFLICT (alias_normalized) DO NOTHING;")
 sql += ['COMMIT;','']
 Path('scripts/sql/seed_summary_aliases.sql').write_text('\n'.join(sql),encoding='utf-8')
if __name__=='__main__': main()
