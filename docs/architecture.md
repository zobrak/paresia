# Architecture Paresia

Version du document : 0.1.19 · 2026-11-08. Public : administrateur, développeur.

Renvoi. La source de référence est le [cahier des charges](cahier-des-charges.md) : § « Architecture », § « Session de présence », § « Romulus », § « Remus et Castor » et § « Réseau, lighttpd et tunnel SSH ». En cas d'écart, le cahier fait foi. Les messages sont décrits dans le [protocole](protocole.md). Version vulgarisée : [Architecture et sécurité](wiki/Architecture-et-securite.md).

## Machines

Yang est la machine d'administration (`backend-admin` dans les noms de scripts et de dossiers) ; yin est la machine du relais (`backend-relais`).

| Machine | Rôle |
| --- | --- |
| yang | Romulus, Pollux, `pollux-session`, bunkerd, Nisaba (journal légal ; ses scripts `journal-legal-*` d'origine subsistent), lighttpd, tunnel SSH sortant |
| yin | Remus, Castor, relais strfry, comptes `chef` et `tunnel` |
| `pare-feu` | HAProxy (hors dépôt) ; filtrage par source |
| `poste client` | Paresia-admin (application de bureau), agent SSH (indépendant du client), `rbw` |

## Modes de déploiement (D151, qui révise D68)

- **Distribué (livré en 1.0)** : `paresia-yin` (Remus, Castor) sur yin et `paresia-yang` (Romulus, Pollux) sur yang, installés chacun par un script sur des machines séparées, avec des recommandations de pare-feu et de reverse proxy ; c'est le mode idéal, au vrai cloisonnement.
- **Docker rootless tout-en-un (après la 1.0)** : pare-feu, reverse proxy, yin, yang et greffons dans un ensemble utilisable tout de suite.
- Le lien yin–yang reste le **tunnel SSH** dans les deux modes. Les démons sont les mêmes.

## Composants

| Composant | Machine | Rôle | Cahier |
| --- | --- | --- | --- |
| Romulus | yang | point de contact ; émet et vérifie les jetons ; aiguille vers bunkerd, Nisaba (journal légal) ou Remus | § Romulus |
| Pollux | yang | carrefour et feu de circulation de la présence ; relaie les jetons et les pings | § Session de présence |
| `pollux-session` | yang, compte `app` | commande forcée SSH ; relais entre la session SSH et Pollux | § Session de présence |
| bunkerd | yang | bunker NIP-46 ; socket d'administration réservée à Romulus | § Administration de bunkerd |
| journal légal | yang | tenu par Nisaba, qui assure aussi sa consultation ; Romulus ne fait que router (état et vérification livrés, recherche et export à faire) | § Journal légal |
| Remus | yin | exécute les opérations du relais, uniquement feu vert | § Remus et Castor |
| Castor | yin | un feu par session de présence ; n'écoute que Pollux | § Remus et Castor |
| Paresia-admin | poste client | application de bureau : session de présence, fenêtre web | § Application de bureau |

## Socle commun des démons (`server/commun/`)

**Pollux, Romulus, Castor, Remus, Nisaba et bunkerd l'utilisent** : chaque `__main__.py` se réduit à `lancer()`, les unités livrées sont de `Type=notify`.

| Module | Rôle |
| --- | --- |
| `demon.py` | `lancer()` : options communes, cycle `Type=notify` (prêt, arrêt sur `SIGTERM` et `SIGINT`), codes de sortie de `sysexits.h` |
| `systemd.py` | `sd_notify(3)` (`READY=1`, `STOPPING=1`, `STATUS=`) ; détection du flux journal (`JOURNAL_STREAM`) pour le préfixe de priorité |
| `metriques.py` | registre au format texte Prometheus 0.0.4 ; collecteur `textfile` écrivant `<démon>.prom` |
| `version.py` | version du produit lue une fois dans `VERSION` |
| `journal.py`, `config.py` | journal par niveaux ; types `niveau` et `booleen`, options facultatives |

- **Métriques** : chaque démon écrit dans son propre dossier `metriques/` (par défaut sous `$STATE_DIRECTORY`), jamais dans le dossier de node_exporter. L'administrateur ajoute chaque dossier par une option `--collector.textfile.directory` supplémentaire (option répétable, motif glob admis, node_exporter 1.9.0 de Debian 13). Paresia ne modifie pas la configuration de node_exporter.
- **Liaisons entre démons** : uniquement `jumeaux/1`, sans liaison binaire.
- **Après la 1.0** : topologie N:M entre yin et yang et greffons hôtes résidents ; aucun choix de la 1.0 ne les écarte.

## Comptes et emplacements

- Compte système de Romulus sur yang : `paresia-romulus`.
- Compte `app` sur yang : sans mot de passe, sans `sudo`, réservé à `pollux-session` ; répertoire `/var/lib/paresia-app` (root, 0755), qui porte `.ssh/authorized_keys`.
- Compte `tunnel` sur yin : redirections de sockets Unix seulement, sans shell ; répertoire `/var/lib/paresia-tunnel` par défaut (paramètre `REPERTOIRE_TUNNEL`).
- Aucun compte système n'a de répertoire sous `/home` (FHS 3.0). Les autres comptes système (`paresia-romulus`, `paresia-castor`, `chef`, etc.) ont `/nonexistent`, qui ne doit jamais exister (`adduser(8)` : « This directory should never exist on any Debian system »). Chaque `useradd` porte `--home-dir` et `--no-create-home`.
- Code serveur sous `/usr/local/lib/paresia` ; ce qui varie sous `/var`.

## Flux

- **Présence** : l'application ouvre une session SSH vers le compte `app` de yang ; `pollux-session` relaie vers Pollux ; Pollux demande un jeton à Romulus ; le jeton revient à l'application par la session SSH.
- **Administration** : le navigateur passe par HAProxy, puis lighttpd, puis Romulus, qui contrôle le jeton et aiguille. HAProxy et lighttpd sont installés par l'administrateur (exigences : [serveur web](serveur-web.md)).
- **Relais** : un seul tunnel SSH relie yang à yin et porte les deux paires de jumeaux, chacune sur sa socket, dans un dossier propre à son démon (propriétaire, groupe et mode posés par `tmpfiles.d`). Remus n'exécute une commande que si le feu de Castor est vert pour la session.
- **Liaisons internes** : sockets Unix, contrôle de l'appelant par `SO_PEERCRED`, messages NDJSON ([protocole](protocole.md), § 1 à 3).

## Normes utiles

- SSH : RFC 4251 (architecture), RFC 4254 (connexion, redirections TCP). Les redirections de sockets Unix sont une extension OpenSSH, non normalisée (à vérifier). Format des clés publiques : RFC 4716.
- HTTP : RFC 9110 (sémantique), RFC 9112 (HTTP/1.1). Cookies : RFC 6265 ; l'attribut `SameSite` est décrit par un successeur de cette RFC (à vérifier).
- Flux continus : spécification « Server-sent events » du WHATWG (`text/event-stream`).
- Données : RFC 8259 (JSON), RFC 3629 (UTF-8). NDJSON n'est pas normalisé.
- Nostr : NIP-01, NIP-46, NIP-49 (dépôt `nostr-protocol/nips`) ; BIP-340 pour les signatures Schnorr.
