"""Draft pending golden fixtures and a DB-free corpus coverage report."""
from __future__ import annotations
import argparse, json, sys, yaml
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from app.news.services.summaries.detection import detect_summary
from app.news.services.summaries.gazetteer import GazetteerSnapshot
from app.news.services.summaries.headers import default_header_dictionary
from app.news.services.summaries.parser import parse_summary
from app.news.services.summaries.window import resolve_window

ROOT=Path("tests/fixtures/summaries")
def load():
    gaz=GazetteerSnapshot.from_dict(json.loads((ROOT/"gazetteer_snapshot.json").read_text(encoding="utf-8")))
    lex=yaml.safe_load(Path("app/core/llm_knowledge/terminology/summary_location_lexicon.yaml").read_text(encoding="utf-8"))
    return gaz,default_header_dictionary(),lex
def simple_item(i):
    return {"condition_id":i.condition_id,"primary":i.primary_village.name_ar,"secondary":i.secondary_village.name_ar if i.secondary_village else None,"qualifiers":list(i.qualifiers),"reported_count":i.reported_count,"location_texts":list(i.location_texts)}
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--after-aliases',action='store_true'); args=ap.parse_args()
    gaz,headers,lex=load(); rows=[json.loads(x) for x in Path("recon_output/summary_bulletins.jsonl").open(encoding="utf-8")]
    selected=[]; channels=Counter()
    # Deterministic diverse sample; 40279 is mandatory.
    for r in sorted(rows,key=lambda x:(x["message_id"]!=40279,x["message_id"])):
        ch=r.get("origin_account") or r.get("source")
        early=datetime.fromisoformat(r["message_datetime"]).astimezone().hour<3
        useful=channels[ch]<5 or (":" in r["text"] and "\n" not in r["text"][:250]) or "بين" in r["text"] or early
        if useful and len(selected)<30: selected.append(r); channels[ch]+=1
    pending=ROOT/"pending"; pending.mkdir(parents=True,exist_ok=True)
    leftovers=Counter(); unresolved_places=Counter(); unresolved_headers=Counter(); rules=Counter(); blockers=Counter(); accepted=0
    sectioned=sectioned_ok=prose_total=prose_ok=0
    for r in rows:
        posted=datetime.fromisoformat(r["message_datetime"]); window=resolve_window(r["text"],posted)
        result=parse_summary(r["text"],gaz,headers,lex); accepted+=result.auto_acceptable
        if result.out_of_scope_lines: prose_total+=1; prose_ok+=result.auto_acceptable
        else: sectioned+=1; sectioned_ok+=result.auto_acceptable
        leftovers.update(result.leftover_tokens); unresolved_places.update(result.unresolved_places); unresolved_headers.update(result.unresolved_headers); rules[window.rule]+=1
        if result.leftover_tokens: blockers['leftover tokens']+=1
        if result.unresolved_places: blockers['unresolved places']+=1
        if result.unresolved_headers: blockers['unresolved headers']+=1
        if result.ambiguous_places: blockers['ambiguous places']+=1
        if result.out_of_scope_lines: blockers['prose/timeline']+=1
        if r in selected and r["message_id"]!=40279:
            payload={"message_id":r["message_id"],"channel":r.get("origin_account"),"raw_text":r["text"],"posted_at":r["message_datetime"],"expected":{"window":{"start":window.start.isoformat(),"end":window.end.isoformat(),"rule":window.rule},"items":[simple_item(i) for i in result.items],"leftover_tokens":list(result.leftover_tokens),"out_of_scope_lines":list(result.out_of_scope_lines),"auto_acceptable":result.auto_acceptable},"reviewer_notes":""}
            (pending/f"{r['message_id']}.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    report=["# Step 1b parser coverage","",f"- Corpus: {len(rows)}",f"- Detected summaries: {sum(detect_summary(r['text']).is_summary for r in rows)}/{len(rows)}",f"- Before Step 1b: 19/{len(rows)} ({19/len(rows):.1%})",f"- After Step 1b{' and approved aliases' if args.after_aliases else ''}: {accepted}/{len(rows)} ({accepted/len(rows):.1%})",f"- Sectioned/non-prose: {sectioned_ok}/{sectioned} ({sectioned_ok/sectioned:.1%})",f"- Prose/timeline: {prose_ok}/{prose_total} ({prose_ok/prose_total:.1%})" if prose_total else "- Prose/timeline: 0/0","","## Remaining blockers by class",""]
    report += [f"- {k}: {v}" for k,v in blockers.most_common()]
    report += ["","## Window rules",""]
    report += [f"- {k}: {v}" for k,v in rules.most_common()]
    for title,data in (("Top leftover tokens",leftovers),("Top unresolved places",unresolved_places),("Unresolved headers",unresolved_headers)):
        report += ["",f"## {title}",""]+[f"- `{k}`: {v}" for k,v in data.most_common(30)]
    Path("recon_output/step1_parser_coverage.md").write_text("\n".join(report)+"\n",encoding="utf-8")
if __name__=="__main__": main()
