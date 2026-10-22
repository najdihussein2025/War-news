/** Build-time only. Runtime map assets are served entirely by the office frontend. */
import { mkdir, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { join } from "node:path";

const root = process.argv[2] ?? "frontend/public";
const ranges = [0, 256, 512, 768, 1536, 1792, 2048, 8192, 64256, 64512, 64768, 65024, 65280];
const manifest = [];
async function download(url, path) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${response.status}: ${url}`);
  const data = Buffer.from(await response.arrayBuffer());
  await writeFile(path, data);
  manifest.push({ url, file: path.slice(root.length + 1).replaceAll("\\", "/"), bytes: data.length,
    sha256: createHash("sha256").update(data).digest("hex") });
}
for (const font of ["Noto Sans Regular", "Noto Sans Bold"]) {
  const directory = join(root, "map-fonts", font);
  await mkdir(directory, { recursive: true });
  await Promise.all(ranges.map((start) => download(
    `https://demotiles.maplibre.org/font/${encodeURIComponent(font)}/${start}-${start + 255}.pbf`,
    join(directory, `${start}-${start + 255}.pbf`),
  )));
}
await mkdir(join(root, "map-rtl"), { recursive: true });
// MapLibre 4.7.1 expects synchronous plugin registration (0.3.x is asynchronous).
await download("https://unpkg.com/@mapbox/mapbox-gl-rtl-text@0.2.3/mapbox-gl-rtl-text.js",
  join(root, "map-rtl", "mapbox-gl-rtl-text.js"));
await download("https://unpkg.com/@mapbox/mapbox-gl-rtl-text@0.2.3/LICENSE.md",
  join(root, "map-rtl", "LICENSE.md"));
await download("https://raw.githubusercontent.com/notofonts/noto-fonts/main/LICENSE",
  join(root, "map-fonts", "LICENSE"));
await writeFile(join(root, "map-fonts", "manifest.json"), JSON.stringify(manifest.sort((a, b) => a.file.localeCompare(b.file)), null, 2) + "\n");
console.log(`Vendored ${manifest.length} local assets`);
