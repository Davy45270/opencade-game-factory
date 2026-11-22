# Atlas des planches et écrans de contrôle

## Besoin

Charger les atlas découpés des planches de David, rejouer le parcours jusqu'à un écran donné, vérifier la
transparence en CI, garder les réglages et piloter les commandes à la manette.

## Candidats

| Besoin | Candidat | Licence | Choix |
|---|---|---|---|
| Rendu des atlas | Phaser, chargeur JSON hash | MIT | Réutiliser le moteur de rendu déjà chargé, les pivots et les tags livrés |
| Rendu des atlas | PixiJS, spritesheets | MIT | Ajouterait un second moteur de rendu |
| Rejeu | Journal et vérification d'empreinte du moteur | MIT | Exporter les commandes du bot du slice et les appliquer par le rejeu du moteur |
| Rejeu | Sauvegarde de fixture sérialisée | MIT | Ne restitue pas le parcours qui mène à l'écran |
| Alpha en CI | ImageMagick | Licence ImageMagick | Utilisé pour la production, absent de l'image Node des contrôles |
| Alpha en CI | Node zlib et lecture de l'export PNG RGBA | MIT | Vérifie les pixels de référence sans dépendance supplémentaire ; le WebP livré n'est verrouillé que par empreinte |
| Alpha en CI | `@jsquash/webp` 1.5.0 (npm, développement seulement) | Apache-2.0 | Décode le WebP livré lui-même (WebAssembly, sans binaire natif) pour la porte G3 |
| Réglages | localStorage natif | API navigateur | Adapté à quelques valeurs, séparé de la sauvegarde IndexedDB |
| Réglages | IndexedDB natif | API navigateur | Transaction et ouverture de base inutiles pour un seul enregistrement |
| Manette | Gamepad API | API navigateur | Pilote le focus des commandes HTML, même avant une partie |
| Manette | Entrée Gamepad de Phaser | MIT | Fournit les boutons de la scène, avec un pont supplémentaire vers les commandes HTML |

## Choix

Phaser et son chargeur JSON hash pour le rendu (déjà chargé, garde pivots et tags) ; le journal et l'empreinte du
moteur pour le rejeu ; pour la transparence, l'export PNG lu par zlib dans `npm run assets:check` et le WebP livré
décodé par `@jsquash/webp` dans la porte G3 ; `localStorage` pour les réglages ; la Gamepad API branchée sur le
focus des commandes HTML.

## Risques

- Le contrôle de l'export PNG ne prouve rien sur le WebP livré : c'est le décodage du WebP qui fait foi.
- Une table de découpe qui déclare un cadre « non détouré » le soustrait au contrôle d'alpha.

## Tests de qualification

- `tests/unit/atlas-generation.test.ts` : pixels des atlas livrés, cadres, durées et provenance.
- `tests/unit/web-assets.test.ts` : empreintes, manifestes, tags et textures employées.
- `tests/unit/rejeu-web.test.ts`, `tests/unit/options-web.test.ts` : rejeu jusqu'à un écran et réglages.
