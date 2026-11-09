# Journaux, métriques et dépannage

Version du document : 0.1.16 · 2026-11-08 · [Accueil](Accueil.md)

Référence : [exploitation](../exploitation.md) (guide d'exploitation), rubrique DIAGNOSTICS de chaque page de manuel, [protocole](../protocole.md) § 9 (codes d'erreur).

## Les journaux

Les démons écrivent **une ligne JSON par événement sur la sortie standard**, que journald collecte. Champs communs : `ts` (UTC, ISO 8601), `level`, `component`, `event`, puis des champs propres à l'événement. Aucun secret, jeton ni contenu de requête n'y figure.

```
journalctl -u castor.service -n 50 --no-pager      # dernières lignes
journalctl -u castor.service -o cat -f             # JSON brut, en continu
journalctl -u castor.service -p warning -b         # avertissements et erreurs depuis le démarrage
journalctl -u castor.service --since '1 hour ago'
```

Résultat attendu pour la première commande : jusqu'à 50 lignes, chacune un objet JSON avec les champs `ts`, `level`, `component` et `event` ; pour la troisième, rien si le démon n'a émis aucun avertissement. La suite : repérez l'événement qui vous intéresse parmi ceux décrits plus bas.

Le tunnel écrit du texte (celui de `ssh`), non du JSON. Sur `backend-relais`, le journal de `sshd` est celui de l'unité `ssh`. Nisaba écrit en plus des lignes `ECHEC_COPIE`, `ECHEC_ACL`, `ECHEC_SCELLEMENT`, `ECHEC_HORODATAGE`, `ECHEC_PURGE`.

Événements à connaître : `startup_failed` (le démon n'a pas démarré ; regardez `cause`, `section` et `option`) et `service_failed` (échec après la mise en service), `peer_unavailable` (le pair est absent), `peer_refused` (une identité non autorisée a tenté une connexion). Pour Remus : `plugins_loaded` (fin du chargement des fonctions, avec leur nombre), `plugin_rejected` (une fonction locale défectueuse est ignorée) et `plugin_skipped` (une fonction écartée parce qu'une condition de chargement n'est pas remplie, par exemple un binaire absent). Pour tous les démons, `cause` vaut `os_error` (avec `errno` numérique, par exemple 98 pour une socket déjà utilisée), `data_unreadable`, `internal_error` ou un code de configuration.

Pour diagnostiquer un `internal_error`, relancez le démon avec `--debug` : une ligne `internal_error_detail` donne la classe de l'exception et au plus les 16 derniers cadres de la pile (fichier relatif, ligne, fonction), jamais de valeur. Le niveau se règle aussi avec `[<démon>.journal] niveau`. bunkerd est sur ce socle : ses échecs de démarrage sont un événement unique `startup_failed` (champ `cause`) ; `state_unreadable` signale en plus un état illisible.

## Le journal d'activité de Romulus

En plus du journal habituel (journald), Romulus tient un **journal d'activité** : qui a demandé quoi, quand, et avec quel résultat (accepté, ou le code du refus). Il sert à répondre à « qu'est-ce qui s'est passé hier soir ? ». Vous le lisez depuis la page « Journaux de Paresia » de l'application d'administration (voir [Premier usage](Premier-usage.md)).

À savoir :

- **Il ne contient jamais de secret** : ni paramètre, ni réponse, ni jeton, ni signature, ni cookie. Un paramètre n'y figure que si le greffon qui le reçoit l'a déclaré non secret, et seulement au niveau 3.
- **Trois niveaux de détail** (option `detail` de `[romulus.activite]`, 1 par défaut) : 1, les actions et les refus ; 2, avec la durée et le service qui a traité ; 3, avec le détail des échanges du protocole, utile au dépannage.
- **Il est borné et circulaire** : par défaut 1 Mio au total ; quand la place manque, les plus anciennes entrées disparaissent. Réglez `taille_max` (de 64 Kio à 16 Mio) si vous voulez garder plus d'historique.
- **Il n'est pas sauvegardé** : c'est un journal d'exploitation, pas le journal légal. Ne le confondez pas avec celui-ci.
- Les requêtes refusées sans session (jeton absent, par exemple) sont **regroupées par minute** : une rafale de mille refus identiques fait une seule entrée avec un compteur, pour qu'elle ne chasse pas les entrées utiles.
- Si le fichier est inutilisable (propriétaire inattendu, droits trop ouverts) ou si l'écriture échoue, l'administration continue de fonctionner ; Romulus écrit l'événement `activity_unusable` ou `activity_write_failed` dans le journal habituel.

Référence : page de manuel `paresia-romulus(8)`, sections JOURNAL D'ACTIVITÉ et DOMAINE KERNEL.

## Les métriques

Le socle commun sait publier des métriques au format texte Prometheus (séries `paresia_up`, `paresia_info`, `paresia_start_time_seconds`, `paresia_log_events_total`) dans un fichier `<démon>.prom`. Deux règles à retenir :

- c'est **désactivé par défaut** ;
- Paresia **n'écrit jamais dans le dossier de node_exporter** : si vous l'utilisez, c'est à vous d'ajouter le dossier `metriques/` de chaque démon à node_exporter par une option `--collector.textfile.directory` supplémentaire.

Pollux, Romulus, Castor, Remus, Nisaba et bunkerd utilisent ce socle : section `[<démon>.metriques]` (`actif`, `dossier`, `periode_s`). À défaut de `dossier`, le fichier va sous `metriques/` dans le dossier d'état fourni par systemd (`STATE_DIRECTORY`). **Les unités livrées de Pollux, Romulus, Castor et Remus ont leur dossier d'état** : `/var/lib/paresia-<démon>` (mode 0711), créé par systemd au démarrage et conservé à l'arrêt, donc inscriptible malgré le système en lecture seule. Les métriques restent **désactivées par défaut** ; pour les activer, mettez `actif = true` dans `[<démon>.metriques]`. Un `dossier` situé ailleurs fait échouer l'écriture (`metrics_write_failed`). Les métriques du journal légal restent celles de `nisaba-ctl metrics`.

## FAQ

**Les commandes sont refusées avec `relay_light_red` alors que ma session est ouverte.**
Suivez la chaîne : Pollux reçoit-il des pings (son journal) ? Le tunnel est-il monté ? Castor reçoit-il les pings (`light_green` dans son journal) ? `peer_unavailable` du côté de Remus signifie que Castor lui-même est injoignable (unité arrêtée, socket absente).

**Un démon redémarre en boucle.**
L'unité relance un démon après 5 s en cas d'échec (sauf codes 64, 65 et 78, erreurs permanentes : usage, données, configuration). Un démon qui boucle a donc un échec transitoire (code 70 ou 71 : voir `journalctl -u <unité>` et `--debug`). Après un 78, l'unité reste arrêtée : l'événement `startup_failed` donne la cause. Codes de configuration : `config_missing` (option obligatoire absente), `config_invalid` (valeur hors bornes), `config_unknown_option` / `config_unknown_section`, `config_unsafe_permissions` (propriétaire ou droits d'écriture), `config_unreadable`.

**Le tunnel ne se monte pas.** Sur `backend-admin`, dans l'ordre :
1. `systemctl status paresia-tunnel.service` : actif ? L'unité relance `ssh` toutes les 5 s.
2. `ss -xl | grep paresia-tunnel` : les deux sockets existent-elles ? Sinon `ssh` n'a pas établi les redirections.
3. Droits des dossiers : `/run/paresia-tunnel` en `root:root` 0711 ; `romulus` en `paresia-tunnel:paresia-romulus` 0710 ; `pollux` en `paresia-tunnel:paresia-pollux` 0710. Écart : `systemd-tmpfiles --create /etc/tmpfiles.d/paresia-tunnel.conf`.
4. Sur `backend-relais` : `journalctl -u ssh -n 30` doit montrer `Accepted publickey for tunnel from <adresse de backend-admin>`.
5. Remus et Castor écoutent-ils ? `systemctl status remus.service castor.service`.
6. Une erreur d'empreinte ? Désactiver la vérification supprimerait la seule preuve que vous parlez à la bonne machine, et un intrus pourrait s'y substituer : contrôlez plutôt l'empreinte par un second canal (téléphone, message distinct du tunnel).
7. L'adresse du relais a-t-elle changé ? Elle est dans `/etc/paresia/tunnel/ssh_config.d/10-relais.conf`.

**Que se passe-t-il si je redémarre un démon ?**

| Unité | Effet |
| --- | --- |
| `pollux`, `romulus` | ferment **toutes** les sessions de présence (elles se rouvrent à la reconnexion de l'application) |
| `castor` | remet **tous** les feux au rouge ; commandes en attente refusées |
| `remus` | n'interrompt pas une opération en cours avant 120 s ; l'arrêt peut durer 150 s |
| `paresia-tunnel` | coupe Pollux et Romulus de leurs jumeaux du relais |

**Puis-je redémarrer sshd pour appliquer un changement ?**
Mieux vaut l'éviter : un redémarrage avec une configuration invalide ferait refuser même vos nouvelles connexions, et vous seriez enfermé dehors. Contrôlez avec `sshd -t` (aucune sortie : la configuration est valide), puis `systemctl reload ssh` avec une session de secours déjà ouverte et testée.

**Une commande d'administration répond 404, 501…**
`404 unknown_action` : l'action n'existe pas dans la liste fermée ou n'est pas routée (les domaines `presence` et `castor` ne le sont pas par HTTP ; du domaine `nisaba`, seules `state/status` et `state/verify` le sont). `501 not_available` : l'action est prévue mais pas encore livrée (c'est le cas du domaine `legal`).

## Gestes risqués et pourquoi

- Redémarrer sshd : voir la question ci-dessus, vous pourriez vous enfermer dehors.
- Toucher à strfry à la main : Paresia suppose l'état qu'elle a posé, et un changement manuel crée un écart qu'elle refuse ensuite d'écraser.
- Éditer `/etc/sudoers.d/paresia-remus` : le fichier est généré, la prochaine installation le refuserait ; une erreur de syntaxe peut aussi bloquer `sudo`.
- Copier ou afficher une clé privée : toute copie est une fuite possible ; elle peut rester dans un historique ou un journal.
- Supprimer une socket de `/run/paresia-*` : le démon qui l'a créée ne la recrée qu'à son redémarrage, et ses clients sont coupés.
- Ajouter un compte au groupe d'un dossier de socket du tunnel : ce compte pourrait alors parler au démon, ce que le cloisonnement veut éviter.
- Laisser l'accès du compte `tunnel` ouvert sans la règle nftables `paresia_relais` : la règle limite ce compte à ce dont il a besoin.

## À venir

- Tableau de bord et alertes Prometheus d'exemple.
- Envoi des journaux vers Loki : option de configuration prévue.
