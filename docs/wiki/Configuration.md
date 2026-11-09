# Configuration

Version du document : 0.1.16 · 2026-11-08 · [Accueil](Accueil.md)

Référence complète : [configuration](../configuration.md), `paresia.conf(5)`, exemple intégral `server/conf/paresia.conf` (côté relais : `server/conf/paresia-relais.conf`).

## Principe : des couches

La configuration se compose de couches ; **la dernière qui définit une option l'emporte**.

| Couche | Emplacement | Qui la lit |
| --- | --- | --- |
| 1 | `/etc/paresia/paresia.conf` | tous |
| 2 | `/etc/paresia/conf.d/NN-*.conf` (deux chiffres, tiret, nom, `.conf` ; ordre alphabétique) | tous |
| 3 | `~/.config/paresia/*.conf` (ou `$XDG_CONFIG_HOME/paresia/`) | **programmes lancés par un utilisateur** seulement (poste client, outils) |
| 4 | variables d'environnement `PARESIA_*` | tous, sauf `pollux-session` |

Conséquences pratiques :

- vos réglages locaux vont dans un fichier de `conf.d/`, par exemple `/etc/paresia/conf.d/50-site.conf` : ne modifiez pas le fichier de base ;
- **les démons n'ont pas de couche utilisateur** : un fichier du répertoire personnel d'un utilisateur ne peut pas changer un démon, même avec des variables d'environnement forgées ; l'environnement d'un démon est fixé par son unité systemd ;
- `pollux-session` ne lit aucune variable d'environnement.

## Format

Fichier INI, sans interpolation. Une section par composant et par domaine : `[<composant>.<domaine>]`. Exemple de réglage local :

```ini
[romulus.http]
max_body = 131072
```

Variable d'environnement correspondante : `PARESIA_<COMPOSANT>_<DOMAINE>_<CLE>` en majuscules, par exemple `PARESIA_POLLUX_SESSIONS_TIMEOUT_S`. La section `[DEFAULT]` est interdite.

## Sections par composant

| Composant | Sections |
| --- | --- |
| Pollux | `pollux.sessions`, `.signature`, `.relay`, `.romulus`, `.castor`, `.transport`, `.journal`, `.metriques` |
| `pollux-session` | `pollux-session.transport`, `.auth` |
| Romulus | `romulus.presence`, `.http`, `.plugins`, `.bunker`, `.relay`, `.nisaba` (facultative), `.activite` (journal d'activité : `detail`, `taille_max`), `.journal`, `.metriques` ; les sections de service viennent des déclarations installées (voir [Architecture et sécurité](Architecture-et-securite.md)) |
| Castor | `castor.tunnel`, `.state`, `.lights`, `.transport`, `.journal`, `.metriques` |
| Remus | `remus.server`, `.castor`, `.light`, `.transport`, `.executor`, `.plugins`, `.journal`, `.metriques` |
| Nisaba | `nisaba.socket`, `.ctl`, `.journal` (avec `niveau`), `.metriques`, `.horaire`, `.etat`, `.source`, `.ots`, `.droits` |
| bunkerd | `bunkerd`, `.etat`, `.outils`, `.controle`, `.web`, `.admin`, `.signature`, `.journal`, `.metriques` |
| sauvegarde | `sauvegarde.stockage` |
| Paresia-admin | `admin.connexion`, `.cle`, `.presence`, `.interface` |

Chaque composant ne lit que ses sections. Les chemins, comptes et uid n'ont **aucun défaut dans le code** ; seules les durées et les limites en ont.

**Les fonctions de Remus (`[remus.plugins]`).** Remus ne sait rien faire par lui-même : il charge des fonctions (des greffons) au démarrage. Quatre options : `fonctions` (dossier des fonctions livrées, `/usr/local/lib/paresia/remus/fonctions` par défaut), `locales` (vos propres fonctions, `/etc/paresia/remus/plugins.d` par défaut), `domaine` (le domaine d'actions servi, `relay` dans l'exemple livré) et `cible` (le nom de Remus dans le catalogue, `principale` par défaut). **Sans `domaine`, Remus ne charge aucune fonction.** Les deux dossiers doivent appartenir à root, sans droit d'écriture pour d'autres : sinon une fonction livrée empêche le démarrage (code 78) et une fonction locale est ignorée, avec une ligne au journal. Le greffon strfry de base livre trois fonctions dans le dossier des fonctions livrées (voir [Administrer le relais strfry](Administration-du-relais-strfry.md)).

## Réglages que vous toucherez le plus

| Option | Défaut | Sens |
| --- | --- | --- |
| `[pollux.signature] challenge_ttl_s` | 60 | durée de validité du défi de présence |
| `[pollux.signature] authorized_keys` | obligatoire | fichier des clés des administrateurs, relu à chaque vérification |
| `[romulus.relay] heartbeat_s` | 30 | battement ; même valeur côté Pollux |
| `[romulus.relay] flux_max_simultanes` | 8 | flux de suivi en direct ouverts en même temps |
| `[romulus.http] export_max_octets` | 8 Mio | taille maximale d'une archive exportée |
| `[nisaba.horaire] conservation_jours` | 365 | conservation du journal légal (1 à 36500) |
| `[sauvegarde.stockage] taille_max_mio` | 64 | taille totale des sauvegardes de procédure |
| `[sauvegarde.stockage] actif` | oui | `non` désactive les sauvegardes |
| `[<démon>.journal] niveau` | `info` | niveau minimal du journal (`debug`, `info`, `notice`, `warning`, `error`, `critical`) ; `--debug` force `debug` |
| `[<démon>.metriques] actif` | `false` | publie les métriques dans `<démon>.prom` (voir [Dépannage](Journaux-metriques-depannage.md)) |

## Appliquer un changement

**Aucune unité ne se recharge à chaud** : tout changement de configuration exige un redémarrage du démon concerné, avec les conséquences expliquées dans [Dépannage](Journaux-metriques-depannage.md) (redémarrer Pollux ou Romulus ferme toutes les sessions de présence, redémarrer Castor remet tous les feux au rouge).

**Validez avant de redémarrer** : Pollux, Romulus, Castor, Remus, Nisaba et bunkerd acceptent `--check`. L'option lit la configuration comme au démarrage, puis sort avec le code 0 sans ouvrir de socket ni de fichier ; une configuration invalide sort avec le code 78. Exemple, avec le compte de l'unité et le même environnement :

```
python3 -P -s -B -m server.castor --check
```

Les codes de sortie suivent `sysexits.h` : 64 usage, 65 données illisibles, 70 erreur interne, 71 erreur du système, 78 configuration (voir `paresia-castor(8)`). L'unité ne relance pas un démon après 64, 65 ou 78.
## Contrôles de sécurité sur les fichiers

Un fichier de configuration n'est accepté que s'il est un fichier régulier (pas un lien symbolique), appartenant à root ou à l'utilisateur courant, sans écriture pour le groupe ni les autres, de 1 Mio au plus (64 fichiers au plus par dossier). Sinon, le démon refuse de démarrer avec un code stable (`config_unsafe_permissions`, `config_unreadable`, `config_too_large`…). **Jamais de secret** dans ces fichiers ni dans les variables `PARESIA_*` : les secrets sont des fichiers.

## Langue

Les messages passent par des catalogues `i18n/<langue>.json` (`fr-FR` par défaut, `en-US`). Les journaux d'audit et le journal légal ne sont jamais traduits, pour rester comparables dans le temps.

## À venir

- Rechargement à chaud : non livré.
- Unités de bunkerd et de Nisaba (donc leur dossier d'état, nécessaire pour activer leurs métriques) : non livrées.
- Emplacement définitif du fichier des clés autorisées : dépend de la gestion des utilisateurs (non fixé).
- Configuration de lighttpd : non livrée par Paresia ; ses exigences et un extrait d'exemple sont dans [Serveur web](../serveur-web.md).
