"""Build a self-contained, offline review sheet for pending fixtures."""
import json
from pathlib import Path


def main():
    cases=[]
    for path in sorted(Path("tests/fixtures/summaries/pending").glob("*.json")):
        case=json.loads(path.read_text(encoding="utf-8")); case["_file"]=path.name; cases.append(case)
    payload=json.dumps(cases,ensure_ascii=False).replace("</","<\\/")
    page="""<!doctype html><meta charset="utf-8"><title>Summary fixture review</title>
<style>body{font:14px sans-serif;max-width:1200px;margin:auto}article{border:1px solid #bbb;padding:1rem;margin:1rem}pre{white-space:pre-wrap;direction:rtl;text-align:right;background:#f7f7f7;padding:1rem}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ddd;padding:.4rem}textarea{width:100%}</style>
<h1>Pending summary fixtures</h1><button onclick="save()">Export corrections</button><div id="root"></div>
<script>const cases=__PAYLOAD__,root=document.getElementById('root');const esc=x=>String(x).replace(/[&<>]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[m]));
for(const c of cases){const a=document.createElement('article');a.dataset.file=c._file;const residual=(c.expected.residual||[]).map(x=>`<tr><td>${esc(x.kind)}</td><td>${esc(x.text)}</td><td>${esc(x.section_header||'')}</td><td>${esc((x.offsets||[]).join(':'))}</td></tr>`).join('');a.innerHTML=`<h2>${c.message_id} — ${esc(c.badge||'')}</h2><p>Disposition: ${esc(c.expected.disposition||'')} · Siblings: ${esc((c.siblings||[]).join(', '))}</p><pre>${esc(c.raw_text)}</pre><p>Window [${esc(c.expected.window.rule)}]: ${c.expected.window.start} → ${c.expected.window.end}</p><table><tr><th>Wrong</th><th>Condition</th><th>Primary</th><th>Secondary</th><th>Qualifiers</th><th>Count</th><th>Event time</th><th>Source header</th><th>Notes</th></tr>${c.expected.items.map((x,i)=>`<tr><td><input type=checkbox data-wrong="${i}"></td><td>${x.condition_id}</td><td>${esc(x.primary)}</td><td>${esc(x.secondary||'')}</td><td>${esc((x.qualifiers||[]).join(', '))}</td><td>${x.reported_count||1}</td><td>${esc(x.event_time||'')}</td><td>${esc(x.source_header||'')}${x.condition_source&&x.condition_source!=='header'?' ['+esc(x.condition_source)+']':''}</td><td><input data-note="${i}"></td></tr>`).join('')}</table><h3>Residual</h3><table><tr><th>Kind</th><th>Text</th><th>Header</th><th>Offsets</th></tr>${residual}</table><label>Missing items / fixture notes<textarea data-missing></textarea></label>`;root.appendChild(a)}
function save(){const out={};for(const a of document.querySelectorAll('article')){const wrong=[...a.querySelectorAll('[data-wrong]:checked')].map(x=>({index:+x.dataset.wrong,note:a.querySelector(`[data-note="${x.dataset.wrong}"]`).value}));out[a.dataset.file]={wrong,missing:a.querySelector('[data-missing]').value}}const b=new Blob([JSON.stringify(out,null,2)],{type:'application/json'}),u=URL.createObjectURL(b),x=document.createElement('a');x.href=u;x.download='fixture_corrections.json';x.click()}</script>""".replace("__PAYLOAD__",payload)
    Path("recon_output/fixture_review.html").write_text(page,encoding="utf-8")


if __name__=="__main__": main()
