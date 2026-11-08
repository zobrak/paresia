# Installation : côté yin et côté yang

Version du document : 0.1.19 · 2026-11-08 · [Accueil](Accueil.md)

Suivi, 2026-11-08 : réécrite pas à pas, dépôt récupéré dès le début ; numéro du document inchangé.

Alpha : pas en production, à essayer sur des machines jetables. Cette page donne le chemin court de l'installation, puis les raisons et les références. Les commandes complètes, avec les paquets et les contrôles, sont dans `INSTALL.md` à la racine du dépôt.

## Avant de commencer

Il vous faut :

- deux machines Debian 13 : `backend-admin` (yang) et `backend-relais` (yin) ;
- sur chaque machine, un compte ordinaire membre du groupe `sudo`, avec `curl` installé ;
- un second terminal ouvert sur chaque machine (session de secours) ;
- le conteneur `strfry` en marche sur `backend-relais` (page « Installer le relais strfry »).

### À personnaliser obligatoirement

| Valeur | Où | Exemple du guide | Ce qu'il faut mettre |
| --- | --- | --- | --- |
| adresse de `backend-admin` | passe 2, `--adresse-admin` | `192.0.2.10` | l'adresse IP de `backend-admin` |
| adresse de `backend-relais` | passe 3, `--adresse-relais` | `192.0.2.20` | l'adresse IP de `backend-relais` (une adresse, non un nom) |
| `CLE_PUBLIQUE_TUNNEL` | passe 2 | affichée par la passe 1 | ce qui suit `CLE_PUBLIQUE_TUNNEL=` |
| `EMPREINTE_CLE_TUNNEL` | passe 2 | affichée par la passe 1 | ce qui suit `EMPREINTE_CLE_TUNNEL=` |
| `EMPREINTE_HOTE_RELAIS` | passe 3 | affichée par la passe 2 | ce qui suit `EMPREINTE_HOTE_RELAIS=` |

## 1. Récupérer le dépôt

Machines : `backend-admin` (en root) puis `backend-relais` (avec votre compte, `sudo` devant `apt`).

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

## 2. Vérifier

Machine : chacune, dans `~/paresia`. Rien n'est modifié.

```
bash deploy/backend-admin/installer-backend-admin.sh --verifier
```

```
bash deploy/backend-relais/installer-backend-relais.sh --verifier
```

La première commande se lance sur `backend-admin`, la seconde sur `backend-relais`. Résultat attendu : aucune erreur. Un prérequis manquant donne le code 69 et son nom.

## 3. Passe 1 : backend-admin

Machine : `backend-admin`, en root.

```
bash deploy/backend-admin/installer-backend-admin.sh --alpha-test --session-secours oui
```

Résultat attendu : deux lignes à copier.

```
CLE_PUBLIQUE_TUNNEL=ssh-ed25519 AAAA…
EMPREINTE_CLE_TUNNEL=SHA256:…
```

## 4. Passe 2 : backend-relais

Machine : `backend-relais`, avec votre compte.

**À personnaliser : remplacez `192.0.2.10` par l'adresse de `backend-admin`, et `CLE_PUBLIQUE_TUNNEL` et `EMPREINTE_CLE_TUNNEL` par les valeurs de la passe 1.**

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

## 5. Passe 3 : backend-admin, le tunnel

Machine : `backend-admin`, en root.

**À personnaliser : remplacez `192.0.2.20` par l'adresse IP de `backend-relais`, et `EMPREINTE_HOTE_RELAIS` par la valeur de la passe 2.**

```
bash deploy/backend-admin/installer-backend-admin.sh --alpha-test --session-secours oui \
  --adresse-relais 192.0.2.20 \
  --empreinte-hote-relais 'EMPREINTE_HOTE_RELAIS'
```

Résultat attendu : le tunnel est posé et démarré après comparaison de l'empreinte avec celle de `ssh-keyscan`.

## 6. Contrôler

Machine : `backend-admin`.

```
systemctl status pollux.service romulus.service paresia-tunnel.service
```

Résultat attendu : trois unités à l'état `active (running)`.

Sur `backend-relais` :

```
sudo /usr/bin/systemctl status castor.service remus.service
```

Résultat attendu : deux unités à l'état `active (running)`.

## Suite

[Premier usage](Premier-usage.md) ; [Sauvegarde et retour arrière](Sauvegarde-et-retour-arriere.md) ; [Administrer le relais strfry](Administration-du-relais-strfry.md).

## Annexe A : principe des scripts

Chaque machine s'installe par un script complet et commenté (`deploy/backend-admin/installer-backend-admin.sh`, `deploy/backend-relais/installer-backend-relais.sh`). Le script :

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

Le tunnel demande un échange de clés dans cet ordre : `backend-admin` génère la clé du tunnel (la clé privée y reste) ; `backend-relais` reçoit adresse, clé publique et empreinte, puis affiche l'empreinte de sa clé d'hôte ; `backend-admin` compare cette empreinte à `ssh-keyscan`. L'empreinte passe par un second canal, pas par le tunnel qu'elle protège.

Deux machines, deux règles, voulues par le mainteneur (voir [`docs/decisions.md`](../decisions.md)) :

- `backend-admin` : root, sans `sudo` installé (une porte de moins). Tout autre compte est refusé (code 77).
- `backend-relais` : aucun shell root ; compte ordinaire avec `sudo` (1.9.10 au moins) limité aux commandes nécessaires, par chemin absolu. Root est refusé (code 77).

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
| `--sauter <étape>` | aucune | `produit` (relais : contrôle de l'image strfry), `fonctions` (relais), `sudoers`, `nftables`, `isolation_remus`, `www-data` |
| `--activer` | non | active les unités au démarrage, après vérification (le tunnel, tiré par `pollux` et `romulus`, n'est jamais activé pour lui-même) |
| `--mise-a-jour` | non | met à jour une installation existante (voir `INSTALL.md`, annexe A) |
| `--retour-arriere --jeu <nom> --confirme` | | retour arrière |

Propres au relais : `--repertoire-tunnel` (défaut `/var/lib/paresia-tunnel`, jamais sous `/home`), `--profil`, `--port-essai`, `--acces-tunnel-sans-nftables`. Propre à l'administration : `--repertoire-app` (défaut `/var/lib/paresia-app`).

## Annexe E : codes de sortie

Selon `sysexits.h` : 0 succès ; 64 usage ; 65 valeur invalide ; 66 catalogue illisible ; 69 prérequis manquant ; 73 journal déjà existant ; 74 sauvegarde en échec ; 77 compte d'exécution refusé ; 78 état différent de l'attendu.

## Annexe F : ce que les scripts créent

- Des comptes système sans mot de passe ni répertoire sous `/home` (relais : `paresia-castor`, `chef`, `tunnel` ; admin : `app`, `paresia-romulus`, `paresia-pollux`, `paresia-tunnel`). Leurs uid et gid sont choisis par le système dans la plage de `login.defs(5)` et reportés dans la configuration. Un compte conforme est repris ; un compte non conforme est refusé (code 78).
- Le code sous `/usr/local/lib/paresia`, la configuration sous `/etc/paresia/` (`paresia.conf`, `conf.d/`).
- Côté admin, les pages de l'interface sous `/usr/local/share/paresia/web/` (propriété de root), avec sous `greffons/` les pages des greffons et un `index.json`. Le script ne sert pas ces fichiers : à vous de les faire servir sous `/admin/` (`docs/serveur-web.md`).
- Les unités systemd (`pollux`, `romulus`, `paresia-tunnel` ; `castor`, `remus`, `paresia-nftables`).
- Côté relais, `/etc/sudoers.d/paresia-remus` (généré) et la table nftables `paresia_relais`.

## Annexe G : réserves

- Les unités et l'installation de bunkerd et de Nisaba ne sont pas livrées. Procédure de migration depuis les anciens scripts `journal-legal-*` : non livrée.
- Paresia n'installe ni lighttpd ni HAProxy ; elle en documente les exigences (`docs/serveur-web.md`, avec un extrait pour lighttpd).
- Mode Docker rootless tout-en-un : après la 1.0.
- Essai de bout en bout de la présence : `deploy/essai-presence.md`.
- Références : pages de manuel `installer-backend-admin(8)` et `installer-backend-relais(8)`, `docs/prerequis.md`. Lisez `--aide` de la version que vous avez.
