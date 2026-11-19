#!/usr/bin/env node
// Contrôle MINIMAL d'un SBOM CycloneDX JSON, commun à tous les jeux — remplace `grep -c CycloneDX sbom.json`, qui passe
// pour n'importe quel fichier contenant le mot (un message d'erreur npm, un JSON tronqué, un SBOM vide).
// usage : node verifier-sbom.mjs <sbom.json>     codes : 0 valide, 1 invalide (motif sur stderr), 2 usage.
// Exige : JSON lisible ; bomFormat === "CycloneDX" ; specVersion de forme 1.N ; components = liste NON vide dont chaque
// entrée a un `name`. Sans dépendance. Source : gabarit CI de l'usine (ci/scripts) ; fichier GÉNÉRÉ dans chaque jeu.
import { readFileSync } from 'node:fs';

const f = process.argv[2];
if (!f) { console.error('usage : node verifier-sbom.mjs <sbom.json>'); process.exit(2); }
const ko = (m) => { console.error(`SBOM INVALIDE (${f}) : ${m}`); process.exit(1); };
let b;
try { b = JSON.parse(readFileSync(f, 'utf8')); } catch (e) { ko(`JSON illisible — ${String(e.message).slice(0, 160)}`); }
if (!b || typeof b !== 'object' || Array.isArray(b)) ko('la racine n\'est pas un objet');
if (b.bomFormat !== 'CycloneDX') ko(`bomFormat = ${JSON.stringify(b.bomFormat)}, attendu "CycloneDX"`);
if (typeof b.specVersion !== 'string' || !/^1\.\d+$/.test(b.specVersion)) ko(`specVersion = ${JSON.stringify(b.specVersion)}, attendu 1.N`);
if (!Array.isArray(b.components) || b.components.length === 0) ko('components absent ou vide');
const sansNom = b.components.filter((c) => !c || typeof c.name !== 'string' || !c.name).length;
if (sansNom) ko(`${sansNom} composant(s) sans name`);
console.log(`SBOM CycloneDX ${b.specVersion} : ${b.components.length} composants`);
