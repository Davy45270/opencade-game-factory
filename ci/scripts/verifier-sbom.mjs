#!/usr/bin/env node
// Contrôle d'un SBOM CycloneDX JSON, commun à tous les jeux — remplace `grep -c CycloneDX sbom.json`, qui passe
// pour n'importe quel fichier contenant le mot (un message d'erreur npm, un JSON tronqué, un SBOM vide).
// usage : node verifier-sbom.mjs <sbom.json>     codes : 0 valide, 1 invalide (motif sur stderr), 2 usage.
// Exige (même socle que la preuve SBOM de la barrière de qualité, sans dépendance) : JSON lisible ; bomFormat
// "CycloneDX" ; specVersion 1.4, 1.5 ou 1.6 ; components = liste NON vide ; chaque composant a un `type` de la liste
// CycloneDX et un `name` non vide ; `version`, `purl`, `bom-ref` sont des chaînes quand ils sont présents ; bom-ref uniques.
// Source : gabarit CI de l'usine (ci/scripts) ; fichier GÉNÉRÉ dans chaque jeu.
import { readFileSync } from 'node:fs';

const VERSIONS = new Set(['1.4', '1.5', '1.6']);
const TYPES = new Set(['application', 'framework', 'library', 'container', 'platform', 'operating-system', 'device',
  'device-driver', 'firmware', 'file', 'machine-learning-model', 'data', 'cryptographic-asset']);
const f = process.argv[2];
if (!f) { console.error('usage : node verifier-sbom.mjs <sbom.json>'); process.exit(2); }
const ko = (m) => { console.error(`SBOM INVALIDE (${f}) : ${m}`); process.exit(1); };
let b;
try { b = JSON.parse(readFileSync(f, 'utf8')); } catch (e) { ko(`JSON illisible — ${String(e.message).slice(0, 160)}`); }
if (!b || typeof b !== 'object' || Array.isArray(b)) ko('la racine n\'est pas un objet');
if (b.bomFormat !== 'CycloneDX') ko(`bomFormat = ${JSON.stringify(b.bomFormat)}, attendu "CycloneDX"`);
if (!VERSIONS.has(b.specVersion)) ko(`specVersion = ${JSON.stringify(b.specVersion)}, attendu 1.4, 1.5 ou 1.6`);
if (!Array.isArray(b.components) || b.components.length === 0) ko('components absent ou vide');
const refs = new Set();
b.components.forEach((c, i) => {
  const ou = `components[${i}]`;
  if (!c || typeof c !== 'object' || Array.isArray(c)) ko(`${ou} n'est pas un objet`);
  if (!TYPES.has(c.type)) ko(`${ou}.type = ${JSON.stringify(c.type)}, hors de la liste CycloneDX`);
  if (typeof c.name !== 'string' || !c.name) ko(`${ou} sans name`);
  for (const k of ['version', 'purl', 'bom-ref']) if (k in c && typeof c[k] !== 'string') ko(`${ou}.${k} n'est pas une chaîne`);
  if (c['bom-ref'] !== undefined) { if (refs.has(c['bom-ref'])) ko(`bom-ref en double : ${c['bom-ref']}`); refs.add(c['bom-ref']); }
});
console.log(`SBOM CycloneDX ${b.specVersion} : ${b.components.length} composants`);
