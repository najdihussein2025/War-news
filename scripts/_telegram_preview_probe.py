import re
import time

import httpx
from app.sources.services.red_alert_collector import parse_public_preview


base = "https://t.me/s/redlinkleb"
urls = [
    base,
    f"{base}?cache_bust={int(time.time())}",
    f"{base}?q=%23%D8%AC%D9%86%D9%88%D8%A8",
]
for url in urls:
    response = httpx.get(
        url,
        headers={"User-Agent": "Mozilla/5.0", "Cache-Control": "no-cache"},
        follow_redirects=True,
    )
    ids = [int(value) for value in re.findall(r'data-post="redlinkleb/(\d+)', response.text)]
    print(url, response.status_code, len(response.text), max(ids, default=0))
    posts = parse_public_preview(response.text, "redlinkleb")
    print([(post.message_id, post.message_datetime, post.text[:80]) for post in posts[:3]])
