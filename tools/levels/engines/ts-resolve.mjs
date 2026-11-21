// Charge les sources TypeScript d'un jeu sans son outillage d'écran : imports sans extension (comme Vite) et
// transpilation par l'outillage du jeu lui-même (`rolldown`, celui de Vite) : le retrait des types de Node ne couvre
// pas tout (propriétés de paramètre).
import { readFileSync } from 'node:fs';
import { createRequire, registerHooks } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';

const game = createRequire(process.cwd() + '/');
const { transformSync } = await import(pathToFileURL(game.resolve('rolldown/experimental')).href);

registerHooks({
    resolve(specifier, context, next) {
        try {
            return next(specifier, context);
        } catch (error) {
            if (!/^\.{1,2}\//.test(specifier) || /\.[cm]?[jt]s$/.test(specifier)) throw error;
            for (const suffix of ['.ts', '/index.ts']) {
                try { return next(specifier + suffix, context); } catch { /* suffixe suivant */ }
            }
            throw error;
        }
    },
    load(url, context, next) {
        if (!url.startsWith('file:') || !url.endsWith('.ts')) return next(url, context);
        const path = fileURLToPath(url);
        const { code, errors } = transformSync(path, readFileSync(path, 'utf8'), { lang: 'ts' });
        if (errors?.length) throw new Error(`${path} : ${errors.map(e => e.message).join(' ; ')}`);
        return { format: 'module', source: code, shortCircuit: true };
    },
});
