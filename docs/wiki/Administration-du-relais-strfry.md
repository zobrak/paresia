# Administrer le relais strfry

Version du document : 0.1.19 · 2026-11-08 · [Accueil](Accueil.md)

**En une phrase.** Paresia, sur un strfry existant, lit son état, ses arbres negentropy (index de synchronisation) et peut le redémarrer, par le greffon de base ; elle ne l'installe jamais et ne modifie jamais ni le conteneur ni son image.

Référence : `docs/cahier-des-charges.md` (§ Remus et Castor sur backend-relais), `docs/protocole.md` § 5, `deploy/backend-relais/strfry/strfry.conf`, `deploy/backend-relais/isolation-remus.md`, `paresia-remus(8)`.

strfry est le premier greffon yin : le relais Nostr que Paresia administre. Cette page distingue ce qui est **livré** de ce qui est **prévu**.

## Le rôle de Remus

Remus **ne sait rien faire par lui-même**. Ce sont les greffons qui lui apportent ses capacités, sous forme de **fonctions** : chacune est une brique (un script et son manifeste), et Remus aiguille chaque requête vers la fonction qui la déclare. Il charge les fonctions au démarrage, depuis deux dossiers (`/usr/local/lib/paresia/remus/fonctions` pour celles qui sont livrées, `/etc/paresia/remus/plugins.d` pour les vôtres), et ne sert que les actions qu'elles déclarent : toute autre action est refusée.

Une fonction qui agit sur strfry le fait sous le compte `chef`, avec un `sudo` limité aux seules commandes `docker` qu'elle déclare : un fichier sudoers **généré** à partir des manifestes (`/etc/sudoers.d/paresia-remus`) liste chaque commande et ses arguments exacts. Ne le modifiez pas à la main. Remus n'écoute que Romulus (par le tunnel) et refuse toute commande dont la session n'a pas le feu vert de Castor ; seules les deux actions qui décrivent le catalogue des fonctions (liste et description, en lecture seule) répondent sans attendre le feu.

Le principe des greffons : un greffon **ne livre pas le produit** qu'il administre. Il déclare avec quelles versions il fonctionne ; Paresia reste étranger au produit installé. Le greffon officiel de strfry sera livré clé en main (configuration qui fonctionne, procédure d'installation soignée), découpé en briques : celles qui **lisent** seront installées par défaut, celles qui **modifient** seulement à votre demande (exception de la version de base : le redémarrage du conteneur est posé par défaut).

## Ce qui est livré

- Le **greffon strfry de base** (côté Remus, `paresia-yin-strfry`) : trois fonctions, posées par le script d'installation du relais dans `/usr/local/lib/paresia/remus/fonctions` (voir ci-dessous).
- Remus : socle, chargement des fonctions, exécuteur de commandes et de scripts, flux d'événements sur le fil, générateur de sudoers, comptes, règle nftables, unités systemd, isolation (voir `isolation-remus.md`).
- Un **`strfry.conf` complet**, toutes les valeurs écrites explicitement. Points d'attention pour les administrateurs de relais :
  - `relay.auth.restrictedReadKinds = "4"` : le défaut amont (`"4, 1059"`) bloquerait l'application **bitchat**, qui ne gère pas NIP-42 ; ses messages privés sont des kind 1059 ;
  - `restrictReadToInvolvedPubkey = true` ;
  - `rejectEventsNewerThanSeconds = 1800` (les dates des kind 1059 de bitchat iOS sont décalées de plus ou moins 900 s) ;
  - `filterValidation.requireAuthorOrTag` non activé (filtres `#g`, `#r`, `#x`).
  Servir bitchat est un **objectif à évaluer**, non une règle absolue.
- Un **plugin d'écriture** (`writePolicy`) en Python, exécuté dans le conteneur (donc `python3` dans l'image), qui alimente le journal légal. Le kind 20000 (canaux géographiques de bitchat) reste journalisé ; les kinds éphémères non journalisés (20001, présence…) prennent un chemin rapide sans écriture. Si l'écriture du journal échoue, la publication est **acceptée** et la ligne complète va dans journald. Une liste noire (fichier `blocklist.txt`, lue par le plugin) refuse les écritures qu'elle désigne ; illisible au démarrage, le relais accepte les écritures et journalise une alerte `ECHEC_LISTE_NOIRE`, pour ne pas couper le service.
- Négentropie : ne créez jamais d'arbre negentropy prédéfini (`strfry negentropy add` et `build`) ; sans arbre, `NEG-OPEN` ne laisse fuir aucun kind 4 ou 1059. Les fichiers livrés n'en créent pas.

## Les trois fonctions de base

| Action | Ce qu'elle fait | Réponse |
| --- | --- | --- |
| `relay/state/status` | prouve que le conteneur `strfry` répond et que la base est lisible (`strfry info`) | la version de la base (`db_version`) |
| `relay/sync/trees` | liste les arbres negentropy existants, en **lecture seule** (jamais d'ajout ni de reconstruction) | les lignes de la liste (arbre, filtre, taille, empreinte) |
| `relay/container/restart` | redémarre le conteneur `strfry` (arrêt gracieux de deux minutes au plus) | succès ou `command_failed` |

Ces fonctions agissent sous le compte `chef`, avec exactement trois commandes `sudo` (`docker exec strfry /app/strfry info`, `docker exec strfry /app/strfry negentropy list`, `docker restart strfry`) inscrites dans le fichier sudoers généré. Elles supposent un conteneur Docker nommé `strfry` : **le script d'installation du relais vérifie, avant toute modification, que l'image de ce conteneur correspond à la version que le greffon déclare** (l'étiquette de l'image doit être `4cd3cf6` ; l'étape se saute avec `--sauter produit`) et s'arrête sinon. Le script ne crée, ne démarre ni ne modifie ce conteneur.

Prudence : **redémarrer le conteneur interrompt le relais** pour ses clients le temps du redémarrage ; la page du catalogue de l'application demande une confirmation avant de lancer une action.

## Ce qui est prévu (contrat, non livré)

Le cahier prévoit les opérations ci-dessous, par domaines. **Aujourd'hui, seules les trois fonctions ci-dessus sont livrées** : toute autre action `relay/…` répond `not_available` (HTTP 501, Romulus convertissant le refus de Remus). La liste est un contrat, non un état ; chaque famille deviendra une ou plusieurs briques du greffon strfry.

| Famille | Actions prévues |
| --- | --- |
| état | état, métriques, NIP-11, journal, avertissements, connexions, suivi en direct |
| événements | compter, kinds, lister, montrer, supprimer par filtre, supprimer par âge |
| sauvegarde | exporter, importer, lister |
| synchronisation | télécharger, comparer, arbres |
| conteneur | redémarrer, arrêter, démarrer, configuration, compacter |
| modération | signalements, bannir, débannir, importer des bannissements, journal, liste de sourdine (kind 10000, signée par le bunker), publier la liste |

## Ce qu'il ne faut pas faire

Ne démarrez pas, n'arrêtez pas et ne modifiez pas strfry (configuration, données) à la main en parallèle de Paresia : Remus ne lance que les fonctions de ses dossiers. Hors de ce cadre, vous pouvez interrompre un relais en service.

## Côté reverse proxy

Le plugin ne valide pas l'adresse de connexion qu'il reçoit : votre reverse proxy DOIT écraser l'en-tête d'adresse du client, et le port de strfry doit être publié **uniquement vers ce proxy** (`bind = "0.0.0.0"` est l'adresse dans le conteneur). Un essai de charge et le contrôle de la poignée de main WebSocket au proxy restent à faire par vous.

## À venir

- Toutes les opérations de la table ci-dessus, sous forme de fonctions du greffon strfry (aujourd'hui, Romulus renvoie `not_available`), et les pages web du relais.
- Image strfry reconstructible : Dockerfile et paquets ajoutés **non établis** dans le dépôt.
- Sauvegarde et restauration de la base strfry par BorgBackup : à concevoir (principe 8 du cahier).
