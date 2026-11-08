# Essai réel de la session de présence

SPDX-License-Identifier: AGPL-3.0-or-later

Paramètres : fixez les variables d'environnement avant les étapes concernées.

| Variable | Rôle | Défaut |
| --- | --- | --- |
| `DEPOT` | Copie propre du dépôt (le clone fait au préalable, qui contient les scripts d'installation) | obligatoire, sans défaut |
| `CLE_PUBLIQUE` | Clé publique de l'administrateur, forme ssh-ed25519 AAAA… | obligatoire, sans défaut |
| `ADMIN` | Nom de l'administrateur, lettres, chiffres, . _ @ - | obligatoire, sans défaut |

Avant toute étape, sur chaque machine concernée, contrôlez les paramètres obligatoires :

```bash
(
set -euo pipefail
: "${DEPOT:?Fixez DEPOT avant de commencer}"
: "${CLE_PUBLIQUE:?Fixez CLE_PUBLIQUE avant de commencer}"
: "${ADMIN:?Fixez ADMIN avant de commencer}"
)
```

Version du document : 0.1.16 · 2026-11-08 · public : administrateur. Historique : `CHANGELOG.md`.

Procédure à exécuter **par vous seul, une étape à la fois**, sur la machine indiquée en tête de chaque étape (backend-relais, backend-admin ou poste client). Lisez le résultat de chaque étape avant la suivante. Chaque commande qui modifie le système est précédée d'une ligne **ATTENTION**. Gardez une deuxième session ouverte sur chaque machine, **testée par une nouvelle connexion** avant toute modification de sshd.

**Aucun shell root n'est requis** (ni `sudo -i`, ni `su`, ni `sudo sh -c`) : chaque commande privilégiée porte son propre `sudo` et le chemin absolu de l'exécutable, pour qu'un `sudoers` restreint puisse les autoriser une à une. Un administrateur déjà root sans `sudo` (cas de backend-admin) lance les mêmes commandes sans le préfixe `sudo`. Les redirections vers un fichier privilégié passent par `sudo /usr/bin/tee`. Les variables (`DEPOT`, `JEU`, `JEU_ESSAI`, …) sont celles de votre shell ordinaire. La fonction `outil` qui lance l'outil de sauvegarde est définie plus bas (« Outil de sauvegarde »), après le premier passage du script de la machine.

**Commandes lancées par `sudo` : liste descriptive, pas un sudoers à recopier.** Elle décrit ce que l'essai lance, sur les deux machines, y compris par les scripts d'installation cités. La plupart des entrées valent root si on les autorise sans arguments figés : `env`, `python3` et `tee` (écriture ou exécution arbitraire), `install`, `sed -i`, `chown`, `cp`, `mv`, `tar`, `find -exec`, `runuser` (`-u root` passerait), `nsenter` (pid libre), `apt`, `systemctl` sans unité, `visudo`, `systemd-run`. Pour confronter cette liste à un sudoers, figez un par un l'exécutable, le compte cible et les arguments exacts : les unités pour `systemctl`, le seul compte visé pour `runuser`, les chemins pour `install`, `tee`, `sed`, `chown`, `cp`, `mv`, le pid pour `nsenter`, `--no-pager` et l'unité pour `journalctl`, les arguments de `sshd -T -C`. `env … python3 -P -m server.sauvegarde` et `runuser … python3 -c` **ne peuvent pas être restreintes** (l'argument est du code ou un chemin variable) : elles sont propres à cet essai.

- outil de sauvegarde : `/usr/bin/env PYTHONPATH=… PARESIA_SAUVEGARDE_CONFIG=… /usr/bin/python3 -P -m server.sauvegarde` (`jeu`, `releve`, `copier`, `retrouver`, `lister`, `restaurer`) ; fixer : chemins des fichiers sauvegardés ;
- fichiers : `/usr/bin/sha256sum`, `/usr/bin/install`, `/usr/bin/tee` (`-a` pour `authorized_keys` de `app`), `/usr/bin/sed -i` (`authorized_keys` de `tunnel` seulement), `/usr/bin/chown`, `/usr/bin/tar`, `/usr/bin/cp -a`, `/usr/bin/mv -T`, `/usr/bin/find … -exec /usr/bin/chmod`, `/usr/bin/rm`, `/usr/bin/rmdir`, `/usr/bin/cat`, `/usr/bin/diff`, `/usr/bin/grep`, `/usr/bin/test`, `/usr/bin/stat`, `/usr/bin/ls`, `/usr/bin/namei -l`, `/usr/bin/systemd-tmpfiles --create /etc/tmpfiles.d/paresia-tunnel.conf` ; lecture seule : `stat`, `ls`, `cat`, `diff`, `grep`, `test`, `namei` ;
- comptes et sshd : `/usr/sbin/groupadd`, `/usr/sbin/useradd`, `/usr/sbin/usermod`, `/usr/sbin/userdel`, `/usr/sbin/groupdel`, `/usr/bin/gpasswd`, `/usr/bin/passwd -S`, `/usr/bin/getent group paresia-romulus paresia-pollux`, `/usr/sbin/sshd` (`-t`, `-T -C user=…`), `/usr/bin/ssh-keygen` (`-lf`, génération de la clé du tunnel), `/usr/bin/ssh-keyscan`, `/usr/bin/ssh` (`-G`) ;
- services : `/usr/bin/systemctl` (unités `pollux`, `romulus`, `castor`, `remus`, `paresia-tunnel`, `paresia-nftables` pour `start`, `stop`, `status`, `show`, `daemon-reload` ; `reload ssh`), `/usr/bin/systemd-analyze verify`, `/usr/bin/systemd-run`, `/usr/bin/journalctl -u <unité> -n 30 --no-pager`, `/usr/bin/ss -ltnp`, `/usr/sbin/nft` (`list`, `-c -f`, `delete table inet paresia_relais` pour la table du relais) ;
- sudoers (étape `sudoers` du script de backend-relais, hors essai car sautée) : `/usr/sbin/visudo -c -f`, `/usr/bin/sudo` ;
- essais : `/usr/sbin/runuser -u chef|nobody|paresia-pollux|paresia-romulus|tunnel|www-data [-g paresia-http] -- /usr/bin/python3 -c …` ou `/usr/bin/curl …` (`nobody` pour les refus et pour la génération du sudoers, `www-data` pour le rôle de lighttpd) ; `/usr/sbin/runuser -u chef -g chef -G paresia-castor-etat -- /usr/bin/python3 -c …` (sonde de l'état de Castor) ; `/usr/bin/nsenter -t <pid> -m -- /usr/bin/ls -l /var/lib/paresia-app/.ssh/authorized_keys` ;
- produit visé par les fonctions (étape `produit` du script de backend-relais, lecture seule, aucune action sur Docker) : `/usr/bin/docker inspect --format …` ;
- paquet : `/usr/bin/apt install|remove python3-cryptography`, contrôle du prérequis `libssl3t64` en lecture seule par `/usr/bin/dpkg-query` et `/usr/bin/dpkg`.

Les fonctions `outil` (le script de la machine a copié le code sous `/run/paresia-installation` et créé le jeu `JEU`) et `sonde`/`jumeaux` sont définies dans les blocs. Les blocs sont écrits pour **bash**. Toute mention de `journalctl` s'entend comme `sudo /usr/bin/journalctl -u … -n 30 --no-pager`.

Chaque étape donne : la machine, l'intention, la commande, l'avertissement, le relevé avant, la vérification, la ligne de journal attendue et le retour arrière. Toute valeur inattendue a la même consigne : **arrêtez-vous et transmettez au mainteneur**, avec la sortie exacte. Aucune consigne ne suppose la valeur relevée.

## But et déroulement

Ouvrir depuis le poste client une session de présence (défi signé par votre agent SSH), recevoir un jeton, observer les pings de Pollux vers Castor à travers le tunnel (feu vert), fermer la session (feu rouge), puis constater le refus de Romulus sur le jeton détruit.

| Étape | Machine | Contenu |
| --- | --- | --- |
| A | backend-relais, backend-admin | relevés préalables, lecture seule |
| B | backend-relais | `backend-relais/installer-backend-relais.sh`, étapes `prerequis` à `refus_castor`, sans `produit`, `fonctions`, `sudoers`, `nftables` ni `isolation_remus` |
| C | backend-admin | `backend-admin/installer-backend-admin.sh`, étapes `prerequis` à `refus` (1re passe), puis ligne de test |
| D | backend-relais, backend-admin | parties « tunnel » des deux scripts : `tunnel_releves` à `tunnel_sockets` |
| E | poste client, backend-admin, backend-relais | scénario E1 à E6 |
| F | toutes | fin d'essai |

Ne sont **pas** dans l'essai, par le strict nécessaire : l'activation des unités au démarrage (option `--activer` des scripts, non donnée), le contrôle de l'image de strfry et la pose des fonctions du greffon strfry (`--sauter produit`, `--sauter fonctions` : l'essai porte sur le noyau seul), le sudoers de Remus (`--sauter sudoers`), la règle nftables (`--sauter nftables`), l'essai d'isolation de Remus (`--sauter isolation_remus`), l'ajout de `www-data` au groupe `paresia-http` (`--sauter www-data`) et l'essai manuel de backend-admin (remplacé par le client). Aucune commande d'administration réelle n'est possible : la table de Remus est vide.

**Rien n'arrête, ne redémarre ni ne recharge** strfry, Docker, lighttpd ni une unité étrangère à l'essai. Le seul rechargement est `systemctl reload ssh`, jamais un redémarrage de sshd, précédé de `sshd -t` et exécuté session de secours ouverte. Le rechargement ne coupe pas les sessions existantes ; le risque est une configuration erronée qui refuse les nouvelles connexions (retour arrière : restaurer le fichier, `sshd -t`, `reload`).

Chaque étape renvoie aux étapes nommées des scripts d'installation et à leurs options, **sans les recopier** : les scripts restent la référence. Seuls les contrôles propres à l'essai sont ajoutés ici.

## Machines déjà en service

Constats génériques sur des machines qui hébergent déjà des services (par exemple strfry dans Docker) ; ce qui n'est pas connu est relevé à l'étape A.

1. **Noms d'unités** : une machine en service peut déjà avoir `bunkerd.service`, des unités et minuteries de journal légal ou une tâche de purge. Aucune ne doit porter le nom d'une unité de l'essai (`pollux`, `romulus`, `paresia-tunnel`, `castor`, `remus`). `bunkerd` n'est pas installé par l'essai.
2. **Comptes** : les noms `app`, `chef`, `tunnel` peuvent être pris par un autre usage : relevé à l'étape A, arrêt si c'est le cas. Les identifiants numériques sont attribués par le système (plage système de `login.defs(5)`) et reportés par les scripts dans la configuration installée ; un compte existant conforme est repris, un autre est refusé (code 78). Les relevés de `getent` sur des numéros précis ci-dessous sont des vérifications des numéros d'exemple, à adapter à ceux que le système a attribués.
3. **Chemins** : un journal légal existant écrit sous `/var/log/paresia` ; cette procédure ne le crée, ne le modifie et ne change ni son propriétaire ni son mode. `/etc/paresia` et `/usr/local/lib/paresia` : existence relevée à l'étape A (les scripts comparent avant d'écraser et refusent un état différent).
4. **Réseau** : l'essai n'ouvre aucun port TCP (sockets Unix et sshd existant). Les ports en écoute sont relevés pour mémoire. Sur backend-relais, strfry est dans Docker : aucun rechargement de Docker, aucune règle de pare-feu.
5. **lighttpd et `www-data`** : l'essai ne modifie ni lighttpd ni le compte `www-data`. Les requêtes HTTP de E3 et E6 passent par `runuser -u www-data -g paresia-http` : Romulus n'accepte comme pair HTTP que l'UID `uid_lighttpd` (33, `www-data`, section `[romulus.http]` de `server/conf/paresia.conf`), c'est donc `www-data` qui joue le rôle de lighttpd (`runuser(1)`, `-g, --group=group` : « The primary group to be used. This option is allowed for the root user only. »). Le groupe est donné par la commande, pas par l'appartenance de `www-data` : l'option `--sauter www-data` du script de backend-admin laisse ce compte inchangé.
6. **sshd** : l'essai ajoute `50-paresia-app.conf` (backend-admin) et `50-paresia-tunnel.conf` (backend-relais). Un `Match` antérieur ou un `AllowUsers` qui exclut `app` bloque l'essai ; un `AllowUsers` qui exclut `tunnel` est traité par la sous-étape `AllowUsers` de l'étape `tunnel_sshd` du script de backend-relais.
7. **Journal** : tout passe par journald (`sudo /usr/bin/journalctl -u <unité>`) ; aucun fichier journal ad hoc.

## Étape A — Relevés préalables (lecture seule)

Machines : backend-relais, puis backend-admin. Intention : connaître l'état avant toute modification. Aucune commande de cette étape ne modifie la configuration du système.

Préalable (lecture seule) : sur chaque machine, lancez le script de la machine avec `--verifier` (paramètres et prérequis, aucune écriture). Les relevés ci-dessous sont lus sur le terminal ; en outre, le premier passage réel de chaque script (étape B ou C) les consigne lui-même, avant toute modification, dans son jeu de sauvegarde `JEU` dont le nom est affiché sur la sortie standard (relevés `comptes-avant`, `groupes-avant`, `unites-actives-avant`, `sshd-app-avant` et `sshd-tunnel-avant`).

Sur chacune des deux machines :

```bash
{ getent passwd app chef tunnel paresia-pollux paresia-romulus paresia-tunnel paresia-castor || test "$?" -eq 2; }
{ getent group app chef tunnel paresia-sessions paresia-liaison paresia-http paresia-castor-tunnel paresia-remus-tunnel paresia-castor-etat || test "$?" -eq 2; }
getent passwd 970 971 972 973 974 975 980 981 982 983
getent group 970 971 972 973 974 975 984 985 986
sudo /usr/bin/stat -c '%U:%G %a %n' /etc/paresia /etc/paresia/conf.d /usr/local/lib/paresia /usr/local/bin/pollux-session /var/lib/paresia-app /var/log/paresia 2>&1
ls -d /run/paresia-* 2>&1
/usr/bin/systemctl list-unit-files 'pollux*' 'romulus*' 'castor*' 'remus*' 'paresia-*' --no-pager
/usr/bin/systemctl list-units --type=service --state=active --no-pager
sudo /usr/sbin/sshd -T -C user=app,host=backend-admin.example.org,addr=192.0.2.50
sudo /usr/sbin/sshd -T -C user=tunnel,host=backend-admin.example.org,addr=192.0.2.50
grep -n -i -E '^[[:space:]]*(Include|AllowUsers|AllowGroups|Match|UsePAM|Port|ListenAddress)' /etc/ssh/sshd_config /etc/ssh/sshd_config.d/*.conf
sudo /usr/bin/ss -ltnp
ss -xl
systemctl --version | head -n 1
ssh -V
python3 --version
dpkg -s acl python3-cryptography curl 2>&1 | grep -E '^(Package|Status):'
```

Le deuxième relevé `getent` est vide dans le cas normal. Seul backend-relais : `sudo --version | head -n 1`, `ls -d /run/sudo`, `id -nG chef` (ne contient pas `docker`), `sudo /usr/sbin/nft list ruleset` (relevé seulement, aucune règle n'est chargée ni modifiée).

Les relevés `sshd -T` de cette étape portent sur le nom d'utilisateur ; l'évaluation d'`AllowUsers` par adresse source est refaite à l'étape D avec l'adresse réelle de backend-admin. Relevez aussi les valeurs de `strictmodes` et de `permituserenvironment` dans ces sorties : le fichier du tunnel les pose au début de la configuration et remplacerait des valeurs plus faibles posées plus bas.

Résultat attendu et motif de chaque relevé :

- comptes, groupes, identifiants : aucun de ces noms ni de ces identifiants n'existe (sauf `www-data` 33, `docker` éventuel). Si l'un existe : **arrêtez-vous et transmettez au mainteneur** ;
- `/etc/paresia`, `/usr/local/lib/paresia`, `/var/lib/paresia-app` : à relever ; un dossier existant n'est pas un échec, mais les scripts comparent avant d'écraser ; `/var/log/paresia` existe sans doute (journal légal) : il n'est pas touché ;
- unités de l'essai absentes de `list-unit-files` ; les autres unités actives sont relevées pour mémoire ;
- sshd : `Include /etc/ssh/sshd_config.d/*.conf` présent ; pas de `Match` ni d'`AllowGroups` qui exclurait `app` ou `tunnel` ; un `AllowUsers` qui exclurait `app` bloque l'essai, un `AllowUsers` qui exclurait `tunnel` est traité par la sous-étape `AllowUsers` de l'étape `tunnel_sshd` ; un `AllowUsers` est relevé : traité à l'étape D (étape `tunnel_sshd`) ; `AllowTcpForwarding` et `AllowStreamLocalForwarding` globaux sont relevés, le bloc `Match User tunnel` les restreint (à vérifier par `sshd -T -C user=tunnel,…`) ; `UsePAM`, `Port`, `ListenAddress` relevés. Sinon : **arrêtez-vous et transmettez au mainteneur** ;
- écouteurs TCP (`ss -ltnp`) : sur backend-relais, tout écouteur sur 127.0.0.1 ou sur le réseau interne, autre que sshd et strfry, est à **transmettre au mainteneur avant l'étape D** : sans la règle nftables, le compte `tunnel` pourrait s'y connecter pendant l'essai ;
- systemd 257 ou plus, Python 3.11 ou plus, paquets `acl` et `curl` installés ; `python3-cryptography` absent est installé à l'étape C. Sinon : **arrêtez-vous** ;
- la présence de `/run/sudo` et l'absence de `chef` dans `docker` sont les conditions du compte `chef` ; nftables : aucune règle `paresia_relais` encore chargée.

Retour arrière : sans objet (lecture seule).

## Étape B — backend-relais : comptes, code, Castor et Remus

Machine : backend-relais. Intention : installer ce qui répond côté relais. Lancer, sans les recopier, `deploy/backend-relais/installer-backend-relais.sh --sauter produit --sauter fonctions --sauter sudoers --sauter nftables --sauter isolation_remus --session-secours oui` : prérequis, identifiants et comptes, vérification des comptes, code et configuration, copie des unités, démarrage de Castor puis de Remus, contrôles de refus et essai local de Castor. Sans `--activer`. Le script affiche à la fin l'empreinte de la clé d'hôte (`EMPREINTE_HOTE_RELAIS`) qui sert à l'étape D.

Relevé avant : celui de chaque étape du script (outil de sauvegarde, jeu `JEU`). Retour arrière : `--retour-arriere --jeu "$JEU" --confirme` du script.

ATTENTION : Remus est démarré sans le sudoers (étape `sudoers`, sautée) : aucune règle sudo n'est installée, et, les fonctions étant sautées (`--sauter fonctions`), le sudoers généré à partir des fonctions installées reste vide : il n'exécute rien. Castor et Remus ne sont démarrés que par `start`.

Vérification : `sudo /usr/bin/journalctl -u castor.service -n 30 --no-pager` et `sudo /usr/bin/journalctl -u remus.service -n 30 --no-pager`, deux unités `active (running)` ; l'essai local de l'étape `refus_castor` donne les réponses attendues par cette étape.

Ligne attendue (code, `server/castor/__init__.py`) : au démarrage `startup` (l. 181) ; pendant l'essai local `light_green` (l. 106) puis `light_closed` avec `reason` valant `close` (l. 119) pour la session 1.

## Étape C — backend-admin : comptes, code, Pollux et Romulus

Machine : backend-admin. Intention : installer Pollux, `pollux-session` et Romulus. Lancer, sans les recopier, `deploy/backend-admin/installer-backend-admin.sh --sauter www-data --session-secours oui` (1re passe : l'essai manuel n'est pas dans le script : il est remplacé par le client, aucune activation). Le script affiche la clé publique du tunnel et son empreinte, à porter sur backend-relais.

Points propres à l'essai :

- **Prérequis ajouté avant le script : `python3-cryptography`.** Pollux vérifie la signature du défi avec la bibliothèque `cryptography` (`server/commun/sshsig.py`, import l. 78 à 79) ; le script de backend-admin la contrôle désormais à son étape `prerequis` (code 69 si elle manque), mais ne l'installe pas : installez-la avant le script. Sans elle, toute preuve est refusée. Relevé avant, lu sur le terminal :

  ```bash
  { dpkg -s python3-cryptography 2>&1 || true; }
  ```

  ATTENTION : `apt install` modifie la base des paquets et peut installer des dépendances ; lisez la liste proposée avant de confirmer, et ne confirmez pas si elle retire un paquet existant. Aucun service n'est redémarré par cette commande, hors ceux que le paquet imposerait : vérifiez la liste.

  ```bash
  sudo /usr/bin/apt install python3-cryptography
  python3 -c "import cryptography; print(cryptography.__version__)"
  ```

  Résultat attendu : une version s'affiche. Retour arrière (seulement si le relevé avant montre le paquet absent) : ATTENTION, `apt remove` retire le paquet ; `sudo /usr/bin/apt remove python3-cryptography`, en lisant la liste des paquets retirés.

- **Étape `appartenances`** : `--sauter www-data` ; `www-data` n'est pas modifié. À l'étape `refus`, le test HTTP de `www-data` est sauté avec lui et remplacé par le même appel sous `runuser -u www-data -g paresia-http`, qui doit afficher `token_missing` suivi de `403`.
- **Étape `dossier_app` (`authorized_keys`)** : le fichier est sous `/var/lib/paresia-app/.ssh/authorized_keys`, hors des répertoires masqués par `ProtectHome=yes`. `ProtectSystem=strict` le laisse lisible en lecture seule. Le fichier peut être modifié ou remplacé pendant que Pollux tourne ; aucun montage particulier n'est nécessaire.
- **Vérification après l'étape `demarrage`** : le fichier est visible dans l'espace de noms de Pollux (le script la fait : `nsenter -t <pid> -m -- ls -l` attend `root:root 644`).

  ```bash
  sudo /usr/bin/nsenter -t "$(systemctl show -p MainPID --value pollux.service)" -m -- /usr/bin/ls -l /var/lib/paresia-app/.ssh/authorized_keys
  ```

  Résultat attendu : le fichier est listé, `root:root 644`. Sinon : **arrêtez-vous et transmettez au mainteneur**.
- **Étape `demarrage` (`ss -xl`)** : quatre sockets à l'écoute (Pollux, Romulus).

Ligne attendue : journal de Pollux et de Romulus sans erreur (`sudo /usr/bin/journalctl -u pollux.service -n 30 --no-pager`, `sudo /usr/bin/journalctl -u romulus.service -n 30 --no-pager`).

Écarts relevés entre le script et l'essai : (a) le script ne contient pas l'essai manuel sans défi signé, remplacé par E1 à E6 ; (b) il ne pose pas de ligne `authorized_keys` de test, ajoutée ci-dessous ; (c) `python3-cryptography`, désormais contrôlé par le script, reste à installer avant lui (voir ci-dessus).

### Outil de sauvegarde

Les scripts ont copié le code sous `/run/paresia-installation` (copie root) et créé un jeu de sauvegarde (son nom est affiché à la pose). Pour les relevés et restaurations propres à l'essai, définissez la fonction `outil` sur backend-admin (sur backend-relais, remplacez `paresia.conf` par `paresia-relais.conf`) :

```bash
outil() { sudo /usr/bin/env PYTHONPATH=/run/paresia-installation PARESIA_SAUVEGARDE_CONFIG=/run/paresia-installation/server/conf/paresia.conf /usr/bin/python3 -P -m server.sauvegarde "$@"; }
```

### Ligne de test de `authorized_keys` (backend-admin)

Intention : autoriser, pour l'essai seulement, la clé publique de l'agent SSH de votre poste client. Seule la **partie publique** est copiée, jamais la clé privée.

Sur le poste client, choisissez la clé publique de votre agent (`ssh-add -L`), enregistrez la ligne choisie dans un fichier `cle-essai.pub` du dossier courant, et notez son empreinte (`ssh-keygen -lf cle-essai.pub`). Choisissez un nom d'administrateur (lettres, chiffres, `.`, `_`, `@`, `-`) : il est le commentaire de la ligne.

Sur backend-admin, relevé avant dans un jeu distinct (la première sauvegarde d'un chemin dans un jeu est conservée) :

```bash
JEU_ESSAI=$(outil jeu)
JEU_ESSAI=${JEU_ESSAI##*/}
export JEU_ESSAI
outil copier --jeu "$JEU_ESSAI" /var/lib/paresia-app/.ssh/authorized_keys
```

ATTENTION : modification d'un fichier de root, par ajout d'une seule ligne en place.

```bash
(
set -euo pipefail
: "${CLE_PUBLIQUE:?Fixez CLE_PUBLIQUE avant cette étape}"
: "${ADMIN:?Fixez ADMIN avant cette étape}"
if case "$CLE_PUBLIQUE" in 'ssh-ed25519 '*) true ;; *) false ;; esac && case "$ADMIN" in ''|*[!A-Za-z0-9._@-]*) false ;; *) true ;; esac; then
    printf 'restrict,command="/usr/local/bin/pollux-session" %s %s\n' "$CLE_PUBLIQUE" "$ADMIN" | sudo /usr/bin/tee -a /var/lib/paresia-app/.ssh/authorized_keys > /dev/null
else
    echo 'Valeur invalide : rien n a été écrit' >&2
    exit 1
fi
sudo /usr/bin/stat -c '%U:%G %a %n' /var/lib/paresia-app/.ssh/authorized_keys
)
```

Vérification : `root:root 644` ; `/usr/bin/ssh-keygen -lf /var/lib/paresia-app/.ssh/authorized_keys` affiche l'empreinte notée sur le poste client. Retour arrière : étape F.

## Étape D — Le tunnel

Machines : backend-relais et backend-admin. Lancer, dans l'ordre et sans les recopier, la partie « tunnel » des scripts : backend-relais avec les mêmes `--sauter` qu'à l'étape B, `--adresse-admin`, `--cle-publique-tunnel` et `--empreinte-cle-tunnel` (valeurs affichées par la 1re passe de backend-admin) et `--acces-tunnel-sans-nftables oui` (la table `paresia_relais` n'est pas chargée pendant l'essai), puis backend-admin (2e passe, avec le même `--jeu`) avec `--adresse-relais` et `--empreinte-hote-relais`. Les points à lire avec attention :

- étape `tunnel_compte` : le compte `tunnel` sans shell ni mot de passe utilisable est vérifié par la connexion réelle de l'étape `tunnel_unite` ; ligne attendue sur backend-relais, `sudo /usr/bin/journalctl -u ssh -n 30 --no-pager` : `Accepted publickey for tunnel` ; **en cas de refus : arrêtez-vous et transmettez au mainteneur**, avec la sortie de `passwd -S tunnel` ;
- étape `tunnel_unite` : installe `tmpfiles.d/paresia-tunnel.conf` dans `/etc/tmpfiles.d/` et lance `systemd-tmpfiles --create` avant de démarrer le tunnel ;
- étape `tunnel_sockets` : relève les modes des sockets du tunnel (`StreamLocalBindMask`) et les groupes des dossiers avec `stat` et `namei -l`, et les membres des groupes `paresia-romulus` et `paresia-pollux` ; **en cas de refus d'accès de Pollux ou de Romulus : arrêtez-vous : à transmettre au mainteneur**.

ATTENTION : le bloc sshd de backend-relais est rechargé par `systemctl reload ssh` (jamais redémarré), précédé de `sshd -t`, session de secours ouverte et testée.

Ligne attendue : celle de chaque étape du script (relevés affichés avec `--alpha-test`). Retour arrière : `--retour-arriere --jeu <nom> --confirme` du script de la machine.

Après l'étape D, l'accès du compte `tunnel` est ouvert **sans la règle nftables** : voir la limite d'OpenSSH : le compte `tunnel` pourrait ouvrir des connexions TCP sortantes tant que la règle `paresia_relais` n'est pas chargée (paramètre `ACCES_TUNNEL_SANS_NFTABLES` du script de backend-relais). L'étape F le referme. Menez l'étape E sans attendre.

## Étape E — Scénario depuis le poste client

Le client est `tests/banc/client.py` du dépôt (bibliothèque standard, `ssh`, `ssh-keygen`). Il utilise la clé de votre agent SSH (`SSH_AUTH_SOCK`) ; il ne lit, ne copie et ne charge aucune clé privée.

Divergence relevée : `SessionPresence` de l'application ouvre sans défi et ne permet pas d'y insérer la signature ; le client implémente donc l'échange lui-même.

Commande, sur le poste client :

```bash
python3 tests/banc/client.py --hote backend-admin.example.org --compte app --cle-publique ./cle-essai.pub --admin NOM_ADMINISTRATEUR
```

Remplacez l'hôte par l'adresse ou le nom de backend-admin et `NOM_ADMINISTRATEUR` par le nom choisi pour la ligne de test. Le client ouvre `ssh -T -o IdentitiesOnly=yes -o BatchMode=yes -i cle-essai.pub -- app@hôte`, joue l'échange de `docs/protocole.md` § 4.1 (défi, signature par `ssh-keygen -Y sign` avec la clé tenue par l'agent, ouverture) puis envoie un ping toutes les `heartbeat_s`. Si la connexion échoue, relancez avec `--diagnostic` : le client affiche alors la dernière ligne (filtrée) de l'erreur de `ssh`, jamais de contenu de session. Il ne dit rien si tout va bien, hors une ligne de confirmation. Deux commandes se tapent dans son terminal : `jeton` (affiche le jeton, avec un avertissement) et `fermer`. Laissez cette commande tourner pendant E1 à E4.

### E1 — Connexion de présence

Machine : poste client, puis backend-admin. Intention : établir la session SSH et obtenir une session de présence. Lancez la commande ci-dessus.

ATTENTION : l'agent SSH peut demander une confirmation de signature ; elle ne porte que sur le défi.

Vérification, sur backend-admin :

```bash
sudo /usr/bin/journalctl -u ssh -n 30 --no-pager | grep 'for app'
sudo /usr/bin/journalctl -u pollux.service -n 30 --no-pager | grep -E 'challenge_issued|auth_ok|session_opened'
```

Lignes attendues : sshd, `Accepted publickey for app from <adresse du poste client> port … ssh2: ED25519 SHA256:…` ; Pollux, dans cet ordre, `challenge_issued` (`server/pollux/__init__.py` l. 379), `auth_ok` (l. 405), `session_opened` (l. 459) avec `session`, `admin` et `source`. Aucun défi, signature ni jeton dans un journal. Relevé avant : aucun (lecture). Retour arrière : E5 ferme la session.

Si le client répond `Présence refusée : signature_invalid` : lisez `sudo /usr/bin/journalctl -u pollux.service -n 30 --no-pager` ; `auth_failed` avec `reason` valant `keys_file` (l. 361) signifie que Pollux ne lit pas `authorized_keys` : **arrêtez-vous et transmettez au mainteneur**.

### E2 — Jeton remis

Machine : poste client, puis backend-admin. Intention : constater que le jeton est remis sans être exposé. Le client écrit « Session N ouverte ; jeton reçu et contrôlé (64 caractères hexadécimaux) » : la longueur est contrôlée, la valeur n'est pas affichée.

Vérification, sur backend-admin : `sudo /usr/bin/journalctl -u romulus.service -n 30 --no-pager | grep session_opened`.

Ligne attendue : Romulus, `session_opened` avec `session`, `admin` et `source` (`server/romulus/sessions.py` l. 56 et 71), sans jeton. Retour arrière : E5.

### E3 — Preuve du chemin par le tunnel

Machine : poste client (pour lire le jeton), puis backend-admin. Intention : envoyer par Romulus une requête à Remus, à travers le tunnel. Remus a une table vide (les fonctions du greffon strfry ne sont pas posées pour cet essai) : la réponse attendue est l'échec `not_available`, **retenu comme preuve que la requête a traversé Romulus puis le tunnel jusqu'à Remus**.

Dans le terminal du client, tapez `jeton` : le jeton s'affiche sur le terminal (secret de session, détruit à la fermeture). Sur backend-admin, saisissez-le **sans écho ni historique** ; il est passé à `curl` par l'entrée standard (`curl(1)`, `-H, --header <header/@file>` : « Using @- makes curl read the header file from stdin. »).

ATTENTION : le jeton est un secret de session ; ne l'écrivez dans aucun fichier ni aucune commande.

```bash
read -r -s -p 'Jeton : ' JETON; echo
printf 'X-Admin-Token: %s\nOrigin: http://localhost\n' "$JETON" | sudo /usr/sbin/runuser -u www-data -g paresia-http -- /usr/bin/curl -s -w ' %{http_code}\n' --unix-socket /run/paresia-romulus/romulus-http.sock -X POST -d '' -H @- http://localhost/api/admin/relay/state/status
```

Si vous ne menez pas E6, exécutez `unset JETON` dès la fin de E3. (`Origin` doit être égal à `Host` : `server/romulus/http.py` l. 411.) Résultat attendu : un corps contenant `not_available` suivi du statut `501` (`STATUTS`, `http.py` l. 54).

Lignes attendues : Romulus, `action_routed` avec `destination` valant `remus`, `action` valant `relay/state/status`, `result` valant `not_available` (`server/romulus/aiguillage.py` l. 254 ; niveau `warning`) ; backend-relais, `sudo /usr/bin/journalctl -u ssh -n 30 --no-pager` : `Accepted publickey for tunnel`. Si `PermissionError` ou une erreur de connexion s'affiche, la socket HTTP n'est pas jointe : relevez `stat` de `/run/paresia-romulus/romulus-http.sock` et transmettez au mainteneur. Retour arrière : E5.

### E4 — Pings de Pollux vers Castor, feu vert

Machine : backend-admin, puis backend-relais. Intention : constater que l'aiguillage de Romulus a fait pinguer Castor par Pollux après l'envoi à Remus (`_pinguer`, `apres_envoi`, `aiguillage.py` l. 144 et 160).

Sur backend-relais, **dans les 30 secondes** qui suivent E3 (le feu reste vert `heartbeat_s` + `margin_s` après chaque ping), remplacez `N` par le numéro de session affiché par le client :

La sonde prend l'identité `chef` et le groupe de lecture `paresia-castor-etat`
accordé à Remus par `SupplementaryGroups=` ; elle ne modifie pas les groupes du
compte `chef`. Source installée, runuser(1) : `-g, --group` : « The primary group
to be used. This option is allowed for the root user only. » ; `-G, --supp-group` :
« Specify a supplementary group. This option is available to the root user only. »
Le préfixe `sudo` permet de fixer ces groupes.

```bash
sonde() {
    sudo /usr/sbin/runuser -u chef -g chef -G paresia-castor-etat -- /usr/bin/python3 -c "import json,secrets,socket,sys; s=socket.socket(socket.AF_UNIX); s.settimeout(3); s.connect('/run/paresia-castor/castor-state.sock'); s.sendall(json.dumps({'proto':'jumeaux/1','id':secrets.token_hex(8),'session':int(sys.argv[1]),'action':'castor/light/state','params':{}}).encode()+b'\n'); print(s.makefile('rb').readline().decode().strip())" "$1" 2>&1 | tail -n 1
}
sonde N
sudo /usr/bin/journalctl -u castor.service -n 30 --no-pager | grep light_
```

Lignes attendues : Castor, `light_green` pour le numéro de session (`server/castor/__init__.py` l. 106) ; la sonde répond `"state":"green"` (l. 130). Aucun `peer_unavailable` dans `sudo /usr/bin/journalctl -u pollux.service` ni `sudo /usr/bin/journalctl -u romulus.service` (`pollux/__init__.py` l. 143, 208, 211). Notez la réponse brute. Retour arrière : E5.

### E5 — Déconnexion, feu rouge

Machine : poste client, puis backend-relais. Intention : fermer la session et constater le feu rouge. Dans le terminal du client, tapez `fermer` : le client envoie `presence/session/close`, puis ferme l'entrée.

Vérification : sur backend-admin, `sudo /usr/bin/journalctl -u pollux.service -n 30 --no-pager | grep session_closed` ; sur backend-relais, `sonde N` tout de suite, puis de nouveau après 12 secondes.

Lignes attendues : Pollux, `session_closed` avec `reason` valant `close` (`pollux/__init__.py` l. 231, motif de la l. 530) ; Castor, `light_closed` avec `reason` valant `close` (l. 119). La sonde répond d'abord l'erreur `session_closed` (pendant `closed_s` = 10 s), puis `"state":"red"` (l. 132). Notez les réponses brutes exactes. Retour arrière : sans objet (la session est détruite).

Variante par silence, si vous voulez un second essai : ouvrez une session, envoyez un `relay/state/status` (E3), puis ne faites plus rien ; `light_expired` (l. 82) apparaît au plus `heartbeat_s` + `margin_s` + `verification_s` après `light_green`, la session de présence restant ouverte (`timeout_s` = 90 s).

### E6 — Refus de Romulus sur jeton détruit

Machine : backend-admin. Intention : constater que le jeton est inutilisable. Rejouez la commande de E3 avec le même jeton (la variable `JETON` est encore dans votre shell).

```bash
printf 'X-Admin-Token: %s\nOrigin: http://localhost\n' "$JETON" | sudo /usr/sbin/runuser -u www-data -g paresia-http -- /usr/bin/curl -s -w ' %{http_code}\n' --unix-socket /run/paresia-romulus/romulus-http.sock -X POST -d '' -H @- http://localhost/api/admin/relay/state/status
unset JETON
sudo /usr/bin/journalctl -u romulus.service -n 30 --no-pager | grep session_closed
```

Résultat attendu : un corps contenant `token_unknown` suivi de `403` (`http.py` l. 45 et 409 ; commentaire de `[romulus.http]` dans `server/conf/paresia.conf`). Ligne attendue : Romulus, `session_closed` (session détruite, `sessions.py` l. 82). Aucune ligne `action_routed` nouvelle : la requête n'atteint pas Remus. Retour arrière : sans objet.

## Étape F — Fin d'essai

Machines : backend-admin, backend-relais, poste client. Intention : ne rien laisser d'ouvert. Aucune unité n'est activée au démarrage ; `strfry`, Docker et lighttpd ne sont ni arrêtés ni redémarrés.

**F1. Arrêt des unités, dans l'ordre inverse du démarrage.**

ATTENTION : l'arrêt ferme toutes les sessions de présence et remet les feux de Castor au rouge.

```bash
sudo /usr/bin/systemctl stop paresia-tunnel.service
sudo /usr/bin/systemctl stop pollux.service romulus.service
```

Puis, sur backend-relais : `sudo /usr/bin/systemctl stop remus.service castor.service`. Vérification : `systemctl is-active paresia-tunnel.service pollux.service romulus.service` répond `inactive`; de même `remus` et `castor` sur backend-relais. Ligne attendue : `shutdown` de Castor (`castor/__init__.py` l. 196).

**F2. Retrait de la ligne de test d'`authorized_keys` de `app`** (backend-admin, unités arrêtées).

ATTENTION : restauration de `authorized_keys` depuis le jeu `JEU_ESSAI` (écrasement) ; elle s'arrête sans rien modifier si la sauvegarde manque (code 5).

```bash
outil restaurer --jeu "$JEU_ESSAI" /var/lib/paresia-app/.ssh/authorized_keys
sudo /usr/bin/stat -c '%U:%G %a %n' /var/lib/paresia-app/.ssh/authorized_keys
```

Vérification : `wc -l /var/lib/paresia-app/.ssh/authorized_keys` vaut `0`.

**F3. Désactivation de l'accès du compte `tunnel`** (backend-relais). Raison : la règle nftables `paresia_relais` n'est pas chargée, et OpenSSH ne peut pas limiter une redirection de socket Unix à un chemin (`AllowStreamLocalForwarding local` partage l'autorisation des redirections locales de TCP ; `PermitOpen` n'accepte pas de chemin de socket ; cahier des charges, section du tunnel SSH). Le compte `tunnel` pourrait donc ouvrir des connexions TCP sortantes. **L'accès reste désactivé tant que la règle `paresia_relais` n'est pas chargée** ; l'exposition a duré le temps de l'essai (de l'étape D à la présente étape).

Relevé avant :

```bash
REPERTOIRE_TUNNEL=$(getent passwd tunnel | cut -d: -f6)
JEU_FIN=$(outil jeu); JEU_FIN=${JEU_FIN##*/}; export JEU_FIN
outil copier --jeu "$JEU_FIN" "$REPERTOIRE_TUNNEL/.ssh/authorized_keys"
```

ATTENTION : la ligne de clé est mise en commentaire, le compte ne peut plus se connecter.

```bash
sudo /usr/bin/sed -i 's/^restrict,/#restrict,/' "$REPERTOIRE_TUNNEL/.ssh/authorized_keys"
sudo /usr/bin/stat -c '%U:%G %a %n' "$REPERTOIRE_TUNNEL/.ssh/authorized_keys"
grep -c '^#restrict,' "$REPERTOIRE_TUNNEL/.ssh/authorized_keys"
sudo /usr/sbin/sshd -T -C user=tunnel,host=backend-admin.example.org,addr=192.0.2.50 | grep -i -E '^(allowtcpforwarding|allowstreamlocalforwarding|permitlisten) '
```

Vérification : `root:root 644` ; le décompte vaut `1` ; `sshd -T` est inchangé (`local`, `local`, `none`) : ce contrôle ne prouve pas la désactivation, qui est prouvée par le refus ci-dessous. Pour constater le refus, démarrez le tunnel sur backend-admin (`sudo /usr/bin/systemctl start paresia-tunnel.service`) ; `pollux` et `romulus` sont déjà arrêtés (F1), le coupe-circuit de Pollux vers son jumeau n'a donc aucun effet sur une session ; le tunnel ayant `Restart=always` avec `RestartSec=5`, les échecs se répètent toutes les 5 secondes dans le journal de sshd : la connexion est refusée, `sudo /usr/bin/journalctl -u ssh -n 30 --no-pager` sur backend-relais ne montre aucune nouvelle ligne `Accepted publickey for tunnel` mais un refus (ligne à relever et à transmettre au mainteneur) ; arrêtez ensuite le tunnel (`sudo /usr/bin/systemctl stop paresia-tunnel.service`) et vérifiez `systemctl is-active paresia-tunnel.service` (`inactive`).

Commande inverse (réactiver l'accès, seulement quand la règle `paresia_relais` est chargée) : `sudo /usr/bin/sed -i 's/^#restrict,/restrict,/' "$REPERTOIRE_TUNNEL/.ssh/authorized_keys"`, ou restauration depuis le jeu `JEU_FIN` par l'outil.

**F4. Poste client.**

ATTENTION : `rm` supprime définitivement le fichier de clé publique d'essai (la clé privée reste dans l'agent et n'est pas touchée).

```bash
rm ./cle-essai.pub
```

**F5. État laissé.**

| Ce qui reste | Machine | État |
| --- | --- | --- |
| Comptes et groupes, code sous `/usr/local/lib/paresia`, `pollux-session`, configuration sous `/etc/paresia` | les deux | installés |
| Unités `pollux`, `romulus`, `paresia-tunnel`, `castor`, `remus` | les deux | installées, arrêtées, non activées |
| Bloc sshd `50-paresia-app.conf` | backend-admin | en place |
| Bloc sshd `50-paresia-tunnel.conf` | backend-relais | en place |
| `authorized_keys` de `app` | backend-admin | vide |
| `authorized_keys` de `tunnel` | backend-relais | ligne en commentaire |
| `/etc/ssh/sshd_config.d/40-paresia-tunnel-allowusers.conf` (seulement s'il a été créé par l'étape `tunnel_sshd`) | backend-relais | en place ; retrait : retour arrière de cette sous-étape |
| Clé du tunnel, `known_hosts`, `ssh_config` | backend-admin | en place |
| Jeux de sauvegarde `JEU`, `JEU_TUNNEL`, `JEU_ESSAI`, `JEU_FIN` | les deux | conservés (rotation de l'outil) |

Retrait complet : `--retour-arriere --jeu <nom> --confirme --session-secours oui` de chaque script (le jeu est celui affiché à la pose), sur backend-admin puis sur backend-relais, après l'arrêt des unités ci-dessus.
