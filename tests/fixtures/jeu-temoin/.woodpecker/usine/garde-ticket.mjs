#!/usr/bin/env node
// Garde « identifiant de ticket » commune aux jeux : aucune référence de backlog (forme MAJUSCULES-chiffres) dans un
// texte public. Relevé du 19/11 : le motif prenait la licence CC-BY-4.0 pour un ticket (« BY-4 »).
// Correctif sans affaiblir le garde : le motif ne change pas ; seuls les identifiants de licence SPDX de la LISTE
// ci-dessous, écrits en entier et isolés, sont retirés de la ligne avant le test. « CC-BY-4 », « XCC-BY-4.0 » ou
// « CC-BY-4.0 AB-9 » restent refusés.
// Module : import { estTicket, TICKET, LICENCES_SPDX } from './garde-ticket.mjs'
// CLI    : node garde-ticket.mjs <fichier>...   imprime fichier:ligne de chaque violation ; code 1 s'il y en a, 2 = usage.
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

// Bornes explicites (revue du 19/11) : « _ » est une frontière (\b ne la voyait pas : « x_AB-12 » passait).
export const TICKET = /(?<![A-Za-z0-9])[A-Z]{2,10}-\d+(?![0-9])/;
// Identifiants SPDX (https://spdx.org/licenses/) qui contiennent la forme MAJUSCULES-chiffres. Liste fermée : une
// licence absente reste refusée jusqu'à son ajout ici, avec un test.
export const LICENCES_SPDX = [
    'CC-BY-1.0', 'CC-BY-2.0', 'CC-BY-2.5', 'CC-BY-3.0', 'CC-BY-4.0',
    'CC-BY-SA-1.0', 'CC-BY-SA-2.0', 'CC-BY-SA-2.5', 'CC-BY-SA-3.0', 'CC-BY-SA-4.0',
    'CC-BY-NC-4.0', 'CC-BY-ND-4.0', 'CC-BY-NC-SA-4.0', 'CC-BY-NC-ND-4.0',
    'GPL-2.0', 'GPL-3.0', 'LGPL-2.1', 'LGPL-3.0', 'AGPL-3.0', 'MPL-2.0', 'EPL-2.0', 'EUPL-1.2', 'OFL-1.1',
];
const echapper = (t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
// Licence ENTIÈRE et isolée : ni « _ » collé, ni « .<chiffre> » à droite (« CC-BY-4.0.1 » n'est pas dans la liste).
const SPDX = new RegExp(`(?<![A-Za-z0-9_.+-])(?:${LICENCES_SPDX.map(echapper).join('|')})(?:-only|-or-later|\\+)?(?![A-Za-z0-9_-]|\\.[A-Za-z0-9])`, 'g');

export const estTicket = (ligne) => TICKET.test(String(ligne).replace(SPDX, ' '));

if (import.meta.url === pathToFileURL(process.argv[1] || '').href) {
    const fichiers = process.argv.slice(2);
    if (!fichiers.length) { console.error('usage : node garde-ticket.mjs <fichier>...'); process.exit(2); }
    let n = 0;
    for (const f of fichiers) {
        readFileSync(f, 'utf8').split('\n').forEach((l, i) => { if (estTicket(l)) { console.log(`${f}:${i + 1}`); n += 1; } });
    }
    process.exit(n ? 1 : 0);
}
