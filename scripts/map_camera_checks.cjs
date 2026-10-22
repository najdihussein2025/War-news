const assert = require('node:assert/strict');
const path = require('node:path');

module.exports = async function checkCamera(page, output) {
  const results = [];
  const settle = () => page.waitForTimeout(650);
  const read = () => page.evaluate(() => {
    const m = window.__verifyMap, el = m.getContainer(), w = el.clientWidth, h = el.clientHeight;
    const nw = m.project([35.05, 34.7]), se = m.project([36.65, 33.03]);
    const intersection = Math.max(0, Math.min(w, se.x) - Math.max(0, nw.x)) * Math.max(0, Math.min(h, se.y) - Math.max(0, nw.y));
    const full = !!el.closest('[aria-modal="true"]');
    const fit = m.cameraForBounds([[35.05, 33.03], [36.65, 34.7]], { padding: full ? { top: 96, bottom: 16, left: 16, right: 16 } : 16 }).zoom;
    return { zoom: m.getZoom(), minZoom: m.getMinZoom(), center: m.getCenter(), fit, full,
      coverage: intersection / (w * h), retained: intersection / (Math.min(w, se.x - nw.x) * Math.min(h, se.y - nw.y)),
      cooperative: m.cooperativeGestures.isEnabled(), inert: document.querySelectorAll('[inert]').length,
      box: el.getBoundingClientRect().toJSON(), scroll: scrollY };
  });
  const point = async () => page.evaluate(() => {
    const canvas = window.__verifyMap.getCanvas(), b = canvas.getBoundingClientRect();
    for (const y of [.5, .65, .4, .75, .3]) for (const x of [.5, .35, .65, .15, .85]) {
      const p = { x: b.x + b.width * x, y: b.y + b.height * y };
      if (p.y > 0 && p.y < innerHeight - 20 && document.elementFromPoint(p.x, p.y) === canvas) return p;
    }
    throw new Error('No exposed map canvas to drag');
  });
  const drag = async (dx = 70, dy = 0) => {
    const p = await point();
    await page.mouse.move(p.x, p.y); await page.mouse.down();
    await page.mouse.move(p.x + dx, p.y + dy, { steps: 12 }); await page.mouse.up(); await settle();
  };
  for (const [width, height] of [[1280, 800], [1920, 1080], [390, 844]]) {
    if (process.env.MAP_CAMERA_WIDTH && width !== Number(process.env.MAP_CAMERA_WIDTH)) continue;
    await page.setViewportSize({ width, height });
    await page.locator('.maplibregl-canvas').scrollIntoViewIfNeeded(); await settle();
    for (const full of [false, true]) {
      console.log('CAMERA', width, height, full ? 'full' : 'small');
      if (full) { await page.getByRole('button', { name: 'View full map', exact: true }).click(); await settle(); }
      await page.getByRole('button', { name: 'Reset view', exact: true }).click(); await settle();
      let state = await read();
      assert.equal(state.cooperative, !full);
      assert(Math.abs(state.minZoom - (state.fit - .5)) < .01, `Wrong fit floor: ${JSON.stringify(state)}`);
      // Exercise real pointer input, then repeated/extreme pan requests at each scale.
      await drag();
      for (const zoom of process.env.MAP_SKIP_PANS ? [] : [state.fit, state.minZoom, 11.2]) {
        await page.evaluate(z => window.__verifyMap.jumpTo({ zoom: z }), zoom); await settle();
        for (const [dx, dy] of [[100000, 0], [-100000, 0], [0, 100000], [0, -100000]]) {
          console.log('PAN', width, full, zoom, dx, dy);
          await drag(Math.sign(dx) * 60, Math.sign(dy) * 60);
          await page.evaluate(([x, y]) => window.__verifyMap.panBy([x, y], { duration: 0 }), [dx, dy]); await settle();
          state = await read();
          assert(state.retained >= .4 - .001, `Lost country: ${JSON.stringify(state)}`);
          results.push({ width, height, direction: [dx, dy], ...state });
        }
      }
      await page.evaluate(() => window.__verifyMap.zoomTo(-10, { duration: 0 })); await settle();
      state = await read();
      assert(state.zoom >= state.fit - .6, 'Zoomed below fit floor');
      assert(Math.abs(state.zoom - state.minZoom) < .01, 'Old detail bounds blocked zooming out to the floor');
      await page.getByRole('button', { name: 'Reset view', exact: true }).click(); await settle();
      const beforeWheel = await read(), p = await point();
      await page.mouse.move(p.x, p.y); await page.mouse.wheel(0, 220); await settle();
      const wheel = await read();
      if (full) assert(wheel.zoom < beforeWheel.zoom, 'Full map did not wheel zoom');
      else {
        assert(Math.abs(wheel.zoom - beforeWheel.zoom) < .001, 'Plain wheel zoomed embedded map');
        assert(wheel.scroll > beforeWheel.scroll, 'Plain wheel did not scroll page');
        await page.locator('.maplibregl-canvas').scrollIntoViewIfNeeded(); await settle();
        const ctrlPoint = await point(), beforeCtrl = await read();
        await page.mouse.move(ctrlPoint.x, ctrlPoint.y); await page.keyboard.down('Control');
        await page.mouse.wheel(0, -300); await page.keyboard.up('Control'); await settle();
        assert((await read()).zoom > beforeCtrl.zoom, 'Ctrl+wheel did not zoom embedded map');
      }
      // Canvas keyboard gestures and button zooms must survive container resizing.
      await page.locator('.maplibregl-canvas').focus();
      const beforeKey = await read(); await page.keyboard.press('+'); await settle();
      assert((await read()).zoom > beforeKey.zoom, 'Keyboard zoom is unavailable');
      await page.getByRole('button', { name: 'Zoom in', exact: true }).click(); await settle();
      const beforeResize = await read();
      await page.setViewportSize({ width: width + 8, height }); await settle();
      assert(Math.abs((await read()).zoom - beforeResize.zoom) < .001, 'Resize undid button zoom');
      await page.setViewportSize({ width, height }); await settle();
      await page.getByRole('button', { name: 'Reset view', exact: true }).click(); await settle();
      if (width === 1920) {
        await page.getByRole('button', { name: 'Zoom in', exact: true }).click(); await settle();
        const empty = await page.evaluate(() => {
          const m = window.__verifyMap, c = m.getCanvas(), b = c.getBoundingClientRect();
          for (const x of [.05, .15, .9, .95]) for (const y of [.3, .5, .7]) {
            const p = { x: b.width * x, y: b.height * y };
            if (document.elementFromPoint(b.x + p.x, b.y + p.y) === c && !m.queryRenderedFeatures([p.x, p.y], { layers: ['fill-mohafaza'] }).length)
              return { x: b.x + p.x, y: b.y + p.y };
          }
          throw new Error('No empty canvas point for reset');
        });
        await page.mouse.dblclick(empty.x, empty.y); await settle();
        const reset = await read(); assert(Math.abs(reset.zoom - reset.fit) < .01, `Empty double-click did not reset: ${JSON.stringify(reset)}`);
      }
      if (!full && width === 1920) { await page.evaluate(() => window.scrollTo(0, 0)); await settle(); }
      await page.screenshot({ path: path.join(output, `${width}-after-${full ? 'full' : 'small'}.png`) });
      if (full) {
        await page.getByRole('button', { name: 'Close full map' }).click(); await settle();
        assert.equal((await read()).inert, 0, 'Inert leaked after closing');
        await page.locator('.maplibregl-canvas').scrollIntoViewIfNeeded(); await settle();
        const beforeDrag = await read(); await drag(0, 70);
        assert.notEqual((await read()).center.lat, beforeDrag.center.lat, 'Map not draggable after fullscreen');
      }
    }
  }
  await page.setViewportSize({ width: 1920, height: 1080 }); await settle();
  await page.getByRole('button', { name: 'View full map', exact: true }).click(); await settle();
  await page.selectOption('#full-map-level', 'caza'); await settle();
  await page.getByRole('button', { name: 'Reset view', exact: true }).click(); await settle();
  // Exercise the defensive moveend recovery independently of the hard pan clamp.
  await page.evaluate(() => {
    const m = window.__verifyMap;
    window.__restoreCameraGuard = { transform: m.transformCameraUpdate, bounds: m.getMaxBounds() };
    m.transformCameraUpdate = null; m.setMaxBounds(null); m.jumpTo({ center: [20, 20] });
  }); await settle();
  assert((await read()).retained >= .4, 'Moveend snap-back did not recover country');
  await page.evaluate(() => {
    const m = window.__verifyMap, saved = window.__restoreCameraGuard;
    m.transformCameraUpdate = saved.transform; m.setMaxBounds(saved.bounds); delete window.__restoreCameraGuard;
  });
  const hit = await page.evaluate(() => { const p = window.__verifyMap.project([35.43, 33.20]); return { x: p.x, y: p.y }; });
  const dialog = page.getByRole('dialog', { name: 'Full map of Lebanon' });
  await page.mouse.click(hit.x, hit.y); await dialog.getByRole('complementary', { name: 'Area profile' }).waitFor(); await settle();
  assert(await page.evaluate(() => Array.from(document.querySelectorAll('aside[aria-label="Area profile"]'))
    .filter(el => !el.closest('[aria-modal="true"]')).every(el => !!el.closest('[inert]'))), 'Background replacement escaped inert');
  await drag(); await page.getByRole('button', { name: 'Zoom in', exact: true }).click(); await settle();
  const selectedCamera = await read();
  await dialog.getByRole('button', { name: 'Close area profile' }).click(); await settle();
  const closedCamera = await read();
  assert(Math.abs(selectedCamera.zoom - closedCamera.zoom) < .001, 'Closing area reset zoom');
  assert(Math.abs(selectedCamera.center.lng - closedCamera.center.lng) < .00001, 'Closing area reset center');
  assert(Math.abs(selectedCamera.center.lat - closedCamera.center.lat) < .00001, 'Closing area reset center');
  await page.selectOption('#full-map-level', 'mohafaza'); await settle();
  await page.getByRole('button', { name: 'Close full map' }).click(); await settle();
  assert.equal(await page.getByRole('dialog', { name: 'Full map of Lebanon' }).count(), 0);
  assert.equal((await read()).inert, 0);
  // Map tab uses the same instance and gestures, not just the Overview box.
  await page.getByRole('button', { name: 'Map', exact: true }).click(); await settle();
  const beforeTabDrag = await read(); await drag();
  assert.notEqual((await read()).center.lng, beforeTabDrag.center.lng);
  await page.getByRole('button', { name: 'Overview', exact: true }).click(); await settle();
  await page.getByRole('button', { name: 'Reset view', exact: true }).click(); await settle();
  // Verify runtime token changes without inventing a product-wide dark theme.
  const background = await page.evaluate(() => window.__verifyMap.getPaintProperty('background', 'background-color'));
  await page.evaluate(() => {
    document.documentElement.style.setProperty('--color-surface-muted', '#1c3447');
    document.documentElement.style.setProperty('--color-accent', '#8ca0af');
  }); await settle();
  assert.equal(await page.evaluate(() => window.__verifyMap.getPaintProperty('background', 'background-color')), '#1c3447');
  assert.equal(await page.evaluate(() => window.__verifyMap.getPaintProperty('country-outline', 'line-color')), '#8ca0af');
  await page.screenshot({ path: path.join(output, '1920-dark-token-simulation.png') });
  await page.evaluate(() => {
    document.documentElement.style.removeProperty('--color-surface-muted');
    document.documentElement.style.removeProperty('--color-accent');
  }); await settle();
  assert.equal(await page.evaluate(() => window.__verifyMap.getPaintProperty('background', 'background-color')), background);
  assert(await page.evaluate(() => window.__verifyMap.getContainer().isConnected), 'Map was recreated');
  return results;
};
