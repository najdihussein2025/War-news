"""Regenerate deduplicated fixtures and current/simulated coverage."""
from __future__ import annotations
import csv,json,sys,yaml
from collections import Counter,defaultdict
from datetime import datetime
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from app.news.services.summaries.detection import detect_summary
from app.news.services.summaries.dtos import VillageRef
from app.news.services.summaries.gazetteer import GazetteerSnapshot
from app.news.services.summaries import invariants
from app.news.services.summaries.headers import default_header_dictionary
from app.news.services.summaries.normalize import normalize_summary_text
from app.news.services.summaries.parser import parse_summary
from app.news.services.summaries.window import resolve_window

ROOT=Path("tests/fixtures/summaries")

def load():
    gaz=GazetteerSnapshot.from_dict(json.loads((ROOT/"gazetteer_snapshot.json").read_text(encoding="utf-8")))
    lex=yaml.safe_load(Path("app/core/llm_knowledge/terminology/summary_location_lexicon.yaml").read_text(encoding="utf-8"))
    return gaz,default_header_dictionary(),lex

def simulated(gaz):
    names={k:list(v) for k,v in gaz.names.items()}; refs={v.id:v for values in gaz.names.values() for v in values}
    for row in csv.DictReader(Path("recon_output/alias_proposals.csv").open(encoding="utf-8-sig")):
        if row["approve"].strip().lower()!="yes" or not row["recommended_id"]: continue
        ref=refs.get(int(row["recommended_id"]))
        if ref:
            names[row["unresolved_text"]]=[VillageRef(ref.id,ref.name_ar,ref.caza,ref.coord_x,ref.coord_y,row["place_detail"] or None)]
    return GazetteerSnapshot(names,gaz.descriptors)

def simple_item(i):
    return {"condition_id":i.condition_id,"primary":i.primary_village.name_ar,"secondary":i.secondary_village.name_ar if i.secondary_village else None,"qualifiers":list(i.qualifiers),"reported_count":i.reported_count,"location_texts":list(i.location_texts),"event_time":i.event_time.isoformat() if i.event_time else None,"origin_text":i.origin_text,"status":i.status,"source_header":i.header_text,"condition_source":i.condition_source}

def main():
    gaz,headers,lex=load(); sim=simulated(gaz)
    rows=[json.loads(x) for x in Path("recon_output/summary_bulletins.jsonl").open(encoding="utf-8")]
    current=[]; proposed=[]; rules=Counter(); blockers=Counter(); leftovers=Counter(); unresolved_places=Counter(); unresolved_headers=Counter(); residuals=Counter(); residual_texts=Counter()
    sectioned=sectioned_ok=sim_sectioned_ok=timeline=timeline_ok=sim_timeline_ok=0
    by_id={r["message_id"]:r for r in rows}
    for r in rows:
        posted=datetime.fromisoformat(r["message_datetime"]); window=resolve_window(r["text"],posted)
        a=parse_summary(r["text"],gaz,headers,lex,window.anchor_date); b=parse_summary(r["text"],sim,headers,lex,window.anchor_date)
        current.append(a); proposed.append(b); rules[window.rule]+=1
        residuals.update(x.kind for x in a.residual); residual_texts.update((x.kind,x.text) for x in a.residual)
        is_timeline=any(i.event_time for i in a.items) or bool(a.out_of_scope_lines)
        if is_timeline: timeline+=1; timeline_ok+=a.auto_acceptable; sim_timeline_ok+=b.auto_acceptable
        else: sectioned+=1; sectioned_ok+=a.auto_acceptable; sim_sectioned_ok+=b.auto_acceptable
        leftovers.update(a.leftover_tokens); unresolved_places.update(a.unresolved_places); unresolved_headers.update(a.unresolved_headers)
        for label,value in (("leftover tokens",a.leftover_tokens),("unresolved places",a.unresolved_places),("unresolved headers",a.unresolved_headers),("ambiguous places",a.ambiguous_places),("prose/timeline",a.out_of_scope_lines)):
            if value: blockers[label]+=1

    # Start from a diverse deterministic sample, force the three Step 1c cases,
    # then retain one representative for byte-normalised repost families.
    selected=[]; channels=Counter()
    for r in sorted(rows,key=lambda x:x["message_id"]):
        ch=r.get("origin_account") or r.get("source")
        if channels[ch]<5 and len(selected)<30: selected.append(r); channels[ch]+=1
    for message_id in (2083,28169,28316,28640,31010):
        if by_id[message_id] not in selected: selected.append(by_id[message_id])
    families=defaultdict(list)
    for r in rows: families[normalize_summary_text(r["text"]).text].append(r["message_id"])
    unique={normalize_summary_text(by_id[x]["text"]).text:by_id[x] for x in (2083,28169,28316,28640,31010)}
    for r in selected: unique.setdefault(normalize_summary_text(r["text"]).text,r)
    pending=ROOT/"pending"; pending.mkdir(parents=True,exist_ok=True)
    for old in pending.glob("*.json"): old.unlink()
    index={r["message_id"]:i for i,r in enumerate(rows)}
    for key,r in unique.items():
        if r["message_id"]==40279: continue
        i=index[r["message_id"]]; a=current[i]; b=proposed[i]; window=resolve_window(r["text"],datetime.fromisoformat(r["message_datetime"]))
        badge="auto_acceptable" if a.auto_acceptable else "blocked by aliases" if b.auto_acceptable else "blocked by parser"
        payload={"message_id":r["message_id"],"siblings":[x for x in families[key] if x!=r["message_id"]],"channel":r.get("origin_account"),"raw_text":r["text"],"posted_at":r["message_datetime"],"badge":badge,"expected":{"window":{"start":window.start.isoformat(),"end":window.end.isoformat(),"rule":window.rule,"note":window.note},"items":[simple_item(x) for x in a.items],"residual":[{"kind":x.kind,"text":x.text,"section_header":x.section_header,"offsets":list(x.offsets)} for x in a.residual],"disposition":a.disposition,"leftover_tokens":list(a.leftover_tokens),"out_of_scope_lines":list(a.out_of_scope_lines),"auto_acceptable":a.auto_acceptable},"reviewer_notes":""}
        (pending/f"{r['message_id']}.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")

    n=len(rows); cur=sum(x.auto_acceptable for x in current); simok=sum(x.auto_acceptable for x in proposed)
    def count(kind,values): return sum(x.disposition==kind for x in values)
    def candidates(values): return sum(len(x.items)+len(x.residual) for x in values)
    def places(values): return sum(any(x.kind in {'unresolved_place','ambiguous_place'} for x in r.residual) for r in values)
    times=sum(1 for r in current for x in r.items if x.event_time)
    sizes=sorted(len(x.residual) for x in current); median=sizes[len(sizes)//2]; p90=sizes[min(len(sizes)-1,int(len(sizes)*.9))]
    report=["# Step 1e parser coverage","","| metric | current DB | aliases simulated |","|---|---:|---:|",f"| bulletins complete | {count('complete',current)} | {count('complete',proposed)} |",f"| bulletins partial | {count('partial',current)} | {count('partial',proposed)} |",f"| bulletins residual_only | {count('residual_only',current)} | {count('residual_only',proposed)} |",f"| **resolved items / all item candidates** | {sum(len(x.items) for x in current)}/{candidates(current)} | {sum(len(x.items) for x in proposed)}/{candidates(proposed)} |",f"| residual entries total, by kind | {sum(residuals.values())}: {dict(residuals)} | {sum(len(x.residual) for x in proposed)} |",f"| residual entries per bulletin (median, p90) | {median}, {p90} | — |",f"| timeline events with exact time | {times} | {sum(1 for r in proposed for x in r.items if x.event_time)} |","",f"- S4 workload: {places(current)} bulletins have a place-like residual under an approved header.","","## Top residual texts by kind",""]
    report += [f"- `{kind}` / `{text}`: {count}" for (kind,text),count in residual_texts.most_common(20)]
    report += ["","## Remaining blockers by class",""]
    report += [f"- {k}: {v}" for k,v in blockers.most_common()]+["","## Window rules",""]+[f"- {k}: {v}" for k,v in rules.most_common()]
    for title,data in (("Top leftover tokens",leftovers),("Top unresolved places",unresolved_places),("Unresolved headers",unresolved_headers)):
        report += ["",f"## {title}",""]+[f"- `{k}`: {v}" for k,v in data.most_common(30)]
    # Real invariant counts: each check recomputes header-like lines from the text.
    violations={"header provenance":{},"residual header":{},"secondary != primary":{}}
    for r,result in zip(rows,current):
        found={"header provenance":invariants.header_provenance_violations(r["text"],result,gaz,headers),"residual header":invariants.residual_header_violations(r["text"],result,gaz,headers),"secondary != primary":invariants.secondary_violations(result)}
        for name,values in found.items():
            if values: violations[name][r["message_id"]]=values[0]
    report += ["","## Invariant violations","",f"Checked over {len(rows)} bulletins."]
    report += [f"- {name}: {len(bad)}"+(f" (message ids: {sorted(bad)})" if bad else "") for name,bad in violations.items()]
    Path("recon_output/step1_parser_coverage.md").write_text("\n".join(report)+"\n",encoding="utf-8")

if __name__=="__main__": main()
