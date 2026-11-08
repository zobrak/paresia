# Documentation Paresia

Version du document : 0.1.19 · 2026-11-08.

Index des documents du projet. Le README, à la racine, est le premier contact ; les détails sont ici. Tout est versionné avec le code. Le wiki est écrit dans `docs/wiki/` ; sa publication sur le wiki du dépôt n'est qu'une copie de ces fichiers.

Public : **A** = administrateur, **D** = développeur ou contributeur.

## Pour comprendre

| Document | Une ligne | Public |
| --- | --- | --- |
| `../README.md` | présentation, état, feuille de route | A, D |
| `wiki/Accueil.md` | guide vulgarisé de l'administrateur (sommaire du wiki ; chaque page marque son « à venir ») | A |
| `architecture.md` | composants, comptes et flux | A, D |
| `cahier-des-charges.md` | spécification, qui fait foi | D |
| `decisions.md` | décisions, source, conséquence d'un retour en arrière | D |
| `../CHANGELOG.md` | historique des versions | A, D |
| `../SECURITY.md` | modèle de menace (provisoire) et signalement | A, D |

## Pour installer et exploiter

| Document | Une ligne | Public |
| --- | --- | --- |
| `prerequis.md` | paquets, versions et modules par machine | A |
| `exploitation.md` | démarrer, lire les journaux, feu de Castor, tunnel, retours arrière | A |
| `configuration.md` | configuration en couches, codes d'erreur, emplacements | A, D |
| `man/` | pages de manuel (liste : `man/README.md`) | A |
| `installation-journal-legal-acl.md` | procédure pas à pas des scripts `journal-legal-*` | A |
| `../INSTALL.md` | guide « Installer » : deux machines Debian 13, du paquet au tunnel (alpha), avec la mise à jour d'une installation existante (§ 12) | A |
| `serveur-web.md` | exigences pour le serveur web (lighttpd) et le proxy (HAProxy) devant l'interface, extrait d'exemple et vérifications (Paresia n'installe ni l'un ni l'autre) | A |
| `plugins/strfry.md` | greffon du relais strfry : actions livrées (trois fonctions de base) et contrat prévu | A, D |

## Pour développer

| Document | Une ligne | Public |
| --- | --- | --- |
| `protocole.md` | messages NDJSON entre démons, `jumeaux/1` | D |
| `exigences-client.md` | ce que le client doit implémenter, avec source et état côté serveur | D |
| `conventions.md` | versions, branches, code, documentation, normes, licence | D |
| `developpement.md` | poste de développement, tests, CI, garde contre les secrets, contenu du dépôt, contrats des briques communes | D |
| `licences-tierces.md` | licences des dépendances et outils | D |
| `../CONTRIBUTING.md` | comment contribuer | D |

La procédure d'installation de bunkerd n'est pas encore écrite (démon écrit, unité non livrée).

## Règles de documentation

- Chaque document porte le numéro de `VERSION` au moment de sa modification, un public (A administrateur, D développeur) et un objet.
- Les normes citées sont listées dans `conventions.md`, § « Normes et usages de référence ».
- Les dates sont au format ISO 8601.
