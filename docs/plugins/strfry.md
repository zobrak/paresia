# Greffon du relais strfry

Version du document : 0.1.19 · 2026-11-08.

Le relais strfry est un greffon livré avec Paresia (trois fonctions de base aujourd'hui) : la paire `paresia-yin-strfry` (côté Remus, qui exécute les fonctions) et `paresia-yang-strfry` (côté Romulus, qui aiguille le domaine `relay` vers Remus). Les deux sont versionnées ensemble. Le noyau ignore tout de ce domaine : il le transporte (`docs/protocole.md`, § 5).

## État

Le greffon de base livre trois fonctions, sous `deploy/backend-relais/usr/local/lib/paresia/remus/fonctions/` : `relay/state/status` (la base répond et est lisible), `relay/sync/trees` (arbres negentropy, lecture seule) et `relay/container/restart` (redémarrage du conteneur). Les autres actions du tableau ci-dessous sont le contrat prévu ; chacune deviendra un manifeste de fonction chargé par Remus. Toute action `relay/…` absente du catalogue de Remus reçoit `unknown_action` de Remus (`not_available`, 501, par HTTP). Les paramètres de chaque action seront fixés avec la fonction qui l'implémente. Le détail des trois fonctions livrées est dans `docs/wiki/Administration-du-relais-strfry.md` et `paresia-remus(8)`.

## Comment l'enficher

- Côté Remus : `domaine = relay` dans `[remus.plugins]` (`docs/configuration.md`) ; le catalogue publié par `relay/catalog/list` et décrit par `relay/catalog/describe` est celui des fonctions chargées.
- Côté Romulus : la déclaration `paresia-yang-strfry.toml` (domaine `relay`, `catalogue = "pair"`, destination Remus) ; les actions du tableau y sont déclarées, les deux actions de catalogue sont transmises à Remus.

## Actions du domaine `relay`

Le numéro entre parenthèses est celui de l'opération dans la liste « Opérations » du cahier des charges.

Les actions livrées sont marquées « livrée » dans la colonne État ; toutes les autres sont prévues.

| Action | Menu | État |
| --- | --- | --- |
| `state/status` | (1) | livrée |
| `state/metrics` | (2) | prévue |
| `state/nip11` | (3) | prévue |
| `state/log` | (4) | prévue |
| `state/warnings` | (5) | prévue |
| `state/connections` | (6) | prévue |
| `state/follow` | (7) | prévue |
| `events/count` | (10) | prévue |
| `events/kinds` | (11) | prévue |
| `events/list` | (12) | prévue |
| `events/show` | (13) | prévue |
| `events/delete-filter` | (14) | prévue |
| `events/delete-age` | (15) | prévue |
| `backup/export` | (20) | prévue |
| `backup/import` | (21) | prévue |
| `backup/list` | (22) | prévue |
| `sync/download` | (30) | prévue |
| `sync/compare` | (31) | prévue |
| `sync/trees` | (32) | livrée |
| `container/restart` | (40) | livrée |
| `container/stop` | (41) | prévue |
| `container/start` | (42) | prévue |
| `container/config` | (43) | prévue |
| `container/compact` | (44) | prévue |
| `moderation/reports` | (60) | prévue |
| `moderation/ban` | (61) | prévue |
| `moderation/unban` | (61) | prévue |
| `moderation/ban-import` | (61) | prévue |
| `moderation/log` | (62) | prévue |
| `moderation/mute-list` | (63) | prévue |
| `moderation/publish-mute-list` | (63) | prévue |

`moderation/mute-list` et `moderation/publish-mute-list` partagent le numéro 63 ; `moderation/ban`, `moderation/unban` et `moderation/ban-import` partagent le numéro 61. Le suivi en direct (`state/follow`) est un flux (`docs/protocole.md`, § 4.3).
