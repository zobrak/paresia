# Paresia

État au : 0.1.19, 2026-11-08.

**Paresia est un noyau d'administration à distance, cloisonné et enfichable, fondé sur la présence prouvée.** Un administrateur ne peut agir sur ses services que pendant qu'il prouve sa présence par une clé SSH ; sinon, toute commande est refusée.

> **Alpha : pas en production, à essayer sur des machines jetables.**
>
> **Ce qui marche aujourd'hui** : les démons du serveur (Romulus, Pollux, Castor, Remus, Nisaba, bunkerd) sont écrits et testés ; les scripts d'installation des deux machines, avec leur option de mise à jour d'une installation existante (`INSTALL.md`, § 12), sont écrits et essayés en alpha ; le client a une fenêtre qui ouvre la session de présence (indicateur à trois états) et trois pages du noyau (état, journaux de Paresia, catalogue des actions) ; un greffon strfry de base livre trois fonctions (état, arbres negentropy, redémarrage du conteneur).
>
> **Ce qui ne marche pas encore** : bunkerd et Nisaba n'ont ni unité systemd ni installation livrées ; aucun greffon n'apporte encore de page d'administration au client (relais, bunker, journal légal) ; lighttpd et HAProxy ne sont ni installés ni configurés par Paresia.

## Pour décider d'essayer

- **Ce qu'il faut** : deux machines Debian 13 (une pour l'administration, une pour le relais), un accès SSH entre elles, et une clé SSH tenue par un agent SSH sur votre poste.
- **Ce que vous pouvez voir aujourd'hui** : l'installation des deux côtés, le tunnel, et l'ouverture d'une session de présence prouvée par votre clé (voir [INSTALL.md](INSTALL.md), puis [Premier usage](docs/wiki/Premier-usage.md)). C'est une démonstration du principe.
- **Ce que vous ne pouvez pas faire encore** : administrer un relais strfry, un bunker ou un journal légal depuis le client. Les seules actions réelles sur le relais sont les trois du greffon de base (état, arbres negentropy, redémarrage), sans page dédiée dans le client.
- **Prévoyez** de partir de machines jetables et de lire [SECURITY](SECURITY.md) avant d'exposer quoi que ce soit.

## Limites connues (v0.1)

- **Essais réels partiels** : les scripts d'installation des deux machines et l'ouverture d'une session de présence ont été essayés sur de vraies machines, mais sur une version antérieure à celle-ci. Le code ajouté depuis (mise à jour d'une installation, pages servies, greffon strfry de base, pages du noyau) n'a pas été essayé sur une vraie machine ; il est vérifié par les tests automatisés seulement.
- **Pages du client** : le rendu réel des pages d'administration dans la fenêtre de Paresia-admin n'a pas été essayé.
- **Administration du relais, journaux, bunker** : prévues en v0.2. Aujourd'hui, le greffon strfry de base ne fait que trois choses (état, arbres negentropy en lecture seule, redémarrage du conteneur) et aucun greffon n'apporte de page au client ; depuis la page « Catalogue », une action avec paramètres ne se lance pas.
- **Journal légal** : la consultation (recherche, export) n'est pas livrée ; les actions `legal/*` répondent encore 501 `not_available`. L'état et la vérification passent par `nisaba/state/*`.
- **Services sans unité systemd** : bunkerd et Nisaba n'ont pas d'unité ni d'installation livrées.
- **Serveur web et proxy** : à votre charge ([Serveur web](docs/serveur-web.md)) ; leurs exigences ne sont pas toutes éprouvées (états « établi », « déduit » et « non vérifié » dans ce document).

## Ce que c'est

- **Un noyau en deux couples de jumeaux**, un couple par machine, reliés par un tunnel SSH (liaison chiffrée entre les deux machines) : côté yang (administration) Romulus et Pollux, côté yin (service administré) Remus et Castor. Les démons (programmes de fond) ne font que transporter : commandes d'un côté, présence de l'autre (protocole `jumeaux/1`, le « langage » commun des démons ; voir le [Glossaire](docs/wiki/Glossaire.md)).
- **Un noyau étranger aux produits.** Il ne connaît ni strfry (le relais Nostr), ni Nisaba (journal légal), ni le bunker (signature à distance, NIP-46). Les **greffons** (modules enfichés) déclarent leur compatibilité avec un produit installé à part et ne le livrent pas. Remus reste « bête » : ses capacités viennent des greffons.
- **Un client en deux parties** : un noyau Qt et une interface web, chaque greffon apportant ses propres pages.
- **Deux produits, un numéro de version** : Paresia-server (démons et configurations) et Paresia-admin (client).

## Principes immuables

Refus par défaut, moindre privilège, aucun secret affiché ni journalisé, rien exécuté chez l'administrateur sans son action, licence AGPL-3.0-or-later, documentation livrée avec le code.

## Pour qui

Les administrateurs qui hébergent eux-mêmes leurs services, en particulier les administrateurs de nœuds Nostr (relais strfry, bunker NIP-46, journal légal).

## État réel

- **Fait côté serveur** : le protocole `jumeaux/1`, Pollux (preuve de possession de la clé SSH par défi signé), Romulus (sessions, jetons, frontal HTTP, aiguillage, suivi en direct), Castor, Remus avec chargement de greffons (greffon strfry de base livré), Nisaba (démon écrit), bunkerd 2.0.0 (démon écrit), la configuration en couches, l'outil de sauvegarde et les scripts d'installation (écrits, essayés en alpha).
- **Client** : noyau Qt écrit (configuration, session de présence, fenêtre QtWebEngine en profil privé, cookie du jeton, indicateur d'état, socle des pages web, chargement des pages déclarées par les greffons, pages du noyau : état, journaux, catalogue). Aucun greffon ne livre encore de page d'administration.
- **Pas encore là** : les autres fonctions du greffon strfry, les pages d'administration des greffons, unités systemd et installation de Nisaba et de bunkerd.

Le détail des modifications est dans le [CHANGELOG](CHANGELOG.md).

## Développement assisté par IA

Paresia est dirigé par un mainteneur humain, qui en fixe l'orientation, les exigences et les limites. La plus grande partie du code et de la documentation est écrite par des outils d'IA (Claude Code d'Anthropic et Codex d'OpenAI), sous cette direction.

Le code passe par une suite de tests automatisés et une intégration continue. Malgré ce soin, il peut contenir des erreurs, y compris de sécurité. Il n'a fait l'objet d'aucun audit de sécurité externe.

Paresia est fourni sans garantie (AGPL-3.0-or-later). Lisez le code, testez avant de l'exposer, et signalez tout problème selon [SECURITY](SECURITY.md).

## Feuille de route

- **v0.1, preuve de concept** : noyaux serveur et client, client Qt parlant à l'API, pages servies par un serveur web, démonstration de la présence, de l'état et des journaux de Paresia, greffon strfry de base.
- **v0.2, administration complète du relais** avec journaux et bunker, pour la communauté des administrateurs de nœuds Nostr.
- **Avant la 1.0** : le périmètre du cahier des charges. **Après la 1.0** : mode Docker rootless tout-en-un, greffons tiers.

## Documentation

- Index de tout : [docs/README.md](docs/README.md)
- Guide de l'administrateur (wiki) : [Accueil](docs/wiki/Accueil.md)
- Spécification, qui fait foi : [cahier des charges](docs/cahier-des-charges.md)
- Architecture : [architecture](docs/architecture.md) ; protocole : [protocole](docs/protocole.md)
- Pages de manuel : [docs/man/](docs/man/) ; exploitation : [exploitation](docs/exploitation.md) ; configuration : [configuration](docs/configuration.md)
- Décisions : [décisions](docs/decisions.md) ; historique : [CHANGELOG](CHANGELOG.md)

## Installation

Guide « Installer » : [INSTALL.md](INSTALL.md) (deux machines Debian 13, scripts essayés en alpha). Mise à jour : [INSTALL.md, annexe A](INSTALL.md#annexe-a--mettre-à-jour-une-installation-existante). Poste de développement : [développement](docs/developpement.md), § 3. Prérequis : [Prérequis](docs/prerequis.md). Serveur web et proxy (à votre charge) : [Serveur web](docs/serveur-web.md). Les guides d'installation du noyau (Paresia) et des greffons (strfry, Nisaba, bunker) sont classés séparément dans l'[Accueil du wiki](docs/wiki/Accueil.md).

## Sécurité

Modèle de menace provisoire et signalement des vulnérabilités (pas de ticket public) : [SECURITY](SECURITY.md).

## Contribuer

Voir [CONTRIBUTING](CONTRIBUTING.md). Tout apport est publié sous AGPL-3.0-or-later.

## Versions

Le numéro est dans `VERSION` (Semantic Versioning 2.0.0, `0.MINEUR.CORRECTIF` jusqu'à la 1.0.0). Journal : [CHANGELOG](CHANGELOG.md) (Keep a Changelog 1.1.0).

## Licence

GNU Affero General Public License, version 3 ou ultérieure (SPDX `AGPL-3.0-or-later`). Texte : [LICENSE](LICENSE). Dépendances : [licences tierces](docs/licences-tierces.md).
