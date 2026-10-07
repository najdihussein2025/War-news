"""Read-only fuzzy suggestions for human alias review; never used by production parsing."""
import argparse,csv,json,re,sys
from collections import Counter,defaultdict
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from app.news.services.summaries.normalize import normalize_token,village_key

def edit(a,b):
 prev=list(range(len(b)+1))
 for i,x in enumerate(a,1):
  cur=[i]+[0]*len(b)
  for j,y in enumerate(b,1): cur[j]=min(cur[j-1]+1,prev[j]+1,prev[j-1]+(x!=y))
  prev=cur
 return prev[-1]
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--after-aliases',action='store_true'); ap.parse_args()
 coverage=Path('recon_output/step1_parser_coverage.md').read_text(encoding='utf-8')
 unresolved=coverage.split('## Top unresolved places',1)[1].split('\n## ',1)[0]
 gaps=[(x,int(n)) for x,n in re.findall(r"- `(.+?)`: (\d+)",unresolved) if int(n)>=3]
 snap=json.loads(Path('tests/fixtures/summaries/gazetteer_snapshot.json').read_text(encoding='utf-8'))
 villages={v['id']:(v['name_ar'],v['caza']) for values in snap['names'].values() for v in values}
 corpus=[json.loads(x) for x in Path('recon_output/summary_bulletins.jsonl').open(encoding='utf-8')]
 out=[]
 for raw,count in gaps:
  key=village_key(raw); candidates=[]
  for vid,(name,caza) in villages.items():
   nk=village_key(name)
   if key in nk or nk in key or edit(key.replace(' ',''),nk.replace(' ',''))<=1: candidates.append((vid,name,caza))
  candidates=list(dict.fromkeys(candidates))[:3]
  ids=[str(r['message_id']) for r in corpus if raw in r['text'] or raw.replace('ه','ة') in r['text']][:5]
  kind='not_a_place' if re.search(r't\.me|https?|اصابات|اعتداءات|تحركات',raw,re.I) else 'place_detail_of_village' if re.search(r'مزرعه|وادي|حي|مجري|سدانه',key) else 'alias_to_village'
  row=[raw,count,';'.join(ids),kind]
  for i in range(3): row += list(candidates[i]) if i<len(candidates) else ['','','']
  row += [candidates[0][0] if len(candidates)==1 else '','','','']
  out.append(row)
 cols=['unresolved_text','count','example_message_ids','proposed_type']+[f'candidate_{i}_{x}' for i in range(1,4) for x in ('id','name','caza')]+['recommended_id','approve','place_detail','notes']
 with Path('recon_output/alias_proposals.csv').open('w',newline='',encoding='utf-8-sig') as f: w=csv.writer(f); w.writerow(cols); w.writerows(out)
if __name__=='__main__': main()
