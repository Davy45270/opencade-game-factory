# Aucun workflow Forgejo Actions, volontairement

La CI de la forge est **Woodpecker** (`.woodpecker/*.yml`). Le workflow `.github/workflows/usine.yml` sert la copie
publique sur GitHub.

Forgejo Actions lit le PREMIER dossier qui existe parmi `.forgejo/workflows`, `.gitea/workflows` et
`.github/workflows`. Sans ce dossier, il prenait le workflow GitHub et posait sur chaque commit des statuts
« usine / registre » et « usine / briques » restés en attente pour toujours (aucun runner Forgejo `ubuntu-24.04`).
Ce dossier existe donc, sans aucun `.yml` : Forgejo s'y arrête et ne lance rien (HL-525, oracle
`tests/github/test_forgejo_sans_actions.py`).
