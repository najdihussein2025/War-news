import argparse,json,shutil
from pathlib import Path
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('corrections'); args=ap.parse_args(); corrections=json.loads(Path(args.corrections).read_text(encoding='utf-8'))
 pending=Path('tests/fixtures/summaries/pending'); approved=pending.parent/'approved'; approved.mkdir(exist_ok=True)
 blocked=[]; approved_siblings=[]
 for name,c in corrections.items():
  src=pending/name
  if not src.exists(): continue
  if not c.get('wrong') and not str(c.get('missing','')).strip():
   fixture=json.loads(src.read_text(encoding='utf-8')); shutil.move(src,approved/name); approved_siblings.extend(fixture.get('siblings',[]))
  else:
   (pending/(src.stem+'.reviewer_notes.txt')).write_text(json.dumps(c,ensure_ascii=False,indent=2),encoding='utf-8'); blocked.append(name)
 print(json.dumps({'approved':len(corrections)-len(blocked),'approved_identical_siblings':approved_siblings,'pending':blocked},ensure_ascii=False))
if __name__=='__main__': main()
