# Wiki Paresia : accueil

Version du document : 0.1.16 · 2026-11-08.

Paresia est un noyau d'administration à distance, cloisonné et enfichable, fondé sur la présence prouvée : sans session de présence ouverte, toute commande est refusée. Le noyau ne connaît aucun produit ; des greffons (modules enfichés : strfry, le relais Nostr ; Nisaba, le journal légal ; le bunker, qui signe à distance selon NIP-46) s'y enfichent et déclarent leur compatibilité avec le produit que vous installez vous-même.

Ce wiki est le guide de l'administrateur de Paresia. Il s'adresse à ceux qui hébergent eux-mêmes leurs services (auto-hébergement, petite structure) et, en particulier, aux administrateurs de nœuds Nostr. Il explique simplement, sans rien inventer : tout vient du code et de la documentation du dépôt. Ce qui n'est pas encore livré est marqué **à venir** ; ce que les sources ne permettent pas d'établir est marqué **non établi**.

Les mots techniques sont expliqués dans le [glossaire](Glossaire.md).

## Sommaire

| Page | Pour répondre à la question |
| --- | --- |
| [Qu'est-ce que Paresia ?](Qu-est-ce-que-Paresia.md) | À quoi sert Paresia, de quoi est-il fait, qu'est-ce qu'un greffon ? |
| [Architecture et sécurité](Architecture-et-securite.md) | Comment les morceaux se parlent, et pourquoi une panne ou une intrusion reste cloisonnée |
| [Prérequis](Prerequis.md) | Quelles machines, quels logiciels, quels comptes |
| [Installer le relais strfry](Installer-strfry.md) | Préparer le conteneur Docker `strfry` de `backend-relais`, avant l'installation |
| [Installer `nak`](Installer-nak.md) | Sur le poste de vos clés privées : installer `nak` et créer une clé ; aussi sur `backend-admin` pour le bunker |
| [Installation](Installation.md) | Principe de l'installation semi-automatique, options et codes de sortie des scripts (le parcours pas à pas est `INSTALL.md`) |
| [Premier usage](Premier-usage.md) | Que vérifier juste après l'installation, ce qui est utilisable aujourd'hui |
| [Administrer le relais strfry](Administration-du-relais-strfry.md) | Ce que Paresia fera (et ne fera pas) sur un relais strfry |
| [Nisaba et le bunker](Nisaba-et-bunker.md) | Journal légal, signatures à distance (NIP-46), identités |
| [Configuration](Configuration.md) | Où sont les réglages, comment ils se combinent |
| [Journaux, métriques, dépannage](Journaux-metriques-depannage.md) | Lire les journaux, interpréter les erreurs, FAQ |
| [Sauvegarde et retour arrière](Sauvegarde-et-retour-arriere.md) | Sauvegarder avant de toucher, revenir en arrière |
| [Glossaire](Glossaire.md) | Les termes employés |

## Où trouver le détail technique

Ce wiki vulgarise ; la référence précise est dans le dépôt :

- cahier des charges (fait foi) : `docs/cahier-des-charges.md` ;
- protocole entre démons : `docs/protocole.md` ;
- configuration : `docs/configuration.md` ;
- guide d'exploitation : `docs/exploitation.md` ;
- pages de manuel : `docs/man/` (lecture : `man -l docs/man/paresia-castor.8`) ;
- décisions et retours en arrière : `docs/decisions.md`.

## État du projet

Paresia est en version alpha (voir le fichier `VERSION` du dépôt). Les démons côté serveur sont en grande partie écrits ; le client Paresia-admin a une fenêtre qui ouvre la session de présence, avec les pages d'état, de journal d'activité et de catalogue du noyau (pas encore de pages d'administration du relais) ; les scripts d'installation et de mise à jour sont écrits et essayés en alpha (le guide pas à pas est `INSTALL.md`, à la racine du dépôt) ; un greffon strfry de base livre trois fonctions ; bunkerd et Nisaba sont écrits, mais leur unité et leur installation ne sont pas encore livrées. Alpha : pas en production, à essayer sur des machines jetables. Chaque page dit précisément ce qui est utilisable aujourd'hui.

**Feuille de route.** Version 0.1 (actuelle) : preuve de concept (noyaux serveur et client, client Qt parlant à l'API, pages servies par un lighttpd que vous configurez selon `docs/serveur-web.md`, démonstration de la présence, de l'état et du journal d'activité de Paresia, greffon strfry de base). Ses limites sont dans le `README.md`, section « Limites connues ». Version 0.2 : administration complète du relais, avec journaux et bunker, **à venir**.

**Ce que Paresia n'installe pas.** lighttpd (serveur web) et HAProxy (proxy et répartiteur de charge) ne sont pas installés par Paresia, qui en documente seulement les exigences (voir [Installation](Installation.md) et [Prérequis](Prerequis.md)).

## Maintenir ce wiki

Ce wiki est écrit dans `docs/wiki/` du dépôt et suit les versions du code. Il sera publié sur le wiki du dépôt : la publication est une copie de ces fichiers.

**À venir** : publication sur le wiki du dépôt ; traduction anglaise ; captures d'écran de l'application une fois la fenêtre livrée.
