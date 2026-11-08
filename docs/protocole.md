# Protocole entre jumeaux — Paresia

Version du document : 0.1.19 · 2026-11-08 · protocole `jumeaux/1`
Fait foi pour toutes les liaisons internes de Paresia-server. Complète `docs/cahier-des-charges.md` ; en cas d'écart, le cahier des charges l'emporte et ce fichier est corrigé.

## 1. Transport

- Liaisons internes : sockets Unix `SOCK_STREAM`. Entre backend-admin et backend-relais : les mêmes sockets, redirigées par le tunnel SSH (`ssh -L socket_locale:socket_distante`).
- Session de présence : entrée et sortie standard de `pollux-session`, à travers la session SSH de l'application.
- Lighttpd → Romulus : le transport est une socket Unix `SOCK_STREAM` (`romulus-http.sock`) ; le protocole échangé sur cette socket est HTTP/1.1 (lighttpd `mod_proxy`, voir § 6), et non `jumeaux/1`. Toutes les autres liaisons internes suivent ce document (`jumeaux/1`).
- Chaque démon serveur vérifie l'appelant à l'acceptation (`SO_PEERCRED`) et ferme la connexion d'un uid non prévu, sans répondre :

| Socket | Machine | Serveur | Appelant admis (uid) |
| --- | --- | --- | --- |
| `pollux.sock` (sessions) | backend-admin | Pollux | compte `app` (`pollux-session`) |
| `pollux-relay.sock` | backend-admin | Pollux | Romulus |
| `romulus.sock` (sessions) | backend-admin | Romulus | Pollux |
| `romulus-http.sock` (HTTP, § 6) | backend-admin | Romulus | lighttpd : uid `uid_lighttpd` de `[romulus.http]` (en configuration), contrôlé par `SO_PEERCRED` ; socket en mode 0660, groupe `gid` |
| socket d'administration de bunkerd | backend-admin | bunkerd | Romulus (compte d'uid 0 refusé : la socket n'est pas ouverte, raison de journal `admin_disabled`, jamais un code de réponse) |
| `ctl.sock` (bunkerctl) | backend-admin | bunkerd | root |
| `web.sock` | backend-admin | bunkerd | page web de bunkerd, hors du périmètre de ce document (`docs/configuration.md`) |
| `nisaba.sock` | backend-admin | Nisaba | Romulus (§ 5.2) |
| `nisaba-ctl.sock` | backend-admin | Nisaba | uid 0 seul (§ 5.2) |
| `castor.sock` | backend-relais | Castor | compte `tunnel` (sshd) ; seulement `castor/light/ping` et `castor/light/close` |
| `castor-state.sock` | backend-relais | Castor | Remus ; seulement `castor/light/state` |
| `remus.sock` | backend-relais | Remus | compte `tunnel` (sshd) |

Chaque socket n'admet que les actions de son rôle : une autre action reçue donne `unknown_action` (par exemple `light/state` sur `castor.sock`).

Propriétaire et mode (`server/commun/serveur.py`) : par défaut mode 0660 et groupe `gid` de la section de configuration. La socket est créée sous umask 0777 puis `chown` et `chmod` : elle n'est jamais plus ouverte que son mode final. Une socket ou un fichier préexistant n'est jamais supprimé par le serveur commun. Exceptions : la socket d'administration de bunkerd est en mode 0600 avec une ACL (`setfacl`) pour le seul compte de Romulus, et bunkerd supprime une socket périmée à son propre chemin ; `nisaba-ctl.sock` est en mode 0600.

Contrôle du serveur par l'appelant : les appelants internes de Romulus, de Remus et de Pollux vérifient l'uid du serveur par `SO_PEERCRED` avant tout envoi (`server/commun/client.py`, paramètre `uid_serveur`). Le paramètre est facultatif dans le client commun (§ 9) mais renseigné par chacun de ces appelants.

Chemins, comptes et uid viennent de la configuration, jamais du code.

## 2. Encadrement : NDJSON

- Un message = un objet JSON sur une seule ligne, encodé en UTF-8, terminé par `\n` (0x0A). Les sauts de ligne contenus dans les chaînes sont échappés par JSON.
- Longueur maximale d'une ligne : 1 Mio par défaut (réglable) ; 64 Kio (65536 octets, LF compris) par défaut pour la socket d'administration de bunkerd (`bunkerd.admin.max_line`), pour Nisaba (`[nisaba.socket] max_line`) et pour l'appel de Romulus vers bunkerd (`[romulus.bunker] max_line`). Au-delà : réponse `line_too_long`, connexion fermée.
- JSON strict (`server/commun/jumeaux.py`) : une clé en double, `NaN` et `Infinity` sont refusés (`bad_request`).
- Ligne illisible (JSON invalide, pas un objet) : réponse `bad_request` avec `id` nul ; la connexion reste ouverte ; le démon ne s'arrête jamais sur une entrée malformée.
- Une connexion peut porter plusieurs requêtes successives ; chaque réponse, sans exception, reprend l'`id` de sa requête.

## 3. Messages

**Requête**

```json
{"proto": "jumeaux/1", "id": "8f2a7d1b4c9e0a13", "session": 104, "action": "relay/events/count", "params": {}}
```

| Champ | Type | Règle |
| --- | --- | --- |
| `proto` | chaîne | `jumeaux/<majeure>` ; version du protocole, indépendante de la version du produit |
| `id` | chaîne | 16 caractères hexadécimaux (majuscules et minuscules admises), choisis par l'appelant |
| `session` | entier | numéro de session de présence ; 0 si l'action n'en dépend pas ou si la session n'existe pas encore (`presence/session/open`). C'est le seul emplacement du numéro de session : il n'apparaît jamais dans `params` |
| `action` | chaîne | `<domaine>/<objet>/<opération>`, liste fermée (§ 5) |
| `params` | objet | toujours présent, `{}` si vide ; champs inconnus refusés |

**Réponse**

```json
{"id": "8f2a7d1b4c9e0a13", "ok": true, "data": {"count": 14502}}
{"id": "8f2a7d1b4c9e0a13", "ok": false, "error": {"code": "relay_light_red", "detail": "no ping since 31 s"}}
```

- `ok` (et non `success`) : même convention que bunkerd et bunkerctl aujourd'hui.
- `error.code` : code stable, traduit par l'interface (`i18n/<langue>.json`), jamais modifié une fois publié.
- `error.detail` : facultatif, texte technique court en anglais, caractères de contrôle filtrés ; jamais de secret ni de donnée reçue telle quelle.
- `proto` de majeure différente : réponse `protocol_version_mismatch` puis fermeture.
- Champ `session` absent des `params` ; un `params` qui contient `session` est refusé (`bad_request`). Un démon qui reçoit une requête pour une session qu'il sait fermée répond `session_closed`.

**Exception HTTP : archive de réquisition (D25, D37)**

Seule l'action `legal/journal/export` (assurée par Nisaba, Romulus ne faisant que la router et en livrer la réponse HTTP) peut répondre
avec un corps binaire (§ 6). Les messages NDJSON entre démons restent inchangés.
Sans publication, la réponse HTTP est un statut 200, `application/json`, avec
`{"ok":true,"data":{"count":0}}` ; aucune archive n'est créée. Les erreurs gardent
la forme `{"ok":false,"error":{"code":"…"}}` et les statuts du § 9.

## 4. Échanges

**4.1 Session de présence (application ↔ `pollux-session` ↔ Pollux ↔ Romulus)**

La preuve de possession de la clé SSH est obligatoire (D20, D28). Une connexion à
`pollux.sock` reçoit au plus un défi, utilisable une seule fois. `session/challenge`
n'est jamais admise sur `pollux-relay.sock`.

1. Application → `pollux-session` : `{"proto":"jumeaux/1","id":"a1…","session":0,"action":"presence/session/challenge","params":{}}`.
   Le relais remplace les paramètres par `{"admin":"<commentaire de la clé SSH>","source":"<adresse SSH>"}`,
   obtenus de la connexion SSH (D1), et les transmet à Pollux.
2. Pollux → application : `{"id":"a1…","ok":true,"data":{"challenge":"<64 caractères hexadécimaux>","namespace":"paresia-presence","expires_s":60}}`.
   Pollux conserve le défi aléatoire de 32 octets, le nom, la source et l'échéance monotone
   dans le contexte de cette connexion. Le délai est paramétrable ; la surveillance ferme
   une connexion dont le défi non utilisé expire.
3. L'application connaît son nom d'administrateur (commentaire de sa clé publique).
   Elle vérifie l'espace de noms annoncé contre celui qu'elle attend, puis construit
   elle-même ces octets UTF-8, avec un saut de ligne final :

   ```text
   paresia-presence/1
   <défi>
   <admin>
   ```

   Elle fait signer ce message sur l'entrée standard de
   `ssh-keygen -Y sign -f <clé publique> -n <espace de noms>`, par un agent conforme
   au protocole standard SSH (RFC 9987). La clé privée n'est jamais exportée.
   Elle retire les lignes `-----BEGIN SSH SIGNATURE-----` et
   `-----END SSH SIGNATURE-----` ainsi que les retours à la ligne de l'enveloppe,
   pour ne transmettre que le base64 du blob SSHSIG binaire (PROTOCOL.sshsig d'OpenSSH).
   Elle ne signe jamais un texte arbitraire fourni par le serveur.
4. Application → `pollux-session` : `{"proto":"jumeaux/1","id":"a2…","session":0,"action":"presence/session/open","params":{"signature":"<base64 SSHSIG>"}}`.
   Le relais transmet uniquement `admin` et `source` issus de SSH, plus `signature`
   fournie par l'application. Les autres paramètres sont écartés. Il contrôle la forme
   ASCII base64 et la longueur maximale du texte (2048 octets par défaut), sans vérifier
   la signature. Sans `signature`, il transmet seulement `admin` et `source`.
5. Pollux contrôle d'abord la **forme** : session nulle, paramètres exactement
   `admin`, `source`, `signature`, nom et adresse valides, signature ASCII base64 bornée.
   Sinon : `bad_request`, sans fermer ni consommer le défi, qui reste utilisable jusqu'à
   son échéance. Il retire ensuite le **défi** du contexte, avant toute vérification :
   absence → `challenge_required`, expiration → `challenge_expired`, identité ou source
   différente → `signature_invalid`. Une deuxième demande de défi est refusée par
   `challenge_required`. Ces refus entraînent l'envoi de l'erreur puis la fermeture.
6. Pollux reconstruit le message de l'étape 3 et vérifie la **signature** hors du verrou
   global. Le format reconnu est SSHSIG version 1 ; l'espace de noms doit être celui
   annoncé ; seuls `sha256` et `sha512` sont admis pour le condensat du message.
   Clés admises : `ssh-ed25519`, `ecdsa-sha2-nistp256`, `ecdsa-sha2-nistp384`,
   `ecdsa-sha2-nistp521`, RSA d'au moins 2048 bits avec `rsa-sha2-256` ou `rsa-sha2-512`.
   La signature RSA/SHA-1 (`ssh-rsa`), DSA, les clés `sk-*` et les certificats sont refusés.
   Dans `authorized_keys`, seule l'option `cert-authority` est interprétée : une ligne
   qui la porte, ou dont les options sont mal formées, est ignorée (journal `key_ignored`,
   motifs `cert_authority` et `options`). Les autres options (`from=`, `restrict`,
   `principals=`) ne sont **pas** appliquées par Pollux : les restrictions inscrites sur
   une clé ne jouent pas ici (D20, D28). L'uid du compte `app` ne peut pas être 0.
   Les encodages et algorithmes suivent PROTOCOL.sshsig et les RFC 4251, 4253, 5656,
   8709 et 8332. Le champ réservé est pris en compte dans les données signées.
   La clé publique du blob doit figurer sous le nom exact de l'administrateur dans
   `authorized_keys` ; plusieurs clés sous un même nom sont admises. Le fichier est
   relu à chaque vérification, en lecture seule avec `O_NOFOLLOW`, et contrôlé sur le
   descripteur : fichier régulier, propriétaire root, non modifiable par le compte SSH,
   le groupe ni les autres. Une suppression de ligne retire donc immédiatement l'accès.
   Toute erreur de signature, de clé ou de fichier donne `signature_invalid`, sans
   distinction de cause côté client, puis ferme la connexion après la réponse.
   Si `cryptography` est absente : `not_available`, fermeture après réponse, démon vivant.
7. Après cette preuve seulement, Pollux → Romulus (`romulus.sock`) :
   `{"proto":"jumeaux/1","id":"b2…","session":0,"action":"presence/session/open","params":{"admin":"<commentaire de la clé SSH>","source":"<adresse SSH>"}}`.
   Romulus ne reçoit ni défi ni signature. Il crée le jeton (32 octets, `secrets.token_hex`)
   et le numéro de session : `{"id":"b2…","ok":true,"data":{"session":104,"token":"…"}}`.
   Pollux → application : `{"id":"a2…","ok":true,"data":{"session":104,"token":"…","heartbeat_s":30,"timeout_s":90}}`.
   C'est le seul message qui transporte le jeton hors de Romulus.
8. Battement : toutes les `heartbeat_s`, l'application envoie
   `{"proto":"jumeaux/1","id":"c3…","session":104,"action":"presence/session/ping","params":{}}` ;
   Pollux répond `{"id":"c3…","ok":true}`. Sans ping pendant `timeout_s`, il ferme la session.
   `ping` et `close` doivent avoir `params` vide et le numéro de session de la connexion,
   sinon `bad_request` ; sur une session inconnue ou fermée, ils donnent `session_closed`.
   Côté `pollux-session`, un `params` non vide pour une action qui n'est ni `challenge` ni
   `open` donne aussi `bad_request`.
9. Fin de session (SSH fermée, délai dépassé) : Pollux envoie `presence/session/close`
   (`"session":104`) à Romulus, qui détruit le jeton, et `castor/light/close`
   (`"session":104`) à Castor, qui passe le feu de cette session au rouge immédiatement.

Configuration : `[pollux.signature] authorized_keys` (chemin obligatoire, identique à
`[pollux-session.auth] authorized_keys`), `namespace` (texte obligatoire ;
`paresia-presence` dans l'exemple), `challenge_ttl_s` (60 s par défaut),
`max_signature` (2048 octets de texte base64 par défaut). Surcharges par
`PARESIA_POLLUX_SIGNATURE_<CLE>`, sans couche utilisateur.
Le relais conserve ses délais : une requête sans réponse est chronométrée ; l'attente
entre la réponse au défi et `open` ne l'est pas à ce titre. L'échéance absolue
`open_timeout_s` du processus continue de s'appliquer.

Journal de Pollux : `challenge_issued` (admin, source, connexion), `auth_ok`,
`auth_failed` avec une cause technique (`expired`, `no_challenge`, `bad_format`,
`bad_namespace`, `bad_hash`, `key_type`, `sig_algorithm`, `key_weak`, `key_unknown`,
`bad_signature`, `keys_file`, `not_available`). Les lignes de type de clé non admis
sont ignorées et journalisées au niveau info (`key_ignored`, sans la clé).
Ni défi, ni signature, ni jeton ne sont journalisés. Les textes affichés sont filtrés.
Une signature d'une autre connexion ou d'un autre nom ne prouve pas ce défi.
Le relais d'un défi au sein d'un canal SSH authentifié déjà compromis reste hors du
modèle de protection.

**4.2 Commande destinée au relais (Romulus → Remus ; Romulus → Pollux → Castor)**

1. Romulus → Remus : la requête `relay/…` (`"session":104`). Remus la met en attente.
2. Romulus → Pollux (`pollux-relay.sock`) : `presence/relay/ping` (`"session":104`). Pollux répond `session_closed` si la session n'est plus ouverte ; sinon il envoie `castor/light/ping` (`"session":104`) à Castor et répond `{"id":…,"ok":true}`, ou `peer_unavailable` si Castor ne répond pas.
   Règle de Romulus : le ping part après l'envoi de la requête à Remus, au plus une fois par `heartbeat_s` et par session (une commande concurrente attend l'issue du ping en cours). Toute erreur de Pollux autre que `session_closed` devient `peer_unavailable` ; un refus du ping remplace la réponse de Remus.
3. Castor tient un feu par session. Un ping passe le feu de cette session au vert pour `green_s` secondes ; `green_s` = `heartbeat_s` + `margin_s` (30 + 5 = 35 s par défaut, réglables). Sans nouveau ping dans ce délai, ou sur `castor/light/close`, le feu repasse au rouge. Après `close`, la session est mémorisée fermée pendant `closed_s` (10 s par défaut, D50) : `ping` et `state` répondent `session_closed` pendant ce délai. Au plus `maximum` feux (`[castor.lights]`, 64 par défaut) : au-delà, un ping d'une nouvelle session reçoit `session_limit`. Le fil de surveillance tourne toutes les `verification_s` (1 s par défaut). `session` doit valoir au moins 1 et `params` être vide, sinon `bad_request`. `castor/light/state` répond `{"state":"green","remaining_s":<entier ≥ 1>}` ou `{"state":"red"}`.
4. Remus interroge Castor (`castor/light/state`, `"session":104`) toutes les `poll_s` (0,25 s par défaut) ; tant que le feu est rouge, il réessaie jusqu'à `wait_s` (5 s par défaut), puis répond `relay_light_red`. Feu vert : il exécute et répond. Autres issues : `session_closed` immédiat si Castor le dit ; `peer_unavailable` si Castor est injoignable (ou répond une forme inattendue) à l'issue de `wait_s` ; `bad_request` si `session` vaut 0 ; `not_available` pour une action non enregistrée, contrôlée avant `session`. `check_s` (5 s par défaut) est la période de surveillance des flux ouverts.
5. Romulus renouvelle `presence/relay/ping` au plus une fois par `heartbeat_s` pour une session qui a des commandes ou des flux en cours.
6. Feu repassé au rouge (expiration ou fermeture) : les commandes en attente de cette session reçoivent `relay_light_red` ou `session_closed`, ses flux s'arrêtent ; une opération déjà en cours d'exécution dans strfry va à son terme et son résultat est journalisé.

**4.3 Flux continus (suivi en direct, opération 7)**

Une requête `relay/state/follow` reçoit plusieurs lignes de réponse de même `id` : `{"id":"…","ok":true,"stream":"line","data":{…}}`, puis une dernière `{"id":"…","ok":true,"stream":"end"}` (ou `{"id":"…","ok":false,"error":{"code":"relay_light_red"}}`). Tant que le flux est ouvert, Romulus renouvelle le ping de sa session à chaque `heartbeat_s`, même sans nouvelle commande. Romulus convertit le flux en événements HTTP `text/event-stream` ; il s'arrête quand le feu repasse au rouge, quand la session se ferme ou quand le client se déconnecte. Côté Remus, le flux s'arrête avec le code `relay_light_red` (feu rouge), `session_closed` (session fermée) ou `peer_unavailable` (Castor ou arrêt de Remus) ; une erreur de l'opération (`internal_error` ou son propre code) l'emporte sur la raison d'arrêt. La fermeture du transport libère l'opération et son registre.

## 5. Actions (liste fermée du noyau, catalogue par domaine)

Les deux couples de jumeaux (Romulus et Remus, Pollux et Castor) sont le noyau de Paresia : ils transportent des actions sans en connaître le contenu. Les greffons livrés (relais strfry, bunkerd, Nisaba, journal légal) s'y enfichent ; leurs actions, déclarations et documents leur appartiennent.

**Liste fermée du noyau.** Seules les actions de présence et de feu appartiennent au noyau. Ce tableau est contrôlé par un test contre les descripteurs du catalogue du noyau (`server/commun/noyau.py`), qui en est la source unique ; `ACTIONS` (`server/commun/jumeaux.py`) en est calculée.

| Domaine | Actions |
| --- | --- |
| `presence` | `session/challenge`, `session/open`, `session/ping`, `session/close`, `relay/ping` |
| `castor` | `light/ping`, `light/state`, `light/close` |

**Liste fermée par catalogue.** Tout autre domaine est celui d'un greffon, qui déclare ses actions : une action est admise si elle a la forme `domaine/objet/opération` (1 à 128 caractères, minuscules, chiffres, `_` et `-`, de 2 à 4 segments) **et** figure au catalogue du démon qui sert la socket. Toute action absente de ce catalogue est refusée avec `unknown_action`. Le contrôle de l'uid du pair (`SO_PEERCRED`) et la validation des paramètres s'appliquent à toute action.

**Introspection.** Chaque domaine d'un démon enfichable répond à `<domaine>/catalog/list` (lecture seule, `params` vide) et `<domaine>/catalog/describe` (`params` = `{"action"}`), définies par leur suffixe et décrites au § 5.5. Le catalogue d'un domaine est la source unique de ses actions, de ses paramètres typés et de ses erreurs ; la description du `data` reste en prose dans ce document (limite assumée), et les tableaux des paragraphes 5.1 à 5.3 sont contrôlés contre leur source (le catalogue du noyau pour le § 5.3, la déclaration livrée pour les autres), non générés.

**Adresse d'une action.** Une action est adressée par (cible, domaine, action). En 1.0 la cible est celle du démon qui sert la socket interrogée (une cible par démon) ; elle n'est pas portée par la chaîne d'action, `catalog/list` la publie (`target`), et les catalogues sont indexés par (cible, domaine). Aucun appel n'est supposé aller d'un greffon yang vers un seul greffon yin : l'appariement de leurs noms est une convention de livraison, non un mécanisme du protocole. Le format des greffons (clé `format`, champ `forme` réservé) est défini par la documentation du format ; ce protocole ne fixe qu'une forme ponctuelle. Le contrat d'un greffon s'exprime en exécutable, JSON et codes de sortie, sans nommer de langage.

**Nommage des greffons.** `paresia-yin-<nom>` pour un greffon chargé par Remus, `paresia-yang-<nom>` pour un greffon chargé par Romulus ; un greffon à deux côtés est une paire de même nom de base, livrée et versionnée ensemble. Le champ `plugin` des réponses de `catalog/list` et `catalog/describe` porte le nom du greffon qui répond.

**Correspondance avec Varlink (voie d'évolution, aucun développement engagé ; `jumeaux/2` sera réévalué après la 1.0, D154).** Le domaine est l'interface ; une action sans domaine est une méthode : `identity/add` devient `IdentityAdd`, `relay-key/sign-mute-list` devient `RelayKeySignMuteList` (fonction `nom_varlink` de `server/commun/catalogue.py`). Le type d'un paramètre est le type de l'IDL, un paramètre facultatif un type nullable ; un code d'erreur est une erreur nommée `<interface>.<CodeEnCamelCase>`. Ce que l'IDL ne porte pas (bornes, motifs, privilège) reste dans `describe`. Le préfixe d'interface n'est pas fixé ici.

Les paramètres des actions sont reportés dans un tableau par domaine : `bunker` (§ 5.1) et `nisaba` (§ 5.2), greffons livrés ; `presence` et `castor` (§ 5.3), `kernel` (§ 5.6), noyau. Les actions du relais strfry sont dans `docs/plugins/strfry.md` ; celles du journal légal ne sont pas implémentées (§ 5.4).

**Exposition par HTTP (§ 6).** Le domaine `kernel`, servi par Romulus lui-même (§ 5.6), a une route `POST /api/admin/kernel/…`. Les autres routes `POST /api/admin/…` viennent des déclarations de services de Romulus (`paresia-yang-<nom>.toml`, `docs/developpement.md`, § 6.3 ; D148, D150), sans liste en dur. Les domaines exposés sont ceux des déclarations installées ; les actions `<domaine>/catalog/list` et `<domaine>/catalog/describe` sont routables pour les domaines qui publient un catalogue (servies par Romulus pour `catalogue = "declaration"`, transmises au pair pour `catalogue = "pair"`). Seules `nisaba/state/status` et `nisaba/state/verify` sont exposées pour Nisaba (les autres actions du § 5.2 ne sont pas déclarées) ; sans la section `[romulus.nisaba]`, elles répondent 501 `not_available`. Un autre chemin, donc `presence/*` et `castor/*`, reçoit 404 `unknown_action`, avant le contrôle du jeton. L'uid du pair de chaque service est vérifié avant tout envoi (`SO_PEERCRED`).

L'action legal/journal/export (51) livre l'archive de réquisition selon le § 6.
Sa construction est confiée à Nisaba, prévue et non livrée (aujourd'hui `legal/*` répond 501 `not_available`, § 5.4) : extraction.jsonl, preuves.txt, sceaux
seals/<jour>.txt et leurs preuves .ots disponibles, fichiers MANIFEST des jours
concernés, et SHA256SUMS. SHA256SUMS couvre tous les fichiers de contenu de
l'archive, MANIFEST compris (il ne peut pas contenir sa propre empreinte).
La forme exacte des MANIFEST est définie par le cahier des charges ; le transport
ne prescrit ni un fichier entier ni une sélection de lignes.

### 5.1 Domaine `bunker` : `params` et `data`

Greffon livré avec Paresia (`paresia-yang-bunkerd`). Socket d'administration de bunkerd (§ 1), appelant Romulus ; seuls l'uid du compte de Romulus (`SO_PEERCRED`) et seulement les neuf actions `identity/*` et `relay-key/sign-mute-list` sont admis ; il n'existe pas d'action de déverrouillage, de verrouillage ni d'adresse `bunker://` sur cette socket. `session` (entier ≥ 0, enveloppe) n'est que journalisé. Un champ inconnu ou manquant dans `params` donne `bad_request`. **Par la voie HTTP, Romulus prévalide d'abord la forme** (D57, descripteurs de la déclaration `paresia-yang-bunkerd.toml`) : nom des champs, présence des obligatoires et type JSON (texte, entier non booléen, liste). Tout champ inconnu ou manquant, ou de mauvais type, donne `bad_request` (400) avant d'atteindre bunkerd ; par exemple `identity: 5` donne `bad_request` et non `invalid_identity`, et `timeout_min: true` donne `bad_request` et non `invalid_timeout`. Les formats de valeur ci-dessous sont contrôlés par bunkerd. Sur la socket d'administration directement (sans Romulus), les contrôles de forme sont ceux de bunkerd. `identity` : 1 à 32 caractères parmi `a-z`, `0-9`, `-`, `_`. `relays` : 1 à 10 adresses, `wss://` ; `ws://` seulement pour un hôte en `.onion` ; doublons supprimés en gardant l'ordre. `ncryptsec` : jamais renvoyé ni journalisé. `client` : clé publique en npub ou en 64 caractères hexadécimaux (convertie et stockée en hexadécimal ; somme bech32 contrôlée). `minutes` et `timeout_min` : entier (non booléen) de 1 à 1440. Les contrôles sont faits dans l'ordre : forme de l'identité, existence (`clients`, `timeout`), `minutes`, identité déverrouillée, existence ou non (`add`), formats.

| Action | `params` | `data` | Erreurs spécifiques |
| --- | --- | --- | --- |
| `identity/list` | `{}` | `{"identities":[{"identity","unlocked","remaining" (secondes, seulement si déverrouillée),"pubkey" (ou null),"relays","clients" (nombre),"timeout" (secondes),"relay_key" (booléen)}]}` | — |
| `identity/clients` | `identity` | `{"clients":[{"pubkey","name","url"}]}` | `invalid_identity`, `unknown_identity` |
| `identity/add` | `identity`, `ncryptsec`, `relays`, `timeout_min` (facultatif, 15 par défaut) | — | `invalid_identity`, `identity_unlocked`, `identity_exists`, `invalid_ncryptsec`, `invalid_relays`, `invalid_timeout` |
| `identity/secret` | `identity`, `ncryptsec` | — | `invalid_identity`, `identity_unlocked`, `unknown_identity`, `invalid_ncryptsec` |
| `identity/relays` | `identity`, `relays` | — | `invalid_identity`, `identity_unlocked`, `unknown_identity`, `invalid_relays` |
| `identity/authorize` | `identity`, `client` | — (idempotent) | `invalid_identity`, `identity_unlocked`, `unknown_identity`, `invalid_client` |
| `identity/revoke` | `identity`, `client` | — | `invalid_identity`, `identity_unlocked`, `unknown_identity`, `invalid_client`, `client_not_authorized` |
| `identity/timeout` | `identity`, `minutes` | — (permis déverrouillée, effet immédiat) | `invalid_identity`, `unknown_identity`, `invalid_timeout` |
| `identity/remove` | `identity`, `confirmation` (égale à `identity`) | — | `invalid_identity`, `identity_unlocked`, `unknown_identity`, `relay_identity_protected`, `confirmation_mismatch` |
| `relay-key/sign-mute-list` | `identity` (égale à `relay_identity`), `passphrase` (chaîne non vide, jamais journalisée), `pubkeys` (0 à 500 chaînes de 64 caractères hexadécimaux minuscules, distinctes ; npub refusé) | `{"event":{"id","pubkey","created_at","kind" (10000),"tags" (une étiquette `["p", clé]` par clé, dans l'ordre reçu),"content" (vide),"sig"}}` | `invalid_identity`, `invalid_passphrase`, `invalid_pubkeys`, `not_relay_key`, `unknown_identity`, `pubkey_mismatch`, `not_available`, `log_n_too_high`, `bad_passphrase` (réponse retardée de 2 s) |

Note : `pubkey_mismatch` n'est pas retardé. Le déchiffrement (scrypt) et la pause de 2 s sont sérialisés par un verrou dédié : une seule opération de ce genre à la fois, les autres actions restent servies. La signature produite est vérifiée avant d'être renvoyée (échec : `internal_error`).

`relay_key` vaut `true` pour l'unique identité désignée par l'option `relay_identity` de la configuration de bunkerd (posée par l'administrateur root ; aucune action ne la modifie) ; `identity/remove` refuse cette identité (`relay_identity_protected`), alors que `ctl.sock` (root) reste inchangé. Chaque adresse de relais fait 255 caractères au plus, et un saut de ligne final dans un nom, un relais ou un `ncryptsec` est refusé.

### 5.2 Domaine `nisaba` : `params`, `data` et traces (D87, D111)

Greffon livré avec Paresia (`paresia-yang-nisaba`). Nisaba (processus annexe du journal légal, backend-admin) écoute sur deux sockets Unix (`docs/configuration.md`, § Nisaba) : `nisaba.sock`, où seul le compte de Romulus (`SO_PEERCRED`) est admis, sert `nisaba/state/status` et `nisaba/state/verify` ; `nisaba-ctl.sock` (mode 0600, uid indiqué seul admis, en pratique root) sert en plus `nisaba/job/run`, `nisaba/acl/check` et `nisaba/acl/apply` pour la ligne de commande `python3 -m server.nisaba.ctl` (`status`, `verify`, `run <tâche> [AAAA-MM-JJ]`, `metrics`, `acl check`, `acl apply`). Codes de sortie de la CLI : 0 succès, 1 échec, 2 usage, 3 Nisaba injoignable. Une action réservée à la socket de contrôle, reçue sur `nisaba.sock`, donne `unknown_action`.

| Action | `params` | `data` | Erreurs spécifiques |
| --- | --- | --- | --- |
| `nisaba/state/status` | `{}` | `{"demarrage","taches":{<tâche>:{"derniere","resultat","prochaine","echecs"}},"journal","metriques"}` ; dates ISO 8601 UTC ; `echecs` : 20 derniers échecs de la tâche (code `ECHEC_*`, texte filtré, heure) | `command_busy` |
| `nisaba/state/verify` | `{}` | `{"code":0\|1,"lignes":[…]}` : vérification du `MANIFEST` et des sceaux (lecture seule) | `command_busy` |
| `nisaba/job/run` | `task` (`copie`, `scellement`, `horodatage` ou `purge`) ; `day` (`AAAA-MM-JJ`, seulement avec `scellement` : journée terminée, UTC) | `{"tache","resultat":"ok"\|"echec","echecs"}` | `bad_request`, `not_available` (tâche non enregistrée), `command_busy` |
| `nisaba/acl/check` | `{}` | `{"code":0\|1,"lignes":[…]}` (200 lignes au plus) : propriétaire, entrées ACL et attributs, sans essai de lecture ; lecture seule | `bad_request` |
| `nisaba/acl/apply` | `{}` | `{"code":0\|1,"lignes":[…]}` : modes, ACL et attributs rétablis, un élément à la fois | `bad_request`, `command_busy` |

Un seul traitement exclusif à la fois (planificateur, vérification, `acl apply`) : un second reçoit `command_busy`.

**Lignes de trace de `acl check|apply` et de `verify` (D111).** Les lignes de `data.lignes` sont un format de données stable de la preuve : reprises des anciens scripts `journal-legal-*`, versées telles quelles dans `preuves.txt`, **non traduites** (elles ne passent pas par les catalogues `i18n/`) et filtrées (`server/commun/texte.py`). Formes :
- `verify` : `OK      <jour>  <statut>` ; `ERREUR ligne <n> (<jour>) : <texte>` ; `ERREUR lecture impossible : <fichier> (droits ou ACL manquants)` ; `registre vide ou absent : <fichier>` ; dernière ligne `RÉSULTAT : registre intègre (<n> journées)` ou `RÉSULTAT : <n> erreur(s)`. Le code vaut 0 sans erreur, 1 sinon.
- `acl check` : une ligne par défaut constaté ; `OK      MANIFEST absent (pas encore créé) : <fichier>` ou `OK      seals/ absent (pas encore créé) : <dossier>` ; dernière ligne `RÉSULTAT : conforme` ou `RÉSULTAT : <n> erreur(s)`. La reprise d'un fichier sans l'attribut d'immuabilité (`+i`) est détectée ; un `lsattr` illisible vaut « non immuable ».
- `acl apply` : `INCHANGE <chemin> (déjà conforme)` ; `TRAITE <chemin>` ; `ARRÊT : …` (interruption demandée ou rétablissement d'attribut impossible) ; dernière ligne `RÉSULTAT : modes et ACL appliqués` ou `RÉSULTAT : <n> élément(s) en échec`. Les lignes `INCHANGE` ne sont pas renvoyées par la socket (taille de la réponse) ; toutes les lignes sont écrites à journald ; un échec ajoute une ligne `ECHEC_ACL <détail>`.

Les échecs des tâches sont écrits à journald avec leur code stable en tête de ligne (`ECHEC_COPIE`, `ECHEC_ACL`, `ECHEC_SCELLEMENT`, `ECHEC_HORODATAGE`, `ECHEC_PURGE`), étiquette unique `nisaba` (D89).

État réel : Romulus route par HTTP `nisaba/state/status` et `nisaba/state/verify`, d'après la déclaration `paresia-yang-nisaba.toml` (service facultatif : sans la section `[romulus.nisaba]`, 501 `not_available` ; D148). Les actions `nisaba/job/run`, `nisaba/acl/check` et `nisaba/acl/apply` ne sont atteignables que par la CLI `python3 -m server.nisaba.ctl`.

### 5.3 Domaines `presence` et `castor` : `params` et `data`

| Action | `params` | `data` | Erreurs spécifiques |
| --- | --- | --- | --- |
| `presence/session/challenge` | application → relais : `{}` ; relais → Pollux : `admin`, `source` | `{"challenge" (64 caractères hexadécimaux),"namespace","expires_s"}` | `bad_request`, `challenge_required`, `auth_info_unavailable` |
| `presence/session/open` | application → relais : `signature` (base64 SSHSIG) ; Pollux → Romulus : `admin`, `source` | application : `{"session","token","heartbeat_s","timeout_s"}` ; Romulus à Pollux : `{"session","token"}` | `bad_request`, `challenge_required`, `challenge_expired`, `signature_invalid`, `session_limit`, `auth_info_unavailable`, `not_available` |
| `presence/session/ping` | `{}` | — | `bad_request`, `session_closed` |
| `presence/session/close` | `{}` | — | `bad_request`, `session_closed` |
| `presence/relay/ping` | `{}` (sur `pollux-relay.sock` seulement) | — | `bad_request`, `session_closed`, `peer_unavailable` |
| `castor/light/ping` | `{}` | — | `bad_request`, `session_closed`, `session_limit` |
| `castor/light/close` | `{}` | — | `bad_request` |
| `castor/light/state` | `{}` | `{"state":"green","remaining_s"}` ou `{"state":"red"}` | `bad_request`, `session_closed` |

Voir § 4.1 pour l'enchaînement du défi et § 4.2 pour les feux. Les codes de `presence/session/open` sont ceux que porte le code de Pollux et de Romulus ; la table complète est au § 9.

### 5.4 Domaines `relay` et `legal` : greffons, état non implémenté

- `relay/*` : Remus est enfiché (0.1.9) : ses actions sont celles des fonctions chargées (§ 5.5) et le greffon de base de strfry livre trois fonctions : `relay/state/status`, `relay/sync/trees` et `relay/container/restart`, sans paramètre. Le catalogue de Remus contient donc ces trois actions et les deux actions de catalogue `relay/catalog/list` et `relay/catalog/describe` (si `[remus.plugins] domaine = relay`, valeur de l'exemple livré). Toute autre action `relay/…` reçoit de Remus `unknown_action` (action absente de son catalogue), que Romulus convertit en `not_available` (501 par HTTP, `server/romulus/aiguillage.py`) ; le client ne voit donc pas de changement. La liste des fonctions prévues est dans `docs/plugins/strfry.md` (contrat prévu, non un état livré). Seul `castor/light/state` est consulté pour les actions des fonctions chargées ; les deux actions de catalogue sont servies sans attendre le feu.
- `legal/*` : la consultation du journal légal (recherche, export, état, vérification) est confiée à Nisaba ; Romulus ne fait que router ces actions vers lui. La recherche et l'export ne sont pas livrés (état et vérification le sont, sous `nisaba/state/*`, § 5.2). Romulus répond 501 `not_available` à toute action `legal/*` (`FrontalHTTP.actions` sans enregistrement, § 6.1). Les tableaux `params` et `data` de ces deux domaines s'ajouteront avec le code qui implémente chaque action.

### 5.5 Introspection du catalogue et fonctions enfichables (D148, D154)

**État réel : Remus sert ces actions (0.1.9) ; Romulus sert celles de `bunker` et de `nisaba` depuis ses déclarations de services (0.1.16).** Le catalogue, le chargeur de fonctions et le contrat de sortie sont dans le socle commun (`server/commun/catalogue.py`, `plugins.py`, `sortie.py`, `privileges.py`). Remus les appelle (`server/remus/fonctions.py`) : ses actions `relay/…` sont celles des fonctions chargées des dossiers configurés (`[remus.plugins]`, `docs/configuration.md`) et il répond aux deux actions de catalogue de son domaine, lecture seule, sans attendre le feu de Castor. Les fonctions livrées sont celles du greffon de base (§ 5.4). Les autres démons n'ont pas de greffon. Une action absente du catalogue de Remus reçoit `unknown_action` (avant 0.1.9 : `not_available`). Romulus route les actions de catalogue par HTTP (0.1.16) : il sert lui-même celles des domaines déclarés avec `catalogue = "declaration"` (`bunker`, `nisaba`) et transmet à Remus celles de `relay` (`catalogue = "pair"`). Aucune liste d'actions de greffons n'existe dans le socle (seule la liste du noyau, § 5, y est calculée de son catalogue) : une action est admise si elle a la forme `domaine/objet/opération` (1 à 128 caractères, minuscules, chiffres, `_` et `-`, de 2 à 4 segments) **et** figure dans l'ensemble que le démon déclare. Le serveur (`Serveur`) et le client (`Connexion`, paramètre `actions`) contrôlent la forme ; la liste admise reste celle du démon.

Chaque domaine d'un démon enfichable répond à deux actions de catalogue, de forme `<domaine>/catalog/list` et `<domaine>/catalog/describe`, ajoutées d'office au catalogue. Elles sont en lecture seule et ne publient aucun secret, aucun chemin et aucune commande privilégiée. Les domaines `presence` et `castor` sont réservés et ne peuvent pas être des domaines de greffons.

| Action | `params` | `data` | Erreurs |
| --- | --- | --- | --- |
| `<domaine>/catalog/list` | `{}` | `{"proto":"jumeaux/1","target","domain","format":1,"actions":[{"action","plugin"}…]}`, actions triées | `bad_request` (`params` non vide) |
| `<domaine>/catalog/describe` | `{"action"}` (forme valide, 128 caractères au plus) | `{"action","plugin","privilege","delay_s","parameters":[…],"errors":[…]}` | `bad_request` (clés ou forme invalides), `unknown_action` (action absente du catalogue) |

`target` vaut `principale` par défaut. Un paramètre publié est `{"name","type","required","bounds"}`. Types : `texte` (bornes `motif`, `longueur_max`), `entier` (`minimum`, `maximum`), `choix` (`valeurs`), `hexadecimal` (`longueur`), `liste_entiers` (`minimum`, `maximum`, `nombre_max`, facultatif `nombre_min`), `liste_texte` (`motif`, `longueur_max`, `nombre_max`, facultatif `nombre_min`) ; toutes les bornes requises d'un type sont obligatoires. Le descripteur se traduit en interface Varlink sans perte de sens : le domaine est l'interface, `objet/opération` devient la méthode `ObjetOperation`, un code d'erreur devient `<interface>.<CodeEnCamelCase>` ; les bornes autres que `valeurs` restent dans le descripteur et dans `describe`.

**Contrat de sortie d'une fonction** (`server/commun/sortie.py`). Une fonction est un exécutable lancé hors processus par le démon. Sa sortie standard est un seul objet JSON strict (UTF-8, sans doublon de clé, sans `NaN` ni `Infinity`, profondeur 8 au plus, sans caractère de contrôle), de taille au plus `sortie_max` (65 536 octets par défaut) : `{"ok":true,"data":{…}}` ou `{"ok":false,"error":{"code":"…"}}`, rien d'autre. Le code de sortie recoupe le JSON : 0 avec `ok` vrai ; 1 avec un `code` déclaré dans les `erreurs` du descripteur ; 2 avec le seul code `not_available`. Tout autre code, tout signal, toute sortie trop longue ou non conforme, tout code d'erreur non déclaré est une violation : la réponse est `command_failed`, sans la sortie brute ni message du script.

**Codes de chargement** (journal et rejets du chargeur ; ils ne sont pas des réponses `jumeaux/1`) :

| Code | Sens |
| --- | --- |
| `plugin_manifest_invalid` | manifeste illisible, hors format ou hors bornes (clé inconnue, nom, action, délai, paramètre, commande privilégiée) |
| `plugin_format_unsupported` | `format` du manifeste différent de 1 |
| `plugin_form_unsupported` | `forme` autre que `ponctuel` |
| `plugin_incomplete` | script ou manifeste manquant |
| `plugin_unexpected_entry` | entrée inattendue du dossier (nom hors motif, non ordinaire) |
| `plugin_unsafe_permissions` | propriétaire, droits (écriture groupe ou autres, bits setuid ou setgid, absence de bit d'exécution du script) ou lien symbolique refusés |
| `plugin_unreadable` | dossier ou fichier illisible |
| `plugin_too_many` | plus de 256 fonctions |
| `plugin_duplicate` | nom, action ou nom de méthode Varlink déjà pris |
| `plugin_privileges_rejected` | commandes privilégiées refusées par le vérificateur du démon |

Une condition de chargement non remplie (`requiert`) n'est pas un rejet : la fonction est écartée avec l'événement `plugin_skipped` (`code` `plugin_requirement_unmet`, champ `requirement` : `binaires` ou `fichiers`). Événements du chargeur : `plugin_rejected` (erreur), `plugin_skipped` (avertissement), `plugin_loaded` (débogage), avec `code`, `scope` (`livre` ou `local`) et `file` (nom de base filtré), jamais de chemin ni de valeur fautive. Politique : tout défaut d'un élément livré est fatal ; tout défaut d'un élément local fait ignorer le dossier local entier (rien n'est gardé de ce dossier). Côté Remus, un paramètre que les gabarits de l'exécuteur n'expriment pas (entier négatif, liste de plus de 1024 éléments, `nombre_min` supérieur à 1) est refusé : fatal pour une fonction livrée (`plugin_manifest_invalid`, démarrage refusé, code 78), et pour une fonction locale cette seule fonction est ignorée (`plugin_rejected`) et retirée du catalogue. Une erreur fatale de chargement ne publie ni chemin ni nom de fichier (`startup_failed`).

### 5.6 Domaine `kernel` et journal d'activité de Romulus

Le domaine `kernel` est servi par Romulus lui-même (`POST /api/admin/kernel/<objet>/<opération>`, jeton et contrôle `Origin` comme toute action), sans pair, sans passage par Pollux ni par le relais. Il est en lecture seule et ne publie aucun secret, aucun chemin, aucun compte ni aucune socket. Le domaine est réservé : une déclaration de service ne peut pas le prendre. `params` est validé exactement (champ inconnu, manquant ou de mauvais type : `bad_request`) ; une réponse fait 1 Mio au plus.

| Action | `params` | `data` | Erreurs |
| --- | --- | --- | --- |
| `kernel/state/status` | `{}` | `{"version","uptime_s","sessions","activity_detail","daemons":[{"name","unit","metrics","sample_age_s"?}]}` ; `metrics` vaut `enabled`, `disabled` ou `unreadable` | `bad_request` |
| `kernel/state/services` | `{}` | `{"services":[{"domain","greffon","target","catalog","available"}]}` ; `catalog` vaut `none`, `declaration` ou `pair` | `bad_request` |
| `kernel/state/metrics` | `{"daemon"}` (`pollux`, `pollux-session` ou `romulus`) | `{"daemon","available","samples":[{"name","labels","value"}]}` (500 échantillons au plus) | `bad_request`, `not_available` |
| `kernel/state/config` | `{"daemon"}` (même liste) | `{"daemon","options":[{"section","key","type","value","masked"}]}` | `bad_request`, `not_available` |
| `kernel/activity/list` | `limit` (1 à 200, 50 par défaut), `level` (1 à 3, 1 par défaut), `domain` (facultatif) | `{"detail","entries":[…],"truncated"}`, plus récentes d'abord | `bad_request`, `not_available` |

**Configuration masquée.** Seule une valeur de type `duree`, `limite`, `niveau`, `booleen` ou `uid` est publiée ; une valeur de type `texte`, `chemin` ou `compte` n'est publiée que si sa clé figure dans une liste blanche du code ; toute clé dont le nom contient `secret`, `passphrase`, `password`, `token`, `jeton`, `key` ou `cle` est masquée (`"value": null`, `"masked": true`).

**Journal d'activité.** Romulus tient un journal d'activité (fichier `activite.jsonl`, une ligne JSON ASCII de 2048 octets au plus par entrée), distinct du journal d'exploitation : il dit qui fait quoi. Niveau de détail `[romulus.activite] detail` :

| Niveau | Contenu |
| --- | --- |
| 1 | une entrée par requête d'administration traitée ou refusée : `ts`, `level`, `event` (`action`, `refusal`, `session_open`, `session_close`), `admin`, `session`, `domain`, `action`, `result` (`ok` ou un code du § 9) ; `domain` et `action` valent `null` pour une action inconnue (le chemin reçu n'est jamais recopié) ; `source` pour un refus sans session |
| 2 | ajoute `duration_ms`, `twin` (jumeau ou service qui a traité l'action) et `source` pour une session ; les appels à `kernel/activity/list` ne sont enregistrés qu'à ce niveau |
| 3 | ajoute, pour le dépannage, des entrées `protocol` (`request_id`, `step` `sent` ou `received`, `ok`, `code`, `bytes`, `http_status`, `peer_uid`) et `args` : paramètres explicitement marqués non secrets (`limit`, `level`, `domain`, `daemon` pour `kernel`) |

Jamais de `params`, de `data`, de jeton, de défi, de signature, de cookie, d'en-tête ni de chemin brut. Les refus sans session de même `result` et de même `source` sont regroupés par minute en une entrée portant `count` (plafonds `regroupement_max` et `regroupements_simultanes`). Le volume est borné par `taille_max` : le fichier courant est renommé en `activite.jsonl.1` quand il atteindrait la moitié de `taille_max`, les plus anciennes entrées disparaissant d'abord. Le journal d'activité est un journal circulaire d'exploitation, exempt de sauvegarde. La lecture ignore toute ligne tronquée ou hors forme.

**Privilèges (grammaire fixée, non appliquée).** Un privilège s'écrit `greffon::privilège:rôle`, de forme `^[a-z][a-z0-9-]*::[a-z][a-z0-9-]*:[a-z][a-z0-9-]*$`. La grammaire est fixée ici pour les greffons à venir ; aucune vérification n'existe dans le code et un seul super-administrateur existe.

## 6. lighttpd → Romulus

- HTTP/1.1 sur socket Unix (lighttpd `mod_proxy`), `POST /api/admin/<domaine>/<objet>/<opération>`, corps JSON = `params`, jeton en cookie `admin_token` (ou en-tête `X-Admin-Token`), `Origin` contrôlé. Sont routés les domaines des déclarations de services installées (avec les déclarations livrées : `bunker`, `legal`, `relay` et `nisaba`, ce dernier pour `state/status` et `state/verify` seulement) (§ 5), et le domaine `kernel`, servi par Romulus (§ 5.6).
- Ordre des contrôles (`server/romulus/http.py`, `_traiter`) : méthode (405 `bad_request`, en-tête `Allow: POST`) ; chemin (404 `unknown_action`) ; jeton (400 `bad_request` si plusieurs en-têtes `X-Admin-Token` ou plusieurs cookies `admin_token`, 400 `token_conflict`, 403 `token_missing` ou `token_unknown`) ; `Content-Length` invalide, doublé ou `Transfer-Encoding` présent (400 `bad_request`) ; taille (413 `body_too_large`) ; `Origin` (403 `origin_refused`) ; lecture du corps (400 si incomplet) ; `session` à la racine du corps (400 `bad_request`) ; action. Un corps absent vaut `{}`.
- `Origin` : un seul `Host` non vide et un seul `Origin`, qui contient `://` ; la partie après `://` est comparée à `Host` en minuscules ASCII (D111).
- Les erreurs HTTP ont la forme `{"ok":false,"error":{"code":"…"}}`, sans `detail`, avec `Connection: close`. Les réponses JSON de succès portent `Content-Type`, `Content-Length`, `Cache-Control: no-store`, `X-Content-Type-Options: nosniff` et `Connection: close`.
- Réponse : le même objet `{"ok": …}` qu'au § 3, sans `id`, sauf l'archive de `legal/journal/export` ci-dessous.
- Flux continus : `text/event-stream`. Exige `server.stream-response-body = 2` dans lighttpd (sinon la réponse est mise en tampon entière) et des délais HAProxy assez longs pour ce chemin ; à régler et vérifier à la configuration de lighttpd. Format (WHATWG HTML, § Server-sent events) :
  - Avant le premier événement, une erreur est une réponse JSON ordinaire avec le statut de la table du § 9 ; ensuite le statut est 200 (`Cache-Control: no-store`, `X-Content-Type-Options: nosniff`). Le client examine donc le type de contenu avant de lire un flux.
  - Un événement sans nom (`message`) par ligne de Remus, `data:` = l'objet `data` en JSON sur une seule ligne.
  - Événement nommé `end` (`data: {}`) : fin normale du suivi. Événement nommé `error` (`data: {"code":"…"}`, code de la table du § 9) : arrêt par erreur, puis fermeture de la connexion.
  - Ligne de commentaire `: heartbeat` pendant l'attente, sans événement.
  - Aucun champ `id:` ni `retry:`. Après `end` comme après `error`, Romulus ferme la connexion ; un client `EventSource` DOIT alors appeler `close()` dès qu'il reçoit `end` ou `error`, sinon le navigateur se reconnecte de lui-même (comportement normatif de WHATWG à la fermeture de la connexion) et ouvre un nouveau suivi, soit une nouvelle commande, sans que l'utilisateur l'ait demandé (D121).
  - Plafond de flux : `flux_max_simultanes` (8 par défaut) ; l'excédent reçoit 503 `command_busy` avant tout octet de flux. Le suivi s'arrête quand le feu repasse au rouge, quand la session se ferme ou quand le client se déconnecte (§ 4.3).
- Romulus sert plusieurs requêtes à la fois (bibliothèque standard : `http.server.ThreadingHTTPServer` ou `asyncio`) : un flux ouvert ne bloque jamais les autres commandes.

### 6.1 Livraison de l'archive de réquisition

Après les contrôles habituels de méthode, jeton et corps, Romulus prépare
entièrement l'archive dans un fichier temporaire anonyme, détruit à sa fermeture.
La taille et le SHA-256 sont calculés pendant l'écriture, sans charger l'archive
entière en mémoire. Un dépassement arrête la création et détruit le temporaire
avant la réponse JSON `export_too_large` (422). Toute erreur de préparation est
renvoyée en JSON avant l'envoi des en-têtes de succès.

En cas de succès, statut 200 et en-têtes :

```http
Content-Type: application/gzip
Content-Length: <nombre exact d'octets du corps>
Content-Disposition: attachment; filename="requisition-AAAAMMJJ-HHMMSS.tar.gz"
X-Paresia-Sha256: <SHA-256 du corps, 64 chiffres hexadécimaux minuscules>
Cache-Control: no-store
X-Content-Type-Options: nosniff
Connection: close
```

Romulus construit le nom exclusivement à partir de son horloge UTC au début de
la création. Il vérifie avant l'envoi la correspondance complète avec
`^requisition-[0-9]{8}-[0-9]{6}\.tar\.gz$`, sinon `internal_error`. Aucun nom,
chemin ou élément du client n'entre dans les en-têtes. Tous les en-têtes sont
contrôlés avant écriture : aucun caractère de contrôle, notamment CR ou LF.
Aucun cookie, `Content-Encoding` ni `Content-Digest` n'est émis.

Le fichier est envoyé par blocs de 65536 octets au plus. Une échéance totale
d'écriture de `timeout_s` couvre les en-têtes et le corps, sans remise à zéro
entre blocs. Si le client se déconnecte ou si l'envoi échoue, Romulus ferme la
connexion et libère le fichier et la place d'export ; il n'ajoute jamais une
réponse JSON à un corps binaire commencé. Une réception incomplète n'est pas
un succès pour l'application (contrôles ci-dessous).

Les options de type `limite` de `[romulus.http]` sont lues par `lire`, selon
les couches de configuration habituelles : `export_max_octets` = 8388608 par
défaut, plafond 16777216 (16 Mio) ; `export_max_simultanes` = 2 par défaut.
Cette dernière borne couvre l'exécution de l'action, la préparation et l'envoi.
Une demande excédentaire reçoit immédiatement `export_busy` (503).
Surcharges : `PARESIA_ROMULUS_HTTP_EXPORT_MAX_OCTETS` et
`PARESIA_ROMULUS_HTTP_EXPORT_MAX_SIMULTANES`. Les connexions restent également
bornées par `max_connexions`.

L'audit JSON sur stdout/journald émet `export_delivered` après l'envoi de
l'archive : `session`, `action`, `size` (octets), `sha256`, `count` (publications)
et `period` (deux dates ISO, bornes inclusives). Un échec d'une action d'export
enregistrée émet `export_failed` avec `session`, `action` et `code` ; un échec
d'envoi utilise `internal_error`. Ni critère, ni valeur recherchée, ni contenu,
ni jeton ne sont journalisés. Le résultat vide ne produit pas `export_delivered`.

**Contrat pour l'application** : envoyer un
POST avec le jeton ; distinguer `application/gzip` de `application/json`.
Pour le gzip, recalculer le SHA-256 des octets reçus et vérifier à la fois
`X-Paresia-Sha256` et `Content-Length` ; refuser l'archive si l'un manque,
est mal formé ou diffère. Utiliser le nom de `Content-Disposition` seulement
s'il respecte entièrement l'expression ci-dessus, sinon imposer un nom local
sûr. Afficher le SHA-256 comme « empreinte de l'archive ». Traiter le JSON
comme les autres réponses. La transmission sans modification ni recompression
par lighttpd et les délais HAProxy sont à régler et vérifier à l'installation.

**Contrat interne du producteur de `legal/*`** (mécanisme présent dans le code de Romulus, sans producteur enregistré ; la recherche et l'export seront assurés par Nisaba et la répartition définitive reste à fixer avec leur code) : le dictionnaire `FrontalHTTP.actions`, vide par
défaut, associe un nom d'action à une fonction `traiter(params, session)`.
Sans enregistrement, le statut reste 501 `not_available`. Une fonction retourne
un objet JSON de succès ou, uniquement pour `legal/journal/export`, un
`ExportBinaire(produire)`. Romulus appelle `produire(destination)` sous la limite
de concurrence ; la destination propose `write`, `tell`, `flush`, sans accès au
fichier ni possibilité de repositionnement. Le producteur écrit le gzip par
blocs, ferme son compresseur puis retourne
`{"count": entier_positif, "periode": (date_debut, date_fin)}` : deux objets
`datetime.date`, dans l'ordre. Ces métadonnées décrivent les publications
exportées et sont validées avant envoi. Il ne ferme pas la destination et
ne fournit aucun en-tête. Une `ErreurProtocole` peut signaler `bad_request`
ou `unknown_action` ; une autre exception produit `internal_error` sans détail
externe. L'aiguillage est construit à partir des déclarations de services (`server/romulus/__init__.py`, `aiguillage.py`) ; un service dont la section ou le socket manque n'a pas de route (501) ; aucune destination n'est encore raccordée pour `legal/*` (Nisaba n'assure pas encore la recherche ni l'export) : sans enregistrement, `legal/*` répond 501 `not_available`.

## 7. Secrets dans les messages

- Le jeton ne circule que dans la réponse de `presence/session/open` (§ 4.1, étape 4) et, dans l'autre sens, de l'application à Romulus par HTTPS. Il ne va jamais vers bunkerd, Castor ni Remus ; ceux-ci ne voient que le numéro de session.
- `bunker/relay-key/sign-mute-list` : `params` = `{"identity": "…", "passphrase": "…", "pubkeys": ["<64 hex>", …]}`. bunkerd construit lui-même l'événement kind 10000 (une étiquette `p` par clé, `created_at` = maintenant), le sérialise selon NIP-01 (`[0, pubkey, created_at, kind, tags, content]`, sans espace), le signe (BIP-340) et efface clé et passphrase. Il ne signe jamais un événement fourni par l'appelant.
- `relay/moderation/publish-mute-list` : `params` = `{"event": {…}}` signé ; Remus vérifie kind, auteur (clé publique du relais, configuration) et signature avant import.
- ncryptsec (`identity/add`, `identity/secret`) et passphrase : jamais renvoyés, jamais journalisés ; seule la liaison Romulus → bunkerd les porte.

## 8. Tests exigés

- Chaque démon : lignes malformées, objet non conforme, champ inconnu, action inconnue, `proto` incompatible, ligne trop longue ; aucun cas n'arrête le démon.
- Appelant non admis (`SO_PEERCRED`) : connexion fermée.
- Chaîne complète simulée sans SSH (sockets Unix locales à la place du tunnel), puis test d'intégration avec un sshd local (compte `tunnel`, redirection de sockets Unix) dans la CI. État : la chaîne simulée existe ; le test avec sshd est **couvert** par le job `banc` de `.github/workflows/ci.yml` (`docs/developpement.md`, § 5.2) : deux conteneurs avec systemd et sshd réels, tunnel de production, étapes E0 à E6 (présence, aiguillage, feu de Castor, fermeture, silence, révocation du jeton) observées. Le banc ne couvre pas les essais négatifs d'isolation entre comptes ni le refus des connexions TCP sortantes du compte `tunnel`.
- Feu rouge : commande refusée après `wait_s` ; feu repassé au rouge sans ping après `green_s` ; feu rouge immédiat sur `castor/light/close` ; feux de deux sessions indépendants.
- Flux continu maintenu au-delà de `green_s` sans nouvelle commande, arrêté à la fermeture de session.
- Corrélation : chaque réponse porte l'`id` de sa requête ; `session` dans `params` refusé.

## 9. Codes d'erreur

`proto` accepte uniquement `jumeaux/<entier>` (chiffres ASCII décimaux,
non signés, sans suffixe). Une majeure différente est refusée avant le contrôle
des champs de l'enveloppe ; un identifiant invalide reste un `bad_request` à id nul.

Configuration en couches (D29, `docs/configuration.md`), par priorité croissante :
`/etc/paresia/paresia.conf`, `/etc/paresia/conf.d/NN-*.conf`, pour les seuls programmes
lancés par un utilisateur `$XDG_CONFIG_HOME/paresia/*.conf`, puis les variables
`PARESIA_<COMPOSANT>_<DOMAINE>_<CLE>`. Les démons n'ont pas de couche utilisateur ;
l'environnement d'un démon est fixé par son unité et est de confiance. `pollux-session`
ne lit aucune variable d'environnement. Chaque fichier et dossier lu doit être régulier
(ou un dossier réel), appartenir à root ou à l'uid effectif et ne pas être modifiable par
le groupe ni les autres ; l'ouverture refuse les liens symboliques (`O_NOFOLLOW`), un fichier
fait au plus 1 Mio et un dossier compte au plus 64 fichiers.

Limites du socle : `max_line` et les options de type `limite` sont compris
entre 1 et 16 Mio ; les délais sont strictement positifs et au plus de 3600 s.
Le serveur accepte `max_connexions` (64 par défaut dans le socle, de 1 à 1024 ;
16 par défaut pour Remus et pour la socket d'administration de bunkerd), ferme sans
réponse les connexions excédentaires et journalise `connection_limit`.
Une échéance totale borne la lecture de chaque requête et l'envoi de sa réponse,
sans remise à zéro à chaque octet ; le traitement métier doit lui aussi respecter
son délai. Le client accepte `uid_serveur` facultatif : lorsqu'il est fourni,
`SO_PEERCRED` est vérifié avant d'envoyer la requête (les appelants internes le fournissent tous, § 1).
Les catégories Unicode Cc, Cf, Zl, Zp, Cs et Co sont remplacées par U+FFFD
pour l'affichage des détails et les journaux.

Les codes sont stables et traduits par les catalogues `i18n/fr-FR.json` et
`i18n/en-US.json`. Le détail technique facultatif reste court, fixe, en anglais,
sans donnée reçue ni secret. « — » signifie qu'aucun statut HTTP n'est défini
pour ce code.

| Code | Signification | Statut HTTP associé |
| --- | --- | --- |
| `bad_request` | Ligne ou enveloppe non conforme ; méthode HTTP autre que POST | 400 ; 405 pour une méthode autre que POST |
| `unknown_action` | Action inconnue ou non admise par le démon | 404 |
| `internal_error` | Échec interne du traitement | 500 |
| `peer_unavailable` | Pair injoignable, connexion rompue ou délai dépassé | 503 |
| `token_missing` | Jeton absent | 403 |
| `token_unknown` | Jeton inconnu | 403 |
| `token_conflict` | Jetons du cookie et de l'en-tête différents | 400 |
| `origin_refused` | Origine de la requête refusée : `Origin` absent, multiple ou différent de `Host` | 403 |
| `body_too_large` | Corps HTTP dépassant la limite configurée | 413 |
| `export_too_large` | Archive dépassant la taille maximale pendant sa création | 422 |
| `export_busy` | Limite d'exports simultanés atteinte | 503 |
| `command_failed` | Commande du relais échouée | 502 |
| `command_timeout` | Délai de la commande du relais dépassé | 504 |
| `command_busy` | Trop de commandes simultanées | 503 |
| `not_available` | Opération connue mais non disponible | 501 |
| `session_limit` | Nombre maximal de sessions atteint | — |
| `challenge_required` | Défi absent ou deuxième demande de défi ; fermeture après réponse | — |
| `challenge_expired` | Défi expiré ; fermeture après réponse | — |
| `signature_invalid` | Preuve SSHSIG refusée ; fermeture après réponse | — |
| `auth_info_unavailable` | Informations d'authentification absentes ou ambiguës | — |
| `line_too_long` | Ligne dépassant la limite ; fermeture de la connexion | — |
| `protocol_version_mismatch` | Version majeure incompatible ; fermeture de la connexion | — |
| `session_closed` | Session déjà fermée | 403 |
| `relay_light_red` | Feu de la session au rouge | 503 |
| `invalid_identity` | Nom d'identité hors format (bunkerd) | 422 |
| `unknown_identity` | Identité inexistante (bunkerd) | 404 |
| `identity_exists` | Identité déjà existante (bunkerd) | 409 |
| `identity_unlocked` | Opération refusée : identité déverrouillée (bunkerd) | 409 |
| `invalid_relays` | Liste de relais non conforme (bunkerd) | 422 |
| `invalid_ncryptsec` | ncryptsec non conforme (bunkerd) | 422 |
| `invalid_client` | Clé de client non conforme (bunkerd) | 422 |
| `client_not_authorized` | Client absent des clients autorisés (bunkerd) | 404 |
| `invalid_timeout` | Délai d'inactivité hors de 1 à 1440 minutes (bunkerd) | 422 |
| `confirmation_mismatch` | Confirmation de suppression différente du nom (bunkerd) | 422 |
| `relay_identity_protected` | Suppression refusée : identité désignée par `relay_identity` (socket d'administration seulement ; bunkerd) | 409 |
| `not_relay_key` | Signature demandée pour une identité autre que `relay_identity` (bunkerd) | 422 |
| `bad_passphrase` | Phrase secrète fausse ou secret chiffré altéré (y compris erreur de format du `ncryptsec`) ; réponse retardée de 2 s (bunkerd) | 422 |
| `invalid_pubkeys` | Liste de clés publiques non conforme (bunkerd) | 422 |
| `invalid_passphrase` | Phrase secrète absente, vide ou non codable (bunkerd) | 422 |
| `pubkey_mismatch` | Clé publique dérivée différente de la clé connue, ou clé connue absente (bunkerd) | 409 |
| `log_n_too_high` | Coût de dérivation (`log_n`) du secret chiffré supérieur au plafond de `[bunkerd.signature]` (bunkerd) | 422 |

## Suivi des versions

Historique des modifications : `CHANGELOG.md`. Le protocole `jumeaux/1` n'a pas changé de majeure.
