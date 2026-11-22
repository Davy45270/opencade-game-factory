# Migration depuis Drive

`./specctl inscrire-drive` inscrit un document Drive à importer, et `./specctl import` crée ou met à jour les fiches. La liste des documents en attente reste dans `registry/drive-a-importer.json`, parce qu'elle est publiée dans le même lot atomique que le registre.
