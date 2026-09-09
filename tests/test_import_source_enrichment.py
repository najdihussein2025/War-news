import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.news.services.air_violations.import_source_enrichment import (
    match_import_village, parse_telegram_post, source_local_datetime, telegram_post_url,
)


@pytest.mark.parametrize('url', ['http://127.0.0.1/a', 'https://t.me.evil.com/channel/1', 'https://t.me@evil.com/channel/1', 'https://t.me/+invite', 'https://[bad'])
def test_source_lookup_rejects_non_public_post_urls(url):
    assert telegram_post_url(url) is None


def test_telegram_preview_extracts_only_requested_post():
    html = '''<div class="tgme_widget_message" data-post="channel/42">
    <a class="tgme_widget_message_owner_name">News source</a>
    <div class="tgme_widget_message_text">Original news</div>
    <a class="tgme_widget_message_date"><time datetime="2026-08-01T21:30:00+00:00"></time></a></div>'''
    result = parse_telegram_post(html, 'https://t.me/channel/42')
    assert result['text'] == 'Original news'
    assert source_local_datetime(result).isoformat() == '2026-08-02T00:30:00+03:00'
    assert parse_telegram_post(html, 'https://t.me/channel/43')['status'] == 'unavailable'
    assert parse_telegram_post('Telegram Widget Post not found', 'https://t.me/channel/42')['status'] == 'unavailable'


@pytest.mark.parametrize('text, code', [('مسير كفرة', 72257), ('مسير الدوير', 71334), ('مسير الشهابية', 62254), ('مسير شعث', 53274), ('مسير النبطية', 71111)])
def test_import_location_uses_canonical_reference(text, code):
    data = json.loads((Path(__file__).parents[1] / 'Data/Villages.json').read_text(encoding='utf-8'))
    villages = [SimpleNamespace(id=index, **item) for index, item in enumerate(data)]
    result = match_import_village(text, villages)
    assert result is not None
    assert result[0].acs_code == code


def test_ambiguous_location_is_not_guessed():
    assert match_import_village('مسير المنزلة', []) is None


def test_researched_manzleh_is_limited_to_the_two_original_links():
    village = SimpleNamespace(id=1, acs_code=71113, ref_name_ar='نبطية الفوقا', caza_ar='النبطية')
    for post in ('37930', '37954'):
        result = match_import_village('مسير المنزلة', [village], 'https://t.me/redlinkleb/' + post)
        assert result[0].acs_code == 71113
    assert match_import_village('مسير المنزلة', [village], 'https://t.me/otherchannel/37930') is None
    assert match_import_village('مسير المنزلة', [village]) is None
