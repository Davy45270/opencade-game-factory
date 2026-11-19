#!/usr/bin/env node
// e2e de DÉMARRAGE sous la CSP de production : sert dist/ tel qu'il sera publié, ouvre la page dans Chromium (Playwright
// du jeu) et refuse au moindre écart. Né d'un constat sur un jeu : la CSP stricte, vérifiée seulement comme texte, peut
// bloquer au chargement un script ou un worker que les e2e en serveur de dev ne voient jamais.
// usage : node demarrage-csp.mjs <dist> [--csp "<politique>"] [--attente <ms>] [--sec]
//   La politique de production est la balise <meta http-equiv="Content-Security-Policy"> de <dist>/index.html ;
//   --csp l'envoie AUSSI en en-tête HTTP (cas d'un serveur qui la pose). Sans aucune des deux : REFUS (rien à prouver).
//   --sec : lit et affiche la politique, sans navigateur (contrôle rapide, tests de l'usine).
// Refus (code 1) : aucune CSP ; une violation `securitypolicyviolation` ; une erreur JS (pageerror) ; une requête
// bloquée ou en échec vers l'origine ; une page vide (ni canvas ni texte) après l'attente. Code 2 : usage.
// Muet : Chromium lancé avec --mute-audio. Aucune ressource externe chargée hors de dist/.
import { createServer } from 'node:http';
import { readFileSync, existsSync, statSync } from 'node:fs';
import { join, normalize, extname, resolve } from 'node:path';

const args = process.argv.slice(2);
const opt = (nom) => { const i = args.indexOf(nom); return i >= 0 ? args[i + 1] : undefined; };
const dist = args.find((a, i) => !a.startsWith('--') && !['--csp', '--attente'].includes(args[i - 1]));
if (!dist) { console.error('usage : node demarrage-csp.mjs <dist> [--csp "<politique>"] [--attente <ms>] [--sec]'); process.exit(2); }
const racine = resolve(dist);
const index = join(racine, 'index.html');
if (!existsSync(index)) { console.error(`REFUS : ${index} absent (construire d'abord)`); process.exit(1); }
const html = readFileSync(index, 'utf8');
const meta = /<meta\b[^>]*http-equiv=["']Content-Security-Policy["'][^>]*content=["']([^"']+)["']/i.exec(html);
const entete = opt('--csp');
const politique = meta?.[1] ?? entete;
if (!politique) { console.error('REFUS : aucune CSP de production (ni <meta> dans index.html, ni --csp)'); process.exit(1); }
console.log(`CSP de production (${meta ? 'meta' : 'en-tête'}) : ${politique}`);
if (args.includes('--sec')) process.exit(0);

const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.css': 'text/css',
  '.json': 'application/json', '.webmanifest': 'application/manifest+json', '.png': 'image/png', '.svg': 'image/svg+xml',
  '.webp': 'image/webp', '.jpg': 'image/jpeg', '.woff2': 'font/woff2', '.wasm': 'application/wasm', '.ogg': 'audio/ogg',
  '.mp3': 'audio/mpeg', '.ico': 'image/x-icon', '.txt': 'text/plain' };
const serveur = createServer((req, res) => {
  let chemin = normalize(decodeURIComponent(new URL(req.url, 'http://x').pathname)).replace(/^(\.\.[/\\])+/, '');
  let f = join(racine, chemin);
  if (!f.startsWith(racine)) { res.writeHead(403).end(); return; }
  if (existsSync(f) && statSync(f).isDirectory()) f = join(f, 'index.html');
  if (!existsSync(f)) { res.writeHead(404).end(); return; }
  const h = { 'Content-Type': TYPES[extname(f)] ?? 'application/octet-stream' };
  if (entete) h['Content-Security-Policy'] = entete;
  res.writeHead(200, h).end(readFileSync(f));
});
await new Promise((ok) => serveur.listen(0, '127.0.0.1', ok));
const url = `http://127.0.0.1:${serveur.address().port}/`;

let chromium;
try { ({ chromium } = await import(join(process.cwd(), 'node_modules', '@playwright/test', 'index.mjs'))); }
catch { ({ chromium } = await import('playwright')); }
const navigateur = await chromium.launch({ args: ['--mute-audio'] });
const page = await navigateur.newPage();
const ecarts = [];
await page.addInitScript(() => {
  window.__csp = [];
  document.addEventListener('securitypolicyviolation', (e) =>
    window.__csp.push(`${e.violatedDirective} bloque ${e.blockedURI || 'en ligne'}`));
});
page.on('pageerror', (e) => ecarts.push(`erreur JS : ${String(e.message).slice(0, 200)}`));
page.on('console', (m) => { if (m.type() === 'error' && /Content Security Policy/i.test(m.text())) ecarts.push(`console CSP : ${m.text().slice(0, 200)}`); });
page.on('requestfailed', (r) => { if (r.url().startsWith(url)) ecarts.push(`requête en échec : ${r.url().slice(url.length - 1)} (${r.failure()?.errorText})`); });
page.on('response', (r) => { if (r.url().startsWith(url) && r.status() >= 400) ecarts.push(`HTTP ${r.status()} : ${r.url().slice(url.length - 1)}`); });
try {
  await page.goto(url, { waitUntil: 'load', timeout: 30000 });
  await page.waitForTimeout(Number(opt('--attente') ?? 3000));
  const csp = await page.evaluate(() => window.__csp);
  for (const v of csp) ecarts.push(`violation CSP : ${v}`);
  const vivant = await page.evaluate(() => !!document.querySelector('canvas') || (document.body?.innerText ?? '').trim().length > 0);
  if (!vivant) ecarts.push('page vide après le démarrage (ni canvas ni texte)');
} catch (e) {
  ecarts.push(`chargement : ${String(e.message).slice(0, 200)}`);
} finally {
  await navigateur.close();
  serveur.close();
}
if (ecarts.length) { console.error(`DÉMARRAGE SOUS CSP : REFUS (${ecarts.length})\n  ${ecarts.join('\n  ')}`); process.exit(1); }
console.log('démarrage sous CSP de production : 0 violation, 0 erreur JS, page vivante');
