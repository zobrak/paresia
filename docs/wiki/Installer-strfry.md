# Installer le relais strfry

Version du document : 0.1.19 · 2026-11-08.

Cette page prépare `backend-relais` **avant** [`INSTALL.md`](../../INSTALL.md) : elle met en place le conteneur Docker `strfry` que l'installateur du relais cherche, sans le créer lui-même. Alpha : à essayer sur une machine jetable. Les noms (`backend-relais`, `relay.example.org`, `192.0.2.20`) sont des exemples génériques (RFC 2606, RFC 5737).

Ce qui n'est pas établi par une source du dépôt est marqué **à compléter** ; rien n'y est deviné.

## Ce que l'installateur attend

- un conteneur Docker nommé **exactement** `strfry` ;
- lancé depuis l'image **exacte** `z0brak/paresia-yin-strfry:4cd3cf6` : l'installateur compare l'étiquette `4cd3cf6` à la version déclarée par le greffon strfry et s'arrête sinon, avant toute modification (code 78) ;
- il ne crée, ne démarre ni ne modifie ce conteneur (`INSTALL.md`, § 1).

## 1. Docker Engine

Conseil, non une obligation : sur Debian 13, le dépôt `docker-ce` s'active par `extrepo`. En root, ou avec `sudo` :

    apt install extrepo
    extrepo enable docker-ce
    apt update
    apt install docker-ce docker-ce-cli containerd.io docker-compose-plugin

`docker-compose-plugin` fournit la commande `docker compose` (paquet du dépôt Docker, d'après sa documentation d'installation sur Debian). Sans lui, la commande `docker run` équivalente au `compose.yml` reste **à compléter**.

## 2. L'image

    docker pull z0brak/paresia-yin-strfry:4cd3cf6

Ne changez pas l'étiquette : `4cd3cf6` est l'identifiant court du commit de strfry sur lequel l'image est construite, et c'est lui que l'installateur compare. Elle n'est pas l'image d'origine de strfry : le projet l'a modifiée (Alpine 3.24, OpenSSL au lieu de LibreSSL). Le plugin du journal légal exige `python3` dans l'image (`docs/prerequis.md`, § 5) ; que l'image publiée l'embarque est **à compléter** (non vérifié ici).

## 3. Le fichier `compose.yml`

Dossier de travail au choix ; l'exemple utilise `/srv/strfry`. Dans l'image, les chemins établis par les sources sont : programme `/app/strfry`, base `/app/strfry-db`, configuration cherchée dans cet ordre : option `--config`, variable `STRFRY_CONFIG`, `/etc/strfry.conf`, `./strfry.conf` (`/app/strfry.conf`).

    # /srv/strfry/compose.yml
    services:
      strfry:
        # Le nom du conteneur DOIT être "strfry" (sudoers de Remus, installateur).
        container_name: strfry
        # Image exacte ; ne pas changer l'étiquette.
        image: z0brak/paresia-yin-strfry:4cd3cf6
        # Utilisateur sans privilège (uid et gid de l'utilisateur du conteneur
        # de production) ; la base et le journal doivent lui appartenir.
        user: "10001:10001"
        restart: unless-stopped
        # Port : strfry n'est joignable que par le proxy inverse, car l'en-tête
        # d'adresse du client est cru sur parole. Remplacez 192.0.2.20 par
        # l'adresse de backend-relais joignable par le proxy ; jamais 0.0.0.0.
        ports:
          - "192.0.2.20:7777:7777"
        volumes:
          # Configuration (lecture seule), lue à /etc/strfry.conf.
          - ./strfry.conf:/etc/strfry.conf:ro
          # Base LMDB.
          - ./data:/app/strfry-db
          # Plugin du journal légal (lecture seule) et son dossier d'écriture.
          - ./plugins:/app/plugins:ro
          - ./journal:/app/journal
        # Durcissement relevé sur le relais de production du projet.
        read_only: true
        tmpfs:
          - /tmp
        cap_drop:
          - ALL
        security_opt:
          - no-new-privileges:true
        stop_grace_period: 2m
        # Journaux dans journald, étiquette "strfry" (journalctl -t strfry).
        logging:
          driver: journald
          options:
            tag: strfry
        healthcheck:
          test: ["CMD", "wget", "-q", "-O", "/dev/null", "http://127.0.0.1:7777/"]
          interval: 60s

Préparez les dossiers et les droits :

    mkdir -p /srv/strfry/data /srv/strfry/plugins /srv/strfry/journal
    chown 10001:10001 /srv/strfry/data /srv/strfry/journal
    cp server/strfry/journal_legal.py /srv/strfry/plugins/

Points **à compléter** :

- Limites de ressources de la production (`pids_limit`, `mem_limit`, `cpus`) : non reprises ici, leurs valeurs ne sont pas des exigences de Paresia.
- `nofiles = 524288` du `strfry.conf` livré : le conteneur doit l'autoriser (D95). Si strfry s'en plaint au démarrage, ajoutez `ulimits.nofile` ; la valeur requise n'est pas établie.
- Le fichier `blocklist.txt` du plugin (`/app/plugins/blocklist.txt` par défaut) : forme et contenu à établir dans la fiche du greffon.
- Le même `compose.yml` essayé tel quel sur une machine : **non essayé**.

## 4. Le fichier `strfry.conf`

Partez du fichier livré : `deploy/backend-relais/strfry/strfry.conf`.

    cp deploy/backend-relais/strfry/strfry.conf /srv/strfry/strfry.conf

À adapter :

| Clé | Pourquoi |
| --- | --- |
| `relay.auth.serviceUrl` | URL publique exacte du relais en `wss://` ; la valeur livrée est un exemple (`wss://relay.example.org`), sinon l'authentification NIP-42 échoue pour tous |
| `relay.info.*` (`name`, `description`, `pubkey`, `self`, `contact`, `icon`, `banner`, `privacy`, `terms`) | annonce NIP-11 ; les champs vides sont des valeurs d'installation |

À **ne pas** changer sans raison (D95, D110) : `db = "/app/strfry-db/"` (doit coïncider avec le montage), `relay.port = 7777`, `relay.bind = "0.0.0.0"` (adresse **dans** le conteneur ; l'exposition se règle dans `ports`), `relay.realIpHeader = "x-forwarded-for"` (le proxy doit écraser cet en-tête), `relay.writePolicy.plugin = "/app/plugins/journal_legal.py"` (doit coïncider avec le montage), `restrictedReadKinds = "4"` et `filterValidation.enabled = false` (compatibilité bitchat). Ne créez **jamais** d'arbre negentropy (`strfry negentropy add`, `build`) : le fichier livré l'interdit.

## 5. La clé du relais avec `nak`

`nak` est un binaire qui n'est pas fourni par Debian ; son origine, sa version et sa licence ne sont **pas établies** dans le dépôt (`docs/prerequis.md`, § 2 ; `docs/licences-tierces.md`). Le chemin attendu par la configuration d'exemple est `/usr/local/bin/nak`, sur `backend-admin` (bunkerd). Installation : **à compléter** (méthode, version, vérification d'intégrité).

Sous-commandes vérifiées sur un poste avec `nak` v0.22.0 : `nak key generate` génère une clé secrète, `nak key public` calcule la clé publique, `nak key encrypt` chiffre une clé en `ncryptsec`. Le reste de l'interface (options, version minimale requise) n'est pas établi par le dépôt.

Génération sans que la clé en clair soit affichée ni gardée : passez `generate` directement à `encrypt` par un tube, et ne conservez que le `ncryptsec` :

    nak key generate | nak key encrypt

La syntaxe exacte du tube est **à vérifier** par `nak key encrypt --help` (lecture de la clé sur l'entrée standard, manière de fournir la phrase de passe) : elle n'a pas pu être contrôlée ici. Ne mettez pas la phrase de passe sur la ligne de commande, où elle resterait dans l'historique du shell. Pour obtenir la clé publique sans écrire la clé secrète, la syntaxe de `nak key public` avec un `ncryptsec` est aussi **à vérifier**.

Où garder la clé :

- la clé privée du relais est une **identité du bunker**, désignée par `[bunkerd] relay_identity` ; bunkerd n'en garde que la forme chiffrée (`ncryptsec`) ;
- ne collez jamais la clé privée (`nsec`) dans un fichier, un terminal partagé, une conversation ou ce dépôt ;
- seule la clé **publique** (`npub`) se publie, par exemple dans `relay.info.self` de `strfry.conf`.

## 6. Démarrer et contrôler

    cd /srv/strfry
    docker compose up -d

(ou la commande `docker run` équivalente, **à compléter**). Contrôles :

    docker ps --filter name=^strfry$
    docker exec strfry wget -qO- http://127.0.0.1:7777/metrics
    ss -ltn 'sport = :7777'
    curl -s -H 'Accept: application/nostr+json' http://192.0.2.20:7777/

Résultats attendus :

- `docker ps` montre le conteneur `strfry` (l'état de santé passe à `healthy` après la première minute) ;
- la deuxième commande affiche des métriques au format texte Prometheus (même port que le relais) ;
- `ss` montre une écoute sur `192.0.2.20:7777`, et non sur `0.0.0.0:7777` ;
- `curl` renvoie le document NIP-11 : un objet JSON dont `name` vaut `Paresia` si vous n'avez pas changé `relay.info.name`.

En cas d'échec : `journalctl -t strfry`. Ensuite, passez à [`INSTALL.md`](../../INSTALL.md), § 5 (passe 2 : `backend-relais`).
