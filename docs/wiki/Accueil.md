# Wiki Paresia : accueil

Version du document : 0.1.16 · 2026-11-08.

Suivi, 2026-11-09 : sommaire réorganisé en quatre parties (comprendre, installer le noyau, installer les greffons, exploiter), page HAProxy ajoutée ; décision de l'utilisateur du 2026-11-09 ; numéro du document inchangé (aucun numéro donné).

Paresia est un noyau d'administration à distance, cloisonné et enfichable, fondé sur la présence prouvée : sans session de présence ouverte, toute commande est refusée. Le noyau ne connaît aucun produit ; des greffons (modules enfichés : strfry, le relais Nostr ; Nisaba, le journal légal ; le bunker, qui signe à distance selon NIP-46) s'y enfichent et déclarent leur compatibilité avec le produit que vous installez vous-même.

Ce wiki est le guide de l'administrateur de Paresia. Il s'adresse à ceux qui hébergent eux-mêmes leurs services (auto-hébergement, petite structure) et, en particulier, aux administrateurs de nœuds Nostr. Il explique simplement, sans rien inventer : tout vient du code et de la documentation du dépôt. Ce qui n'est pas encore livré est marqué **à venir** ; ce que les sources ne permettent pas d'établir est marqué **non établi**.

Les mots techniques sont expliqués dans le [glossaire](Glossaire.md).

## Sommaire

Le wiki a quatre parties : comprendre, installer le noyau, installer les greffons, exploiter ; une page de petites aides, [Tips](#tips), complète le tout. **Le noyau** est Paresia lui-même (yin, yang, le client) ; **les greffons** sont les modules qu'on enfiche dessus (strfry, Nisaba, le bunker). Les deux installations sont séparées.

1. [Comprendre Paresia](#1-comprendre-paresia)
2. [Installer le noyau](#2-installer-le-noyau)
3. [Installer les greffons](#3-installer-les-greffons)
4. [Exploiter, dépanner, consulter](#4-exploiter-dépanner-consulter)

### 1. Comprendre Paresia

| Page | Pour répondre à la question |
| --- | --- |
| [Qu'est-ce que Paresia ?](Qu-est-ce-que-Paresia.md) | À quoi sert Paresia, de quoi est-il fait, qu'est-ce qu'un greffon ? |
| [Architecture et sécurité](Architecture-et-securite.md) | Comment les morceaux se parlent, et pourquoi une panne ou une intrusion reste cloisonnée |
| [Glossaire](Glossaire.md) | Les termes employés |

### 2. Installer le noyau

Le noyau, c'est Paresia : yin (`backend-relais`), yang (`backend-admin`) et le client. Dans l'ordre :

| Étape | Page | Pour répondre à la question |
| --- | --- | --- |
| 1 | [Prérequis](Prerequis.md) | Quelles machines, quels logiciels, quels comptes |
| 2 | [INSTALL.md](../../INSTALL.md) | **Le parcours pas à pas de yin et de yang**, de haut en bas (deux machines Debian 13) |
| 3 | [Installation](Installation.md) | En complément : principe de l'installation semi-automatique, options et codes de sortie des scripts |
| 4 | [Installer et configurer lighttpd](Installer-lighttpd.md) | Installer le serveur web de yang et le régler pour Paresia, avant le client |
| 5 | [Régler HAProxy pour Paresia](Installer-haproxy.md) | Ce que Paresia exige du frontal HAProxy (très pointu : seulement les exigences du projet) |
| 6 | [Installer le client](Installer-client.md) | Installer le client Paresia-admin sur le poste de l'administrateur |
| 7 | [Premier usage](Premier-usage.md) | Que vérifier juste après l'installation, ce qui est utilisable aujourd'hui |
| 8 | [Configurer Paresia](Configuration.md) | Où sont les fichiers de réglage de yin et de yang, comment ils se combinent, quels réglages vous toucherez le plus. Le réglage du client est à l'[étape 5 de son guide](Installer-client.md#5-configurer-lapplication) |

Le serveur web et HAProxy ne sont pas installés par Paresia : ce sont des logiciels que vous installez vous-même, et les deux pages ci-dessus ne disent que ce que le projet leur impose.

### 3. Installer les greffons

Les greffons s'enfichent sur le noyau. Aujourd'hui, un seul a un guide d'installation complet.

| Greffon | Page | Pour répondre à la question |
| --- | --- | --- |
| strfry (relais Nostr) | [Installer le relais strfry](Installer-strfry.md) | Docker et configuration du conteneur `strfry` de yin. **À faire sur yin avant l'étape 6 d'[INSTALL.md](../../INSTALL.md)**, qui vérifie ce conteneur |
| strfry | [Installer `nak`](Installer-nak.md) | Sur le poste de vos clés privées : installer `nak` et créer la clé du relais (utilisé par l'installation de strfry) |
| Nisaba (journal légal) et bunker (signature NIP-46) | [Nisaba et le bunker](Nisaba-et-bunker.md) | Ce qu'ils font ; **leur guide d'installation n'est pas encore écrit** (unités non livrées, **à venir**). `nak` sert aussi sur yang pour le bunker : [Installer `nak`](Installer-nak.md) |

### 4. Exploiter, dépanner, consulter

| Page | Pour répondre à la question |
| --- | --- |
| [Administrer le relais strfry](Administration-du-relais-strfry.md) | Ce que Paresia fera (et ne fera pas) sur un relais strfry |
| [Journaux, métriques, dépannage](Journaux-metriques-depannage.md) | Lire les journaux, interpréter les erreurs, FAQ |
| [Sauvegarde et retour arrière](Sauvegarde-et-retour-arriere.md) | Sauvegarder avant de toucher, revenir en arrière |

### Tips

Les petites aides d'ordre général, distinctes de l'installation du noyau et des greffons.

| Page | Pour répondre à la question |
| --- | --- |
| [Tips](Tips.md) | Comment ajouter une clé à son agent SSH (bash et fish) ? |

## Où trouver le détail technique

Ce wiki vulgarise et sert à **installer** ; le dossier `docs/` du dépôt est la **référence technique** (à lire pour le détail, pas pour installer). Elle est dans le dépôt :

- cahier des charges (fait foi) : [cahier des charges](../cahier-des-charges.md) ;
- protocole entre démons : [protocole](../protocole.md) ;
- configuration : [configuration](../configuration.md) ;
- guide d'exploitation : [exploitation](../exploitation.md) ;
- pages de manuel : [dossier `docs/man/`](../man/) (lecture : `man -l docs/man/paresia-castor.8`) ;
- décisions et retours en arrière : [décisions](../decisions.md).

## État du projet

Paresia est en version alpha (voir le fichier `VERSION` du dépôt). Les démons côté serveur sont en grande partie écrits ; le client Paresia-admin a une fenêtre qui ouvre la session de présence, avec les pages d'état, de journal d'activité et de catalogue du noyau (pas encore de pages d'administration du relais) ; les scripts d'installation et de mise à jour sont écrits et essayés en alpha (le guide pas à pas est `INSTALL.md`, à la racine du dépôt) ; un greffon strfry de base livre trois fonctions ; bunkerd et Nisaba sont écrits, mais leur unité et leur installation ne sont pas encore livrées. Alpha : pas en production, à essayer sur des machines jetables. Chaque page dit précisément ce qui est utilisable aujourd'hui.

**Feuille de route.** Version 0.1 (actuelle) : preuve de concept (noyaux serveur et client, client Qt parlant à l'API, pages servies par un lighttpd que vous configurez selon [Serveur web](../serveur-web.md), démonstration de la présence, de l'état et du journal d'activité de Paresia, greffon strfry de base). Ses limites sont dans le [README](../../README.md), section « Limites connues ». Version 0.2 : administration complète du relais, avec journaux et bunker, **à venir**.

**Ce que Paresia n'installe pas.** lighttpd (serveur web) et HAProxy (proxy et répartiteur de charge) ne sont pas installés par Paresia, qui en documente seulement les exigences (voir [Installer et configurer lighttpd](Installer-lighttpd.md), [Régler HAProxy pour Paresia](Installer-haproxy.md), [Installation](Installation.md) et [Prérequis](Prerequis.md)).

## Maintenir ce wiki

Ce wiki est écrit dans `docs/wiki/` du dépôt et suit les versions du code. Il sera publié sur le wiki du dépôt : la publication est une copie de ces fichiers.

**À venir** : publication sur le wiki du dépôt ; traduction anglaise ; captures d'écran de l'application une fois la fenêtre livrée.
