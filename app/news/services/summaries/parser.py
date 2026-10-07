from __future__ import annotations

import hashlib
import re
from dataclasses import replace
from typing import Iterable

from .dtos import EvidenceSpan, HeaderEntry, ParseResult, ParsedSection, ParsedSummaryItem, VillageRef
from .gazetteer import GazetteerSnapshot
from .headers import HeaderDictionarySnapshot
from .normalize import normalize_summary_text, normalize_token

_ACTION = re.compile(r"غار|غارات|قصف|تفجير|قنابل|تمشيط|غالونات|طيران|مسير|فوسفور|مدفعي")
_COUNT = re.compile(r"(?:\(\s*(\d+)\s*\)|[×x]\s*(\d+)|(\d+)\s+غارات|غارتين|بقذيفتين|بقذيفه|بثلاث\s+قذائف)")
_BETWEEN = re.compile(r"^بين\s+(.+?)\s*(?:\s+و\s*|\s*[-–—]\s*)(.+)$")
_DASH = re.compile(r"^(.+?)\s*[-–—]\s*(.+)$")
_CONJ = re.compile(r"^(.+?)\s+و\s*(.+)$")
_SUFFIX = re.compile(r"\s+(لجهه|جهه|عند|قرب|باتجاه)\s+(.+)$")
_PROSE_HEADER = re.compile(r"^(?:اعتداءات\s+اخري|التحركات\s+الاسرائيليه)$")


def _resolve(gazetteer: GazetteerSnapshot, value: str) -> tuple[VillageRef | None, bool]:
    hits = gazetteer.lookup(value)
    return (hits[0], False) if len(hits) == 1 else (None, len(hits) > 1)


def _count(value: str) -> tuple[str, int]:
    hit = _COUNT.search(value)
    if not hit: return value, 1
    fixed = {"غارتين":2,"بقذيفتين":2,"بقذيفه":1,"بثلاث قذائف":3}
    number = fixed.get(hit.group(0), int(next((x for x in hit.groups() if x), "1")))
    return (value[:hit.start()] + value[hit.end():]).strip(), number


def _dp_places(value: str, gazetteer: GazetteerSnapshot) -> tuple[list[VillageRef], list[str]]:
    words = value.split(); n = len(words)
    best: list[tuple[int,int,list[VillageRef],list[str]] | None] = [None]*(n+1)
    best[n] = (0, 0, [], [])
    for i in range(n-1,-1,-1):
        tail = best[i+1]; assert tail
        options = [(tail[0], tail[1], tail[2], [words[i]]+tail[3])]
        for size in range(1, min(gazetteer.max_tokens,n-i)+1):
            hits = gazetteer.lookup(" ".join(words[i:i+size]))
            if len(hits)==1 and best[i+size]:
                b=best[i+size]; assert b
                options.append((b[0]+size,b[1]-1,[hits[0]]+b[2],b[3]))
        best[i]=max(options,key=lambda x:(x[0],x[1]))
    result=best[0]; assert result
    return result[2], result[3]


def _span(normalized, phrase: str, search_start: int) -> tuple[EvidenceSpan, int]:
    needle = normalize_summary_text(phrase).text.strip()
    pos = normalized.text.find(needle, search_start)
    if pos < 0: pos = normalized.text.find(needle)
    if pos < 0: return EvidenceSpan(0,0,phrase), search_start
    return normalized.original_span(pos,pos+len(needle)), pos+len(needle)


def parse_summary(text: str, gazetteer: GazetteerSnapshot, headers: HeaderDictionarySnapshot,
                  lexicon: dict) -> ParseResult:
    normalized = normalize_summary_text(text)
    flat = normalized.text
    header_hits: list[tuple[int,int,object,str]]=[]
    for entry in headers.entries:
        key=normalize_token(entry.normalized_header)
        pattern=re.compile(rf"(?<![\u0600-\u06ff]){re.escape(key)}(?:\s+[^:\n]{{0,90}})?\s*:")
        for hit in pattern.finditer(flat):
            candidate=flat[hit.start():hit.end()-1].strip()
            matched,note=headers.resolve(candidate)
            if matched and normalize_token(matched.normalized_header)==key:
                header_hits.append((hit.start(),hit.end(),matched,candidate))
    for colon in re.finditer(":", flat):
        boundary=max(flat.rfind("\n",0,colon.start()),flat.rfind(":",0,colon.start()))+1
        raw_before=flat[boundary:colon.start()]
        before=raw_before.strip()
        suffix=headers.suffix_match(before)
        if suffix:
            offset,entry,candidate=suffix
            absolute=boundary + len(raw_before) - len(raw_before.lstrip()) + offset
            header_hits.append((absolute,colon.end(),entry,candidate))
        elif _PROSE_HEADER.match(normalize_token(before)):
            entry=HeaderEntry(normalize_token(before),(),"prose","section-level prose")
            header_hits.append((boundary,colon.end(),entry,before))
    # Prefer the longest dictionary match at a shared colon, then remove overlaps.
    chosen=[]
    for item in sorted(header_hits,key=lambda x:(x[1],-(x[1]-x[0]))):
        if chosen and item[1]==chosen[-1][1]: continue
        chosen.append(item)
    chosen.sort()
    unresolved_headers=[]
    for hit in re.finditer(r"([^:\n]{2,100}):",flat):
        candidate=hit.group(1).strip()
        if _ACTION.search(candidate) and not any(a<=hit.start()<b or hit.end()==b for a,b,_,_ in chosen):
            unresolved_headers.append(candidate)
    sections=[]; raw_items=[]; leftovers=[]; unresolved_places=[]; ambiguous=[]; prose=[]
    qualifiers_set={normalize_token(x) for x in lexicon.get("qualifiers",[])}
    noise={normalize_token(x) for x in lexicon.get("noise",[])}
    cursor=0
    for index,(start,end,entry,candidate) in enumerate(chosen):
        stop=chosen[index+1][0] if index+1<len(chosen) else len(flat)
        location_block=flat[end:stop].strip()
        if entry.status == "prose":
            prose.extend(p.strip() for p in re.split(r"[\n،,؛;]+",location_block) if p.strip())
            continue
        if entry.status != "approved":
            unresolved_headers.append(candidate); continue
        section=ParsedSection(candidate,entry.condition_ids,location_block); sections.append(section)
        parts=[p.strip(" .:؛;,\n") for p in re.split(r"[\n،,؛;]+",location_block) if p.strip(" .:؛;,\n")]
        if not parts and location_block: parts=[location_block]
        for original_part in parts:
            item_conditions=entry.condition_ids
            part=re.sub(r"https?://\S+|(?:www\.)?t\.me/\S+", "", original_part, flags=re.I)
            part=re.sub(r"«[^»]{1,40}»\s*$", "", part).strip()
            for phrase in lexicon.get("noise_phrases",[]):
                part=part.replace(normalize_token(phrase)," ")
            part=re.sub(r"[^\u0600-\u06ffA-Za-z0-9\s()×x+\-–—]", " ", part)
            part,count=_count(part); quals=[]
            direct,direct_ambiguous=_resolve(gazetteer,part)
            pairs=[(direct,None)] if direct else []
            tokens=part.split()
            while not pairs and len(tokens)>1:
                one=normalize_token(tokens[0]); two=normalize_token(" ".join(tokens[:2]))
                descriptor=two if two in qualifiers_set else one if one in qualifiers_set else None
                if descriptor is None: break
                quals.append(descriptor); del tokens[:len(descriptor.split())]
            part=" ".join(tokens)
            suffix=_SUFFIX.search(part)
            if suffix:
                quals.append(suffix.group(0).strip()); part=part[:suffix.start()].strip()
            between=_BETWEEN.match(part)
            if not between:
                embedded=re.search(r"(?:^|\s)بين\s+(.+?)\s+و\s*(.+)$",part)
                if embedded:
                    prefix=part[:embedded.start()].strip()
                    inline=headers.match_grammar(prefix) if prefix else None
                    if not prefix or inline:
                        between=embedded
                        if inline: item_conditions=inline.condition_ids
                    else:
                        prose.append(original_part)
                        continue
            dash=_DASH.match(part) if not between else None
            conjunction=_CONJ.match(part) if not between and not dash else None
            pair=between or dash or conjunction
            if pair:
                left,right=pair.group(1).strip(),pair.group(2).strip()
                lv,la=_resolve(gazetteer,left); rv,ra=_resolve(gazetteer,right)
                if lv and rv:
                    pairs=[(lv,rv if between or dash else None)] if between or dash else [(lv,None),(rv,None)]
                elif la or ra: ambiguous.append(original_part)
            if not pairs:
                whole,is_ambiguous=_resolve(gazetteer,part)
                if whole: pairs=[(whole,None)]
                elif is_ambiguous: ambiguous.append(original_part)
            if not pairs:
                places,unused=_dp_places(part,gazetteer)
                significant_unused=[u for u in unused if normalize_token(u) not in noise]
                inline=headers.match_grammar(" ".join(significant_unused)) if significant_unused else None
                if places and inline:
                    pairs=[(p,None) for p in places]; item_conditions=inline.condition_ids
                elif places and not significant_unused: pairs=[(p,None) for p in places]
                elif places:
                    if len(significant_unused)>=4: prose.append(original_part)
                    else:
                        pairs=[(p,None) for p in places]; leftovers.extend(significant_unused)
                else:
                    significant=[u for u in part.split() if normalize_token(u) not in noise]
                    if len(significant)>=4: prose.append(original_part)
                    elif significant:
                        unresolved_places.append(original_part); leftovers.extend(significant)
            evidence,cursor=_span(normalized,original_part,cursor)
            for primary,secondary in pairs:
                for condition_id in item_conditions:
                    key_material=f"{condition_id}|{primary.id}|{'|'.join(sorted(quals))}"
                    raw_items.append(ParsedSummaryItem(condition_id,primary,secondary,tuple(quals),primary.place_detail,count,(original_part,),(evidence,),candidate,hashlib.sha256(key_material.encode()).hexdigest()))
    # A summary may consist entirely of self-contained action/place lines, without
    # section headers. Accept only lines whose non-place tokens are a complete
    # header-grammar expression; anything else remains fail-closed.
    if not chosen:
        for original_line in (x.strip() for x in flat.splitlines() if x.strip()):
            line=re.sub(r"https?://\S+|(?:www\.)?t\.me/\S+", "", original_line, flags=re.I)
            line=re.sub(r"«[^»]{1,40}»\s*$", "", line).strip()
            line,count=_count(line)
            embedded=re.search(r"(?:^|\s)بين\s+(.+?)\s+و\s*(.+)$",line)
            if embedded:
                inline=headers.match_grammar(line[:embedded.start()].strip())
                left,_=_resolve(gazetteer,embedded.group(1).strip())
                right,_=_resolve(gazetteer,embedded.group(2).strip())
                if inline and left and right:
                    evidence,cursor=_span(normalized,original_line,cursor)
                    for condition_id in inline.condition_ids:
                        key_material=f"{condition_id}|{left.id}|"
                        raw_items.append(ParsedSummaryItem(condition_id,left,right,(),left.place_detail,count,(original_line,),(evidence,),inline.normalized_header,hashlib.sha256(key_material.encode()).hexdigest()))
                    continue
            places,unused=_dp_places(line,gazetteer)
            significant=[u for u in unused if normalize_token(u) not in noise]
            inline=headers.match_grammar(" ".join(significant)) if places and significant else None
            if not inline:
                if len(line.split())>=4: prose.append(original_line)
                elif line: unresolved_places.append(original_line)
                continue
            evidence,cursor=_span(normalized,original_line,cursor)
            for primary in places:
                for condition_id in inline.condition_ids:
                    key_material=f"{condition_id}|{primary.id}|"
                    raw_items.append(ParsedSummaryItem(condition_id,primary,None,(),primary.place_detail,count,(original_line,),(evidence,),inline.normalized_header,hashlib.sha256(key_material.encode()).hexdigest()))
    merged={}
    for item in raw_items:
        k=(item.condition_id,item.primary_village.id)
        if k not in merged: merged[k]=item; continue
        old=merged[k]
        quals=list(dict.fromkeys(old.qualifiers+item.qualifiers))
        secondary=old.secondary_village or item.secondary_village
        if old.secondary_village and item.secondary_village and old.secondary_village.id!=item.secondary_village.id:
            quals.append(f"secondary:{item.secondary_village.name_ar}")
        key_material=f"{item.condition_id}|{item.primary_village.id}|{'|'.join(sorted(quals))}"
        merged[k]=replace(old,secondary_village=secondary,qualifiers=tuple(quals),reported_count=max(old.reported_count,item.reported_count),location_texts=tuple(dict.fromkeys(old.location_texts+item.location_texts)),evidence_spans=old.evidence_spans+item.evidence_spans,item_key=hashlib.sha256(key_material.encode()).hexdigest())
    acceptable=not(any((leftovers,unresolved_headers,unresolved_places,ambiguous,prose))) and bool(merged)
    return ParseResult(tuple(sections),tuple(merged.values()),tuple(leftovers),tuple(dict.fromkeys(unresolved_headers)),tuple(dict.fromkeys(unresolved_places)),tuple(dict.fromkeys(ambiguous)),tuple(dict.fromkeys(prose)),acceptable)
