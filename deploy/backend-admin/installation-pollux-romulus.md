# Installation de Pollux, de pollux-session et de Romulus sur backend-admin

**Cette procédure est remplacée par le script `deploy/backend-admin/installer-backend-admin.sh`** (page de manuel `installer-backend-admin(8)`, `--aide`). Utilisez le script ; ce document n'est conservé que comme détail de chaque étape (intention, vérifications, retours arrière).

Paramètres : fixez les variables d'environnement avant les étapes concernées.

| Variable | Rôle | Défaut |
| --- | --- | --- |
| `DEPOT` | Copie propre du dépôt | `obligatoire, sans défaut` |
| `REPERTOIRE_APP` | Répertoire personnel de app ; toute autre valeur est refusée avec la configuration livrée | `/var/lib/paresia-app` |

Version du document : 0.1.16 · 2026-11-08 · public : administrateur. Historique : `CHANGELOG.md`.

Procédure à exécuter **par vous seul, sur backend-admin, une étape à la fois**. Ne passez à l'étape suivante qu'après avoir lu le résultat de la précédente.
Chaque commande destructive ou risquée est précédée d'une ligne **ATTENTION**.

Convention de cette procédure : **aucun shell root n'est requis** (ni `sudo -i`, ni `su`, ni `sudo sh -c`). Vous travaillez sous un compte ordinaire ; chaque commande privilégiée porte son propre `sudo` et le chemin absolu de l'exécutable. Un administrateur déjà root, sans `sudo` (cas d'un backend-admin sans ce paquet), lance les mêmes commandes sans le préfixe `sudo`. Les redirections vers un fichier privilégié passent par `sudo /usr/bin/tee`. Les blocs sont écrits pour **bash**. Les blocs qui doivent s'arrêter sur erreur utilisent un sous-shell `( … )` avec `set -euo pipefail` : l'échec arrête ce bloc sans fermer votre session. Lisez son code de sortie avant de poursuivre ; un sous-shell ne transmet pas ses variables au shell appelant.

**Commandes lancées par `sudo` : liste descriptive, pas un sudoers à recopier.** Elle décrit ce que cette procédure lance. Plusieurs entrées valent root si on les autorise sans arguments figés (`env`, `python3`, `tee`, `install`, `sed -i`, `chown`, `runuser`, `find -exec`, `tar`, `systemctl` sans unité) ; `env … python3 -P -m server.sauvegarde` et `runuser … python3 -c` ne peuvent pas être restreintes et sont propres à cette installation. Pour un sudoers, figez un par un l'exécutable, le compte cible et les arguments exacts (unités pour `systemctl`, chemins pour `install`, `tee`, `sed` et `chown`).

- outil de sauvegarde : `/usr/bin/env PYTHONPATH=/run/paresia-installation PARESIA_SAUVEGARDE_CONFIG=… /usr/bin/python3 -P -m server.sauvegarde` (`jeu`, `copier`, `retrouver`, `restaurer`) ;
- comptes : `/usr/sbin/groupadd`, `/usr/sbin/useradd`, `/usr/sbin/usermod`, `/usr/bin/gpasswd`, `/usr/sbin/userdel`, `/usr/sbin/groupdel` ;
- fichiers : `/usr/bin/install`, `/usr/bin/tar`, `/usr/bin/chown`, `/usr/bin/find … -exec /usr/bin/chmod`, `/usr/bin/tee -a` (ligne de test), `/usr/bin/rm`, `/usr/bin/rmdir`, `/usr/bin/sed`, `/usr/bin/stat`, `/usr/bin/ls`, `/usr/bin/test` ;
- sshd : `/usr/sbin/sshd` (`-t`, `-T -C user=…`) ; `/usr/bin/systemctl` (`reload ssh`, `daemon-reload`, `start`, `stop`, `status`, `enable`, `disable`, `is-enabled` pour `pollux.service` et `romulus.service`) ; `/usr/bin/systemd-analyze verify` ;
- lecture : `/usr/bin/nsenter -t <pid de pollux> -m -- /usr/bin/ls -l …` ; `/usr/bin/journalctl -u <unité> -n 30 --no-pager` ; `/usr/sbin/runuser -u nobody|www-data -- /usr/bin/python3 -c …` ou `/usr/bin/curl …`.

La fonction `outil` est définie à l'étape 1, après la copie réussie du code.

Livrables (dossier `deploy/backend-admin/` du dépôt, plus `server/`) :

| Fichier | Destination |
| --- | --- |
| `etc/systemd/system/pollux.service`, `romulus.service` | `/etc/systemd/system/` |
| `server/conf/paresia.conf` | `/etc/paresia/paresia.conf` (partagé avec l'installation de bunkerd) |
| `etc/paresia/conf.d/10-backend-admin.conf` | `/etc/paresia/conf.d/10-backend-admin.conf` |
| `usr/local/lib/paresia/romulus/services/*.toml` (quatre fichiers) | `/usr/local/lib/paresia/romulus/services/` |
| `etc/ssh/sshd_config.d/50-paresia-app.conf` | `/etc/ssh/sshd_config.d/50-paresia-app.conf` |
| `server/` (sans `conf/`) | `/usr/local/lib/paresia/server/` |
| `server/bin/pollux-session` | `/usr/local/bin/pollux-session` |
| `VERSION` (racine du dépôt) | `/usr/local/lib/paresia/VERSION` (à côté de `server/`, lu par les démons) |

**Identifiants : le script les fait attribuer par le système.** Le script `installer-backend-admin.sh`
crée les comptes et groupes sans numéro imposé (`groupadd --system`, `useradd --system`), relève les
identifiants choisis dans la plage système de `login.defs(5)` et les reporte dans la copie installée de
`10-backend-admin.conf`. Les numéros ci-dessous et dans les commandes de cette procédure pas à pas sont
ceux de l'exemple du dépôt ; sur une installation faite à la main, adaptez-les ou reportez de même ceux
que le système attribue. Le script reprend un compte existant conforme (plage système, groupe primaire du
même nom, mêmes répertoire et interpréteur) et refuse (code 78) tout autre.

Exemple de numéros : comptes `paresia-pollux` 980, `paresia-romulus` 981, `paresia-tunnel` 982
(provisoire : il ne sert ici qu'à donner une valeur à `castor.uid` ; sa clé, son unité et sa mise en
place relèvent de la procédure du tunnel), `app` 983 ; groupes `paresia-sessions` 984, `paresia-liaison`
985, `paresia-http` 986 ; `www-data` 33 (identifiant statique de Debian).

Dans les commandes, `DEPOT` désigne une copie propre du dépôt déjà présente sur backend-admin (la copie
du dépôt vers la machine est laissée à vous) : `export DEPOT=<chemin-de-la-copie>`.

Limites connues à lire avant de commencer :

- Tout processus de l'uid `app` peut forger `SSH_USER_AUTH` : le nom de l'administrateur n'est
  une preuve d'identité que si le client signe le défi de présence (paresia-admin le fait ; voir
  `SECURITY.md`). Sans le paquet `python3-cryptography`, Pollux refuse toute ouverture (`not_available`).
- Redémarrer ou arrêter Pollux ou Romulus ferme toutes les sessions de présence.
- `AcceptEnv` : un bloc `Match` ne peut pas vider la liste posée par la configuration principale ; le
  client peut donc transmettre `LANG` et `LC_*`. Sans effet : le lanceur `pollux-session` vide
  l'environnement (`env -i`).
- Castor est absent tant que le tunnel n'existe pas : `pollux-relay` et la fermeture de session
  renvoient alors `peer_unavailable`. Aucune vérification ci-dessous ne suppose Castor présent.
- `StrictModes yes` et `PermitUserEnvironment no` sont posés **hors** du bloc `Match`, car `sshd_config(5)`
  ne les permet pas dans un `Match` ; ce sont les valeurs par défaut d'OpenSSH, appliquées à tous les comptes.

## Étape 1 — Prérequis (lecture seule)

Intention : vérifier la machine avant toute modification.

```bash
(
set -euo pipefail
: "${DEPOT:?Fixez DEPOT vers une copie propre du dépôt}"
. /etc/os-release; echo "$PRETTY_NAME"
systemctl --version | head -n 1
python3 --version
command -v curl ssh-keygen
if test -x /usr/sbin/sshd; then
    echo '/usr/sbin/sshd présent'
else
    echo '/usr/sbin/sshd absent : ne pas poursuivre' >&2
fi
who
)
```

Résultat attendu : Debian 13 ; systemd 257 ou plus (sinon, voir étape 9 : `::ro` est retiré) ; Python
3.11 ou plus ; `curl`, `ssh-keygen` et `sshd` présents (le paquet `acl` n'est pas requis). Sauvegardes
en place. **Une deuxième session SSH vers backend-admin est ouverte et restera ouverte jusqu'à l'étape 13.**

Sauvegardes : toute copie de sauvegarde passe par l'outil `python3 -P -m server.sauvegarde`,
lancé depuis une copie du code appartenant à `root` (`PYTHONPATH` fixé en dur par la fonction `outil` ; voir plus bas). Il range les
jeux datés sous `/var/backups/paresia/admin/<AAAAMMJJ-HHMMSS>/` (dossiers `root:root` 0700), refuse de copier
une clé privée, borne la taille totale et supprime les jeux les plus anciens au-delà. Réglages : section
`[sauvegarde.stockage]` (`actif`, `taille_max_mio`, `dossier`, `machine`) ; pendant cette procédure, la
configuration livrée du dépôt s'applique (`PARESIA_SAUVEGARDE_CONFIG`) ; pour désactiver les sauvegardes,
exporter `PARESIA_SAUVEGARDE_STOCKAGE_ACTIF=non` dans votre shell avant tout appel de `outil`, qui la transmet à l'outil (aucune copie n'est alors faite et les retours arrière
échouent faute de sauvegarde). `restaurer` ne supprime jamais un fichier sans avoir retrouvé sa sauvegarde ou
la marque d'absence enregistrée avant la pose du fichier ; sinon il répond 5 et ne modifie rien. Les retours
arrière sont des commandes successives : arrêtez-vous à la première restauration en échec (code 5).

Lancement de l'outil : l'outil s'exécute en root ; il ne s'exécute donc jamais depuis le clone du
dépôt, que d'autres comptes peuvent avoir modifié. Le bloc suivant copie d'abord `server/` du clone dans le
dossier de travail `/run/paresia-installation` (`root` 0700, sur tmpfs) par `sudo /usr/bin/install -o root -g root`
(fichiers 0644, dossiers 0755, propriétaire `root`), en refusant tout lien symbolique ou fichier spécial dans la
source (échec et arrêt) ; `__pycache__` n'est pas copié. Seule une copie réussie définit la fonction `outil`
(qui fixe `PYTHONPATH` à `/run/paresia-installation` et `PARESIA_SAUVEGARDE_CONFIG`) ; un échec la supprime : sans
copie réussie, aucun appel de l'outil n'aboutit. L'outil est lancé par `python3 -P -m` (option `-P` : ni le
répertoire courant ni celui d'un script n'est ajouté à `sys.path`). Si la copie existe déjà (reprise de la
procédure), le bloc s'arrête : retirez d'abord `/run/paresia-installation/server` à la main (commande destructive :
ne viser que ce dossier), puis rejouez le bloc.

ATTENTION : si le message « Copie du code impossible » s'affiche, arrêtez-vous ; corrigez la source (lien symbolique ou fichier spécial dans `server/`, copie déjà présente) avant de poursuivre.

```bash
if test -d "$DEPOT/server" && test ! -L "$DEPOT/server" \
   && test -z "$(find "$DEPOT/server" ! -type d ! -type f -print -quit)" \
   && sudo /usr/bin/test ! -e /run/paresia-installation/server \
   && sudo /usr/bin/install -d -o root -g root -m 0700 /run/paresia-installation \
   && (cd "$DEPOT" && find server -name __pycache__ -prune -o -type d -print0 | while IFS= read -r -d '' d; do sudo /usr/bin/install -d -o root -g root -m 0755 "/run/paresia-installation/$d" < /dev/null || exit 1; done) \
   && (cd "$DEPOT" && find server -name __pycache__ -prune -o -type f -print0 | while IFS= read -r -d '' f; do sudo /usr/bin/install -o root -g root -m 0644 -- "$DEPOT/$f" "/run/paresia-installation/$f" < /dev/null || exit 1; done); then
  outil() { sudo /usr/bin/env PYTHONPATH=/run/paresia-installation PARESIA_SAUVEGARDE_CONFIG=/run/paresia-installation/server/conf/paresia.conf ${PARESIA_SAUVEGARDE_STOCKAGE_ACTIF:+PARESIA_SAUVEGARDE_STOCKAGE_ACTIF="$PARESIA_SAUVEGARDE_STOCKAGE_ACTIF"} /usr/bin/python3 -P -m server.sauvegarde "$@"; }
else
  unset -f outil
  echo 'Copie du code impossible : ne pas poursuivre' >&2
fi
```

Résultat attendu : aucun message ; `/run/paresia-installation/server` existe et appartient à `root`.

ATTENTION : cette commande crée `/var/backups/paresia` et `/var/backups/paresia/admin` (root:root 0700) et un
jeu daté ; aucune clé n'y est copiée.

```bash
JEU_DOSSIER=$(outil jeu) || echo 'Échec du jeu de sauvegarde : ne pas poursuivre' >&2
JEU=${JEU_DOSSIER##*/}
export JEU
echo "Jeu : $JEU"
```

Résultat attendu : un nom `AAAAMMJJ-HHMMSS` (le jeu apparaît avec `python3 -P -m server.sauvegarde lister`). Avec
les sauvegardes désactivées, « sauvegardes désactivées » est affiché et rien n'est créé. Dans une nouvelle
session, refaire `DEPOT` et rejouer la copie du code (elle définit la fonction `outil`), puis fixer `JEU` au nom relevé par `lister`.

Retour arrière : seul le jeu de sauvegarde est créé ; il est conservé (la rotation le supprime au besoin).

## Étape 2 — Identifiants libres (lecture seule)

Intention : s'assurer qu'aucun identifiant d'exemple n'est déjà pris.

```bash
sudo /usr/bin/stat -c '%U:%G %a %n' /var/lib/paresia-app /var/lib/paresia-app/.ssh
getent passwd 980 981 982 983
getent group 984 985 986
getent passwd paresia-pollux paresia-romulus paresia-tunnel app
getent group paresia-pollux paresia-romulus paresia-tunnel app paresia-sessions paresia-liaison paresia-http
getent passwd www-data | cut -d: -f1,3
```

Résultat attendu : `stat` signale les dossiers absents ; les quatre commandes `getent` suivantes n'affichent **rien** ; la dernière affiche
`www-data:33`. Si l'un des identifiants ou des noms est pris : **arrêtez-vous** et signalez-le au
mainteneur, ne créez rien.

Retour arrière : sans objet.

## Étape 3 — Groupes et comptes

Source installée : useradd(8), --home-dir : « The new user will be created using
HOME_DIR as the value for the user's login directory. The default is to append the
LOGIN name to BASE_DIR and use that as the login directory name. » ; --base-dir :
« /home by default. » ; --no-create-home : « Do not create the user's home directory,
even if the system wide setting from /etc/login.defs (CREATE_HOME) is set to yes. »
Sans --home-dir, le répertoire de connexion reste donc sous BASE_DIR (par défaut
/home), même avec --no-create-home. Les comptes sans répertoire utile reçoivent
explicitement /nonexistent ; seuls app et tunnel ont un répertoire réel sous
/var/lib (Filesystem Hierarchy Standard, section /var/lib : état variable).

La page installée adduser.conf(5), vérifiée par `man -w adduser.conf`, ne décrit pas
/nonexistent ; sa rubrique « SEE ALSO » renvoie à adduser(8). Cette dernière précise,
pour les utilisateurs système : « If no home directory is specified, the default home
directory for a new system user is /nonexistent. This directory should never exist on
any Debian system, and adduser will never create it automatically. »

Intention : créer les groupes, puis les comptes, aux identifiants d'exemple. `app` n'a ni mot de passe
ni `sudo`.

ATTENTION : `groupadd` et `useradd` modifient `/etc/group`, `/etc/passwd` et `/etc/shadow`.

```bash
(
set -euo pipefail
REPERTOIRE_APP="${REPERTOIRE_APP:-/var/lib/paresia-app}"
if test "$REPERTOIRE_APP" != /var/lib/paresia-app; then
    echo 'REPERTOIRE_APP doit valoir /var/lib/paresia-app avec la configuration livrée' >&2
    exit 1
fi
sudo /usr/sbin/groupadd --system --gid 984 paresia-sessions
sudo /usr/sbin/groupadd --system --gid 985 paresia-liaison
sudo /usr/sbin/groupadd --system --gid 986 paresia-http
sudo /usr/sbin/groupadd --system --gid 980 paresia-pollux
sudo /usr/sbin/groupadd --system --gid 981 paresia-romulus
sudo /usr/sbin/groupadd --system --gid 982 paresia-tunnel
sudo /usr/sbin/groupadd --system --gid 983 app
sudo /usr/sbin/useradd --system --uid 980 --gid 980 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin paresia-pollux
sudo /usr/sbin/useradd --system --uid 981 --gid 981 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin paresia-romulus
sudo /usr/sbin/useradd --system --uid 982 --gid 982 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin paresia-tunnel
sudo /usr/sbin/useradd --system --uid 983 --gid 983 --no-create-home --home-dir "$REPERTOIRE_APP" --shell /bin/sh app
)
```

Résultat attendu :

```bash
id paresia-pollux; id paresia-romulus; id paresia-tunnel; id app
```

affiche les uid et gid 980, 981, 982, 983 (`app` : `uid=983(app) gid=983(app)`).

Retour arrière (dans cet ordre) :

ATTENTION : `userdel` et `groupdel` sont destructifs.

```bash
sudo /usr/sbin/userdel app; sudo /usr/sbin/userdel paresia-tunnel; sudo /usr/sbin/userdel paresia-romulus; sudo /usr/sbin/userdel paresia-pollux
sudo /usr/sbin/groupdel app; sudo /usr/sbin/groupdel paresia-tunnel; sudo /usr/sbin/groupdel paresia-romulus; sudo /usr/sbin/groupdel paresia-pollux
sudo /usr/sbin/groupdel paresia-http; sudo /usr/sbin/groupdel paresia-liaison; sudo /usr/sbin/groupdel paresia-sessions
```

## Étape 4 — Appartenance aux groupes

Intention : `app` rejoint `paresia-sessions` (socket de Pollux) ; `www-data` rejoint `paresia-http`
(socket HTTP de Romulus). `usermod -aG` ajoute, il ne remplace jamais. lighttpd prend ce groupe à son
prochain redémarrage (hors de cette procédure).

ATTENTION : `usermod` modifie `/etc/group` ; ne jamais utiliser `-G` sans `-a`.

```bash
sudo /usr/sbin/usermod -aG paresia-sessions app
sudo /usr/sbin/usermod -aG paresia-http www-data
```

Résultat attendu :

```bash
id -nG app; id -nG www-data
```

affiche `paresia-sessions` pour `app` et `paresia-http` pour `www-data`, sans perte des groupes
précédents de `www-data`.

Retour arrière :

ATTENTION : `gpasswd -d` retire un compte d'un groupe.

```bash
sudo /usr/bin/gpasswd -d app paresia-sessions
sudo /usr/bin/gpasswd -d www-data paresia-http
```

## Étape 5 — Dossier personnel de `app`

Intention : `/var/lib/paresia-app`, `/var/lib/paresia-app/.ssh` et `authorized_keys` appartiennent à root et ne sont pas
modifiables par `app` : `StrictModes yes` les accepte et `app` ne peut ni ajouter de clé ni créer de
fichier de profil ou d'environnement. `authorized_keys` reste vide pour l'instant.

ATTENTION : `install` écrase le fichier cible s'il existe ; le résultat de l'étape 2 garantit qu'il n'existe pas, et l'outil en consigne l'absence (marque d'absence) pour que le retour arrière puisse le retirer.

```bash
(
set -euo pipefail
REPERTOIRE_APP="${REPERTOIRE_APP:-/var/lib/paresia-app}"
if test "$REPERTOIRE_APP" != /var/lib/paresia-app; then
    echo 'REPERTOIRE_APP doit valoir /var/lib/paresia-app avec la configuration livrée' >&2
    exit 1
fi
outil copier --si-absent --jeu "$JEU" "$REPERTOIRE_APP/.ssh/authorized_keys"
sudo /usr/bin/install -d -m 0755 -o root -g root "$REPERTOIRE_APP" "$REPERTOIRE_APP/.ssh"
sudo /usr/bin/install -m 0644 -o root -g root /dev/null "$REPERTOIRE_APP/.ssh/authorized_keys"
)
```

Résultat attendu :

```bash
(
set -euo pipefail
REPERTOIRE_APP="${REPERTOIRE_APP:-/var/lib/paresia-app}"
if test "${REPERTOIRE_APP:?}" != /var/lib/paresia-app; then
    echo 'REPERTOIRE_APP doit valoir /var/lib/paresia-app avec la configuration livrée' >&2
    exit 1
fi
sudo /usr/bin/stat -c '%U:%G %a %n' "${REPERTOIRE_APP:?}" "${REPERTOIRE_APP:?}/.ssh" "${REPERTOIRE_APP:?}/.ssh/authorized_keys"
sudo /usr/bin/ls -A "${REPERTOIRE_APP:?}"
)
```

affiche `root:root 755` pour les deux dossiers et `root:root 644` pour le fichier ; `ls -A` ne montre
que `.ssh` (ni `.profile`, ni `.bashrc`, ni fichier d'environnement).

Retour arrière : l'outil retire `authorized_keys` (marque d'absence) puis les deux dossiers vides sont supprimés.

ATTENTION : la restauration retire le fichier créé par l'étape et `rmdir` supprime les dossiers s'ils sont vides ; l'arrêt est immédiat si l'outil ne retrouve pas la marque (code 5).

```bash
(
set -euo pipefail
REPERTOIRE_APP="${REPERTOIRE_APP:-/var/lib/paresia-app}"
if test "${REPERTOIRE_APP:?}" != /var/lib/paresia-app; then
    echo 'REPERTOIRE_APP doit valoir /var/lib/paresia-app avec la configuration livrée' >&2
    exit 1
fi
outil restaurer --jeu "$JEU" "${REPERTOIRE_APP:?}/.ssh/authorized_keys"
sudo /usr/bin/rmdir "${REPERTOIRE_APP:?}/.ssh" "${REPERTOIRE_APP:?}"
)
```

## Étape 6 — Code et lanceur

Intention : installer le code sous `/usr/local/lib/paresia/server/` (sans `conf/` ni `__pycache__`) et le
lanceur sous `/usr/local/bin/pollux-session`, tous à root, rien d'inscriptible par un autre compte.
Aucune compilation, aucun `pip`. Une version déjà installée est d'abord **sauvegardée** par l'outil (`copier --arbre`),
puis retirée ; son absence est consignée si elle n'existe pas.

ATTENTION : `rm -r` retire l'ancien code seulement après la réussite de la sauvegarde (`&&`), `install` écrase le lanceur ; jamais de `rm -rf`. Si un message « ne pas poursuivre » s'affiche, arrêtez-vous.

```bash
sudo /usr/bin/install -d -m 0755 -o root -g root /usr/local/lib/paresia
outil copier --arbre --si-absent --jeu "$JEU" /usr/local/lib/paresia/server /usr/local/lib/paresia/VERSION /usr/local/bin/pollux-session
if [ -e /usr/local/lib/paresia/server ]; then
    outil retrouver --jeu "$JEU" /usr/local/lib/paresia/server > /dev/null && sudo /usr/bin/rm -r /usr/local/lib/paresia/server || echo 'Sauvegarde introuvable ou retrait impossible : ne pas poursuivre' >&2
fi
if test -z "$(find "$DEPOT/server" ! -type d ! -type f -print -quit)"; then
    sudo /usr/bin/tar -C "$DEPOT" --exclude='__pycache__' --exclude='server/conf' -cf - server | sudo /usr/bin/tar -C /usr/local/lib/paresia -xf - --no-same-owner
    sudo /usr/bin/install -m 0644 -o root -g root "$DEPOT/VERSION" /usr/local/lib/paresia/VERSION
    sudo /usr/bin/install -m 0755 -o root -g root "$DEPOT/server/bin/pollux-session" /usr/local/bin/pollux-session
else
    echo 'Lien symbolique ou fichier spécial dans server/ : ne pas poursuivre' >&2
fi
```

ATTENTION : `chown -R` change le propriétaire de tout l'arbre indiqué ; vérifiez le chemin avant de lancer.

```bash
sudo /usr/bin/chown -R root:root /usr/local/lib/paresia/server
sudo /usr/bin/find /usr/local/lib/paresia/server -type d -exec /usr/bin/chmod 0755 {} +
sudo /usr/bin/find /usr/local/lib/paresia/server -type f -exec /usr/bin/chmod 0644 {} +
```

Résultat attendu :

```bash
find /usr/local/lib/paresia ! -user root -o -perm /022 | head
sudo /usr/bin/stat -c '%U:%G %a %n' /usr/local/bin/pollux-session /usr/local/lib/paresia/server /usr/local/lib/paresia/VERSION
sudo /usr/bin/ls /usr/local/lib/paresia/server
```

La première commande n'affiche **rien** ; le lanceur est `root:root 755`, le dossier `root:root 755`,
le fichier `VERSION` `root:root 644` ; `conf` n'apparaît pas dans la liste. Le fichier `VERSION` doit être à
côté du dossier `server/` : les démons le lisent au démarrage (`--version`) et sortent avec le code 70
(`internal_error`) s'il manque.

Retour arrière : l'outil rétablit le code et le lanceur sauvegardés, ou les retire s'ils n'existaient pas.

ATTENTION : la restauration remplace le dossier courant (l'ancien est déplacé de côté puis supprimé seulement après le succès) et le lanceur ; elle s'arrête sans rien modifier si une sauvegarde manque (code 5).

```bash
outil restaurer --jeu "$JEU" /usr/local/lib/paresia/server
outil restaurer --jeu "$JEU" /usr/local/lib/paresia/VERSION
outil restaurer --jeu "$JEU" /usr/local/bin/pollux-session
```

## Étape 7 — Configuration (étape partagée avec l'installation de bunkerd)

Intention : installer `/etc/paresia/paresia.conf` et la surcharge `conf.d/10-backend-admin.conf`, à
root, non inscriptibles. Si l'installation de bunkerd a déjà posé `paresia.conf`, cette étape le
constate : comparez avant d'écraser.

ATTENTION : `install` écrase un fichier existant ; l'outil le sauvegarde avant (ou consigne son absence) et un rejeu ne remplace jamais la première sauvegarde du jeu.

```bash
sudo /usr/bin/install -d -m 0755 -o root -g root /etc/paresia /etc/paresia/conf.d
outil copier --si-absent --jeu "$JEU" /etc/paresia/paresia.conf /etc/paresia/conf.d/10-backend-admin.conf
sudo /usr/bin/install -m 0644 -o root -g root "$DEPOT/server/conf/paresia.conf" /etc/paresia/paresia.conf
sudo /usr/bin/install -m 0644 -o root -g root "$DEPOT/deploy/backend-admin/etc/paresia/conf.d/10-backend-admin.conf" /etc/paresia/conf.d/10-backend-admin.conf
```

Résultat attendu :

```bash
sudo /usr/bin/stat -c '%U:%G %a %n' /etc/paresia /etc/paresia/paresia.conf /etc/paresia/conf.d /etc/paresia/conf.d/10-backend-admin.conf
```

affiche `root:root 755` pour les deux dossiers et `root:root 644` pour les deux fichiers.

Retour arrière : l'outil restaure les deux fichiers sauvegardés, ou retire ceux que l'étape a créés.

ATTENTION : la restauration écrase ou retire les deux fichiers de configuration ; elle s'arrête sans rien modifier si une sauvegarde manque (code 5).

```bash
outil restaurer --jeu "$JEU" /etc/paresia/conf.d/10-backend-admin.conf
outil restaurer --jeu "$JEU" /etc/paresia/paresia.conf
```

## Étape 7 bis — Déclarations des services de Romulus

Intention : installer les quatre déclarations de services (bunkerd, journal légal, Nisaba, relais strfry) dans `/usr/local/lib/paresia/romulus/services/`, à root, non inscriptibles. Sans elles, les sections `[romulus.bunker]` et `[romulus.relay]` de `10-backend-admin.conf` sont inconnues et Romulus sort en code 78 au démarrage. À faire avant l'étape 10 (premier démarrage de Romulus).

ATTENTION : `install` écrase un fichier existant ; l'outil le sauvegarde avant (ou consigne son absence) et un rejeu ne remplace jamais la première sauvegarde du jeu.

```bash
D=/usr/local/lib/paresia/romulus/services
S="$DEPOT/deploy/backend-admin/usr/local/lib/paresia/romulus/services"
sudo /usr/bin/install -d -m 0755 -o root -g root /usr/local/lib/paresia /usr/local/lib/paresia/romulus "$D"
outil copier --si-absent --jeu "$JEU" "$D/paresia-yang-bunkerd.toml" "$D/paresia-yang-journal-legal.toml" "$D/paresia-yang-nisaba.toml" "$D/paresia-yang-strfry.toml" "$D/paresia-yang-webui.toml"
for n in paresia-yang-bunkerd paresia-yang-journal-legal paresia-yang-nisaba paresia-yang-strfry paresia-yang-webui; do
  sudo /usr/bin/install -m 0644 -o root -g root "$S/$n.toml" "$D/$n.toml"
done
```

Résultat attendu :

```bash
sudo /usr/bin/stat -c '%U:%G %a %n' /usr/local/lib/paresia/romulus /usr/local/lib/paresia/romulus/services /usr/local/lib/paresia/romulus/services/*.toml
```

affiche `root:root 755` pour les deux dossiers et `root:root 644` pour les quatre fichiers.

Retour arrière : l'outil restaure les quatre fichiers sauvegardés, ou retire ceux que l'étape a créés.

ATTENTION : la restauration écrase ou retire les cinq fichiers ; elle s'arrête sans rien modifier si une sauvegarde manque (code 5).

```bash
outil restaurer --jeu "$JEU" /usr/local/lib/paresia/romulus/services/paresia-yang-strfry.toml
outil restaurer --jeu "$JEU" /usr/local/lib/paresia/romulus/services/paresia-yang-nisaba.toml
outil restaurer --jeu "$JEU" /usr/local/lib/paresia/romulus/services/paresia-yang-journal-legal.toml
outil restaurer --jeu "$JEU" /usr/local/lib/paresia/romulus/services/paresia-yang-bunkerd.toml
outil restaurer --jeu "$JEU" /usr/local/lib/paresia/romulus/services/paresia-yang-webui.toml
```

## Étape 8 — Réglages sshd du compte `app`

Intention : installer `50-paresia-app.conf` (`StrictModes yes`, `PermitUserEnvironment no`, puis le bloc
`Match User app` : `ExposeAuthInfo yes`, `ClientAliveInterval 15`, `ClientAliveCountMax 3`,
`PasswordAuthentication no`, `AuthenticationMethods publickey`).

Avant tout : vérifier que la configuration principale inclut `sshd_config.d` (`sshd -T` n'affiche pas
les `Include`) :

```bash
grep -n -i '^[[:space:]]*Include' /etc/ssh/sshd_config
```

Résultat attendu : une ligne `Include /etc/ssh/sshd_config.d/*.conf`. Sinon, **arrêtez-vous**.

ATTENTION : `install` écrase un éventuel fichier du même nom ; l'outil le sauvegarde d'abord, ou consigne son absence.

```bash
sudo /usr/bin/ls /etc/ssh/sshd_config.d/50-paresia-app.conf 2>/dev/null || true
outil copier --si-absent --jeu "$JEU" /etc/ssh/sshd_config.d/50-paresia-app.conf
sudo /usr/bin/install -m 0644 -o root -g root "$DEPOT/deploy/backend-admin/etc/ssh/sshd_config.d/50-paresia-app.conf" /etc/ssh/sshd_config.d/50-paresia-app.conf
sudo /usr/sbin/sshd -t
sudo /usr/sbin/sshd -T -C user=app,host=backend-admin.example.org,addr=192.0.2.10 | grep -i -E '^(exposeauthinfo|clientaliveinterval|clientalivecountmax|strictmodes|permituserenvironment|passwordauthentication|authenticationmethods) '
sudo /usr/sbin/sshd -T -C user=nobody,host=backend-admin.example.org,addr=192.0.2.10 | grep -i -E '^(exposeauthinfo|clientaliveinterval) '
```

Résultat attendu : `sshd -t` ne dit rien. Pour `app` : `exposeauthinfo yes`, `clientaliveinterval 15`,
`clientalivecountmax 3`, `strictmodes yes`, `permituserenvironment no`, `passwordauthentication no`,
`authenticationmethods publickey`. Pour l'autre compte : `exposeauthinfo no` (et l'intervalle propre à
votre configuration). La première commande ne doit rien afficher si le fichier est nouveau.

Prise en compte (ATTENTION : garder la deuxième session ouverte, `sshd -t` doit avoir réussi) :

ATTENTION : `systemctl reload ssh` recharge sshd ; une configuration invalide ou une erreur ferme l'accès. Ne rechargez qu'avec une session de secours ouverte.

```bash
sudo /usr/bin/systemctl reload ssh
```

Résultat attendu : la session de secours fonctionne toujours (nouvelle connexion de test depuis le poste client).

Retour arrière : l'outil rétablit le fichier précédent ou retire celui que l'étape a créé.

ATTENTION : la restauration écrase ou retire le fichier ; testez ensuite avec `sshd -t` avant de recharger, session de secours ouverte.

```bash
outil restaurer --jeu "$JEU" /etc/ssh/sshd_config.d/50-paresia-app.conf
sudo /usr/sbin/sshd -t
sudo /usr/bin/systemctl reload ssh
```

## Étape 9 — Unités systemd

Intention : copier les unités, recharger systemd, les vérifier. Chaque unité porte
`ConfigurationDirectory=paresia::ro` et `ConfigurationDirectoryMode=0755`. Le drapeau `::ro` exige
systemd 257 ou plus (étape 1).

Si `systemctl --version` donne un numéro **inférieur à 257**, retirer `::ro` des copies installées :

ATTENTION : `sed -i` modifie les unités installées (pas celles du dépôt). Sautez cette commande si systemd est 257 ou plus.

```bash
sudo /usr/bin/sed -i 's/^ConfigurationDirectory=paresia::ro$/ConfigurationDirectory=paresia/' /etc/systemd/system/pollux.service /etc/systemd/system/romulus.service
```

(à lancer après la copie ci-dessous, avant `daemon-reload`.)

ATTENTION : `install` écrase des unités existantes ; l'outil les sauvegarde d'abord (ou consigne leur absence).

```bash
for u in pollux romulus; do
  outil copier --si-absent --jeu "$JEU" "/etc/systemd/system/$u.service" && sudo /usr/bin/install -m 0644 -o root -g root "$DEPOT/deploy/backend-admin/etc/systemd/system/$u.service" "/etc/systemd/system/$u.service"
done
sudo /usr/bin/systemctl daemon-reload
sudo /usr/bin/systemd-analyze verify pollux.service romulus.service
```

Résultat attendu : `systemd-analyze verify` n'affiche aucune erreur concernant ces deux unités.

Retour arrière : l'outil rétablit les unités sauvegardées ou retire celles que l'étape a créées.

ATTENTION : la restauration écrase ou retire les unités installées ; elle s'arrête sans rien modifier si une sauvegarde manque (code 5).

```bash
outil restaurer --jeu "$JEU" /etc/systemd/system/pollux.service
outil restaurer --jeu "$JEU" /etc/systemd/system/romulus.service
sudo /usr/bin/systemctl daemon-reload
```

## Étape 10 — Démarrage et vérifications

Intention : démarrer Romulus puis Pollux (`start`, pas `enable`) et contrôler sockets, propriétaires et
droits. Aucune session de présence n'existe encore.

ATTENTION : tout redémarrage de Pollux ou de Romulus ferme toutes les sessions de présence. Vérifiez qu'aucun administrateur n'est connecté.

```bash
sudo /usr/bin/systemctl start romulus.service
sudo /usr/bin/systemctl start pollux.service
sudo /usr/bin/systemctl status romulus.service pollux.service --no-pager
sudo /usr/bin/journalctl -u romulus.service -n 30 --no-pager
sudo /usr/bin/journalctl -u pollux.service -n 30 --no-pager
ss -xl | grep paresia
sudo /usr/bin/stat -c '%U:%G %a %n' /run/paresia-pollux /run/paresia-romulus /run/paresia-pollux/pollux.sock /run/paresia-pollux/pollux-relay.sock /run/paresia-romulus/romulus.sock /run/paresia-romulus/romulus-http.sock
sudo /usr/bin/stat -c '%U:%G %a %n' /var/lib/paresia-pollux /var/lib/paresia-romulus
sudo /usr/bin/systemctl show -p StateDirectory pollux.service romulus.service
sudo /usr/bin/stat -c '%U:%G %a %n' /etc/paresia
sudo /usr/bin/nsenter -t "$(systemctl show -p MainPID --value pollux.service)" -m -- /usr/bin/ls -l /var/lib/paresia-app/.ssh/authorized_keys
```

Résultat attendu : le fichier `authorized_keys` est listé, `root:root 644` ; deux unités `active (running)` ; journaux sans erreur ; quatre sockets à l'écoute.

| Élément | Attendu |
| --- | --- |
| `/run/paresia-pollux`, `/run/paresia-romulus` | `paresia-pollux:paresia-pollux 711`, `paresia-romulus:paresia-romulus 711` |
| `/var/lib/paresia-pollux`, `/var/lib/paresia-romulus` (dossiers d'état, `StateDirectory=` ; `systemctl show` : `StateDirectory=paresia-pollux`, `StateDirectory=paresia-romulus`) | `paresia-pollux:paresia-pollux 711`, `paresia-romulus:paresia-romulus 711` |
| `pollux.sock` | `paresia-pollux:paresia-sessions 660` |
| `pollux-relay.sock` | `paresia-pollux:paresia-liaison 660` |
| `romulus.sock` | `paresia-romulus:paresia-liaison 660` |
| `romulus-http.sock` | `paresia-romulus:paresia-http 660` |
| `/etc/paresia` | `root:root 755` |

Si `/etc/paresia` n'est plus à `root:root`, ou devient inscriptible par un compte de service :
**arrêtez** les unités, signalez-le au mainteneur, ne continuez pas. De même si un propriétaire de
socket diffère du tableau (le droit de `chown` vers un groupe supplémentaire n'est pas confirmé par la
documentation de systemd). Contrôle de l'arrêt : après `systemctl stop`, les dossiers `/run/paresia-*`
ont disparu ; les dossiers d'état `/var/lib/paresia-pollux` et `/var/lib/paresia-romulus` sont conservés.
Au retour arrière complet, le script les retire par `rmdir`, seulement s'ils sont vides (ils sont créés
par systemd, jamais par le script).

Retour arrière :

ATTENTION : l'arrêt de Pollux ou de Romulus ferme toutes les sessions de présence.

```bash
sudo /usr/bin/systemctl stop pollux.service romulus.service
```

## Étape 11 — Contrôles de refus

Intention : un compte tiers ne peut pas ouvrir les sockets ; `www-data` n'obtient pas d'action sans jeton.

```bash
sudo /usr/sbin/runuser -u nobody -- /usr/bin/python3 -c "import socket; s=socket.socket(socket.AF_UNIX); s.connect('/run/paresia-pollux/pollux.sock')"
sudo /usr/sbin/runuser -u nobody -- /usr/bin/python3 -c "import socket; s=socket.socket(socket.AF_UNIX); s.connect('/run/paresia-romulus/romulus-http.sock')"
sudo /usr/sbin/runuser -u www-data -- /usr/bin/curl -s -w ' %{http_code}\n' --unix-socket /run/paresia-romulus/romulus-http.sock -X POST http://localhost/api/admin/bunker/identity/list
sudo /usr/sbin/runuser -u www-data -- /usr/bin/curl -s -w ' %{http_code}\n' --unix-socket /run/paresia-romulus/romulus-http.sock -X GET http://localhost/api/admin/bunker/identity/list
```

Résultat attendu : les deux premières commandes se terminent par `PermissionError` ; la troisième
affiche un corps contenant `token_missing` suivi de `403` ; la quatrième affiche `405`. (Si `www-data`
obtient `PermissionError`, il n'a pas encore le groupe `paresia-http` : étape 4.)

Retour arrière : sans objet (lecture seule).

## Étape 12 — Essai de bout en bout (poste client)

Intention : ouvrir et fermer une session de présence avec une **clé de test générée pour l'occasion**,
sans lien avec une clé de l'administrateur. Le défi signé étant en service, cet essai simple est à adapter : l'essai complet, avec signature du défi, est décrit dans `deploy/essai-presence.md`.

Sur le poste client, générer la clé de test (fichier temporaire, sans passphrase) :

```bash
ssh-keygen -t ed25519 -N '' -C test-installation -f ./cle-test-installation
cat ./cle-test-installation.pub
```

Sur backend-admin, ajouter sa partie publique à `authorized_keys`, avec le commentaire
`test-installation`. Modèle d'une ligne (les champs entre chevrons sont à remplacer ; aucune clé réelle
dans le dépôt) :

```text
restrict,command="/usr/local/bin/pollux-session" ssh-ed25519 <clé publique de l'administrateur> <nom de l'administrateur>
```

ATTENTION : modification d'un fichier de root ; sauvegarde préalable par l'outil, dans un jeu distinct (`JEU_ESSAI`, car la première sauvegarde d'un chemin dans un jeu est conservée), puis ajout d'une seule ligne.

```bash
JEU_ESSAI=$(outil jeu) || echo 'Échec du jeu de sauvegarde : ne pas poursuivre' >&2
JEU_ESSAI=${JEU_ESSAI##*/}
export JEU_ESSAI
outil copier --jeu "$JEU_ESSAI" /var/lib/paresia-app/.ssh/authorized_keys
printf 'restrict,command="/usr/local/bin/pollux-session" %s\n' "<contenu de cle-test-installation.pub>" | sudo /usr/bin/tee -a /var/lib/paresia-app/.ssh/authorized_keys > /dev/null
sudo /usr/bin/stat -c '%U:%G %a %n' /var/lib/paresia-app/.ssh/authorized_keys
```

Résultat attendu : `root:root 644` ; la ligne se termine par le commentaire `test-installation`.

Sur le poste client, ouvrir la session SSH, puis taper les lignes NDJSON :

```bash
ssh -T -o IdentitiesOnly=yes -i ./cle-test-installation app@backend-admin.example.org
```

```text
{"proto":"jumeaux/1","id":"a1a1a1a1a1a1a1a1","session":0,"action":"presence/session/open","params":{}}
```

Résultat attendu : une réponse `{"id":"a1a1a1a1a1a1a1a1","ok":true,"data":{"session":N,"token":"…","heartbeat_s":30,"timeout_s":90}}`.
Le jeton n'est affiché que pour cette session de test ; ne le conservez pas. Fermer ensuite, en remplaçant
`N` par le numéro reçu, puis fin d'entrée (Ctrl-D) :

```text
{"proto":"jumeaux/1","id":"b2b2b2b2b2b2b2b2","session":N,"action":"presence/session/close","params":{}}
```

Sur backend-admin, vérifier le journal :

```bash
sudo /usr/bin/journalctl -u pollux.service -n 30 --no-pager | grep -E 'session_opened|session_closed'
```

Résultat attendu : `session_opened` puis `session_closed`, sans jeton. Si sshd refuse le compte, lire
`sudo /usr/bin/journalctl -u ssh -n 30 --no-pager` et signaler la cause au mainteneur ; ne contournez pas par un mot
de passe.

Nettoyage obligatoire : retirer la ligne de test, supprimer la clé de test.

ATTENTION : restauration de `authorized_keys` depuis la sauvegarde (écrasement) ; elle s'arrête sans rien modifier si la sauvegarde manque (code 5).

```bash
outil restaurer --jeu "$JEU_ESSAI" /var/lib/paresia-app/.ssh/authorized_keys
sudo /usr/bin/stat -c '%U:%G %a %n' /var/lib/paresia-app/.ssh/authorized_keys
```

Sur le poste client :

ATTENTION : `rm` supprime définitivement la clé de test.

```bash
rm ./cle-test-installation ./cle-test-installation.pub
```

Retour arrière : le nettoyage ci-dessus ; le jeu `JEU_ESSAI` est conservé et disparaîtra par la rotation de l'outil.

## Étape 13 — Activation au démarrage ou retour arrière complet

Intention : n'activer qu'après conformité de toutes les étapes précédentes.

ATTENTION : `systemctl enable` est persistant ; ne l'exécutez que si tout est conforme.

```bash
sudo /usr/bin/systemctl enable pollux.service romulus.service
sudo /usr/bin/systemctl is-enabled pollux.service romulus.service
```

Résultat attendu : `enabled` pour les deux unités.

Retour arrière complet (si un contrôle a échoué) : dans cet ordre, arrêt, retrait des unités, du bloc
sshd, du code et de la configuration (seulement ce que cette procédure a posé), puis des comptes et
groupes. Pour chaque commande, relire d'abord l'étape de pose correspondante.

ATTENTION : l'arrêt ferme toutes les sessions ; la restauration écrase ou retire les fichiers installés, `userdel` et `groupdel` sont destructifs ; `sshd -t` d'abord, puis `systemctl reload ssh` avec la session de secours ouverte ; le bloc s'arrête à la première restauration en échec (code 5 : sauvegarde introuvable, rien n'est supprimé).

```bash
sudo /usr/bin/systemctl disable --now pollux.service romulus.service
outil restaurer --jeu "$JEU" /etc/systemd/system/pollux.service
outil restaurer --jeu "$JEU" /etc/systemd/system/romulus.service
sudo /usr/bin/systemctl daemon-reload
outil restaurer --jeu "$JEU" /etc/ssh/sshd_config.d/50-paresia-app.conf
sudo /usr/sbin/sshd -t
sudo /usr/bin/systemctl reload ssh
outil restaurer --jeu "$JEU" /etc/paresia/conf.d/10-backend-admin.conf
for n in strfry nisaba journal-legal bunkerd; do outil restaurer --jeu "$JEU" "/usr/local/lib/paresia/romulus/services/paresia-yang-$n.toml"; done
outil restaurer --jeu "$JEU" /usr/local/bin/pollux-session
```

Puis les étapes de retour arrière des étapes 6, 5, 4 et 3 (code, dossier de `app`, groupes, comptes).
