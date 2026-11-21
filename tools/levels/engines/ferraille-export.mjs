// EXT-002, plateforme : exporte les niveaux de Ferraille (Opencade) en fichiers JSON, tels que le jeu les déclare
// (séquence de modules complétée par le catalogue de niveaux du jeu). Lancé dans le dépôt du jeu : node <ce fichier> <dossier>.
import './ts-resolve.mjs';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const { LEVELS } = await import(new URL('src/engines/ferraille/levels.ts', pathToFileURL(process.cwd() + '/')).href);
mkdirSync(process.argv[2], { recursive: true });
LEVELS.forEach((level, rank) => writeFileSync(join(process.argv[2], `ferraille-${String(rank).padStart(2, '0')}.json`),
    JSON.stringify({ ferraille: rank, ...level }, null, 1) + '\n'));
console.log(LEVELS.length);
