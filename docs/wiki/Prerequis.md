# Prérequis

Version du document : 0.1.19 · 2026-11-08 · [Accueil](Accueil.md)

Référence, avec la source de chaque ligne : [Prérequis](../prerequis.md). Cette page en donne le sens.

## Machines

| Machine | Rôle | Obligatoire |
| --- | --- | --- |
| `backend-admin` (yang) | Romulus, Pollux, tunnel sortant, et les greffons Nisaba et bunker | oui |
| `backend-relais` (yin) | Remus, Castor, le relais strfry (dans un conteneur Docker) | oui |
| pare-feu et reverse proxy | HAProxy et lighttpd devant `backend-admin` | recommandé ; hors dépôt, à votre charge |
| poste client | l'application Paresia-admin et un agent SSH | oui pour l'usage quotidien |

Le cloisonnement exige **deux machines distinctes** (physiques, virtuelles ou conteneurs séparés). Un seul tunnel TCP 22 doit pouvoir aller de `backend-admin` vers `backend-relais`.

## Système

- **Debian 13** est le système cible ; la CI le vérifie.
- **Python 3.11 au moins** (3.13 sur Debian 13) : tous les démons n'emploient que la bibliothèque standard de Python, sauf mentions ci-dessous.
- **systemd 257 ou plus** conseillé sur `backend-admin` (Debian 13 livre la 257). Sous 257, le script d'installation ne refuse pas : il retire de l'unité l'option `::ro`, qu'il ne comprend pas.
- **Compte d'exécution** : sur `backend-admin`, vous travaillez en root et vous n'installez pas `sudo`. Sur `backend-relais`, il n'y a pas de shell root : vous utilisez un compte ordinaire avec `sudo`, limité aux commandes nécessaires, par chemins absolus.

## backend-admin

- OpenSSH (`sshd`), avec `sshd_config.d` inclus par la configuration principale ;
- `python3-cryptography` : vérifie la signature du défi de présence (sans lui, toute preuve est refusée) et signe la liste de sourdine ; le script d'installation de `backend-admin` le contrôle (code 69 s'il manque) ;
- `libssl3t64` **3.5.7-1~deb13u3 au moins** : correctif de sécurité pour la multiplication de clés secp256k1 à temps constant (contrôlé par le script d'installation de `backend-admin`) ;
- `acl` (`setfacl`, `getfacl`), `openssh-client` (dont `ssh-keygen` et `ssh-keyscan`), `curl`, `rsync` ; le script d'installation contrôle aussi Debian 13, Python 3.11 et `sshd` ;
- pour le journal légal (Nisaba) : `ots` (OpenTimestamps), `chattr` et `lsattr` (paquet `e2fsprogs`) ;
- pour le bunker : l'exécutable `nak` (signature Nostr) ; `python3-qrcode` facultatif (code QR de la page de déverrouillage) ;
- lighttpd (frontal HTTP vers Romulus) : requis, mais **installé et configuré par vous** ; Paresia n'en documente que les exigences : [Serveur web](../serveur-web.md).

## backend-relais

- OpenSSH (`sshd`), nftables, `sudo` **1.9.10 au moins** (expressions régulières d'arguments dans le fichier sudoers généré ; Debian 13 fournit 1.9.16), `visudo` ;
- Docker, pour le conteneur strfry ; conseil, non une obligation : sur Debian 13, `apt install extrepo`, `extrepo enable docker-ce`, `apt update`, puis `apt install docker-ce docker-ce-cli containerd.io docker-compose-plugin` ;
- l'image strfry **n'est pas l'image d'origine** : elle contient `python3`, requis par le plugin d'écriture du journal légal. L'image publique du projet est `z0brak/paresia-yin-strfry:4cd3cf6`. Ses modifications exactes sont **non établies** dans le dépôt (voir [Prérequis](../prerequis.md), § 5) ; ne pas supposer que l'image d'origine suffit ;
- `rrsync` côté relais pour la copie en lecture seule du journal légal.

## Poste client

- `python3-pyqt6`, `python3-pyqt6.qtsvg` et le module QtWebEngine pour PyQt6 ;
- `rbw` (client Bitwarden, lit la phrase de déverrouillage du bunker dans le coffre) ;
- `openssh-client` et un agent SSH quelconque (norme du protocole d'agent SSH, RFC 9987).

## Ce qui n'est pas un prérequis

Les outils de développement (git, pytest, outils d'analyse…) servent à construire Paresia, non à l'installer ni à l'exécuter.

## À venir

- Version minimale de systemd côté relais : **non établie**.
- Liste complète de paquets par machine : les paquets de base sont dans [INSTALL.md](../../INSTALL.md), étapes [3](../../INSTALL.md#3-sur-yang--installer-les-paquets) et [5](../../INSTALL.md#5-sur-yin--installer-les-paquets) ; les autres figurent dans [Prérequis](../prerequis.md).
