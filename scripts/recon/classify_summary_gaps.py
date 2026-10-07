"""Classify the top Step-1 parser gaps with corpus evidence."""
import csv,json,re
from collections import Counter
from pathlib import Path

CLASSES={
 "header variant": re.compile(r"غار|قصف|تفجير|قنابل|تمشيط|طيران|مدفعي|فوسف"),
 "noise/signature": re.compile(r"t\.me|https?|𓂆|كرار|ميثم|جهاد",re.I),
 "descriptor/qualifier": re.compile(r"بلده|منطقه|مشاع|حرش|احراش|مرتفعات|تلال|وادي|مزرعه|حي|مجري|بين"),
 "count word": re.compile(r"قذيف|غارتين|ثلاث"),
 "prose": re.compile(r"العدو|استهدف|تقدم|محلقه|منازل|احراق|اعتداءات|القت|دبابه|تحركات|اصابات"),
}
def classify(token):
 for name,pattern in CLASSES.items():
  if pattern.search(token): return name
 return "alias candidate"
def main():
 report=Path('recon_output/step1_parser_coverage.md').read_text(encoding='utf-8')
 rows=[]
 for section in ('Top leftover tokens','Top unresolved places'):
  block=report.split('## '+section,1)[1].split('## ',1)[0]
  for token,count in re.findall(r"- `(.+?)`: (\d+)",block)[:30]: rows.append((token,int(count)))
 corpus=[json.loads(x) for x in Path('recon_output/summary_bulletins.jsonl').open(encoding='utf-8')]
 with Path('recon_output/step1b_gap_classification.csv').open('w',newline='',encoding='utf-8-sig') as f:
  w=csv.writer(f); w.writerow(['token','count','class','example_segment','message_id'])
  for token,count in rows:
   hit=next((r for r in corpus if token in r['text'] or token.replace('ه','ة') in r['text']),None)
   segment=''
   if hit:
    segment=next((x.strip() for x in re.split(r'[\n،,؛;]',hit['text']) if token in x or token.replace('ه','ة') in x),'')
   w.writerow([token,count,classify(token),segment,hit['message_id'] if hit else ''])
if __name__=='__main__': main()
