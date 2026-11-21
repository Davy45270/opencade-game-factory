#!/usr/bin/env python3
"""Cadres découpés par pestouille-rpg (25 tables de assets/source/, qui font foi) → assets du registre (HL-538, 21/11).
Pas de redécoupe : la boîte de chaque élément du jeu est reprise telle quelle, sur la planche de David qu'il cite.
Usage : importer_jeu.py <registre> <dépôt-jeu> <dossier-planches-docs> <reçu-de-recherche.json> <dossier-travail>"""
import hashlib, json, subprocess, sys
from pathlib import Path

REG, JEU, DOCS, RECU, TRAV = map(Path, sys.argv[1:6])
sys.path.insert(0, str(REG))
from tools.core.catalog import write_json  # noqa: E402

LIC = "LicenseRef-David-Prive-Tous-Droits-Reserves"
LIC_PREUVE = {"method": "décision du propriétaire", "ref": "HL-538 7-3162",
              "decision": "Dessins de Pestouille fournis par David : privé, tous droits réservés ; publiables à travers "
                          "tout jeu de David qui les emploie (HL-538, 2026-11-21)."}
AUTEUR = "David (dessin fourni par David ; auteur ou outil de création non déclaré)"
EDIT = "sources/editable/pestouille-2026-11-21/jeu"
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
commit = subprocess.run(["git", "-C", str(JEU), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
TRAV.mkdir(parents=True, exist_ok=True); (REG / EDIT).mkdir(parents=True, exist_ok=True)
recu = json.loads(RECU.read_text())
elements, n_tables = {}, 0
for t_path in sorted((JEU / "assets/source").glob("*.decoupe.json")):
    t = json.loads(t_path.read_text())
    planche = DOCS / t["planche"]
    t["planche_sha256"] = sha(planche)
    copie = REG / EDIT / t_path.name
    copie.write_text(json.dumps(t, ensure_ascii=False, indent=1) + "\n")
    r = subprocess.run([str(REG / "assetctl"), "import-sheet", str(planche), "--decoupe", str(copie), "--json"],
                       cwd=REG, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"{t_path.name} -> {r.returncode}\n{r.stdout[-1500:]}")
    d = json.loads(r.stdout); n_tables += 1
    for a, e in zip(d["assets"], t["elements"]):
        elements[a["assetId"]] = (e, t_path.name, t, sha(copie), d["sheetId"])
for aid, (e, table, t, sha_t, sid) in elements.items():
    p = REG / "catalog/assets" / f"{aid}.json"; a = json.loads(p.read_text())
    assert a["family"]["sprite"]["frameName"] == e["id"], (aid, e["id"])
    retouche = [k for k in ("derive", "effacements", "masque_max") if k in e]
    a["description"] = (f"Pestouille RPG — élément « {e['id']} » de la table {table} (planche {t['planche']})"
                        + (f" ; le jeu le retouche ({', '.join(retouche)}) : ici, la découpe brute" if retouche else ""))
    a["tags"] = list(dict.fromkeys(["pestouille", "pestouille-rpg", table.split(".")[0], table.split("-")[0]]))
    ev = f"pestouille-rpg@{commit[:12]}:assets/source/{table} · élément {e['id']} ; copie {EDIT}/{table} (SHA-256 {sha_t})"
    for champ in ("description", "tags"):
        a.setdefault("inference", {})[champ] = {"method": "proven", "confidence": 1, "evidence": [ev]}
    a["originUniverse"] = "pestouille"
    a["inference"]["originUniverse"] = {"method": "proven", "confidence": 1, "evidence": [f"{t['planche']} · planche de la spec Pestouille RPG"]}
    a["license"], a["licenseEvidence"] = LIC, LIC_PREUVE
    a["provenance"].update(type="original-sheet-cut", author=AUTEUR)
    a["provenance"]["evidence"] = [a["provenance"]["evidence"][0], ev,
                                   f"Planche {t['planche']} (SHA-256 {t['planche_sha256']}) fournie par David (sources de la spec, homelab-docs).",
                                   f"Licence de la table du jeu (« {t.get('licence', 'absente')} ») non reprise : décision de David HL-538 7-3162."]
    a["creation"] = {"searchReceipt": {**recu, "rejectedCandidates": []}, "rejectedCandidates": []}
    write_json(p, a)
print(json.dumps({"tables": n_tables, "assets": len(elements), "commit_jeu": commit}))
