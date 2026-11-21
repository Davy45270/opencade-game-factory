// EXT-002, circuit : juge un circuit de Dérapage (Opencade) avec le moteur du jeu, sans écran.
// Lancé dans le dépôt du jeu : node <ce fichier> <circuit.json>. Le circuit remplace un tracé du jeu, puis le
// pilote de démonstration du jeu (`controller`) court la course complète. Rien des règles n'est réécrit ici.
// Réponse : `OK <nom> …` si la course se termine (trois tours bouclés, quel que soit le classement du pilote de
// démonstration), `ÉCHEC <nom> : motif` sinon.
import './ts-resolve.mjs';
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

const root = pathToFileURL(process.cwd() + '/');
const load = path => import(new URL(path, root).href);
const data = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const { circuits } = await load('src/engines/derapage/circuits.ts');
const { Engine } = await load('src/engines/derapage/engine.ts');
const { controller } = await load('src/engines/derapage/ai.ts');
const slot = 0;
const name = data.name ?? 'circuit';
try {
    circuits[slot] = { ...circuits[slot], ...data };
    const race = new Engine(slot, 28);
    const limit = 60 * 60 * 5; // cinq minutes de course simulée
    let frame = 0;
    for (; frame < limit && race.status === 'playing'; frame++) {
        race.input(controller(race.karts[0], race.track));
        race.step(1000 / 60);
    }
    const done = race.status !== 'playing' && race.lapTimesMs.length === 3;
    if (done)
        console.log(`OK ${name} 3 tours en ${Math.round(race.lapTimesMs.reduce((a, b) => a + b, 0))} ms, ${frame} images, course ${race.status === 'won' ? 'gagnée' : 'perdue'}`);
    else console.log(`ÉCHEC ${name} : course non terminée en ${limit} images (${race.lapTimesMs.length} tour(s) bouclé(s))`);
    process.exitCode = done ? 0 : 1;
} catch (error) {
    console.log(`ÉCHEC ${name} : ${error instanceof Error ? error.message : String(error)}`);
    process.exitCode = 1;
}
