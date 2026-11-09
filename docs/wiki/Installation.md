# Installation semi-automatique : principe et références

Version du document : 0.1.19 · 2026-11-08 · [Accueil](Accueil.md)

Suivi, 2026-11-09 : la page ne contient plus de parcours numéroté ; le seul parcours est [INSTALL.md](../../INSTALL.md). Numéro du document inchangé.

Alpha : pas en production, à essayer sur des machines jetables.

## En bref

L'**installation semi-automatique** : vous enchaînez les étapes, et un script par machine fait le travail de chaque étape. Elle se distingue de l'installation automatique prévue pour la 1.0, pilotée par le client (D176), qui n'existe pas encore.

Elle consiste en cinq temps :

1. préparer chaque machine : récupérer le dépôt, installer les paquets, mettre en marche strfry sur yin ;
2. lancer le script de yang (il crée la clé du tunnel) ;
3. lancer le script de yin (il autorise cette clé et donne son empreinte) ;
4. relancer le script de yang pour poser le tunnel ;
5. vérifier, activer au démarrage, puis autoriser la clé d'un administrateur.

**Le parcours complet, avec les commandes et les résultats attendus, est dans [INSTALL.md](../../INSTALL.md), à la racine du dépôt.** C'est le seul parcours : suivez-le de haut en bas.

**Yang** est la machine d'administration, non exposée (`backend-admin` dans les noms de scripts et de dossiers). **Yin** est la machine du relais, exposée (`backend-relais`). Chaque machine a besoin d'une valeur produite par l'autre : l'installation alterne entre elles.

Après l'installation : [Premier usage](Premier-usage.md) ; [Sauvegarde et retour arrière](Sauvegarde-et-retour-arriere.md) ; [Administrer le relais strfry](Administration-du-relais-strfry.md).

## Annexe A : principe des scripts

Chaque machine s'installe par un script complet et commenté (`deploy/backend-admin/installer-backend-admin.sh` pour yang, `deploy/backend-relais/installer-backend-relais.sh` pour yin ; les noms des scripts et des dossiers gardent les anciens noms). Le script :

- s'exécute depuis un clone que vous avez fait vous-même ; il ne clone ni ne télécharge rien ;
- ne pose aucune question : option de ligne de commande, sinon variable d'environnement, sinon valeur par défaut ;
- vérifie tout avant de modifier : une valeur absente ou invalide l'arrête (code 64 ou 65) ;
- est rejouable : état déjà conforme, rien ne se passe ; état différent, refus (code 78) ;
- sauvegarde avant toute modification ;
- n'arrête et ne redémarre aucune unité, sauf sous `--mise-a-jour` ; il démarre (`start`) celles qu'il pose, et n'active au démarrage que sous `--activer` ;
- ne recharge `sshd` qu'après `sshd -t` et avec une session de secours (`--session-secours oui`) ; il ne le redémarre jamais ;
- ne touche pas à strfry, Docker, lighttpd, bunkerd ;
- n'affiche ni ne journalise aucune clé privée ;
- affiche ses messages depuis le catalogue de langue du clone (`fr-FR` ou `en-US`, selon `LC_ALL`/`LANG`).

Ce que chaque machine installe : côté yang, Pollux, `pollux-session`, Romulus et le tunnel ; côté yin, Castor, Remus, leurs comptes, le sudoers généré, la table nftables et le tunnel du relais.

## Annexe B : pourquoi trois passes, et deux règles de compte

Le tunnel demande un échange de clés dans cet ordre : yang génère la clé du tunnel (la clé privée y reste) ; yin reçoit adresse, clé publique et empreinte, puis affiche l'empreinte de sa clé d'hôte ; yang compare cette empreinte à `ssh-keyscan`. L'empreinte passe par un second canal, pas par le tunnel qu'elle protège.

Deux machines, deux règles, voulues par le mainteneur (voir [décisions](../decisions.md)) :

- yang : root, sans `sudo` installé (une porte de moins). Tout autre compte est refusé (code 77).
- yin : aucun shell root ; compte ordinaire avec `sudo` (1.9.10 au moins) limité aux commandes nécessaires, par chemin absolu. Root est refusé (code 77).

L'en-tête de chaque script liste les commandes privilégiées lancées. Elle est descriptive, non un sudoers à recopier.

## Annexe C : le mode `--alpha-test`

Temporaire, retiré après validation :

- pause après chaque étape (Entrée pour continuer) ; arrêt au premier écart ;
- affichage de chaque vérification et de chaque relevé ;
- avertissement avant toute commande destructive ou risquée ;
- journal horodaté sans secret `alpha-test-<machine>-<date>.log`, écrit dans le dossier de lancement (ou `--dossier-journal`). Le dossier doit exister, ne pas être un lien symbolique, appartenir à root ou à votre compte et n'être modifiable ni par le groupe ni par les autres ; fichier en `0600`, jamais écrasé. Un journal sous `/var/log/paresia` est refusé ;
- exige un terminal.

## Annexe D : paramètres principaux

| Option | Défaut | Rôle |
| --- | --- | --- |
| `--depot` | racine du clone du script | copie propre du dépôt, jamais un lien symbolique |
| `--langue` | dérivée de `LC_ALL`/`LANG`, repli `fr-FR` | langue des messages |
| `--dossier-journal` | dossier de lancement | journal de `--alpha-test` |
| `--session-secours` | `non` | `oui` : seconde session ouverte et testée ; obligatoire pour recharger sshd |
| `--code-remplacement-confirme` | `non` | `oui` autorise le remplacement de fichiers installés qui diffèrent |
| `--stockage-actif` | `oui` | `non` désactive les sauvegardes (retour arrière impossible : à éviter) |
| `--sauter <étape>` | aucune | `produit` (yin : contrôle de l'image strfry), `fonctions` (yin), `sudoers`, `nftables`, `isolation_remus`, `www-data` |
| `--activer` | non | active les unités au démarrage, après vérification (le tunnel, tiré par `pollux` et `romulus`, n'est jamais activé pour lui-même) |
| `--mise-a-jour` | non | met à jour une installation existante (voir [INSTALL.md, annexe A](../../INSTALL.md#annexe-a--mettre-à-jour-une-installation-existante)) |
| `--retour-arriere --jeu <nom> --confirme` | | retour arrière |

Propres à yin : `--repertoire-tunnel` (défaut `/var/lib/paresia-tunnel`, jamais sous `/home`), `--profil`, `--port-essai`, `--acces-tunnel-sans-nftables`. Propre à yang : `--repertoire-app` (défaut `/var/lib/paresia-app`).

## Annexe E : codes de sortie

Selon `sysexits.h` : 0 succès ; 64 usage ; 65 valeur invalide ; 66 catalogue illisible ; 69 prérequis manquant ; 73 journal déjà existant ; 74 sauvegarde en échec ; 77 compte d'exécution refusé ; 78 état différent de l'attendu.

## Annexe F : ce que les scripts créent

- Des comptes système sans mot de passe ni répertoire sous `/home` (yin : `paresia-castor`, `chef`, `tunnel` ; yang : `app`, `paresia-romulus`, `paresia-pollux`, `paresia-tunnel`). Leurs uid et gid sont choisis par le système dans la plage de `login.defs(5)` et reportés dans la configuration. Un compte conforme est repris ; un compte non conforme est refusé (code 78).
- Le code sous `/usr/local/lib/paresia`, la configuration sous `/etc/paresia/` (`paresia.conf`, `conf.d/`).
- Sur yang, les pages de l'interface sous `/usr/local/share/paresia/web/` (propriété de root), avec sous `greffons/` les pages des greffons et un `index.json`. Le script ne sert pas ces fichiers : à vous de les faire servir sous `/admin/` ([Serveur web](../serveur-web.md)).
- Les unités systemd (`pollux`, `romulus`, `paresia-tunnel` ; `castor`, `remus`, `paresia-nftables`).
- Sur yin, `/etc/sudoers.d/paresia-remus` (généré) et la table nftables `paresia_relais`.

## Annexe G : réserves

- Les unités et l'installation de bunkerd et de Nisaba ne sont pas livrées. Procédure de migration depuis les anciens scripts `journal-legal-*` : non livrée.
- Paresia n'installe ni lighttpd ni HAProxy ; elle en documente les exigences ([Serveur web](../serveur-web.md), avec un extrait pour lighttpd).
- Mode Docker rootless tout-en-un : après la 1.0.
- Essai de bout en bout de la présence : [essai de présence](../../deploy/essai-presence.md).
- Références : pages de manuel `installer-backend-admin(8)` et `installer-backend-relais(8)`, [Prérequis](../prerequis.md). Lisez `--aide` de la version que vous avez.
