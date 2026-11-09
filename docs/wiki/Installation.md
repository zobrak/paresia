# Installation semi-automatique : côté yin et côté yang

Version du document : 0.1.19 · 2026-11-08 · [Accueil](Accueil.md)

Suivi, 2026-11-09 : mêmes titres et mêmes noms (yin, yang) que `INSTALL.md` ; numéro du document inchangé.

Alpha : pas en production, à essayer sur des machines jetables. Cette page décrit l'**installation semi-automatique** (vous enchaînez les étapes, les scripts font le travail), à distinguer de l'installation automatique prévue pour la 1.0, pilotée par le client (D176). Elle donne le chemin court de l'installation, puis les raisons et les références. Les commandes complètes, avec les paquets et les contrôles, sont dans `INSTALL.md` à la racine du dépôt ; cette page a sa propre numérotation, plus courte, avec les mêmes titres de parties.

**Yang** est la machine d'administration, non exposée (`backend-admin` dans les noms de scripts et de dossiers). **Yin** est la machine du relais, exposée (`backend-relais` dans les noms de scripts et de dossiers). Chaque machine a besoin d'une valeur produite par l'autre : l'installation alterne entre elles.

## Sommaire

- [Avant de commencer](#avant-de-commencer)
- [I. Installer les prérequis](#i-installer-les-prérequis) : étape 1
- [II. Installer les démons](#ii-installer-les-démons) : étapes 2 à 4
- [III. Relier les deux machines](#iii-relier-les-deux-machines) : étape 5
- [IV. Vérifier](#iv-vérifier) : étape 6
- Suite : autoriser votre clé d'administrateur et premier usage (`INSTALL.md`, étape 15)
- Annexes A à G

## Avant de commencer

Il vous faut :

- deux machines Debian 13 : yang et yin ;
- sur chaque machine, un compte ordinaire membre du groupe `sudo`, avec `curl` installé ;
- un second terminal ouvert sur chaque machine (session de secours) ;
- le conteneur `strfry` en marche sur yin (page « Installer le relais strfry »).

### À personnaliser obligatoirement

| Valeur | Où | Exemple du guide | Ce qu'il faut mettre |
| --- | --- | --- | --- |
| adresse de yang | passe 2, `--adresse-admin` | `192.0.2.10` | l'adresse IP de yang |
| adresse de yin | passe 3, `--adresse-relais` | `192.0.2.20` | l'adresse IP de yin (une adresse, non un nom) |
| `CLE_PUBLIQUE_TUNNEL` | passe 2 | affichée par la passe 1 | ce qui suit `CLE_PUBLIQUE_TUNNEL=` |
| `EMPREINTE_CLE_TUNNEL` | passe 2 | affichée par la passe 1 | ce qui suit `EMPREINTE_CLE_TUNNEL=` |
| `EMPREINTE_HOTE_RELAIS` | passe 3 | affichée par la passe 2 | ce qui suit `EMPREINTE_HOTE_RELAIS=` |

# I. Installer les prérequis

## A. Sur yang puis sur yin

### 1. Sur yang puis sur yin : récupérer le dépôt

On récupère le code et ses scripts d'installation sur chaque machine. Machines : yang (en root) puis yin (avec votre compte, `sudo` devant `apt`).

```
apt install git
```

```
git clone https://github.com/zobrak/paresia.git ~/paresia
```

```
cat ~/paresia/VERSION
```

Résultat attendu (sur les deux machines) :

```
0.1.19
```

Étape terminée quand la version s'affiche sur les deux machines. Passez à l'étape 2.

# II. Installer les démons

## A. Vérifier, sur yang et sur yin

### 2. Sur yang et sur yin : vérifier

Chaque script contrôle que sa machine est prête, sans rien modifier. Machine : chacune, dans `~/paresia`.

```
bash deploy/backend-admin/installer-backend-admin.sh --verifier
```

```
bash deploy/backend-relais/installer-backend-relais.sh --verifier
```

La première commande se lance sur yang, la seconde sur yin. Résultat attendu : aucune sortie. **Aucune sortie signifie : tous les prérequis de la machine sont présents et rien n'a été modifié.** Passez à l'étape 3.

En cas d'échec, le script s'arrête avec le code 69 et nomme le prérequis manquant : installez-le (paquets listés dans `INSTALL.md`, étapes 3 et 5), puis relancez la commande.

## B. Première passe, sur yang

### 3. Sur yang : installer les démons (passe 1)

Le script installe Pollux et Romulus et crée la clé du tunnel, dont yin a besoin. Machine : yang, en root.

```
bash deploy/backend-admin/installer-backend-admin.sh --alpha-test --session-secours oui
```

Résultat attendu : deux lignes à copier.

```
CLE_PUBLIQUE_TUNNEL=ssh-ed25519 AAAA…
EMPREINTE_CLE_TUNNEL=SHA256:…
```

Notez-les : elles servent à la passe 2. Passez à l'étape 4.

## C. Deuxième passe, sur yin

### 4. Sur yin : installer les démons (passe 2)

Le script installe Castor et Remus et autorise la clé du tunnel de la passe 1. Machine : yin, avec votre compte.

**À personnaliser : remplacez `192.0.2.10` par l'adresse de yang, et `CLE_PUBLIQUE_TUNNEL` et `EMPREINTE_CLE_TUNNEL` par les valeurs de la passe 1.**

```
bash deploy/backend-relais/installer-backend-relais.sh --alpha-test --session-secours oui \
  --adresse-admin 192.0.2.10 \
  --cle-publique-tunnel 'CLE_PUBLIQUE_TUNNEL' \
  --empreinte-cle-tunnel 'EMPREINTE_CLE_TUNNEL'
```

Résultat attendu : une ligne à transmettre par un autre canal que le tunnel.

```
EMPREINTE_HOTE_RELAIS=SHA256:…
```

Notez-la : elle sert à l'étape 5. Passez à l'étape 5.

# III. Relier les deux machines

### 5. Sur yang : poser le tunnel (passe 3)

Yang connaît maintenant l'empreinte de yin : le script la compare à celle de `ssh-keyscan`, puis pose le tunnel et le démarre. Machine : yang, en root.

**À personnaliser : remplacez `192.0.2.20` par l'adresse IP de yin, et `EMPREINTE_HOTE_RELAIS` par la valeur de la passe 2.**

```
bash deploy/backend-admin/installer-backend-admin.sh --alpha-test --session-secours oui \
  --adresse-relais 192.0.2.20 \
  --empreinte-hote-relais 'EMPREINTE_HOTE_RELAIS'
```

Résultat attendu : le tunnel est posé et démarré après comparaison de l'empreinte avec celle de `ssh-keyscan`. Si l'empreinte diffère, le script s'arrête sans poser le tunnel : reprenez l'empreinte affichée sur yin. Passez à l'étape 6.

# IV. Vérifier

### 6. Sur yang puis sur yin : contrôler les unités

On contrôle que les démons tournent. Machine : yang d'abord.

```
systemctl status pollux.service romulus.service paresia-tunnel.service
```

Résultat attendu : trois unités à l'état `active (running)`.

Puis sur yin :

```
sudo /usr/bin/systemctl status castor.service remus.service
```

Résultat attendu : deux unités à l'état `active (running)`. L'installation est terminée : passez à « Suite » ci-dessous (et à `INSTALL.md`, étape 15, pour autoriser votre clé).

## Suite

[Premier usage](Premier-usage.md) ; [Sauvegarde et retour arrière](Sauvegarde-et-retour-arriere.md) ; [Administrer le relais strfry](Administration-du-relais-strfry.md).

## Annexe A : principe des scripts

Chaque machine s'installe par un script complet et commenté (`deploy/backend-admin/installer-backend-admin.sh` pour yang, `deploy/backend-relais/installer-backend-relais.sh` pour yin ; les noms des scripts et des dossiers gardent les anciens noms). Le script :

- s'exécute depuis un clone que vous avez fait vous-même ; il ne clone ni ne télécharge rien ;
- ne pose aucune question : option de ligne de commande, sinon variable d'environnement, sinon valeur par défaut ;
- vérifie tout avant de modifier : une valeur absente ou invalide l'arrête (code 64 ou 65) ;
- est rejouable : état déjà conforme, rien ne se passe ; état différent, refus (code 78) ;
- sauvegarde avant toute modification ;
- n'arrête et ne redémarre aucune unité, sauf sous `--mise-a-jour` ; il démarre (`start`) celles qu'il pose, et n'active au démarrage que sous `--activer` ;
- ne recharge `sshd` qu'après `sshd -t` et avec une session de secours (`--session-secours oui`) ; jamais de `restart` ;
- ne touche jamais à strfry, Docker, lighttpd, bunkerd ;
- n'affiche ni ne journalise aucune clé privée ;
- affiche ses messages depuis le catalogue de langue du clone (`fr-FR` ou `en-US`, selon `LC_ALL`/`LANG`).

Ce que chaque machine installe : côté yang, Pollux, `pollux-session`, Romulus et le tunnel ; côté yin, Castor, Remus, leurs comptes, le sudoers généré, la table nftables et le tunnel du relais.

## Annexe B : pourquoi trois passes, et deux règles de compte

Le tunnel demande un échange de clés dans cet ordre : yang génère la clé du tunnel (la clé privée y reste) ; yin reçoit adresse, clé publique et empreinte, puis affiche l'empreinte de sa clé d'hôte ; yang compare cette empreinte à `ssh-keyscan`. L'empreinte passe par un second canal, pas par le tunnel qu'elle protège.

Deux machines, deux règles, voulues par le mainteneur (voir [`docs/decisions.md`](../decisions.md)) :

- yang : root, sans `sudo` installé (une porte de moins). Tout autre compte est refusé (code 77).
- yin : aucun shell root ; compte ordinaire avec `sudo` (1.9.10 au moins) limité aux commandes nécessaires, par chemin absolu. Root est refusé (code 77).

L'en-tête de chaque script liste les commandes privilégiées lancées. Elle est descriptive, non un sudoers à recopier.

## Annexe C : le mode `--alpha-test`

Temporaire, retiré après validation :

- pause après chaque étape (Entrée pour continuer) ; arrêt au premier écart ;
- affichage de chaque vérification et de chaque relevé ;
- avertissement avant toute commande destructive ou risquée ;
- journal horodaté sans secret `alpha-test-<machine>-<date>.log`, écrit dans le dossier de lancement (ou `--dossier-journal`). Le dossier doit exister, ne pas être un lien symbolique, appartenir à root ou à votre compte et n'être modifiable ni par le groupe ni par les autres ; fichier en `0600`, jamais écrasé. Un journal sous `/var/log/paresia` est refusé.
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
| `--mise-a-jour` | non | met à jour une installation existante (voir `INSTALL.md`, annexe A) |
| `--retour-arriere --jeu <nom> --confirme` | | retour arrière |

Propres à yin : `--repertoire-tunnel` (défaut `/var/lib/paresia-tunnel`, jamais sous `/home`), `--profil`, `--port-essai`, `--acces-tunnel-sans-nftables`. Propre à yang : `--repertoire-app` (défaut `/var/lib/paresia-app`).

## Annexe E : codes de sortie

Selon `sysexits.h` : 0 succès ; 64 usage ; 65 valeur invalide ; 66 catalogue illisible ; 69 prérequis manquant ; 73 journal déjà existant ; 74 sauvegarde en échec ; 77 compte d'exécution refusé ; 78 état différent de l'attendu.

## Annexe F : ce que les scripts créent

- Des comptes système sans mot de passe ni répertoire sous `/home` (yin : `paresia-castor`, `chef`, `tunnel` ; yang : `app`, `paresia-romulus`, `paresia-pollux`, `paresia-tunnel`). Leurs uid et gid sont choisis par le système dans la plage de `login.defs(5)` et reportés dans la configuration. Un compte conforme est repris ; un compte non conforme est refusé (code 78).
- Le code sous `/usr/local/lib/paresia`, la configuration sous `/etc/paresia/` (`paresia.conf`, `conf.d/`).
- Sur yang, les pages de l'interface sous `/usr/local/share/paresia/web/` (propriété de root), avec sous `greffons/` les pages des greffons et un `index.json`. Le script ne sert pas ces fichiers : à vous de les faire servir sous `/admin/` (`docs/serveur-web.md`).
- Les unités systemd (`pollux`, `romulus`, `paresia-tunnel` ; `castor`, `remus`, `paresia-nftables`).
- Sur yin, `/etc/sudoers.d/paresia-remus` (généré) et la table nftables `paresia_relais`.

## Annexe G : réserves

- Les unités et l'installation de bunkerd et de Nisaba ne sont pas livrées. Procédure de migration depuis les anciens scripts `journal-legal-*` : non livrée.
- Paresia n'installe ni lighttpd ni HAProxy ; elle en documente les exigences (`docs/serveur-web.md`, avec un extrait pour lighttpd).
- Mode Docker rootless tout-en-un : après la 1.0.
- Essai de bout en bout de la présence : `deploy/essai-presence.md`.
- Références : pages de manuel `installer-backend-admin(8)` et `installer-backend-relais(8)`, `docs/prerequis.md`. Lisez `--aide` de la version que vous avez.
