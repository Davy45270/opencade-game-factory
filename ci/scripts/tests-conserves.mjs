#!/usr/bin/env node
// ARCH-001 E030 dans la CI d'un jeu, BLOQUANT : « les tests instables sont identifiés, non masqués ; aucune
// suppression de test pour faire passer la CI ». Compare la base et HEAD :
//   - fichier de test supprimé (un renommage n'en est pas un) ou moins de cas `it(` / `test(` : échec « tests-retires » ;
//   - un test masqué de plus (.skip, .only, .fixme, .todo, xit(, xdescribe() : échec « tests-masques » ;
//   - dérogation : un commit de base..HEAD porte le trailer `Tests-Retires: HL-n 7-n` (décision tracée) ;
//   - base absente du clone : échec « base-indisponible » (rien de prouvé = pas de vert muet).
// usage : node .woodpecker/usine/tests-conserves.mjs [--base <réf>]   (défaut : merge-base avec origin/<cible> sur une
// PR, puis CI_PREV_COMMIT_SHA, puis HEAD~1). Rapport : tests-conserves-rapport.json.
import { execFileSync } from "node:child_process";
import { writeFileSync } from "node:fs";

const RAPPORT = "tests-conserves-rapport.json";
const FICHIER_TEST = /(^|\/)(tests?|__tests__|e2e)\/.*\.[cm]?[jt]sx?$|\.(test|spec)\.[cm]?[jt]sx?$/;
const CAS = /(?<![\w.$])x?(?:it|test)(?:\.(?:skip|only|fixme|todo|concurrent|fails))?\s*\(/g;  // un test masqué reste un cas
const MASQUE = /(?<![\w$])(?:(?:it|test|describe)\.(?:skip|only|fixme|todo)\b|x(?:it|describe)\s*\()/g;
const DEROGATION = /^Tests-Retires:\s*(HL-[0-9]+ 7-[0-9]+)\s*$/m;

function git(...args) {
  return execFileSync("git", args, { encoding: "utf8", maxBuffer: 1 << 28, stdio: ["ignore", "pipe", "ignore"] });
}

function ecrire(rapport) {
  writeFileSync(RAPPORT, JSON.stringify(rapport, null, 1) + "\n");
  console.log(`tests conservés : ${rapport.status}`);
  console.log(`--- ${RAPPORT} ---\n${JSON.stringify(rapport)}`);
  if (!["ok", "derogation"].includes(rapport.status)) {
    console.log("ÉCHEC : un test supprimé ou masqué ne fait pas passer la CI (ARCH-001 E030). Un test instable se signale ; "
                + "un retrait voulu porte le trailer « Tests-Retires: HL-n 7-n » (décision tracée).");
    process.exit(1);
  }
  process.exit(0);
}

function revision(ref) {
  try {
    return git("rev-parse", "--verify", "--end-of-options", `${ref}^{commit}`).trim();
  } catch {
    return null;
  }
}

function inventaire(commit) {
  const fichiers = git("ls-tree", "-r", "--name-only", commit).split("\n")
    .filter((c) => c && !c.split("/").includes("node_modules") && FICHIER_TEST.test(c));
  let cas = 0, masques = 0;
  for (const f of fichiers) {
    const texte = git("cat-file", "-p", `${commit}:${f}`);
    cas += (texte.match(CAS) || []).length;
    masques += (texte.match(MASQUE) || []).length;
  }
  return { fichiers: fichiers.length, cas, masques };
}

function baseParDefaut() {
  const cible = process.env.CI_COMMIT_TARGET_BRANCH;
  if (cible && process.env.CI_PIPELINE_EVENT !== "push" && /^[A-Za-z0-9._/-]+$/.test(cible) && !cible.startsWith("-") && !cible.includes("..")) {
    try { git("fetch", "-q", "origin", `+refs/heads/${cible}:refs/remotes/origin/${cible}`); } catch { /* vu au merge-base */ }
    try {
      return git("merge-base", "HEAD", `origin/${cible}`).trim();
    } catch { /* branche cible absente du clone : on tente la suite */ }
  }
  return process.env.CI_PREV_COMMIT_SHA || "HEAD~1";
}

const args = process.argv.slice(2);
const i = args.indexOf("--base");
const demandee = i >= 0 ? args[i + 1] : baseParDefaut();
const base = revision(demandee);
const head = revision("HEAD");
if (!base || !head) ecrire({ status: "base-indisponible", base: demandee });
const avant = inventaire(base), apres = inventaire(head);
const fichiersSupprimes = git("diff", "--name-only", "--diff-filter=D", "-M", base, head).split("\n")
  .filter((c) => c && FICHIER_TEST.test(c) && !c.split("/").includes("node_modules")).sort();
const messages = git("log", "--format=%B%x00", `${base}..${head}`).split("\0");
const derogation = messages.map((m) => (m.match(DEROGATION) || [])[1]).find(Boolean) || null;
let status = "ok";
if (fichiersSupprimes.length || apres.cas < avant.cas) status = "tests-retires";
else if (apres.masques > avant.masques) status = "tests-masques";
if (status !== "ok" && derogation) status = "derogation";
ecrire({ status, base, head, avant, apres, fichiersSupprimes, derogation });
