# Prérequis et dépendances de Paresia

Version du document : 0.1.19 · 2026-11-08. Public : administrateur (§ 1 à 5), développeur (§ 6).

Liste par machine. Elle ne contient que ce qui est vérifiable : chaque ligne cite sa source (code, procédure, cahier des charges). Une version minimale n'est donnée que si une source l'écrit. Les licences des dépendances sont dans `docs/licences-tierces.md`. Les outils de développement ne sont pas des prérequis de Paresia.

Système cible : Debian 13 (CI sur Python 3.13). Deux modes de déploiement sont prévus : le mode **distribué**, `paresia-yin` (Remus, Castor) et `paresia-yang` (Romulus, Pollux) installés par script sur des machines séparées, livré en 1.0 ; le mode **Docker rootless tout-en-un**, après la 1.0. Le lien yin–yang reste le tunnel SSH dans les deux modes. Les prérequis ci-dessous valent pour le mode distribué ; ceux du mode Docker rootless ne sont pas établis (emballage non écrit).

**Contrôle automatique.** Le script d'installation de chaque machine vérifie ses prérequis avant de modifier quoi que ce soit (étape `prerequis`, option `--verifier`) et s'arrête avec le code 69 si l'un manque. Ce que contrôle chaque script est indiqué aux § 2 et 3.

## 1. Toutes les machines de Paresia-server

| Élément | Version minimale | Rôle | Source |
| --- | --- | --- | --- |
| `sh` | — | lanceurs `server/bin/*` | en-têtes de `server/bin/pollux-session` et `server/bin/bunkerd` |
| Python 3 (`/usr/bin/python3`) | 3.11 | tous les démons | contrôle `python-3.11` des deux scripts d'installation |
| Bibliothèque standard de Python | — | Pollux, Romulus, Castor, Remus, socle commun, bunkerd | en-têtes de `server/**/*.py` |

## 2. backend-admin

Le script `deploy/backend-admin/installer-backend-admin.sh` contrôle : Debian 13, systemd (version relevée), Python 3.11 ou plus, `python3-cryptography`, `curl`, `ssh-keygen`, `ssh-keyscan` et `sshd`.

| Élément | Version minimale | Rôle | Source | Statut |
| --- | --- | --- | --- | --- |
| Debian 13 | — | système cible | contrôle `debian-13` du script | requis |
| systemd | 257 ou plus conseillé | unités `pollux.service` et `romulus.service` ; `ConfigurationDirectory=paresia::ro` (avant 257, le script et la procédure retirent `::ro`) | script (`lire_systemd`) ; unités de `deploy/backend-admin/etc/systemd/system/` | requis ; sous 257 l'unité installée est normalisée, le script ne refuse pas |
| `systemd-analyze` (avec systemd) | — | contrôle des unités (`verify`) | procédure `installation-pollux-romulus.md`, étape 9 ; `tests/test_installation_pollux_romulus.py` | requis pour la procédure |
| `curl` | — | essais d'installation : requêtes HTTP sur la socket de Romulus (`--unix-socket`) | script (`controle_prerequis`) | requis |
| `ssh-keygen`, `ssh-keyscan` (paquet `openssh-client`) | — | clé de test ; comparaison de l'empreinte de la clé d'hôte du relais | script (`controle_prerequis`) | requis |
| OpenSSH (`sshd`) | — | session de présence, compte `app`, commande forcée `pollux-session` ; bloc `Match User app` dans `sshd_config.d/` (la configuration principale doit inclure `sshd_config.d`) | cahier des charges, § Session de présence ; script (`/usr/sbin/sshd`) | requis |
| `runuser`, `getent`, `ss` (paquet `iproute2`) | — | contrôles du script et de la procédure (comptes, sockets) ; le script contrôle `ss` à l'étape `prerequis` et signale tous les prérequis manquants en une fois | script (étapes `demarrage` et `tunnel_sockets`) ; procédure `installation-pollux-romulus.md` | requis |
| `python3-cryptography` | — | signature de la liste de sourdine (NIP-49, BIP-340, multiplication scalaire secp256k1) ; vérification des signatures SSHSIG du défi de présence | `server/bunkerd/signature.py`, `server/commun/sshsig.py` ; script (`import cryptography`) | requis sur backend-admin ; absente, Pollux répond `not_available` et refuse toute preuve. Installation : `sudo /usr/bin/apt install`, étape C de `deploy/essai-presence.md` |
| `libssl3t64` (OpenSSL) | **3.5.7-1~deb13u3** | multiplication scalaire de `cryptography` à temps constant pour secp256k1 (échelle de Montgomery) ; versions antérieures sans le correctif de CVE-2026-54872 (DSA-6531-1, vérifié sur le security-tracker de Debian) | commentaire de `server/bunkerd/signature.py` | requis, contrôlé par le script d'installation de backend-admin (`dpkg-query` et `dpkg --compare-versions` ; code 69 s'il manque ou s'il est trop ancien) ; à vérifier aussi par `dpkg -s libssl3t64` |
| `nak` (binaire, `/usr/local/bin/nak` dans l'exemple ; amont https://github.com/fiatjaf/nak, licence The Unlicense, `docs/licences-tierces.md`) | v0.22.3 (SHA-256 du binaire `linux-amd64` : `2eb9a16f86c865275983459b2c705d22d5dfbcf527026a279449cbf204d164fe`, installation : `docs/wiki/Installer-nak.md`, sur le poste des clés privées et sur `backend-admin`) | signataires NIP-46 de bunkerd | `server/bunkerd/__main__.py` (en-tête) ; `server/conf/paresia.conf`, `[bunkerd.outils]` | requis sur `backend-admin` (bunkerd) et sur le poste où les clés privées sont conservées (création de la clé du relais) ; inutile sur `backend-relais` |
| `setfacl` (paquet `acl`) | — | ACL des sockets de bunkerd ; ACL du journal légal (le tunnel n'en a plus besoin) | `server/bunkerd/__main__.py` ; `server/conf/paresia.conf` | requis par bunkerd et Nisaba |
| `python3-qrcode` | — | code QR de la page de déverrouillage | en-tête de `server/bunkerd/web.py` | facultatif |
| `rsync`, `ssh`, `flock`, `logger`, `chattr` et `lsattr`, `ots` (OpenTimestamps), `runuser` | non indiquée | scripts `journal-legal-*` | en-têtes de `deploy/backend-admin/usr/local/sbin/journal-legal-*.sh` ; simulacres de `tests/outils/journal_legal/` | requis par le journal légal (scripts) |
| `rsync`, `ssh` (paquet `openssh-client`), `ots` (OpenTimestamps), `chattr` et `lsattr` (paquet `e2fsprogs`), `setfacl` et `getfacl` (paquet `acl`) | non indiquée | Nisaba : copie depuis backend-relais, horodatage, immuabilité, modes et ACL ; programmes lancés par argv, chemins réglés dans `[nisaba.source]`, `[nisaba.ots]`, `[nisaba.journal]`, `[nisaba.droits]` ; `CAP_LINUX_IMMUTABLE` donnée par l'unité (non livrée) ; Nisaba n'emploie ni `flock`, ni `logger`, ni `runuser` | `server/conf/paresia.conf` ; `docs/configuration.md`, § Nisaba ; D87 | requis par Nisaba |
| `ssh` (paquet `openssh-client`) | — | unité `paresia-tunnel.service` : `ssh -F … -N` ; dossiers des sockets créés par `systemd-tmpfiles` (`tmpfiles.d(5)`, fourni par systemd) avec propriétaire, groupe et mode, sans ACL | `deploy/backend-admin/etc/systemd/system/paresia-tunnel.service` ; `deploy/backend-admin/etc/tmpfiles.d/paresia-tunnel.conf` | requis par l'unité du tunnel |
| lighttpd | non indiquée | frontal HTTP vers Romulus | cahier des charges, § Réseau, lighttpd et tunnel SSH | requis (exigences et extrait d'exemple : `docs/serveur-web.md` ; Paresia ne l'installe pas ni ne le configure) |

HAProxy tourne sur le pare-feu, hors dépôt.

**Compte d'exécution** : sur backend-admin, on travaille en root et on n'installe pas `sudo` ; `sudo` n'est donc pas un prérequis de backend-admin. Sur backend-relais, il n'y a pas de shell root et `sudo` (1.9.10 au moins) est limité aux commandes strictement nécessaires (Remus et script d'installation).

**Procédures** : les procédures de `deploy/` (tunnel, essai de présence, installation de Pollux et de Romulus, installation du relais) sont écrites avec `sudo` et chemin absolu par commande, sans shell root, et donnent en tête la liste descriptive des commandes `sudo`. Sur backend-admin (root), le préfixe `sudo` se retire. `docs/installation-journal-legal-acl.md` est écrite pour backend-admin en root, sans `sudo` (aucune commande à préfixer) ; ses versions de scripts (pull 1.2.1, seal 1.3.0, acl 1.1.0, purge 1.1.0) correspondent à celles de `deploy/backend-admin/usr/local/sbin/`.

## 3. backend-relais

Le script `deploy/backend-relais/installer-backend-relais.sh` contrôle : Debian 13, systemd, Python 3.11 ou plus, `ss`, `sudo`, `nft`, `visudo`, `runuser` et `sudo` 1.9.10 au moins.

| Élément | Version minimale | Rôle | Source | Statut |
| --- | --- | --- | --- | --- |
| OpenSSH (`sshd`) | — | tunnel : compte `tunnel`, redirection de sockets Unix | cahier des charges, § Réseau, lighttpd et tunnel SSH (essai sur OpenSSH 9.6 ; Debian 13 fournit la 10.0 d'après le même texte) | requis |
| nftables (`/usr/sbin/nft`) | — | table `inet paresia_relais` : règle `meta skuid "tunnel" ct state new reject` ; unité `paresia-nftables.service` (`CAP_NET_ADMIN`) ; `nft -c -f` exige root, vérifié sur la cible | cahier des charges, même section ; `deploy/backend-relais/etc/nftables/paresia-relais.nft` ; script (`/usr/sbin/nft`) | requis |
| `sudo` | **1.9.10** | commandes `docker` de Remus (compte `chef`) : expressions régulières d'arguments `^…$` du fichier sudoers généré (`sudoers(5)`, « Regular expressions » : « Starting with version 1.9.10, it is possible to use regular expressions » ; `NEWS` 1.9.10 : prise en charge des expressions régulières POSIX étendues). Debian 13 fournit 1.9.16p2 | `server/remus/sudoers.py` ; script (contrôle `sudo-1.9.10`) | requis |
| `visudo` (paquet `sudo`) | — | contrôle du fichier généré avant installation (`visudo -c -f`) | script (`/usr/sbin/visudo`) | requis |
| systemd | à vérifier | unités `paresia-nftables.service`, `castor.service` et `remus.service` ; pages locales comparées à systemd 257.13 | script (`lire_systemd`) ; `systemd-analyze verify` | requis ; version minimale non établie |
| `runuser`, `ss` | — | contrôles du script | script | requis |
| `useradd`, `getent`, `awk` | — | comptes `paresia-castor`, `chef`, `tunnel` (identifiants choisis par le système dans la plage de `login.defs(5)` et reportés dans la configuration par le script d'installation, sans répertoire sous `/home`) et contrôles de la procédure | procédure `installation-relais.md`, étapes 1 à 3 | requis pour la procédure |
| Docker | — | conteneur strfry | cahier des charges, § Remus et Castor | requis |
| `rrsync` (côté relais) | non indiquée | copie du journal légal en lecture seule | commentaire de `deploy/backend-admin/usr/local/sbin/journal-legal-pull.sh` | requis par le journal légal |

Castor et Remus n'utilisent que la bibliothèque standard de Python (en-têtes de `server/castor/` et de `server/remus/`). Sauvegardes de procédure sous `/var/backups/paresia/relais/` (dossiers 0700).

## 4. Poste client (Paresia-admin)

| Élément | Version minimale | Rôle | Source |
| --- | --- | --- | --- |
| `python3-pyqt6`, `python3-pyqt6.qtsvg` | — | application de bureau | cahier des charges, § Application de bureau, dépendances |
| QtWebEngine pour PyQt6 | — | vue web intégrée | même ligne ; `admin/app/fenetre.py` |
| `rbw` | — | lecture de la passphrase dans le coffre | même ligne |
| `openssh-client` | — | `ssh -T app@backend-admin` ; `ssh-keygen -Y sign` pour le défi | `admin/app/presence.py`, `admin/app/signature.py` |
| Python 3 et `server/commun/` | 3.11 | l'application importe la configuration, le filtrage et le NDJSON de `server.commun` ; le poste client reçoit ces modules par l'installation avancée (clonage du dépôt) | `admin/app/` |
| Agent SSH, quelle que soit l'application qui le sert | — | signature de la clé de l'administrateur (`SSH_AUTH_SOCK` exigé) | RFC 9987 et `PROTOCOL.sshsig` |

## 5. Images Docker

| Image | Statut |
| --- | --- |
| strfry (relais) | `z0brak/paresia-yin-strfry:4cd3cf6` (image publique du projet, D175) ; Dockerfile et modifications exactes **à compléter** |

Faits établis : Paresia requiert une image strfry modifiée, non l'image d'origine. La variante avec `jq` n'était requise que par l'ancien plugin d'écriture en shell du journal légal (`journal-legal.sh`, `jq` ≥ 1.6 d'après son en-tête), qui s'exécutait dans le conteneur ; le plugin livré aujourd'hui est en Python et le code du dépôt n'emploie plus `jq` (vérifié par recherche dans `server/` et `deploy/backend-relais/`). Ni le Dockerfile, ni les commandes de construction, ni les paquets ajoutés (hors `jq`), ni le nom d'un registre ne sont établis : **les modifications exactes sont à compléter**, sans rien déduire. Exigence : `python3` (paquet Alpine) DOIT figurer dans l'image, car le plugin `writePolicy` du journal légal livré (`server/strfry/journal_legal.py`, chemin `/app/plugins/journal_legal.py` dans `deploy/backend-relais/strfry/strfry.conf`) est un module Python de la bibliothèque standard, sans `jq` ni sous-processus. Relevé à l'essai réel sur `backend-relais` : l'image `z0brak/paresia-yin-strfry:4cd3cf6` contient `python3` (`Python 3.14.10`). La version n'est pas exigée : le plugin reste exécutable par Python 3.9 et plus. Le `strfry.conf` livré écrit `bind = "0.0.0.0"` (adresse dans le conteneur) : le port ne DOIT être publié que vers le proxy. L'image est publiée (`docker pull z0brak/paresia-yin-strfry:4cd3cf6`) ; l'image d'origine ne doit pas être supposée suffisante. L'image strfry est sous GPL-3.0 : obligation de fournir les sources si elle est distribuée (`docs/licences-tierces.md`).

## 6. Développement et CI (hors prérequis d'exploitation)

| Élément | Source |
| --- | --- |
| git, Python 3.11 au moins (3.13 en CI), `pytest` | `.github/workflows/ci.yml` |
| Conteneur `debian:trixie` (Debian 13) sous un compte non root ; paquets `acl`, `ca-certificates`, `curl`, `git`, `groff-base`, `iproute2`, `man-db`, `nftables`, `nodejs`, `openssh-client`, `openssh-server`, `python3`, `python3-cryptography`, `python3-pip`, `python3-pyqt6`, `python3-pyqt6.qtwebengine`, `python3-venv`, `shellcheck`, `sudo`, `systemd` : outils dont les tests dépendent, contrôlés par la CI | `.github/workflows/ci.yml` ; `docs/developpement.md` |
| Tests de l'application : PyQt6 est importé par `importorskip` en local (absent : tests sautés) ; tests JavaScript lancés par `node` | `.github/workflows/ci.yml` |

`pyright` n'est pas un prérequis du projet : aucun fichier du dépôt ne l'exige ni ne le lance, et l'intégration continue ne l'emploie pas. Un outil d'analyse statique de l'éditeur reste un choix personnel du développeur, hors dépendances.
