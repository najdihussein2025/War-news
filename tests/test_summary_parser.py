import json, sys
from pathlib import Path
import yaml
from app.news.services.summaries.dtos import HeaderEntry, VillageRef
from app.news.services.summaries.gazetteer import GazetteerSnapshot
from app.news.services.summaries.headers import HeaderDictionarySnapshot, default_header_dictionary
from app.news.services.summaries.parser import parse_summary

LEX=yaml.safe_load(Path('app/core/llm_knowledge/terminology/summary_location_lexicon.yaml').read_text(encoding='utf-8'))
def gaz():
    names={n:[VillageRef(i,n,'Nabatiye',i*1000.0,0)] for i,n in enumerate(['الخيام','المنصوري','ميفدون','حداثا','حاريص','شقرا','كفرتبنيت','علي الطاهر','النبطية الفوقا'],1)}
    return GazetteerSnapshot(names,LEX['qualifiers'])
def parse(text,g=None,h=None): return parse_summary(text,g or gaz(),h or default_header_dictionary(),LEX)

def test_inline_multiple_headers_and_counts():
    p=parse('ملخص الاعتداءات: القصف المدفعي: الخيام المنصوري التفجيرات: ميفدون (٢) الخيام القنابل المضيئة: شقرا المنصوري')
    assert {i.condition_id for i in p.items}=={5,21,9} and any(i.reported_count==2 for i in p.items)
def test_between_attached_w_and_dash_are_one_item():
    a=parse('القصف المدفعي: بين حداثا وحاريص'); b=parse('القصف المدفعي: حداثا-حاريص')
    assert len(a.items)==len(b.items)==1 and a.items[0].secondary_village.name_ar=='حاريص'
def test_compound_header_two_items_per_place():
    p=parse('القصف المدفعي و الفوسفوري: الخيام')
    assert [i.condition_id for i in p.items]==[5,7]
def test_prefix_and_suffix_qualifiers():
    p=parse('القصف المدفعي: اطراف ميفدون، الخيام لجهة حاريص')
    assert 'اطراف' in p.items[0].qualifiers and any('لجهه' in q for q in p.items[1].qualifiers)
def test_dynamic_segmentation_and_conjunction():
    p=parse('القصف المدفعي: الخيام المنصوري ميفدون، حداثا و حاريص')
    assert {i.primary_village.name_ar for i in p.items}=={'الخيام','المنصوري','ميفدون','حداثا','حاريص'}
def test_ambiguous_and_out_of_scope_and_leftover():
    g=gaz(); g.names['عين']=(VillageRef(20,'عين','Sour'),VillageRef(21,'عين','Nabatiye'))
    p=parse_summary('القصف المدفعي: عين، كلمةغريبة\nتحركات واليات العدو في المنطقة الحدودية',g,default_header_dictionary(),LEX)
    assert p.ambiguous_places and p.leftover_tokens and not p.auto_acceptable
def test_out_of_south_absent():
    assert parse('القصف المدفعي: جبيل').unresolved_places==('جبيل',)
def test_d2_merge_and_deterministic_key():
    text='القصف المدفعي: ميفدون، اطراف ميفدون'
    a=parse(text); b=parse(text)
    assert len(a.items)==1 and len(a.items[0].location_texts)==2 and a.items[0].item_key==b.items[0].item_key

def test_header_grammar_fillers_and_compound_plus():
    p=parse('القصف المدفعي التي نفذها العدو في البلدات الجنوبيه: الخيام\nمدفعي+فوسفوري: المنصوري')
    assert {(i.condition_id,i.primary_village.name_ar) for i in p.items}=={(5,'الخيام'),(5,'المنصوري'),(7,'المنصوري')}

def test_d4_headers_are_now_approved():
    p=parse('غارات مسيره: الخيام\nغالونات متفجره: المنصوري\nقنابل لانشر: ميفدون\nالقنابل المتفجره: شقرا')
    assert {i.condition_id for i in p.items}=={46,21,13}

def test_unknown_header_extra_word_and_prose_stay_unresolved():
    p=parse('القصف المدفعي مفاجاه: الخيام\nباخلاء مبني عند اطراف البلده و قام بعد ذلك بتدميره: المنصوري')
    assert p.unresolved_headers and not p.auto_acceptable

def test_noise_signature_url_and_count_words():
    p=parse('القصف المدفعي: الخيام بقذيفتين، المنصوري بثلاث قذائف «كرار»، https://t.me/example')
    assert {(i.primary_village.name_ar,i.reported_count) for i in p.items}=={('الخيام',2),('المنصوري',3)}

def test_headerless_inline_action_line_and_prose_section():
    inline=parse('قصف مدفعي يستهدف المنصوري')
    assert [(i.condition_id,i.primary_village.name_ar) for i in inline.items]==[(5,'المنصوري')]
    prose=parse('القصف المدفعي: الخيام\nاعتداءات اخري: تقدم معاد من بلده حداثا باتجاه اطراف عيتا الجبل')
    assert prose.out_of_scope_lines and not prose.leftover_tokens

def test_embedded_between_is_parsed_only_with_action_grammar():
    good=parse('قصف مدفعي بين حداثا وحاريص')
    assert len(good.items)==1 and good.items[0].secondary_village.name_ar=='حاريص'
    narrative=parse('مواد حارقه بين حداثا وحاريص')
    assert narrative.out_of_scope_lines and not narrative.items

def test_no_fuzzy_matching_in_production_summary_package():
    forbidden=('similarity','difflib','rapidfuzz','levenshtein','word_similarity')
    source='\n'.join(path.read_text(encoding='utf-8').lower() for path in Path('app/news/services/summaries').glob('*.py'))
    assert not any(term in source for term in forbidden)

def test_real_27996_bullet_header_and_exact_places():
    p=parse('● غارات من الطيران الحربي:\n- حي الدير في بلدة النبطية الفوقا\n- مرتفع علي الطاهر')
    assert {i.condition_id for i in p.items}=={46}
    assert {i.primary_village.name_ar for i in p.items}=={'علي الطاهر','النبطية الفوقا'}

def test_split_decorative_signatures_are_noise():
    p=parse('القصف المدفعي:\nالخيام\n«جـھ,آد𓂆»\n«مـيّـثـمـ𓂆»')
    assert p.auto_acceptable and not p.leftover_tokens

def test_parenthetical_action_overrides_section_header():
    p=parse('القصف المدفعي:\nكفرتبنيت(قذائف دخانية)')
    assert [(i.condition_id,i.primary_village.name_ar) for i in p.items]==[(8,'كفرتبنيت')]

def test_timeline_target_time_origin_and_distinct_events():
    from datetime import date
    p=parse_summary('- الساعة ٦:٢٨ صباحاً تفجير في بلدة المنصوري\n- الساعة ٧:٤٨ صباحاً قصف مدفعي من البياضة باتجاه المنصوري\n- الساعة ١٠:٣٠ صباحاً قصف مدفعي استهدف المنصوري -المشاع',gaz(),default_header_dictionary(),LEX,date(2026,9,13))
    assert len(p.items)==3 and [i.event_time.hour for i in p.items]==[6,7,10]
    assert p.items[1].origin_text=='البياضه' and all(i.primary_village.name_ar=='المنصوري' for i in p.items)

def test_every_action_core_accepts_article_and_fillers():
    h=default_header_dictionary()
    for core in h.action_cores:
        raw=core.normalized_header
        bare=raw[2:] if raw.startswith('ال') else raw
        for variant in (bare,'ال'+bare,f'{bare} المعادي',f'التي نفذها العدو {bare}',f'{bare} من قصف مدفعي'):
            assert h.match_grammar(variant), (raw,variant)
def test_pure_imports_do_not_load_sqlalchemy_or_settings():
    files=['normalize.py','detection.py','window.py','parser.py','headers.py']
    source='\n'.join((Path('app/news/services/summaries')/name).read_text(encoding='utf-8') for name in files)
    assert 'sqlalchemy' not in source.lower() and 'app.core.config' not in source
