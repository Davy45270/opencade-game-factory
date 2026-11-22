# Décisions d'intégration (ARCH-001 § 3.2)

Une ADR par arbitrage de David sur l'intégration de l'usine : HL-525 7-2955 (relecture ARCH-001, REG-003, BB-001)
et HL-538 7-2949 (relecture OPS-001, EXT-001, EXT-002). Le texte de l'arbitrage est cité ; la décision fait foi dans
le commentaire YouTrack, l'ADR en garde la trace versionnée avec ses alternatives et son retour arrière.
Contrôle : `specs/tests/contracts/test_e014_adr_integration.py`.

| ADR | Décision | Source |
|---|---|---|
| [ADR-0001](ADR-0001-specs-source-de-verite.md) | Specs : import initial depuis la doc, puis versionnées dans l'usine | HL-525 7-2955 |
| [ADR-0002](ADR-0002-depot-unique-usine.md) | Un seul dépôt usine : assets, niveaux, specs et briques | HL-525 7-2955 |
| [ADR-0003](ADR-0003-decouverte-d-abord-en-parallele.md) | Découverte de l'existant tout de suite, en parallèle des chantiers | HL-525 7-2955 |
| [ADR-0004](ADR-0004-ops-reutiliser-l-existant.md) | OPS-001 : réutiliser Prometheus, VictoriaLogs et Grafana | HL-538 7-2949 |
| [ADR-0005](ADR-0005-ext001-assets-externes-si-le-style-colle.md) | EXT-001 : un asset externe partout si le style colle | HL-538 7-2949 |
| [ADR-0006](ADR-0006-ext002-fait-foi-dans-le-registre.md) | EXT-002 fait foi, dans le registre ; un validateur par premier jeu | HL-538 7-2949 |
| [ADR-0007](ADR-0007-priorites-jeux-registre-puis-tower.md) | Priorités : jeux et registre, puis Tower ; 2e Codex si l'onduleur le permet | HL-538 7-2949 |
| [ADR-0008](ADR-0008-niveaux-algorithmes-existants.md) | Niveaux : réutiliser Sturgeon, clingo, python-tcod, Tiled et l'IA des jeux ; pilote Ferraille validé, extension décidée | HL-538 7-3320, HL-525 7-3321 |
