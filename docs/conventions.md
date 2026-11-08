# Conventions du projet Paresia

Version du document : 0.1.19 · 2026-11-08. Public : développeur, contributeur. S'applique à toute contribution.

## Sommaire

Versions · Changements, décisions et registre · Branches et commits · Arborescence · Code · Tests · Documentation · Normes et usages de référence · Licence

## Versions

- Un seul numéro pour tout l'ensemble, dans `VERSION` : `A.B.C[-préversion]`.
  - A : version majeure (0 jusqu'à la 1.0.0, qui réunit toutes les fonctionnalités attendues).
  - B : ajout de fonctionnalités, modifications importantes ; chaque jalon monte la version mineure.
  - C : corrections mineures, correctifs.
  - Les numéros antérieurs `3.0.0-alpha.N` ne subsistent que dans l'historique.
- Étiquettes Git : `v0.1.0`, `v0.2.0`… `v1.0.0`, posées par le mainteneur.
- Chaque fichier source porte un en-tête avec son rôle, ses dépendances et un « Suivi des versions » (une ligne par version : numéro, date ISO, changement). Le numéro d'un fichier modifié prend la valeur de `VERSION` au moment de la fusion.
- Le protocole entre démons a son propre numéro, indépendant de celui du produit (`jumeaux/1`, champ `proto` de chaque message, `docs/protocole.md`, § 3). L'API HTTP d'administration n'a pas de numéro propre à ce jour.

## Changements, décisions et registre

- Chaque changement livré ou décision qui modifie le projet fait monter `VERSION` d'un cran (correctif : `0.1.0` devient `0.1.1` ; jalon : `0.1.x` devient `0.2.0`), au numéro que donne le mainteneur.
- Chaque document modifié prend le numéro courant de `VERSION`. Pas de renumérotation rétroactive.
- Un retour en arrière est une décision comme une autre : il monte `VERSION` et s'inscrit au registre. L'historique n'est pas réécrit.
- `CHANGELOG.md` : une section par version, avec la date et un résumé, et la décision (`Dxx`) concernée.
- `docs/decisions.md` : une fiche par décision, avec la date, l'énoncé court, la version qui l'introduit, les composants touchés, les conséquences d'un retour en arrière et le statut (en vigueur, remplacée par `Dxx`, à évaluer). Une décision remplacée reste au registre.

## Branches et commits

- `main` : branche des versions publiées, gérée par le mainteneur.
- Les contributions passent par une demande de fusion vers la branche de développement indiquée par le mainteneur (`CONTRIBUTING.md`, § 2). Fusion sans avance rapide (`git merge --no-ff`).
- Message de commit : une première ligne courte, à l'impératif, puis un corps qui explique le pourquoi. Exemple : « Ajoute la vérification du jeton à Romulus ».
- Pas de réécriture d'historique publié.

## Arborescence

```
Paresia/
├── VERSION  README.md  INSTALL.md  CONTRIBUTING.md  CHANGELOG.md  SECURITY.md  LICENSE
├── server/                 Paresia-server
│   ├── commun/             socle commun : protocole jumeaux/1, configuration, journal, démon, métriques
│   ├── romulus/            backend-admin : point de contact, aiguillage
│   ├── pollux/             backend-admin : présence, pollux-session
│   ├── bunkerd/            backend-admin : bunker NIP-46
│   ├── nisaba/             backend-admin : journal légal
│   ├── remus/              backend-relais : exécution des fonctions du relais
│   ├── castor/             backend-relais : présence du relais
│   ├── strfry/             plugin d'écriture du journal légal (exécuté dans le conteneur strfry)
│   ├── sauvegarde/         outil de sauvegarde des procédures
│   ├── bin/                lanceurs
│   └── conf/               paresia.conf et paresia-relais.conf (exemples complets de configuration)
├── deploy/                 fichiers installés sur une machine, à l'image de son arborescence
│   ├── backend-admin/      unités, surcharge de configuration, sshd, déclarations de services, scripts, procédures
│   └── backend-relais/     unités, nftables, sudoers, strfry.conf, procédures
├── admin/                  Paresia-admin
│   ├── app/                application de bureau (PyQt6)
│   └── web/                interface /admin/ (HTML, JS, CSS statiques)
├── i18n/                   fr-FR.json, en-US.json (installés dans /usr/local/share/paresia/i18n/)
├── docs/                   documentation (index : docs/README.md), man/, plugins/, wiki/
├── tests/                  pytest (unitaires et intégration) ; tests/vecteurs/ : vecteurs publiés marqués ; tests/banc/ : banc d'essai
└── tools/                  crochets Git et outils de développement
```

L'arborescence peut évoluer ; tout changement met ce fichier à jour. L'emballage Docker (après la 1.0) n'est pas encore créé.

## Code

- Python 3.13 (Debian 13), 3.11 au moins ; bibliothèque standard d'abord ; sinon paquet Debian 13 ; sinon dépendance épinglée, licence compatible AGPL-3.0-or-later vérifiée et notée dans `docs/licences-tierces.md`. Aucune dépendance ni outil requis propriétaire (voir § Licence).
- Aucune valeur d'environnement en dur (chemins, hôtes, ports) : fichier de configuration, puis variables d'environnement.
- Fichiers de configuration livrés complets, jamais par fragments à recopier.
- **Noms en minuscules** : démons, composants et identifiants en minuscules ; aucune majuscule dans le nom d'un fichier livré, sauf exception justifiée par les bonnes pratiques : `README.md`, `LICENSE`, `CHANGELOG.md`, `CONTRIBUTING.md`, `SECURITY.md`, `INSTALL.md`, `VERSION`, noms imposés par un outil, étiquettes de langue BCP 47 (`fr-FR`). Contrôle : `git ls-files | grep "[A-Z]"` ; chaque nom restant a sa justification.
- Configuration en couches (D29), ordre de priorité croissant : `/etc/paresia/paresia.conf`, `/etc/paresia/conf.d/*.conf` (ordre lexical, préfixe `NN-`), puis pour les programmes lancés par un utilisateur `$XDG_CONFIG_HOME/paresia/*.conf` (défaut `~/.config/paresia/`), puis variables `PARESIA_*`. Format INI, une section par composant. Les démons n'ont pas de couche utilisateur ; `pollux-session` ignore l'environnement fourni par le client. Sections `[<composant>.<domaine>]` ; `--config` ou `PARESIA_<COMPOSANT>_CONFIG` remplace les couches fichier. Détail : `docs/configuration.md`.
- Aucun texte affiché en dur : clés des catalogues `i18n/<langue>.json`. Les démons renvoient des codes stables (`token_missing`, `identity_locked`…).
- Journaux : une ligne JSON par événement sur la sortie standard ; codes stables, jamais traduits ; jamais de secret.
- Tout texte reçu de l'extérieur est nettoyé des caractères de contrôle avant affichage ; l'interface web n'utilise que `textContent`.
- Comparaisons de jetons en temps constant (`hmac.compare_digest`). Refus par défaut. Entrées validées par liste blanche.
- Variables sensibles effacées après usage autant que le langage le permet ; aucun secret en argument de commande ni en variable d'environnement.

## Tests

- pytest ; un test au moins par critère d'acceptation.
- Clés et identités de test générées pour l'occasion.
- Les tests d'intégration n'ouvrent aucune connexion réseau sortante ; démons lancés sur des sockets temporaires.
- La suite complète passe avant toute fusion (`pytest -q`, CI GitHub). Détail : `docs/developpement.md`, § 5.

## Documentation

- Pages de manuel en format mdoc dans `docs/man/` : section 1 (commandes utilisateur), 5 (formats de fichiers), 8 (démons et administration).
- `README.md` court, aux sections classiques ; les détails sont dans `docs/` (index : `docs/README.md`).
- **Wiki** : guide vulgarisé mais précis et exhaustif pour les administrateurs auto-hébergés et semi-professionnels et les administrateurs de relais Nostr. Il est écrit dans `docs/wiki/` (Markdown, une page par sujet, sommaire `Accueil.md`, liens relatifs entre pages), donc versionné avec le code ; sa publication sur le wiki du dépôt n'en est qu'une copie. Chaque page cite sa source dans le dépôt, marque « à venir » ou « non établi » ce qui n'est pas livré, et ne contient ni secret ni référence à une installation réelle (noms et adresses d'exemple : RFC 5737, RFC 2606).
- La documentation est tenue à jour avec le code : toute fusion qui change ce que voit un administrateur met à jour la page de wiki concernée.
- `CONTRIBUTING.md` (comment contribuer), `INSTALL.md` (installation), `CHANGELOG.md` (Keep a Changelog 1.1.0, en français), `SECURITY.md` (modèle de menace).
- Toute option, variable de configuration ou code d'erreur ajouté est documenté dans la même modification.
- **Fichiers livrés** : un fichier livré (code, unités, configuration, procédures, documentation, pages de manuel, catalogues) ne cite ni identifiant de tâche, ni lot, ni rôle d'agent, ni fiche, ni identifiant d'avis (D101). Les décisions `D<n>` de `docs/decisions.md` restent citables.
- Chaque document porte un public, un objet et, s'il est long, un sommaire.

## Normes et usages de référence

La documentation applique les normes et usages établis, et les cite. Une norme n'est citée qu'avec un numéro certain ; sinon elle est marquée « à vérifier ».

| Sujet | Norme ou usage | Application |
| --- | --- | --- |
| Mots normatifs | RFC 2119 et RFC 8174 | DOIT, NE DOIT PAS, DEVRAIT, NE DEVRAIT PAS, PEUT, en capitales (MUST, SHOULD, MAY en anglais) |
| Dates et heures | ISO 8601 | `AAAA-MM-JJ` ; heure avec décalage (`+01:00`) |
| Versions | Semantic Versioning 2.0.0 | `0.MINEUR.CORRECTIF` est conforme (version initiale de développement, 0.y.z, selon le § 4) ; `0.1.0` est la première version |
| Journal | Keep a Changelog 1.1.0 | versions récentes en tête ; `[Non publié]` ; catégories Ajouté, Modifié, Retiré, Corrigé, Sécurité (libellés français : à vérifier contre la traduction officielle) |
| Adresses d'exemple | RFC 5737 (IPv4), RFC 3849 (IPv6) | 192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24 ; 2001:db8::/32 |
| Domaines d'exemple | RFC 2606 | `example.org`, `bunker.example.org` |
| Pages de manuel | mdoc(7), format retenu ; man-pages(7) pour les sections et la structure | sections 1, 5, 8 ; `mandoc -T lint` |
| Chemins | FHS 3.0 ; spécification XDG Base Directory (freedesktop.org) | `/etc/paresia`, `/usr/local/lib/paresia`, `/var`, `$XDG_CONFIG_HOME` |
| Formats | RFC 8259 (JSON) ; RFC 3629 (UTF-8) ; NDJSON : un objet par ligne, fin de ligne LF | `docs/protocole.md`, § 2 |
| HTTP et cookies | RFC 9110 (dont 413 « Content Too Large ») ; RFC 9112 ; RFC 6265 | `docs/protocole.md`, § 9 |
| Étiquettes de langue | RFC 5646 (BCP 47), forme `fr-FR` | catalogues `fr-FR` et `en-US` (D58) |
| Fichiers du dépôt | conventions GitHub : README, CONTRIBUTING, CHANGELOG, SECURITY, LICENSE ; RFC 9116 (security.txt) à la publication | voir `SECURITY.md` |
| Licence | GNU AGPL v3 ; identifiant SPDX `AGPL-3.0-or-later` | en-tête SPDX dans chaque fichier source |
| Tunnels SSH | RFC 4254 ; redirections de sockets Unix : extension OpenSSH (à vérifier) | `docs/cahier-des-charges.md`, § Réseau, lighttpd et tunnel SSH |
| Nostr | NIP-01, NIP-46, NIP-49 ; BIP-340 | `docs/cahier-des-charges.md`, § Administration de bunkerd |

Structure du README : description, état, fonctionnalités, architecture, prérequis, installation, configuration, utilisation, sécurité, documentation, contribution, versions, licence. Une section sans contenu disponible dit « à venir ». Les détails vont dans `docs/`.

## Licence

AGPL-3.0-or-later (GNU Affero General Public License, version 3 ou ultérieure ; identifiant SPDX `AGPL-3.0-or-later`), décision D30. Texte : `LICENSE`, copie du texte officiel. Chaque fichier source livré porte l'en-tête :

```
SPDX-License-Identifier: AGPL-3.0-or-later
```

Tout apport est publié sous cette licence (`CONTRIBUTING.md`). Les licences des dépendances sont listées dans `docs/licences-tierces.md` ; elles sont à vérifier.

### Dépendances et outils

Par défaut, aucune dépendance propriétaire. Une exception n'est possible qu'en cas d'impasse, par décision du mainteneur, inscrite au registre (`docs/decisions.md`) avec sa justification et l'alternative libre étudiée. Toute dépendance est compatible avec AGPL-3.0-or-later ; une licence permissive est admise si elle est compatible.

Les outils de développement ne sont pas des dépendances de Paresia : ni distribués, ni requis pour l'installer ou l'exécuter. Leur licence n'appelle ni exception ni alternative.
