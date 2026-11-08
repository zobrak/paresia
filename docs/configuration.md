# Configuration de Paresia-server

Version du document : 0.1.19 · 2026-11-08 · public : administrateur, développeur
Rôle : décrit la configuration en couches (sections par composant, fichier explicite, exemple
unique). Complète `docs/protocole.md` § 9 et `docs/conventions.md`. L'exemple complet est
`server/conf/paresia.conf`. Module : `server/commun/config.py` (bibliothèque standard).

## Couches et ordre de priorité

Priorité croissante : la dernière couche qui définit une option l'emporte.

| Couche | Emplacement | Qui la lit |
| --- | --- | --- |
| 1 | `/etc/paresia/paresia.conf` | tous |
| 2 | `/etc/paresia/conf.d/NN-*.conf` (nom `^[0-9]{2}-[A-Za-z0-9._-]+\.conf$`, ordre lexical ; les autres noms sont ignorés) | tous |
| 3 | `$XDG_CONFIG_HOME/paresia/*.conf` (ordre lexical ; `XDG_CONFIG_HOME` s'il est défini et absolu, sinon `~/.config/paresia/`) | **programmes lancés par un utilisateur seulement** (poste client, outils en ligne de commande) |
| 4 | variables d'environnement `PARESIA_*` | tous, sauf `pollux-session` |

- Aucune couche n'est obligatoire : une configuration par variables seules (conteneurs) est
  valable si toutes les options obligatoires sont fournies, sinon `config_missing`.
- Chaque valeur rencontrée est contrôlée (type, bornes), même si une couche supérieure la
  masque : une faute n'est pas cachée.
- Les chemins, comptes et uid n'ont aucun défaut dans le code ; seules les durées et les limites
  en ont un.
- Exemple de surcharge locale `/etc/paresia/conf.d/50-site.conf` :

```ini
[romulus.http]
max_body = 131072
```

## Format et sections

Format INI, sans interpolation. Une section par composant et par domaine : `[<composant>.<domaine>]`.
La section nue `[<composant>]` correspond au domaine réservé `general`. Chaque composant ne lit
que ses sections ; celles des autres composants sont ignorées. `[DEFAULT]` est interdit.

| Composant | Sections | Préfixe des variables |
| --- | --- | --- |
| `pollux` | `pollux.sessions`, `pollux.signature`, `pollux.relay`, `pollux.romulus`, `pollux.castor`, `pollux.transport` | `PARESIA_POLLUX_<DOMAINE>_<CLE>` (ex. `PARESIA_POLLUX_SESSIONS_TIMEOUT_S`) |
| `pollux-session` | `pollux-session.transport`, `pollux-session.auth` | aucun : environnement ignoré |
| `romulus` | `romulus.presence`, `romulus.http`, `romulus.plugins`, puis une section par service déclaré (livrés : `romulus.bunker`, `romulus.relay`, `romulus.nisaba`) | `PARESIA_ROMULUS_<DOMAINE>_<CLE>` |
| `nisaba` | `nisaba.socket`, `nisaba.ctl`, `nisaba.journal`, `nisaba.horaire`, `nisaba.etat`, `nisaba.source`, `nisaba.ots`, `nisaba.droits` | `PARESIA_NISABA_<DOMAINE>_<CLE>` |
| `bunkerd` | `bunkerd` (général), `bunkerd.etat`, `bunkerd.outils`, `bunkerd.controle`, `bunkerd.web`, `bunkerd.admin`, `bunkerd.signature` | `PARESIA_BUNKERD_<DOMAINE>_<CLE>` (ex. `PARESIA_BUNKERD_ADMIN_SOCKET`) |
| `sauvegarde` | `sauvegarde.stockage` | `PARESIA_SAUVEGARDE_STOCKAGE_<CLE>` |
| `admin` (poste client) | `admin.connexion`, `admin.cle`, `admin.presence`, `admin.interface` | `PARESIA_ADMIN_<DOMAINE>_<CLE>` ; `--config` ou `PARESIA_ADMIN_CONFIG` remplace les couches fichier |
| `castor` | `castor.tunnel`, `castor.state`, `castor.lights`, `castor.transport`, `castor.journal`, `castor.metriques` | `PARESIA_CASTOR_<DOMAINE>_<CLE>` |
| `remus` | `remus.server`, `remus.castor`, `remus.light`, `remus.transport`, `remus.executor`, `remus.plugins`, `remus.journal`, `remus.metriques` | `PARESIA_REMUS_<DOMAINE>_<CLE>` |

Les options de Castor et de Remus, leurs défauts et leurs commentaires sont dans `server/conf/paresia-relais.conf` et dans `paresia-castor(8)` et `paresia-remus(8)`.

### Export binaire de Romulus (`romulus.http`)

Options de type `limite` (1 à 16777216), toutes deux facultatives ; défauts et commentaires dans `server/conf/paresia.conf`. Livraison de l'archive : `docs/protocole.md`, § 6.1.

| Option | Défaut | Rôle | Variable |
| --- | --- | --- | --- |
| `export_max_octets` | 8388608 (8 Mio) | taille maximale de l'archive gzip ; au-delà, l'export est refusé (`export_too_large`, 422) | `PARESIA_ROMULUS_HTTP_EXPORT_MAX_OCTETS` |
| `export_max_simultanes` | 2 | exports (action, préparation et envoi) en cours en même temps ; excédent refusé sans attente (`export_busy`, 503) | `PARESIA_ROMULUS_HTTP_EXPORT_MAX_SIMULTANES` |

### Transport de Pollux (`pollux.transport`)

Options de type `duree` ou `limite`, toutes facultatives ; défauts et commentaires dans `server/conf/paresia.conf`.

| Option | Défaut | Rôle | Variable |
| --- | --- | --- | --- |
| `delai_s` | 120 | échéance totale d'une requête entrante (lecture, traitement, réponse) ; à prévoir plus grande que `timeout_s` et que la durée des notifications aux pairs | `PARESIA_POLLUX_TRANSPORT_DELAI_S` |
| `pair_delai_s` | 5 | échéance de chaque appel sortant vers Romulus ou Castor ; aucun nouvel essai de fermeture Castor ; borne aussi l'attente des notifications en cours à l'arrêt | `PARESIA_POLLUX_TRANSPORT_PAIR_DELAI_S` |
| `max_line` | 1048576 | longueur NDJSON en octets, LF compris (1 à 16777216) | `PARESIA_POLLUX_TRANSPORT_MAX_LINE` |
| `max_connexions` | 64 | plafond de connexions sur chaque écoute (1 à 1024) | `PARESIA_POLLUX_TRANSPORT_MAX_CONNEXIONS` |

- Les appels vers Romulus et Castor ne se font plus sous le verrou global de Pollux : un Castor lent ne retarde ni les autres sessions, ni les pings, ni les expirations. Le client Romulus reste unique : un Romulus lent retarde les autres ouvertures et fermetures vers Romulus, jamais les pings, les échanges avec Castor ni les expirations.
- Garder `pair_delai_s` court devant `timeout_s` (quelques secondes). Pire cas prudent, pour la perte de Romulus et l'arrêt : `maximum` × `pair_delai_s` < `timeout_s` (16 × 5 s = 80 s pour 90 s). Aucun contrôle au démarrage ne l'impose : c'est une règle de réglage. `TimeoutStopSec=180` de l'unité reste inchangé.
- L'écoute du frontal HTTP de Romulus a une file d'attente (`listen`) au moins égale à `max_connexions` : une rafale de connexions n'est plus perdue.

### Aiguillage de Romulus (`romulus.bunker`, `romulus.relay`)

Valeurs d'illustration dans `server/conf/paresia.conf` (chemins, uid) : à adapter à l'installation. Les uid sont contrôlés par `SO_PEERCRED` avant l'envoi. Pour l'uid du compte de bunkerd, la procédure d'installation indique comment le relever. Types : `chemin`, `uid`, `duree` (> 0 et au plus 3600 s), `limite` (1 à 16777216).

| Section | Option | Défaut | Rôle |
| --- | --- | --- | --- |
| `[romulus.bunker]` | `bunkerd_socket`, `bunkerd_uid` | obligatoires | socket d'administration de bunkerd (`[bunkerd.admin] socket`) et uid du compte de bunkerd |
| | `delai_s` | 120 | échéance d'un appel, supérieure à `[bunkerd.admin] delai_s` |
| | `max_line` | 65536 | longueur maximale d'une ligne, LF compris |
| `[romulus.relay]` | `remus_socket`, `remus_uid` | obligatoires | socket locale du tunnel vers Remus et uid du processus qui l'écoute |
| | `pollux_socket`, `pollux_uid` | obligatoires | socket `pollux-relay.sock` pour le ping de session et uid de Pollux |
| | `delai_s` | 600 | attente du résultat de Remus, au moins `[remus.transport] delai_s` |
| | `ping_delai_s` | 5 | échéance de l'appel de ping à Pollux, strictement inférieure à `heartbeat_s` |
| | `heartbeat_s` | 30 | un ping par session au plus toutes les `heartbeat_s` ; même valeur que `[pollux.sessions] heartbeat_s` |
| | `flux_max_simultanes` | 8 | flux HTTP de suivi en direct ouverts en même temps (1 à 1024) ; excédent refusé avant tout octet de flux par 503 `command_busy` ; plafond global, non par session (plafond par session : après la 1.0) |
| | `max_line` | 1048576 | longueur maximale d'une ligne |

Variables : `PARESIA_ROMULUS_BUNKER_<CLE>` et `PARESIA_ROMULUS_RELAY_<CLE>` (ex. `PARESIA_ROMULUS_RELAY_FLUX_MAX_SIMULTANES`). Format du flux : `docs/protocole.md`, § 6.

**Ces sections viennent des déclarations de services.** Romulus ne les connaît pas en dur : chaque section de service, ses options, leurs types, défauts et bornes sont décrits par une déclaration `paresia-yang-<nom>.toml` (format : `docs/developpement.md`, § 6.3). Les tableaux ci-dessus décrivent les quatre déclarations livrées ; sans la déclaration correspondante, la section est refusée (78, `config_unknown_section`). Une déclaration locale peut ajouter un service (nouvelle section), jamais en remplacer un.

| Section | Option | Type, défaut | Rôle | Variable |
| --- | --- | --- | --- | --- |
| `[romulus.plugins]` | `livrees` | chemin, `/usr/local/lib/paresia/romulus/services` | dossier des déclarations livrées | `PARESIA_ROMULUS_PLUGINS_LIVREES` |
| | `locales` | chemin, `/etc/paresia/romulus/services.d` | dossier des déclarations locales | `PARESIA_ROMULUS_PLUGINS_LOCALES` |
| `[romulus.nisaba]` (facultative) | `socket`, `uid` | chemin, uid | socket réservée à Romulus du processus du journal légal (`[nisaba.socket] socket`) et uid de son compte ; sans la section, `nisaba/*` répond 501 `not_available` | `PARESIA_ROMULUS_NISABA_<CLE>` |
| | `delai_s` | durée, 120 | échéance d'un appel | |
| | `max_line` | limite, 1048576 | longueur maximale d'une ligne | |

Les deux dossiers (et leurs ancêtres) et les fichiers appartiennent à root, sans écriture pour le groupe ni les autres, sans lien symbolique. Une déclaration livrée défectueuse refuse le démarrage (78) ; une déclaration locale défectueuse est ignorée et journalisée (`service_declaration_rejected`).

**Règle socket et uid.** Avec le socket d'un service, l'uid de son compte est exigé, et l'inverse (de même `pollux_socket` et `pollux_uid` pour le ping de session) ; un seul des deux fait refuser la configuration (78, `config_invalid`, option de l'uid). Romulus ne construit jamais de connexion sans uid du pair, qui est vérifié par `SO_PEERCRED` avant l'envoi. Un service facultatif sans socket ni uid n'est pas aiguillé. Les contrôles croisés déclarés (`maximum`, `inferieure_a`, ex. `flux_max_simultanes` au plus 1024 et `ping_delai_s` inférieur à `heartbeat_s`) sont appliqués à la configuration lue.

**Deux extensions de `server/commun/config.py`** :

- *Lecture partielle* : `lire(..., partielle=True)` ignore les sections et options du composant absentes du schéma (sans `config_unknown_section` ni `config_unknown_option`) ; celles du schéma sont validées comme d'habitude. Romulus s'en sert une seule fois, pour lire `[romulus.plugins]` avant de connaître les déclarations ; la configuration finale est relue en lecture stricte. Par défaut, la lecture reste stricte pour tous les autres appelants.
- *`uid` facultatif* : `Option('uid', facultatif=True)` (sans défaut) accepte l'absence, représentée par `None`, comme `chemin`, `texte` et `compte`.

### Nisaba (`nisaba.*`)

Processus annexe du journal légal de backend-admin (`python3 -P -s -B -m server.nisaba`). Seules `duree` et `limite` ont un défaut dans le code ; toute autre option est obligatoire (absente : `config_missing`, démarrage refusé). Valeurs d'illustration et commentaires : `server/conf/paresia.conf`. Les horaires sont en UTC, au format strict `HH:MM`. Protocole et CLI : `docs/protocole.md`, § 5.2.

| Section | Options (défaut) | Rôle |
| --- | --- | --- |
| `[nisaba.socket]` | `socket`, `uid_romulus`, `gid` ; `delai_s` (30), `max_line` (65536) | socket `jumeaux/1` de Romulus ; seul l'uid de Romulus est admis ; le gid est un entier |
| `[nisaba.ctl]` | `socket`, `uid` | socket de contrôle de la CLI, mode 0600, seul l'uid indiqué est admis |
| `[nisaba.journal]` | `dossier`, `compte_acl`, `lsattr`, `chattr` | copie du journal légal ; compte de Romulus, lecteur par ACL (droit hérité : la consultation du journal est confiée à Nisaba et Romulus ne s'en sert pas aujourd'hui) ; outils lancés par argv, sans interpréteur de commandes |
| `[nisaba.horaire]` | `scellement`, `purge` ; `copie_s` (60), `conservation_jours` (365, de 1 à 36500), `arret_s` (30) | planification interne ; une journée D est supprimée à D + 366 jours |
| `[nisaba.etat]` | `dossier` ; `historique` (20, plafonné à 40) | dossier d'état (même chemin que le `StateDirectory=` de l'unité) ; échecs conservés par tâche |
| `[nisaba.source]` | `source`, `cle_ssh`, `rsync`, `ssh` ; `connexion_s` (20), `rsync_s` (50) | copie depuis backend-relais (`utilisateur@hôte:/`, rsync par ssh, clé dédiée jamais lue ni copiée par Nisaba) |
| `[nisaba.ots]` | `ots` ; `attente_max_jours` (3), `delai_s` (120) | client OpenTimestamps ; seule l'empreinte de la ligne du registre part sur Internet ; preuve incomplète après `attente_max_jours` : `ECHEC_HORODATAGE` |
| `[nisaba.droits]` | `chattr`, `setfacl`, `getfacl`, `compte` | modes, ACL et attributs ; `compte` DOIT être le même que `[nisaba.journal] compte_acl` : une divergence est refusée au démarrage par `config_invalid` (domaine `droits`, clé `compte`) |

Planification : à chaque démarrage et à chaque échéance, le scellement part de la journée suivant la dernière inscrite jusqu'à la veille (rattrapage). L'unité systemd et la procédure de migration depuis les anciens scripts ne sont pas encore livrées ; l'immuabilité (`chattr`) exige `CAP_LINUX_IMMUTABLE`, donnée par l'unité et non par le code. Les anciennes minuteries doivent être arrêtées avant le démarrage de Nisaba.

### Plugin du journal légal de strfry (`server/strfry/journal_legal.py`)

Module Python de la bibliothèque standard, exécuté dans le conteneur strfry (`python3` dans l'image), sans `jq` ni sous-processus. Variables d'environnement facultatives : `JOURNAL_DIR` (défaut `/app/journal`), `BLOCKLIST_FILE` (défaut `/app/plugins/blocklist.txt`), `UNJOURNALED_KINDS` (défaut `20001 22242 23194 23195 24133 24242 27235`, séparés par des espaces). `relay.writePolicy.plugin` et `timeoutSeconds` (10) sont fixés par `deploy/backend-relais/strfry/strfry.conf`.

- Chemin rapide : un kind non journalisé n'écrit aucune ligne de journal. Le kind 20000 reste journalisé.
- Les caractères C1, DEL, U+2028 et U+2029 sont échappés en `\uXXXX` dans la ligne du journal ; ce format est partagé avec Nisaba.
- Échec d'écriture du journal : la publication est acceptée et la ligne complète est écrite sur la sortie d'erreur, donc dans journald (comportement du plugin 1.3.0).
- Liste noire (`BLOCKLIST_FILE`) : sans liste encore lue, un fichier absent donne une liste vide sans alerte ; toute autre erreur de lecture donne une liste vide et le relais accepte les écritures, avec une alerte `ECHEC_LISTE_NOIRE` sur la sortie d'erreur. Après une lecture réussie, un fichier disparu ou illisible laisse la dernière liste valide en place. Une seule alerte par épisode d'erreur, réarmée par la première lecture réussie. Les lignes invalides sont ignorées ; l'alerte donne leur nombre et au plus 10 numéros de ligne, jamais leur contenu.
- Négentropie : `strfry.conf` documente l'interdiction de créer un arbre negentropy prédéfini (`strfry negentropy add` et `build`), pour qu'aucun kind 4 ou 1059 ne fuie par `NEG-OPEN` ; un test vérifie le commentaire et `restrictedReadKinds`.
- `sourceInfo` n'est pas validé par le plugin : la seule protection est que le proxy écrase l'en-tête d'adresse et que le port de strfry ne soit publié que vers lui ; cette exigence relève de la procédure d'installation.
- Essai de charge : `tests/test_strfry_plugin_charge.py`, ignoré par défaut (`PARESIA_ESSAI_CHARGE=1`).

### Fichier d'état de bunkerd (`bunker.json`)

- Format 1 : un objet `{"format": 1, "identities": {…}}` (aucune autre clé à la racine). Le format 0, historique, est l'objet des identités seul. Un format supérieur, inconnu ou non entier est refusé (`unsupported_format`).
- Au démarrage, avant tout service, bunkerd migre un format 0 en format 1 : copie de sûreté `bunker.json.bak-format<N>-<AAAAMMJJ>T<HHMMSS>Z` (mode 0600, relue et comparée), écriture du nouvel état, entrée de journal `state_migrated`. Seules la nouvelle copie et les deux plus récentes sont gardées. La copie reste dans le dossier d'état de `bunker.json`, seul dossier où bunkerd peut écrire : ce n'est pas une sauvegarde de procédure.
- Lecture stricte : JSON invalide, clés en double, `NaN` ou `Infinity`, racine non objet, noms d'identité hors `IDENTITY_RE` sont refusés ; bunkerd journalise `state_unreadable` (avec la cause), y compris à l'échec d'une migration (message affiché `state_migration_failed`). Retour au format 0 : restaurer une copie `bak-format0-…` (procédure à écrire).

### Socket d'administration de bunkerd (`bunkerd.admin`)

- `socket`, `romulus_user` : obligatoires. Seul le compte `romulus_user` y est admis (`SO_PEERCRED`, puis ACL posée par bunkerd). Un compte inexistant ou d'uid 0 est refusé : la socket d'administration est désactivée, `admin_disabled` (`reason` : `unknown_account` ou `invalid_account`) est journalisé et bunkerd continue.
- `max_line` : longueur maximale d'une ligne, LF compris ; 1 à 16777216 ; **65536 par défaut** (une requête d'administration tient en quelques centaines d'octets, au lieu de 1 Mio pour les autres sockets). `delai_s` : 90 par défaut (au plus 3600). `max_connexions` : 16 par défaut (1 à 1024).
- Mode de la socket, paramètre du socle (`server/commun/serveur.py`, `mode`) : le propriétaire DOIT avoir la lecture et l'écriture ; seuls 0o600, 0o620, 0o640 et 0o660 sont admis. bunkerd utilise 0o600 ; l'accès de Romulus passe par l'ACL. La socket est créée sans aucun droit (umask 0777), puis groupe et mode final sont posés : jamais plus ouverte que le mode final.

### Preuve de possession de la clé SSH (`pollux.signature`, `pollux-session.auth`)

Valeurs d'illustration et commentaires : `server/conf/paresia.conf`. Protocole : `docs/protocole.md`, § 4.1.

| Section | Option | Défaut | Rôle |
| --- | --- | --- | --- |
| `[pollux.signature]` | `authorized_keys` | obligatoire (chemin) | fichier des clés des administrateurs, relu à chaque vérification (retrait d'une ligne immédiat), ouvert sans suivre les liens ; propriétaire root, non modifiable par le compte SSH, le groupe ni les autres ; même valeur que `[pollux-session.auth] authorized_keys` |
| | `challenge_ttl_s` | 60 | durée du défi (> 0 et au plus 3600 s) ; un seul essai par connexion |
| | `namespace` | obligatoire | espace de noms SSHSIG attendu aussi par l'application (`paresia-presence` dans l'exemple) |
| | `max_signature` | 2048 | taille maximale du texte base64 de la signature, en octets (1 à 16777216 ; 2048 admet une clé RSA de 4096 bits) |
| `[pollux-session.auth]` | `authorized_keys` | obligatoire (chemin) | fichier du compte SSH, lu pour retrouver le nom de l'administrateur |
| | `max_signature` | 2048 | même plafond côté relais, DOIT être égal à celui de `[pollux.signature]` |

- Variables de Pollux : `PARESIA_POLLUX_SIGNATURE_<CLE>` ; `pollux-session` ne lit aucune variable. Aucun mode sans preuve : si `cryptography` est absente, l'ouverture répond `not_available`.
- Les lignes de `authorized_keys` de type non admis (`sk-*`, DSA, certificats) et les lignes `cert-authority` sont ignorées et journalisées au niveau info (`key_ignored`, sans la clé).
- Le chemin d'illustration est celui du compte `app` : `/var/lib/paresia-app/.ssh/authorized_keys` (le compte n'a aucun répertoire sous `/home`). L'emplacement définitif des clés autorisées dépend de la gestion des utilisateurs : il n'est pas encore fixé. Le fichier DOIT rester lisible par Pollux, dont l'unité `pollux.service` porte `ProtectHome=yes` (le fichier n'est pas sous `/home`) et `ProtectSystem=strict`, qui laisse le fichier lisible en lecture seule (test `tests/test_unites_chemins_config.py`). Un autre emplacement hors de `/home` ne demande aucune adaptation de l'unité.

### Signature de la liste de sourdine (`bunkerd.signature`)

| Option | Défaut | Rôle | Variable |
| --- | --- | --- | --- |
| `log_n` | 20 | plafond du paramètre `log_n` (scrypt, NIP-49) d'un secret chiffré, de 1 à 20 (1 Gio de mémoire, RFC 7914) ; au-dessus, le secret est refusé (`log_n_too_high`) avant tout calcul ; une valeur supérieure à 20 est refusée au démarrage (`config_invalid`) | `PARESIA_BUNKERD_SIGNATURE_LOG_N` |

- Les déchiffrements sont sérialisés (un seul à la fois) et une passphrase refusée est suivie d'une pause de 2 s : mémoire bornée à un scrypt, au plus un essai toutes les 2 s. Une erreur de format du secret chiffré est rendue `bad_passphrase`.
- La multiplication du générateur par un scalaire secret est confiée à `cryptography` (`ec.derive_private_key`), qui suit l'échelle de Montgomery à temps constant d'OpenSSL pour secp256k1 : le paquet `libssl3t64` 3.5.7-1~deb13u3 ou plus est requis (`docs/prerequis.md`). Les opérations modulaires sur entiers Python (étape de l'arithmétique, passage du secret par un entier) restent hors garantie de temps constant : résidu admis, seul Romulus peut provoquer le calcul (socket locale à accès restreint).

### Sauvegardes de procédure (`sauvegarde.stockage`)

Outil `python3 -P -m server.sauvegarde` (page `docs/man/paresia-sauvegarde.8`). Exemple dans `server/conf/paresia.conf` et `server/conf/paresia-relais.conf`.

| Option | Défaut | Rôle | Variable |
| --- | --- | --- | --- |
| `actif` | obligatoire (`oui` dans l'exemple) | `oui` ou `non` (pas de type booléen dans `config.py`) ; `non` désactive toute copie et tout relevé, la restauration des sauvegardes existantes reste possible | `PARESIA_SAUVEGARDE_STOCKAGE_ACTIF` |
| `taille_max_mio` | 64 | taille totale maximale de `<dossier>/<machine>/`, de 1 à 16777216 Mio ; les jeux les plus anciens sont supprimés au-delà, jamais le jeu en cours ni le plus récent | `PARESIA_SAUVEGARDE_STOCKAGE_TAILLE_MAX_MIO` |
| `dossier` | obligatoire | dossier de base (chemin absolu), `/var/backups/paresia` dans l'exemple | `PARESIA_SAUVEGARDE_STOCKAGE_DOSSIER` |
| `machine` | obligatoire | nom du sous-dossier (`^[a-z][a-z0-9-]{0,31}$`), `admin` ou `relais` | `PARESIA_SAUVEGARDE_STOCKAGE_MACHINE` |

- Jeux rangés en `<dossier>/<machine>/<AAAAMMJJ-HHMMSS>/` (dossiers root 0700, aucune clé privée copiée). Le manifeste d'un jeu (`manifeste.json`, version 3) porte l'empreinte SHA-256 de chaque fichier copié ; `restaurer` et `retrouver` la vérifient avant toute écriture et refusent (code 1, `backup_integrity_failed`) si elle diffère ou manque.
- L'outil est lancé par les procédures depuis une copie du code appartenant à root, dans `/run/paresia-installation`, jamais depuis le clone du dépôt.
- La copie de sûreté de migration de `bunker.json` n'est pas une sauvegarde de procédure : elle reste dans le dossier d'état du démon.

### Paresia-admin, poste client (`admin.*`)

Exemple complet : `admin/app/conf/paresia-admin.conf`. Couches comme pour les autres programmes lancés par un utilisateur (`$XDG_CONFIG_HOME/paresia/`, puis `PARESIA_ADMIN_<DOMAINE>_<CLE>`). Aucun secret dans ce fichier.

| Section | Option | Défaut | Rôle |
| --- | --- | --- | --- |
| `[admin.connexion]` | `url` | obligatoire | adresse HTTPS de base, sans identifiant, chemin, requête ni fragment |
| | `hote_ssh`, `compte_ssh` | obligatoires | cible de l'ouverture de présence (nom DNS ou adresse IP ; compte, `app`) |
| | `ssh` | obligatoire (chemin) | exécutable `ssh` du poste client |
| `[admin.cle]` | `cle_publique` | obligatoire (chemin) | clé publique de l'administrateur (la clé privée reste dans l'agent SSH) |
| | `commande_forcee` | obligatoire (chemin) | commande forcée à inscrire côté serveur |
| | `ssh_keygen` | obligatoire (chemin) | exécutable `ssh-keygen`, lancé pour signer le défi de présence (`ssh-keygen -Y sign`, variable `PARESIA_ADMIN_CLE_SSH_KEYGEN`) ; la clé privée reste dans l'agent SSH (`SSH_AUTH_SOCK` est exigé), elle n'est jamais lue ni copiée |
| `[admin.presence]` | `ouverture_s` | 90 | attente de la réponse à l'ouverture de session (> 0 et au plus 3600 s) ; les autres délais viennent de la réponse du serveur |
| `[admin.interface]` | `langue` | obligatoire | étiquette BCP 47 de la forme `fr-FR` ; une langue absente du dossier se replie sur `fr-FR` |
| | `dossier_i18n` | obligatoire (chemin) | dossier des catalogues |

Variable : majuscules, tirets remplacés par `_`. Aucune paire de composants ne produit le même
nom (vérifié par les tests). Une variable inconnue du schéma est ignorée.

Lancement : `python3 -m admin.app [--config <fichier>]`. Aucune option nouvelle : la fenêtre lit `connexion.url` (adresse de base, origine unique de la navigation et du cookie du jeton), `cle.cle_publique` et `cle.commande_forcee` (ligne à remettre), `presence.ouverture_s` et `interface.*`. Une option invalide arrête le démarrage (code de sortie 1) avec le nom de l'option sur la sortie d'erreur, jamais sa valeur ; voir `paresia-admin(1)`.

### Journal d'activité et domaine `kernel` de Romulus (`[romulus.activite]`, `[romulus.noyau]`)

Romulus tient un journal d'activité (qui a demandé quoi, avec quel résultat ; jamais de paramètre, de réponse ni de secret) et sert le domaine d'administration `kernel` en lecture seule. Page de manuel : `paresia-romulus(8)`, sections JOURNAL D'ACTIVITÉ et DOMAINE KERNEL.

| Section | Option | Défaut | Rôle |
| --- | --- | --- | --- |
| `[romulus.activite]` | `detail` | 1 | niveau de détail : 1 actions et refus, 2 avec durée et service, 3 avec le dépannage du protocole ; hors de 1 à 3 : code 78 |
| | `taille_max` | 1048576 | volume total des deux fichiers, de 65536 à 16777216 octets |
| | `dossier` | sous-dossier `activite` du dossier d'état de Romulus | chemin absolu ; créé en 0700, fichiers en 0600 |
| | `regroupement_max` | 100000 | requêtes au plus par regroupement de refus sans session (1 à 1000000) |
| | `regroupements_simultanes` | 64 | regroupements ouverts au plus (1 à 1024) |
| `[romulus.noyau]` | `dossier_etat` | `/var/lib` | racine des dossiers d'état des démons dont `kernel/state/metrics` lit les métriques |

Variables : `PARESIA_ROMULUS_ACTIVITE_<CLE>` et `PARESIA_ROMULUS_NOYAU_DOSSIER_ETAT`. Le journal d'activité est un journal d'exploitation circulaire : à `taille_max`, les plus anciennes entrées disparaissent ; il n'est pas sauvegardé par les procédures (`docs/wiki/Sauvegarde-et-retour-arriere.md`). Les métriques restent désactivées par défaut ; une configuration d'exemple de démonstration qui les active est livrée sous `deploy/backend-admin/etc/paresia/exemples/`, non posée par l'installation.

### Journal et métriques du socle commun (`[journal]`, `[metriques]`)

Sections ajoutées par le socle commun (`server/commun/demon.py`) à la configuration d'un démon. **Pollux, Romulus, Castor, Remus, Nisaba et bunkerd les lisent** ; elles figurent dans les exemples `server/conf/paresia.conf` et `paresia-relais.conf` avec `actif = false`. Pour Nisaba, `niveau` s'ajoute à la section `[nisaba.journal]` existante. Les unités livrées de Pollux, Romulus, Castor et Remus portent `StateDirectory=paresia-<démon>` et `StateDirectoryMode=0711` (systemd.exec(5)) : `/var/lib/paresia-<démon>`, créé par systemd, propre au compte de l'unité, conservé à l'arrêt, inscriptible sous `ProtectSystem=strict` sans `ReadWritePaths=`. Le système reste en lecture seule ailleurs : un `dossier` hors de ce dossier fait échouer l'écriture (`metrics_write_failed`), et activer les métriques sans `dossier` ni `STATE_DIRECTORY` (hors systemd) fait refuser la configuration (78). L'unité de Nisaba a son propre `StateDirectory=` (voir `[nisaba.etat]`).

| Section | Option | Type, défaut | Rôle |
| --- | --- | --- | --- |
| `[<démon>.journal]` | `niveau` | `debug`, `info`, `notice`, `warning`, `error` ou `critical` ; défaut `info` | niveau minimal journalisé (priorités de la RFC 5424, § 6.2.1) ; `--debug` force `debug` |
| `[<démon>.metriques]` | `actif` | `true` ou `false` ; défaut `false` | écriture du fichier `<démon>.prom` : **désactivée par défaut** |
| `[<démon>.metriques]` | `dossier` | chemin absolu, facultatif | par défaut `metriques/` sous le premier dossier de `$STATE_DIRECTORY` (`/var/lib/paresia-<démon>/metriques`, fourni par l'unité livrée) ; si `actif = true` et qu'aucun dossier n'est déterminable : `config_missing` |
| `[<démon>.metriques]` | `periode_s` | durée en secondes, défaut 15, au plus 3600 | période d'écriture |

- Paresia **n'écrit jamais dans le dossier de node_exporter**. L'administrateur ajoute le dossier `metriques/` de chaque démon par un `--collector.textfile.directory` supplémentaire (option répétable ; motif glob admis dans node_exporter 1.9.0, Debian 13). Paresia ne modifie pas la configuration de node_exporter.
- Écriture atomique : fichier temporaire `<démon>.prom.tmp` puis renommage ; dossier créé en 0755, fichier en 0644 ; lien symbolique refusé. Un échec d'écriture est journalisé (`metrics_write_failed`) sans arrêter le démon.
- Séries publiées : `paresia_up`, `paresia_info` (étiquette `version`), `paresia_start_time_seconds`, `paresia_log_events_total` (étiquettes `daemon`, `level`).
- Types de schéma ajoutés : `niveau`, `booleen` (`true` ou `false`) ; `facultatif=True` pour `chemin`, `texte`, `compte` et `uid` (absence représentée par `None`).

### Fonctions enfichées de Remus (`[remus.plugins]`)

Section de Remus (`server/remus/__init__.py`, `SCHEMA_PLUGINS`), présente dans `server/conf/paresia-relais.conf`. Chemins par défaut conformes à FHS 3.0.

| Option | Type, défaut | Rôle | Variable |
| --- | --- | --- | --- |
| `fonctions` | chemin, `/usr/local/lib/paresia/remus/fonctions` | dossier des fonctions livrées | `PARESIA_REMUS_PLUGINS_FONCTIONS` |
| `locales` | chemin, `/etc/paresia/remus/plugins.d` | dossier des fonctions locales | `PARESIA_REMUS_PLUGINS_LOCALES` |
| `domaine` | texte, facultatif ; exemple livré : `relay` | domaine des actions servi par Remus (un seul en 1.0) : minuscules, chiffres et `_`, 32 caractères au plus, ni `presence` ni `castor` ; **sans lui, aucune fonction n'est chargée** | `PARESIA_REMUS_PLUGINS_DOMAINE` |
| `cible` | texte, `principale` | nom sous lequel Remus se présente dans le catalogue | `PARESIA_REMUS_PLUGINS_CIBLE` |

Les deux dossiers appartiennent à root, sans écriture pour le groupe ni les autres. Une valeur invalide de `domaine` ou de `cible` fait refuser la configuration (78, `config_invalid`). Format des fonctions : `docs/developpement.md`, § 6.2 ; manuel : `paresia-remus(8)`.

## Référence des options des démons

Source : les schémas de configuration de chaque démon (`server/<démon>/__init__.py`, `server/remus/executeur.py`, `server/pollux/session.py`) et les exemples `server/conf/`. « obligatoire » : pas de défaut dans le code (`config_missing` si absente). Types : `chemin` (absolu), `uid` (entier), `compte` (nom de compte existant), `duree` (secondes, > 0 et au plus 3600), `limite` (entier de 1 à 16777216, sauf indication), `texte`. Chaque option se remplace par `PARESIA_<COMPOSANT>_<DOMAINE>_<CLE>` (majuscules). Les sections `[<démon>.journal]` et `[<démon>.metriques]` sont décrites plus haut.

### Pollux

| Section | Option | Défaut | Rôle |
| --- | --- | --- | --- |
| `[pollux.sessions]` | `socket`, `uid`, `gid` | obligatoires | écoute de `pollux-session` : chemin, uid du compte `app`, groupe de la socket (mode 0660) |
| | `heartbeat_s` | 30 | battement attendu des applications ; DOIT être inférieur à `timeout_s` |
| | `timeout_s` | 90 | silence au-delà duquel la session est fermée |
| | `verification_s` | 0,1 | période de vérification des expirations ; au plus `timeout_s` |
| | `maximum` | 16 | sessions simultanées |
| `[pollux.relay]` | `socket`, `uid`, `gid` | obligatoires | écoute réservée à Romulus (`pollux-relay.sock`) |
| `[pollux.romulus]` | `socket`, `uid` | obligatoires | destination persistante vers Romulus ; l'uid du serveur est vérifié avant tout envoi |
| `[pollux.castor]` | `socket`, `uid` | obligatoires | socket locale du tunnel vers Castor et uid du processus qui l'écoute |

`pollux.signature` et `pollux.transport` : sections ci-dessus.

### pollux-session

| Section | Option | Défaut | Rôle |
| --- | --- | --- | --- |
| `[pollux-session.transport]` | `socket` | obligatoire | socket de Pollux |
| | `timeout_s` | 90 | silence au-delà duquel la session est coupée |
| | `open_timeout_s` | 30 | échéance absolue, depuis le démarrage du processus, pour réussir `open` (sinon code de sortie 1) |
| | `max_line` | 1048576 | taille maximale d'une ligne, LF compris |
| `[pollux-session.auth]` | `authorized_keys` | obligatoire | fichier des clés du compte SSH |
| | `max_signature` | 2048 | taille maximale de la signature base64 relayée ; DOIT égaler celle de `[pollux.signature]` |

### Romulus

| Section | Option | Défaut | Rôle |
| --- | --- | --- | --- |
| `[romulus.presence]` | `socket`, `uid_pollux`, `gid` | obligatoires | écoute de Pollux (mode 0660) ; seul l'uid de Pollux est admis |
| | `timeout_s` | 30 | échéance d'une requête à partir de son premier octet |
| | `max_line` | 1048576 | taille maximale d'une ligne |
| | `max_connexions` | 64 | connexions simultanées (1 à 1024) |
| | `max_sessions` | 1024 | sessions simultanées par connexion de Pollux ; au-delà `session_limit` |
| `[romulus.http]` | `socket`, `uid_lighttpd`, `gid` | obligatoires | socket HTTP (`romulus-http.sock`, mode 0660) ; seul l'uid du serveur web est admis |
| | `timeout_s` | 30 | délai de lecture de la socket |
| | `read_deadline_s` | 30 | échéance globale de lecture de la requête (en-têtes et corps) |
| | `max_body` | 65536 | corps maximal en octets ; au-delà `body_too_large` |
| | `max_headers`, `max_header_bytes` | 100, 16384 | nombre d'en-têtes et taille cumulée maximaux de la requête |
| | `max_connexions` | 64 | connexions HTTP simultanées (1 à 1024) ; l'excédent est fermé sans réponse |
| | `client_ip_header` | obligatoire | en-tête d'adresse que le mandataire de confiance DOIT poser (valeur du fichier livré : `X-Paresia-Client-IP`, voir `docs/serveur-web.md`) |
| | `fallback_ip` | obligatoire | adresse journalisée quand l'en-tête est absent, multiple ou invalide |
| | `export_max_octets`, `export_max_simultanes` | 8388608, 2 | voir « Export binaire de Romulus » |

`romulus.bunker`, `romulus.relay`, `romulus.nisaba` et `romulus.plugins` : voir « Aiguillage de Romulus ».

### Castor

| Section | Option | Défaut | Rôle |
| --- | --- | --- | --- |
| `[castor.tunnel]` | `socket`, `uid`, `gid` | obligatoires | socket du tunnel (`castor.sock`, mode 0660) ; seul le compte `tunnel` y envoie `castor/light/ping` et `castor/light/close` |
| `[castor.state]` | `socket`, `uid`, `gid` | obligatoires | socket d'état (`castor-state.sock`) ; seul l'uid de Remus y envoie `castor/light/state` ; son chemin diffère de `castor.tunnel` |
| `[castor.lights]` | `heartbeat_s`, `margin_s` | 30, 5 | le feu reste vert `heartbeat_s + margin_s` secondes après chaque ping (au plus 3600) |
| | `maximum` | 64 | feux simultanés (et sessions fermées mémorisées) |
| | `closed_s` | 10 | durée pendant laquelle une session fermée répond `session_closed` |
| | `verification_s` | 1 | période de purge des feux expirés |
| `[castor.transport]` | `delai_s`, `max_line`, `max_connexions` | 30, 1048576, 64 | échéance d'une connexion, taille d'une ligne, connexions simultanées par socket |

### Remus

| Section | Option | Défaut | Rôle |
| --- | --- | --- | --- |
| `[remus.server]` | `socket`, `uid`, `gid` | obligatoires | socket de Remus (`remus.sock`, mode 0660) ; seul le compte `tunnel` y envoie les commandes `relay/…` |
| | `stop_s` | 120 | attente maximale des opérations en cours à l'arrêt |
| `[remus.castor]` | `socket`, `uid` | obligatoires | socket d'état de Castor et compte qui la possède (vérifié avant tout envoi) |
| | `delai_s` | 2 | délai d'une interrogation, au plus `wait_s` |
| `[remus.light]` | `wait_s` | 5 | attente maximale du feu vert avant `relay_light_red` |
| | `poll_s` | 0,25 | période d'interrogation de Castor ; au plus `wait_s` |
| | `check_s` | 5 | période de contrôle du feu pour les flux ouverts |
| `[remus.transport]` | `delai_s` | 600 | échéance d'une connexion ; DOIT couvrir `wait_s` plus le délai maximal des commandes (sinon Remus refuse de démarrer) |
| | `max_line`, `max_connexions` | 1048576, 16 | taille d'une ligne ; connexions simultanées |
| `[remus.executor]` | `sudo`, `docker` | obligatoires | chemins des exécutables (usuellement `/usr/bin/sudo`, `/usr/bin/docker`) |
| | `delai_s` | 60 | délai par défaut d'une commande : `SIGTERM` au groupe de processus, puis `SIGKILL` après `kill_grace_s` |
| | `kill_grace_s` | 5 | délai entre `SIGTERM` et `SIGKILL` |
| | `sortie_max` | 65536 | octets de sortie conservés par commande (de 1 à 16777216) ; `sortie_max × 12` plus une marge DOIT rester inférieur à `max_line` |
| | `simultanes`, `attente_s` | 4, 5 | commandes simultanées ; attente d'un emplacement avant `command_busy` |

`remus.plugins` : voir « Fonctions enfichées de Remus ».

### bunkerd (sections non détaillées plus haut)

| Section | Option | Défaut | Rôle |
| --- | --- | --- | --- |
| `[bunkerd]` | `relay_identity` | obligatoire | identité servant de clé du relais ; `(none)` : aucune |
| `[bunkerd.etat]` | `home` | obligatoire | dossier d'état : profils `nak` et `bunker.json` |
| `[bunkerd.outils]` | `nak`, `setfacl` | obligatoires | exécutables `nak` et `setfacl` |
| `[bunkerd.controle]` | `socket` | obligatoire | socket de contrôle, réservée à root |
| `[bunkerd.web]` | `socket` | obligatoire | socket de la page web de déverrouillage ; `(none)` désactive la page |
| | `user` | obligatoire | compte autorisé par ACL sur cette socket (obligatoire même si la page est désactivée) |

## Démons, `pollux-session` et fichier explicite

- Les **démons** n'ont pas de couche utilisateur : un fichier du répertoire personnel d'un
  utilisateur ne peut pas modifier un démon, même si `HOME` ou `XDG_CONFIG_HOME` sont forgés.
  Leur environnement est fixé par l'unité systemd.
- `pollux-session` s'exécute dans la session SSH d'un client : il ne lit **aucune** variable
  d'environnement (`PARESIA_POLLUX_SESSION_*` et `PARESIA_POLLUX_SESSION_CONFIG` comprises), n'a
  aucun argument (pas de `--config`), et le lanceur vide l'environnement. Seules les couches 1 et 2 agissent.
- **Fichier explicite** (tests, conteneurs) : `--config <chemin>` ou `PARESIA_<COMPOSANT>_CONFIG`
  désigne un fichier unique qui remplace les couches fichier 1 à 3 ; `--config` prime ; les
  variables de la couche 4 s'appliquent ensuite. `--config` vide : `config_path_missing`.
- Le répertoire système `/etc/paresia` est une constante du module, remplaçable seulement par un
  paramètre de fonction (tests), jamais par une variable d'environnement.

## Contrôles de sécurité

Pour chaque fichier et dossier lu : ouverture avec `O_NOFOLLOW` (lien symbolique refusé :
`config_unreadable`), contrôle sur le descripteur ouvert, fichier régulier ou dossier réel,
propriétaire root ou uid effectif, aucune écriture pour le groupe ni les autres
(`config_unsafe_permissions`). S'applique à `/etc/paresia`, `conf.d` et au dossier utilisateur.
Taille d'un fichier au plus 1 Mio ; au plus 64 fichiers par dossier de couche (`config_too_large`).
Jamais de secret dans ces fichiers ni dans les variables `PARESIA_*` : les secrets sont des
fichiers montés.

## Codes d'erreur de configuration

Stables, sans valeur fautive ni contenu de ligne ; l'erreur porte au plus la section (domaine), la
clé et le nom de base du fichier.

| Code | Cas |
| --- | --- |
| `config_missing` | option obligatoire absente de toutes les couches |
| `config_invalid` | valeur de type ou de bornes incorrect (fichier ou variable) |
| `config_unknown_option` | option inconnue dans une section du composant |
| `config_unknown_section` | domaine inconnu dans une section du composant |
| `config_defaults_forbidden` | section `[DEFAULT]` |
| `config_unreadable` | fichier absent (fichier explicite), illisible, lien symbolique, syntaxe invalide, clé en double |
| `config_unsafe_permissions` | propriétaire non admis, écriture groupe/autres, fichier non régulier |
| `config_too_large` | fichier de plus de 1 Mio ou plus de 64 fichiers dans un dossier |
| `config_path_missing` | `--config` vide |
| `config_invalid_arguments` | argument autre que `--config` (toujours pour `pollux-session`) |
| `config_invalid_daemon`, `config_invalid_schema` | erreur de programmation |

## Unités systemd

Unités livrées : `deploy/backend-admin/etc/systemd/system/pollux.service` et
`romulus.service` (procédure : `deploy/backend-admin/installation-pollux-romulus.md`).

- `ConfigurationDirectory=paresia::ro` et `ConfigurationDirectoryMode=0755` : `/etc/paresia`
  reste à root, lisible et non inscriptible par le compte du service (`systemd.exec(5)` exclut cette
  directive du changement de propriétaire) ; `::ro` exige systemd 257 ou plus, sinon le retirer.
- Un `RuntimeDirectory=` par unité, mode `0711` : `/run/paresia-pollux` (`pollux.sock`,
  `pollux-relay.sock`) et `/run/paresia-romulus` (`romulus.sock`, `romulus-http.sock`). La socket
  locale du tunnel vers Castor (`/run/paresia-tunnel/pollux/castor.sock`) est dans un dossier créé
  par `tmpfiles.d` (voir plus bas), non par l'unité.
- Groupes, sans fichier ni autre usage : `paresia-sessions` (`pollux.sock` ; `app`, Pollux),
  `paresia-liaison` (`pollux-relay.sock`, `romulus.sock` ; Pollux, Romulus), `paresia-http`
  (`romulus-http.sock` ; `www-data`, Romulus). Les unités les reçoivent par `SupplementaryGroups=`.
- Identifiants : le dépôt livre des numéros d'exemple (uid 980 à 983, gid 984 à 986) ; le script
  d'installation les remplace par ceux que le système a attribués aux comptes (`useradd --system`).
  `www-data` reste 33. Ils sont inscrits dans `/etc/paresia/conf.d/10-backend-admin.conf`, au-dessus
  de `paresia.conf`.
- Environnement limité à `PYTHONPATH` ; aucun argument de configuration, aucune variable `PARESIA_*`.
- Fichiers de configuration appartenant à root et non inscriptibles par le compte du service.

Unités de backend-relais et du tunnel : `deploy/backend-relais/etc/systemd/system/castor.service` (`TimeoutStopSec=90`) et `remus.service` (`TimeoutStopSec=150`, `KillMode=mixed` pour que l'arrêt n'interrompe pas une opération en cours avant `stop_s`), `deploy/backend-admin/etc/systemd/system/paresia-tunnel.service` (compte `paresia-tunnel`). Un `RuntimeDirectory=` par unité de relais (`paresia-castor`, `paresia-remus`) ; le tunnel n'en a pas : ses dossiers sont créés par `deploy/backend-admin/etc/tmpfiles.d/paresia-tunnel.conf` (`tmpfiles.d(5)`, appliqué avant le démarrage, puis au démarrage du système) : `/run/paresia-tunnel` en `root:root` 0711, `romulus` en `paresia-tunnel:paresia-romulus` 0710, `pollux` en `paresia-tunnel:paresia-pollux` 0710, sans ACL ; l'unité ouvre en écriture ces deux sous-dossiers seulement (`ReadWritePaths=`). Raison : systemd v257 réapplique `RuntimeDirectoryMode` avant chaque commande, ce qui remettait le masque ACL à `---`. stdout et stderr vont à journald. L'isolation de Remus suit à la lettre le tableau de `deploy/backend-relais/isolation-remus.md`. Procédure (étapes 9 à 14, retour arrière sûr) : `deploy/backend-relais/installation-relais.md`. L'installation et le démarrage du tunnel : `deploy/installation-tunnel.md`.

## Emplacements

- Configuration : `/etc/paresia/paresia.conf` et `/etc/paresia/conf.d/`.
- Code serveur : `/usr/local/lib/paresia` ; lanceur : `/usr/local/bin/pollux-session`.
- Catalogues `i18n/<langue>.json` : conservés dans le dépôt. Les scripts d'installation lisent ceux du dépôt cloné ; le client
  prend `/usr/local/share/paresia/i18n/` pour valeur d'exemple de `[admin.interface] dossier_i18n`, et aucun
  script du serveur n'y installe de catalogue. Aucun chargeur commun n'existe encore : bunkerd (`server/bunkerd/state.py`) charge seul le catalogue `fr-FR` pour ses messages de démarrage, avec repli sur la clé ; le chargeur reste à centraliser dans `server/commun/`. Le choix de la langue (domaine `general` du premier composant concerné) viendra avec ce chargeur.

## Mode de déploiement

Cette configuration vaut pour le mode distribué (`paresia-yin` et `paresia-yang` sur des machines séparées, livré en 1.0). La configuration du mode Docker rootless tout-en-un, après la 1.0, n'est pas établie. Historique des modifications : `CHANGELOG.md`.
