# Glossaire

Version du document : 0.1.19 · 2026-11-08 · [Accueil](Accueil.md)

| Terme | Définition |
| --- | --- |
| **ACL** | liste de contrôle d'accès POSIX : droits fins sur un fichier ou une socket, en plus du propriétaire, du groupe et des autres (`setfacl`, `getfacl`) |
| **agent SSH** | programme qui garde vos clés SSH et signe pour les applications, sans leur donner la clé |
| **backend-admin** | machine yang : Romulus, Pollux, Nisaba, bunkerd |
| **backend-relais** | machine yin : Remus, Castor, strfry |
| **battement (heartbeat)** | ping envoyé toutes les 30 s par l'application pour prouver que la session vit |
| **bunker (NIP-46)** | service qui signe des événements Nostr à distance, sans exposer la clé |
| **bunkerd** | le bunker de Paresia (greffon yang) |
| **Castor** | démon yin : tient un feu par session de présence |
| **chef** | compte de `backend-relais` sous lequel Remus lance ses commandes `docker` via `sudo` |
| **cloisonnement** | séparation en machines, comptes et sockets distincts pour limiter la portée d'une panne ou d'une intrusion |
| **défi (challenge)** | suite aléatoire que le serveur demande de signer pour prouver la possession de la clé |
| **démon** | programme qui tourne en arrière-plan, ici sous systemd |
| **feu (de Castor)** | vert, rouge ou fermé : autorise ou non Remus pour une session |
| **feu de circulation** | autre nom du feu de Castor : vert, les commandes passent ; rouge ou fermé, elles sont refusées |
| **fonction** | côté yin, une brique d'un greffon : un script et son manifeste, que Remus charge et appelle ; elle ne s'exécute qu'à la demande |
| **greffon** | module enfiché sur le noyau : strfry (yin), Nisaba et bunker (yang) sont les premiers. Il ne livre pas le produit qu'il administre : il déclare avec quelles versions il fonctionne |
| **HAProxy** | proxy et répartiteur de charge, installé par l'administrateur, devant le serveur d'administration ([Serveur web](../serveur-web.md)) |
| **lighttpd** | serveur web léger qui sert les pages de l'interface web ; installé par l'administrateur ([Serveur web](../serveur-web.md)) |
| **identité (bunker)** | clé Nostr chiffrée (`ncryptsec`) avec ses relais et clients autorisés |
| **jeton** | valeur aléatoire émise à l'ouverture d'une session de présence, portée par chaque commande |
| **journal légal** | journal des événements publiés sur le relais, conservé de façon probante |
| **jumeaux** | les couples Romulus/Remus (commandes) et Pollux/Castor (présence) ; protocole `jumeaux/1` |
| **`jumeaux/1`** | protocole entre démons : lignes JSON (NDJSON), actions nommées par domaine |
| **MANIFEST** | registre des journées du journal légal, avec leurs empreintes |
| **N:M** | plusieurs machines yin (N) pour plusieurs machines yang (M) ; prévu après la 1.0 |
| **`ncryptsec`** | clé privée Nostr chiffrée par phrase secrète (NIP-49) ; la forme à conserver et à transporter ; voir [Comprendre les formats de clés](Installer-nak.md) |
| **`npub`** | clé publique Nostr en bech32 (NIP-19) ; se partage librement ; voir [Comprendre les formats de clés](Installer-nak.md) |
| **`nsec`** | clé privée Nostr en clair, en bech32 (NIP-19) ; à ne jamais diffuser ; voir [Comprendre les formats de clés](Installer-nak.md) |
| **hex (clé)** | clé de 32 octets écrite en 64 caractères hexadécimaux, forme du protocole et de `strfry.conf` ; ne distingue pas publique et privée ; voir [Comprendre les formats de clés](Installer-nak.md) |
| **NDJSON** | JSON délimité par des sauts de ligne : un message par ligne |
| **nftables** | pare-feu du noyau Linux ; Paresia l'emploie pour interdire au compte `tunnel` d'ouvrir des connexions TCP |
| **NIP** | proposition de spécification Nostr (NIP-01, NIP-42, NIP-46, NIP-49…) |
| **Nisaba** | greffon yang : conservation probante du journal légal |
| **Nostr** | protocole ouvert de messagerie par relais et clés cryptographiques |
| **OpenTimestamps (`ots`)** | horodatage à date certaine ancré dans une chaîne publique |
| **Pollux** | démon yang : constate la présence et relaie jetons et pings |
| **`pollux-session`** | commande forcée du compte `app` : relaie la session SSH vers Pollux |
| **présence** | état « l'administrateur est là » prouvé par une session SSH vivante |
| **relais** | serveur Nostr qui stocke et diffuse des événements (ici strfry) |
| **Remus** | démon yin : charge les fonctions des greffons et les exécute quand le feu est vert ; il ne connaît lui-même aucune opération |
| **robinet** | l'ouverture des commandes d'administration : fermé sauf pendant une session |
| **Romulus** | démon yang : reçoit les commandes, vérifie les jetons, aiguille |
| **`SO_PEERCRED`** | mécanisme du noyau qui atteste l'identité de l'autre bout d'une socket Unix |
| **socket Unix** | prise locale à un fichier, protégée par les droits du système de fichiers |
| **SSHSIG** | format de signature de SSH ; sert à signer le défi de présence |
| **strfry** | logiciel de relais Nostr administré par Paresia |
| **sudoers** | règles de `sudo` ; celles de Remus sont générées |
| **tunnel (SSH)** | liaison SSH permanente entre `backend-admin` et `backend-relais` portant les deux couples de jumeaux |
| **unité systemd** | description d'un service pour systemd |
| **yin / yang** | les deux côtés : yin = relais (Remus, Castor), yang = administration (Romulus, Pollux) |
