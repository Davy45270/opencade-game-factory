#!/usr/bin/env node
// Version de Playwright d'un jeu = celle de son package-lock.json (jamais une image figée dans la CI).
// usage : node version-playwright.mjs [--lock <package-lock.json>]                 affiche la version (ex. 1.65.1)
//         node version-playwright.mjs [--lock …] --image                           affiche l'image mcr.microsoft.com/playwright:v<version>-noble
//         node version-playwright.mjs [--lock …] --verifier <image>                0 si <image> porte la version du lock, 1 sinon
// codes : 0 succès, 1 divergence, 2 usage, 4 lock absent ou sans Playwright. Sans dépendance.
// Règle (même que ci/woodpecker.py) : `packages["node_modules/@playwright/test"].version`, sinon
// `packages["node_modules/playwright"].version`, sinon l'ancien format `dependencies[…].version` ; version EXACTE x.y.z.
import { readFileSync } from 'node:fs';

const args = process.argv.slice(2);
const opt = (nom) => { const i = args.indexOf(nom); return i >= 0 ? args[i + 1] : undefined; };
const lock = opt('--lock') ?? 'package-lock.json';
let l;
try { l = JSON.parse(readFileSync(lock, 'utf8')); } catch (e) { console.error(`lock illisible : ${lock}`); process.exit(4); }
const p = l.packages ?? {};
const d = l.dependencies ?? {};
const v = p['node_modules/@playwright/test']?.version ?? p['node_modules/playwright']?.version
  ?? d['@playwright/test']?.version ?? d.playwright?.version;
if (typeof v !== 'string' || !/^\d+\.\d+\.\d+$/.test(v)) { console.error(`Playwright absent du lock ${lock} (ou version non exacte : ${v})`); process.exit(4); }
const image = `mcr.microsoft.com/playwright:v${v}-noble`;
if (args.includes('--verifier')) {
  const img = opt('--verifier');
  if (!img) { console.error('usage : --verifier <image>'); process.exit(2); }
  if (img !== image) { console.error(`image ${img} ≠ lock ${v} (attendu ${image}) : régénérer la CI depuis l'usine`); process.exit(1); }
  console.log(`Playwright : image et lock en ${v}`);
} else {
  console.log(args.includes('--image') ? image : v);
}
