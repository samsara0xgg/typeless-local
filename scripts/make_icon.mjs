#!/usr/bin/env node
/* Draws the 言字 app icon and writes it out.

     node scripts/make_icon.mjs            # SVGs only
     node scripts/make_icon.mjs --icns     # also assets/AppIcon.icns (needs Playwright)

   The icon is the character 言 (speech): a dot, three strokes of text and a
   mouth, the mouth made of glass with a voice in it. It is drawn on a 1024
   grid and placed on Apple's macOS icon template (an 824 squircle, centred,
   with a soft shadow). The same SVG is the guide window's picture, so the
   two can never drift apart. */
import { writeFileSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const OUT_SVG = [join(ROOT, 'assets', 'AppIcon.svg'), join(ROOT, 'typeless_local', 'web', 'appicon.svg')];
const OUT_ICNS = join(ROOT, 'assets', 'AppIcon.icns');

function squircle(cx, cy, r, n = 5, steps = 120) {
  const pts = [];
  for (let i = 0; i < steps; i++) {
    const t = (i / steps) * Math.PI * 2, c = Math.cos(t), s = Math.sin(t);
    pts.push(`${(cx + r * Math.sign(c) * Math.abs(c) ** (2 / n)).toFixed(1)},${(cy + r * Math.sign(s) * Math.abs(s) ** (2 / n)).toFixed(1)}`);
  }
  return 'M' + pts.join('L') + 'Z';
}

const SQ = squircle(512, 512, 512);
const BG = ['#FF6A4D', '#EA3A36', '#B81D33'];
const GLASS = 'rgba(255,255,255,.26)';
const RIM = 0.95;

const rr = (x, y, w, h, r) => a => `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${r}" ${a}/>`;
const circ = (cx, cy, r) => a => `<circle cx="${cx}" cy="${cy}" r="${r}" ${a}/>`;
const solid = shape => `<g filter="url(#sh)">${shape('fill="#FFFFFF"')}</g>`;
const glass = shape => `<g filter="url(#sh)">${shape(`fill="${GLASS}"`)}${shape('fill="url(#sheen)"')}${shape('fill="none" stroke="url(#rim)" stroke-width="7"')}</g>`;

function artwork() {
  const mouth = [[440, 700, 24, 56], [478, 682, 24, 92], [516, 692, 24, 72], [554, 704, 24, 48]];
  return solid(circ(512, 226, 50))
    + solid(rr(222, 312, 580, 66, 33))
    + solid(rr(302, 424, 420, 58, 29))
    + solid(rr(302, 526, 420, 58, 29))
    + glass(rr(302, 626, 420, 226, 72))
    + mouth.map(([x, y, w, h]) => solid(rr(x, y, w, h, 12))).join('');
}

function svg() {
  const defs = `
<linearGradient id="bg" x1=".1" y1="0" x2=".9" y2="1">${BG.map((c, i) => `<stop offset="${i / (BG.length - 1)}" stop-color="${c}"/>`).join('')}</linearGradient>
<linearGradient id="rim" x1="0" y1="0" x2=".35" y2="1"><stop offset="0" stop-color="#fff" stop-opacity="${RIM}"/><stop offset=".42" stop-color="#fff" stop-opacity="${RIM * 0.18}"/><stop offset=".7" stop-color="#fff" stop-opacity="${RIM * 0.1}"/><stop offset="1" stop-color="#fff" stop-opacity="${RIM * 0.55}"/></linearGradient>
<linearGradient id="sheen" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".34"/><stop offset=".5" stop-color="#fff" stop-opacity="0"/></linearGradient>
<radialGradient id="spec" cx=".28" cy=".12" r=".9"><stop offset="0" stop-color="#fff" stop-opacity=".2"/><stop offset=".55" stop-color="#fff" stop-opacity="0"/></radialGradient>
<filter id="sh" x="-30%" y="-30%" width="160%" height="170%"><feDropShadow dx="0" dy="14" stdDeviation="16" flood-color="#000" flood-opacity=".22"/></filter>
<filter id="plate" x="-10%" y="-10%" width="120%" height="125%"><feDropShadow dx="0" dy="12" stdDeviation="14" flood-color="#000" flood-opacity=".3"/></filter>
<clipPath id="clip"><path d="${SQ}"/></clipPath>`;
  // Apple's template: the 824 pt body sits 100 pt in from each edge of the 1024 canvas.
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" width="1024" height="1024"><defs>${defs}</defs>`
    + `<g transform="translate(100 100) scale(0.8046875)">`
    + `<path d="${SQ}" fill="url(#bg)" filter="url(#plate)"/><path d="${SQ}" fill="url(#spec)"/>`
    + `<g clip-path="url(#clip)">${artwork()}</g></g></svg>\n`;
}

// PNG-backed ICNS entries: type -> pixel size.
const ICNS = [['icp4', 16], ['icp5', 32], ['ic11', 32], ['icp6', 64], ['ic12', 64], ['ic07', 128], ['ic13', 256], ['ic08', 256], ['ic14', 512], ['ic09', 512], ['ic10', 1024]];

async function renderPngs(source) {
  const require = createRequire(import.meta.url);
  let playwright;
  try { playwright = require('playwright'); } catch { playwright = require('/opt/node22/lib/node_modules/playwright'); }
  const browser = await playwright.chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1024, height: 1024 } });
  const out = new Map();
  for (const size of new Set(ICNS.map(([, s]) => s))) {
    await page.setViewportSize({ width: size, height: size });
    await page.setContent(`<html><body style="margin:0;background:transparent">${source.replace('width="1024" height="1024"', `width="${size}" height="${size}"`)}</body></html>`);
    out.set(size, await page.screenshot({ omitBackground: true, clip: { x: 0, y: 0, width: size, height: size } }));
  }
  await browser.close();
  return out;
}

function icns(pngs) {
  const chunks = ICNS.map(([type, size]) => {
    const data = pngs.get(size), head = Buffer.alloc(8);
    head.write(type, 0, 'ascii');
    head.writeUInt32BE(data.length + 8, 4);
    return Buffer.concat([head, data]);
  });
  const body = Buffer.concat(chunks), head = Buffer.alloc(8);
  head.write('icns', 0, 'ascii');
  head.writeUInt32BE(body.length + 8, 4);
  return Buffer.concat([head, body]);
}

const source = svg();
for (const path of OUT_SVG) { mkdirSync(dirname(path), { recursive: true }); writeFileSync(path, source); }
console.log(`wrote ${OUT_SVG.map(p => p.slice(ROOT.length + 1)).join(', ')}`);
if (process.argv.includes('--icns')) {
  writeFileSync(OUT_ICNS, icns(await renderPngs(source)));
  console.log(`wrote ${OUT_ICNS.slice(ROOT.length + 1)}`);
}
