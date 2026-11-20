#!/usr/bin/env node
// Spec résolue (REG-06 : une PR est refusée sans résolution des specs). Lit .woodpecker/usine/spec.json, écrit par
// l'usine (`ci/woodpecker.py rendre`, à partir de `specctl resolve`) : 0 si la spec du jeu est résolue, 1 sinon.
// Une résolution périmée se voit côté usine : `ci/woodpecker.py verifier` signale le fichier comme une dérive.
import { readFileSync } from 'node:fs';

const f = '.woodpecker/usine/spec.json';
let s;
try { s = JSON.parse(readFileSync(f, 'utf8')); } catch (e) {
  console.error(`REG-06 : ${f} absent ou illisible : régénérer la CI depuis l'usine`); process.exit(1);
}
if (s?.status !== 'ok' || typeof s.version !== 'string' || !s.version || typeof s.specId !== 'string') {
  console.error(`REG-06 : spec du projet ${JSON.stringify(s?.project)} non résolue (${s?.status ?? 'statut absent'}) : `
    + 'importer la spec dans le registre de l\'usine, ou faire arbitrer sa version, puis régénérer la CI');
  process.exit(1);
}
console.log(`REG-06 : spec ${s.specId} résolue en ${s.version}`);
