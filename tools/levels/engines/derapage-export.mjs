// EXT-002, circuit : exporte les circuits de Dérapage (Opencade) en fichiers JSON, tels que le jeu les déclare.
// Lancé dans le dépôt du jeu : node <ce fichier> <dossier>. Un fichier par circuit, nommé par son rang de jeu.
import './ts-resolve.mjs';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const { circuits } = await import(new URL('src/engines/derapage/circuits.ts', pathToFileURL(process.cwd() + '/')).href);
mkdirSync(process.argv[2], { recursive: true });
circuits.forEach((circuit, rank) => writeFileSync(join(process.argv[2], `circuit-${String(rank).padStart(2, '0')}.json`),
    JSON.stringify(circuit, null, 1) + '\n'));
console.log(circuits.length);
