# Décisions de conception — Paresia

Version du document : 0.1.19 · 2026-11-08. Public : développeur, contributeur.

Ce document recense les décisions de produit qui expliquent des choix visibles dans le code, la configuration ou la documentation ; elles sont citées sous la forme `Dxx` (ou `Bxx` pour bunkerd). Les décisions de conduite du projet n'y figurent pas. Un retour en arrière est une décision du mainteneur : elle s'ajoute ici comme nouvelle décision et l'historique n'est pas réécrit.

Statuts : **en vigueur** ; **en vigueur, non livrée** (décidée, pas encore dans le code) ; **révisée par Dxx** ; **remplacée par Dxx**. Les décisions sont groupées par sujet ; les dates vont du 2026-11-05 au 2026-11-08.

## Sommaire

1. Identité et sessions de présence · 2. Romulus, HTTP et flux · 3. Relais : Castor et Remus · 4. Tunnel, comptes et unités · 5. Moindre privilège et sudo · 6. bunkerd · 7. Journal légal et Nisaba · 8. strfry · 9. Sauvegardes · 10. Configuration, journaux et métriques · 11. Noyau, greffons et déploiement · 12. Client Paresia-admin · 13. Utilisateurs · 14. Qualité, tests et documentation · 15. Licence

## 1. Identité et sessions de présence

| N° | Décision | Statut |
| --- | --- | --- |
| D1 | Le nom de l'administrateur vient de la session SSH : `sshd` expose `SSH_USER_AUTH` (`ExposeAuthInfo yes`) et `pollux-session` retrouve le commentaire de la clé dans `authorized_keys`. Risque résiduel : D20. | en vigueur |
| D6 | `pollux-session` journalise dans `syslog` et sort avec les codes 0 à 3 ; ses délais sont réglables. | en vigueur |
| D7 | Une connexion à Pollux porte une session de présence ; 16 sessions au plus. | en vigueur |
| D8 | Un pair injoignable (Castor, Remus, Pollux) donne `peer_unavailable`, sans arrêter le démon. | en vigueur |
| D9 | Pollux garde une connexion persistante vers Romulus ; sa rupture ferme les sessions. | en vigueur |
| D14 | Après une rupture, Pollux se reconnecte à Romulus à l'ouverture de session suivante. | en vigueur |
| D18 | `pollux-session` sort avec le code 3 si Pollux ferme la connexion alors qu'une requête est en attente. | en vigueur |
| D19 | Les appels de Pollux vers Romulus et Castor se font hors du verrou global de Pollux : un pair lent ne bloque pas les autres sessions. | en vigueur |
| D20 | Usurpation via `SSH_USER_AUTH` : le compte `app` ne sert qu'à `pollux-session`, et la présence est prouvée par la signature d'un défi aléatoire (SSHSIG) avec la clé de l'administrateur. | en vigueur |
| D28 | Défi de présence : le type de clé est celui de la clé de l'administrateur ; `python3-cryptography` est admis comme dépendance ; le défi vaut 60 s par défaut ; l'espace de noms est `paresia-presence`. | en vigueur |
| D38 | Défi : clés `sk-*`, certificats et DSA refusés ; RSA de 2048 bits au moins ; `authorized_keys` appartient à root ; signature de 2 Kio au plus. | en vigueur |
| D67 | Les fonctions qui s'appuient sur un agent SSH suivent les spécifications standard (protocole d'agent SSH, RFC 9987 ; `PROTOCOL.sshsig`), quel que soit le client qui sert l'agent. | en vigueur |
| D27 | L'état de Pollux et son verrou sont tenus par session, sans composant supplémentaire. | en vigueur |
| D73 | Aucun `castor/light/ping` n'est envoyé après le `castor/light/close` de la même session. | en vigueur |

## 2. Romulus, HTTP et flux

| N° | Décision | Statut |
| --- | --- | --- |
| D4 | Codes d'erreur stables, traduits par l'interface, avec statuts HTTP (RFC 9110). | en vigueur |
| D10 | Romulus numérote les sessions ; un cookie et un en-tête de jeton différents donnent `token_conflict` ; les actions non servies répondent 501. | en vigueur |
| D15 | Contrôle `Origin` : exactement un `Origin` égal à la partie de `Host` après `://`, sinon 403 `origin_refused`. | en vigueur |
| D100 | Aiguillage de Romulus : nouveau code `origin_refused` (403) et table des statuts HTTP (422 valeurs refusées par bunkerd ; 404 `unknown_identity`, `client_not_authorized` ; 409 `identity_exists`, `identity_unlocked`, `relay_identity_protected` ; 502 `command_failed` ; 503 `command_busy`, `relay_light_red` ; 504 `command_timeout` ; 403 `session_closed`) ; `flux_max_simultanes` vaut 8 par défaut ; événements de flux `end` et `error`. | en vigueur |
| D105 | La file d'écoute du frontal HTTP de Romulus est au moins égale à `max_connexions` : une rafale de connexions n'est plus perdue. | en vigueur |
| D111 | La comparaison `Origin`/`Host` ignore la casse des seules lettres ASCII ; les lignes de trace de `acl check`, `acl apply` et `verify` sont un format de données stable, non traduit. | en vigueur |
| D121 | Après `end` ou `error`, Romulus ferme le flux et le client `EventSource` DOIT appeler `close()`, sinon le navigateur ouvre un nouveau suivi à l'insu de l'utilisateur. Le plafond de flux par session est reporté après la 1.0. | en vigueur |
| D85 | Le suivi en direct de Remus (flux sur le fil) se termine par une ligne d'erreur ou de fin portant la raison d'arrêt. | en vigueur |
| D37 | Export du journal légal : `application/gzip`, nom `requisition-AAAAMMJJ-HHMMSS.tar.gz`, en-tête `X-Paresia-Sha256`, 8 Mio par défaut (plafond 16 Mio), `export_too_large` (422), `export_busy` (503), résultat vide → `count` à 0. | en vigueur |
| D25 | Le protocole prévoit une réponse binaire pour l'export du journal légal (menu 51). | en vigueur |
| D92 | Contrat `ExportBinaire(produire)` : Romulus possède le fichier anonyme, calcule taille et SHA-256 et fixe le nom ; le producteur ne rend que `{count, periode}` ; options `export_max_octets` (8 Mio, plafond 16 Mio) et `export_max_simultanes` (2) dans `[romulus.http]`. | en vigueur |
| D23 | Le reverse proxy remplace l'en-tête `X-Forwarded-For` par l'adresse source réelle (`%[src]` avec HAProxy). | en vigueur |
| D135 | Le groupe `paresia-http` donne l'accès à `romulus-http.sock` (mode 0660) au seul lighttpd (`www-data`), avec en plus le contrôle `SO_PEERCRED`. | en vigueur |

## 3. Relais : Castor et Remus

| N° | Décision | Statut |
| --- | --- | --- |
| D45 | L'exemple de configuration du backend-relais est un fichier complet distinct : `server/conf/paresia-relais.conf`. | en vigueur |
| D46 | Castor et Remus se lancent par `python3 -m server.castor` et `python3 -m server.remus`, sans lanceur dans `server/bin/`. | en vigueur |
| D50 | Feux de Castor : vert jusqu'à `now + green_s`, sans cumul ; `close` puis `session_closed` pendant `closed_s` (10 s) ; 64 feux au plus. | en vigueur |
| D51 | `castor.sock` admet `ping` et `close` ; `castor-state.sock` admet `state` seulement ; toute autre action donne `unknown_action`. | en vigueur |
| D52 | Remus attend le feu par interrogation (`poll_s` 0,25 s, `wait_s` 5 s) ; codes `relay_light_red`, `session_closed`, `peer_unavailable`. | en vigueur |
| D53 | Une opération en cours est menée à terme ; l'arrêt attend `stop_s` (120 s) et `TimeoutStopSec` de Remus est supérieur. | en vigueur |
| D54 | Remus arrête les flux continus quand le feu passe au rouge (`check_s` 5 s). | en vigueur |
| D55 | Exécuteur de Remus : table fermée, `argv` fixe, pas de shell, délai 60 s, sortie 64 Kio, 4 commandes simultanées. | en vigueur |
| D56 | Journal d'audit de l'exécuteur : `command_started`, `command_finished` ; les paramètres ne sont journalisés que si leur gabarit est `journalisable` ; la sortie ne l'est jamais. | en vigueur |
| D57 | Codes `command_failed`, `command_timeout`, `command_busy` et `not_available` ; Romulus prévalide la forme des `params` de bunkerd. | en vigueur |
| D72 | La rupture d'une `Connexion` est définitive : après la fermeture d'un flux, l'appelant en crée une nouvelle. | en vigueur |
| D66 | `TimeoutStopSec=180` pour Pollux (au pire 16 × (5 + 5) = 160 s). | en vigueur |
| D81 | Remus : `KillMode=mixed`, pour ne pas tuer les `sudo` en cours dès l'arrêt. | en vigueur |
| D84 | Castor sans `MemoryDenyWriteExecute` jusqu'à un essai réel. | en vigueur |

## 4. Tunnel, comptes et unités

| N° | Décision | Statut |
| --- | --- | --- |
| D21 | Le compte système de Romulus est `paresia-romulus` ; le code serveur est sous `/usr/local/lib/paresia`. | en vigueur |
| D40 | Un `RuntimeDirectory=` par unité, en mode 0711 : `/run/paresia-pollux`, `/run/paresia-romulus`, `/run/paresia-castor`, `/run/paresia-remus`. | en vigueur |
| D41 | Groupes de sockets de backend-admin : `paresia-sessions`, `paresia-liaison`, `paresia-http`. | en vigueur |
| D42 | Les identifiants des comptes et groupes sont des numéros d'exemple dans le dépôt ; le script d'installation fait attribuer les vrais par le système (plage système de `login.defs(5)`) et les reporte dans la configuration. | en vigueur |
| D43 | La configuration installée est `paresia.conf` (base) plus `conf.d/10-backend-admin.conf` (surcharge livrée). | en vigueur |
| D44 | Le compte `app` n'a ni mot de passe ni `sudo` ; il est réservé à `pollux-session`. | révisée par D144 (répertoire) |

D40 à D44 sont reconstituées d'après la documentation (`docs/configuration.md`, § Unités systemd, `docs/architecture.md`, § Comptes et emplacements) et les unités livrées ; leur énoncé d'origine n'a pas été inscrit au registre.
| D47 | Comptes de backend-relais : `paresia-castor`, `chef`, `tunnel`, sans répertoire sous `/home`. | en vigueur |
| D48 | Un `RuntimeDirectory=` par unité du relais ; sockets de Castor et de Remus dans leurs dossiers. | en vigueur |
| D49 | Trois groupes minimaux pour les sockets du relais : `paresia-castor-tunnel`, `paresia-remus-tunnel`, `paresia-castor-etat`. | en vigueur |
| D61 | `paresia-tunnel.service` est livrée côté backend-admin. | en vigueur |
| D62 | Le mode du socket local du tunnel est réglé par `StreamLocalBindMask` ; pas de groupe dédié au-delà de D152. | révisée par D152 |
| D63 | Le compte `tunnel` a pour shell `nologin` ; la redirection seule (`ssh -N`) fonctionne sans shell. | en vigueur |
| D65 | Table nftables `paresia_relais` chargée par une unité `oneshot` ; `ssh_config` en couches (`Include`, `10-relais.conf`) ; `TimeoutStopSec` 90 (Castor) et 150 (Remus). | en vigueur |
| D69 | `StrictModes yes` et `PermitUserEnvironment no` sont posés hors du bloc `Match User app` (`sshd_config(5)` ne les admet pas dans un `Match`). | en vigueur |
| D82 | D69 s'étend au relais ; bloc `Match User tunnel` figé. | en vigueur |
| D98 | `nft -c -f` exige root : la vérification de la table se fait sur la cible, avant le chargement. | en vigueur |
| D144 | Aucun compte système sous `/home` (FHS) : répertoires sous `/var/lib/paresia-<compte>` ou `/nonexistent`. Les scripts et procédures ne posent aucune question ; les choix se font par paramètres avec des valeurs par défaut (seule exception : la saisie masquée d'un secret). | en vigueur |
| D152 | Les dossiers des sockets du tunnel sont créés par `tmpfiles.d` : parent `root:root` 0711, sous-dossiers 0710 avec le groupe du démon, sans ACL ni `RuntimeDirectory=` (systemd 257 réapplique `RuntimeDirectoryMode` avant chaque commande et remettait le masque ACL à `---`). | en vigueur |

## 5. Moindre privilège et sudo

| N° | Décision | Statut |
| --- | --- | --- |
| D60 | Fichier sudoers strict : un motif par paramètre ; pas de joker après `docker exec <conteneur> <programme>`. | en vigueur |
| D80 | Gabarits sudoers : seuls `Hexadecimal`, `Choix` et `Entier` sont traduits ; une règle exacte par valeur de `Choix` ; expression régulière `^…$` sans espace ; aucun joker ; aucun programme intermédiaire setuid. Résidu accepté : arguments fixes fusionnés lors d'un appel direct à `sudo`. | en vigueur |
| D96 | Générateur de sudoers limité aux verbes `exec` et `restart` ; sudo 1.9.10 au moins (`sudoers(5)`, « Regular expressions »). | en vigueur |
| D137 | `sudo` n'est pas installé sur backend-admin ; il n'est prévu que sur backend-relais, pour Remus. | en vigueur (confirmée par D161) |
| D138 | Procédures livrées : jamais de shell root (`sudo -i`, `su`, `sudo sh -c`) ; chaque commande privilégiée porte son `sudo` et un chemin absolu ; chaque procédure donne en tête la liste descriptive des commandes `sudo`. | en vigueur |
| D141 | Recommandation d'exploitation : administrer par un compte ordinaire avec `sudo`, sans connexion SSH directe de root (`PermitRootLogin no`). | en vigueur, amendée par D161 |
| D161 | Le script d'installation de backend-admin s'exécute en root et n'installe pas `sudo` ; celui de backend-relais refuse root et emploie `sudo` limité aux commandes nécessaires. | en vigueur |

## 6. bunkerd

| N° | Décision | Statut |
| --- | --- | --- |
| B1 | La signature utilise `python3-cryptography` (paquet Debian 13). | en vigueur |
| B2 | La clé de relais est une seule identité, désignée par `relay_identity`. | en vigueur |
| B3 | Relais en `wss://` ; `ws://` seulement pour un hôte `.onion`. | en vigueur |
| B4 | Configuration INI et journal JSON ; démon sous systemd. | en vigueur |
| B5 | `identity/add` : délai d'inactivité de 15 minutes par défaut. | en vigueur |
| B8 | Socket d'administration : ACL posées par bunkerd, `SO_PEERCRED` obligatoire. | en vigueur |
| B9 | Verrou global de bunkerd conservé (60 s au plus). | en vigueur |
| B10 | `identity/remove` demande une confirmation ; `authorize` et `revoke` acceptent un npub ou de l'hexadécimal. | en vigueur |
| B11 | `bunker.json` est versionné (format 1) ; migration avec copie de sûreté et lecture stricte. | en vigueur |
| B12 | `sign-mute-list` : 0 à 500 clés, vérification de la clé, temporisation de 2 s après un échec. | en vigueur |
| B13 | Code `pubkey_mismatch` ; signature refusée sans clé connue. | en vigueur |
| D70 | `relay_identity` est obligatoire, avec la valeur-témoin `(none)` pour « aucune identité de relais ». | en vigueur |
| D75 | Plafond de `log_n` (NIP-49) fixé à 20 (1 Gio, RFC 7914) ; au-dessus, le secret est refusé. | en vigueur |
| D77 | Mode de la socket d'administration : le propriétaire a lecture et écriture ; seuls 0600, 0620, 0640 et 0660 sont admis ; bunkerd utilise 0600. | en vigueur |
| D91 | Lecture stricte de `bunker.json` (clés en double, `NaN`, `Infinity`, format inconnu refusés) ; la copie de sûreté de migration reste dans le dossier d'état. | en vigueur |
| D112 | Les six codes de `bunker/relay-key/sign-mute-list` atteignent le client : 422 `not_relay_key`, `bad_passphrase`, `invalid_pubkeys`, `invalid_passphrase`, `log_n_too_high` ; 409 `pubkey_mismatch` ; pas de 401. | en vigueur |
| D120 | La multiplication scalaire secrète est confiée à `cryptography` (temps constant d'OpenSSL pour secp256k1) ; `libssl3t64` 3.5.7-1~deb13u3 au moins. | en vigueur |
| D162 | Aucun démon n'attend son arrêt sans délai : l'attente se fait par tranches de 0,1 s, pour qu'un signal reçu par un autre fil soit traité. | en vigueur |

## 7. Journal légal et Nisaba

| N° | Décision | Statut |
| --- | --- | --- |
| D22 | Romulus lit le journal légal en lecture seule par ACL nommée, sans groupe ni écriture. **Complétée le 2026-11-08 (mainteneur : « on a confié ce travail à un nouveau démon : nisaba »)** : la consultation du journal légal (recherche, export, état, vérification) est confiée à Nisaba ; Romulus ne fait que router et ne lit plus le journal. Le texte d'origine reste l'historique ; l'ACL de lecture pour `paresia-romulus` est posée par les scripts et par Nisaba, mais Romulus ne s'en sert plus. | en vigueur, complétée |
| D24 | Les scripts `journal-legal-*` appliquent D22 : tout `chmod` est suivi d'un `setfacl`. | en vigueur |
| D35 | `journal-legal-acl.sh` offre `--appliquer` et `--verifier` ; `ECHEC_ACL` n'interrompt pas la copie ; fichiers temporaires par `mktemp` et `trap`. | en vigueur |
| D26 | Le `MANIFEST` du journal légal est documenté à partir des scripts et de leur usage. | en vigueur, non livrée |
| D36 | Journal légal : `event` et `author` en minuscules (`^[0-9a-f]{64}$`) ; Romulus n'a pas accès au journal systemd. | en vigueur |
| D76 | L'archive d'export contient `extraction.jsonl`, `preuves.txt`, `seals/<jour>.txt` et `.ots`, `SHA256SUMS` et les `MANIFEST` des jours concernés. | en vigueur, non livrée |
| D87 | Copie, scellement, droits et purge du journal légal sont intégrés à un processus annexe dédié, **Nisaba**, sur backend-admin ; Romulus l'interroge par socket Unix, sans lire journald. | en vigueur |
| D88 | Nisaba : planification interne (rattrapage au démarrage) ; Romulus garde la recherche et l'export par l'ACL de D22 ; Nisaba répond pour l'état et la vérification (**partage révisé le 2026-11-08 : toute la consultation est confiée à Nisaba, voir D22 ; compte d'exécution révisé par D171**) ; code `ECHEC_PURGE`. | en vigueur, révisée en partie |
| D171 | Nisaba tourne sous un compte dédié `paresia-nisaba`, sans root, avec la seule capacité `CAP_LINUX_IMMUTABLE`, propriétaire de l'arbre du journal légal (propriétaire, 2026-11-08 : « pour nisaba : option A ok »). Révise D88 pour le compte d'exécution ; l'historique de D88 est conservé. | en vigueur, non implémentée |
| D89 | Étiquette journald unique `nisaba` ; codes `ECHEC_*` inchangés. | en vigueur |
| D111 | Divergence entre `[nisaba.droits] compte` et `[nisaba.journal] compte_acl` refusée (`config_invalid`) ; la reprise d'un fichier sans l'attribut d'immuabilité est détectée ; `lsattr` illisible vaut « non immuable ». | en vigueur |

## 8. strfry

| N° | Décision | Statut |
| --- | --- | --- |
| D95 | `strfry.conf` livré : `relay.auth.restrictedReadKinds = "4"` (bitchat ne gère pas NIP-42 ; ses messages privés sont des kind 1059) ; `restrictReadToInvolvedPubkey = true` ; `rejectEventsNewerThanSeconds = 1800` ; `filterValidation.requireAuthorOrTag` non activé ; toutes les valeurs écrites explicitement. | en vigueur |
| D99 | Plugin d'écriture du journal légal en Python (`python3` ajouté à l'image strfry, sans `jq` ni sous-processus) ; le kind 20000 reste journalisé ; les kinds éphémères non journalisés prennent un chemin rapide. | en vigueur |
| D110 | Le journal échappe les caractères C1, DEL, U+2028 et U+2029 ; `sourceInfo` n'est pas validé par le plugin : le proxy écrase l'en-tête d'adresse et le port de strfry n'est publié que vers lui ; en cas d'échec d'écriture du journal, la ligne complète va sur la sortie d'erreur (donc journald). | en vigueur |
| D117 | Si le fichier de la liste noire disparaît ou devient illisible après une lecture réussie, la dernière liste valide reste en place et une alerte est émise (une par épisode d'erreur). | en vigueur |
| D119 | Liste noire illisible au démarrage, aucune liste encore lue : le relais accepte les écritures et journalise une alerte. | en vigueur |
| D120 | `NEG-OPEN` de strfry ne laisse fuir aucun kind 4 ni 1059 tant qu'aucun arbre negentropy prédéfini n'existe : les fichiers livrés n'en créent jamais. | en vigueur |

## 9. Sauvegardes

| N° | Décision | Statut |
| --- | --- | --- |
| D83 | Sauvegardes de procédure sous `/var/backups/paresia/<machine>/` (mode 0700), dans toutes les procédures. | en vigueur |
| D90 | Section `[sauvegarde.stockage]` : `actif` (`oui` ou `non`), 64 Mio par défaut, refus de copier une clé privée. | en vigueur |
| D103 | Le retour arrière d'une procédure ne supprime jamais une unité sans avoir retrouvé sa sauvegarde ; sinon il échoue et s'arrête. | en vigueur |
| D104 | Fichier témoin d'absence : quand une procédure installe un fichier qui n'existait pas, elle pose `<fichier>-absente` ; le retour arrière ne supprime ce fichier que si le témoin est trouvé. | en vigueur |
| D113 | L'empreinte SHA-256 de chaque fichier copié est inscrite au manifeste du jeu ; `restaurer` et `retrouver` la vérifient et refusent (`backup_integrity_failed`) si elle diffère ou manque. | en vigueur |
| D114 | L'outil de sauvegarde se lance depuis une copie du code appartenant à root, dans `/run/paresia-installation`, jamais depuis le clone du dépôt. | en vigueur |

## 10. Configuration, journaux et métriques

| N° | Décision | Statut |
| --- | --- | --- |
| D2 | Un fichier INI par démon avec surcharge par variables. | remplacée par D29, D31 à D33 |
| D3 | Chemins, comptes et uid sont obligatoires, sans défaut dans le code ; seules les durées et les limites ont un défaut. | en vigueur |
| D5 | Journal JSON, une ligne par événement, caractères de contrôle filtrés. | en vigueur |
| D11 | Le serveur est un paquet `server/` ; chaque démon se lance par `python3 -m server.<démon>`. | en vigueur |
| D13 | La configuration de `pollux-session` est portée par son script de lancement. | en vigueur |
| D29 | Configuration en couches : `/etc/paresia/paresia.conf`, `conf.d/`, `$XDG_CONFIG_HOME/paresia/`, variables `PARESIA_*` ; remplace les `.ini` par composant. | en vigueur |
| D31 | Sections INI `[<composant>.<domaine>]` ; la section nue vaut `general`. | en vigueur |
| D32 | `--config` ou `PARESIA_<COMPOSANT>_CONFIG` remplace les fichiers de couches ; `pollux-session` ne lit ni variable d'environnement ni `--config`. | en vigueur |
| D33 | Un seul exemple complet, `server/conf/paresia.conf`. | en vigueur |
| D58 | Étiquettes de langue BCP 47 (RFC 5646) : `i18n/fr-FR.json` et `i18n/en-US.json`. | en vigueur |
| D145 | Métriques par le collecteur `textfile` de node_exporter : Paresia n'écrit jamais dans le dossier de node_exporter ; chaque démon écrit dans son propre dossier `metriques/` et l'administrateur l'ajoute par un second `--collector.textfile.directory`. | en vigueur |
| D146 | Chien de garde systemd (`WatchdogSec`) après la 1.0 ; les démons sont en `Type=notify`. | en vigueur, non livrée (chien de garde) |
| D164 | Événement `startup_failed` : `cause` vaut `os_error` (avec `errno` entier), `data_unreadable`, `internal_error` ou un code de configuration ; un échec après la mise en service est `service_failed`. | en vigueur |

## 11. Noyau, greffons et déploiement

| N° | Décision | Statut |
| --- | --- | --- |
| D68 | Deux modes d'installation à terme. | révisée par D151 |
| D147 | Un script d'installation complet et commenté par machine remplace la procédure pas à pas ; l'option `--alpha-test` ajoute des points de contrôle après chaque étape et un journal horodaté ; ses messages passent par les catalogues `i18n`. | en vigueur |
| D148 | Le cœur (Romulus, Remus, Pollux, Castor, tunnel, protocole des jumeaux) ne connaît aucun service ; les services (Nisaba, bunkerd…) se greffent par déclaration ; les fonctions d'administration de chaque démon sont des plugins (script plus manifeste). | en vigueur |
| D150 | Paresia est un noyau d'administration universel et enfichable : les deux couples de jumeaux restent étrangers à ce qu'ils transportent ; nommage `paresia-yin-<nom>` et `paresia-yang-<nom>`. | en vigueur |
| D151 | Deux modes de déploiement : distribué (`paresia-yin` et `paresia-yang` sur des machines séparées, livré en 1.0) et Docker rootless tout-en-un (après la 1.0). Le lien yin–yang reste le tunnel SSH. | en vigueur |
| D153 | Privilèges des greffons : en 1.0, sudo reste le mécanisme, avec un bloc de privilèges neutre dans le manifeste ; la bascule vers une socket systemd par fonction se fait avant l'ouverture des greffons aux tiers, après la 1.0. | en vigueur, non livrée ; complétée le 2026-11-08 : un compte système par greffon est prévu avant la 1.0 |
| D154 | `jumeaux/1` est conservé pour la 1.0 ; l'introspection des catalogues est la source unique des actions et des paramètres, conçue pour se traduire en Varlink ; contrat de sortie, version du manifeste et condition de chargement. | en vigueur |
| D156 | Après la 1.0 : topologie N:M entre yin et yang, greffons hôtes résidents d'un langage ; aucun choix de la 1.0 ne l'écarte. | en vigueur, non livrée |
| D157 | Python pour la pré-alpha ; plus tard, réécriture démon par démon dans un langage compilé, en commençant par Castor en C après la 1.0, avec une suite de conformité en boîte noire de `jumeaux/1`. | en vigueur |
| D166 | Un greffon ne livre pas le produit qu'il administre : il déclare avec quelles versions il fonctionne ; le greffon officiel de strfry est livré clé en main. | en vigueur ; greffon de base (trois fonctions) livré |
| D167 | Remus reste « bête » : il charge des fonctions, sert leur catalogue et aiguille chaque requête ; les fonctions en lecture sont installées par défaut, celles qui modifient seulement à la demande. **Exception explicite** (feuille de route confirmée par le mainteneur le 2026-11-07, qui place le redémarrage du conteneur dans la démonstration du greffon strfry de base) : le greffon de base livre `relay/container/restart` par défaut. | en vigueur, avec cette exception |

## 12. Client Paresia-admin

| N° | Décision | Statut |
| --- | --- | --- |
| D109 | Clés d'interface `ui_*` dans les catalogues racine `i18n/` ; l'application importe `server.commun` ; tests Qt par `importorskip` ; icône limitée à l'indicateur d'état ; pas de saisie du jeton hors de l'application en 1.0. | en vigueur |
| D118 | La page web reçoit sa langue de l'application hôte ; `navigator.language` puis `fr-FR` ne servent que de repli ; attributs de chargement dangereux refusés. | en vigueur |
| D168 | Le noyau du client ne connaît aucun produit ; chaque greffon yang apporte ses pages. Voie de livraison tranchée (2026-11-08) : les pages et l'index sont posés à l'installation, par root, dans un dossier de Paresia ; un serveur web (lighttpd) les sert sous `/admin/` et `/admin/greffons/`, et Romulus reste le seul point de contact côté yang (`/api/admin/`, par Pollux). | en vigueur |
| D172 | Les routes `/api/status`, `/api/unlock`, `/api/lock` et `/api/timeout` de la page publique de bunkerd sont retirées à la livraison de la nouvelle page (v0.2) (mainteneur, 2026-11-08, « Retirer l'applet »). L'applet de barre des tâches cesse alors de fonctionner et n'est pas reprise ; restent la page web et le client Paresia. Retour arrière : garder ces routes derrière un jeton propre à l'applet ou derrière la session. | en vigueur, non implémentée |
| D175 | L'image du greffon strfry est un livrable public du projet : `z0brak/paresia-yin-strfry:4cd3cf6` (mainteneur, 2026-11-08, carte « Citer l'image »). Son nom est cité dans `docs/prerequis.md`, § 5, et dans `INSTALL.md` ; ce nom d'image publique n'est pas une référence à l'installation du mainteneur (invariant 4). Le conteneur s'appelle `strfry` et est lancé depuis cette image exacte ; l'étiquette `4cd3cf6` est celle que l'installateur compare à la version déclarée par le greffon. Retour arrière : retirer le nom de l'image des trois documents et rétablir « à compléter » ; l'installateur continue de comparer l'étiquette déclarée par le greffon. | en vigueur |

## 13. Utilisateurs

| N° | Décision | Statut |
| --- | --- | --- |
| D122 | Clés autorisées du compte `app` sous `/etc/ssh/authorized_keys/app`, propriété de root. | remplacée par D123 |
| D123 | Un administrateur doté d'un privilège dispose dans Paresia-admin d'un module de gestion des utilisateurs ; Romulus tient les clés autorisées du compte `app`. | en vigueur, non livrée |
| D126 | Romulus tient le fichier des clés lu par sshd (`AuthorizedKeysCommand`) ; un seul privilège nommé en 1.0, « utilisateurs » ; plugins internes déclarés en 1.0, tiers après. | en vigueur, non livrée |
| D130 | Gestion des utilisateurs et des plugins limitée au strict socle pour la première version. | en vigueur, non livrée |
| D125 | Niveaux de journal : priorités syslog (RFC 5424) par préfixes `<N>` de `sd-daemon(3)` ; niveau minimal réglable par `[<démon>.journal] niveau` et `--debug` ; le niveau debug ne trace jamais de secret. | en vigueur |

## 14. Qualité, tests et documentation

| N° | Décision | Statut |
| --- | --- | --- |
| D101 | Un fichier livré (code, unités, configuration, procédures, documentation, pages de manuel, catalogues) ne cite ni tâche, ni lot, ni rôle d'agent, ni fiche, ni identifiant d'avis ; les `D<n>` de ce document restent citables. | en vigueur |
| D108 | La CI tourne dans un conteneur `debian:trixie` (Debian 13, systemd 257, comme la cible), sous un compte non root, hébergé par le runner `ubuntu-latest`. | en vigueur |
| D124 | Chaque exécution de `pytest` reçoit un dossier temporaire propre sous `.pytest_cache/` ; un seul `pytest` à la fois par dépôt. | en vigueur |
| D160 | La 1.0 livre le manuel mdoc et un wiki vulgarisé, précis et exhaustif pour les administrateurs auto-hébergés et les administrateurs de relais Nostr ; les documents informatifs du projet sont tenus à jour. | en vigueur |

## 15. Licence

| N° | Décision | Statut |
| --- | --- | --- |
| D30 | Licence AGPL-3.0-or-later, texte officiel dans `LICENSE`, en-têtes SPDX ; aucune dépendance ni outil requis propriétaire, sauf décision inscrite ici avec sa justification. | en vigueur |

## Décisions de conduite

Les décisions qui portent sur l'organisation du travail du projet ne sont pas reprises ici.
