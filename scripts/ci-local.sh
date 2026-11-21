#!/usr/bin/env bash
# Rejoue en local, SANS conteneur, les commandes d'un pipeline Woodpecker du registre, dans le même
# ordre ; s'arrête au premier échec, comme Woodpecker.
#
#   scripts/ci-local.sh validate          .woodpecker/validate.yml
#   scripts/ci-local.sh build-index       .woodpecker/build-index.yml
#   scripts/ci-local.sh scan              .woodpecker/scan.yml (réseau : copies GitHub publiques)
#   scripts/ci-local.sh release           .woodpecker/release.yml
#   scripts/ci-local.sh controle-release  contrôle du SBOM et du manifeste de licences (appelé par release.yml)
#
# Variables :
#   CI_LOCAL_BASE=<ref git>       rejoue aussi l'étape `controle-de-pr` (événement pull_request) contre <ref>
#   CI_LOCAL_SANS_GITLEAKS=1      gitleaks absent : l'étape `secrets` est déclarée SAUTÉE au lieu d'échouer
#
# Interpréteur : .venv/bin/python3 s'il existe (comme la CI), sinon python3 du système. Le script ne
# crée ni n'installe rien. Aucun secret.
set -euo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RACINE"
PIPELINE="${1:-}"
SAUTEES=()

etape() { printf '\n=== %s : %s ===\n' "$PIPELINE" "$1"; }

activer() {
  if [ -f .venv/bin/activate ]; then
    # shellcheck disable=SC1091
    . .venv/bin/activate
  fi
  echo "python : $(command -v python3) ($(python3 --version 2>&1))"
}

dependances() {
  etape dependances
  activer
  python3 -c 'import PIL, numpy, jsonschema, pytest, xdist' || {
    echo "dépendances absentes : python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-ci.txt"
    exit 4
  }
}

controle_release() {
  etape controle-release
  python3 - <<'PY'
import json, sys
from pathlib import Path

erreurs = []
sbom_chemin = Path("generated/sbom.cdx.json")
try:
    sbom = json.loads(sbom_chemin.read_text(encoding="utf-8"))
except (OSError, ValueError) as e:
    sys.exit(f"SBOM illisible ({sbom_chemin}) : {e}")
if sbom.get("bomFormat") != "CycloneDX":
    erreurs.append(f"bomFormat = {sbom.get('bomFormat')!r}, CycloneDX attendu")
if not str(sbom.get("specVersion", "")).startswith("1."):
    erreurs.append(f"specVersion = {sbom.get('specVersion')!r}")
composants = sbom.get("components") or []
attendus = {l.split("==")[0].strip().lower() for l in Path("requirements.txt").read_text().splitlines()
            if l.strip() and not l.lstrip().startswith("#")}
vus = {str(c.get("name", "")).lower() for c in composants
       if str(c.get("purl", "")).startswith("pkg:pypi/")}
if attendus - vus:
    erreurs.append(f"dépendances de requirements.txt absentes du SBOM : {sorted(attendus - vus)}")

lic_chemin = Path("generated/licenses.json")
try:
    licences = json.loads(lic_chemin.read_text(encoding="utf-8"))
except (OSError, ValueError) as e:
    sys.exit(f"manifeste de licences illisible ({lic_chemin}) : {e}")
if isinstance(licences, list):
    lignes = licences
elif isinstance(licences, dict):
    if "bomFormat" in licences:
        erreurs.append("le manifeste de licences d'assets doit être distinct du SBOM")
    lignes = next((v for v in licences.values() if isinstance(v, list)), [])
else:
    lignes = []
if not lignes:
    erreurs.append("manifeste de licences vide")
for l in (x for x in lignes if isinstance(x, dict)):
    if l.get("publicExport") not in ("allowed", "forbidden"):
        erreurs.append(f"{l.get('id')} : publicExport = {l.get('publicExport')!r}")
    if l.get("publicExport") == "allowed" and (l.get("license") in (None, "unknown") or not l.get("evidence")):
        erreurs.append(f"{l.get('id')} : export public autorisé sans licence prouvée")

for e in erreurs:
    print("ÉCHEC :", e)
print(f"SBOM : {len(composants)} composants ; manifeste de licences : {len(lignes)} assets")
sys.exit(1 if erreurs else 0)
PY
}

case "$PIPELINE" in
  validate)
    dependances
    etape tests-unitaires
    python3 -m pytest -n 4 -q -p no:cacheprovider tests/unit
    etape tests-acceptation
    python3 -m pytest -n 4 -q -p no:cacheprovider tests/acceptance
    etape validate
    ./assetctl validate --json
    if [ -n "${CI_LOCAL_BASE:-}" ]; then
      etape "controle-de-pr (base $CI_LOCAL_BASE)"
      ./assetctl validate --base "$CI_LOCAL_BASE" --json
    else
      SAUTEES+=("controle-de-pr (pull_request seulement ; CI_LOCAL_BASE=<ref> pour le rejouer)")
    fi
    etape atlas
    N=0
    for f in atlases/*.json; do [ -e "$f" ] || continue; ./assetctl validate-atlas "$f" --json || exit 1; N=$((N + 1)); done
    echo "atlas validés $N"
    etape licences-externes
    ./assetctl external audit-licenses --json
    etape doublons
    ./assetctl duplicates --json
    etape secrets
    if command -v gitleaks >/dev/null; then
      gitleaks detect --source . --no-banner --redact
    elif [ "${CI_LOCAL_SANS_GITLEAKS:-}" = 1 ]; then
      SAUTEES+=("secrets (gitleaks absent, CI_LOCAL_SANS_GITLEAKS=1)")
    else
      echo "gitleaks absent : installer gitleaks v8.30.1, ou CI_LOCAL_SANS_GITLEAKS=1 pour sauter l'étape en le disant"
      exit 4
    fi
    ;;
  build-index)
    dependances
    etape index
    ./assetctl index --json
    git diff --stat --exit-code -- generated/
    test -z "$(git status --porcelain --untracked-files=all -- generated/)" || { git status --short -- generated/; exit 1; }
    ;;
  scan)
    dependances
    etape reconciliation
    ./assetctl scan-repos --verify --dry-run --provider github --only opencade opencadkid echecs-kid pestouille-rpg capsule-panic six-de-chaque cozy-room-sort petit-astronome tictac --json
    ;;
  release)
    dependances
    etape sbom-et-licences
    ./assetctl index --json
    ./assetctl sbom --out generated/sbom.cdx.json
    controle_release
    ;;
  controle-release)
    controle_release
    ;;
  *)
    sed -n '2,16p' "$0"
    exit 2
    ;;
esac

printf '\n=== %s : OK ===\n' "$PIPELINE"
for s in "${SAUTEES[@]+"${SAUTEES[@]}"}"; do echo "SAUTÉE : $s"; done
