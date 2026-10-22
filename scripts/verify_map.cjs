/* Browser verification against a disposable frontend and a read-only aggregate snapshot.
 * PLAYWRIGHT_CORE_PATH points at a local playwright-core install. No production auth is changed.
 */
const { chromium } = require(process.env.PLAYWRIGHT_CORE_PATH || 'playwright-core');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const path = require('node:path');
const fixtures = JSON.parse(fs.readFileSync('.codex-staging/map_fixtures.json', 'utf8'));
const output = path.resolve(process.env.MAP_SCREENSHOT_DIR || '.codex-staging/map-screenshots');
fs.mkdirSync(output, { recursive: true });

(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe',
    headless: true, args: ['--enable-unsafe-swiftshader', '--use-angle=swiftshader', '--disable-web-security'] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1080 }, deviceScaleFactor: 1 });
  await context.addInitScript(() => localStorage.setItem('lebanon-news-auth', JSON.stringify({
    user: { id: 'visual-check', username: 'visual-check' }, role: 'super_admin',
  })));
  const page = await context.newPage();
  const errors = [], network = [], failed = [], metrics = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });
  page.on('requestfailed', request => failed.push(`${request.url()}: ${request.failure()?.errorText}`));
  page.on('request', request => { if (/map-fonts|map-rtl|village-labels/.test(request.url())) network.push(request.url()); });
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.protocol === 'http:' && url.hostname !== '127.0.0.1' && url.hostname !== 'localhost') {
      failed.push(`External request blocked: ${url}`); return route.abort();
    }
    if (!url.pathname.startsWith('/api/')) return route.continue();
    if (url.pathname.endsWith('/auth/me')) return route.fulfill({ json: { role: 'super_admin', user: { id: 'visual-check', username: 'visual-check' } } });
    const level = url.searchParams.get('level') || 'mohafaza';
    const data = fixtures.levels[level];
    let body;
    if (url.pathname.endsWith('/village-labels')) body = fixtures.labels;
    else if (url.pathname.endsWith('/meta')) body = fixtures.meta;
    else if (url.pathname.endsWith('/tab/overview')) body = data.overview;
    else if (url.pathname.endsWith('/tab/map')) body = data.mapTab || {};
    else if (url.pathname.endsWith('/map')) body = data.map;
    else if (url.pathname.endsWith('/kpis')) body = data.kpis;
    else if (url.pathname.endsWith('/rankings')) body = data.rankings;
    else if (url.pathname.includes('/area/')) body = fixtures.area;
    else body = {};
    return route.fulfill({ json: body });
  });
  await page.goto('http://127.0.0.1:5180/superadmin/analytics', { waitUntil: 'networkidle' });
  await page.getByRole('button', { name: 'View full map', exact: true }).waitFor();
  // Get the existing Map instance from React's ref for diagnostics, without adding a product debug API.
  await page.waitForFunction(() => {
    const element = document.querySelector('.maplibregl-map');
    if (!element) return false;
    const key = Object.keys(element).find(k => k.startsWith('__reactFiber'));
    let fiber = element[key];
    while (fiber && !fiber.memoizedProps?.geo?.mohafaza) fiber = fiber.return;
    for (let hook = fiber?.memoizedState; hook; hook = hook.next) {
      const ref = hook.memoizedState?.current;
      if (typeof ref?.getZoom === 'function') { window.__verifyMap = ref; return ref.loaded(); }
    }
    return false;
  });
  const initialMap = await page.evaluate(() => ({ zoom: window.__verifyMap.getZoom(), layers: window.__verifyMap.getStyle().layers.map(l => l.id) }));
  console.log('INITIAL', JSON.stringify(initialMap));
  const settle = () => page.waitForTimeout(1200);
  const shot = async (width, full, level, zoom) => {
    await page.evaluate(({ zoom, level }) => {
      const map = window.__verifyMap;
      if (level === 'country') map.fitBounds([[35.05, 33.03], [36.65, 34.7]], { padding: 16, duration: 0 });
      else map.jumpTo({ center: [35.43, 33.20], zoom });
    }, { zoom, level });
    await settle();
    const state = await page.evaluate(() => {
      const map = window.__verifyMap;
      return { zoom: map.getZoom(), pageWidth: document.documentElement.scrollWidth, viewport: innerWidth,
        container: map.getContainer().getBoundingClientRect().toJSON(),
        symbols: map.queryRenderedFeatures({ layers: ['names-mohafaza', 'names-caza', 'names-village'] }).map(f => f.properties.name_ar),
        htmlMarkers: document.querySelectorAll('.maplibregl-marker').length };
    });
    assert(state.pageWidth <= width, `Overflow at ${width}: ${state.pageWidth}`);
    assert.equal(state.htmlMarkers, 0);
    if (full) { assert.equal(state.container.width, width); assert.equal(state.container.height, 1080); }
    assert(state.symbols.length > 0, `No ${level} symbols at ${state.zoom}`);
    metrics.push({ width, full, level, ...state });
    await page.screenshot({ path: path.join(output, `${width}-${full ? 'full' : 'normal'}-${level}.png`) });
  };
  for (const width of [1280, 1440, 1920]) {
    await page.setViewportSize({ width, height: 1080 }); await settle();
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    if (width === 1280) continue;
    for (const [level, zoom] of [['country', null], ['caza', 9.2], ['village', 11.2]]) await shot(width, false, level, zoom);
    const trigger = page.getByRole('button', { name: 'View full map', exact: true });
    await trigger.click(); await settle();
    assert(new URL(page.url()).searchParams.get('map') === 'full');
    const dialog = page.getByRole('dialog', { name: 'Full map of Lebanon' });
    await dialog.waitFor();
    const close = page.getByRole('button', { name: 'Close full map' });
    await close.focus(); await page.keyboard.press('Tab');
    assert(await dialog.evaluate(el => el.contains(document.activeElement)), 'Focus escaped');
    for (const [level, zoom] of [['country', null], ['caza', 9.2], ['village', 11.2]]) await shot(width, true, level, zoom);
    await page.getByRole('button', { name: 'AR', exact: true }).click(); await settle();
    await page.screenshot({ path: path.join(output, `${width}-full-arabic.png`) });
    await page.getByRole('button', { name: 'Both', exact: true }).click();
    await page.keyboard.press('Escape'); await settle();
    assert(!new URL(page.url()).searchParams.has('map'));
    assert(await trigger.evaluate(el => el === document.activeElement), 'Focus did not return');
  }
  await page.getByRole('button', { name: 'View full map', exact: true }).click();
  await page.reload({ waitUntil: 'networkidle' });
  await page.getByRole('dialog', { name: 'Full map of Lebanon' }).waitFor();
  await page.getByRole('button', { name: 'Close full map' }).click();
  assert(!new URL(page.url()).searchParams.has('map'));
  fs.writeFileSync(path.join(output, 'verification.json'), JSON.stringify({ initialMap, metrics, errors, failed, network,
    missingCoordinates: fixtures.labels.missing_coordinates }, null, 2));
  console.log('RESULT', JSON.stringify({ screenshots: metrics.length + 2, errors, failed, localMapRequests: network.length }));
  await browser.close();
  assert.equal(errors.length, 0, errors.join('\n'));
  assert.equal(failed.filter(x => !x.includes('ERR_ABORTED')).length, 0, failed.join('\n'));
})().catch(error => { console.error(error); process.exit(1); });
