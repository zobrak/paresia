# Cahier des charges — administration par présence

Paresia (Paresia-server, Paresia-admin) · version du document : 0.1.16 · 2026-11-08 · public : développeur
En cas d'écart entre ce fichier et un autre document, ce fichier fait foi ; toute modification passe par le mainteneur.

Conventions de lecture (RFC 2119 et RFC 8174) : les mots DOIT, NE DOIT PAS, DEVRAIT, NE DEVRAIT PAS et PEUT, en capitales, s'interprètent comme le décrivent la RFC 2119 et la RFC 8174. Les autres occurrences ont leur sens courant. Le caractère normatif des formulations en minuscules n'est pas reclassé ici : il reste à trancher par le mainteneur.

## Objet et principes

L'administration du bunker (bunkerd, backend-admin) et du relais (strfry, backend-relais) s'ajoute à l'interface web existante, derrière un robinet fermé par défaut : il ne s'ouvre que pendant une session SSH de l'application vers backend-admin, et seulement pour elle.

**Ne change pas** : verrouillage, déverrouillage, affichage de l'URI et du QR code (page bunker.example.org, bunkerd 1.9.0). L'applet de barre des tâches, qui s'appuie sur les routes de cette page, est retirée à la mise à jour de la page publique (D172).

**S'ajoute** : l'administration des identités de bunkerd, l'administration du relais (reprise des fonctions de paresia-admin) et la consultation du journal légal, servies par bunker.example.org lui-même, sous /admin/.

Principes :

1. **Robinet fermé par défaut.** Sans session de présence ouverte, toute commande d'administration est refusée, quelle que soit sa provenance.
2. **Présence prouvée par une clé SSH.** L'application ouvre une session SSH vers backend-admin, et seulement vers backend-admin, avec la clé de son administrateur, détenue par un agent SSH (par exemple servi par un gestionnaire de mots de passe). Aucun mot de passe d'administration.
3. **Jeton de session.** À l'ouverture de la présence, l'application reçoit par la session SSH un jeton aléatoire. Chaque commande d'administration le porte ; sans lui, refus. Plusieurs sessions simultanées sont possibles, chacune avec son jeton.
4. **Un seul point de contact.** Le frontend ne parle qu'à backend-admin. Le relais n'est joint que par backend-admin, à travers un tunnel SSH, et n'ouvre son robinet que sur attestation de backend-admin.
5. **Fermeture automatique.** Fin de la session SSH (déconnexion, veille, coupure réseau) = jeton détruit, robinets refermés.
6. **Liste fermée d'opérations.** Chaque démon n'exécute que les opérations prévues ici, arguments vérifiés ; jamais de commande libre.
7. **Aucun secret dans les journaux**, aucun secret en argument de commande.
8. **Outils standard réutilisés, non réécrits.** Quand un outil standard et éprouvé fait le travail, Paresia l'emploie au lieu de le réimplémenter ; pour la sauvegarde des données d'état (profils du bunker, base de strfry, journal légal), l'outil est BorgBackup. Les dépendances restent soumises à la règle de licence (AGPL-3.0-or-later, `docs/licences-tierces.md`).

## Architecture

Deux paires de jumeaux, une sur chaque machine, qui se répondent par un seul tunnel SSH : les démons **Romulus** (backend-admin) et **Remus** (backend-relais), les présences **Pollux** (backend-admin) et **Castor** (backend-relais).

```
              backend-relais                                        backend-admin
                                                 HTTPS        lighttpd
 strfry ◄── remus ◄════════ tunnel SSH ════════► romulus ◄───────────── (HAProxy) ◄── app
              ▲                                   │   │
              │ robinet                           │   └──► bunkerd (socket d'administration)
              │                                   │   └──► nisaba (socket) + copie du journal (lecture seule)
           castor ◄═══════ même tunnel ══════════► pollux ◄── SSH app@backend-admin ◄────── app
```

| Composant | Machine | Rôle |
| --- | --- | --- |
| Romulus | backend-admin | reçoit toutes les commandes d'administration de lighttpd ; émet et vérifie les jetons ; si la session de présence est ouverte, aiguille vers bunkerd, Nisaba (journal légal) ou Remus |
| Pollux | backend-admin | carrefour et feu de circulation : tant que la session SSH de l'administrateur est vivante, laisse passer le jeton de Romulus vers l'application et les pings de Romulus vers Castor |
| Remus | backend-relais | exécute dans strfry, sous `chef`, les opérations du relais, uniquement quand le feu de Castor est au vert pour la session de la commande ; n'écoute que Romulus |
| Castor | backend-relais | carrefour et feu de circulation du relais : un feu par session : vert à chaque ping de Pollux, rouge 35 s après le dernier ping ou dès la fermeture de la session ; n'écoute que Pollux |
| bunkerd | backend-admin | bunker NIP-46 ; sa socket d'administration n'est accessible qu'à Romulus |
| Nisaba | backend-admin | processus annexe qui reprend les fonctions des anciens scripts `journal-legal-*` : copie du journal légal depuis backend-relais, scellement, droits et purge ; répond à Romulus par socket Unix pour la consultation du journal légal : recherche, export, état, vérification (D87, D88 ; livrés : état et vérification) |

Le seul nouveau flux réseau est backend-admin → backend-relais en SSH (port 22), qui porte le tunnel. L'application ne se connecte plus en SSH à backend-relais.

Comptes et emplacements sur backend-admin (D21) : compte système de Romulus `paresia-romulus` ; code serveur installé sous `/usr/local/lib/paresia` (`/usr` pour le code, `/var` pour ce qui varie).

## Session de présence (Pollux)

Une session SSH de l'application vers backend-admin ouvre le robinet de Romulus pour un jeton ; sa fin le referme. Pollux reste simple : il constate la présence et laisse passer.

**Compte et clés**

- Un compte `app` sur backend-admin, sans mot de passe, sans droit `sudo`. Plus de compte `app` sur backend-relais. Le compte `app` ne sert qu'à `pollux-session` : aucun autre service, cron ni shell utile (D20, point a).
- Une clé SSH par administrateur, de son choix : l'administrateur charge sa clé publique dans l'application ; elle est installée côté serveur, nommée (commentaire de la clé = nom de l'administrateur). Aujourd'hui un administrateur root l'installe ; la gestion des utilisateurs (D123, D126, section « Utilisateurs, privilèges et plugins ») la rend caduque : Romulus tient les clés autorisées. La partie privée est détenue par un agent SSH, par exemple servi par un gestionnaire de mots de passe (cité à titre d'exemple ; D67). Retirer un accès = retirer sa ligne.
- `authorized_keys` du compte : `restrict,command="/usr/local/bin/pollux-session" ssh-ed25519 AAAA… <administrateur>`. `restrict` interdit terminal, redirections et transferts ; la commande forcée empêche tout autre usage de la clé.
- sshd : `ClientAliveInterval 15` et `ClientAliveCountMax 3`, pour qu'une session morte soit fermée en 45 s au plus ; `ExposeAuthInfo yes` (bloc `Match User app`) : `pollux-session` lit la clé utilisée dans le fichier `SSH_USER_AUTH`, la retrouve dans `authorized_keys` et en tire le nom de l'administrateur (commentaire), transmis à Pollux avec l'adresse source (`SSH_CONNECTION`).

**Déroulement**

1. L'application ouvre `ssh -T app@backend-admin` ; sshd lance `pollux-session`, qui se branche sur Pollux (socket accessible au seul compte `app`) ; l'application envoie `presence/session/open`.
2. Pollux signale la nouvelle session à Romulus.
3. Romulus crée un jeton de 32 octets aléatoires (`secrets.token_hex`) et un numéro de session, et les confie à Pollux, qui les fait passer à `pollux-session`.
4. `pollux-session` écrit la réponse sur sa sortie : l'application lit le jeton dans la session SSH. À l'aller, il ne transite par aucun autre chemin.
5. L'application renvoie le jeton avec chaque commande, via lighttpd ; Romulus le compare à ceux qu'il a émis.
6. Fin de session SSH → `pollux-session` se termine → Pollux le signale à Romulus, qui détruit le jeton. Toute commande portant ce jeton est dès lors refusée.

Messages, champs et codes d'erreur : `docs/protocole.md` (NDJSON, protocole `jumeaux/1`).

**Usage du jeton**

- L'application le dépose dans sa vue web sous forme de cookie (`admin_token`, avec HttpOnly, Secure et SameSite=Strict) ; à défaut, il peut être envoyé dans l'en-tête HTTP `X-Admin-Token`.
- Romulus le compare en temps constant (`hmac.compare_digest`) aux jetons des sessions ouvertes ; absent ou inconnu → refus (403).
- Il n'est jamais écrit sur disque ni dans un journal ; le journal d'audit désigne la session par un numéro.
- Un seul jeton par session : il couvre le bunker, le relais et le journal légal.

**Battement application ↔ Pollux**

1. Toutes les 30 s, l'application envoie `presence/session/ping` dans la session SSH ; `pollux-session` le relaie à Pollux, qui répond.
2. Pollux : sans ping d'une session depuis 90 s, il la ferme et le signale à Romulus, qui détruit le jeton.
3. `pollux-session` : sans ping de l'application ou sans réponse de Pollux depuis 90 s, il se termine, ce qui ferme la session SSH.
4. Application : sans réponse depuis 90 s, elle tient la session pour perdue, efface le cookie, l'indique et propose de la rouvrir.

Les deux délais (30 s, 90 s) sont réglables.

Codes de sortie de `pollux-session` (D6, complété par D18) : 0 fin normale de l'entrée standard ; 1 délai dépassé ; 2 Pollux injoignable ; 3 erreur de protocole, de transport ou d'authentification, y compris la fermeture par Pollux alors qu'une requête attend sa réponse (cas de panne : Pollux répond toujours avant de fermer).

**Points à spécifier avant mise en service**

- Verrou global de Pollux (D19) : les échanges avec Romulus et Castor sortent du verrou global, sans s'écarter de l'architecture ci-dessus. Si une coordination nouvelle est nécessaire et que Romulus ne peut pas s'en charger, aucun composant Mozart n'est créé (D27) : la coordination reste interne à Pollux (état et verrou par session).
- Preuve par signature à l'ouverture de session (D20, point c) : défi aléatoire signé sur le poste client avec la clé de l'administrateur, vérifié par Pollux avec la clé publique enregistrée. Spécifié dans `docs/protocole.md` § 4.1 et réalisé côté serveur (SSHSIG, espace de noms `paresia-presence`, défi de 60 s, un essai par connexion ; codes `challenge_required`, `challenge_expired`, `signature_invalid`) ; l'étape correspondante du client reste à écrire.

## Romulus : point de contact et aiguillage

Romulus reçoit de lighttpd toutes les commandes d'administration sur une socket Unix. Il émet les jetons (voir la session de présence), vérifie celui de chaque commande, puis aiguille :

| Chemin | Destination |
| --- | --- |
| `POST /api/admin/bunker/<opération>` | socket d'administration de bunkerd |
| `POST /api/admin/legal/<opération>` | consultation du journal légal (recherche, export, état, vérification) : Romulus route vers Nisaba, par socket Unix (D88) ; état et vérification livrés, recherche, export et routage de `legal/*` à faire (501 aujourd'hui) |
| `POST /api/admin/relay/<opération>` | Remus, par le tunnel, après ouverture du robinet de Castor |

- Corps JSON, en-tête `Origin` contrôlé comme aujourd'hui : un seul `Host`, un seul `Origin`, partie de `Origin` après `://` égale à `Host`, sinon refus 403 `origin_refused` (D15, D100). Réponse JSON `{"ok": true|false, …}` avec des codes d'erreur stables, chacun associé à un statut HTTP (RFC 9110 : 422 valeurs refusées par bunkerd, 404 identité ou client inconnu, 409 conflit d'état, 502 commande échouée, 503 relais ou commande indisponible, 504 délai dépassé ; table au § 9 de `docs/protocole.md`) (D100).
- Pour chaque commande destinée au relais, l'ordre « commande à Remus, puis ping de la session à Pollux » est tenu sans second fil d'exécution (D100).
- Romulus vérifie le format de chaque opération avant de la transmettre ; les démons de destination le vérifient à nouveau.
- Romulus sert plusieurs requêtes à la fois (bibliothèque standard : `ThreadingHTTPServer` ou `asyncio`) : un suivi en direct ouvert ne bloque aucune autre commande.
- Suivi en direct (7) en flux d'événements HTTP : lighttpd doit transmettre sans tampon (`server.stream-response-body = 2`) et HAProxy garder la connexion ouverte assez longtemps ; réglages vérifiés dans la tâche lighttpd.

**Commande destinée au relais**

1. Romulus envoie la commande à Remus par le tunnel ; Remus la met en attente.
2. Romulus envoie ensuite un ping à Pollux pour la session de la commande ; si cette session est ouverte, Pollux le fait passer à Castor par le tunnel, sinon il refuse.
3. Le feu de Castor passe au vert pour cette session ; Remus exécute la commande en attente et renvoie le résultat à Romulus.
4. Le feu reste vert 35 s après le dernier ping (battement de 30 s + marge de 5 s, réglables), puis repasse au rouge. Romulus renouvelle le ping au plus une fois par battement tant que des commandes arrivent pour cette session.
5. Une commande en attente dont le feu ne passe pas au vert dans les 5 s (réglable) est refusée.
6. Suivi en direct (7) : tant que le flux est ouvert, Romulus renouvelle le ping de sa session à chaque battement, même sans nouvelle commande ; le flux s'arrête quand le feu repasse au rouge, quand la session se ferme ou quand le client se déconnecte.
7. Fermeture de session : Pollux prévient Romulus et Castor ; le feu de cette session repasse au rouge immédiatement, sans attendre l'expiration. Les commandes en attente et les flux de cette session sont refusés ou arrêtés ; une opération déjà en cours d'exécution dans strfry va à son terme (l'interrompre au milieu, une suppression par exemple, serait pire) et son résultat est journalisé.

## Administration de bunkerd

bunkerd n'exécute que les opérations ci-dessous, reçues de Romulus sur sa socket d'administration (accessible au seul compte de Romulus, par ACL). Il ne connaît ni jeton ni présence : c'est Romulus qui filtre.

| Opération | Paramètres | Condition |
| --- | --- | --- |
| `list` | — | — |
| `clients` | identité | — |
| `add` | identité, ncryptsec, relais, délai | identité nouvelle |
| `secret` | identité, nouveau ncryptsec | identité verrouillée |
| `relays` | identité, relais (1 à 10) | identité verrouillée |
| `authorize` | identité, clé client (npub ou hex) | identité verrouillée |
| `revoke` | identité, clé client | identité verrouillée |
| `timeout` | identité, minutes (1 à 1440) | — |
| `remove` | identité, confirmation = nom de l'identité | identité verrouillée |
| `sign` | identité de relais, passphrase du nœud, clés à mettre en sourdine | — |

- `list` renvoie pour chaque identité : nom, état, temps restant, clé publique, relais, nombre de clients, délai.
- Les contrôles de format sont ceux de bunkerctl (nom `a-z0-9_-` sur 32 caractères, relais `wss://` (`ws://` admis seulement pour un hôte `.onion`), ncryptsec, clé de 64 caractères hexadécimaux).
- Un ncryptsec reçu n'est jamais renvoyé ni journalisé.
- bunkerctl reste disponible en root sur backend-admin, inchangé.

**Signature pour le relais (menu 63)**

- La clé privée du relais est une identité du bunker, désignée comme « clé de relais » par la configuration de bunkerd (`relay_identity`, posée par l'administrateur root) ; son ncryptsec est gardé par bunkerd comme les autres.
- `sign` : l'administrateur envoie la passphrase du nœud et la liste des clés à mettre en sourdine ; bunkerd construit lui-même l'événement kind 10000, le sérialise selon NIP-01, déchiffre le ncryptsec (NIP-49), signe (BIP-340), efface clé et passphrase de la mémoire et renvoie l'événement signé. Rien n'est conservé.
- bunkerd ne signe jamais un événement fourni par l'appelant : seul le kind 10000, construit par lui, est signé par ce chemin.
- Remus, opération de publication (63) : reçoit l'événement signé, vérifie le kind, l'auteur (clé publique du relais, lue dans sa configuration) et la signature BIP-340, puis l'importe dans strfry.
- La saisie de la clé privée en clair (menu 63 actuel) disparaît ; le module sans trace de paresia-admin 2.6.0 (NIP-49, BIP-340) sert de base.

## Journal légal

Tout ce qui concerne le journal légal reste sur backend-admin. Plus de scripts épars : la copie, le scellement, les droits et la purge sont repris par **Nisaba**, processus annexe dédié (D87). Les anciens scripts `journal-legal-pull`, `-seal` et `-acl` sont unifiés dans Nisaba  ; le service journal-legal n'est donc plus « inchangé » ni conservé tel quel. D87 remplace D71 pour la fourniture des messages `ECHEC_*`.

- **Nisaba** (D87, D88) : privilèges `CAP_LINUX_IMMUTABLE` et accès SSH au relais (unité `User=root` bornée à cette capacité) ; planification interne avec rattrapage au démarrage, sans minuteries ; socket Unix de groupe `paresia-nisaba` ; domaine `nisaba` des actions du protocole ; code d'échec `ECHEC_PURGE` en plus des codes `ECHEC_*` existants. Étiquette journald unique `nisaba`, codes `ECHEC_*` inchangés (D89) : les alertes fondées sur journald sont à adapter à la migration. Les lignes de trace de la vérification et du contrôle des droits (`acl check|apply`, `verify`) sont un format de données stable de la preuve, repris des scripts, non traduit (D111 ; `docs/protocole.md` § 5.2). Le contrôle des droits ne tente pas de lecture effective : celle-ci est faite par Romulus sous son propre compte, sans privilège supplémentaire pour Nisaba.
- **La consultation du journal légal est confiée à Nisaba** : rechercher (50), exporter pour réquisition (51), état (52) et vérification du manifeste (53) sont des actions de Nisaba, sans lecture de journald (D87, D88 ; D22 complétée, consigne du propriétaire du 2026-11-08). Romulus ne fait que router les actions `legal/*` vers Nisaba par la socket Unix, selon une déclaration de service ; il ne lit pas le journal légal. **Livré** : état et vérification (`nisaba/state/status`, `nisaba/state/verify`, `docs/protocole.md` § 5.2). **Reste à faire** : recherche et export dans Nisaba, et le routage de `legal/*` par Romulus (aujourd'hui, 501 `not_available`).
- **Export (51)** : archive binaire `application/gzip` nommée `requisition-AAAAMMJJ-HHMMSS.tar.gz`, avec l'en-tête `X-Paresia-Sha256` ; 8 Mio par défaut (plafond 16 Mio), `export_too_large` (422), `export_busy` (503) ; rien à exporter : `count` à 0 (D25, D37). Contenu : `extraction.jsonl`, `preuves.txt`, `seals/<D>.txt` et `.ots`, `SHA256SUMS` (contenu de paresia-admin 2.6.0), plus les fichiers `MANIFEST` des jours concernés, nécessaires à la vérification des sceaux (D76). Romulus possède le fichier, calcule taille et SHA-256 et fixe le nom ; le producteur ne rend que `{count, periode}` ; options `export_max_octets` et `export_max_simultanes` (2) dans `[romulus.http]` (D92 ; `docs/protocole.md` § 6.1). Le partage exact de la livraison de l'archive entre Nisaba (qui produit) et Romulus (qui route et livre sur HTTP) reste à fixer avec le code de `legal/journal/export` ; les contraintes de format ci-dessus restent celles de l'interface.
- Nisaba fixe explicitement modes et ACL (D22) : ACL de lecture pour `paresia-romulus`, même méthode que `journalpull` sur backend-relais, sans groupe. Cette ACL date du temps où Romulus lisait la copie ; la consultation étant confiée à Nisaba, Romulus n'a plus besoin de ce droit (à retirer avec le code).
- Les inscriptions liées à la modération (bannissements, levées de ban, suppressions) continuent comme aujourd'hui ; Remus les écrit là où paresia-admin 2.6.0 les écrit.

## Remus et Castor sur backend-relais

Remus est le démon d'administration du relais : il n'écoute que Romulus, n'exécute que les opérations ci-dessous et seulement quand le feu de Castor est au vert pour la session de la commande.

**Castor**

- Carrefour et feu de circulation : n'écoute que Pollux ; un feu par session de présence (plusieurs administrateurs simultanés ne partagent pas le même feu).
- Chaque ping passe le feu de sa session au vert pour 35 s (battement de 30 s + marge de 5 s, réglables) ; sans nouveau ping dans ce délai, ou à l'annonce de la fermeture de la session par Pollux, il repasse au rouge.
- Feu rouge : Remus refuse les commandes de cette session, en attente ou nouvelles, et arrête ses flux ; une opération déjà en cours va à son terme.
- Donne l'état du feu à Remus par une socket Unix locale accessible à eux seuls.

**Droits de Remus**

- Remus tourne sous le compte `chef`, hors groupe `docker` (ce groupe équivaut à root).
- `sudo` sans mot de passe sur les commandes `docker` des opérations, écrites en entier dans sudoers (par exemple `docker exec strfry /app/strfry …`, `docker restart strfry`) ; liste exacte établie et vérifiée (`sudoers(5)`) dans la tâche.
- Sudoers produit par un générateur (D80, D96) : seuls les gabarits `Hexadecimal`, `Choix` et `Entier` sont traduits ; une règle exacte par valeur de `Choix` ; une expression régulière d'arguments `^…$` sans espace pour `Hexadecimal` et `Entier` ; aucun joker, aucun élément fixe contenant un espace, aucun programme intermédiaire setuid. Verbes limités à `exec` et `restart` (extension prévue, en citant `sudoers(5)`). **sudo 1.9.10 au moins** (expressions régulières d'arguments, `sudoers(5)`). La vérification `nft -c -f` exige root : elle est faite par l'administrateur sur backend-relais, à l'étape nftables de la procédure (D98). Remus : `KillMode=mixed` (D81). `chef` est limité aux seules commandes nécessaires pour administrer strfry : un `docker` sans restriction permettrait de monter la racine de backend-relais dans un conteneur, donc d'être root.
- Après `docker exec strfry`, les options appartiennent à la commande lancée dans le conteneur et non à `docker` (`SetInterspersed(false)` dans le code de docker/cli) : un motif `docker exec strfry /app/strfry *` ne permet pas d'ajouter d'options à `docker`.
- Le mot de passe de `user` (administrateur complet de backend-relais) n'est écrit nulle part.

**Opérations** (numéros des menus actuels de paresia-admin)

| Domaine | Opérations |
| --- | --- |
| État | statut du conteneur (1), métriques (2), test NIP-11 (3), dernières lignes du journal (4), avertissements et erreurs (5), connexions par IP (6), suivi en direct (7) |
| Événements | compter par filtre (10), répartition par kind (11), lister (12), afficher par identifiant (13), supprimer par filtre (14), supprimer par âge (15) |
| Sauvegardes | exporter (20), importer (21), lister les sauvegardes (22) |
| Synchronisation | télécharger depuis un relais (30), comparer (31), arbres negentropy (32) |
| Conteneur | redémarrer (40), arrêter (41), démarrer (42), afficher la configuration (43), compacter la base (44) |
| Modération | signalements (60), bannissements : bannir, lever, importer une liste (61), journal de modération (62), liste de sourdine publiée (63) |

- Les filtres d'événements restent guidés (kinds par numéro, auteur, dates), jamais un filtre JSON libre transmis tel quel à strfry.
- Les opérations destructrices (14, 15, 21, 41, bannir, lever un ban) exigent une confirmation dans l'application et sont inscrites au journal d'audit ; les bannissements et suppressions liées sont inscrits au journal légal, comme aujourd'hui.
- Les outils de clés (menus 70 à 73) restent locaux à l'application : aucun secret ne part vers un serveur.

**Relais et bitchat (D95, D99)**

- Objectif du relais : servir l'application bitchat. C'est un objectif à évaluer, non une règle absolue : toute décision sur le relais pèse bitchat, les autres clients, la confidentialité et les standards Nostr (NIP).
- Le `strfry.conf` est livré complet (`deploy/backend-relais/strfry/strfry.conf`), toutes les valeurs écrites explicitement : `relay.auth.restrictedReadKinds = "4"` (le défaut amont `"4, 1059"` bloquerait bitchat, qui ne gère pas NIP-42 ; ses messages privés sont des kind 1059), `restrictReadToInvolvedPubkey = true`, `rejectEventsNewerThanSeconds = 1800` (dates des kind 1059 de bitchat iOS décalées de ±900 s), `filterValidation.requireAuthorOrTag` non activé (filtres `#g`, `#r`, `#x`) (D95, qui remplace D94).
- Plugin `writePolicy` du journal légal en Python (`python3` ajouté à l'image de strfry, sans `jq` ni sous-processus) (D99). Le kind 20000 (canaux géographiques de bitchat) reste journalisé ; le chemin rapide ne vise que les kinds non journalisés (20001, présence, autres éphémères non journalisés). Le plugin livré échappe en `\uXXXX` les caractères C1, DEL, U+2028 et U+2029 de la ligne de journal, et accepte la publication même si l'écriture du journal échoue (la ligne complète va alors à journald) (D110). L'adresse de connexion n'étant pas validée par le plugin, le proxy DOIT écraser l'en-tête d'adresse et le port de strfry n'est publié que vers lui (D110). Reste à faire, par l'administrateur : essai de charge et contrôle de la poignée de main WebSocket au proxy (D95).
- Liste noire du plugin illisible au démarrage, aucune liste encore lue : le relais accepte les écritures et journalise une alerte, pour maintenir le service de bitchat (D119). Négentropie : avec strfry 4cd3cf6, `NEG-OPEN` ne laisse fuir aucun kind 4 ou 1059 tant qu'aucun arbre negentropy prédéfini n'existe ; les fichiers livrés n'en créent jamais (`strfry negentropy add` et `build` ne sont jamais lancés) et `REQ` reste la voie de lecture (D120).

## Réseau, lighttpd et tunnel SSH

L'administration passe par bunker.example.org lui-même, sans nouveau nom ni règle HAProxy ; un seul tunnel SSH permanent relie backend-admin à backend-relais et porte les deux paires, chacune sur sa socket.

**HAProxy (pare-feu)**

- Aucun ajout : même nom bunker.example.org, même filtrage par source (`198.51.100.0/24`, `192.0.2.111`, `192.0.2.112`), même pool vers lighttpd (`192.0.2.50:7780`), `X-Forwarded-For` remplacé par l'adresse du client.
- `Access-Control-Allow-Origin: *` ne doit plus s'appliquer à bunker.example.org.

**lighttpd (backend-admin)**

| Chemin sur bunker.example.org | Destination |
| --- | --- |
| `/admin/` | pages statiques de l'interface d'administration |
| `/api/admin/*` | Romulus, socket Unix (accès `www-data` par ACL) |
| autres chemins | page publique actuelle, inchangée |

- L'accès reste réservé à HAProxy (`192.0.2.254`).
- Le jeton n'apparaît dans aucun journal de lighttpd (pas d'en-têtes ni de cookies journalisés).

**Tunnel SSH backend-admin → backend-relais**

- Service systemd `paresia-tunnel` sur backend-admin, sous un compte dédié : une connexion `ssh -N` vers `tunnel@backend-relais` avec deux redirections de sockets Unix, `/run/paresia-tunnel/romulus/remus.sock` vers la socket de Remus sur backend-relais et `/run/paresia-tunnel/pollux/castor.sock` vers celle de Castor ; options `StreamLocalBindUnlink=yes` (une socket restée d'une connexion précédente n'empêche pas la reconnexion) et `ExitOnForwardFailure=yes` ; relancé automatiquement, avec `ServerAliveInterval 15`.
- Sur backend-admin, chaque dossier n'est traversable que par son démon, par propriétaire, groupe et mode posés par `tmpfiles.d` (D152, qui révise D62) : `/run/paresia-tunnel` en `root:root` 0711, `romulus` en `paresia-tunnel:paresia-romulus` 0710, `pollux` en `paresia-tunnel:paresia-pollux` 0710, sans ACL. Romulus ne joint que Remus, Pollux ne joint que Castor.
- Sur backend-relais, sshd ouvre les sockets distantes sous l'identité du compte `tunnel` : les sockets de Remus et de Castor ne sont accessibles qu'à ce compte, et chaque démon vérifie l'appelant (`SO_PEERCRED`, uid de `tunnel`). Rien n'écoute sur le réseau ni sur la boucle locale.
- Compte `tunnel` sur backend-relais : `authorized_keys` `restrict,port-forwarding,from="192.0.2.50",command="/bin/false"` suivi de la clé ; dans `sshd_config`, bloc `Match User tunnel` avec `AllowTcpForwarding local`, `AllowStreamLocalForwarding local`, `PermitListen none`, `PermitTTY no`, `X11Forwarding no`, `AllowAgentForwarding no`.
- Limite d'OpenSSH (code source de sshd, `channels.c`, `session.c`) : la redirection de sockets Unix partage l'autorisation des redirections TCP locales, et `permitopen` n'accepte pas de chemin de socket. La clé `tunnel` pourrait donc aussi ouvrir des connexions TCP depuis backend-relais. Une règle nftables sur backend-relais l'interdit : `meta skuid "tunnel" ct state new reject` dans la chaîne `output`.
- Fonctionnement vérifié le 2026-11-05 sur un sshd de test (OpenSSH 9.6, même code que la 10.0 de Debian 13 sur ces points) : redirection vers la socket autorisée acceptée, uid vu par le démon = `tunnel` ; socket non accessible au compte refusée par sshd (« Permission denied ») ; redirection TCP refusée par la règle nftables.
- La clé du tunnel reste sur backend-admin, lisible par le seul compte du service.
- Pare-feu : une seule règle nouvelle, backend-admin (`192.0.2.50`) → backend-relais (`192.0.2.200`) TCP 22. SSH chiffre ce tronçon : il n'attend pas le TLS.

## Application de bureau

L'application réunit l'icône de barre des tâches actuelle et une fenêtre principale qui affiche l'interface web dans une vue intégrée ; elle seule ouvre les sessions de présence.

- **Fenêtre principale** : vue web intégrée (QtWebEngine) sur bunker.example.org (page de déverrouillage et interface `/admin/`), avec un profil privé : rien n'est écrit sur disque (cookies, cache, historique).
- **Ouvrir l'administration** : l'application lance `ssh -T app@backend-admin` avec la clé de l'administrateur servie par un agent SSH (protocole de l'agent SSH, RFC 9987 ; D67), lit le jeton dans la réponse de Pollux et dépose le cookie dans la vue web. Une seule session couvre bunker, relais et journal légal.
- **Clé de l'administrateur** : l'application charge la clé publique choisie et affiche la ligne `authorized_keys` complète à remettre à l'administrateur root (remplacé par la gestion des utilisateurs : D123, D126).
- **Battement** : ping toutes les 30 s, surveillance des réponses ; une session perdue est signalée, son cookie effacé, et l'application propose de la rouvrir.
- **Fermer l'administration**, fermer la fenêtre ou quitter : la session SSH est terminée, le cookie effacé, les robinets se referment.
- **Indicateur** : la fenêtre et l'icône montrent si une session d'administration est ouverte.
- **Passphrase de déverrouillage** : la vue intégrée n'a pas l'extension Bitwarden ; l'application lit la passphrase dans le coffre par `rbw` et la transmet au formulaire, sans presse-papiers.
- **Interface d'administration** : pages statiques servies par lighttpd sous `/admin/` ; utilisables aussi dans un navigateur si un jeton y est fourni.
- **Dépendances (poste client)** : python3-pyqt6, python3-pyqt6.qtsvg (présents), module QtWebEngine pour PyQt6, rbw, openssh-client.

## Utilisateurs, privilèges et plugins

Prévu pour la 1.0 (D123, D126, D130). La conception détaillée reste à établir.

- **Gestion des utilisateurs** : un administrateur doté du privilège « utilisateurs » dispose, dans Paresia-admin, d'un module qui ajoute et retire des administrateurs et leurs clés. **Romulus tient le fichier des clés autorisées** lu par sshd (`AuthorizedKeysCommand`, `sshd_config(5)`, compte dédié) : il décide des accès SSH. L'administrateur ne recopie plus de ligne à la main ; le compte `app` n'a aucun droit d'écriture sur ses clés ; root garde la main par une commande de dépannage de Romulus. Les données gérées par un démon sont hors de `/etc`, sous `/var/lib/paresia/` (D123, D126).
- **Privilèges** : un seul privilège nommé en 1.0, « utilisateurs ». Les privilèges par domaine et les jetons d'API viennent après la 1.0 (D126).
- **Plugins** : Paresia-admin et son backend sont modulables. En 1.0, les plugins sont internes et déclarés : modules de Romulus et dossiers de pages web de Paresia-admin, activés par la configuration. Les plugins tiers dynamiques et les modules Python de l'application de bureau (Qt) viennent après la 1.0 (D126). Le module de gestion des utilisateurs est le premier plugin et éprouve l'architecture.
- **Périmètre de la première version (D130)** : strict socle, à savoir l'architecture des plugins, les comptes et les privilèges minimaux ; le reste vient après la première version (la 1.0). Les anciennes mentions « V3.0 » et « V3.1 » ont été remplacées par « 1.0 » et « après la 1.0 » avec la renumérotation.
- **Cœur et services (D148)** : le cœur de Paresia est formé de Romulus, Remus, Pollux, Castor, du tunnel et du protocole des jumeaux. Les services (Nisaba, bunkerd, d'autres plus tard) s'y greffent par déclaration (domaine, socket, compte attendu, catalogue d'actions) ; Romulus aiguille selon ces déclarations, sans liste écrite dans le code.
- **Fonctions d'administration en plugins (D148)** : les fonctions d'administration de chaque démon (Remus, Romulus, Nisaba) sont des plugins : un script exécutable et un manifeste par fonction (nom, paramètres typés et bornés, privilège, commandes `sudo`), dans un dossier lu par le noyau du démon. Les fonctions livrées sont sous `/usr/local/lib/paresia/<démon>/fonctions/`, les fonctions locales sous `/etc/paresia/<démon>/plugins.d/`, tous deux appartenant à root ; le sudoers est régénéré à partir des manifestes. Calendrier : la structure vient en 1.0, toutes les fonctions livrées étant des plugins ; le support officiel des plugins écrits par les utilisateurs (documentation, interface stable) vient juste après la 1.0. Précise D126 (point 3) et D130.
- **Noyau universel et greffons (D150)** : Paresia est un noyau d'administration universel et enfichable. Castor et Pollux, Remus et Romulus (« les deux couples de jumeaux sont Paresia ») demeurent étrangers à ce qu'ils transportent. Pour développer Paresia, on enfiche côté Remus un relais strfry, côté Romulus Nisaba et bunker : ce sont « les premiers greffons livrés avec Paresia, pour éprouver son fonctionnement ». But : « un noyau le plus simple et universel possible, qu'il n'ait pas à être modifié d'exceptions à chaque usage ». Nommage : `paresia-yin-<nom>` côté Remus, `paresia-yang-<nom>` côté Romulus ; un greffon présent des deux côtés devient deux greffons appariés.
- **Après la 1.0 : topologie, greffons hôtes, contrat central (D156)** : plusieurs yin et plusieurs yang pourront coexister (N:M) ; des greffons hôtes résidents d'un langage (Node.js, Python, etc.) pourront être chargés ; contrat central : un greffon yin et un greffon yang se parlent, se répondent et exploitent leurs API. Rien n'est implémenté en 1.0, mais aucun choix de la 1.0 ne l'écarte (**non-fermeture**) : champ `forme` réservé dans le manifeste, cible nommée et non socket écrite en dur, contrat indépendant du langage, adresse « cible, domaine, action ».
- **Langages du noyau (D157)** : Python pour la pré-alpha ; plus tard, le cœur enfichable et le bus réécrits dans un langage compilé. L'utilisateur a tranché le 2026-11-07, après l'étude : la première réécriture sera **Castor en C, après la 1.0** ; le préalable est une suite de conformité en boîte noire de `jumeaux/1`. Les démons ne se parlent que par `jumeaux/1`, sans liaison binaire, de sorte que la réécriture puisse se faire démon par démon.
- **Lecture des clés par Pollux** et journalisation de ces opérations : à établir par la conception (D123).

## Journalisation et secrets

Chaque démon tient un journal d'audit sans aucun secret, envoyé vers Loki sur backend-admin comme les autres journaux.

- **Niveaux et débogage (D125)** : tous les démons et outils émettent leurs lignes avec la priorité syslog (RFC 5424, 0 à 7) par les préfixes `<N>` de `sd-daemon(3)` sur la sortie d'erreur, via `server/commun/journal.py` (ajout au module commun, sans réécriture des démons). Le niveau minimal se règle par `[journal] niveau` (configuration en couches), sa variable d'environnement et `--debug` ; `LogLevelMax=` de systemd et `journalctl -p` filtrent aussi. Le niveau debug ne trace jamais de secret. Paresia-admin offre la même option. Toute tâche prévoit ses traces de débogage.

- **Sessions** (Pollux) : ouverture et fermeture, numéro de session, administrateur (commentaire de la clé), adresse source SSH. sshd journalise déjà l'empreinte de la clé acceptée.
- **Opérations** (Romulus, Remus) : date, numéro de session, adresse du client (posée par HAProxy), opération, paramètres non secrets, résultat.
- **Robinet du relais** (Castor) : ouvertures et fermetures, numéro de session.
- **Refus** : commande sans jeton, avec un jeton inconnu, ou robinet fermé, avec l'adresse du client.
- **Jamais journalisés** : jetons, ncryptsec, passphrases, contenu des requêtes signées par nak.
- **Affichage** : l'interface web n'insère jamais de texte reçu comme du HTML (`textContent`), et les démons nettoient les caractères de contrôle.

## Exigences transverses

Tous les composants sont écrits dès maintenant pour tourner aussi bien sur l'installation de référence qu'en conteneurs, et sans texte affiché en dur.

**Prêt pour les conteneurs**

- Configuration en couches (D29), ordre de priorité croissant : `/etc/paresia/paresia.conf` (base), `/etc/paresia/conf.d/*.conf` (ordre lexical, préfixe `NN-`), pour les programmes lancés par un utilisateur (poste client, outils en ligne de commande) `$XDG_CONFIG_HOME/paresia/*.conf` (défaut `~/.config/paresia/`), puis variables d'environnement `PARESIA_*`. Format INI (`configparser`), une section par composant ; il remplace le fichier par démon (D2). Les démons n'ont pas de couche utilisateur : leur environnement est fixé par l'unité systemd. Aucun chemin, nom d'hôte, adresse ou port figé dans le code.
- Secrets (clé du tunnel) lus dans des fichiers montés, jamais en variables d'environnement (lisibles via `/proc` et `docker inspect`).
- Journaux sur la sortie standard, une ligne JSON par événement ; l'envoi vers Loki est une option de configuration (par défaut : sortie standard seule).
- Un processus par service ; protection mémoire des secrets reproduite en conteneur (pas de swap, pas de vidage mémoire, système de fichiers en lecture seule, aucune capacité).
- **Moindre privilège sans perte de fonctionnalité** : un droit n'est retiré que si l'information ou la fonction perdue est rendue par un autre moyen, sans privilège supplémentaire ; toute réduction de droits nomme la fonctionnalité préservée et son moyen.
- **Moindre privilège dans les procédures livrées (D138)** : sur une machine exposée, une procédure n'exige jamais de shell root (`sudo -i`, `su`, `sudo sh -c`) ; chaque commande privilégiée porte son `sudo` et un chemin absolu ; chaque procédure donne en tête la liste descriptive de ses commandes `sudo` (ce n'est pas un sudoers à recopier ; elle avertit des entrées équivalentes à root quand les arguments ne sont pas figés) ; un administrateur déjà root, sans `sudo`, lance ces commandes sans ce préfixe.
- **Compte d'exécution des installations (D161, qui amende D141 pour backend-admin)** : sur backend-admin, on travaille en root et on n'installe pas `sudo` ; le script d'installation s'exécute en root et refuse tout autre compte. Sur backend-relais, il n'y a pas de shell root : le script refuse root et emploie `sudo` limité aux commandes strictement nécessaires, chemins absolus (D138).
- **Journaux et emplacements standard** : journaux par journald (sortie standard et d'erreur des unités, `logger` ; syslog admis en plus), aucun fichier journal ad hoc dispersé ; caches, états et fichiers d'exécution aux emplacements standard (systemd : `CacheDirectory=`, `StateDirectory=`, `RuntimeDirectory=`, `LogsDirectory=` si un fichier est indispensable ; XDG Base Directory côté utilisateur). Le journal légal est une donnée probante, pas un fichier journal.
- **Configuration livrée complète** : un fichier de configuration est livré entier, jamais en fragments à recopier.
- Deux modes de déploiement (D151, qui révise D68) : (a) **distribué** : `paresia-yin` (Remus, Castor) et `paresia-yang` (Romulus, Pollux) sur des machines séparées, installés par script après clonage du dépôt, avec des recommandations de pare-feu et de reverse proxy ; c'est le mode idéal, avec un vrai cloisonnement, livré en 1.0 ; (b) **Docker rootless tout-en-un** (pare-feu, reverse proxy, yin, yang et greffons), après la 1.0. Le lien yin–yang reste le tunnel SSH dans les deux modes ; l'emballage Docker Compose en deux ensembles n'est plus retenu. **Livrable de la 1.0 (D147)** : backend-admin et backend-relais s'installent chacun par un seul script complet et commenté, qui remplace la procédure pas à pas. L'option `--alpha-test` ajoute des points de contrôle après chaque étape et un journal de sortie horodaté, sans secret, écrit dans le dossier courant ou dans celui que désigne `--dossier-journal` (fichier en 0600, créé par le compte qui lance le script ; tout dossier sous `/var/log/paresia` est refusé) ; elle sera retirée après validation. Les messages des scripts passent par les catalogues `i18n`, lus par `python3`. **Ni procédure ni script ne posent de question (D144)** : les choix se font par paramètres, avec des valeurs par défaut ; seule exception, la saisie masquée d'un secret. **Aucun compte système n'a de répertoire sous `/home` (D144)** : `/var/lib/paresia-<compte>`, ou `/nonexistent` pour un compte sans répertoire. Les démons sont les mêmes dans les deux modes. L'image Docker de strfry n'est pas l'image d'origine : `docs/prerequis.md`.

- **Logo des scripts d'installation** (à faire avant la sortie de la 1.0) : chaque script d'installation affiche un logo en art ASCII. Le logo est un fichier du dépôt, jamais du texte en dur dans le script, et n'est affiché que sur un terminal.

**Textes et traductions**

- Aucun texte affiché en dur : catalogues JSON par langue (`fr-FR`, `en-US`, étiquettes BCP 47, D58), une clé par message, langue choisie dans la configuration, `fr-FR` par défaut.
- Les démons renvoient des codes stables (`identity_locked`, `token_missing`…) ; l'interface et l'application les traduisent.
- Journaux d'audit et journal légal : codes stables et texte fixe, jamais traduits, pour rester comparables dans le temps.
- Feuille de style remplaçable par langue, pour les textes plus longs ou un autre sens d'écriture.

**Produit, versions et qualité**

- Deux produits, un seul numéro de version pour tout l'ensemble : **Paresia-server** (Romulus, Remus, Pollux, Castor, bunkerd, configurations) et **Paresia-admin** (application de bureau et interface web).
- Numérotation `A.B.C` : A version majeure, B fonctionnalités et modifications importantes, C corrections. Version en cours : voir le fichier `VERSION` (`0.1.0` au 2026-11-07) ; la `1.0.0` réunit toutes les fonctionnalités attendues, chaque jalon monte la version mineure.
- Dépôt GitHub `Paresia` : branche `main` = branche de livraison, qui recevra ce projet une fois rendu ; branche `alpha` = ce projet ; une branche par tâche, fusionnée dans `alpha` après relecture et tests.
- Le protocole entre jumeaux et l'API d'administration annoncent leur version ; une version incompatible est refusée proprement.
- Formats de données versionnés (`bunker.json`, profils), migration automatique précédée d'une sauvegarde.
- Sauvegarde et restauration documentées et testées : profils du bunker, configurations, base strfry.
- Sauvegardes de procédure (relevés avant et après, etc.) sous `/var/backups/paresia/<machine>/` (mode 0700), activées par défaut, taille totale raisonnable fixée dans la configuration, paramétrables et désactivables : section `[sauvegarde.stockage]`, `actif` = `oui` ou `non`, 64 Mio par défaut, refus de copier une clé privée (D83, D90). Dossiers `relais` et `admin` (D80 bis). La copie de sûreté de migration de `bunker.json` reste, elle, dans le dossier d'état du démon (D91). Intégrité (D113) : l'empreinte SHA-256 de chaque fichier copié est inscrite au manifeste du jeu ; la restauration la vérifie et refuse si elle diffère ou manque ; règle générale : tout composant qui stocke ou relit des données prévoit leur contrôle d'intégrité. L'outil est lancé pendant l'installation depuis une copie du code appartenant à root, dans `/run/paresia-installation`, jamais depuis le clone du dépôt (D114).- Ligne de commande : chaque service est utilisable en CLI ; cette CLI est documentée par des pages mdoc, et l'API de chaque service (sockets, HTTP, protocole) l'est aussi.
- Métriques au format Prometheus (D145) : à prévoir pour tout service qui en a besoin.
- Tests automatiques rejoués à chaque modification (intégration continue, dans un conteneur Debian 13 sous un compte non root, comme la cible : D108), dont la chaîne complète lighttpd → Romulus → Pollux → tunnel → Castor → Remus, jeton, battement et refus.
- Recherche de secrets à chaque commit et dans l'intégration continue ; images et binaires externes vérifiés par empreinte.
- Documentation au standard Unix : pages de manuel (sections 1, 5, 8), `README`, `INSTALL`, `CHANGELOG`, `SECURITY` (modèle de menace).
- **Documentation complète de la 1.0 (D160)** : la 1.0 livre le manuel mdoc et un wiki vulgarisé, précis et exhaustif, pour les administrateurs auto-hébergés et semi-professionnels et pour les administrateurs de relais Nostr (strfry, Nisaba et le bunker étant les premiers greffons d'illustration). Tout document informatif du projet (README, CHANGELOG, protocole, SECURITY…) est tenu à jour. Le wiki est écrit dans `docs/wiki/` (`docs/conventions.md`, § Documentation). Méthode : documentation en temps réel (D159).
- Licence AGPL-3.0-or-later (D30), sous réserve de compatibilité avec les licences des dépendances (à vérifier une par une).
- Liste des travaux tenue à jour par le mainteneur.

## Points ouverts et ordre de réalisation

Aucun point ouvert de fond ; l'ordre proposé livre d'abord l'administration du bunker, puis celle du relais.

**Décisions prises**

- Liste de sourdine (63) : signée par bunkerd avec la clé du relais, déverrouillée par la passphrase que l'administrateur envoie.
- Journal légal : reste sur backend-admin ; copie, scellement, droits et purge repris par Nisaba (D87) ; consultation par Romulus en lecture seule.
- Paquets du poste client (QtWebEngine pour PyQt6, `rbw`) : vérifiés au début de l'étape 3.
- Suivi en direct du journal (7) : flux d'événements HTTP.
- Démons : bibliothèque standard de Python autant que possible.
- Une seule session SSH de l'application, vers backend-admin ; un seul tunnel backend-admin → backend-relais pour les deux paires de jumeaux.
- Jetons émis et vérifiés par Romulus ; Pollux et Castor restent de simples carrefours et feux de circulation.
- Remus tourne sous `chef`, avec `sudo` limité aux seules commandes `docker` nécessaires pour administrer strfry ; pas de programme `strfry-ops`.
- Castor n'écoute que Pollux, Remus que Romulus : sockets Unix, droits par compte et contrôle `SO_PEERCRED` ; connexions TCP du compte `tunnel` interdites par nftables.
- Protocole entre jumeaux : NDJSON, `jumeaux/1`, actions nommées par domaine (`docs/protocole.md`).

**Décisions de conception** : voir `docs/decisions.md` (D24 à D28 : ACL après tout changement de mode, export binaire, `MANIFEST`, état de Pollux par session, défi signé ; D113 à D126 : sauvegardes, liste noire, flux, utilisateurs, niveaux de journal).

**Ordre de réalisation**

1. Pollux et `pollux-session`, compte `app` sur backend-admin ; Romulus (jetons, aiguillage) ; socket d'administration de bunkerd 2.0.0 et ses opérations (identités, `sign`) ; consultation du journal légal.
2. lighttpd : chemins `/admin/` et `/api/admin/` sur bunker.example.org ; HAProxy : retrait de `Access-Control-Allow-Origin` pour bunker.example.org.
3. Application : fenêtre principale, session de présence, battement, pages d'administration du bunker et du journal légal.
4. backend-relais : Castor, Remus, compte `chef` et sudoers, compte `tunnel` ; service `paresia-tunnel` sur backend-admin ; règle du pare-feu backend-admin → backend-relais TCP 22.
5. Pages d'administration du relais, domaine par domaine (état, modération, événements, conteneur, sauvegardes, synchronisation).
6. Plus tard : TLS avec la CA interne sur le tronçon HAProxy → backend-admin.
7. Installation, deux modes (D151, qui révise D68 : l'emballage Docker Compose en deux ensembles n'est plus retenu) :
   1. **Distribué** : `paresia-yin` (Remus, Castor) et `paresia-yang` (Romulus, Pollux), installés par script sur des machines séparées, avec des recommandations de pare-feu et de reverse proxy ; c'est le mode idéal, avec un vrai cloisonnement ; livré en 1.0. Un script complet par machine, avec l'option `--alpha-test` (D147).
   2. **Docker rootless tout-en-un** : pare-feu, reverse proxy, yin, yang et greffons ; but : mettre la structure réelle de l'installation de référence dans une « boule à neige » utilisable tout de suite par un administrateur d'infrastructure personnelle ; après la 1.0.
   Le lien yin–yang reste le tunnel SSH dans les deux modes.

## Suivi des versions

Historique des modifications : `CHANGELOG.md` ; décisions : `docs/decisions.md`.
