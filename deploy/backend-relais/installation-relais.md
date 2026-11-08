# Installation de backend-relais

**Cette procédure est remplacée par le script `deploy/backend-relais/installer-backend-relais.sh`** (page de manuel `installer-backend-relais(8)`, `--aide`). Utilisez le script ; ce document n'est conservé que comme détail de chaque étape (intention, vérifications, retours arrière).

SPDX-License-Identifier: AGPL-3.0-or-later

Paramètres : fixez les variables d'environnement avant de lancer les étapes.

| Variable | Rôle | Défaut |
| --- | --- | --- |
| `DEPOT` | Copie propre du dépôt | obligatoire, sans défaut |
| `REPERTOIRE_TUNNEL` | Répertoire personnel réel de tunnel | `/var/lib/paresia-tunnel` |
| `PROFIL` | Configuration relais ou partage | `relais` |
| `CODE_REMPLACEMENT_CONFIRME` | Confirmation après arrêt des démons | `non`, fixer `oui` pour remplacer |
| `PORT_ESSAI` | Port TCP libre du contrôle local | `49152` |

Version du document : 0.1.16 · 2026-11-08 · public : administrateur. Historique : `CHANGELOG.md`.

À exécuter **par vous seul, sur backend-relais, une étape à la fois**.
Confirmez le résultat avant la suivante. Gardez une deuxième session ouverte.
Aucun secret n'est saisi ni copié.
Les blocs supposent un shell bash interactif conservé entre étapes.

Convention : **aucun shell root n'est requis ni conseillé** (ni `sudo -i`, ni `su`, ni `sudo sh -c`). Vous
travaillez sous un compte ordinaire doté de `sudo` ; chaque commande privilégiée porte son propre `sudo` et le
chemin absolu de l'exécutable. Un administrateur déjà root, sans `sudo`, lance les mêmes commandes sans le
préfixe `sudo`. Les redirections vers un fichier privilégié passent par `sudo /usr/bin/tee`. Les blocs sont
écrits pour **bash**. Les sous-shells `( set -euo pipefail … )` sont des sous-shells ordinaires de votre
compte : chaque commande privilégiée qu'ils contiennent a son propre `sudo`.

**Commandes lancées par `sudo` : liste descriptive, pas un sudoers à recopier.** Elle décrit ce que cette
procédure lance. Plusieurs entrées valent root si on les autorise sans arguments figés (`env`, `python3`, `tee`,
`install`, `sed -i`, `chown`, `runuser`, `find -exec`, `tar`, `cp`, `mv`, `visudo`, `systemd-run`, `systemctl` sans unité) ;
`env … python3 -P -m server.sauvegarde` et `runuser … python3 -c` ne peuvent pas être restreintes et sont propres
à cette installation. Pour un sudoers, figez un par un l'exécutable, le compte cible et les arguments exacts
(unités pour `systemctl`, chemins pour `install`, `tee`, `sed`, `chown`, `mv`, `cp`).

- outil de sauvegarde : `/usr/bin/env PYTHONPATH=/run/paresia-installation PARESIA_SAUVEGARDE_CONFIG=… /usr/bin/python3 -P -m server.sauvegarde` (`jeu`, `releve`, `copier`, `retrouver`, `lister`, `restaurer`) ;
- comptes : `/usr/sbin/groupadd`, `/usr/sbin/useradd`, `/usr/sbin/usermod`, `/usr/sbin/userdel`, `/usr/sbin/groupdel`, `/usr/bin/passwd -S` ;
- fichiers : `/usr/bin/install`, `/usr/bin/tar`, `/usr/bin/cp -a`, `/usr/bin/mv -T`, `/usr/bin/chown`, `/usr/bin/find … -exec /usr/bin/chmod`, `/usr/bin/sed -i`, `/usr/bin/tee`, `/usr/bin/cat`, `/usr/bin/diff`, `/usr/bin/grep`, `/usr/bin/test`, `/usr/bin/stat`, `/usr/bin/ls` ;
- sudoers et réseau : `/usr/sbin/visudo -c -f`, `/usr/bin/sudo` (`-V`, `-n -l -U chef`, `-u chef`), `/usr/sbin/nft` (`--version`, `list`, `-c -f`, `delete table inet paresia_relais`) ;
- services : `/usr/bin/systemctl` (`daemon-reload`, `start`, `stop`, `status`, `show`, `enable`, `disable`, `is-enabled` pour `paresia-nftables`, `castor` et `remus`), `/usr/bin/systemd-analyze verify`, `/usr/bin/systemd-run --wait --pipe --collect`, `/usr/bin/journalctl -u <unité> -n 30 --no-pager` ;
- essais : `/usr/sbin/runuser -u tunnel|nobody|chef -- /usr/bin/python3 -c …`, `/usr/sbin/runuser -u chef -g chef -G paresia-castor-etat -- /usr/bin/python3 -c …` (lecture de l'état de Castor), `/usr/bin/env -i PYTHONPATH=… /usr/sbin/runuser -u nobody -- /usr/bin/python3 -P -s -B -m server.remus.sudoers`.

La fonction `outil` est définie à l'étape 1, après la copie réussie du code.

Portée de `set -e` : la session interactive ne doit **jamais** recevoir
`set -e`, `set -o pipefail` ni `exit`, qui fermeraient la session (y compris la
session de secours). Tout bloc qui s'arrête à la première erreur est donc écrit
dans un sous-shell `( … )` qui commence par `set -euo pipefail` : `set -e`, et
`exit`, ne valent que dans les parenthèses. Les variables utiles aux étapes
suivantes (`DEPOT`, `JEU`, `TRAVAIL`, `REPERTOIRE_TUNNEL`, `PROFIL`,
`CONFIGURATION`) sont paramétrées hors du sous-shell puis
**exportées** pour y être visibles. `PORT_ESSAI` est fixé et exporté dans le
sous-shell de son essai local. Un sous-shell ne renvoie rien au shell
appelant : lisez son code de sortie (`echo $?`) ou son dernier message, et
n'enchaînez jamais l'étape suivante après un échec. Les blocs sans parenthèses
sont en lecture seule. Rappel (bash(1), `set -e`) : l'option est ignorée dans
une condition de `if`, de `&&` ou de `||` ; ces blocs ne s'appuient donc sur elle
que pour des commandes isolées.

| Livrable du dépôt | Destination |
| --- | --- |
| `server/` sans `conf/` ni `__pycache__/` | `/usr/local/lib/paresia/server/` |
| `VERSION` (racine du dépôt) | `/usr/local/lib/paresia/VERSION` (à côté de `server/`, lu par les démons) |
| `server/conf/paresia-relais.conf` | `/etc/paresia/paresia.conf` ou `conf.d/20-relais.conf` |
| `deploy/backend-relais/etc/sudoers.d/paresia-remus` | `/etc/sudoers.d/paresia-remus` |
| `deploy/backend-relais/etc/nftables/paresia-relais.nft` | `/etc/nftables/paresia-relais.nft` |
| `deploy/backend-relais/etc/systemd/system/paresia-nftables.service` | `/etc/systemd/system/paresia-nftables.service` |
| `isolation-remus.md` | Décisions et essais repris aux étapes 9 à 13 |

**Identifiants : le script les fait attribuer par le système.** Le script `installer-backend-relais.sh`
crée comptes et groupes sans numéro imposé (`--system`), relève les identifiants choisis dans la plage
système de `login.defs(5)` et les reporte dans la copie installée de la configuration ; un compte existant
conforme est repris, tout autre est refusé (code 78). Les numéros ci-dessous et ceux des commandes de cette
procédure pas à pas sont des exemples.

Exemple de numéros : groupes primaires et comptes paresia-castor 970, chef 971,
tunnel 972 ; groupes de sockets paresia-castor-tunnel 973,
paresia-remus-tunnel 974, paresia-castor-etat 975. Le sudoers de
Remus est généré à partir des fonctions installées : aucune fonction livrée, aucun droit sudo ; les unités de Castor et de Remus sont installées aux étapes 9 à 14. Le tunnel, sshd
et les clés relèvent de la procédure du tunnel, hors de ce document.
Chef reste hors docker, sudo, adm et des groupes de lecture du journal.
Les opérations d'état qui lisent actuellement le journal restent à traiter
ultérieurement, sans privilège supplémentaire de chef. Pas de métrique pour cette
unité ; compteur des refus nftables laissé à un développement ultérieur.

## Étape 1 — Prérequis et relevés initiaux

Intention : vérifier Debian 13, les outils et conserver les relevés sans secret.

```bash
export DEPOT
(
set -euo pipefail
: "${DEPOT:?Fixez DEPOT vers une copie propre du dépôt}"
cat /etc/os-release
systemctl --version
/usr/bin/sudo --version
sudo /usr/sbin/nft --version
python3 --version
command -v docker python3 ss
if test -x /usr/bin/sudo; then
    echo '/usr/bin/sudo présent'
else
    echo '/usr/bin/sudo absent : ne pas poursuivre' >&2
fi
if test -x /usr/sbin/nft && test -x /usr/sbin/visudo && test -x /usr/sbin/runuser; then
    echo '/usr/sbin/nft, visudo et runuser présents'
else
    echo '/usr/sbin/nft, visudo ou runuser absent : ne pas poursuivre' >&2
fi
test -d "$DEPOT/server"
)
echo "Code de sortie : $?"
```

Résultat attendu : Debian 13, Python compatible avec le dépôt, systemd relevé
(comparer les pages locales à systemd 257.13 étudié), nft à `/usr/sbin/nft` et
sudo/Docker aux chemins de la configuration. Sinon arrêter et adapter les
chemins explicitement avant installation. **sudo >= 1.9.10**, sinon arrêter :
sudoers(5), Regular expressions : « Starting with version 1.9.10, it is possible
to use regular expressions ». Version minimale établie le 2026-11-06 sur deux sources
installées avec sudo 1.9.16p2 : la page sudoers(5) citée ci-dessus et le journal
des versions `/usr/share/doc/sudo/NEWS.gz`, section « What's new in Sudo
1.9.10 » : « Added support for using POSIX extended regular expressions in
sudoers rules. » À porter dans `docs/prerequis.md`. Le
générateur n'accepte que les verbes `exec` et `restart` ; l'ajout d'autres verbes devra
se faire en citant sudoers(5). L'outil `ss` (iproute2) sert à l'essai de
l'étape 7.
Ne pas remplacer un pare-feu déjà actif ni une unité de ce nom déjà active.

Sauvegardes : toute copie de sauvegarde et tout relevé passent par l'outil
`python3 -P -m server.sauvegarde`, lancé depuis une copie du code appartenant à `root` (`PYTHONPATH` sur cette copie, fixé par la fonction `outil` ; voir plus bas). Il range les jeux datés sous `/var/backups/paresia/relais/<AAAAMMJJ-HHMMSS>/`
(dossiers `root:root` 0700), refuse de copier une clé privée, borne la taille totale et supprime les
jeux les plus anciens au-delà. Réglages : section `[sauvegarde.stockage]` de la configuration
(`actif`, `taille_max_mio`, `dossier`, `machine`) ; pendant cette procédure, la configuration livrée du
dépôt (copiée avec le code) s'applique (variable `PARESIA_SAUVEGARDE_CONFIG`) : pour désactiver les sauvegardes, exporter
`PARESIA_SAUVEGARDE_STOCKAGE_ACTIF=non` dans votre shell avant tout appel de `outil`, qui la transmet à l'outil (aucune copie n'est alors faite et les
retours arrière ci-dessous échouent faute de sauvegarde : ne les lancer qu'en connaissance de cause).
`restaurer` ne supprime jamais un fichier sans avoir retrouvé sa sauvegarde et répond 5 sinon ; chaque
retour arrière s'arrête alors sans rien modifier. `TRAVAIL` (`/run/paresia-installation`) est un dossier de travail temporaire
(`root` 0700, sous `/run`) pour les fichiers de préparation : il disparaît au redémarrage.

Lancement de l'outil : l'outil s'exécute en root ; il ne s'exécute donc jamais depuis le clone du
dépôt, que d'autres comptes peuvent avoir modifié. Le bloc suivant copie d'abord `server/` du clone dans le
dossier de travail `/run/paresia-installation` (`root` 0700, sur tmpfs) par `install -o root -g root`
(fichiers 0644, dossiers 0755, propriétaire `root`), en refusant tout lien symbolique ou fichier spécial dans la
source (échec et arrêt) ; `__pycache__` n'est pas copié. Seule une copie réussie définit la fonction `outil`, qui fixe
`PYTHONPATH` (`/run/paresia-installation`) et `PARESIA_SAUVEGARDE_CONFIG` ; un échec la supprime : sans copie
réussie, aucun appel n'aboutit. L'outil est
lancé par `python3 -P -m` (option `-P` : ni le répertoire courant ni celui d'un script n'est ajouté à
`sys.path`). Si la copie existe déjà (reprise de la procédure), le bloc s'arrête : retirez d'abord
`/run/paresia-installation/server` à la main (commande destructive : ne viser que ce dossier), puis rejouez le bloc.

ATTENTION : si le message « Copie du code impossible » s'affiche, arrêtez-vous ; corrigez la source (lien symbolique ou fichier spécial dans `server/`, copie déjà présente) avant de poursuivre.

```bash
(
set -euo pipefail
test -d "$DEPOT/server"
test ! -L "$DEPOT/server"
test -z "$(find "$DEPOT/server" ! -type d ! -type f -print -quit)"
sudo /usr/bin/test ! -e /run/paresia-installation/server
sudo /usr/bin/install -d -o root -g root -m 0700 /run/paresia-installation
find "$DEPOT/server" -name __pycache__ -prune -o -type d -printf '%P\0' | while IFS= read -r -d '' d; do sudo /usr/bin/install -d -o root -g root -m 0755 "/run/paresia-installation/server/$d" < /dev/null; done
find "$DEPOT/server" -name __pycache__ -prune -o -type f -printf '%P\0' | while IFS= read -r -d '' f; do sudo /usr/bin/install -o root -g root -m 0644 -- "$DEPOT/server/$f" "/run/paresia-installation/server/$f" < /dev/null; done
)
if test "$?" = 0; then
  outil() { sudo /usr/bin/env PYTHONPATH=/run/paresia-installation PARESIA_SAUVEGARDE_CONFIG=/run/paresia-installation/server/conf/paresia-relais.conf ${PARESIA_SAUVEGARDE_STOCKAGE_ACTIF:+PARESIA_SAUVEGARDE_STOCKAGE_ACTIF="$PARESIA_SAUVEGARDE_STOCKAGE_ACTIF"} /usr/bin/python3 -P -m server.sauvegarde "$@"; }
else
  unset -f outil
  echo 'Copie du code impossible : ne pas poursuivre' >&2
fi
```

Résultat attendu : aucun message ; `/run/paresia-installation/server` existe et appartient à `root`.

ATTENTION — création de dossiers root:root 0700 sous /var/backups/paresia (sauvegardes) et d'un dossier de travail sous /run ; aucune clé n'est copiée.

```bash
TRAVAIL=/run/paresia-installation
export TRAVAIL
sudo /usr/bin/install -d -o root -g root -m 0700 "$TRAVAIL" || echo 'Échec du dossier de travail : ne pas poursuivre' >&2
JEU_DOSSIER=$(outil jeu) || echo 'Échec du jeu de sauvegarde : ne pas poursuivre' >&2
JEU=${JEU_DOSSIER##*/}
export JEU
(
set -euo pipefail
test -n "$TRAVAIL"
test -n "$JEU"
{ getent passwd paresia-castor chef tunnel || test "$?" -eq 2; } | outil releve comptes-avant --jeu "$JEU"
{ getent group paresia-castor chef tunnel paresia-castor-tunnel paresia-remus-tunnel paresia-castor-etat || test "$?" -eq 2; } | outil releve groupes-avant --jeu "$JEU"
sudo /usr/sbin/nft list ruleset | outil releve nft-initial --jeu "$JEU"
)
echo "Code de sortie : $?"
```

Résultat attendu : code de sortie 0 ; le dossier du jeu (`python3 -P -m server.sauvegarde lister`) contient
les relevés `comptes-avant`, `groupes-avant` et `nft-initial` sous `releves/`. Avec les sauvegardes
désactivées, l'outil affiche « sauvegardes désactivées » et ne crée rien (code 0). Toute erreur autre
que noms absents impose l'arrêt. `JEU` est le nom du dossier daté, repris à toutes les étapes ; dans une
nouvelle session, recréer `DEPOT`, rejouer la copie du code (elle définit la fonction `outil`), recréer `TRAVAIL`, puis fixer `JEU`
au nom relevé par `python3 -P -m server.sauvegarde lister`.
Retour arrière : conserver ces relevés pour le diagnostic ; aucun service modifié.

## Étape 2 — Contrôle des identifiants et des bornes (lecture seule)

Intention : refuser toute collision avant de créer un groupe ou un compte.

```bash
(
set -euo pipefail
if getent passwd 970 971 972 973 974 975; then exit 1; else test "$?" -eq 2; fi
if getent group 970 971 972 973 974 975; then exit 1; else test "$?" -eq 2; fi
if getent passwd paresia-castor chef tunnel paresia-castor-tunnel paresia-remus-tunnel paresia-castor-etat; then exit 1; else test "$?" -eq 2; fi
if getent group paresia-castor chef tunnel paresia-castor-tunnel paresia-remus-tunnel paresia-castor-etat; then exit 1; else test "$?" -eq 2; fi
awk '/^[[:space:]]*(SYS_UID_MIN|SYS_UID_MAX|SYS_GID_MIN|SYS_GID_MAX|UID_MIN|GID_MIN)[[:space:]]/ {print}' /etc/login.defs
awk '/^[[:space:]]*(FIRST_SYSTEM_UID|LAST_SYSTEM_UID)[[:space:]]*=/ {print}' /etc/adduser.conf
)
echo "Code de sortie : $?"
```

Résultat attendu : les quatre getent ne produisent **aucune sortie** (code 2
pour absence). Sinon arrêter : ne jamais réutiliser un compte existant.
Choisir une autre plage (les numéros de `server/conf/paresia-relais.conf`
sont des exemples), puis faire revoir ensemble configuration, procédure et cohérence des
tests ; ne pas poursuivre avec les numéros de cette procédure.

Lire les bornes effectives de la cible et vérifier que **970 à 975** sont
compris dans chacune des plages. Si une valeur est absente, consulter les
valeurs par défaut **des pages de la cible**, ne pas déduire une borne d'une
sortie vide. login.defs(5), SYS_UID_MIN/SYS_UID_MAX : « Range of user IDs used
for the creation of system users by useradd or newusers. » ;
SYS_GID_MIN/SYS_GID_MAX : « Range of group IDs used for the creation of system
groups by useradd, groupadd, or newusers. » adduser.conf(5),
FIRST_SYSTEM_UID/LAST_SYSTEM_UID : « specify an inclusive range of UIDs from
which UIDs for system users can be dynamically allocated. »
Retour arrière : sans objet. Arrêter si hors plage ou indéterminé.

## Étape 3 — Groupes puis comptes

Intention : fixer le répertoire personnel de tunnel sous /var/lib, créer les
identités sans mot de passe, puis les seuls groupes supplémentaires de tunnel.

ATTENTION — modification des fichiers d'identités ; ne poursuivre qu'après l'étape 2 entièrement validée.

```bash
REPERTOIRE_TUNNEL=${REPERTOIRE_TUNNEL:-/var/lib/paresia-tunnel}
export REPERTOIRE_TUNNEL
(
set -euo pipefail
test ! -e "$REPERTOIRE_TUNNEL" && test ! -L "$REPERTOIRE_TUNNEL" || exit 1
case "$REPERTOIRE_TUNNEL" in /*) ;; *) exit 1 ;; esac
REPERTOIRE_TUNNEL=$(realpath -m -- "${REPERTOIRE_TUNNEL:?}")
case "$REPERTOIRE_TUNNEL" in /home|/home/*)
    echo 'Répertoire sous /home refusé ; aucun compte existant ne sera déplacé' >&2
    exit 1 ;;
esac
sudo /usr/sbin/groupadd --system --gid 970 paresia-castor
sudo /usr/sbin/groupadd --system --gid 971 chef
sudo /usr/sbin/groupadd --system --gid 972 tunnel
sudo /usr/sbin/groupadd --system --gid 973 paresia-castor-tunnel
sudo /usr/sbin/groupadd --system --gid 974 paresia-remus-tunnel
sudo /usr/sbin/groupadd --system --gid 975 paresia-castor-etat
sudo /usr/sbin/useradd --system --uid 970 --gid 970 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin paresia-castor
sudo /usr/sbin/useradd --system --uid 971 --gid 971 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin chef
sudo /usr/sbin/useradd --system --uid 972 --gid 972 --home-dir "$REPERTOIRE_TUNNEL" --no-create-home --shell /usr/sbin/nologin tunnel
sudo /usr/bin/install -d -o root -g root -m 0755 "$REPERTOIRE_TUNNEL" "$REPERTOIRE_TUNNEL/.ssh"
sudo /usr/sbin/usermod -aG paresia-castor-tunnel,paresia-remus-tunnel tunnel
)
echo "Code de sortie : $?"
```

Résultat attendu : comptes verrouillés sans mot de passe utilisable ; aucun
mot de passe défini. Groupes primaires créés avant tous les comptes. La procédure du tunnel
traitera le contenu et les modes de `.ssh` et `authorized_keys`.

Sources installées : groupadd(8), --gid : « The numerical value of the group's ID. » ;
--system : « Create a system group. » useradd(8), --uid : « The numerical value of
the user's ID. » ; --gid : « The name or the number of the user's primary group. » ;
--system : « Create a system account. » ; --no-create-home : « Do not create the user's home directory,
even if the system wide setting from /etc/login.defs (CREATE_HOME) is set to yes. » ;
--home-dir : « The new user will be created using HOME_DIR as the value for the user's login directory.
The default is to append the LOGIN name to BASE_DIR and use that as the login directory name. » ;
--base-dir : « /home by default. » ; --shell : « sets the path to the user's login shell. » ; --password absent : « Without this option, the
new account will be locked and with no password defined »
usermod(8), --append : « Add the user to the supplementary group(s). Use only
with the -G option. » install(1), --directory : « create all components of the
specified directories » ; --owner : « set ownership » ; --group : « set group
ownership » ; --mode : « set permission mode » (modes explicites ci-dessus).
Sans --home-dir, le répertoire de connexion reste sous BASE_DIR (par défaut /home),
même avec --no-create-home. Les comptes sans répertoire utile reçoivent /nonexistent ;
le répertoire réel de tunnel est sous /var/lib (Filesystem Hierarchy Standard : état variable).

La page installée adduser.conf(5), vérifiée par `man -w adduser.conf`, ne décrit pas
/nonexistent ; sa rubrique « SEE ALSO » renvoie à adduser(8). Cette dernière précise,
pour les utilisateurs système : « If no home directory is specified, the default home
directory for a new system user is /nonexistent. This directory should never exist on
any Debian system, and adduser will never create it automatically. »

Retour arrière : seulement avant les étapes 9 et suivantes et avant la procédure du tunnel, sans processus en cours.

ATTENTION — suppression destructive des seuls comptes/groupes créés ici ; ne jamais employer userdel -r ni supprimer un répertoire personnel existant.

```bash
(
set -euo pipefail
sudo /usr/sbin/userdel tunnel
sudo /usr/sbin/userdel chef
sudo /usr/sbin/userdel paresia-castor
sudo /usr/sbin/groupdel paresia-castor-etat
sudo /usr/sbin/groupdel paresia-remus-tunnel
sudo /usr/sbin/groupdel paresia-castor-tunnel
# userdel peut déjà avoir supprimé le groupe primaire privé : vérifier avant groupdel.
for groupe in tunnel chef paresia-castor; do
    if getent group "$groupe" > /dev/null; then
        sudo /usr/sbin/groupdel "$groupe"
    fi
done
)
echo "Code de sortie : $?"
```

## Étape 4 — Vérification des comptes

Intention : contrôler les identités réelles avant les droits de sudo et réseau.

```bash
(
set -euo pipefail
getent passwd paresia-castor chef tunnel
getent group paresia-castor chef tunnel paresia-castor-tunnel paresia-remus-tunnel paresia-castor-etat
id paresia-castor
id chef
id tunnel
id -nG chef
id -nG tunnel
getent group paresia-castor-tunnel paresia-remus-tunnel
REPERTOIRE_TUNNEL=$(getent passwd tunnel | cut -d: -f6)
case "$REPERTOIRE_TUNNEL" in /*) ;; *) exit 1 ;; esac
REPERTOIRE_TUNNEL=$(realpath -m -- "${REPERTOIRE_TUNNEL:?}")
case "$REPERTOIRE_TUNNEL" in /home|/home/*)
    echo 'Répertoire sous /home refusé ; aucun compte existant ne sera déplacé' >&2
    exit 1 ;;
esac
sudo /usr/bin/stat -c '%U:%G %a %n' "$REPERTOIRE_TUNNEL" "$REPERTOIRE_TUNNEL/.ssh"
sudo /usr/bin/passwd -S paresia-castor
sudo /usr/bin/passwd -S chef
sudo /usr/bin/passwd -S tunnel
)
```

Résultat attendu : getent et id donnent les identifiants 970 à 975 du tableau,
les trois shells nologin ; paresia-castor n'a que son groupe primaire.
`id -nG chef` donne **chef seul** ; `id -nG tunnel` donne **tunnel,
paresia-castor-tunnel, paresia-remus-tunnel** (ordre non garanti). Les deux groupes
de sockets listent tunnel, pas chef. Le sixième champ passwd tunnel est le
répertoire choisi ; stat donne **root:root 755** pour les deux dossiers.
Chaque `passwd -S` indique un mot de passe verrouillé (`L`), jamais utilisable.
Retour arrière : arrêter et revoir l'étape 3 si une identité diffère ; aucun
ajout de groupe privilégié pour corriger une permission de socket.

## Étape 5 — Code et configuration, deux profils

Intention : installer des fichiers root:root sans écriture des comptes de service.
Le dépôt doit être une copie propre et contrôlée ; ne pas copier des données
locales ni des clés. En profil **tout sur une machine**, le code est partagé avec
Pollux/Romulus : ne le remplacer **que s'il diffère**, après arrêt de ces démons
par vous-même ; cet arrêt ferme leurs sessions. Le profil **machine seule**
installe la base relais. Fixez `PROFIL` en amont ; le défaut est `relais`.

ATTENTION — préparation et sauvegarde avant tout remplacement du code installé ; confirmer l'arrêt des démons utilisateurs du code si celui-ci diffère.

```bash
PROFIL=${PROFIL:-relais}
case "$PROFIL" in
    relais) CONFIGURATION=/etc/paresia/paresia.conf ;;
    partage) CONFIGURATION=/etc/paresia/conf.d/20-relais.conf ;;
    *) CONFIGURATION=''; echo 'Profil inconnu : fixez PROFIL à relais ou partage' >&2 ;;
esac
export PROFIL CONFIGURATION
(
set -euo pipefail
test -n "$CONFIGURATION"
umask 022
sudo /usr/bin/install -d -o root -g root -m 0755 /usr/local/lib/paresia /etc/paresia /etc/paresia/conf.d
sudo /usr/bin/install -d -o root -g root -m 0700 "$TRAVAIL/code-neuf"
test -z "$(find "$DEPOT/server" ! -type d ! -type f -print -quit)"
sudo /usr/bin/tar -C "$DEPOT" --exclude='__pycache__' --exclude='server/conf' -cf - server | sudo /usr/bin/tar -C "$TRAVAIL/code-neuf" -xf -
sudo /usr/bin/install -o root -g root -m 0644 "$DEPOT/VERSION" "$TRAVAIL/code-neuf/VERSION"
if test -d /usr/local/lib/paresia/server; then
    sudo /usr/bin/diff -qr /usr/local/lib/paresia/server "$TRAVAIL/code-neuf/server" || test "$?" -eq 1
fi
)
echo "Code de sortie : $?"
```

Résultat attendu : différence absente si code identique ; code de diff 1 s'il
diffère, toute autre erreur impose l'arrêt. Dans ce dernier cas confirmer que
les démons sont arrêtés avant le bloc suivant. Un lien symbolique à une
destination, ou un objet autre qu'un dossier de code/fichier de configuration
régulier, impose l'arrêt et une revue manuelle.

ATTENTION — remplacement uniquement en cas de différence ; sauvegarde préalable du code et de la configuration, chown -R limité au code installé.

```bash
(
set -euo pipefail
test -n "$CONFIGURATION"
test ! -L /usr/local/lib/paresia/server
test ! -L "$CONFIGURATION"
outil copier --arbre --si-absent --jeu "$JEU" /usr/local/lib/paresia/server /usr/local/lib/paresia/VERSION "$CONFIGURATION"
DIFFERENCE=1
if test -d /usr/local/lib/paresia/server; then
    DIFFERENCE=0
    sudo /usr/bin/diff -qr /usr/local/lib/paresia/server "$TRAVAIL/code-neuf/server" || DIFFERENCE=$?
    test "$DIFFERENCE" -le 1 || exit 1
fi
if test "$DIFFERENCE" -eq 1; then
    CODE_REMPLACEMENT_CONFIRME=${CODE_REMPLACEMENT_CONFIRME:-non}
    if test "$CODE_REMPLACEMENT_CONFIRME" != oui; then
        echo 'Arrêtez les démons puis relancez avec CODE_REMPLACEMENT_CONFIRME=oui' >&2
        exit 1
    fi
    if test -e /usr/local/lib/paresia/server; then
        sudo /usr/bin/mv -T /usr/local/lib/paresia/server "$TRAVAIL/code-retire-$JEU"
    fi
    sudo /usr/bin/cp -a "$TRAVAIL/code-neuf/server" /usr/local/lib/paresia/server
fi
sudo /usr/bin/chown -R root:root /usr/local/lib/paresia/server
sudo /usr/bin/find /usr/local/lib/paresia/server -type d -exec /usr/bin/chmod 0755 {} +
sudo /usr/bin/find /usr/local/lib/paresia/server -type f -exec /usr/bin/chmod 0644 {} +
sudo /usr/bin/install -o root -g root -m 0644 "$TRAVAIL/code-neuf/VERSION" /usr/local/lib/paresia/VERSION
sudo /usr/bin/install -o root -g root -m 0644 "$DEPOT/server/conf/paresia-relais.conf" "$CONFIGURATION"
)
echo "Code de sortie : $?"
```

Résultat attendu : code root:root, dossiers 0755, fichiers 0644, sans `conf/`
ni `__pycache__` ; fichier `/usr/local/lib/paresia/VERSION` root:root 0644, à côté de
`server/` (les démons le lisent au démarrage et sortent avec le code 70 s'il
manque) ; /etc/paresia root:root 0755. Profil partage : base de
backend-admin inchangée, surcharge `20-relais.conf` ajoutée. La couche système
est suivie des surcharges puis de l'environnement PARESIA_REMUS_* / PARESIA_CASTOR_*.

Retour arrière : démons toujours arrêtés, restaurer par l'outil uniquement les objets
sauvegardés par cette étape (pas de copie de clés ; `restaurer` rétablit le code et la configuration
avant l'étape, ou les retire s'ils n'existaient pas).

ATTENTION — restauration écrasant (ou retirant, si absents avant l'étape) les fichiers installés ; elle s'arrête sans rien modifier si l'outil ne retrouve pas une sauvegarde (code 5) ; vérifier le jeu `JEU` et les destinations du profil choisi avant ces commandes.

```bash
(
set -euo pipefail
test -n "$CONFIGURATION"
outil restaurer --jeu "$JEU" /usr/local/lib/paresia/server
outil restaurer --jeu "$JEU" /usr/local/lib/paresia/VERSION
outil restaurer --jeu "$JEU" "$CONFIGURATION"
)
echo "Code de sortie : $?"
```

## Étape 6 — Sudoers généré, contrôlé puis installé

Intention : environnement vidé, génération sans privilège, session root de secours
ouverte. Le chemin de runuser est vérifié à l'étape 1 ; il est absolu
ci-dessous car `env -i` retire PATH (chemin de recherche par défaut `/bin:/usr/bin`
relevé par `getconf PATH`, qui n'inclut pas `/usr/sbin`). Aucun droit avec la table vide. Vérifier aussi que les sudoers de l'hôte
n'accordent aucun droit à chef par ailleurs ; ne jamais modifier /etc/sudoers ici.

Contrôle préalable de la politique sudo de l'hôte, en lecture seule. Le fichier
généré ne pose aucun `Defaults` : il repose sur le réglage par défaut
`env_reset` et sur l'inclusion de `/etc/sudoers.d`. sudoers(5), Command
environment : « By default, the env_reset flag is enabled. This causes commands
to be executed with a new, minimal environment. » ; si `env_reset` est
désactivé, « any variables not explicitly denied by the env_check and
env_delete options are allowed and their values are inherited from the invoking
process ». Scénario visé : avec `env_reset` désactivé ou un `env_keep` large,
chef passerait `DOCKER_HOST` ou `DOCKER_CONFIG` au docker lancé en root par
sudo, et redirigerait ainsi les commandes autorisées vers un autre démon ou une
autre configuration (aucune de ces variables n'est dans les arguments que le
fichier contrôle). Sources : sudoers(5), `env_keep` : « Environment variables
to be preserved in the user's environment when the env_reset option is in
effect », et « The global list of variables to keep is displayed when sudo is
run by root with the -V option » ; sudo(8), -V ; sudoers(5), Including other
files : « The @includedir directive can be used to create a sudoers.d
directory » (`#includedir` aussi accepté). Le contrôle s'arrête si `/etc/sudoers`
ne contient pas la directive d'inclusion, si un `Defaults` désactive `env_reset`
dans `/etc/sudoers` ou `/etc/sudoers.d`, ou si la liste affichée par `sudo -V`
mentionne `DOCKER_` ou un joker seul. Un arrêt impose une revue manuelle de la
politique, sans modifier `/etc/sudoers` ici.

Termes, sudoers(5) : Defaults (« Certain configuration options may be changed
from their default values at run-time via one or more Default_Entry lines »),
dont les formes ciblées `Defaults:utilisateur`, `Defaults@hôte`, `Defaults!commande`
et `Defaults>utilisateur_cible` ; tags `SETENV`/`NOSETENV` (« If SETENV has been
set for a command, the user may disable the env_reset flag from the command line
via the -E option ») ; option `setenv` (même effet, « not subject to the
restrictions imposed by env_check, env_delete, or env_keep »). Le `grep -r -P`
ci-dessous refuse donc toute ligne active (non commentée) qui mentionne
env_keep, env_check, env_delete, `!env_reset` (désactivation) ou setenv, quelle
que soit la forme du Defaults, à une seule exception : la ligne exacte du
paquet Debian `sudo` 1.9.16p2-3+deb13u2, limitée à la commande visudo. Lignes
réelles de `/usr/share/doc/sudo/examples/sudoers.dist` de ce paquet (lignes
44 à 51) :

```text
## Preserve editor environment variables for visudo.
## To preserve these for all commands, remove the "!visudo" qualifier.
Defaults!/usr/sbin/visudo env_keep += "SUDO_EDITOR EDITOR VISUAL"
##
## Use a hard-coded PATH instead of the user's to find commands.
## This also helps prevent poorly written scripts from running
## arbitrary commands under sudo.
Defaults secure_path="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
```

Ce fichier ne contient aucune ligne `Defaults env_reset` : `env_reset` n'est pas
écrit, c'est le réglage par défaut compilé de sudo (sudoers(5) cité plus haut),
et un hôte intact ne le porte donc pas dans `/etc/sudoers`. Le contrôle n'exige
pas cette ligne ; il refuse la désactivation `!env_reset`. Un `/etc/sudoers.d`
absent ou illisible est aussi un arrêt (code 2 de grep traité comme arrêt).

IMPORTANT : ce contrôle est nécessaire mais non suffisant. Il ne suit pas les
fichiers inclus par `@include` ou `@includedir` imbriqués, ni ceux d'autres
répertoires ; la revue manuelle de tous les fichiers inclus (`@include`,
`@includedir`) n'est pas facultative et précède l'installation.

```bash
(
set -euo pipefail
sudo /usr/bin/test -f /etc/sudoers
sudo /usr/bin/test -r /etc/sudoers
if ! sudo /usr/bin/test -d /etc/sudoers.d || ! sudo /usr/bin/test -r /etc/sudoers.d || ! sudo /usr/bin/test -x /etc/sudoers.d; then
    echo 'Arrêt : /etc/sudoers.d absent ou illisible ; revue manuelle' >&2
    exit 1
fi
if ! sudo /usr/bin/grep -q -E '^[[:space:]]*[@#]includedir[[:space:]]+/etc/sudoers\.d[[:space:]]*$' /etc/sudoers; then
    echo 'Arrêt : /etc/sudoers ne contient pas @includedir /etc/sudoers.d' >&2
    exit 1
fi
# grep rend 0 (trouvé), 1 (rien) ou 2 (erreur) : seul 1 est accepté.
RC=0
sudo /usr/bin/grep -r -n -P '^(?![[:space:]]*#)(?![[:space:]]*Defaults!/usr/sbin/visudo[[:space:]]+env_keep[[:space:]]*\+=[[:space:]]*"SUDO_EDITOR EDITOR VISUAL"[[:space:]]*$).*(Defaults[:!@>]?.*(env_keep|env_check|env_delete)|!env_reset|setenv|SETENV)' /etc/sudoers /etc/sudoers.d || RC=$?
if test "$RC" -ne 1; then
    echo 'Arrêt : Defaults sur l environnement, setenv/SETENV ou lecture impossible ; revue manuelle' >&2
    exit 1
fi
VERSION_SUDO=$(sudo /usr/bin/sudo -V)
if grep -q -E 'DOCKER_|(^|[[:space:]])[*]([[:space:]]|$)' <<< "$VERSION_SUDO"; then
    echo 'Arrêt : env_keep large ou DOCKER_* conservé ; revue manuelle' >&2
    exit 1
fi
)
echo "Code de sortie : $?"
```

Résultat attendu : code 0 sans message d'arrêt. Le fichier temporaire est créé
dans le dossier de travail `TRAVAIL` (root:root 0700, sous `/run`), donc jamais dans `/tmp`
et sans nettoyage à prévoir en cas d'échec ; le contenu installé est conservé
comme relevé `sudoers-genere` du jeu de sauvegarde.

ATTENTION — installation de sudoers ; une erreur de syntaxe peut priver de sudo, garder la session de secours.

```bash
(
set -euo pipefail
TEMP_SUDOERS="$TRAVAIL/sudoers-genere"
sudo /usr/bin/env -i PYTHONPATH=/usr/local/lib/paresia /usr/sbin/runuser -u nobody -- /usr/bin/python3 -P -s -B -m server.remus.sudoers | sudo /usr/bin/tee "$TEMP_SUDOERS" > /dev/null
sudo /usr/bin/diff -- "$DEPOT/deploy/backend-relais/etc/sudoers.d/paresia-remus" "$TEMP_SUDOERS"
sudo /usr/sbin/visudo -c -f "$TEMP_SUDOERS"
sudo /usr/bin/cat "$TEMP_SUDOERS" | outil releve sudoers-genere --jeu "$JEU"
outil copier --si-absent --jeu "$JEU" /etc/sudoers.d/paresia-remus
sudo /usr/bin/install -o root -g root -m 0440 "$TEMP_SUDOERS" /etc/sudoers.d/paresia-remus
)
echo "Code de sortie : $?"
```

Résultat attendu : diff vide, visudo accepte **avant** installation, propriétaire
root:root 0440, nom `paresia-remus` sans point ni suffixe `~`.
La CLI lit le schéma fusionné de Remus et les mêmes couches que le démon ;
aucun état ni fichier journal. Une erreur écrit seulement son code sur stderr.

```bash
(
set -euo pipefail
# Contrôle après installation, avec sudo : sudo -l -U chef (sudoers(5) : « Matching Defaults entries »).
# LC_ALL=C : en-têtes de sudo -l non traduits ; une section absente ou vide est un échec.
LISTE=$(sudo /usr/bin/env LC_ALL=C /usr/bin/sudo -n -l -U chef) || test "$?" -eq 1
printf '%s\n' "$LISTE"
DEFAUTS=$(awk '/^Matching Defaults entries for chef/ {d=1; next} d && /^[[:space:]]*$/ {d=0} d' <<< "$LISTE")
if test -z "$DEFAUTS"; then
    echo 'Arrêt : section Matching Defaults entries for chef absente ou vide ; revue manuelle' >&2
    exit 1
fi
# Même liste fautive que le contrôle préalable (env_reset positif toléré), sur toute la sortie
# (y compris « Runas and Command-specific defaults for chef »), plus DOCKER_.
if grep -q -E 'env_keep|env_check|env_delete|!env_reset|setenv|SETENV|DOCKER_' <<< "$LISTE"; then
    echo 'Arrêt : politique de chef avec env_keep, env_check, env_delete, !env_reset, setenv, SETENV ou DOCKER_ ; retirer /etc/sudoers.d/paresia-remus et revoir la politique' >&2
    exit 1
fi
if sudo /usr/bin/sudo -u chef /usr/bin/sudo -n -- /usr/bin/docker ps; then
    exit 1
else
    printf 'Code du refus : %s\n' "$?"
fi
sudo /usr/bin/journalctl --since '10 minutes ago' _COMM=sudo --no-pager
)
echo "Code de sortie : $?"
```

Résultat attendu : liste sans commande autorisée (code non nul possible),
second appel refusé avec code non nul, sans demander de mot de passe ; root
retrouve la trace du refus au journal, sous réserve de la politique de
journalisation hôte à vérifier. **Aucun droit de lecture du journal à chef.**
Si une commande est autorisée, arrêter : vérifier la politique globale.

Sources : sudo(8), -n : « Avoid prompting the user for input of any kind. » ;
-l : « list the privileges for the invoking user » ; -U : « list the privileges for user instead of for the invoking user. » ; -u : « Run the command as a user other than
the default target user » ; -- : « delimit the end of the sudo options ».
visudo(8), -c : « Enable check-only mode. » ; -f : « Specify an alternate sudoers
file location ». Voir les extraits de syntaxe ci-dessous.

Retour arrière : l'outil restaure le précédent fichier, ou retire seulement celui créé par l'étape (marque d'absence) ; sans sauvegarde retrouvée il s'arrête sans rien supprimer.

ATTENTION — modification des droits sudo ; session de secours toujours ouverte ; le fichier restauré est contrôlé par `visudo -c` juste après la restauration, avant de fermer la session de secours.

```bash
(
set -euo pipefail
outil restaurer --jeu "$JEU" /etc/sudoers.d/paresia-remus
if test -e /etc/sudoers.d/paresia-remus; then
    sudo /usr/sbin/visudo -c -f /etc/sudoers.d/paresia-remus
fi
)
echo "Code de sortie : $?"
```

## Étape 7 — nftables : coexistence et essai avant activation permanente

Intention : ajouter une seule table, sans modifier le pare-feu de l'hôte ni Docker.
Le compte tunnel doit déjà exister pour résoudre son nom. Le contrôle sans
chargement peut nécessiter CAP_NET_ADMIN. Vérifier `test -x /usr/sbin/nft` :
`/usr/sbin/nft` ; arrêter sinon et faire adapter l'unité.

ATTENTION — sauvegarde par l'outil des éventuels fichiers existants avant leur remplacement (`install` écrase) ; ne pas remplacer une unité ou table homonyme déjà en usage sans revue.

```bash
(
set -euo pipefail
sudo /usr/sbin/nft list ruleset | outil releve nft-avant --jeu "$JEU"
outil copier --si-absent --jeu "$JEU" /etc/nftables/paresia-relais.nft /etc/systemd/system/paresia-nftables.service
sudo /usr/bin/install -d -o root -g root -m 0755 /etc/nftables
sudo /usr/bin/install -o root -g root -m 0644 "$DEPOT/deploy/backend-relais/etc/nftables/paresia-relais.nft" /etc/nftables/paresia-relais.nft
sudo /usr/bin/install -o root -g root -m 0644 "$DEPOT/deploy/backend-relais/etc/systemd/system/paresia-nftables.service" /etc/systemd/system/paresia-nftables.service
sudo /usr/sbin/nft -c -f /etc/nftables/paresia-relais.nft
sudo /usr/bin/systemd-analyze verify /etc/systemd/system/paresia-nftables.service
)
echo "Code de sortie : $?"
```

Résultat attendu : contrôles valides, aucune règle chargée jusqu'ici.

ATTENTION — chargement de règles réseau ; seule notre table est vidée puis chargée, aucune modification du reste du ruleset.

```bash
(
set -euo pipefail
sudo /usr/bin/systemctl daemon-reload
sudo /usr/bin/systemctl start paresia-nftables.service
sudo /usr/sbin/nft list ruleset | outil releve nft-apres --jeu "$JEU"
AVANT=$(outil retrouver --releve nft-avant --jeu "$JEU" | cut -f3)
APRES=$(outil retrouver --releve nft-apres --jeu "$JEU" | cut -f3)
sudo /usr/bin/diff -u "$AVANT" "$APRES" || test "$?" -eq 1
sudo /usr/sbin/nft list table inet paresia_relais
)
echo "Code de sortie : $?"
```

Résultat attendu : diff ajoute **seulement** `inet paresia_relais`, chaîne output,
une règle `meta skuid "tunnel" ct state new reject`. La sortie peut présenter
l'uid au lieu du nom. Les tables Docker et du pare-feu hôte sont inchangées ;
sinon arrêter et revoir le diff. La boucle locale est couverte ; sockets Unix
exclues, redirections du tunnel préservées. Réponses de connexions établies
non visées. Ne pas ajouter de compteur à cette règle.

Essai local TCP réel par vous seul : le port `PORT_ESSAI` doit être libre ; démarrer un petit
serveur temporaire borné sur 127.0.0.1 (adresse utilisée partout, serveur et
clients), attendre explicitement qu'il écoute, essayer tunnel puis nobody.

```bash
(
set -euo pipefail
PORT_ESSAI=${PORT_ESSAI:-49152}
if ! [[ "$PORT_ESSAI" =~ ^[0-9]{1,5}$ ]] || test "$PORT_ESSAI" -lt 1024 || test "$PORT_ESSAI" -gt 65535; then
    echo 'Port invalide (entier de 1024 à 65535 attendu)' >&2
    exit 1
fi
export PORT_ESSAI
test -n "${PORT_ESSAI:-}"
test -z "$(ss -H -ltn "sport = :$PORT_ESSAI")"
python3 - <<'PY' &
import os, socket
with socket.socket() as serveur:
    serveur.settimeout(30)
    serveur.bind(('127.0.0.1', int(os.environ['PORT_ESSAI'])))
    serveur.listen(1)
    connexion, _ = serveur.accept()
    connexion.close()
PY
PID_ESSAI=$!
trap 'kill "$PID_ESSAI" 2>/dev/null || true' EXIT
ATTENTE=0
until test -n "$(ss -H -ltn "sport = :$PORT_ESSAI")"; do
    ATTENTE=$((ATTENTE + 1))
    test "$ATTENTE" -le 50
    sleep 0.1
done
if sudo /usr/sbin/runuser -u tunnel -- /usr/bin/python3 -c 'import socket,sys; socket.create_connection(("127.0.0.1",int(sys.argv[1])),3).close()' "$PORT_ESSAI"; then
    exit 1
else
    printf 'Code du refus tunnel : %s\n' "$?"
fi
sudo /usr/sbin/runuser -u nobody -- /usr/bin/python3 -c 'import socket,sys; socket.create_connection(("127.0.0.1",int(sys.argv[1])),3).close()' "$PORT_ESSAI"
wait "$PID_ESSAI"
)
echo "Code de sortie : $?"
```

Résultat attendu : tunnel est refusé immédiatement (`ConnectionRefusedError`,
code non nul), nobody réussit (code 0). Si le serveur n'écoute pas ou si nobody
échoue, essai invalide : corriger puis recommencer ; ne pas activer l'unité.

ATTENTION — activation au prochain démarrage uniquement après les essais et le diff validés.

```bash
sudo /usr/bin/systemctl enable paresia-nftables.service
```

Retour arrière : désactiver/arrêter puis vérifier l'absence de notre table.

ATTENTION — arrêt et suppression de règles réseau : seul paresia_relais doit disparaître ; aucune suppression du ruleset global ; restauration des deux fichiers depuis le jeu `JEU` (arrêt sans rien modifier si une sauvegarde manque).

```bash
(
set -euo pipefail
sudo /usr/bin/systemctl disable paresia-nftables.service
sudo /usr/bin/systemctl stop paresia-nftables.service
sudo /usr/sbin/nft list tables
# Seulement si ExecStop a échoué et que la table subsiste :
if sudo /usr/sbin/nft list table inet paresia_relais > /dev/null 2>&1; then
    sudo /usr/sbin/nft delete table inet paresia_relais
fi
outil restaurer --jeu "$JEU" /etc/nftables/paresia-relais.nft
outil restaurer --jeu "$JEU" /etc/systemd/system/paresia-nftables.service
sudo /usr/bin/systemctl daemon-reload
)
echo "Code de sortie : $?"
```

Résultat attendu : les autres tables demeurent ; la suppression finale n'a lieu
que si la table subsiste (l'unité tolère déjà une table absente : `ExecStop=-`,
systemd.service(5)). L'outil rétablit ensuite les deux fichiers sauvegardés (ou retire
ceux que l'étape a créés) avant de recharger systemd ; ne pas redémarrer l'ancienne unité
avant revue de ses effets.

## Étape 8 — Suite : unités Castor et Remus

Intention : poursuivre avec les unités Castor/Remus et les essais d'isolation.

```bash
cat "$DEPOT/deploy/backend-relais/isolation-remus.md"
```

Résultat attendu : tableau et essais réels relus ; les étapes suivantes poursuivent la numérotation.
Ne pas lancer Remus avant les validations de son unité, ni le tunnel avant la procédure du tunnel.
Retour arrière : aucun service supplémentaire démarré à cette étape.

## Étape 9 — Unités de Castor et de Remus : copie et vérification

Intention : copier `castor.service` et `remus.service`, recharger systemd et les vérifier,
sans rien démarrer. Chaque unité porte `ConfigurationDirectory=paresia::ro` ; le drapeau `::ro`
exige systemd **257 ou plus** (systemd.exec(5) : « since v257 can take a value of ro »). Le code
et la configuration sont ceux installés à l'étape 5 ; `JEU` et `DEPOT` viennent de l'étape 1
(les recréer comme à cette étape dans une nouvelle session). Castor et Remus ne dépendent d'aucune autre
unité : `paresia-nftables.service` n'est pas une dépendance.

```bash
systemctl --version | head -n 1
command -v systemd-analyze
if test -n "$JEU"; then
    outil lister
else
    echo 'JEU absent : ne pas poursuivre' >&2
fi
sudo /usr/bin/stat -c '%U:%G %a %n' /etc/paresia /usr/local/lib/paresia
if test -d /run/sudo; then
    sudo /usr/bin/stat -c '%U:%G %a %n' /run/sudo
else
    echo '/run/sudo absent' >&2
fi
```

Résultat attendu : numéro de systemd (257 ou plus ; sinon le `sed -i` ci-dessous retire `::ro` des copies), `systemd-analyze` présent, `/etc/paresia` et le code à `root:root 755`. Si
`/run/sudo` est absent, **arrêter** : Remus ne démarrerait pas (la directive `ReadWritePaths=/run/sudo`
exige que le chemin existe, systemd.exec(5) : le préfixe « - » ignore un chemin absent) ; relever
le `timestampdir` par `sudo -V` et le signaler à l'auteur de la procédure.
Retour arrière : sans objet (lecture seule).

ATTENTION — `install` et la copie écrasent des fichiers : toute unité existante est d'abord
sauvegardée sous `/var/backups/paresia/relais/` (dossier `root:root` 0700), jamais à côté.

```bash
(
set -euo pipefail
test -n "$JEU"
for unite in castor remus; do
    outil copier --si-absent --jeu "$JEU" "/etc/systemd/system/$unite.service"
    sudo /usr/bin/install -m 0644 -o root -g root "$DEPOT/deploy/backend-relais/etc/systemd/system/$unite.service" "/etc/systemd/system/$unite.service"
done
)
echo "Code de sortie : $?"
```

Résultat attendu : code de sortie 0 ; unités copiées, chaque unité préexistante sauvegardée par l'outil
dans le jeu `JEU`, chaque unité absente consignée comme telle (marque d'absence). Un rejeu ne remplace
jamais la première sauvegarde.
Retour arrière : voir la fin de l'étape (restauration ou retrait des unités).

ATTENTION — `sed -i` modifie les **copies installées** (pas celles du dépôt) ; il ne s'exécute que si
systemd est inférieur à 257 (condition dans la commande), après la copie et **avant** la vérification.

```bash
(
set -euo pipefail
VERSION_SYSTEMD=$(systemctl --version | awk 'NR==1 {print $2}')
if test "$VERSION_SYSTEMD" -lt 257; then
    sudo /usr/bin/sed -i 's/^ConfigurationDirectory=paresia::ro$/ConfigurationDirectory=paresia/' /etc/systemd/system/castor.service /etc/systemd/system/remus.service
fi
sudo /usr/bin/systemctl daemon-reload
)
echo "Code de sortie : $?"
```

Résultat attendu : code de sortie 0 ; avec systemd inférieur à 257, la ligne `ConfigurationDirectory=paresia`
remplace la forme `::ro` dans les deux copies ; sinon, aucune modification.
Retour arrière : voir la fin de l'étape.

Vérification des copies installées, éventuellement corrigées par la commande précédente.

```bash
sudo /usr/bin/systemd-analyze verify castor.service remus.service
```

Résultat attendu : aucune erreur de `systemd-analyze verify` pour ces deux unités.
Retour arrière : sans objet (lecture seule).

ATTENTION — la restauration écrase ou retire les unités installées ; à utiliser seulement pour revenir
en arrière. `JEU` doit désigner le jeu de l'étape d'origine (variable de la session ; sinon la fixer au
nom relevé par `python3 -P -m server.sauvegarde lister`, et le contrôler). Une unité sauvegardée est
restaurée ; une unité n'est retirée que si sa marque d'absence existe ; sans l'un ni l'autre, l'outil
répond 5, la commande échoue (code non nul) et rien n'est supprimé.

```bash
(
set -euo pipefail
test -n "$JEU"
for unite in castor remus; do
    outil restaurer --jeu "$JEU" "/etc/systemd/system/$unite.service"
done
sudo /usr/bin/systemctl daemon-reload
)
echo "Code de sortie : $?"
```

Résultat attendu : unités préexistantes restaurées depuis `/var/backups/paresia/relais/`, unités créées
(marque d'absence) retirées, systemd rechargé ; code non nul et rien supprimé si une sauvegarde manque.
Retour arrière : recommencer la copie de cette étape.

## Étape 10 — Démarrage de Castor et vérifications

Intention : démarrer Castor (`start`, jamais `enable` à ce stade) et contrôler son dossier,
ses deux sockets et leurs droits. Castor avant Remus.

ATTENTION — tout redémarrage ou arrêt de Castor remet tous les feux au rouge : les commandes en
attente de Remus seront refusées. Ne démarrer qu'en l'absence de session réelle en cours.

```bash
sudo /usr/bin/systemctl start castor.service
sudo /usr/bin/systemctl status castor.service --no-pager
sudo /usr/bin/journalctl -u castor.service -n 30 --no-pager
ss -xl | grep paresia
sudo /usr/bin/stat -c '%U:%G %a %n' /run/paresia-castor /run/paresia-castor/castor.sock /run/paresia-castor/castor-state.sock
sudo /usr/bin/stat -c '%U:%G %a %n' /var/lib/paresia-castor
sudo /usr/bin/systemctl show -p StateDirectory castor.service
sudo /usr/bin/stat -c '%U:%G %a %n' /etc/paresia
```

Résultat attendu : `active (running)`, journal sans erreur, deux sockets à l'écoute.

| Élément | Attendu |
| --- | --- |
| `/run/paresia-castor` | `paresia-castor:paresia-castor 711` |
| `/var/lib/paresia-castor` (dossier d'état, `StateDirectory=paresia-castor`) | `paresia-castor:paresia-castor 711` |
| `castor.sock` | `paresia-castor:paresia-castor-tunnel 660` |
| `castor-state.sock` | `paresia-castor:paresia-castor-etat 660` |
| `/etc/paresia` | `root:root 755` |

Si un propriétaire de socket diffère du tableau (le `chown` vers un groupe supplémentaire n'est pas
confirmé par la documentation de systemd), ou si `/etc/paresia` n'est plus `root:root`, **arrêter**
(`systemctl stop castor.service`) et signaler. Après un arrêt, `/run/paresia-castor` a disparu ;
`/var/lib/paresia-castor` est conservé. Au retour arrière complet, le script le retire par `rmdir`,
seulement s'il est vide (il est créé par systemd, jamais par le script).
Retour arrière :

ATTENTION — l'arrêt de Castor remet tous les feux au rouge.

```bash
sudo /usr/bin/systemctl stop castor.service
```

## Étape 11 — Démarrage de Remus et vérifications

Intention : démarrer Remus (Castor déjà démarré), contrôler son dossier, sa socket et l'arrêt
non interruptif.

ATTENTION — tout redémarrage ou arrêt de Remus interrompt la mise en attente du feu vert ; avec une
opération en cours, l'arrêt attend `stop_s` (`KillMode=mixed`, systemd.kill(5) : SIGTERM au seul
processus principal, puis SIGKILL au reste du groupe). La table des commandes étant vide, aucune
opération n'est en cours.

```bash
sudo /usr/bin/systemctl start remus.service
sudo /usr/bin/systemctl status remus.service --no-pager
sudo /usr/bin/journalctl -u remus.service -n 30 --no-pager
ss -xl | grep paresia
sudo /usr/bin/stat -c '%U:%G %a %n' /run/paresia-remus /run/paresia-remus/remus.sock
sudo /usr/bin/stat -c '%U:%G %a %n' /var/lib/paresia-remus
sudo /usr/bin/systemctl show -p StateDirectory remus.service
sudo /usr/bin/stat -c '%U:%G %a %n' /etc/paresia
sudo /usr/bin/systemctl show -p KillMode -p TimeoutStopUSec remus.service
```

Résultat attendu : `active (running)`, journal sans erreur, `KillMode=mixed`, `TimeoutStopUSec`
équivalent à 150 s (forme d'affichage à relever).

| Élément | Attendu |
| --- | --- |
| `/run/paresia-remus` | `chef:chef 711` |
| `/var/lib/paresia-remus` (dossier d'état, `StateDirectory=paresia-remus`) | `chef:chef 711` |
| `remus.sock` | `chef:paresia-remus-tunnel 660` |
| `/etc/paresia` | `root:root 755` |

Mêmes règles d'arrêt qu'à l'étape 10 en cas d'écart de propriétaire ou de droits. Le dossier d'état
`/var/lib/paresia-remus` est conservé à l'arrêt et retiré au retour arrière complet, par `rmdir`,
seulement s'il est vide.
Retour arrière :

ATTENTION — l'arrêt de Remus interrompt la mise en attente du feu vert.

```bash
sudo /usr/bin/systemctl stop remus.service
```

## Étape 12 — Contrôles de refus et essai local de Castor

Intention : un compte tiers ne peut ouvrir aucune des trois sockets ; puis un essai local de
Castor sans le tunnel, par des requêtes d'une ligne JSON `jumeaux/1`.

```bash
for socket in /run/paresia-castor/castor.sock /run/paresia-castor/castor-state.sock /run/paresia-remus/remus.sock; do
    sudo /usr/sbin/runuser -u nobody -- /usr/bin/python3 -c "import socket,sys; s=socket.socket(socket.AF_UNIX); s.connect(sys.argv[1])" "$socket" 2>&1 | tail -n 1
done
```

Résultat attendu : `PermissionError` pour chacune des trois sockets.
Retour arrière : sans objet (lecture seule).

Pour lire `castor-state.sock` sous l'identité de Remus, `jumeaux` fixe le groupe
principal `chef` et le groupe supplémentaire `paresia-castor-etat`, accordé à
Remus par `SupplementaryGroups=` dans son unité. Le compte `chef` reste sans
groupe supplémentaire dans la base des comptes. Ce groupe n'est ajouté ni pour
le refus de `chef` sur `castor.sock`, ni pour celui de `tunnel` sur `castor-state.sock`.
Source installée, runuser(1) : `-g, --group` : « The primary group to be used.
This option is allowed for the root user only. » ; `-G, --supp-group` :
« Specify a supplementary group. This option is available to the root user only. »
Ces options sont appliquées par la commande privilégiée `sudo /usr/sbin/runuser`.

ATTENTION — cet essai ouvre puis ferme le feu de la session 1 de Castor : ne pas le mener tant que
des sessions réelles sont en cours. Les requêtes passent par la fonction `jumeaux`, définie ici.

```bash
jumeaux() {
    local -a groupes=()
    if test "$1" = chef && test "$2" = /run/paresia-castor/castor-state.sock; then
        groupes=(-g chef -G paresia-castor-etat)
    fi
    sudo /usr/sbin/runuser -u "$1" "${groupes[@]}" -- /usr/bin/python3 -c "import json,secrets,socket,sys; s=socket.socket(socket.AF_UNIX); s.settimeout(3); s.connect(sys.argv[1]); s.sendall(json.dumps({'proto':'jumeaux/1','id':secrets.token_hex(8),'session':1,'action':sys.argv[2],'params':{}}).encode()+b'\n'); print(s.makefile('rb').readline().decode().strip())" "$2" "$3" 2>&1 | tail -n 1
}
jumeaux tunnel /run/paresia-castor/castor.sock castor/light/ping
jumeaux chef /run/paresia-castor/castor-state.sock castor/light/state
jumeaux tunnel /run/paresia-castor/castor.sock castor/light/close
jumeaux chef /run/paresia-castor/castor-state.sock castor/light/state
jumeaux chef /run/paresia-castor/castor.sock castor/light/ping
jumeaux tunnel /run/paresia-castor/castor-state.sock castor/light/state
sudo /usr/bin/journalctl -u castor.service -n 30 --no-pager | grep -E 'light_green|light_closed'
```

Résultat attendu, dans l'ordre : `ok` à `true` (réponse du ping) ; `data` valant `{"state":"green", …}` ;
`ok` à `true` (fermeture) ; puis l'état de la session 1 : d'après `tests/test_castor_feux.py`
(`test_castor_close_immediat`), une session fermée répond l'erreur `session_closed` pendant `closed_s`,
puis `{"state":"red"}` ; **relever la réponse exacte** ; puis deux refus :
`chef` sur `castor.sock` et `tunnel` sur `castor-state.sock` : `PermissionError [Errno 13]`
(dernière ligne Python : `PermissionError: [Errno 13] Permission denied`).
Le journal de Castor montre, pour la session 1, `light_green` puis `light_closed`
avec `reason` valant `close`. Les séparateurs JSON exacts sont à relever.
Retour arrière : l'essai ne laisse aucun état (le feu de la session 1 est refermé) ; `systemctl restart castor.service` remet les feux au rouge (ATTENTION précédente).

## Étape 13 — Essais réels de l'isolation de Remus

Intention : éprouver sur la cible chaque ligne « à vérifier sur la cible » de `isolation-remus.md`
(essais 1 à 6 de ce fichier). Table des commandes vide : seul un refus est attendu ; l'essai positif
d'une commande réelle passe par Remus sous sa véritable unité et reste à mener lorsque la table des commandes n'est pas vide, avant toute commande de production (de même que
l'essai d'arrêt avec une opération en cours).

```bash
PID=$(systemctl show -p MainPID --value remus.service)
echo "PID principal : $PID"
grep -E '^(NoNewPrivs|CapBnd|CapEff|CapAmb|Seccomp):' /proc/"$PID"/status
sudo /usr/bin/systemctl show -p KillMode -p User -p CapabilityBoundingSet -p ReadWritePaths -p ReadOnlyPaths remus.service
sudo /usr/bin/sudo -V | grep -i -E 'timestamp|version'
sudo /usr/bin/stat -c '%U:%G %a %n' /run/sudo
sudo /usr/bin/ls -A /proc/"$PID"/root/root /proc/"$PID"/root/tmp
sudo /usr/bin/ls /proc/"$PID"/root/dev
sudo /usr/bin/journalctl -u remus.service -n 50 --no-pager
```

(`--value` : systemctl(1), « only print the value, and skip the property name and "=" ».)
Résultat attendu : `NoNewPrivs: 0` (la directive est retirée, ligne `NoNewPrivileges` du tableau) ;
`CapAmb` nul ; `CapBnd` limité à CAP_SETGID (6), CAP_SETUID (7) et CAP_AUDIT_WRITE (29, `linux/capability.h`),
soit `00000000200000c0` ; `Seccomp` non nul (valeur à relever) ; `ReadWritePaths` `/run/sudo`, `ReadOnlyPaths`
`/etc/paresia /usr/local/lib/paresia` ; `/proc/PID/root/root` et `/tmp` vides ; `/dev` réduit aux pseudo-fichiers ;
journal sans SIGSYS ni erreur de bibliothèque. Un écart **bloque** : arrêter Remus et signaler.
Retour arrière : sans objet (lecture seule).

Correspondance avec les lignes à vérifier du tableau (`isolation-remus.md`) :

| Directive | Commande de l'étape ou essai | Attendu |
| --- | --- | --- |
| CapabilityBoundingSet | `CapBnd` du bloc ci-dessus | `00000000200000c0` |
| ProtectHome | `ls -A /proc/"$PID"/root/root` | vide |
| PrivateTmp | `ls -A /proc/"$PID"/root/tmp` | vide |
| PrivateDevices | `ls /proc/"$PID"/root/dev` | pseudo-fichiers seulement |
| ProtectControlGroups | essai 3 de `isolation-remus.md` (`/proc/"$PID"/root/sys/fs/cgroup`, lecture seule) | aucune écriture possible |
| ProtectProc | essai 3 et `sudo -n -l` ci-dessous | sudo atteint sa politique |
| RestrictAddressFamilies | essais 3 et 4 : `journalctl -u remus.service` | aucune erreur de permission |
| RestrictNamespaces | essai 3 : commande auditée, table non vide | à mener avec une table non vide |
| SystemCallArchitectures | `Seccomp` du bloc et `sudo -n -l` | pas de SIGSYS |
| SystemCallFilter | `Seccomp` du bloc et `sudo -n -l` | pas de SIGSYS |
| MemoryDenyWriteExecute | essai 3 : commande auditée, table non vide | à mener avec une table non vide ; directive absente |
| ReadWritePaths | `sudo -V` et `stat` de `/run/sudo` | aucune erreur « read-only » |

Essai de `sudo -n -l` par `chef` dans l'environnement d'isolation de l'unité (systemd-run(1) :
`--property=`, `-p` « takes an assignment in the same format as systemctl(1)'s set-property
command »). Chaque `-p` reprend la valeur de l'unité installée (NoNewPrivileges absent, comme
dans l'unité).

ATTENTION — `sudo -n -l` en environnement transitoire : le sudoers installé est atteint, aucune
commande de production n'est lancée.

```bash
sudo /usr/bin/systemd-run --wait --pipe --collect \
    -p User=chef -p Group=chef \
    -p 'SupplementaryGroups=paresia-remus-tunnel paresia-castor-etat' \
    -p LimitCORE=0 -p 'CapabilityBoundingSet=CAP_SETUID CAP_SETGID CAP_AUDIT_WRITE' \
    -p AmbientCapabilities= -p ProtectSystem=strict -p ProtectHome=yes -p PrivateTmp=yes \
    -p PrivateDevices=yes -p ProtectKernelTunables=yes -p ProtectKernelModules=yes \
    -p ProtectKernelLogs=yes -p ProtectControlGroups=yes -p ProtectClock=yes \
    -p ProtectHostname=yes -p ProtectProc=invisible -p RestrictAddressFamilies=AF_UNIX \
    -p RestrictNamespaces=yes -p RestrictRealtime=yes -p RestrictSUIDSGID=yes \
    -p LockPersonality=yes -p SystemCallArchitectures=native -p SystemCallFilter=@system-service \
    -p UMask=0077 -p ReadWritePaths=/run/sudo \
    -p 'ReadOnlyPaths=/etc/paresia /usr/local/lib/paresia' \
    /usr/bin/sudo -n -l
echo "Code de sortie : $?"
```

Résultat attendu (sudo(8), `-n` : « If a password is required for the command to run, sudo will
display an error message and exit ») : un message indiquant qu'un mot de passe est requis prouve que
la politique de sudoers a été atteinte. Toute autre sortie (échec de montée de privilège, appel système
refusé) est **à relever et à conserver, puis à signaler à l'auteur de la procédure**, sans élargir l'isolation.
Retour arrière : sans objet (l'unité transitoire est collectée à la fin, `--collect`).

## Étape 14 — Activation

Intention : activer Castor et Remus au démarrage, seulement si toutes les étapes 9 à 13 sont
conformes.

ATTENTION — `systemctl enable` modifie le démarrage de la machine ; ne l'exécuter que si les contrôles
sont tous conformes.

```bash
sudo /usr/bin/systemctl enable castor.service remus.service
sudo /usr/bin/systemctl is-enabled castor.service remus.service
```

Résultat attendu : `enabled` pour les deux unités. Le tunnel et son essai de bout en bout relèvent de
la procédure du tunnel : ne pas démarrer le tunnel avant elle.
Retour arrière en cas d'écart sur une étape 9 à 13 (ou de désactivation) :

ATTENTION — l'arrêt de Remus puis de Castor interrompt la mise en attente et remet les feux au rouge ;
l'outil restaure les unités sauvegardées et ne retire que celles dont la marque d'absence existe (même contrôle que ci-dessus : `JEU` = jeu de l'étape 9).

```bash
sudo /usr/bin/systemctl disable castor.service remus.service
sudo /usr/bin/systemctl stop remus.service castor.service
(
set -euo pipefail
test -n "$JEU"
for unite in castor remus; do
    outil restaurer --jeu "$JEU" "/etc/systemd/system/$unite.service"
done
sudo /usr/bin/systemctl daemon-reload
)
echo "Code de sortie : $?"
```

## Références de syntaxe et limites de sudoers

Extraits de sudoers(5) installé, sudo 1.9.16p2, consulté le 2026-11-06 :

- Cmnd : « If a Cmnd has associated command line arguments, the arguments in
  the Cmnd must match those given by the user on the command line. »
- Wildcards in command arguments : « Command line arguments are matched as a
  single, concatenated string. » ; « Wildcards in command line arguments should
  be used with care. » Le générateur refuse `*` et `?` partout.
- Échappement : « the following characters must be escaped with a '\' if they
  are used in command arguments: ',', ':', '=', '\'. » Les espaces internes
  sont refusés, pas échappés ; seuls les séparateurs fixes sont produits ici.
- Regular expressions : « supported by sudoers are POSIX extended regular
  expressions » ; « regular expressions must start with a `^' character and
  end with a `$' » ; « Regular expressions in sudoers are limited to 1024
  characters. » Les points et plus fixes sont échappés pour regexec, avec deux
  niveaux d'antislashs : sudoers(5), « two levels of escaping, one in the sudoers
  parser itself and another when command line arguments are matched ».
- Runas : exemple « (root) » ; NOPASSWD : « NOPASSWD: » (Tag_Spec) désactive le mot de passe pour cette commande. Aucun Defaults ajouté.
- Inclusion : « skipping file names that end in `~' or contain a `.' character » ;
  mode : « the default file mode is 0440 (readable by owner and group, writable by none). » Propriété root:root contrôlée à l'installation.

Constantes de ressources du générateur : 256 règles par commande (produit des
Choix), Hexadecimal au plus 128 caractères, expression Entier au plus 512
caractères, expression totale au plus 1024 (limite publiée). Les deux premières
bornes sont des choix conservateurs ; les intervalles décimaux sont partitionnés
exactement, sinon refus. Éléments fixes : ASCII lettres/chiffres, `/._+-` ;
chemin Docker absolu ; formes fermées restart et exec. Aucun motif libre.
Le résidu des **arguments fixes fusionnés** est traité dans isolation-remus.md
et sera réexaminé pour chaque commande de production ajoutée.

nft(8) : -f « Read input from filename. » ; -c « Check commands validity without
actually applying the changes. » ; table flush « Flush all chains and rules of
the specified table. » ; priorité filter = 0 (table des priorités), politique
« accept or drop » ; hook output pour les paquets locaux. META : skuid « originating socket » (UID) ; CONNTRACK : state « State of the connection » ;
reject « send back an error packet in response to the matched packet ».
L'idiome add table/flush table/définition recharge notre seule table ; add sans
create n'échoue pas si elle existe. network-pre.target, shutdown.target (Conflicts= et Before=
avec DefaultDependencies=no, systemd.special(7) et systemd.unit(5)) et
CAP_NET_ADMIN sont cités dans l'unité ; Type=oneshot et RemainAfterExit relèvent de
systemd.service(5). Aucun fichier journal ad hoc, sorties de l'unité vers le journal.
