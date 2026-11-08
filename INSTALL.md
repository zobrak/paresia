# Installer Paresia

Version du document : 0.1.19 · 2026-11-08.

**Alpha : pas en production. À essayer sur des machines jetables.** Ce guide installe le noyau de Paresia sur deux machines Debian 13 : le côté **yang** (`backend-admin` : Pollux, Romulus) et le côté **yin** (`backend-relais` : Castor, Remus), reliés par un tunnel SSH. La mise à jour d'une installation existante est au § 12. Le serveur web et le proxy sont à votre charge (§ 11).

Détails et raisons des choix : [wiki, page Installation](docs/wiki/Installation.md). Prérequis complets : `docs/prerequis.md`. Pages de manuel : `installer-backend-admin(8)` et `installer-backend-relais(8)`.

## Vue d'ensemble

L'installation se fait en trois passes, dans cet ordre, car chaque machine a besoin d'une valeur produite par l'autre :

1. `backend-admin` : le script crée les comptes et le tunnel, et affiche la clé publique du tunnel.
2. `backend-relais` : le script reçoit cette clé, installe Castor et Remus, et affiche l'empreinte de sa propre clé d'hôte SSH.
3. `backend-admin` de nouveau : le script reçoit l'empreinte du relais, pose l'unité du tunnel et la démarre. Le tunnel n'est jamais activé pour lui-même : il est tiré par `pollux.service` et `romulus.service`, et s'arrête avec eux.

Dans les commandes ci-dessous, les `…` et les valeurs entre apostrophes (clés, empreintes) sont des **exemples à remplacer** par celles que vos scripts affichent. Les adresses `192.0.2.x` sont à remplacer par celles de vos machines.

## 1. Ce qu'il vous faut

- **Deux machines Debian 13**, installation minimale, avec `systemd`. Dans les exemples : `backend-admin` en `192.0.2.10` et `backend-relais` en `192.0.2.20` (adresses d'exemple, RFC 5737).
- Réseau : `backend-admin` joint `backend-relais` en TCP, port 22 (SSH). Rien d'autre n'est requis entre les deux.
- **Sur `backend-admin` : le script doit tourner avec l'UID 0 (root).** Il refuse tout autre UID. `sudo` n'est pas requis ; si le compte root est désactivé, lancer le script par `sudo` convient, car l'UID est alors 0. Ce dernier cas découle du code (`controle_identite` exige l'UID 0 ; la fonction `sudo()` appelle le vrai `sudo` s'il est présent) et n'a pas été essayé sur une vraie machine.
- **Sur `backend-relais` : un compte ordinaire doté de `sudo` (1.9.10 au moins ; Debian 13 fournit la 1.9.16).** Le script refuse de s'exécuter en root. Vous le lancez sans préfixe `sudo` : il appelle lui-même `sudo` commande par commande.
- Pour chaque machine, une **session de secours** : un second terminal SSH (ou la console de la machine) ouvert et testé avant de commencer. Le script recharge `sshd` et vous en avez besoin si une règle vous coupe.
- Sur `backend-relais`, le conteneur Docker DOIT s'appeler `strfry` et être lancé depuis l'image exacte `z0brak/paresia-yin-strfry:4cd3cf6` (`docker pull z0brak/paresia-yin-strfry:4cd3cf6`). Le script vérifie qu'il existe et que son image correspond à la version déclarée par le greffon strfry (étiquette `4cd3cf6`) ; il s'arrête sinon, avant toute modification (code 78). Il ne crée, ne démarre ni ne modifie ce conteneur. Sans relais strfry à administrer (essai du noyau seul), ajoutez `--sauter produit` aux commandes du relais (§ 5).
- Conseil, non une obligation : pour installer Docker Engine sur Debian 13, le dépôt `docker-ce` est activable par `extrepo` (`apt install extrepo`, `extrepo enable docker-ce`, `apt update`, `apt install docker-ce docker-ce-cli containerd.io docker-compose-plugin`).

## 2. Installer les paquets

Sur `backend-admin`, en root :

```
apt install git ca-certificates python3 python3-cryptography curl openssh-client openssh-server iproute2
```

Sur `backend-relais`, en root (ou, si `sudo` est déjà là, avec `sudo apt install …`) :

```
apt install git ca-certificates python3 sudo nftables openssh-client openssh-server iproute2
```

Si votre compte n'a pas encore `sudo` sur `backend-relais`, ajoutez-le au groupe `sudo` (`usermod -aG sudo <compte>`) puis ouvrez une nouvelle session.

`git` ne sert qu'à récupérer le dépôt ; `iproute2` fournit `ss`, que les scripts emploient pour leurs contrôles.

## 3. Récupérer le dépôt

Sur chaque machine, récupérez le dépôt officiel de Paresia **à la même version** (un clone, ou l'archive d'une version publiée), dans un dossier de votre compte. Les scripts s'exécutent depuis ce dossier : ils ne téléchargent ni ne clonent rien. Ne placez jamais de lien symbolique à la place du dossier.

Contrôlez la version : `cat VERSION` dans le dossier.

## 4. Passe 1 : `backend-admin`

Dans le dossier du dépôt, en root. D'abord, une vérification qui ne modifie rien :

```
bash deploy/backend-admin/installer-backend-admin.sh --verifier
```

Un prérequis manquant arrête le script avec le code 69 et le nomme. Puis l'installation, étape par étape (le mode `--alpha-test` fait une pause après chaque étape et s'arrête au premier écart ; il exige un terminal) :

```
bash deploy/backend-admin/installer-backend-admin.sh --alpha-test --session-secours oui
```

À la fin, le script affiche deux lignes à reporter sur `backend-relais` :

```
CLE_PUBLIQUE_TUNNEL=ssh-ed25519 AAAA…
EMPREINTE_CLE_TUNNEL=SHA256:…
```

Il affiche aussi le nom du jeu de sauvegarde (`/var/backups/paresia/admin/AAAAMMJJ-HHMMSS`) : notez-le pour un éventuel retour arrière.

## 5. Passe 2 : `backend-relais`

Depuis votre compte ordinaire, dans le dossier du dépôt. Les deux valeurs de la passe 1 doivent vous parvenir **fidèlement** (copie, pas retranscription).

```
bash deploy/backend-relais/installer-backend-relais.sh --verifier
bash deploy/backend-relais/installer-backend-relais.sh --alpha-test --session-secours oui \
  --adresse-admin 192.0.2.10 \
  --cle-publique-tunnel 'ssh-ed25519 AAAA…' \
  --empreinte-cle-tunnel 'SHA256:…'
```

À la fin, le script affiche `EMPREINTE_HOTE_RELAIS=SHA256:…`. Transmettez-la à `backend-admin` **par un autre canal que le tunnel lui-même** (par exemple en la lisant sur la console de la machine).

## 6. Passe 3 : `backend-admin`, le tunnel

De nouveau en root sur `backend-admin`, avec l'adresse et l'empreinte du relais :

```
bash deploy/backend-admin/installer-backend-admin.sh --alpha-test --session-secours oui \
  --adresse-relais 192.0.2.20 \
  --empreinte-hote-relais 'SHA256:…'
```

Le script compare cette empreinte à celle que lit `ssh-keyscan` sur le relais ; elles doivent être identiques. Les adresses sont des adresses IP, non des noms.

Les scripts sont **rejouables** : une étape déjà conforme ne fait rien ; un état qui diffère est refusé (code 78), jamais écrasé.

## 7. Vérifier

Les scripts démarrent les unités qu'ils posent (`start`, jamais `restart`) et ne les activent au démarrage du système que sous `--activer`. Sur `backend-admin` :

```
systemctl status pollux.service romulus.service paresia-tunnel.service
ss -xl | grep paresia-tunnel
```

Deux sockets doivent apparaître : `/run/paresia-tunnel/romulus/remus.sock` et `/run/paresia-tunnel/pollux/castor.sock`. Sur `backend-relais` :

```
sudo /usr/bin/systemctl status castor.service remus.service
```

Quand tout est conforme, relancez chaque script avec `--activer` (en gardant les mêmes paramètres) pour activer les unités au démarrage.

## 8. Autoriser votre clé d'administrateur

Sur `backend-admin`, le compte `app` ouvre la session de présence. Son fichier des clés autorisées est créé **vide**, propriété de root : `/var/lib/paresia-app/.ssh/authorized_keys`. Pour autoriser un administrateur, ajoutez-y, en root, une ligne de la forme

```
restrict,command="/usr/local/bin/pollux-session" ssh-ed25519 AAAA… commentaire
```

où `ssh-ed25519 AAAA…` est la clé **publique** de l'administrateur (la clé privée reste dans son agent SSH) et `commentaire` un nom court qui identifie cet administrateur (1 à 64 caractères parmi lettres, chiffres, `.`, `_`, `@`, `-` ; il identifie l'administrateur dans les journaux). L'application Paresia-admin affiche cette ligne (menu « Ligne de clé à remettre »).

Le fichier doit rester `root:root` en `0644` : un autre propriétaire fait refuser la connexion.

## 9. Premier usage

Sur le poste de l'administrateur : voir [Premier usage](docs/wiki/Premier-usage.md). L'application se lance par `python3 -m admin.app` ; elle exige PyQt6 avec QtWebEngine, un agent SSH actif qui détient votre clé, et `openssh-client` (voir `docs/prerequis.md`, § 4). Un essai de bout en bout de la présence, avec un client de banc, est décrit dans `deploy/essai-presence.md`.

## 10. Retour arrière

Chaque script revient sur ce qu'il a posé :

```
bash deploy/backend-<machine>/installer-backend-<machine>.sh --retour-arriere --jeu AAAAMMJJ-HHMMSS --confirme
```

`--jeu` et `--confirme` sont obligatoires. Il restaure dans l'ordre inverse de la pose et ne supprime que les comptes créés par l'installation. Voir [Sauvegarde et retour arrière](docs/wiki/Sauvegarde-et-retour-arriere.md).

## 11. Ce qui est à votre charge ou pas encore livré

- **Serveur web et proxy.** Paresia n'installe ni lighttpd (serveur web) ni HAProxy (proxy) et n'écrit aucune de leurs configurations ; les exigences sont documentées. Elles (pages servies sous `/admin/` et `/admin/greffons/`, acheminement de `/api/admin/` vers Romulus, flux continus sans tampon, adresse du client) sont dans `docs/serveur-web.md`, avec un extrait d'exemple pour lighttpd ; à vous de les mettre en place. Sans serveur web, le client ne joint pas l'API depuis un poste distant. Les pages à servir sont celles que l'installation de `backend-admin` pose sous `/usr/local/share/paresia/web/`.
- Installation « à partir de rien » en une seule commande pour les deux machines : non livrée ; suivez les § 4 à 6.
- **bunkerd et Nisaba** : pas d'unité systemd ni d'installation livrées.
- **Greffon strfry** : livré en base (trois fonctions : état, arbres negentropy en lecture seule, redémarrage du conteneur ; `docs/plugins/strfry.md`). Aucune page d'administration du relais n'existe encore dans le client.
- Le mode `--alpha-test` est temporaire.

## 12. Mettre à jour une installation existante

Pour amener une machine déjà installée à la version d'un clone plus récent, utilisez **le même script avec `--mise-a-jour`**. Chaque machine se met à jour séparément, depuis un clone propre de la version voulue.

1. Dans le nouveau clone, relisez les changements (`CHANGELOG.md`) et lancez d'abord la vérification des prérequis : `bash deploy/backend-<machine>/installer-backend-<machine>.sh --verifier`. Tous les prérequis manquants sont signalés en une fois (code 69).
2. Lancez la mise à jour. Ouvrez et testez d'abord une session de secours : `--session-secours oui` est **exigé** quand la configuration de sshd livrée diffère de celle qui est installée, et pour le retour arrière d'un jeu qui l'a modifiée.

   ```
   bash deploy/backend-<machine>/installer-backend-<machine>.sh --mise-a-jour --session-secours oui
   ```

   Sur `backend-admin`, la partie **tunnel** n'est mise à jour que si vous redonnez `--adresse-relais` et `--empreinte-hote-relais` (les mêmes qu'à l'installation) ; sans eux, l'unité et la configuration du tunnel ne sont ni comparées ni touchées. Sur `backend-relais`, la partie tunnel n'est mise à jour que si vous redonnez les trois paramètres `--adresse-admin`, `--cle-publique-tunnel` et `--empreinte-cle-tunnel` : le script compare alors le réglage sshd du compte `tunnel` (`50-paresia-tunnel.conf`) et, s'il diffère, exige la session de secours. Le script du relais arrête Remus puis Castor ; il ne touche jamais à la table `nftables` d'une installation existante (un écart avec la version livrée est seulement signalé) ; et s'il y a des fichiers à remplacer alors que Pollux ou Romulus tournent sur la même machine (profil `partage`), il refuse : arrêtez-les vous-même d'abord.

Ce que fait le script :

- Il lit la version installée (`/usr/local/lib/paresia/VERSION`) et celle du clone, affiche « installée X, livrée Y » et ne remplace que ce qui diffère. Une version livrée **plus ancienne**, un fichier de version installé absent ou illisible, ou un format de sauvegarde incompatible entre l'outil installé et le nouveau : refus (code 78) avant toute modification. Un état identique est « déjà en place ». La même version livrée avec des fichiers différents est traitée comme une mise à jour. Sans installation existante, `--mise-a-jour` s'arrête (code 78) : utilisez l'installation (§ 4 à 6).
- **Demander la mise à jour vaut accepter l'interruption des unités de Paresia.** Avant toute modification, il annonce les unités qui vont être arrêtées, l'effet et le nom du jeu de sauvegarde : sur `backend-admin`, Pollux puis Romulus (les sessions de présence sont fermées ; le tunnel n'est arrêté que si vous avez redonné ses paramètres et que son unité ou sa configuration change) ; sur `backend-relais`, Remus puis Castor (les feux de Castor repassent au rouge). Il n'arrête, ni ne redémarre aucun autre service (strfry, Docker, lighttpd, bunkerd).
- Ordre : sauvegarde complète, arrêt (`systemctl stop`, jamais `restart`), remplacement du code, de la configuration livrée et des unités, rechargement de systemd, redémarrage des **seules unités qui étaient actives**, attente de l'état actif, vérifications et contrôle de la version. L'activation au démarrage n'est jamais modifiée.
- **Configuration.** Les empreintes SHA-256 des fichiers livrés sont enregistrées dans `/usr/local/lib/paresia/empreintes-conf` (comme les `conffiles` de dpkg). Un fichier de `/etc/paresia` **inchangé** depuis la pose est remplacé ; un fichier que vous avez **modifié**, ou sans empreinte enregistrée, est conservé tel quel et la version livrée est déposée à côté, en `<fichier>.paresia-nouveau`. Les options nouvelles et supprimées sont affichées par leur nom, jamais par leur valeur : à vous de reporter ce qui vous convient. **Première mise à jour d'une installation faite avec une version plus ancienne** : le fichier d'empreintes n'existe pas encore, donc tout fichier de configuration qui diffère de la version livrée est considéré comme modifié par vous et conservé ; comparez-le au fichier `.paresia-nouveau`.
- **Échec d'une vérification** après l'arrêt des unités : retour arrière automatique du code et de la configuration (aucun compte ni groupe supprimé), sortie 78 avec le nom du jeu.
- **Migration de données.** Les scripts ne migrent aucune donnée : chaque démon migre les siennes à son démarrage. Si le journal d'un démon redémarré montre une migration (`state_migrated`), ou s'il est illisible (dans le doute, rien n'est restauré), le script ne restaure **rien**, arrête les unités redémarrées et affiche la marche à suivre : le retour arrière est alors manuel, avec la sauvegarde propre du démon.
- En fin de mise à jour, il affiche la commande de lecture du journal de chaque unité redémarrée.

`--mise-a-jour` ne se combine pas avec `--retour-arriere` ni `--verifier` (code 64). Pour revenir à la version précédente après une mise à jour réussie, utilisez `--retour-arriere --jeu <nom> --confirme` avec le jeu affiché : il arrête les seules unités de la liste, restaure code, version, unités et configuration, recharge systemd et reprend les unités qui étaient actives ; il ne supprime aucun compte. Voir [Sauvegarde et retour arrière](docs/wiki/Sauvegarde-et-retour-arriere.md) et `installer-backend-<machine>(8)`.
