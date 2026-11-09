# Documentation Paresia

Version du document : 0.1.19 · 2026-11-08.

Suivi, 2026-11-09 : installation classée en noyau et greffons, renvoi au wiki pour installer ; numéro du document inchangé (aucun numéro donné).

Index des documents du projet. Le README, à la racine, est le premier contact ; les détails sont ici. Tout est versionné avec le code. Le wiki est écrit dans [`docs/wiki/`](wiki/Accueil.md) ; sa publication sur le wiki du dépôt n'est qu'une copie de ces fichiers.

**`docs/` est la référence technique ; pour installer, allez au wiki** : [Accueil du wiki](wiki/Accueil.md), parties « Installer le noyau » (Paresia : yin, yang, lighttpd, HAProxy, client) et « Installer les greffons » (strfry, Nisaba, bunker).

Public : **A** = administrateur, **D** = développeur ou contributeur.

## Pour comprendre

| Document | Une ligne | Public |
| --- | --- | --- |
| [README](../README.md) | présentation, état, feuille de route | A, D |
| [Accueil du wiki](wiki/Accueil.md) | guide vulgarisé de l'administrateur (sommaire du wiki ; chaque page marque son « à venir ») | A |
| [Architecture](architecture.md) | composants, comptes et flux | A, D |
| [Cahier des charges](cahier-des-charges.md) | spécification, qui fait foi | D |
| [Décisions](decisions.md) | décisions, source, conséquence d'un retour en arrière | D |
| [CHANGELOG](../CHANGELOG.md) | historique des versions | A, D |
| [SECURITY](../SECURITY.md) | modèle de menace (provisoire) et signalement | A, D |

## Pour installer et exploiter

Les guides d'installation sont dans le wiki, classés en noyau et greffons (voir l'[Accueil du wiki](wiki/Accueil.md)). Cette liste les rappelle, avec la référence technique.

**Noyau (Paresia)**

| Document | Une ligne | Public |
| --- | --- | --- |
| [Prérequis](prerequis.md) | paquets, versions et modules par machine | A |
| [INSTALL](../INSTALL.md) | guide « Installer » : deux machines Debian 13, du paquet au tunnel (alpha), avec la mise à jour d'une installation existante (§ 12) | A |
| [Installer et configurer lighttpd](wiki/Installer-lighttpd.md) | installer le serveur web lighttpd de yang et le régler pour Paresia, avant le client | A |
| [Régler HAProxy pour Paresia](wiki/Installer-haproxy.md) | exigences du projet envers le frontal HAProxy (adresse du client, en-têtes à ne pas poser) | A |
| [Serveur web](serveur-web.md) | exigences pour le serveur web (lighttpd) et le proxy (HAProxy) devant l'interface, extrait d'exemple et vérifications (Paresia n'installe ni l'un ni l'autre) | A |
| [Installer le client](wiki/Installer-client.md) | installer le client Paresia-admin sur le poste de l'administrateur | A |

**Greffons**

| Document | Une ligne | Public |
| --- | --- | --- |
| [Installer le relais strfry](wiki/Installer-strfry.md) | préparer le conteneur Docker `strfry` de yin (image, configuration), avant l'étape 6 d'INSTALL | A |
| [Installer `nak`](wiki/Installer-nak.md) | installer `nak` sur le poste des clés privées (création d'une clé) et sur yang (bunker) | A |
| [Greffon strfry](plugins/strfry.md) | greffon du relais strfry : actions livrées (trois fonctions de base) et contrat prévu | A, D |

La procédure d'installation de bunkerd et de Nisaba n'est pas encore écrite (démons écrits, unités non livrées).

**Exploitation et référence**

| Document | Une ligne | Public |
| --- | --- | --- |
| [Exploitation](exploitation.md) | démarrer, lire les journaux, feu de Castor, tunnel, retours arrière | A |
| [Configuration](configuration.md) | configuration en couches, codes d'erreur, emplacements | A, D |
| [Pages de manuel](man/README.md) | pages de manuel (liste dans ce fichier) | A |
| [Journal légal : ACL](installation-journal-legal-acl.md) | procédure pas à pas des scripts `journal-legal-*` | A |

## Pour développer

| Document | Une ligne | Public |
| --- | --- | --- |
| [Protocole](protocole.md) | messages NDJSON entre démons, `jumeaux/1` | D |
| [Exigences du client](exigences-client.md) | ce que le client doit implémenter, avec source et état côté serveur | D |
| [Conventions](conventions.md) | versions, branches, code, documentation, normes, licence | D |
| [Développement](developpement.md) | poste de développement, tests, CI, garde contre les secrets, contenu du dépôt, contrats des briques communes | D |
| [Licences tierces](licences-tierces.md) | licences des dépendances et outils | D |
| [CONTRIBUTING](../CONTRIBUTING.md) | comment contribuer | D |

La procédure d'installation de bunkerd n'est pas encore écrite (démon écrit, unité non livrée).

## Règles de documentation

- Chaque document porte le numéro de `VERSION` au moment de sa modification, un public (A administrateur, D développeur) et un objet.
- Les normes citées sont listées dans [`conventions.md`](conventions.md#normes-et-usages-de-référence), § « Normes et usages de référence ».
- Les dates sont au format ISO 8601.
