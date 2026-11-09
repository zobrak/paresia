# Développement Paresia

Version du document : 0.1.19 · 2026-11-08. Public : développeur, contributeur.

Ce document regroupe ce qui sert au développement : poste de travail, tests, intégration continue, garde contre les secrets, contenu du dépôt et contrats des briques communes. Le README en donne la version courte. Les règles de contribution sont dans [CONTRIBUTING.md](../CONTRIBUTING.md) ; les conventions de code, de versions et de documentation dans [conventions](conventions.md).

## Sommaire

1. Vue d'ensemble · 2. Branches · 3. Poste de développement · 4. Style et contributions · 5. Tests et intégration continue (5.1 garde contre les secrets, 5.2 banc d'essai) · 6. Contenu du dépôt (6.1 socle commun, 6.2 fonctions enfichables, 6.3 services greffés, 6.4 pages web d'un greffon, 6.5 pose des pages) · 7. État · 8. Historique

## 1. Vue d'ensemble

Paresia est un noyau d'administration à distance en Python (bibliothèque standard d'abord) : deux couples de démons (Romulus et Remus, Pollux et Castor) reliés par un tunnel SSH, des greffons (bunkerd, Nisaba, strfry) et un client Paresia-admin. Les composants et leurs flux sont décrits dans [architecture](architecture.md) ; la spécification qui fait foi est le [cahier des charges](cahier-des-charges.md).

## 2. Branches

- `main` : branche des versions publiées, gérée par le mainteneur.
- Une branche de développement reçoit les modifications, sans avance rapide ; la contribution passe par une demande de fusion ([CONTRIBUTING.md](../CONTRIBUTING.md#2-proposer-une-modification)).

## 3. Poste de développement (Debian 13)

| Outil | Vérification |
| --- | --- |
| git | `git --version` |
| python3 ≥ 3.11 et python3-venv (3.13 sur Debian 13, version de la CI) | `python3 --version` puis `python3 -m venv --help` |
| `pytest` | `python3 -m pytest --version` |

Étapes :

1. Cloner le dépôt et se placer à sa racine.
2. Installer les paquets de test listés dans [prérequis](prerequis.md#6-développement-et-ci-hors-prérequis-dexploitation), § 6 (dont `python3-cryptography`, et PyQt6 pour les tests du client, qui sont sautés en son absence).
3. Lancer la suite : `python3 -m pytest -q`. Le dossier temporaire des tests est propre à chaque exécution (`conftest.py`, § 5) et placé sous `.pytest_cache/` (`pytest.ini`), car `/tmp` peut être monté `noexec`.
4. Avant chaque commit, lancer la recherche de secrets (§ 5.1).

## 4. Style et contributions

Les règles de style, de tests, de commits et de documentation sont dans [CONTRIBUTING.md](../CONTRIBUTING.md) et [conventions](conventions.md). Toute option, variable de configuration ou code d'erreur ajouté est documenté dans la même demande de fusion (page de manuel mdoc, document concerné, [CHANGELOG.md](../CHANGELOG.md)).

## 5. Tests et intégration continue

- `pytest` ; un test au moins par critère d'acceptation.
- Clés et identités de test générées pour l'occasion ; vecteurs publiés seulement dans `tests/vecteurs/`, marqués `scan-secrets: vecteur-public`.
- CI (`.github/workflows/ci.yml`) : recherche de secrets (`tools/hooks/scan_secrets.py --all`), puis `python3 -m pytest -q -rs` sous Python 3.13. Décision D108 : la CI tourne dans un conteneur `debian:trixie` (Debian 13, systemd 257, comme la cible), hébergé par le runner `ubuntu-latest` (systemd 255, dont le résultat de `systemd-analyze verify` diffère). Étapes : (a) paquets système (liste : `docs/prerequis.md`, § 6), avec levée d'une éventuelle exclusion des pages de manuel de l'image ; (b) extraction du dépôt ; (c) création d'un compte non privilégié `ci`, d'uid celui du propriétaire de l'espace de travail (refus si c'est 0) ; (d) recherche de secrets ; (e) environnement virtuel avec les paquets du système (`--system-site-packages`, pour voir `python3-cryptography`) puis installation de `pytest` et de `tools/codex-bridge/requirements.txt` (dépendance des tests du pont de développement) ; (f) contrôle des outils (`systemd-analyze`, `man`, `visudo`, `nft`, `setfacl`, `getfacl`, `shellcheck`, `git` et la page `systemd.exec(5)`) : la CI échoue si l'un manque, afin qu'un paquet mal nommé ne se traduise jamais par un saut silencieux des tests ; (g) tests sous le compte `ci`, avec échec si l'uid est 0. Les tests de propriétaire, sautés en root, sont ainsi exécutés comme sur un poste de développement. `pyright` n'est pas un prérequis du projet.
- **Un seul pytest à la fois par dépôt** (D105, maintenue par D124) : deux exécutions simultanées dans le même dossier vidaient le dossier temporaire commun et faisaient échouer des tests au hasard. Lancer la suite complète seule ; pour reproduire une exécution concurrente, utiliser un dossier jetable distinct (`--basetemp`).
- **Dossier temporaire propre à chaque exécution** (D124, `conftest.py` et `pytest.ini`) : chaque exécution reçoit `.pytest_cache/t<pid>` (chemin court, car les sockets Unix sont limitées à 108 octets). Un verrou `flock` sur `.pytest_cache/t<pid>.lock`, tenu jusqu'à la fin du processus, marque l'exécution en cours ; au démarrage, les dossiers dont le verrou est libre (exécution terminée ou interrompue) sont supprimés, les autres sont laissés. `pytest.ini` ne fixe plus de `--basetemp` ; un `--basetemp` passé en ligne de commande l'emporte. Le mécanisme est propre aux systèmes Unix (`fcntl`).
- **Refus par `SO_PEERCRED`** : un serveur qui refuse un pair peut fermer la connexion avant la fin de l'écriture du client. Un test de refus tolère donc cette fermeture précoce (`BrokenPipeError`, réinitialisation de connexion), vérifie toujours le refus et ne masque aucune autre erreur.

### 5.1 Garde contre les secrets et les références privées

`tools/hooks/scan_secrets.py` contrôle le contenu indexé (`--staged`, via `git show :0:<fichier>`) ou tout l'arbre (`--all`). Sortie : 0 si aucun constat ni erreur ; 1 si un constat ou une erreur ; 2 si l'usage est incorrect. `--help` affiche l'aide. Le crochet `tools/hooks/pre-commit` est activé par `git config core.hooksPath tools/hooks`. Il est **strict par défaut** : il lance `scan_secrets.py --staged --strict` et exige le fichier local de motifs privés décrit plus bas. Un contributeur externe qui n'a pas ce fichier désactive explicitement le mode strict par `git config paresia.gardeStricte false` (réglage local) : le crochet lance alors `scan_secrets.py --staged`, qui applique les secrets et les motifs génériques seuls, avec un avertissement si aucun fichier de motifs privés n'existe.
Deux contrôles :

- **Secrets** : motifs de clés et de jetons, fichiers interdits (`secrets/`, `.env`, `*.key`, `*.pem`). Exception : les vecteurs publiés de `tests/vecteurs/`, marqués sur leur ligne.
- **Garde « installation privée »** : refuse toute référence à une installation réelle. Elle s'applique au contenu indexé ligne par ligne et aux noms de fichiers, en `--staged` comme en `--all`. Deux sources de motifs :
  - **motifs génériques**, inscrits dans le script et toujours actifs : liens du service d'assistant vers des artefacts ou des partages ; chemins `/home/<nom>/`, sauf les noms-gabarits de la constante `HOME_GABARITS` ; adresses IPv4 privées (RFC 1918), validées avec le module `ipaddress`. Les plages d'exemple (RFC 5737) ne sont jamais refusées ;
  - **motifs privés**, dans un fichier local hors dépôt, décrit ci-dessous.

#### Fichier local de motifs privés

- **Emplacement** : par défaut `.motifs-prives.txt`, fichier local ignoré par Git, à la racine de l'arbre de travail principal du dépôt. La clé Git `paresia.motifsPrives` (`git config paresia.motifsPrives <chemin>`, chemin absolu ou relatif à cette racine) indique un autre emplacement. Un fichier nommé `.motifs-prives.txt` indexé est refusé comme fichier interdit. Depuis un worktree lié, le script remonte à l'arbre principal par `git rev-parse --git-common-dir` (`git-rev-parse(1)`).
- **Codage** : UTF-8. Une marque d'ordre des octets (BOM) est tolérée.
- **Lignes** : une expression rationnelle Python (module `re`) par ligne. Les lignes vides sont ignorées. Une ligne dont le premier caractère non blanc est `#` est un commentaire. Une ligne fait 256 caractères au plus ; un motif plus long est refusé.
- **Contenu** : au moins un motif. En `--strict`, un fichier absent, illisible, vide ou sans motif fait refuser le commit, avec une aide à la création.
- **Droits** : le fichier DEVRAIT être en `0600` (RFC 2119). Le crochet ne vérifie pas les droits.
- **Motifs simples** : éviter les répétitions imbriquées, qui peuvent bloquer le moteur par retour arrière.
- **Normalisation** : les motifs subissent la même normalisation que le texte (NFKC, retrait des caractères de catégorie Cf).
- **Motif invalide** : le commit est refusé ; le numéro de la ligne est indiqué, le motif n'est pas recopié.
- **Variable** `PARESIA_MOTIFS_PRIVES` : chemin de remplacement, honoré seulement si `PARESIA_GARDE_TESTS=1` (tests). Sinon elle est ignorée, avec un avertissement.
- **Exceptions par texte exact** : un fichier facultatif `garde-exceptions.txt`, placé dans le même dossier que le fichier de motifs, retire un texte précis d'une ligne avant la recherche des motifs privés (les motifs génériques s'appliquent toujours à la ligne entière). Une ligne par exception : le chemin du fichier indexé, une tabulation, le texte exact ; `#` commence un commentaire ; UTF-8, 65 536 octets au plus. Une ligne mal formée ou un fichier illisible est une erreur. Ce fichier est local : un `garde-exceptions.txt` indexé est refusé.
- **Exclusions par chemin** : un fichier facultatif `tools/hooks/garde-exclusions.txt` de l'arbre de travail courant liste, un chemin exact par ligne (`#` pour un commentaire, UTF-8, 65 536 octets au plus), les fichiers exclus de la garde « installation privée » (jamais par contenu). Absent ou illisible : aucune exclusion, sans message. Ce fichier est propre au dépôt de développement et n'est pas publié.

Exemple inventé, à ne pas reprendre tel quel pour une installation réelle :

```
# exemple inventé
(?i)\bmon-hote\b
```

Le fichier de motifs ne se met jamais dans le dépôt. Le script n'est exclu que du contrôle de secrets (`SELF`).

#### Messages

Un constat s'affiche `fichier:ligne : référence à l'installation privée (motif générique <libellé>)`, ou `(motif privé n° <N>)` où `<N>` est le numéro de la ligne du motif. Le message ne donne jamais la valeur trouvée, ni le motif, ni un extrait ; les parties d'un nom de fichier qui correspondent sont masquées. Les caractères de contrôle sont filtrés.

#### Limite

La CI n'installe que `pytest` pour ses tests. Elle lance `--all` sans `--strict` : l'absence du fichier de motifs n'y produit qu'un avertissement.

Tests : `tests/test_scan_secrets.py` et `tests/test_garde_installation.py`. Les valeurs fabriquées y sont construites à l'exécution.

### 5.2 Banc d'essai CI (job `banc`)

La CI compte deux jobs : `verifications` (secrets puis `pytest`, § 5) et `banc`. Le job `banc` s'exécute sur `ubuntu-latest` avec Docker, sans montage de l'hôte, et réalise le test d'intégration avec un sshd réel exigé par le [protocole](protocole.md), § 8.

- **Montage** : deux conteneurs Debian 13 (systemd 257, OpenSSH 10.0) sur un réseau Docker dédié aux adresses RFC 5737, `backend-admin` (sshd, Pollux, Romulus, tunnel) et `backend-relais` (sshd, Castor, Remus). Les unités et la configuration livrées sont utilisées sans adaptation ; les images sont décrites par `tests/banc/admin.containerfile` et `tests/banc/relais.containerfile`.
- **Orchestration** : `python3 -m banc.orchestrateur` (`PYTHONPATH=tests`), avec les sous-commandes `construire`, `demarrer`, `scenario`, `journal` et `arreter`, enchaînées par le workflow. Le journal et l'arrêt s'exécutent même après un échec. Le module n'appelle aucun moteur à l'import ni pour `--aide`. Il refuse d'exporter un journal où une donnée sensible est détectée (`tests/banc/journal.py`).
- **Scénario** : un client simulé (`tests/banc/client.py`, avec un agent SSH) parcourt E0 (tunnel établi, sockets présentes), E1 (défi signé et ouverture côté Pollux), E2 (session côté Romulus), E3 (action aiguillée vers Remus, réponse HTTP 501 `not_available`), E4 (feu vert de Castor), E5 (fermeture, feu rouge), E5 bis (silence : le feu expire sans fermeture de Pollux) et E6 (jeton révoqué : HTTP 403 `token_unknown`).
- **Lire le résultat** : ouvrir le job `banc` dans GitHub Actions. Chaque étape y reçoit un verdict « observée », « non observée » ou « non exécutée ». Un échec nomme l'étape (`Échec : E3.`) et consigne la commande, son code de retour et la fin de sa sortie d'erreur. L'état `degraded` de systemd dans un conteneur (par exemple `systemd-modules-load.service`) est attendu et journalisé avec `systemctl --failed`.
- **Artefact `banc-journal`** : publié par `actions/upload-artifact` même en cas d'échec ; trois fichiers texte, `scenario.txt` (verdicts, lignes observées, réponses des sondes, versions, modes des sockets, écarts connus), `backend-admin.txt` et `backend-relais.txt` (journaux des unités). Il ne contient ni jeton, ni signature, ni défi, ni clé privée (la clé du client est supprimée après chargement dans l'agent).
- **Écarts connus du banc** (aussi écrits dans `scenario.txt`) : conteneurs neufs sans sauvegarde de procédure ; serveur HTTP joué par `www-data` ; ni nftables ni sudoers de Remus ; connexions TCP sortantes du compte `tunnel` non essayées ; essais négatifs d'isolation entre comptes non couverts (à faire à l'étape 9 de la procédure du tunnel).
- **Tests hors ligne** : `tests/test_banc_ci.py` contrôle le banc sans moteur (en-têtes, versions suivies, absence de secrets et d'adresses non RFC 5737).

## 6. Contenu du dépôt

| Chemin | Contenu |
| --- | --- |
| `server/commun/` | module commun `jumeaux/1` : NDJSON, `SO_PEERCRED`, client, journal JSON, configuration en couches (`config.py`, D29) |
| `server/commun/demon.py`, `systemd.py`, `metriques.py`, `version.py` | socle commun des démons (D145), utilisé par Pollux, Romulus, Castor, Remus, Nisaba et bunkerd ; contrat au § 6.1 |
| `server/pollux/` | Pollux : sessions de présence, battement, relais des jetons et des pings |
| `server/romulus/` | Romulus : sessions, jetons, frontal HTTP, aiguillage par déclarations de services greffés (§ 6.3), suivi en direct par flux d'événements (`flux.py`) ; le producteur du journal légal reste à faire |
| `server/commun/services.py` | déclarations de services greffés de Romulus (`paresia-yang-<nom>.toml`, § 6.3) |
| `server/bunkerd/` | bunkerd 2.0.0 : socket d'administration, `bunker.json` versionné, signature de la liste de sourdine (`signature.py`) |
| `server/sauvegarde/` | outil de sauvegarde et de restauration des procédures, avec empreintes SHA-256 (`docs/man/paresia-sauvegarde.8`) |
| `server/commun/sshsig.py`, `cles_ssh.py` | lecture des signatures SSHSIG et des clés SSH pour le défi signé de Pollux |
| `admin/` | Paresia-admin, poste client : configuration (`admin/app/config.py`, `admin/app/conf/paresia-admin.conf`), catalogues et filtrage (`textes.py`), session de présence (`presence.py`), signature du défi (`signature.py`), lecture de la clé publique (`cles.py`), fenêtre (`fenetre.py`, `controleur.py`) ; `admin/web/` : socle des pages web, avec attributs de chargement refusés (`dom.js`), conteneur propre à chaque page et réponses d'une page quittée ignorées (`app.js`) |
| `server/nisaba/` | Nisaba, processus annexe du journal légal : planificateur, copie, scellement, horodatage, droits, vérification, purge, CLI |
| `server/strfry/` | plugin `writePolicy` du journal légal en Python |
| `deploy/` | procédures, unités systemd, `strfry.conf` livré, nftables, sudoers, déclarations de services (`backend-admin/`, `backend-relais/`) |
| `server/pollux/session.py`, `server/bin/pollux-session` | commande forcée SSH `pollux-session` du compte `app` |
| `server/conf/` | `paresia.conf` : exemple unique de yang (D33, [configuration](configuration.md)) ; `paresia-relais.conf` : exemple de yin (D45) |
| `i18n/` | catalogues `fr-FR.json` et `en-US.json` (codes d'erreur, messages des outils, clés d'interface `ui_*` de l'application, D58, D109) |
| `docs/` | cahier des charges, protocole, conventions, architecture, décisions, index (`README.md`), `man/` (pages de manuel), `wiki/` (guide de l'administrateur) |
| `tools/hooks/` | recherche de secrets et garde « installation privée » (`scan_secrets.py`), crochet `pre-commit` (§ 5.1) |
| `tests/` | tests unitaires et d'intégration ; `conftest.py` à la racine ; `tests/banc/` : banc d'essai (§ 5.2) |
| `.github/workflows/ci.yml` | recherche de secrets puis tests, dans un conteneur Debian 13 sous un compte non root, puis banc d'essai (§ 5) |

Fichiers racine : `README.md`, `CONTRIBUTING.md`, `CHANGELOG.md`, `SECURITY.md` (provisoire), `LICENSE` (AGPL-3.0), `VERSION`, `pytest.ini`, `conftest.py`, `.gitignore`. `INSTALL.md` (guide d'installation) y figure aussi ; `docs/dependances.md` non plus (voir `docs/licences-tierces.md`).

### 6.1 Contrat du socle commun des démons

`server/commun/demon.py`, `lancer(Demon, argv, environ)` ; à appeler depuis le fil principal (les signaux y sont installés).

- **Options** : `--help`, `--version`, `--check` (lit et valide la configuration, puis sort avec 0 sans démarrer), `--debug` (journal au niveau `debug`), `--config FICHIER`. Toute autre option : usage sur la sortie d'erreur, code 64.
- **Version** : lue une fois dans le fichier `VERSION` de la racine du code installé (`version.py`) ; `--version` affiche `<démon> (Paresia) <version>` (GNU Coding Standards, § 4.7). Fichier illisible ou invalide : sortie en erreur, sans version inventée.
- **Codes de sortie** (`sysexits.h`, `os.EX_*`) :

| Code | Nom | Cas |
| --- | --- | --- |
| 0 | `EX_OK` | succès, arrêt normal, `--help`, `--version`, `--check` valide |
| 64 | `EX_USAGE` | option inconnue |
| 65 | `EX_DATAERR` | exception dérivée de `ErreurDonnees` (données illisibles) |
| 70 | `EX_SOFTWARE` | toute autre exception |
| 71 | `EX_OSERR` | `OSError` |
| 78 | `EX_CONFIG` | `ErreurConfiguration` |

- **Journal** : un échec avant la fin du démarrage produit l'événement `startup_failed`, un échec après `cycle.pret()` l'événement `service_failed` ; champs `cause` (code stable), `section`, `option`, `errno`. Le message d'une exception n'est jamais publié. Sur un terminal, un message localisé (clés `commun_startup_failed`, `commun_service_failed`) va sur la sortie d'erreur.
- **Cycle** : `Type=notify` ; le corps appelle `cycle.pret()` (`READY=1`), `SIGTERM` et `SIGINT` envoient `STOPPING=1` puis libèrent `cycle.attendre()`. `attendre()` boucle sur `Event.wait(timeout=0,1)` : un signal reçu par un autre fil ne réveille pas forcément le fil principal (D162). Chien de garde : après la 1.0 (D146).
- **Diagnostic** : au niveau `debug`, un échec écrit en plus l'événement `internal_error_detail` (`classe`, 64 caractères au plus ; `pile`, au plus les 16 derniers cadres du paquet `server`, chemin relatif, ligne, fonction ; aucune valeur).
- **Unités** : `NotifyAccess=main`, `RestartPreventExitStatus=64 65 78`, `TimeoutStartSec=30`, pas de `WatchdogSec=`.
- **Installation** : le fichier `VERSION` est copié à côté de `server/` ; sans lui, tout démon sort en 70 (`internal_error`).
- **Tests** : `tests/test_commun_demon.py`, `test_commun_systemd.py`, `test_commun_metriques.py`, `test_commun_version.py`, `test_commun_journal_niveaux.py`, `test_config_couches.py`.

### 6.2 Fonctions enfichables : catalogue, chargeur et manifeste (D148, D154)

Socle : `server/commun/catalogue.py` (descripteurs, introspection, noms Varlink), `plugins.py` (chargeur), `sortie.py` (contrat de sortie), `privileges.py` (commandes privilégiées neutres). **Remus les utilise** (`server/remus/fonctions.py`, `Executeur.lancer_script` pour la voie « script ») ; aucun autre démon ne le fait encore. Romulus, lui, n'utilise pas ce chargeur : il lit des déclarations de services (§ 6.3). Protocole : [protocole](protocole.md), § 5.5.

**Liste des actions du noyau.** Il n'existe plus de liste d'actions écrite à la main dans `server/commun/jumeaux.py` : `server/commun/noyau.py` décrit les actions de `presence/*` et de `castor/*` par des descripteurs (paramètres, bornes, erreurs), et l'ensemble `ACTIONS` de `jumeaux.py` en est calculé. Les actions des greffons n'y figurent pas : chaque démon admet celles de son catalogue. Les tableaux d'actions de `docs/protocole.md` sont contrôlés contre leur source (le catalogue du noyau pour `presence` et `castor`, les déclarations livrées pour les greffons), non générés. Un test de neutralité (`tests/test_noyau_neutre.py`) vérifie qu'aucun nom de greffon (strfry, bunker, Nisaba, journal légal) n'apparaît dans le code du noyau (`server/commun`, `romulus`, `remus`, `pollux`, `castor`) et qu'il n'y charge aucun mécanisme de greffon propre à un langage (`importlib`, `__import__`, points d'entrée, `pluggy`, `stevedore`, `yapsy`) ; toute exception se justifie dans le test, une ligne par entrée.

Remus enfiché : dossier des fonctions livrées `/usr/local/lib/paresia/remus/fonctions` et dossier des fonctions locales `/etc/paresia/remus/plugins.d` (FHS 3.0), remplaçables par `[remus.plugins] fonctions` et `locales`, tous deux à root et sans écriture groupe ni autres. `[remus.plugins] domaine` (un seul en 1.0) est le domaine servi ; sans lui, aucune fonction n'est chargée ; `cible` nomme Remus dans le catalogue (défaut `principale`). Le script est lancé par son chemin absolu seul, sans interpréteur dans l'argv, avec l'environnement `LC_ALL=C` et `/` pour dossier courant ; les paramètres validés arrivent en JSON (ASCII) sur l'entrée standard ; sa sortie d'erreur n'est ni transmise ni journalisée. Les gabarits de paramètres sont ceux de l'exécuteur (`Texte` borné à 4096 caractères, `Entier`, `Choix`, `Hexadecimal`, `ListeEntiers` à 1024 éléments au plus), sans nouveau validateur. Le générateur de sudoers (`python3 -m server.remus.sudoers`) lit les seuls manifestes ; chaque commande privilégiée passe d'abord par un rendu d'essai (refus par défaut). Limite assumée (D153) : avec sudo, les droits sont ceux du compte de Remus ; `privilege` est publié, non appliqué. Exemple : `server/remus/exemples/fonctions/exemple_echo` et son manifeste, installés nulle part.

Une fonction = deux fichiers de même nom, dans un dossier **livré** et/ou un dossier **local** : `<nom>` (script exécutable, lancé hors processus par le démon) et `<nom>.toml` (manifeste TOML, 64 Kio au plus). Le chargeur lit et contrôle ; il n'exécute ni n'importe rien. Nom : `[a-z][a-z0-9_]{0,63}` ; 256 fonctions au plus par dossier. Contrôle des fichiers : dossier et ancêtres sans lien symbolique, propriétaire attendu, aucune écriture groupe ou autres ; script avec bit d'exécution du propriétaire, ni setuid ni setgid.

| Clé du manifeste | Obligatoire | Contenu |
| --- | --- | --- |
| `format` | oui | entier, `1` (autre : `plugin_format_unsupported`) |
| `forme` | non | `"ponctuel"` (défaut, seule forme admise) |
| `greffon` | oui | `paresia-yin-<nom>` ou `paresia-yang-<nom>` selon le côté du démon (`<nom>` : minuscules, chiffres, `-`, 32 caractères au plus) |
| `nom` | oui | égal au nom du fichier |
| `action` | oui | `domaine/objet/opération` ; le domaine est celui du démon ; les suffixes `catalog/list` et `catalog/describe` sont réservés |
| `delai_s` | oui | nombre fini > 0, au plus le plafond de délai de `jumeaux/1` |
| `privilege` | non | étiquette publiée (`utilisateurs`) ; **non appliquée** à l'appel : avec sudo, les droits sont ceux du compte du démon |
| `sortie_max` | non | entier, 65 536 par défaut |
| `flux` | non | doit valoir `false` (pas de flux dans cette forme) |
| `parametres` | non | tableau de tables, 16 au plus : `nom`, `type` (`texte`, `entier`, `choix`, `hexadecimal`, `liste_entiers`), `obligatoire` (vrai par défaut) et les bornes du type (`docs/protocole.md`, § 5.5) |
| `journaliser` | non | noms de paramètres dont la valeur est journalisée ; les autres ne le sont jamais |
| `erreurs` | non | codes que le script peut renvoyer (défaut `command_failed`) ; chacun doit être un code connu du démon |
| `commandes_privilegiees` | non | tableau de tables `operation` (`exec` ou `restart`) et `arguments` (éléments fixes `[A-Za-z0-9/._+-]`, ou `{parametre = "nom"}` désignant un paramètre `choix`, `hexadecimal` ou `entier`) ; 16 commandes, 16 arguments ; aucune syntaxe de l'outil d'élévation |
| `requiert` | non | `binaires` et/ou `fichiers` : chemins absolus (8 au plus) ; condition de chargement vérifiée par `stat` seulement |

Exemple minimal :

```toml
format = 1
greffon = "paresia-yin-exemple"
nom = "etat"
action = "relay/service/etat"
delai_s = 10
erreurs = ["command_failed"]
```

Politique : tout défaut d'un élément **livré** est fatal au démarrage du démon ; tout défaut d'un élément **local** fait ignorer le dossier local entier (rien n'en est gardé) et alimente la liste des rejets ; un nom, une action ou un nom de méthode Varlink en double est refusé. Une condition `requiert` non remplie écarte la fonction sans erreur (`plugin_skipped`). Le démon fournit un vérificateur des commandes privilégiées (`verifier_privileges`) ; sans lui, elles ne sont pas vérifiées au chargement ; Remus le fournit toujours (rendu d'essai par le générateur de sudoers, `fail-closed`). Codes et événements : `docs/protocole.md`, § 5.5.

### 6.3 Services greffés de Romulus : déclarations `paresia-yang-<nom>.toml` (D148, D150, D154)

`server/commun/services.py` lit, contrôle et valide les déclarations ; `server/romulus/` (`__init__.py`, `aiguillage.py`, `flux.py`, `http.py`) n'a plus aucun nom de greffon : destinations, paramètres, codes, ping, suivi et export viennent des déclarations. Une déclaration est un fichier TOML (des données, jamais du code), `paresia-yang-<nom>.toml`, dans le dossier **livré** `/usr/local/lib/paresia/romulus/services` et/ou le dossier **local** `/etc/paresia/romulus/services.d` (FHS 3.0), remplaçables par `[romulus.plugins] livrees` et `locales`. Contrôle des fichiers : dossier et ancêtres sans lien symbolique, propriétaire root, aucune écriture groupe ou autres, 64 Kio et 64 fichiers au plus (comme le chargeur de § 6.2). Cinq déclarations sont livrées (dont `paresia-yang-webui`, l'interface web) dans `deploy/backend-admin/usr/local/lib/paresia/romulus/services/`.

| Clé | Obligatoire | Contenu |
| --- | --- | --- |
| `format` | oui | entier, `1` (autre : `service_format_unsupported`) |
| `forme` | non | `"ponctuel"` (défaut, seule forme admise ; autre : `service_form_unsupported`) |
| `greffon` | oui | `paresia-yang-<nom>`, égal au nom du fichier sans `.toml` |
| `domaine` | oui | minuscules, chiffres, `_` ; ni `presence` ni `castor` ; unique parmi les déclarations |
| `cible` | non | nom de cible du catalogue (défaut `principale`) ; identique pour toutes les déclarations |
| `section` | si une destination | section `[romulus.<section>]` de la configuration ; jamais `general`, `presence`, `http`, `plugins`, `journal`, `metriques` ; unique |
| `obligatoire` | non | vrai par défaut ; faux : service facultatif (absent sans section ni socket, aucune route, 501 `not_available`) ; une option `duree` ou `limite` d'un service facultatif DOIT avoir un défaut |
| `sans_destination` | non | vrai : domaine routé sans service (toute action répond 501 `not_available`) ; incompatible avec `section`, `options`, `ping`, `suivi` et un catalogue |
| `destination` | non | nom du service dans le journal (défaut : le domaine) |
| `ping`, `ping_oubli` | non | `ping` : ping de la session auprès d'un second pair avant chaque transmission, au plus une fois par battement ; `ping_oubli` : codes du service qui font oublier ce ping |
| `catalogue` | non | `aucun` (défaut), `declaration` (Romulus sert `catalog/list` et `catalog/describe` depuis les descripteurs) ou `pair` (ces deux actions sont transmises au service ; `params_transmis` possible) |
| `codes` | non | codes de retour admis du service (codes connus de `jumeaux/1`, 64 au plus) ; `not_available` est toujours admis ; tout autre code devient `internal_error` |
| `[[options]]` | si une destination | 32 au plus : `nom` (`[a-z][a-z0-9_]*`), `type` (`chemin`, `uid`, `duree`, `limite`), `defaut` (durée ou limite), `maximum` (limite, au plus 16 Mio), `inferieure_a` (durée strictement inférieure à une autre option), `role` |
| `[[actions]]` | oui | 256 au plus : `nom` (sans le domaine), `erreurs`, `suivi` (au plus une action, flux d'événements), `export` (réponse binaire), `params_transmis` (mode `pair` sans `parametres`), `[[actions.parametres]]` (16 au plus : `nom`, `type`, `bornes`, `obligatoire`), `journaliser` (liste de noms de paramètres déclarés de l'action, sans doublon : ceux dont la valeur est non secrète ; voir le journal d'activité) |
| `[[pages]]` | non | 16 au plus, pages d'administration du greffon : exactement `id` (`[a-z][a-z0-9-]{0,31}`, unique dans le greffon), `titre_cle` (`ui_` suivi de 1 à 100 caractères `[a-z0-9_]`, et commençant par `ui_<greffon>_`, tirets du nom remplacés par `_`) et `script` (`[a-z0-9][a-z0-9._-]{0,63}\.js (sans `..`)`) ; toute autre forme : `service_declaration_invalid` |

Rôles des options : `socket` (`chemin`) et `uid` (`uid`) toujours ; `delai` (`duree`) et `max_line` (`limite`) facultatifs ; avec une action `suivi` : `flux_max` (`limite`), `battement` et `ping_delai` (`duree`) ; avec `ping` : `ping_socket` (`chemin`), `ping_uid` (`uid`), `ping_delai` et `battement`. Romulus lit une option par son rôle, jamais par son nom. Au plus un service déclare `ping` ou `suivi` (un seul plafond de flux). Types de paramètres : ceux de `catalogue.py` (`texte`, `entier`, `choix`, `hexadecimal`, `liste_entiers`, `liste_texte`) ; Romulus ne contrôle que les noms, la présence et le type JSON, le service contrôle les valeurs.

Politique : un défaut d'une déclaration **livrée** est fatal au démarrage (`ErreurConfiguration`, code 78) ; un défaut d'une déclaration **locale** la fait ignorer (le dossier local entier si le dossier ou ses ancêtres sont en cause) et alimente la liste des rejets et l'événement `service_declaration_rejected` (`code`, `scope`, `file` : nom de base filtré, jamais de chemin). Une déclaration locale ne remplace jamais un domaine, un greffon ou une section déjà déclaré. Codes : `service_declaration_invalid`, `service_format_unsupported`, `service_form_unsupported`, plus les codes `plugin_*` de § 6.2 pour les fichiers (`docs/protocole.md`, § 5.5).

Chargement en deux temps (`server/romulus/__init__.py`) : `configuration()` lit d'abord `[romulus.plugins]` seule, en lecture partielle, charge les déclarations, puis relit toute la configuration en lecture stricte avec le schéma composé par les déclarations ; une section sans déclaration chargée est refusée (`config_unknown_section`). Les déclarations sont chargées une seconde fois par `Romulus.__init__` (défaut connu, à corriger). Extensions de `server/commun/config.py` et règle socket et uid : `docs/configuration.md`, § Aiguillage de Romulus. Tests : `tests/test_romulus_services.py`, `test_romulus_aiguillage.py`, `test_config_couches.py`.

### 6.4 Pages web d'un greffon : contrat avec le client

Un greffon peut apporter des pages d'administration. Le client (`admin/web/greffons.js`) les découvre au démarrage, avant de construire le menu ; le noyau du client ne connaît aucun produit.

**Fichiers servis** (même origine que les pages du noyau, sous `/admin/greffons/`) :

| Fichier | Rôle |
| --- | --- |
| `index.json` | index des greffons, JSON (RFC 8259), `Content-Type: application/json`, 64 Kio au plus |
| `<nom>/i18n/<langue>.json` | catalogue des textes du greffon, `fr-FR` et `en-US`, 1 Mio au plus |
| `<nom>/<script>.js` | un script par page |

**Index, format 1.** Objet à deux clés exactement : `format` (entier `1`) et `greffons` (tableau de 16 éléments au plus ; au-delà, l'index entier est refusé). Un greffon est un objet à deux clés exactement : `nom` et `pages` (16 au plus). Une page est un objet à trois clés exactement : `id`, `script`, `titre_cle`.

| Champ | Forme |
| --- | --- |
| `nom`, `id` | `[a-z][a-z0-9-]{0,31}` ; un nom présent deux fois écarte tous ses exemplaires ; un `id` déjà pris par une autre page écarte la page |
| `script` | `[a-z0-9][a-z0-9._-]*\.js`, sans `..` ni `/` ; l'adresse chargée est recomposée par le client |
| `titre_cle` | `ui_` suivi de minuscules, chiffres et `_` (100 au plus) |

**Catalogue.** Objet de chaînes. Le client lit la langue courante, sinon `fr-FR`. Toute clé DOIT commencer par `ui_<greffon>_` (le nom du greffon avec ses tirets remplacés par `_`) ; une clé qui existe déjà dans le noyau ou chez un autre greffon fait refuser le greffon entier. Les textes s'ajoutent à ceux du noyau, qui gardent la priorité, et sont filtrés à l'affichage (invariant 7). Aucun texte en dur dans un script.

**Script de page.** Il est chargé par un élément `script` du même site, un script à la fois, dans l'ordre alphabétique des greffons puis des `id`. Il DOIT :

1. enregistrer sa page par `Paresia.enregistrer` **pendant son exécution** (enregistrement synchrone) ; une page non enregistrée à la fin du chargement est écartée ;
2. utiliser le seul **conteneur** que le noyau lui passe (obligatoire), construire son contenu par `Paresia.el` et tester `Paresia.actif(conteneur)` avant toute écriture après un échange asynchrone ;
3. passer son conteneur à `Paresia.diagnostiquer`.

**Délais.** 10 s par lecture de document ou par chargement de script ; 30 s pour l'ensemble de la découverte. À l'échéance, les greffons restants sont abandonnés et le menu du noyau est construit avec les pages déjà enregistrées.

**Défaillances.** Un index absent, illisible ou invalide, un greffon, un catalogue ou une page refusés ne gênent jamais les pages du noyau. Chaque refus est signalé dans la zone de diagnostic par un code constant (`absent`, `type`, `taille`, `json`, `delai`, `index_invalide`, `descripteur_invalide`, `nom_invalide`, `nom_en_double`, `page_invalide`, `catalogue_indisponible`, `catalogue_invalide`, `cle_hors_prefixe`, `cle_en_collision`, `page_en_collision`, `script_introuvable`, `delai_depasse`, `non_enregistree`, `delai_total`), sans recopier de valeur reçue.

**Confiance.** Un script de greffon a les mêmes droits que le noyau de la page : il partage l'objet global `Paresia`. Installer un greffon, c'est installer du code d'administration. Exigences côté client : [exigences du client](exigences-client.md), § 6. Tests : `tests/test_admin_web_greffons.py`.

### 6.5 Pose des pages et de l'index à l'installation

Les pages d'un greffon sont des fichiers statiques que **l'installation** pose ; Romulus n'ajoute aucune route et ne génère rien à l'exécution. L'étape `web` de `installer-backend-admin.sh` (après la pose des déclarations) fait ceci :

- **Dossier de Paresia** `/usr/local/share/paresia/web/` (FHS 3.0) : copie de `admin/web/` (l'interface), puis, sous `greffons/<nom>/`, le dossier de chaque greffon du clone (`deploy/backend-admin/usr/local/share/paresia/web/greffons/<nom>/`, `<nom>` en `[a-z][a-z0-9-]{0,31}`) : un script par page et `i18n/fr-FR.json` (obligatoire), `i18n/en-US.json` (facultatif). Propriétaire root, dossiers 0755, fichiers 0644, aucun lien symbolique ; tout autre type de fichier dans le clone est refusé.
- **Index** `greffons/index.json` : écrit puis vérifié par `python3 -P -s -B -m server.romulus.pages` (`--ecrire`, puis `--verifier` ; voir `paresia-romulus-pages(8)`). Il décrit les greffons dont la déclaration **livrée** porte des `[[pages]]` ; les déclarations locales n'y figurent jamais. Format : § 6.4. Chaque catalogue est contrôlé (objet de chaînes, toutes les clés préfixées `ui_<greffon>_`) ; un greffon défectueux fait échouer la commande, sans index partiel, et le script retire alors l'index.
- **Sauvegarde et remplacement** : un dossier déjà installé qui diffère du clone est refusé (code 78) sauf avec `--code-remplacement-confirme oui`, qui le sauvegarde puis le remplace. Retour arrière : restauration ou retrait du dossier.
- **Interface web** : elle est elle-même un greffon, déclaré par `paresia-yang-webui.toml` (domaine `webui`, sans destination, sans action, sans page) ; ses fichiers sont ceux de `admin/web/`.
- **Aucun serveur web** : le script n'installe pas de serveur web, n'écrit aucune configuration de serveur web et ne recharge aucun service. L'administrateur du serveur web fait servir le dossier sous `/admin/` ; les exigences sont dans la documentation du serveur web.

Tests : `tests/test_romulus_pages.py`, `tests/test_romulus_services.py`, `tests/test_scripts_installation.py`.

## 7. État

Ce qui est livré, ce qui ne l'est pas et la feuille de route : [README](../README.md), § « État réel » et § « Feuille de route ».
## 8. Historique

Le journal des versions est dans [CHANGELOG.md](../CHANGELOG.md). Les décisions et leurs conséquences d'un retour en arrière sont dans [décisions](decisions.md).
