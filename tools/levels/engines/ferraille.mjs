// EXT-002, plateforme : juge un niveau de Ferraille (Opencade) avec le moteur du jeu, sans écran.
// Lancé dans le dépôt du jeu : node <ce fichier> <niveau.json>. Le niveau remplace celui de son rang dans le jeu,
// puis le pilote du jeu (`pilot`, commandes ordinaires seulement) le joue. Rien des règles n'est réécrit ici.
// Réponse : `OK <nom> …` si le pilote gagne (porte atteinte ou boss vaincu), `ÉCHEC <nom> : motif` sinon.
import './ts-resolve.mjs';
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

const root = pathToFileURL(process.cwd() + '/');
const load = path => import(new URL(path, root).href);
const data = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const { LEVELS } = await load('src/engines/ferraille/levels.ts');
const { Engine, DT } = await load('src/engines/ferraille/engine.ts');
const { pilot } = await load('src/engines/ferraille/pilot.ts');
const name = data.name ?? 'niveau';
try {
    const rank = Number.isInteger(data.ferraille) ? data.ferraille : 0;
    const { ferraille: _rank, ...level } = data;
    LEVELS[rank] = level;
    const game = new Engine();
    game.loadLevel(rank);
    const limit = 60 * 60 * 5; // cinq minutes de jeu simulé
    let frame = 0;
    for (; frame < limit && game.status === 'playing'; frame++) {
        pilot(game);
        game.step(DT);
    }
    const won = game.status === 'won';
    if (won) console.log(`OK ${name} gagné en ${frame} images, ${game.state.lives} vie(s) restante(s)`);
    else console.log(`ÉCHEC ${name} : ${game.status === 'lost' ? 'pilote vaincu' : `non terminé en ${limit} images`}`);
    process.exitCode = won ? 0 : 1;
} catch (error) {
    console.log(`ÉCHEC ${name} : ${error instanceof Error ? error.message : String(error)}`);
    process.exitCode = 1;
}
