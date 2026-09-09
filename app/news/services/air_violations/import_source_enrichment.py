"""Recover public Telegram post metadata without replacing file-supplied values."""
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import or_, select

from app.news.models import RawMessage
from app.sources.services.red_alert_collector import match_village, normalize_arabic


def telegram_post_url(link: str) -> str | None:
    try:
        parsed = urlsplit(link)
    except ValueError:
        return None
    if parsed.scheme != 'https' or parsed.netloc.lower() not in {'t.me', 'telegram.me', 'www.t.me'}:
        return None
    path = parsed.path.removeprefix('/s') if parsed.path.startswith('/s/') else parsed.path
    if not re.fullmatch(r'/[A-Za-z][A-Za-z0-9_]{3,}/[0-9]+', path):
        return None
    return 'https://t.me' + path


def parse_telegram_post(html: str, link: str) -> dict:
    soup = BeautifulSoup(html, 'html.parser')
    post = soup.select_one('.tgme_widget_message')
    expected = urlsplit(link).path.strip('/')
    if post is None or post.get('data-post') != expected:
        return {'status': 'unavailable', 'reason': 'The linked Telegram post is not publicly available.'}
    text = post.select_one('.tgme_widget_message_text')
    timestamp = post.select_one('a.tgme_widget_message_date time[datetime]')
    author = post.select_one('.tgme_widget_message_owner_name')
    return {
        'status': 'retrieved', 'text': text.get_text('\n', strip=True) if text else None,
        'published_at': timestamp.get('datetime') if timestamp else None,
        'source_name': author.get_text(' ', strip=True) if author else None,
    }


def fetch_telegram_post(link: str) -> dict:
    url = telegram_post_url(link)
    if url is None:
        return {'status': 'unsupported', 'reason': 'Automatic lookup currently supports public Telegram post links.'}
    try:
        with httpx.stream('GET', url + '?embed=1&mode=tme', timeout=8, follow_redirects=False) as response:
            response.raise_for_status()
            content = bytearray()
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content) > 1_000_000:
                    return {'status': 'unavailable', 'reason': 'The source response was too large.'}
        return parse_telegram_post(content.decode('utf-8', errors='replace'), url)
    except httpx.HTTPError:
        return {'status': 'unavailable', 'reason': 'The source could not be reached.'}


class ImportSourceLookup:
    def __init__(self, db):
        self.db = db
        self.cache = {}

    def lookup(self, link: str | None) -> dict:
        if not link:
            return {'status': 'no_link'}
        if link in self.cache:
            return self.cache[link]
        url = telegram_post_url(link)
        result = None
        if url:
            archived = self.db.execute(select(
                RawMessage.raw_text, RawMessage.message_datetime, RawMessage.source_name,
            ).where(
                RawMessage.raw_payload['import'].as_string().is_(None),
                or_(*(RawMessage.raw_payload[key].as_string() == url for key in ('source_link', 'link', 'url', 'post_url'))),
            ).order_by(RawMessage.id.desc()).limit(1)).mappings().first()
            if archived:
                result = {'status': 'archived', 'text': archived['raw_text'],
                          'published_at': archived['message_datetime'].isoformat() if archived['message_datetime'] else None,
                          'source_name': archived['source_name']}
        if result is None:
            result = fetch_telegram_post(link)
        result.update(link=link, checked_at=datetime.now(timezone.utc).isoformat())
        self.cache[link] = result
        return result


def source_local_datetime(metadata: dict) -> datetime | None:
    try:
        value = datetime.fromisoformat(metadata.get('published_at') or '')
        if value.tzinfo is not None:
            return value.astimezone(ZoneInfo('Asia/Beirut'))
    except (ValueError, TypeError):
        pass
    return None


def import_location_text(text: str) -> str:
    # Short file headlines name a location after the aircraft action. Only use
    # an exact complete remainder; never fuzzy-match an arbitrary nearby place.
    remainder, count = re.subn(r'^(?:مسير[ةه]?|طيران استطلاعي|طيران حربي|طيران مروحي)\s+(?:(?:فوق|في)\s+)?', '', text.strip())
    return remainder.strip() if count and len(remainder.split()) <= 5 else ''


MANZLEH_REFERENCE = 'https://amalbaladi.org.lb/details/4285/'


def researched_import_location(text: str, link: str | None) -> dict | None:
    # These two source-linked records were individually researched. Do not
    # apply the ambiguous bare name to other files or other Telegram posts.
    if telegram_post_url(link or '') in {
        'https://t.me/redlinkleb/37930', 'https://t.me/redlinkleb/37954',
    } and normalize_arabic(import_location_text(text)) == 'المنزله':
        return {'acs_code': 71113, 'location_basis': 'Inferred: Al-Manzala neighborhood, Nabatieh El-Faouka.',
                'location_reference': MANZLEH_REFERENCE}
    return None


def match_import_village(text, villages, source_link=None):
    matched = match_village(text, villages)
    if matched:
        return matched
    researched = researched_import_location(text, source_link)
    if researched:
        village = next((item for item in villages if item.acs_code == researched['acs_code']), None)
        if village:
            return village, import_location_text(text)
    location = import_location_text(text) or text
    key = normalize_arabic(location)
    # Kafra: Ministry of Interior 2025 Bint Jbeil municipality results.
    # Chaat: PDA Lebanon's North Baalbek municipal-union reference.
    # Nabatieh: existing Data/VillageLocationAliases.json city-seat alias.
    aliases = {'كفره': 72257, 'شعث': 53274, 'النبطيه': 71111}
    code = aliases.get(key)
    if code:
        village = next((item for item in villages if item.acs_code == code), None)
        if village:
            return village, location
    candidates = {}
    for village in villages:
        name = normalize_arabic(village.ref_name_ar or '')
        caza = normalize_arabic(village.caza_ar or '')
        if caza and name.endswith(' ' + caza):
            name = name[:-(len(caza) + 1)]
        if name and name.removeprefix('ال') == key.removeprefix('ال'):
            candidates[village.id] = village
    if len(candidates) == 1:
        return next(iter(candidates.values())), location
    return None
