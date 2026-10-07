from __future__ import annotations

import hashlib
import re
from dataclasses import replace
from datetime import date, datetime, time
from typing import Iterable
from zoneinfo import ZoneInfo

from .dtos import EvidenceSpan, HeaderEntry, HeaderSpan, ParseResult, ParsedSection, ParsedSummaryItem, SummaryResidual, VillageRef
from .gazetteer import GazetteerSnapshot
from .headers import HeaderDictionarySnapshot
from .normalize import normalize_summary_text, normalize_token

_ACTION = re.compile(r"غار|غارات|قصف|تفجير|قنابل|تمشيط|غالونات|طيران|مسير|فوسفور|مدفعي")
_COUNT = re.compile(r"(?:\(\s*(\d+)\s*\)|[×x]\s*(\d+)|(\d+)\s+غارات|غارتين|بقذيفتين|بقذيفه|بثلاث\s+قذائف)")
_BETWEEN = re.compile(r"^بين\s+(.+?)\s*(?:\s+و\s*|\s*[-–—]\s*)(.+)$")
_DASH = re.compile(r"^(.+?)\s*[-–—]\s*(.+)$")
_CONJ = re.compile(r"^(.+?)\s+و\s*(.+)$")
_SUFFIX = re.compile(r"\s+(لجهه|جهه|عند|قرب|باتجاه)\s+(.+)$")
_PROSE_HEADER = re.compile(r"^(?:اعتداءات\s+اخري|التحركات\s+الاسرائيليه|تحركات\s+اليات\s+العدو|تحركات\s+واليات\s+العدو|الاعتداءات\s+والتحركات)$")
_TIMELINE = re.compile(r"^(?:الساعه\s+)?(\d{1,2})[:٫](\d{1,2})\s*(صباحا|فجرا|ظهرا|عصرا|مساء|ليلا)?\s+(.+)$")
BEIRUT = ZoneInfo("Asia/Beirut")


def _preclean_text(text: str, gazetteer: GazetteerSnapshot, headers: HeaderDictionarySnapshot) -> str:
    """Remove true tail signatures/URLs before normalization, preserving syntax."""
    text=re.sub(r"(?:https?://|(?:www\.|t\.me/))\S+", " ", text, flags=re.I)
    def guillemet(match: re.Match[str]) -> str:
        before=text[max(0,match.start()-32):match.start()]
        content=match.group(0)[1:-1]
        after=text[match.end():]
        at_tail=not after.strip() or not after.split("\n",1)[0].strip()
        header_context=headers.match_grammar(before.rsplit("\n",1)[-1].strip()+" "+content)
        if at_tail and not gazetteer.lookup(content) and not header_context:
            return " "*len(match.group(0))
        return match.group(0)
    return re.sub(r"«.*?»",guillemet,text,flags=re.S)


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


def _timeline_parts(line: str, gazetteer: GazetteerSnapshot, headers: HeaderDictionarySnapshot,
                    anchor_date: date | None):
    hit=_TIMELINE.match(normalize_token(line))
    if not hit or anchor_date is None: return None
    hour,minute=int(hit.group(1)),int(hit.group(2)); period=hit.group(3) or ""
    if period in {"عصرا","مساء"} and hour<12: hour+=12
    if period in {"صباحا","فجرا"} and hour==12: hour=0
    body=re.sub(r"[-–—]", " ", hit.group(4))
    body=re.sub(r"^(?:للمره\s+(?:الثالثه|الرابعه)\s+)?", "", body)
    body=body.replace(" جديد "," ")
    origin=None
    origin_hit=re.search(r"\s+من\s+(.+?)\s+(?=باتجاه|نحو|استهدف|علي|في)",body)
    if origin_hit:
        origin=origin_hit.group(1).strip(); body=(body[:origin_hit.start()]+" "+body[origin_hit.end():]).strip()
    places,unused=_dp_places(body,gazetteer)
    if not places: return None
    target=places[-1]
    leftovers=[u for u in unused if normalize_token(u) not in {"في","علي","باتجاه","نحو","بلده","مدينه","استهدف","طال"}]
    qualifiers=[]
    qualifier_words={"وسط","البلده","جامع","الحي","الرابع","المشاع"}
    action_words=[u for u in leftovers if normalize_token(u) not in qualifier_words]
    qualifiers=[normalize_token(u) for u in leftovers if normalize_token(u) in qualifier_words]
    action=headers.match_grammar(" ".join(action_words))
    if not action: return None
    event=datetime.combine(anchor_date,time(hour%24,minute),BEIRUT)
    return action.condition_ids,target,tuple(qualifiers),origin,event


def _inline_parts(line: str, gazetteer: GazetteerSnapshot, headers: HeaderDictionarySnapshot):
    places,unused=_dp_places(normalize_token(line),gazetteer)
    action=headers.match_grammar(" ".join(unused)) if places else None
    return (action.condition_ids,places[-1]) if action else None


_SECTION_BULLETS=frozenset("●-🟠🔵🏴○")
_SKIPPED_BEFORE_LINE=re.compile(r"[\s‎‏؜‪-‮️]*$")


def _has_section_bullet(normalized, index: int) -> bool:
    """Normalization drops bullet glyphs, so read them back from the original text."""
    if index>=len(normalized.offsets): return False
    original=normalized.original
    head=original[:normalized.offsets[index]]
    head=head[:_SKIPPED_BEFORE_LINE.search(head).start()]
    return bool(head) and head[-1] in _SECTION_BULLETS


def _has_place(line: str, gazetteer: GazetteerSnapshot) -> bool:
    # Glued tokens such as "المنصوري-وسط" or "كفرشوبا(قذائف)" still name a place.
    return bool(_dp_places(re.sub(r"[()\-–—+×،,/]"," ",normalize_token(line)),gazetteer)[0])


def is_header_like(line: str, bulleted: bool, gazetteer: GazetteerSnapshot, headers: HeaderDictionarySnapshot) -> bool:
    """The Step 1e header barrier: a line that starts a section, resolved or not."""
    raw=line.strip()
    clean=normalize_token(raw.rstrip(":"))
    if not clean or clean.startswith("ملخص "): return False
    if raw.endswith(":"): return True
    if _TIMELINE.match(clean): return False  # a timed event line carries its own action
    if _has_place(clean,gazetteer): return False
    if (bulleted or raw.startswith("-")) and len(clean.split())<=6: return True
    return headers.has_action_core(clean)


def parse_summary(text: str, gazetteer: GazetteerSnapshot, headers: HeaderDictionarySnapshot,
                  lexicon: dict, anchor_date: date | None = None) -> ParseResult:
    """Parse summaries without loss: resolved items reconcile; residual is for S4/review."""
    text=_preclean_text(text,gazetteer,headers)
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
        elif before and flat[colon.end():].split("\n",1)[0].strip():
            # "unknown header: place" on one line (the bare-colon line case is
            # handled per line below): the segment before the colon is an
            # unresolved header when it would be header-like as a line.
            start=boundary + len(raw_before) - len(raw_before.lstrip())
            if not before.rstrip()[-1].isdigit() and is_header_like(before,_has_section_bullet(normalized,start),gazetteer,headers):
                header_hits.append((start,colon.end(),HeaderEntry(normalize_token(before),(),"unresolved","header barrier"),normalize_token(before)))
    offset=0
    for line in flat.splitlines(keepends=True):
        candidate=normalize_token(line.rstrip("\n:"))
        entry,_=headers.resolve(candidate)
        already=any(start==offset for start,_,_,_ in header_hits)
        if already:
            pass
        elif entry and candidate:
            header_hits.append((offset,offset+len(line),entry,candidate))
        elif _PROSE_HEADER.match(candidate):
            header_hits.append((offset,offset+len(line),HeaderEntry(candidate,(),"prose","section-level prose"),candidate))
        elif is_header_like(line,_has_section_bullet(normalized,offset),gazetteer,headers):
            header_hits.append((offset,offset+len(line),HeaderEntry(candidate,(),"unresolved","header barrier"),candidate))
        offset+=len(line)
    # Prefer the longest dictionary match at a shared colon, then remove overlaps.
    chosen=[]
    for item in sorted(header_hits,key=lambda x:(x[1],-(x[1]-x[0]))):
        if chosen and item[1]==chosen[-1][1]: continue
        chosen.append(item)
    chosen.sort()
    contextual_residuals: list[tuple[str,str,str]]=[]
    unresolved_headers=[]
    for hit in re.finditer(r"([^:\n]{2,100}):",flat):
        candidate=hit.group(1).strip()
        if _ACTION.search(candidate) and not any(a<=hit.start()<b or hit.end()==b for a,b,_,_ in chosen):
            unresolved_headers.append(candidate)
    header_spans_orig=[(normalized.original_span(a,b),entry,candidate) for a,b,entry,candidate in chosen]
    sections=[]; raw_items=[]; leftovers=[]; unresolved_places=[]; ambiguous=[]; prose=[]
    qualifiers_set={normalize_token(x) for x in lexicon.get("qualifiers",[])}
    noise={normalize_token(x) for x in lexicon.get("noise",[])}
    cursor=0
    def standalone(original_line: str, line_start: int, line_end: int) -> bool:
        """Parse a self-contained action/place line; True when items were created.

        The condition comes from the line itself, so nothing is inherited from a
        header: this is safe in header-less bulletins and under unresolved headers.
        """
        evidence=normalized.original_span(line_start,line_end)
        timeline=_timeline_parts(original_line,gazetteer,headers,anchor_date)
        if timeline:
            conditions,primary,timeline_quals,origin,event_time=timeline
            for condition_id in conditions:
                key_material=f"{condition_id}|{primary.id}|{event_time.isoformat()}"
                raw_items.append(ParsedSummaryItem(condition_id,primary,None,timeline_quals,primary.place_detail,1,(original_line,),(evidence,),"timeline",hashlib.sha256(key_material.encode()).hexdigest(),event_time,origin,header_spans=(None,),condition_source="timeline"))
            return True
        line=original_line.replace("«", "").replace("»", "").strip()
        line,count=_count(line)
        embedded=re.search(r"(?:^|\s)بين\s+(.+?)\s+و\s*(.+)$",line)
        if embedded:
            inline=headers.match_grammar(line[:embedded.start()].strip())
            left,_=_resolve(gazetteer,embedded.group(1).strip())
            right,_=_resolve(gazetteer,embedded.group(2).strip())
            if inline and left and right:
                for condition_id in inline.condition_ids:
                    key_material=f"{condition_id}|{left.id}|"
                    raw_items.append(ParsedSummaryItem(condition_id,left,right,(),left.place_detail,count,(original_line,),(evidence,),inline.normalized_header,hashlib.sha256(key_material.encode()).hexdigest(),header_spans=(None,),condition_source="inline"))
                return True
        places,unused=_dp_places(line,gazetteer)
        significant=[u for u in unused if normalize_token(u) not in noise]
        inline=headers.match_grammar(" ".join(significant)) if places and significant else None
        if not inline: return False
        for primary in places:
            for condition_id in inline.condition_ids:
                key_material=f"{condition_id}|{primary.id}|"
                raw_items.append(ParsedSummaryItem(condition_id,primary,None,(),primary.place_detail,count,(original_line,),(evidence,),inline.normalized_header,hashlib.sha256(key_material.encode()).hexdigest(),header_spans=(None,),condition_source="inline"))
        return True
    # Lines above the first header, or the whole text when it has none, can only
    # be self-contained action/place lines: accept those whose non-place tokens
    # are a complete header-grammar expression; anything else is residual.
    for line_match in re.finditer(r"[^\n]+",flat[:chosen[0][0] if chosen else len(flat)]):
        original_line=line_match.group(0).strip()
        if not original_line: continue
        line_start=line_match.start()+len(line_match.group(0))-len(line_match.group(0).lstrip()); line_end=line_start+len(original_line)
        if "ملخص" in original_line and "اعتداءات" in original_line: continue
        if standalone(original_line,line_start,line_end): continue
        # Above a header a line with neither a place nor an action (a channel
        # signature, a greeting) could never become an item, so it is not review work.
        if chosen and not _has_place(original_line,gazetteer) and not headers.has_action_core(original_line): continue
        if len(original_line.split())>=4: prose.append(original_line)
        else: unresolved_places.append(original_line)
    for index,(start,end,entry,candidate) in enumerate(chosen):
        stop=chosen[index+1][0] if index+1<len(chosen) else len(flat)
        location_block=flat[end:stop].strip()
        header_span=(header_spans_orig[index][0].start,header_spans_orig[index][0].end)
        if entry.status == "prose":
            for prose_line in (p.strip() for p in re.split(r"[\n،,؛;]+",location_block) if p.strip()):
                parsed=_timeline_parts(prose_line,gazetteer,headers,anchor_date)
                if parsed:
                    conditions,primary,timeline_quals,origin,event_time=parsed
                    evidence,cursor=_span(normalized,prose_line,cursor)
                    for condition_id in conditions:
                        key_material=f"{condition_id}|{primary.id}|{event_time.isoformat()}"
                        raw_items.append(ParsedSummaryItem(condition_id,primary,None,timeline_quals,primary.place_detail,1,(prose_line,),(evidence,),"timeline",hashlib.sha256(key_material.encode()).hexdigest(),event_time,origin,header_spans=(header_span,),condition_source="timeline"))
                else:
                    inline=_inline_parts(prose_line,gazetteer,headers)
                    if inline:
                        conditions,primary=inline; evidence,cursor=_span(normalized,prose_line,cursor)
                        for condition_id in conditions:
                            key_material=f"{condition_id}|{primary.id}|"
                            raw_items.append(ParsedSummaryItem(condition_id,primary,None,(),primary.place_detail,1,(prose_line,),(evidence,),"inline prose",hashlib.sha256(key_material.encode()).hexdigest(),header_spans=(header_span,),condition_source="inline"))
                    else: prose.append(prose_line)
            continue
        if entry.status != "approved":
            blocked=0
            for line_match in re.finditer(r"[^\n]+",flat[end:stop]):
                line=line_match.group(0).strip()
                if line and not line.startswith("ملخص "):  # title lines carry no place
                    line_start=end+line_match.start()+len(line_match.group(0))-len(line_match.group(0).lstrip())
                    # A line that names its own action takes nothing from the header.
                    if not standalone(line,line_start,line_start+len(line)):
                        contextual_residuals.append(("place_under_unresolved_header",line,candidate)); blocked+=1
            # A barrier that blocks nothing (a channel signature, a footer) is not worth a review row.
            if blocked or entry.note!="header barrier" or _ACTION.search(candidate):
                unresolved_headers.append(candidate)
            continue
        section=ParsedSection(candidate,entry.condition_ids,location_block); sections.append(section)
        block_raw=flat[end:stop]
        parts=[]
        for piece in re.finditer(r"[^\n،,؛;/]+",block_raw):
            text_piece=piece.group(0).strip(" .:؛;,\n")
            if text_piece: parts.append((text_piece,end+piece.start()+len(piece.group(0))-len(piece.group(0).lstrip(" .:؛;,\n"))))
        if not parts and location_block: parts=[(location_block,end+len(block_raw)-len(block_raw.lstrip()))]
        for original_part,part_start in parts:
            part_end=part_start+len(original_part)
            item_conditions=entry.condition_ids; condition_source="header"
            timeline=_timeline_parts(original_part,gazetteer,headers,anchor_date)
            if timeline:
                conditions,primary,timeline_quals,origin,event_time=timeline
                evidence=normalized.original_span(part_start,part_end)
                for condition_id in conditions:
                    key_material=f"{condition_id}|{primary.id}|{event_time.isoformat()}"
                    raw_items.append(ParsedSummaryItem(condition_id,primary,None,timeline_quals,primary.place_detail,1,(original_part,),(evidence,),"timeline",hashlib.sha256(key_material.encode()).hexdigest(),event_time,origin,header_spans=(header_span,),condition_source="timeline"))
                continue
            part=original_part.replace("«", "").replace("»", "").strip()
            for phrase in lexicon.get("noise_phrases",[]):
                part=part.replace(normalize_token(phrase)," ")
            part=re.sub(r"[^\u0600-\u06ffA-Za-z0-9\s()×x+\-–—]", " ", part)
            part=re.sub(r"^\s*[-–—]+\s*", "", part).strip(" .،؛;:")
            plus_form=part; part=part.replace("+", " ")
            part,count=_count(part)
            parenthetical=re.search(r"\(([^()]*)\)\s*$",part)
            quals=[]
            if parenthetical:
                override=headers.match_grammar(parenthetical.group(1))
                if override: item_conditions=override.condition_ids; condition_source="parenthetical"
                else: quals.append(normalize_token(parenthetical.group(1)))
                part=part[:parenthetical.start()].strip()
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
                        if inline: item_conditions=inline.condition_ids; condition_source="inline"
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
                    pairs=[(p,None) for p in places]
                    # "place+فوسفوري": an action tacked on with "+" and nothing before
                    # it adds to the header's conditions; a full inline action
                    # ("place مدفعي+فوسفوري") replaces them.
                    lead_places,lead_unused=_dp_places(plus_form.split("+")[0],gazetteer)
                    lead_action=headers.match_grammar(" ".join(u for u in lead_unused if normalize_token(u) not in noise))
                    additive="+" in plus_form and bool(lead_places) and lead_action is None
                    item_conditions=tuple(dict.fromkeys((*entry.condition_ids,*inline.condition_ids))) if additive else inline.condition_ids
                    condition_source="header+inline" if additive else "inline"
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
            evidence=normalized.original_span(part_start,part_end)
            for primary,secondary in pairs:
                for condition_id in item_conditions:
                    key_material=f"{condition_id}|{primary.id}|{'|'.join(sorted(quals))}"
                    raw_items.append(ParsedSummaryItem(condition_id,primary,secondary,tuple(quals),primary.place_detail,count,(original_part,),(evidence,),candidate,hashlib.sha256(key_material.encode()).hexdigest(),header_spans=(header_span,),condition_source=condition_source))
    merged={}
    for item in raw_items:
        k=(item.condition_id,item.primary_village.id,item.event_time)
        if k not in merged: merged[k]=item; continue
        old=merged[k]
        quals=list(dict.fromkeys(old.qualifiers+item.qualifiers))
        secondary=old.secondary_village or item.secondary_village
        if old.secondary_village and item.secondary_village and old.secondary_village.id!=item.secondary_village.id:
            quals.append(f"secondary:{item.secondary_village.name_ar}")
        key_material=f"{item.condition_id}|{item.primary_village.id}|{'|'.join(sorted(quals))}"
        merged[k]=replace(old,secondary_village=secondary,qualifiers=tuple(quals),reported_count=max(old.reported_count,item.reported_count),location_texts=tuple(dict.fromkeys(old.location_texts+item.location_texts)),evidence_spans=old.evidence_spans+item.evidence_spans,header_spans=old.header_spans+item.header_spans,item_key=hashlib.sha256(key_material.encode()).hexdigest())
    residual=[]
    header_table=[(span.start,span.end,candidate,entry.status) for span,entry,candidate in header_spans_orig]
    section_header=sections[-1].header_text if sections else None
    for kind,values in (("leftover_token",leftovers),("unresolved_header",unresolved_headers),("unresolved_place",unresolved_places),("ambiguous_place",ambiguous),("out_of_scope",prose)):
        for value in dict.fromkeys(values):
            span,_=_span(normalized,value,0)
            residual.append(SummaryResidual(kind,value,section_header,(span.start,span.end)))
    for kind,value,header in contextual_residuals:
        span,_=_span(normalized,value,0)
        residual.append(SummaryResidual(kind,value,header,(span.start,span.end)))
    disposition="complete" if merged and not residual else "partial" if merged else "residual_only"
    header_result=tuple(HeaderSpan(text,start,end,status) for start,end,text,status in header_table)
    return ParseResult(tuple(sections),tuple(merged.values()),tuple(leftovers),tuple(dict.fromkeys(unresolved_headers)),tuple(dict.fromkeys(unresolved_places)),tuple(dict.fromkeys(ambiguous)),tuple(dict.fromkeys(prose)),disposition=="complete",tuple(residual),disposition,header_result)
