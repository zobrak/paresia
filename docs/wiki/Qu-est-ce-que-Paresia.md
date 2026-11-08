# Qu'est-ce que Paresia ?

Version du document : 0.1.17 · 2026-11-08 · [Accueil](Accueil.md)

## En une phrase

Paresia est un **noyau d'administration à distance, cloisonné et enfichable** : il permet à un administrateur de piloter des services sur des machines séparées, seulement pendant qu'il est prouvablement présent. Trois premiers usages sont prévus comme greffons : l'administration d'un relais Nostr strfry (trois fonctions de base livrées, le reste **à venir**), un bunker de signature à distance (NIP-46) et la gestion d'un journal légal (Nisaba). Le bunker (bunkerd) et Nisaba sont des démons écrits ; leur unité et leur installation ne sont pas encore livrées. Alpha : pas en production, à essayer sur des machines jetables.

## Le problème qu'il résout

Un administrateur de relais Nostr gère souvent des services sensibles (clés de signature, journaux à valeur légale, base de données du relais). Les laisser pilotables en permanence depuis Internet est risqué. Paresia applique un principe simple, le **robinet fermé par défaut** : sans session de présence ouverte, toute commande d'administration est refusée, d'où qu'elle vienne.

La présence se prouve par une **clé SSH** : l'application de l'administrateur ouvre une session SSH vers le serveur d'administration. Tant que cette session vit, le robinet est ouvert, et seulement pour elle. Veille de l'ordinateur, coupure réseau, fermeture : le robinet se referme tout seul. Aucun mot de passe d'administration n'existe.

## Le noyau : deux couples de jumeaux

Paresia est un noyau « le plus simple et universel possible ». Il ne sait rien de ce qu'il transporte. Il se compose de quatre démons (programmes qui tournent en arrière-plan), en deux couples, un couple par machine :

| Côté | Machine | Démon | Rôle en deux mots |
| --- | --- | --- | --- |
| **yang** (administration) | `backend-admin` | **Romulus** | reçoit les commandes, émet et vérifie les jetons, aiguille |
| yang | `backend-admin` | **Pollux** | constate la présence de l'administrateur et laisse passer jetons et « pings » |
| **yin** (relais) | `backend-relais` | **Remus** | exécute les opérations sur le relais, seulement si le feu est vert |
| yin | `backend-relais` | **Castor** | tient un « feu de circulation » par session de présence (vert : les commandes passent ; rouge ou fermé : elles sont refusées) |

Romulus et Remus sont des jumeaux (ils transportent les commandes) ; Pollux et Castor sont des jumeaux (ils transportent la présence). Un seul tunnel SSH (liaison chiffrée) relie les deux machines et porte les deux couples. Les démons se parlent en lignes de JSON selon le protocole `jumeaux/1` (voir le [glossaire](Glossaire.md)).

Les mots yin et yang désignent simplement les deux côtés : le yin héberge le service administré, le yang héberge l'administration. Les deux ensembles s'appellent `paresia-yin` (Remus, Castor) et `paresia-yang` (Romulus, Pollux) ; chacun s'installe par script sur sa machine.

## Les greffons

Le noyau ne change pas selon l'usage. On y **enfiche des greffons** :

- côté yin, derrière Remus : le relais **strfry** ;
- côté yang, derrière Romulus : **Nisaba** (journal légal) et le **bunker** (bunkerd, qui signe à distance selon NIP-46, la spécification Nostr des signatures déléguées).

Ces trois-là sont les premiers greffons livrés avec Paresia, pour éprouver son fonctionnement. Ils illustrent ce qu'un greffon peut faire ; d'autres pourront suivre. Nommage prévu : `paresia-yin-<nom>` et `paresia-yang-<nom>` ; un greffon présent des deux côtés devient deux greffons appariés.

Trois règles gouvernent les greffons :

- **Le greffon ne livre pas le produit.** Vous installez strfry, Nisaba ou le bunker vous-même ; le greffon déclare avec quelles versions il fonctionne, et son auteur répond de la compatibilité de ses deux moitiés, yin et yang. Le noyau reste étranger au produit installé. Le greffon officiel de strfry sera livré clé en main (configuration qui fonctionne, procédure soignée) ; sa version de base livre trois fonctions, le reste est **à venir**.
- **Remus reste « bête »** : il ne connaît aucune opération du relais ; il charge des fonctions, sert leur catalogue et aiguille chaque requête vers la fonction qui la déclare. Aujourd'hui, le greffon strfry livre trois fonctions de base (état, arbres negentropy, redémarrage du conteneur).
- **Le client ne connaît aucun produit** : son noyau (Qt, avec une interface web) ne sait rien de strfry ni du bunker ; chaque greffon apporte ses propres pages, que l'interface découvre au démarrage par un petit index et charge une à une (voir [Architecture et sécurité](Architecture-et-securite.md)). Le chargement côté client est écrit, et l'installation de `backend-admin` sait poser les pages que les greffons déclarent et générer leur index (`paresia-romulus-pages(8)`), sans toucher au serveur web ; mais **aucun greffon livré n'apporte encore de page**.

## Les deux produits

- **Paresia-server** : les démons et leurs configurations sur les deux machines.
- **Paresia-admin** : le client, composé d'un noyau Qt (qui ouvre la session de présence) et d'une interface web d'administration. La fenêtre qui ouvre la session de présence existe, ainsi que les pages d'état, de journal d'activité et de catalogue du noyau ; les pages d'administration des greffons sont **à venir**.

Un seul numéro de version couvre les deux (fichier `VERSION`).

## Ce que Paresia n'est pas

- Ce n'est pas un relais Nostr : le relais est strfry, que Paresia administre.
- Ce n'est pas un outil qui exécute des commandes libres : chaque démon n'accepte qu'une **liste fermée d'opérations**, aux arguments vérifiés.
- Ce n'est pas un service qu'on installe sur une machine unique « pour essayer » avec tout activé : le cloisonnement entre deux machines est le point fort. Un mode tout-en-un (conteneurs Docker sans privilèges) est prévu **après la 1.0**.

## À venir

- **Version 0.1** (preuve de concept, la version actuelle) : client Qt parlant à l'API, pages servies par un lighttpd que vous configurez (`docs/serveur-web.md`), démonstration de la présence, de l'état de Paresia, de son journal d'activité et d'un greffon strfry de base (trois fonctions). Le **journal d'activité de Romulus** (actions reçues et décisions, sans secret ni paramètres) est livré. Les limites de cette version sont dans le `README.md`, section « Limites connues » : en particulier, le code récent n'a pas été essayé sur de vraies machines, et le rendu des pages dans la fenêtre non plus.
- **Version 0.2** : administration complète du relais, avec journaux et bunker.
- Greffons ouverts à des tiers, privilèges par greffon, plusieurs yin et plusieurs yang (N:M, c'est-à-dire N machines de relais pour M machines d'administration), greffons écrits dans d'autres langages : tout cela est prévu après la 1.0 (choix consignés dans [`docs/decisions.md`](../decisions.md)). Rien n'est implémenté en 1.0, mais rien n'est fermé non plus.
- Réécriture dans un langage compilé : la première sera Castor, en C, après la 1.0, une fois écrite une suite de conformité en boîte noire du protocole `jumeaux/1` (choix consigné dans [`docs/decisions.md`](../decisions.md)). Python reste le langage de la pré-alpha.
- Installation Docker rootless tout-en-un : après la 1.0.
