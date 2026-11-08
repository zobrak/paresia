# Installation du tunnel SSH entre backend-admin et backend-relais

SPDX-License-Identifier: AGPL-3.0-or-later

Paramètres : fixez les variables d'environnement avant les étapes concernées.

| Variable | Rôle | Défaut |
| --- | --- | --- |
| `DEPOT` | Copie propre du dépôt préparée par la procédure de la machine | obligatoire, sans défaut |
| `ADRESSE_ADMIN` | Adresse IP source de backend-admin, exemple 192.0.2.50 | obligatoire, sans défaut |
| `ADRESSE_RELAIS` | Adresse IP de backend-relais, exemple 192.0.2.200 | obligatoire, sans défaut |
| `CLE_PUBLIQUE_TUNNEL` | Clé publique du tunnel, forme ssh-ed25519 AAAA… | obligatoire, sans défaut |

Avant toute étape, sur chaque machine concernée, contrôlez les paramètres obligatoires :

```bash
(
set -euo pipefail
: "${DEPOT:?Fixez DEPOT avant de commencer}"
: "${ADRESSE_ADMIN:?Fixez ADRESSE_ADMIN avant de commencer}"
: "${ADRESSE_RELAIS:?Fixez ADRESSE_RELAIS avant de commencer}"
: "${CLE_PUBLIQUE_TUNNEL:?Fixez CLE_PUBLIQUE_TUNNEL avant de commencer}"
)
```

Version du document : 0.1.19 · 2026-11-08 · public : administrateur. Historique : `CHANGELOG.md`.

À exécuter **par vous seul, une étape à la fois**, sur la machine indiquée en tête de chaque étape. Ne passez à l'étape suivante qu'après avoir lu le résultat de la précédente. Chaque commande qui modifie le système est précédée d'une ligne **ATTENTION**. Une deuxième session reste ouverte sur chaque machine.

**Aucun shell root n'est requis** (ni `sudo -i`, ni `su`, ni `sudo sh -c`) : chaque commande privilégiée porte son propre `sudo` et le chemin absolu de l'exécutable. Un administrateur déjà root, sans `sudo` (cas de backend-admin), lance les mêmes commandes sans le préfixe `sudo`. Les redirections vers un fichier privilégié passent par `sudo /usr/bin/tee`. Les variables `DEPOT`, `JEU_TUNNEL`, `REPERTOIRE_TUNNEL`, `ADRESSE_ADMIN`, `ADRESSE_RELAIS` sont celles de votre shell ordinaire. La fonction `outil` (lanceur de l'outil de sauvegarde) est définie par l'étape 1 de la procédure de la machine. Les blocs sont écrits pour **bash**. Toute mention de `journalctl` s'entend comme `sudo /usr/bin/journalctl -u … -n 30 --no-pager`.

**Commandes lancées par `sudo` : liste descriptive, pas un sudoers à recopier.** Elle décrit ce que ce document lance, sur les deux machines. La plupart des entrées valent root si on les autorise sans arguments figés : `env`, `python3` et `tee` (écriture ou exécution arbitraire), `install`, `sed -i`, `chown`, `cp`, `mv`, `tar`, `find -exec`, `runuser` (`-u root` passerait), `nsenter` (pid libre), `apt`, `systemctl` sans unité, `visudo`, `systemd-run`. Pour confronter cette liste à un sudoers, figez un par un l'exécutable, le compte cible et les arguments exacts : les unités pour `systemctl`, le seul compte visé pour `runuser`, les chemins pour `install`, `tee`, `sed`, `chown`, `cp`, `mv`, le pid pour `nsenter`, `--no-pager` et l'unité pour `journalctl`, les arguments de `sshd -T -C`. `env … python3 -P -m server.sauvegarde` et `runuser … python3 -c` **ne peuvent pas être restreintes** (l'argument est du code ou un chemin variable) : elles sont propres à cet essai.

- fichiers : `/usr/bin/install`, `/usr/bin/tee` (`authorized_keys` de `tunnel`, fichier `sshd_config.d/40-…`, fichiers sous `/run/paresia-installation`), `/usr/bin/sed -i` (adresse de `10-relais.conf`), `/usr/bin/chown`, `/usr/bin/chmod`, `/usr/bin/rm`, `/usr/bin/test`, `/usr/bin/diff`, `/usr/bin/stat`, `/usr/bin/ls`, `/usr/bin/namei -l`, `/usr/bin/systemd-tmpfiles --create /etc/tmpfiles.d/paresia-tunnel.conf` ;
- comptes et clés : `/usr/bin/passwd -S tunnel`, `/usr/bin/ssh-keygen` (génération et `-lf`), `/usr/bin/getent group paresia-romulus paresia-pollux` ;
- sshd et services : `/usr/sbin/sshd` (`-t`, `-T -C user=…`), `/usr/bin/systemctl` (`reload ssh`, `daemon-reload`, `start`, `stop`, `status` pour `paresia-tunnel`), `/usr/bin/systemd-analyze verify`, `/usr/bin/journalctl -u <unité> -n 30 --no-pager` ;
- essais : `/usr/sbin/runuser -u paresia-romulus|paresia-pollux|nobody|… -- /usr/bin/python3 -c …`.

L'outil de sauvegarde (`outil`, fonction définie par l'étape 1 de la procédure de la machine) lance `sudo /usr/bin/env PYTHONPATH=… /usr/bin/python3 -P -m server.sauvegarde` : forme non restreignable, déjà décrite dans cette procédure.

Livrables du dépôt :

| Fichier | Machine | Destination |
| --- | --- | --- |
| `backend-relais/etc/ssh/sshd_config.d/50-paresia-tunnel.conf` | backend-relais | `/etc/ssh/sshd_config.d/50-paresia-tunnel.conf` |
| `backend-admin/etc/paresia/tunnel/ssh_config` | backend-admin | `/etc/paresia/tunnel/ssh_config` |
| `backend-admin/etc/paresia/tunnel/ssh_config.d/10-relais.conf` | backend-admin | `/etc/paresia/tunnel/ssh_config.d/10-relais.conf` |
| `backend-admin/etc/systemd/system/paresia-tunnel.service` | backend-admin | `/etc/systemd/system/paresia-tunnel.service` |
| `backend-admin/etc/tmpfiles.d/paresia-tunnel.conf` | backend-admin | `/etc/tmpfiles.d/paresia-tunnel.conf` |

Limites connues, à lire avant de commencer :

- Arrêter ou redémarrer `paresia-tunnel.service` coupe Pollux et Romulus de leurs jumeaux du relais.
- OpenSSH ne sait pas limiter une redirection de socket Unix à un chemin : `AllowStreamLocalForwarding local` partage l'autorisation des redirections locales de TCP, et `PermitOpen` n'accepte pas de chemin de socket (cahier des charges, section du tunnel SSH). Le compte `tunnel` pourrait donc ouvrir des connexions TCP sortantes depuis backend-relais ; seule la règle nftables `paresia_relais` (procédure du relais, étape 7) ferme cette limite. **Tant qu'elle n'est pas chargée, l'accès du compte `tunnel` ne doit être ouvert que le temps d'un essai.**
- `StrictModes yes` et `PermitUserEnvironment no` sont posés **hors** du bloc `Match`, car `sshd_config(5)` ne les admet pas dans un `Match` ; ce sont les valeurs par défaut d'OpenSSH, appliquées à tous les comptes de backend-relais.
- Suite, hors essai : la règle `paresia_relais` devra s'intégrer au pare-feu en place (firewalld, tables de Docker gérées par iptables-nft) ; rien n'est prescrit ici.
- Aucune étape n'arrête, ne redémarre ni ne recharge un service existant autre que `ssh` (`reload` seulement, jamais `restart`).

## Étape 1 — Relevés avant (lecture seule)

Machine : backend-admin, puis backend-relais.

Intention : consigner l'état avant toute modification.

Sur backend-relais :

```bash
JEU_TUNNEL=$(outil jeu) || echo 'Échec du jeu de sauvegarde : ne pas poursuivre' >&2
JEU_TUNNEL=${JEU_TUNNEL##*/}
export JEU_TUNNEL
REPERTOIRE_TUNNEL=$(getent passwd tunnel | cut -d: -f6)
export REPERTOIRE_TUNNEL
(
set -euo pipefail
case "$REPERTOIRE_TUNNEL" in /*) ;; *) exit 1 ;; esac
REPERTOIRE_TUNNEL=$(realpath -m -- "${REPERTOIRE_TUNNEL:?}")
case "$REPERTOIRE_TUNNEL" in /home|/home/*)
    echo 'Répertoire sous /home refusé ; aucun compte existant ne sera déplacé' >&2
    exit 1 ;;
esac
echo "Jeu : $JEU_TUNNEL ; répertoire personnel de tunnel : $REPERTOIRE_TUNNEL"
sudo /usr/bin/stat -c '%U:%G %a %n' "$REPERTOIRE_TUNNEL" "$REPERTOIRE_TUNNEL/.ssh"
sudo /usr/bin/ls -A "$REPERTOIRE_TUNNEL/.ssh"
sudo /usr/sbin/sshd -T -C user=tunnel,host=backend-admin.example.org,addr=192.0.2.50 | outil releve sshd-tunnel-avant --jeu "$JEU_TUNNEL"
sudo /usr/bin/passwd -S tunnel
)
```

Résultat attendu : `tunnel` existe (étape 3 de la procédure du relais) ; le répertoire personnel et `.ssh` sont `root:root 755` ; `.ssh` est vide. Sinon, **arrêtez-vous et transmettez au mainteneur**. La dernière ligne (`passwd -S`) est relevée pour l'étape 3.

Sur backend-admin :

```bash
JEU_TUNNEL=$(outil jeu) || echo 'Échec du jeu de sauvegarde : ne pas poursuivre' >&2
JEU_TUNNEL=${JEU_TUNNEL##*/}
export JEU_TUNNEL
sudo /usr/bin/stat -c '%U:%G %a %n' /etc/paresia /etc/paresia/tunnel 2>&1
getent passwd paresia-tunnel
```

Résultat attendu : `/etc/paresia` est `root:root 755` ; `/etc/paresia/tunnel` n'existe pas. Sinon, **arrêtez-vous et transmettez au mainteneur**.

Retour arrière : sans objet (seul un jeu de sauvegarde est créé ; il est conservé).

## Étape 2 — Clé du tunnel (backend-admin)

Machine : backend-admin.

Intention : générer sur place la paire de clés du tunnel. La clé privée reste sur backend-admin, propriétaire `paresia-tunnel`, mode 0400, sans phrase secrète (le service redémarre seul). Seule la partie publique est portée sur backend-relais. Aucune clé n'est dans le dépôt.

ATTENTION : `ssh-keygen` écrit une clé privée ; elle ne doit être ni copiée, ni affichée, ni envoyée.

```bash
if sudo /usr/bin/test ! -e /etc/paresia/tunnel/id_ed25519; then
    echo 'Aucune clé existante : la génération peut suivre'
    outil copier --si-absent --jeu "$JEU_TUNNEL" /etc/paresia/tunnel/id_ed25519 /etc/paresia/tunnel/id_ed25519.pub
    sudo /usr/bin/install -d -o root -g root -m 0755 /etc/paresia/tunnel /etc/paresia/tunnel/ssh_config.d
    sudo /usr/bin/ssh-keygen -q -t ed25519 -N '' -C paresia-tunnel -f /etc/paresia/tunnel/id_ed25519
    sudo /usr/bin/chown paresia-tunnel:paresia-tunnel /etc/paresia/tunnel/id_ed25519
    sudo /usr/bin/chmod 0400 /etc/paresia/tunnel/id_ed25519
    sudo /usr/bin/chown root:root /etc/paresia/tunnel/id_ed25519.pub
    sudo /usr/bin/chmod 0644 /etc/paresia/tunnel/id_ed25519.pub
else
    echo 'Une clé existe déjà : ne pas poursuivre' >&2
fi
```

Résultat attendu :

```bash
sudo /usr/bin/stat -c '%U:%G %a %n' /etc/paresia/tunnel /etc/paresia/tunnel/id_ed25519 /etc/paresia/tunnel/id_ed25519.pub
sudo /usr/bin/ssh-keygen -lf /etc/paresia/tunnel/id_ed25519.pub
```

`root:root 755` pour le dossier, `paresia-tunnel:paresia-tunnel 400` pour la clé privée, `root:root 644` pour la clé publique. Notez l'empreinte affichée (ligne `SHA256:…`) : elle sert à l'étape 3.

Retour arrière : l'outil retire les deux fichiers que l'étape a créés (marque d'absence).

ATTENTION : la restauration supprime la clé privée du tunnel ; elle s'arrête sans rien modifier si la marque d'absence est introuvable (code 5).

```bash
outil restaurer --jeu "$JEU_TUNNEL" /etc/paresia/tunnel/id_ed25519
outil restaurer --jeu "$JEU_TUNNEL" /etc/paresia/tunnel/id_ed25519.pub
```

## Étape 3 — Compte `tunnel` : clé publique autorisée (backend-relais)

Machine : backend-relais.

Intention : autoriser la clé publique du tunnel pour le compte `tunnel`, avec les restrictions de `sshd(8)` (`AUTHORIZED_KEYS FILE FORMAT`) :

- `restrict` : « Enable all restrictions, i.e. disable port, agent and X11 forwarding, as well as disabling PTY allocation and execution of ~/.ssh/rc. » ;
- `port-forwarding` : « Enable port forwarding previously disabled by the restrict option. » ;
- `from="…"` : « in addition to public key authentication, either the canonical name of the remote host or its IP address must be present in the comma-separated list of patterns » ;
- `command="/bin/false"` : « Specifies that the command is executed whenever this key is used for authentication. The command supplied by the user (if any) is ignored. » (le tunnel n'exécute aucune commande ; `ssh -N` n'en demande pas).

Le répertoire personnel et `.ssh` restent `root:root 755` : `tunnel` ne peut rien y modifier ; `authorized_keys` est lu par sshd sous root. L'emplacement effectif de `authorized_keys` est celui de `AuthorizedKeysFile` : relevez-le d'abord.

```bash
sudo /usr/sbin/sshd -T -C user=tunnel,host=backend-admin.example.org,addr=192.0.2.50 | grep -i -E '^(authorizedkeysfile|allowusers|allowgroups|usepam|strictmodes) '
```

Résultat attendu : `authorizedkeysfile .ssh/authorized_keys .ssh/authorized_keys2` (valeur par défaut) ; pas d'`allowgroups` qui exclurait `tunnel`. Une ligne `allowusers` qui n'inclut pas `tunnel` n'est pas un échec : elle est traitée à l'étape 4 (« Si `AllowUsers` existe déjà »). Toute autre exclusion : **arrêtez-vous et transmettez au mainteneur**.

Fixez ensuite, sur backend-relais, `CLE_PUBLIQUE_TUNNEL` à la clé publique affichée par `cat /etc/paresia/tunnel/id_ed25519.pub` sur backend-admin (copie manuelle de la seule partie publique), puis comparez l'empreinte avec celle notée à l'étape 2 : **les deux empreintes doivent être identiques, lues sur chaque machine** (second canal). Remplacez l'adresse d'exemple par celle de backend-admin vue par backend-relais.

ATTENTION : `printf >` crée `authorized_keys` ; l'outil en consigne l'absence avant (retour arrière possible).

```bash
(
set -euo pipefail
: "${ADRESSE_ADMIN:?Fixez ADRESSE_ADMIN avant cette étape}"
: "${CLE_PUBLIQUE_TUNNEL:?Fixez CLE_PUBLIQUE_TUNNEL avant cette étape}"
if case "$ADRESSE_ADMIN" in ''|*[!0-9A-Fa-f.:]*) false ;; *) true ;; esac && case "$CLE_PUBLIQUE_TUNNEL" in 'ssh-ed25519 '*) true ;; *) false ;; esac; then
    printf '%s\n' "$CLE_PUBLIQUE_TUNNEL" | ssh-keygen -lf -
    outil copier --si-absent --jeu "$JEU_TUNNEL" "$REPERTOIRE_TUNNEL/.ssh/authorized_keys" \
      && printf 'restrict,port-forwarding,from="%s",command="/bin/false" %s\n' "$ADRESSE_ADMIN" "$CLE_PUBLIQUE_TUNNEL" | sudo /usr/bin/tee "$REPERTOIRE_TUNNEL/.ssh/authorized_keys" > /dev/null \
      && sudo /usr/bin/chown root:root "$REPERTOIRE_TUNNEL/.ssh/authorized_keys" \
      && sudo /usr/bin/chmod 0644 "$REPERTOIRE_TUNNEL/.ssh/authorized_keys"
else
    echo 'Valeur invalide : rien n a été écrit' >&2
    exit 1
fi
)
```

Résultat attendu : l'empreinte affichée est celle de l'étape 2 ; `stat -c '%U:%G %a %n' "$REPERTOIRE_TUNNEL/.ssh/authorized_keys"` donne `root:root 644`. Si les empreintes diffèrent : **arrêtez-vous**, retirez le fichier (retour arrière ci-dessous) et transmettez au mainteneur.

Retour arrière : l'outil retire le fichier créé par l'étape.

ATTENTION : la restauration supprime `authorized_keys` du compte `tunnel` ; elle s'arrête sans rien modifier si la marque d'absence manque (code 5).

```bash
outil restaurer --jeu "$JEU_TUNNEL" "$REPERTOIRE_TUNNEL/.ssh/authorized_keys"
```

## Étape 4 — Bloc sshd du compte `tunnel` (backend-relais)

Machine : backend-relais.

Intention : installer `50-paresia-tunnel.conf` : `StrictModes yes` et `PermitUserEnvironment no` (hors bloc), puis `Match User tunnel` en dernier : `AllowTcpForwarding local`, `AllowStreamLocalForwarding local`, `PermitListen none`, `PermitTTY no`, `X11Forwarding no`, `AllowAgentForwarding no`, `PasswordAuthentication no`, `AuthenticationMethods publickey`.

Extraits de `sshd_config(5)` :

- `AllowStreamLocalForwarding` : « Specifies whether StreamLocal (Unix-domain socket) forwarding is permitted. The available options are yes (the default) or all to allow StreamLocal forwarding, no to prevent all StreamLocal forwarding, local to allow local (from the perspective of ssh(1)) forwarding only or remote to allow remote forwarding only. » ;
- `AllowTcpForwarding` : même forme (« local to allow local (from the perspective of ssh(1)) forwarding only ») ;
- `PermitListen` : « An argument of none can be used to prohibit all listen requests. »

Avant tout : sshd doit inclure `sshd_config.d`.

```bash
grep -n -i '^[[:space:]]*Include' /etc/ssh/sshd_config
```

Résultat attendu : `Include /etc/ssh/sshd_config.d/*.conf`. Sinon, **arrêtez-vous et transmettez au mainteneur**. Un `Match` ou un `AllowGroups` antérieur qui exclurait `tunnel` bloque l'essai : même consigne. Un `AllowUsers` qui exclurait `tunnel` est traité par la sous-étape ci-dessous.

ATTENTION : `install` écrase un éventuel fichier du même nom ; l'outil le sauvegarde d'abord, ou consigne son absence. `systemctl reload ssh` recharge sshd : une configuration invalide refuse les nouvelles connexions. Ne rechargez qu'avec une session de secours ouverte **et testée** (nouvelle connexion de test avant de fermer quoi que ce soit). Le rechargement ne coupe pas les sessions existantes. Jamais `restart`.

Relevé avant : la configuration effective complète d'un compte ordinaire (`nobody`), sans le bloc du tunnel.

```bash
sudo /usr/sbin/sshd -T -C user=nobody,host=backend-admin.example.org,addr=192.0.2.50 | sudo /usr/bin/tee /run/paresia-installation/ordinaire-avant.txt > /dev/null
```

```bash
outil copier --si-absent --jeu "$JEU_TUNNEL" /etc/ssh/sshd_config.d/50-paresia-tunnel.conf
sudo /usr/bin/install -m 0644 -o root -g root "$DEPOT/deploy/backend-relais/etc/ssh/sshd_config.d/50-paresia-tunnel.conf" /etc/ssh/sshd_config.d/50-paresia-tunnel.conf
sudo /usr/sbin/sshd -t
sudo /usr/sbin/sshd -T -C user=tunnel,host=backend-admin.example.org,addr=192.0.2.50 | grep -i -E '^(allowtcpforwarding|allowstreamlocalforwarding|permitlisten|permittty|x11forwarding|allowagentforwarding|passwordauthentication|authenticationmethods|strictmodes|permituserenvironment) '
sudo /usr/sbin/sshd -T -C user=nobody,host=backend-admin.example.org,addr=192.0.2.50 | sudo /usr/bin/tee /run/paresia-installation/ordinaire-apres.txt > /dev/null
sudo /usr/bin/diff /run/paresia-installation/ordinaire-avant.txt /run/paresia-installation/ordinaire-apres.txt
```

Résultat attendu : `sshd -t` ne dit rien. Pour `tunnel` : `allowtcpforwarding local`, `allowstreamlocalforwarding local`, `permitlisten none`, `permittty no`, `x11forwarding no`, `allowagentforwarding no`, `passwordauthentication no`, `authenticationmethods publickey`, `strictmodes yes`, `permituserenvironment no`. Pour le compte ordinaire, `diff` ne doit montrer **aucune différence**, sauf éventuellement `strictmodes` et `permituserenvironment` (posés par ce fichier, lu avant le fichier principal, ils remplacent des valeurs plus faibles posées plus bas : relevez-les). Toute autre différence signifierait que le bloc `Match` déborde sur d'autres comptes. Si l'une des valeurs diffère : **arrêtez-vous et transmettez au mainteneur**.

### Si `AllowUsers` existe déjà (backend-relais)

`sshd_config(5)`, `AllowUsers` : « If specified, login is allowed only for user names that match one of the patterns. […] If the pattern takes the form USER@HOST then USER and HOST are separately checked » ; « This keyword may appear multiple times in sshd_config with each instance appending to the list. » Les directives s'additionnent donc, et un fichier de `sshd_config.d` (lu au début, « options set there will override those in /etc/ssh/sshd_config ») peut ajouter une entrée sans modifier la ligne existante.

Relevé : `sudo /usr/sbin/sshd -T -C user=tunnel,host=backend-admin.example.org,addr=192.0.2.50 | grep -i '^allowusers '`.

- Aucune ligne `allowusers` : cette sous-étape est **sans objet**. N'ajoutez surtout pas de `AllowUsers` : il restreindrait tous les autres comptes au seul `tunnel`.
- Une ligne `allowusers` : sans ajout, `tunnel` est refusé. Le fichier livré ne contient pas d'`AllowUsers` (il ne doit pas en créer là où il n'y en a pas, ni porter d'adresse). Créez un fichier complémentaire, hors dépôt, qui ajoute `tunnel@<adresse de backend-admin>` sans rien retirer.

ATTENTION : une erreur ici refuse les nouvelles connexions, y compris les vôtres. Gardez la session de secours ouverte et, avant de la fermer, testez une nouvelle connexion de votre compte d'administration. Le relevé avant est dans `JEU_TUNNEL`.

```bash
(
set -euo pipefail
if case "$ADRESSE_ADMIN" in ''|*[!0-9A-Fa-f.:]*) false ;; *) true ;; esac; then
    outil copier --si-absent --jeu "$JEU_TUNNEL" /etc/ssh/sshd_config.d/40-paresia-tunnel-allowusers.conf \
      && printf 'AllowUsers tunnel@%s\n' "$ADRESSE_ADMIN" | sudo /usr/bin/tee /etc/ssh/sshd_config.d/40-paresia-tunnel-allowusers.conf > /dev/null \
      && sudo /usr/bin/chmod 0644 /etc/ssh/sshd_config.d/40-paresia-tunnel-allowusers.conf \
      && sudo /usr/sbin/sshd -t \
      && sudo /usr/sbin/sshd -T -C user=tunnel,host=backend-admin.example.org,addr=192.0.2.50 | grep -i '^allowusers '
else
    echo 'Adresse invalide : rien n a été écrit' >&2
    exit 1
fi
)
```

Résultat attendu : la ligne `allowusers` montre les entrées existantes **et** `tunnel@…`. Sinon, **arrêtez-vous et transmettez au mainteneur**. Retour arrière (retrait du fichier par l'outil, marque d'absence).

ATTENTION : la restauration retire le fichier, puis sshd est rechargé : session de secours ouverte, et nouvelle connexion de l'administrateur testée avant de fermer quoi que ce soit.

```bash
outil restaurer --jeu "$JEU_TUNNEL" /etc/ssh/sshd_config.d/40-paresia-tunnel-allowusers.conf
sudo /usr/sbin/sshd -t
sudo /usr/bin/systemctl reload ssh
```

Prise en compte :

```bash
sudo /usr/sbin/sshd -t && sudo /usr/bin/systemctl reload ssh
```

Résultat attendu : une nouvelle connexion de test vers backend-relais réussit (session de secours conservée). Retour arrière : l'outil rétablit le fichier précédent ou retire celui de l'étape.

ATTENTION : la restauration écrase ou retire le fichier ; `sshd -t` d'abord, puis `reload`, session de secours ouverte.

```bash
outil restaurer --jeu "$JEU_TUNNEL" /etc/ssh/sshd_config.d/50-paresia-tunnel.conf
sudo /usr/sbin/sshd -t
sudo /usr/bin/systemctl reload ssh
```

## Étape 5 — Compte `tunnel` sans shell ni mot de passe : points à vérifier (backend-relais)

Machine : backend-relais.

Intention : le compte `tunnel` a le shell `/usr/sbin/nologin`. Les pages de manuel établissent ceci, et laissent un point ouvert que l'étape 8 tranche par un essai réel.

- `ssh(1)`, `-N` : « Do not execute a remote command. This is useful for just forwarding ports. » : le tunnel ne demande ni shell ni commande ; la commande forcée `/bin/false` n'est donc pas exécutée.
- `sshd(8)` : « Regardless of the authentication type, the account is checked to ensure that it is accessible. An account is not accessible if it is locked […]. The definition of a locked account is system dependent. […] a leading `!` on most Linuxes. If there is a requirement to disable password authentication for the account while allowing still public-key, then the passwd field should be set to something other than these values (eg `NP` or `*NP*`). »
- `sshd_config(5)`, `UsePAM` : « Enables the Pluggable Authentication Module interface. If set to yes this will enable PAM authentication using KbdInteractiveAuthentication and PasswordAuthentication in addition to PAM account and session module processing for all authentication types. » La page ne dit pas si un compte dont le mot de passe commence par `!` est refusé quand `UsePAM` vaut `yes`.

Aucune page ne permet donc de conclure à elle seule. Relevé :

```bash
sudo /usr/bin/passwd -S tunnel
sudo /usr/sbin/sshd -T -C user=tunnel,host=backend-admin.example.org,addr=192.0.2.50 | grep -i '^usepam '
getent passwd tunnel | cut -d: -f7
```

La vérification est l'étape 8 : connexion réelle du tunnel, puis `sudo /usr/bin/journalctl -u ssh -n 30 --no-pager` sur backend-relais. Ligne attendue : `Accepted publickey for tunnel from <adresse de backend-admin> port … ssh2: ED25519 SHA256:…` (`sshd(8)`, journalisation de l'authentification). Si la connexion est refusée (ligne `Failed`, `not allowed` ou absence de ligne `Accepted`) : **arrêtez-vous et transmettez au mainteneur**, avec la sortie de `passwd -S tunnel` et la ligne du journal ; ne modifiez ni le mot de passe du compte, ni son shell, ni `UsePAM`.

Retour arrière : sans objet (lecture seule).

## Étape 6 — Configuration du client du tunnel (backend-admin)

Machine : backend-admin.

Intention : installer `ssh_config` (couche commune, sans adresse ni clé) et `ssh_config.d/10-relais.conf` (adresse de backend-relais). `ssh_config(5)` : « the first obtained value will be used » ; `Include` : les fichiers sont lus en ordre lexical et leurs valeurs viennent avant celles qui suivent le `Include`. Le compte `paresia-tunnel` n'a aucun droit d'écriture sur `/etc/paresia/tunnel/` : `ssh` n'écrit rien (`StrictHostKeyChecking yes`, empreintes préchargées à l'étape 7).

Valeur de `StreamLocalBindMask` : voir l'étape 9. Elle est posée à `0111` ; l'étape 9 la confirme ou l'infirme.

Fixez ADRESSE_RELAIS à l'adresse de backend-relais, vue de backend-admin (une adresse IP : un nom pourrait solliciter une famille d'adresses absente de `RestrictAddressFamilies=` ; à relever en cas d'erreur de résolution, sans jamais élargir cette directive).

ATTENTION : `install` écrase un éventuel fichier du même nom ; l'outil le sauvegarde d'abord, ou consigne son absence.

```bash
(
set -euo pipefail
: "${ADRESSE_RELAIS:?Fixez ADRESSE_RELAIS avant cette étape}"
if case "$ADRESSE_RELAIS" in ''|*[!0-9A-Fa-f.:]*) false ;; *) true ;; esac; then
    outil copier --si-absent --jeu "$JEU_TUNNEL" /etc/paresia/tunnel/ssh_config /etc/paresia/tunnel/ssh_config.d/10-relais.conf \
      && sudo /usr/bin/install -m 0644 -o root -g root "$DEPOT/deploy/backend-admin/etc/paresia/tunnel/ssh_config" /etc/paresia/tunnel/ssh_config \
      && sudo /usr/bin/install -m 0644 -o root -g root "$DEPOT/deploy/backend-admin/etc/paresia/tunnel/ssh_config.d/10-relais.conf" /etc/paresia/tunnel/ssh_config.d/10-relais.conf \
      && sudo /usr/bin/sed -i "s/^    HostName 192\.0\.2\.200\$/    HostName $ADRESSE_RELAIS/" /etc/paresia/tunnel/ssh_config.d/10-relais.conf || exit 1
else
    echo 'Adresse invalide : rien n a été écrit' >&2
    exit 1
fi
ssh -G -F /etc/paresia/tunnel/ssh_config paresia-relais | grep -i -E '^(hostname|user|port|stricthostkeychecking|exitonforwardfailure|streamlocalbindunlink|streamlocalbindmask|serveraliveinterval|identitiesonly|batchmode|localforward) '
)
```

Résultat attendu : `hostname` à l'adresse paramétrée, `user tunnel`, `stricthostkeychecking true`, `exitonforwardfailure yes`, `streamlocalbindunlink yes`, `streamlocalbindmask 0111`, `serveraliveinterval 15`, `identitiesonly yes`, `batchmode yes` (forme d'affichage de `ssh -G`), deux lignes `localforward` (les deux chemins de socket). `ssh -G` n'ouvre aucune connexion.

Retour arrière : l'outil rétablit ou retire les deux fichiers.

ATTENTION : la restauration écrase ou retire les deux fichiers ; elle s'arrête sans rien modifier si une sauvegarde manque (code 5).

```bash
outil restaurer --jeu "$JEU_TUNNEL" /etc/paresia/tunnel/ssh_config.d/10-relais.conf
outil restaurer --jeu "$JEU_TUNNEL" /etc/paresia/tunnel/ssh_config
```

## Étape 7 — Empreinte de la clé d'hôte, jamais de confiance au premier usage

Machines : backend-relais, puis backend-admin.

Intention : `known_hosts` est posé **avant** le premier démarrage. L'empreinte de la clé d'hôte de backend-relais est lue **sur backend-relais**, puis comparée à celle que `ssh-keyscan` obtient depuis backend-admin. `ssh-keyscan` seul ne prouve rien : la comparaison par un second canal est obligatoire.

Sur backend-relais (lecture seule) :

```bash
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

Sur backend-admin, la clé d'hôte lue est enregistrée dans un fichier provisoire, son empreinte affichée, puis comparée :

```bash
(
set -euo pipefail
if case "$ADRESSE_RELAIS" in ''|*[!0-9A-Fa-f.:]*) false ;; *) true ;; esac; then
    ssh-keyscan -T 5 -t ed25519 "$ADRESSE_RELAIS" | sudo /usr/bin/tee /run/paresia-installation/known_hosts.nouveau > /dev/null \
      && sudo /usr/bin/test -s /run/paresia-installation/known_hosts.nouveau \
      && sudo /usr/bin/ssh-keygen -lf /run/paresia-installation/known_hosts.nouveau
else
    echo 'Adresse invalide : rien n a été écrit' >&2
    exit 1
fi
)
```

Si les deux empreintes sont **identiques**, installez le fichier. Sinon, **arrêtez-vous et transmettez au mainteneur** : ne posez pas `known_hosts`.

ATTENTION : `install` écrase un `known_hosts` existant ; l'outil le sauvegarde d'abord, ou consigne son absence.

```bash
outil copier --si-absent --jeu "$JEU_TUNNEL" /etc/paresia/tunnel/known_hosts
sudo /usr/bin/install -m 0644 -o root -g root /run/paresia-installation/known_hosts.nouveau /etc/paresia/tunnel/known_hosts
sudo /usr/bin/rm /run/paresia-installation/known_hosts.nouveau
sudo /usr/bin/stat -c '%U:%G %a %n' /etc/paresia/tunnel/known_hosts
```

Résultat attendu : `root:root 644`. Le compte du service ne peut pas modifier ce fichier.

Retour arrière : l'outil rétablit ou retire `known_hosts`.

ATTENTION : la restauration écrase ou retire le fichier (code 5 si la sauvegarde manque).

```bash
outil restaurer --jeu "$JEU_TUNNEL" /etc/paresia/tunnel/known_hosts
```

## Étape 8 — Unité du tunnel et démarrage (backend-admin)

Machine : backend-admin.

Intention : créer les dossiers, copier l'unité, la vérifier, la démarrer (`start`, jamais l'activation au démarrage : l'unité n'a pas de section `[Install]` et est tirée par `pollux.service` et `romulus.service`, dont l'arrêt ou le redémarrage arrête ou redémarre le tunnel), puis lire le journal des deux machines. Les comptes et groupes `paresia-tunnel`, `paresia-romulus` et `paresia-pollux` doivent déjà exister (procédure de backend-admin).

`tmpfiles.d(5)`, type `d`, champs Mode, User et Group : les dossiers sont créés s'ils manquent ; leurs modes et propriétaires sont ajustés même s'ils existent. L'âge `-` désactive le nettoyage périodique. `systemd-tmpfiles(8)` utilise directement le fichier passé en chemin absolu. Ces dossiers persistent à l'arrêt du service et sont recréés au démarrage du système. `systemd.exec(5)`, `ProtectSystem=` et `ReadWritePaths=` : seuls les deux sous-dossiers sont ouverts en écriture dans l'unité, pour créer les sockets après cette préparation ; le parent reste en lecture seule dans le service.

`tmpfiles.d(5)` crée le parent avant ses enfants. La commande lancée sous root peut créer les sous-dossiers sous `/run/paresia-tunnel` en `root:root` 0711 ; ssh peut traverser ce parent, puis écrire dans ses sous-dossiers, sans pouvoir les remplacer dans le parent.

ATTENTION : l'arrêt d'un tunnel déjà installé coupe Pollux et Romulus de leurs jumeaux. Il précède le remplacement de l'ancienne unité pour qu'elle libère ses dossiers. `install` écrase les deux fichiers après sauvegarde, et `systemd-tmpfiles` ajuste les trois dossiers. En cas d'échec du bloc, arrêtez la procédure avant le démarrage.

```bash
(
set -euo pipefail
if sudo /usr/bin/test -f /etc/systemd/system/paresia-tunnel.service; then
    sudo /usr/bin/systemctl stop paresia-tunnel.service
fi
outil copier --si-absent --jeu "$JEU_TUNNEL" /etc/tmpfiles.d/paresia-tunnel.conf
sudo /usr/bin/install -D -m 0644 -o root -g root "$DEPOT/deploy/backend-admin/etc/tmpfiles.d/paresia-tunnel.conf" /etc/tmpfiles.d/paresia-tunnel.conf
sudo /usr/bin/systemd-tmpfiles --create /etc/tmpfiles.d/paresia-tunnel.conf
outil copier --si-absent --jeu "$JEU_TUNNEL" /etc/systemd/system/paresia-tunnel.service
sudo /usr/bin/install -m 0644 -o root -g root "$DEPOT/deploy/backend-admin/etc/systemd/system/paresia-tunnel.service" /etc/systemd/system/paresia-tunnel.service
sudo /usr/bin/systemctl daemon-reload
sudo /usr/bin/systemd-analyze verify paresia-tunnel.service
)
```

Résultat attendu : aucune erreur de création des dossiers ni de `systemd-analyze verify` pour cette unité.

ATTENTION : le bloc suivant démarre le tunnel. `Type=simple` ne garantit pas que les sockets soient déjà à l'écoute au retour de `start` (`systemd.service(5)`) : vérifiez leur présence avant l'étape suivante.

```bash
sudo /usr/bin/systemctl start paresia-tunnel.service
sudo /usr/bin/systemctl status paresia-tunnel.service --no-pager
sudo /usr/bin/journalctl -u paresia-tunnel.service -n 30 --no-pager
ss -xl | grep paresia-tunnel
sudo /usr/bin/stat -c '%U:%G %a %F %n' /run/paresia-tunnel /run/paresia-tunnel/romulus /run/paresia-tunnel/pollux
```

Sur backend-relais :

```bash
sudo /usr/bin/journalctl -u ssh -n 30 --no-pager
```

Résultat attendu :

- backend-admin : `active (running)` ; journal sans erreur ; les deux sockets locales à l'écoute ;
- backend-relais : une ligne `Accepted publickey for tunnel from <adresse de backend-admin> port … ssh2: ED25519 SHA256:…`. Sinon, **arrêtez-vous et transmettez au mainteneur** (voir l'étape 5).
- Dossiers : parent `root:root 711`, sous-dossier `romulus` `paresia-tunnel:paresia-romulus 710`, sous-dossier `pollux` `paresia-tunnel:paresia-pollux 710`. Les trois chemins sont des répertoires, sans lien symbolique (`stat` sans `-L`, champ `%F`). En cas d'écart, arrêtez la procédure et conservez le relevé.
- Une erreur de résolution ou de création de socket dans `sudo /usr/bin/journalctl -u paresia-tunnel` : à relever et à transmettre.

Retour arrière :

ATTENTION : l'arrêt du tunnel coupe Pollux et Romulus de leurs jumeaux.

```bash
sudo /usr/bin/systemctl stop paresia-tunnel.service
outil restaurer --jeu "$JEU_TUNNEL" /etc/systemd/system/paresia-tunnel.service
outil restaurer --jeu "$JEU_TUNNEL" /etc/tmpfiles.d/paresia-tunnel.conf
sudo /usr/bin/systemctl daemon-reload
```

La restauration des fichiers ne rétablit pas les modes des dossiers déjà créés ; ils restent sous `/run` jusqu'au redémarrage du système. Le tunnel reste arrêté : avant de le relancer, appliquez la préparation des dossiers correspondant à la version restaurée. En particulier, si vous revenez à une ancienne unité à `RuntimeDirectory=`, refaites la préparation des dossiers prévue par la version précédente de l'unité : la restauration de l'unité seule ne suffit pas. Vérifiez ensuite ses propriétaires, groupes et permissions avant de reprendre les essais.

## Étape 9 — Mode des sockets et accès des démons (backend-admin)

Machine : backend-admin.

Intention : établir par un essai réel que les sockets locales créées par `ssh` sont accessibles à Pollux et à Romulus, et à eux seuls, malgré `UMask=0077` de l'unité.

Extraits :

- `ssh_config(5)`, `StreamLocalBindMask` : « Sets the octal file creation mode mask (umask) used when creating a Unix-domain socket file for local or remote port forwarding. » ; « The default value is 0177, which creates a Unix-domain socket file that is readable and writable only by the owner. »
- `systemd.exec(5)`, `UMask=` : « Controls the file mode creation mask. »
- `unix(7)` : « On Linux, connecting to a stream socket object requires write permission on that socket ».

Valeur retenue : `0111`, avec des sockets 0666 attendues ; le mode réel reste **à relever**. Les dossiers créés à l'étape 8 sont en 0710, avec `paresia-tunnel` pour propriétaire et le groupe de leur seul démon pour la traversée : `paresia-romulus` ou `paresia-pollux`. Aucun autre compte ne doit appartenir à ces groupes. Le parent en 0711 permet d'atteindre les sous-dossiers, qui refusent les autres comptes (hors propriétaire et root). Chaque démon contrôle aussi l'uid de son pair (`SO_PEERCRED`). Au redémarrage du service, `StreamLocalBindUnlink yes` supprime une socket restante avant sa recréation (`ssh_config(5)`), sans changer les permissions des dossiers.

Relevez les membres déclarés des deux groupes (`getent(1)`, base `group` ; `group(5)`, champ `liste_utilisateurs`) :

```bash
sudo /usr/bin/getent group paresia-romulus paresia-pollux
```

Résultat attendu : deux lignes, une pour `paresia-romulus`, l'autre pour `paresia-pollux`, avec le quatrième champ vide : aucun membre supplémentaire. L'appartenance primaire des démons est définie dans la procédure des comptes. Si un groupe manque ou si sa liste de membres n'est pas vide, arrêtez la procédure avant les connexions et conservez le relevé.

```bash
sudo /usr/bin/stat -c '%U:%G %a %n' /run/paresia-tunnel/romulus/remus.sock /run/paresia-tunnel/pollux/castor.sock
sudo /usr/bin/stat -c '%U:%G %a %F %n' /run/paresia-tunnel /run/paresia-tunnel/romulus /run/paresia-tunnel/pollux
sudo /usr/bin/namei -l /run/paresia-tunnel/romulus/remus.sock /run/paresia-tunnel/pollux/castor.sock
```

Résultat attendu : les deux sockets sont `paresia-tunnel:paresia-tunnel 666` ; le parent est `root:root 711` (`drwx--x--x`) ; `romulus` est `paresia-tunnel:paresia-romulus 710` et `pollux` est `paresia-tunnel:paresia-pollux 710` (`drwx--x---`). `namei -l` doit confirmer les répertoires et leurs groupes, sans lien symbolique. Notez les modes réels.

Connexion réelle de chaque démon (la connexion de Romulus est sans message : Remus ne reçoit rien) :

```bash
sudo /usr/sbin/runuser -u paresia-romulus -- /usr/bin/python3 -c "import socket; s=socket.socket(socket.AF_UNIX); s.settimeout(3); s.connect('/run/paresia-tunnel/romulus/remus.sock'); print('connecte')"
sudo /usr/sbin/runuser -u paresia-pollux -- /usr/bin/python3 -c "import socket; s=socket.socket(socket.AF_UNIX); s.settimeout(3); s.connect('/run/paresia-tunnel/pollux/castor.sock'); print('connecte')"
sudo /usr/sbin/runuser -u nobody -- /usr/bin/python3 -c "import socket; s=socket.socket(socket.AF_UNIX); s.connect('/run/paresia-tunnel/pollux/castor.sock')" 2>&1 | tail -n 1
sudo /usr/sbin/runuser -u paresia-romulus -- /usr/bin/python3 -c "import socket; s=socket.socket(socket.AF_UNIX); s.connect('/run/paresia-tunnel/pollux/castor.sock')" 2>&1 | tail -n 1
sudo /usr/sbin/runuser -u paresia-pollux -- /usr/bin/python3 -c "import socket; s=socket.socket(socket.AF_UNIX); s.connect('/run/paresia-tunnel/romulus/remus.sock')" 2>&1 | tail -n 1
```

Résultat attendu : `connecte` pour les deux premières ; `PermissionError` pour les trois dernières (autre compte, mauvais dossier). **Si l'une des deux premières échoue** (accès refusé à Romulus ou à Pollux), **arrêtez-vous : à transmettre au mainteneur**, avec la sortie des commandes `stat` et `namei`. Si un essai négatif réussit, arrêtez aussi le tunnel et conservez les relevés : l'isolement n'est pas établi. Aucune autre solution (ACL sur la socket, `UMask=` de l'unité, groupe dédié) n'est mise en œuvre sans arbitrage.

Un échange applicatif avec Castor par le tunnel (ping puis fermeture de la session 9001, sans effet sur une session réelle) :

ATTENTION : cet essai ouvre puis ferme le feu de la session 9001 de Castor ; ne pas le mener tant qu'une session réelle porte ce numéro.

```bash
jumeaux() {
    sudo /usr/sbin/runuser -u "$1" -- /usr/bin/python3 -c "import json,secrets,socket,sys; s=socket.socket(socket.AF_UNIX); s.settimeout(3); s.connect(sys.argv[1]); s.sendall(json.dumps({'proto':'jumeaux/1','id':secrets.token_hex(8),'session':int(sys.argv[3]),'action':sys.argv[2],'params':{}}).encode()+b'\n'); print(s.makefile('rb').readline().decode().strip())" "$2" "$3" "$4" 2>&1 | tail -n 1
}
jumeaux paresia-pollux /run/paresia-tunnel/pollux/castor.sock castor/light/ping 9001
jumeaux paresia-pollux /run/paresia-tunnel/pollux/castor.sock castor/light/close 9001
```

Résultat attendu : `"ok":true` pour les deux réponses. Sur backend-relais, `sudo /usr/bin/journalctl -u castor.service -n 30 --no-pager` montre `light_green` puis `light_closed` pour la session 9001.

Retour arrière : l'essai ne laisse aucun état durable (le feu de la session 9001 se referme).

## Étape 10 — Chaîne de protection

| Protection du cahier | Où | Essai qui la vérifie |
| --- | --- | --- |
| Clé restreinte (`restrict`, `port-forwarding`) | `authorized_keys` de `tunnel` | étape 4 : valeurs effectives de `sshd -T` ; étape 8 : connexion acceptée |
| `from=` | `authorized_keys` de `tunnel` | connexion refusée depuis une autre adresse (à tenter seulement si une autre adresse source existe) |
| Commande forcée `/bin/false` | `authorized_keys` de `tunnel` | `ssh -N` ne l'exécute pas : le tunnel s'établit (étape 8) |
| `AllowStreamLocalForwarding local`, `AllowTcpForwarding local` | bloc `Match User tunnel` | étape 4 |
| `PermitListen none` | bloc `Match User tunnel` | étape 4 |
| Règle nftables `paresia_relais` | procédure du relais, étape 7 | hors de l'essai tant qu'elle n'est pas chargée : voir les limites connues |
| Groupes des sockets | procédure du relais, étapes 10 et 11 | `stat` des sockets du relais |
| `SO_PEERCRED` | chaque démon | refus d'un autre uid (étape 9) |
| `StreamLocalBindMask` et groupes des dossiers | `ssh_config`, `tmpfiles.d/paresia-tunnel.conf` | étape 9 |
| Parent `/run/paresia-tunnel` | `tmpfiles.d/paresia-tunnel.conf` | étape 8 |
| Durcissement IP du tunnel (`IPAddressAllow=`, `IPAddressDeny=`) | optionnel, hors dépôt | non livré : la valeur dépend de l'installation |

Retour arrière : sans objet (lecture seule).

## Retrait complet

Dans cet ordre : arrêt du tunnel (ATTENTION : coupe Pollux et Romulus de leurs jumeaux), puis restauration, par l'outil et le jeu `JEU_TUNNEL`, des fichiers dans l'ordre inverse de leur pose (unité, `tmpfiles.d/paresia-tunnel.conf`, `known_hosts`, `10-relais.conf` et `ssh_config`, clés ; sur backend-relais : fichier `40-paresia-tunnel-allowusers.conf` s'il a été créé, bloc sshd avec `sshd -t` puis `systemctl reload ssh` session de secours ouverte, puis `authorized_keys`). Chaque restauration est donnée à l'étape de pose.
