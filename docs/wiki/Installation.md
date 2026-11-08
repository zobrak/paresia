# Installation : côté yin et côté yang

Version du document : 0.1.19 · 2026-11-08 · [Accueil](Accueil.md)

**Statut.** Les scripts sont écrits et essayés en alpha ; le guide pas à pas, avec les paquets à installer, est `INSTALL.md` (à la racine du dépôt). Alpha : pas en production, à essayer sur des machines jetables. Les unités et l'installation de bunkerd et de Nisaba ne sont pas encore livrées.

Référence : en-têtes des scripts `deploy/backend-admin/installer-backend-admin.sh` et `deploy/backend-relais/installer-backend-relais.sh` (l'option `--alpha-test` est temporaire ; **lisez `--aide` de la version que vous avez**), pages de manuel `installer-backend-admin(8)` et `installer-backend-relais(8)`, `docs/prerequis.md`. Les procédures `deploy/*.md` de ces deux machines renvoient désormais aux scripts ; seul l'essai de bout en bout de la présence (`deploy/essai-presence.md`) et la procédure du tunnel restent des procédures à suivre à la main.

## Principe

Chaque machine s'installe par **un seul script complet et commenté** :

- côté **yang** (`backend-admin`) : Pollux, `pollux-session`, Romulus et la partie « tunnel » ;
- côté **yin** (`backend-relais`) : Castor, Remus, leurs comptes, le fichier sudoers généré, la table nftables (règles du pare-feu du noyau Linux) et la partie « tunnel » du relais.

Le script :

- s'exécute depuis **un clone du dépôt que vous avez fait vous-même** ; il ne clone ni ne télécharge rien : pour mettre à jour une machine, vous récupérez vous-même un clone plus récent et lancez le script avec `--mise-a-jour` (voir plus bas) ;
- **ne pose aucune question** : chaque choix est une option de ligne de commande, sinon une variable d'environnement, sinon une valeur par défaut (seule exception : la saisie masquée d'un secret) ;
- vérifie tout **avant** de modifier quoi que ce soit : une valeur absente ou invalide arrête le script (code 64 ou 65) ;
- est **rejouable** : chaque étape lit d'abord l'état ; s'il est déjà conforme, elle ne fait rien (« déjà en place ») ; s'il diffère de l'attendu, elle **refuse** (code 78) au lieu d'écraser ;
- fait une **sauvegarde avant toute modification** ;
- **n'arrête et ne redémarre aucune unité**, sauf sous `--mise-a-jour` (voir plus bas) : si un démon actif doit changer, c'est vous qui l'arrêtez d'abord. Il **démarre** (`start`) les unités qu'il pose ; l'activation au démarrage du système n'a lieu que sous `--activer` ;
- n'emploie `reload ssh` qu'après `sshd -t` et seulement avec une **session de secours** déjà ouverte (`--session-secours oui`) ; jamais de `restart` ;
- ne touche jamais à strfry, Docker, lighttpd, bunkerd ni aux autres services ;
- n'affiche, ne copie et ne journalise jamais de clé privée (seules les clés publiques et les empreintes sortent) ;
- affiche ses messages depuis le catalogue de langue du clone (`fr-FR` ou `en-US`, selon `LC_ALL`/`LANG`).

## Quel compte lance le script ? Deux machines, deux règles

Ce n'est pas une incohérence : chaque machine a sa règle, voulue par le mainteneur du projet (voir [`docs/decisions.md`](../decisions.md)).

- **Sur `backend-admin`, vous travaillez en root et vous n'installez pas `sudo`.** Le script d'administration s'exécute en root et refuse tout autre compte (code 77). Une machine d'administration qui n'a pas `sudo` n'offre pas cette porte de plus. Si `sudo` y est tout de même présent, le script l'emploie commande par commande.
- **Sur `backend-relais`, il n'y a pas de shell root, et `sudo` est limité aux commandes strictement nécessaires.** Le script du relais refuse de s'exécuter en root (code 77) ; vous le lancez depuis un compte ordinaire avec `sudo` (1.9.10 au moins), qui appelle chaque commande par son chemin absolu, sans `sudo -i`, `su` ni `sudo sh -c`. La machine exposée au service public garde ainsi le moindre privilège.

Dans les deux cas, l'en-tête de chaque script donne la liste des commandes privilégiées qu'il lance. Elle est descriptive, ce n'est pas un sudoers à recopier.

## Ordre entre les deux machines

Le tunnel demande un échange de clés dans un ordre précis, en trois passes :

1. **backend-admin, première passe** : installation et génération de la clé du tunnel (la clé privée reste sur `backend-admin`).
2. **backend-relais** : vous fournissez l'adresse de `backend-admin`, la clé **publique** du tunnel et son empreinte (`--adresse-admin`, `--cle-publique-tunnel`, `--empreinte-cle-tunnel`). À la fin, le script affiche l'empreinte de la clé d'hôte du relais.
3. **backend-admin, deuxième passe** : vous fournissez l'adresse du relais et cette empreinte (`--adresse-relais`, `--empreinte-hote-relais`) ; `backend-admin` la compare à ce que lit `ssh-keyscan`. L'empreinte doit être transmise **par un second canal** (pas dans le même tunnel que celui qu'elle protège).

## Le mode `--alpha-test`

Pendant l'alpha, l'option `--alpha-test` ajoute une sécurité (temporaire, elle sera retirée après validation) :

- **pause après chaque étape** : vous lisez, vous appuyez sur Entrée ;
- **arrêt au premier écart** ;
- affichage de chaque vérification et de chaque relevé ;
- **avertissement avant toute commande destructive ou risquée** (création de compte, rechargement de sshd, écrasement de fichier) ;
- **journal horodaté sans secret** : `alpha-test-<machine>-<date>.log`, écrit **dans le dossier d'où vous lancez le script** (ou dans `--dossier-journal`). Le dossier doit exister, ne pas être un lien symbolique, appartenir à root ou à votre compte et n'être modifiable ni par le groupe ni par les autres ; le fichier est en `0600`, jamais écrasé ; lancé par `sudo`, le script le remet à votre compte (si `SUDO_UID` et `SUDO_GID` sont valides), ce qui vous permet de le lire. Il exige un terminal. Un journal sous `/var/log/paresia` est refusé.

Pour commencer, lancez toujours `--verifier` (lecture seule : contrôle les paramètres et les prérequis, dont `python3-cryptography` sur `backend-admin`, ne modifie rien), puis `--alpha-test`.

## Paramètres principaux

| Option | Défaut | Rôle |
| --- | --- | --- |
| `--depot` | racine du clone qui contient le script | copie propre du dépôt, jamais un lien symbolique |
| `--langue` | dérivée de `LC_ALL`/`LANG`, repli `fr-FR` | langue des messages |
| `--dossier-journal` | dossier d'où le script est lancé | journal de `--alpha-test` |
| `--session-secours` | `non` | `oui` : une deuxième session est ouverte et testée ; **obligatoire** pour recharger sshd |
| `--code-remplacement-confirme` | `non` | `oui` autorise le remplacement de fichiers installés qui diffèrent |
| `--stockage-actif` | `oui` | `non` désactive les sauvegardes (le retour arrière échoue alors : à éviter) |
| `--sauter <étape>` | aucune | liste fermée : `produit` (relais seulement : contrôle de l'image strfry), `fonctions` (relais seulement : pose des fonctions de Remus), `sudoers`, `nftables`, `isolation_remus`, `www-data` |
| `--activer` | non | active les unités au démarrage du système, seulement après vérification : côté admin `pollux` et `romulus` (le tunnel, tiré par ces deux services, n'est jamais activé pour lui-même) ; côté relais `castor`, `remus` et la table nftables |
| `--mise-a-jour` | non | `oui` : met à jour une installation existante (arrêt et reprise des seules unités de Paresia, sauvegarde, retour arrière automatique en cas d'échec ; voir `INSTALL.md`, § 12) |
| `--retour-arriere --jeu <nom> --confirme` | — | retour arrière (voir [Sauvegarde et retour arrière](Sauvegarde-et-retour-arriere.md)) |

Paramètres propres au relais : `--repertoire-tunnel` (défaut `/var/lib/paresia-tunnel`, jamais sous `/home`), `--profil`, `--port-essai`, `--acces-tunnel-sans-nftables`. Propres à l'administration : `--repertoire-app` (défaut `/var/lib/paresia-app`).

## Codes de sortie

Ils suivent `sysexits.h` : 0 succès ; 64 usage (paramètre absent, option inconnue) ; 65 valeur invalide ; 66 catalogue illisible ; 69 prérequis manquant ; 73 journal déjà existant ; 74 sauvegarde en échec ; 77 compte d'exécution refusé ; 78 état différent de l'attendu.

## Ce que le script crée

- des **comptes système** sans mot de passe ni répertoire sous `/home` (côté relais : `paresia-castor`, `chef`, `tunnel` ; côté admin : `app`, `paresia-romulus`, `paresia-pollux`, `paresia-tunnel`), dont les **numéros (uid et gid) sont choisis par le système** dans la plage système de `login.defs(5)`, relevés puis reportés dans la configuration installée (les numéros du dépôt ne sont que des exemples) ; un compte ou un groupe déjà présent et conforme est repris tel quel, un compte non conforme est refusé (code 78) ;
- le code sous `/usr/local/lib/paresia`, la configuration sous `/etc/paresia/` (`paresia.conf`, `conf.d/`) ;
- côté admin, les **pages de l'interface d'administration** sous `/usr/local/share/paresia/web/` (propriété de root, jamais modifiables par un autre compte), avec, sous `greffons/`, les pages des greffons installés et un fichier `index.json` qui les liste. Le script contrôle ces fichiers, génère l'index et le vérifie ; en cas d'échec il retire l'index et s'arrête, il n'en laisse jamais un incomplet. **Il ne sert pas ces fichiers** : il n'installe ni ne configure aucun serveur web. C'est à vous de faire servir ce dossier sous `/admin/` par votre serveur web (voir la documentation du serveur web) ;
- les unités systemd (`pollux`, `romulus`, `paresia-tunnel` ; `castor`, `remus`, `paresia-nftables`) ;
- côté relais, le fichier `/etc/sudoers.d/paresia-remus` (généré) et la table nftables `paresia_relais`.

## Après le script

L'essai de bout en bout de la présence reste une procédure : `deploy/essai-presence.md`. La page [Premier usage](Premier-usage.md) dit quoi vérifier.

## Vous avez déjà un relais strfry en service ?

Le script **ne touche pas** à votre conteneur strfry. L'intégration (configuration `strfry.conf` livrée, plugin du journal légal dans l'image) est décrite dans [Administrer le relais strfry](Administration-du-relais-strfry.md).

## Mettre à jour une installation existante

Avec le même script et l'option `--mise-a-jour` : le script compare la version installée à celle de votre clone, sauvegarde, arrête les seules unités de Paresia, remplace le code et la configuration livrée (en conservant vos fichiers modifiés, la version livrée étant déposée à côté en `.paresia-nouveau`), puis redémarre les unités qui étaient actives. En cas d'échec d'une vérification, il revient en arrière. Le détail est dans `INSTALL.md`, § 12.

## À venir

- Unités systemd de bunkerd et de Nisaba, procédure de migration depuis les anciens scripts `journal-legal-*` : non livrées.
- **lighttpd** (serveur web) **et HAProxy** (proxy et répartiteur de charge) : Paresia ne les installe pas et ne les configure pas. Elle en documente seulement les exigences (pages servies, acheminement vers Romulus, flux continus sans tampon, adresse du client, en-têtes) : `docs/serveur-web.md`, avec un extrait d'exemple pour lighttpd à adapter.
- Mode Docker rootless tout-en-un : après la 1.0.
