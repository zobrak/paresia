# Installer Paresia : installation semi-automatique

Version du document : 0.1.19 · 2026-11-08.

Suivi, 2026-11-09 : allégé (fins d'étape fusionnées en une phrase, section « Cinq notions pour commencer » ajoutée) ; quinze étapes, commandes, valeurs et résultats inchangés ; numéro du document inchangé.

Suivi, 2026-11-09 : renvois de fin de page vers la page HAProxy et vers l'Accueil du wiki (parties noyau et greffons) ; numéro du document inchangé (aucun numéro donné).

**Alpha : pas en production. À essayer sur des machines jetables.**

À la fin de ce parcours, vous aurez deux machines Debian 13 reliées entre elles : yin héberge le relais, yang sert à l'administrer, et un administrateur dont la clé est autorisée pourra ouvrir une session de présence. Le parcours compte quinze étapes, à faire dans l'ordre, en passant d'une machine à l'autre ; aucune durée n'est annoncée, elle dépend de vos machines et de votre connexion. Les scripts font le travail ; vous copiez deux valeurs d'une machine à l'autre et vous contrôlez le résultat de chaque étape.

Ce document décrit l'**installation semi-automatique**. Elle se distingue de l'installation automatique prévue pour la 1.0, où vous n'installerez que le client, qui pilotera tout le reste par SSH (décision D176) ; celle-ci n'existe pas encore. Le principe des scripts, leurs options et leurs codes de sortie sont dans [`docs/wiki/Installation.md`](docs/wiki/Installation.md).

## Cinq notions pour commencer

- **Yin** : la machine du relais. Elle est visible depuis Internet, comme une boutique ouverte sur la rue.
- **Yang** : la machine d'administration. Elle n'est pas visible depuis Internet, comme l'arrière-boutique où l'on décide de tout.
- **Tunnel** : une liaison chiffrée et permanente entre yang et yin, comme un couloir privé entre l'arrière-boutique et la boutique.
- **Clé publique** : la partie d'une clé que l'on peut donner à tout le monde, comme une serrure : elle permet de vérifier qu'on détient la clé, sans la révéler.
- **Empreinte** : un résumé court d'une clé, comme une signature à comparer : si les deux empreintes sont identiques, c'est bien la même clé.

Les autres mots du projet sont dans le [Glossaire](docs/wiki/Glossaire.md).

## Ce que vous allez installer

Paresia permet d'administrer un relais Nostr à distance, en prouvant votre présence. Il se compose de deux machines :

- **yang** (`backend-admin` dans les noms de scripts et de dossiers) fait tourner Pollux (la présence) et Romulus (les commandes) ;
- **yin** (`backend-relais` dans les noms de scripts et de dossiers) fait tourner strfry, le relais, avec Castor (le feu de présence) et Remus (l'exécution des commandes).

Chaque machine a besoin d'une valeur produite par l'autre ; l'installation alterne donc entre elles :

```
yang  : prérequis (1-3)              yin : prérequis (4-6)
yang  : démons, passe 1  (7-8)   ->  valeurs : clé du tunnel et empreinte
yin   : démons, passe 2  (9-10)  <-  reçoit la clé du tunnel ; produit l'empreinte de yin
yang  : tunnel, passe 3  (11)    <-  reçoit l'empreinte de yin
vérifier (12-13), activer (14), autoriser votre clé (15)
```

## Sommaire

- [Cinq notions pour commencer](#cinq-notions-pour-commencer)
- [Avant de commencer](#avant-de-commencer)
- [I. Installer les prérequis](#i-installer-les-prérequis)
  - [A. Sur yang](#a-sur-yang) : étapes 1 à 3
  - [B. Sur yin](#b-sur-yin) : étapes 4 à 6 (6 : installer et vérifier strfry)
- [II. Installer les démons](#ii-installer-les-démons)
  - [A. Sur yang (première passe)](#a-sur-yang-première-passe) : étapes 7 et 8
  - [B. Sur yin (deuxième passe)](#b-sur-yin-deuxième-passe) : étapes 9 et 10
- [III. Relier les deux machines](#iii-relier-les-deux-machines) : étape 11
- [IV. Vérifier](#iv-vérifier) : étapes 12 à 14
- [V. Autoriser votre clé d'administrateur et premier usage](#v-autoriser-votre-clé-dadministrateur-et-premier-usage) : étape 15
- [Annexe A : mettre à jour une installation existante](#annexe-a--mettre-à-jour-une-installation-existante)
- [Annexe B : retour arrière](#annexe-b--retour-arrière)
- [Annexe C : réserves et variantes](#annexe-c--réserves-et-variantes)

## Avant de commencer

Il vous faut :

- deux machines Debian 13 avec `systemd`. Exemples : yang en `192.0.2.10`, yin en `192.0.2.20` ;
- yang qui joint yin en TCP sur le port 22 ;
- sur chaque machine, un compte ordinaire membre du groupe `sudo`, avec `curl` installé ;
- `nak` sur le poste où vous conservez vos clés privées (création de la clé du relais) et sur yang (signataires du bunker), plus sur yin : voir [Installer nak](docs/wiki/Installer-nak.md) (non nécessaire aux étapes ci-dessous) ;
- pour chaque machine, un second terminal SSH (ou la console) ouvert et testé : le script recharge `sshd` ;
- le conteneur `strfry` déjà en marche sur yin (page [Installer le relais strfry](docs/wiki/Installer-strfry.md) du wiki), ou, pour un essai du noyau seul, voir l'[annexe C](#annexe-c--réserves-et-variantes).

### À personnaliser obligatoirement

| Valeur | Où | Exemple du guide | Ce qu'il faut mettre |
| --- | --- | --- | --- |
| adresse de yang | étapes [10](#10-sur-yin--installer-les-démons-passe-2) et [14](#14-sur-yin-puis-sur-yang--activer-au-démarrage), `--adresse-admin` | `192.0.2.10` | l'adresse IP de yang |
| adresse de yin | étapes [11](#11-sur-yang--poser-le-tunnel-passe-3) et [14](#14-sur-yin-puis-sur-yang--activer-au-démarrage), `--adresse-relais` | `192.0.2.20` | l'adresse IP de yin (une adresse, non un nom) |
| `CLE_PUBLIQUE_TUNNEL` | étapes [10](#10-sur-yin--installer-les-démons-passe-2) et [14](#14-sur-yin-puis-sur-yang--activer-au-démarrage) | affichée à l'[étape 8](#8-sur-yang--installer-les-démons-passe-1) | ce qui suit `CLE_PUBLIQUE_TUNNEL=` |
| `EMPREINTE_CLE_TUNNEL` | étapes [10](#10-sur-yin--installer-les-démons-passe-2) et [14](#14-sur-yin-puis-sur-yang--activer-au-démarrage) | affichée à l'[étape 8](#8-sur-yang--installer-les-démons-passe-1) | ce qui suit `EMPREINTE_CLE_TUNNEL=` |
| `EMPREINTE_HOTE_RELAIS` | étapes [11](#11-sur-yang--poser-le-tunnel-passe-3) et [14](#14-sur-yin-puis-sur-yang--activer-au-démarrage) | affichée à l'[étape 10](#10-sur-yin--installer-les-démons-passe-2) | ce qui suit `EMPREINTE_HOTE_RELAIS=` |
| `CLE_PUBLIQUE_ADMIN` et `COMMENTAIRE` | [étape 15](#15-sur-yang--autoriser-la-clé-dun-administrateur) | | la clé publique de l'administrateur et un nom court |

# I. Installer les prérequis

On prépare chaque machine : de quoi récupérer le code et les paquets dont les démons ont besoin. Rien de Paresia n'est encore installé.

## A. Sur yang

### 1. Sur yang : installer git

Pour récupérer le code de Paresia, il faut git. Machine : yang, en root.

```
apt install git
```

```
git --version
```

Résultat attendu :

```
git version 2.47.3
```

Git est prêt dès que `git --version` affiche une version ; l'[étape 2](#2-sur-yang--récupérer-le-dépôt) en a besoin.

### 2. Sur yang : récupérer le dépôt

Le dépôt contient les scripts d'installation que vous lancerez à l'[étape 8](#8-sur-yang--installer-les-démons-passe-1). Machine : yang, en root.

```
git clone https://github.com/zobrak/paresia.git ~/paresia
```

```
cat ~/paresia/VERSION
```

Résultat attendu :

```
0.1.19
```

Le dépôt est copié sur yang quand la version s'affiche (si `git clone` échoue, vérifiez la connexion à Internet de yang et relancez-le) ; l'[étape 3](#3-sur-yang--installer-les-paquets) installe les paquets.

### 3. Sur yang : installer les paquets

Les démons de yang s'appuient sur ces paquets Debian. Machine : yang, en root.

```
apt install ca-certificates python3 python3-cryptography curl openssh-client openssh-server iproute2
```

Résultat attendu : `apt` termine sans message `E:`. Un paquet déjà présent est signalé « déjà la version la plus récente » : c'est normal.

Les paquets de yang sont en place quand `apt` revient à l'invite sans `E:` (sinon, lisez la ligne `E:`, qui indique le réseau ou le dépôt Debian en cause, et relancez) ; l'[étape 4](#4-sur-yin--récupérer-le-dépôt) prépare yin.

## B. Sur yin

### 4. Sur yin : récupérer le dépôt

Même raison qu'à l'[étape 2](#2-sur-yang--récupérer-le-dépôt), sur l'autre machine. Machine : yin, avec votre compte.

```
sudo apt install git
```

```
git clone https://github.com/zobrak/paresia.git ~/paresia
```

```
cat ~/paresia/VERSION
```

Résultat attendu (comme sur yang) :

```
0.1.19
```

Le dépôt est copié sur yin quand la version est la même que sur yang (sinon, refaites le clone depuis le même dépôt) ; l'[étape 5](#5-sur-yin--installer-les-paquets) installe les paquets de yin.

### 5. Sur yin : installer les paquets

Les démons de yin s'appuient sur ces paquets Debian. Machine : yin, avec votre compte.

```
sudo apt install ca-certificates python3 nftables openssh-client openssh-server iproute2
```

Résultat attendu : `apt` termine sans message `E:`. Un paquet déjà présent est signalé « déjà la version la plus récente » : c'est normal.

Les paquets de yin sont en place quand `apt` revient à l'invite sans `E:` (sinon, lisez la ligne `E:` et relancez) ; l'[étape 6](#6-sur-yin--installer-et-vérifier-strfry) contrôle le relais strfry.

### 6. Sur yin : installer et vérifier strfry

Paresia administre un relais strfry : il doit tourner avant d'installer les démons. Si ce n'est pas fait, suivez d'abord la page [Installer le relais strfry](docs/wiki/Installer-strfry.md) (conteneur Docker `strfry` de notre image). Si vous utilisez votre propre image, lisez sa section [Si vous n'utilisez pas notre image](docs/wiki/Installer-strfry.md#si-vous-nutilisez-pas-notre-image) (nom du conteneur, étiquette, port 7777, `python3`, arborescence, réglages de `strfry.conf`). Puis contrôlez, machine : yin.

```
sudo docker ps --filter name=^strfry$
```

Résultat attendu : une ligne pour le conteneur `strfry`, à l'état `Up`.

Le relais est prêt quand le conteneur est `Up` (sinon, revenez à la [page strfry du wiki](docs/wiki/Installer-strfry.md)) ; la [partie II](#ii-installer-les-démons) installe les démons, en commençant par yang.

# II. Installer les démons

On installe les démons par un script par machine. Chaque script fait une pause après chaque étape et exige un terminal.

## A. Sur yang (première passe)

### 7. Sur yang : vérifier les prérequis

Le script contrôle que la machine est prête, sans rien modifier. Machine : yang, en root.

```
cd ~/paresia
bash deploy/backend-admin/installer-backend-admin.sh --verifier
```

Résultat attendu : aucune sortie. **Aucune sortie signifie : tous les prérequis de yang sont présents et rien n'a été modifié.**

Yang est prêt à recevoir les démons ; l'[étape 8](#8-sur-yang--installer-les-démons-passe-1) les installe. En cas d'échec, le script s'arrête avec le code 69 et nomme le prérequis manquant : installez-le ([étape 3](#3-sur-yang--installer-les-paquets)), puis relancez.

### 8. Sur yang : installer les démons (passe 1)

Le script installe Pollux et Romulus et crée la clé du tunnel, dont yin a besoin. Machine : yang, en root.

```
cd ~/paresia
bash deploy/backend-admin/installer-backend-admin.sh --alpha-test --session-secours oui
```

Résultat attendu : à la fin, deux lignes à copier telles quelles pour l'[étape 10](#10-sur-yin--installer-les-démons-passe-2).

```
CLE_PUBLIQUE_TUNNEL=ssh-ed25519 AAAA…
EMPREINTE_CLE_TUNNEL=SHA256:…
```

Notez ces deux lignes : elles resservent à l'[étape 10](#10-sur-yin--installer-les-démons-passe-2), puis à l'[étape 14](#14-sur-yin-puis-sur-yang--activer-au-démarrage). Notez aussi le nom du jeu de sauvegarde affiché (`/var/backups/paresia/admin/AAAAMMJJ-HHMMSS`) : il sert au retour arrière ([annexe B](#annexe-b--retour-arrière)).

Yang est installé, avec la clé du tunnel, dès que les deux lignes sont notées ; l'[étape 9](#9-sur-yin--vérifier-les-prérequis) prépare yin. Si le script s'arrête sur un état différent de l'attendu (code 78), il ne modifie rien : lisez son message avant de relancer.

## B. Sur yin (deuxième passe)

### 9. Sur yin : vérifier les prérequis

Même contrôle qu'à l'[étape 7](#7-sur-yang--vérifier-les-prérequis), sans rien modifier. Machine : yin, avec votre compte.

```
cd ~/paresia
bash deploy/backend-relais/installer-backend-relais.sh --verifier
```

Résultat attendu : aucune sortie. **Aucune sortie signifie : tous les prérequis de yin sont présents et rien n'a été modifié.**

Yin est prêt à recevoir les démons ; l'[étape 10](#10-sur-yin--installer-les-démons-passe-2) les installe. En cas d'échec, le script s'arrête avec le code 69 et nomme le prérequis manquant : installez-le ([étape 5](#5-sur-yin--installer-les-paquets)), puis relancez.

### 10. Sur yin : installer les démons (passe 2)

Le script installe Castor et Remus, et autorise la clé du tunnel produite à l'[étape 8](#8-sur-yang--installer-les-démons-passe-1). Machine : yin, avec votre compte (sans `sudo` devant).

**À personnaliser : remplacez `192.0.2.10` par l'adresse de yang, et les deux valeurs `CLE_PUBLIQUE_TUNNEL` et `EMPREINTE_CLE_TUNNEL` par celles de l'[étape 8](#8-sur-yang--installer-les-démons-passe-1) (ce qui suit le signe `=`, copié sans retranscrire).**

```
cd ~/paresia
bash deploy/backend-relais/installer-backend-relais.sh --alpha-test --session-secours oui \
  --adresse-admin 192.0.2.10 \
  --cle-publique-tunnel 'CLE_PUBLIQUE_TUNNEL' \
  --empreinte-cle-tunnel 'EMPREINTE_CLE_TUNNEL'
```

Résultat attendu : à la fin, une ligne à noter pour l'[étape 11](#11-sur-yang--poser-le-tunnel-passe-3).

```
EMPREINTE_HOTE_RELAIS=SHA256:…
```

Transmettez-la à yang par un autre canal que le tunnel, par exemple en la lisant sur la console de la machine : elle resservira à l'[étape 11](#11-sur-yang--poser-le-tunnel-passe-3), puis à l'[étape 14](#14-sur-yin-puis-sur-yang--activer-au-démarrage).

Yin est installé et autorise la clé du tunnel dès que la ligne `EMPREINTE_HOTE_RELAIS=` est notée ; l'[étape 11](#11-sur-yang--poser-le-tunnel-passe-3) relie les deux machines. Si le script refuse (code 77 : compte root, ou 78 : état différent), il ne modifie rien : lisez son message avant de relancer.

# III. Relier les deux machines

### 11. Sur yang : poser le tunnel (passe 3)

Yang connaît maintenant l'empreinte de yin : le script la compare à celle que lit `ssh-keyscan` sur yin, puis pose le tunnel et le démarre. Machine : yang, en root.

**À personnaliser : remplacez `192.0.2.20` par l'adresse IP de yin (une adresse, non un nom), et `EMPREINTE_HOTE_RELAIS` par la valeur de l'[étape 10](#10-sur-yin--installer-les-démons-passe-2).**

```
cd ~/paresia
bash deploy/backend-admin/installer-backend-admin.sh --alpha-test --session-secours oui \
  --adresse-relais 192.0.2.20 \
  --empreinte-hote-relais 'EMPREINTE_HOTE_RELAIS'
```

Résultat attendu : le script se termine sans signaler de différence d'empreinte.

Le tunnel est alors posé et démarré, et la [partie IV](#iv-vérifier) peut le contrôler à l'[étape 12](#12-sur-yang--vérifier-les-démons-et-le-tunnel). Si l'empreinte diffère, le script s'arrête sans poser le tunnel : reprenez l'empreinte affichée sur yin ([étape 10](#10-sur-yin--installer-les-démons-passe-2)) et relancez.

# IV. Vérifier

## A. Sur yang

### 12. Sur yang : vérifier les démons et le tunnel

On contrôle que les unités tournent et que les sockets du tunnel existent. Machine : yang, en root.

```
systemctl status pollux.service romulus.service paresia-tunnel.service
```

Résultat attendu : les trois unités sont `active`.

```
ss -xl | grep paresia-tunnel
```

Résultat attendu : deux sockets, `/run/paresia-tunnel/romulus/remus.sock` et `/run/paresia-tunnel/pollux/castor.sock`.

Yang fonctionne quand les trois unités sont `active` et les deux sockets présentes ; l'[étape 13](#13-sur-yin--vérifier-les-démons) fait le même contrôle sur yin. Sinon, `journalctl -u <unité>` montre la cause ; si `grep` n'affiche rien, le tunnel n'est pas posé : revenez à l'[étape 11](#11-sur-yang--poser-le-tunnel-passe-3).

## B. Sur yin

### 13. Sur yin : vérifier les démons

Même contrôle, côté relais. Machine : yin, avec votre compte.

```
sudo /usr/bin/systemctl status castor.service remus.service
```

Résultat attendu : les deux unités sont `active`.

Yin fonctionne quand les deux unités sont `active` (sinon, `sudo journalctl -u castor.service -u remus.service` montre la cause) ; l'[étape 14](#14-sur-yin-puis-sur-yang--activer-au-démarrage) les fera démarrer avec la machine.

## C. Sur les deux machines

### 14. Sur yin puis sur yang : activer au démarrage

Jusqu'ici, rien ne démarre tout seul après un redémarrage de la machine. Quand tout est conforme, relancez chaque script avec `--activer` et les mêmes paramètres qu'aux étapes [10](#10-sur-yin--installer-les-démons-passe-2) et [11](#11-sur-yang--poser-le-tunnel-passe-3). Machine : yin d'abord.

**À personnaliser : les mêmes valeurs qu'à l'[étape 10](#10-sur-yin--installer-les-démons-passe-2) (`192.0.2.10`, `CLE_PUBLIQUE_TUNNEL`, `EMPREINTE_CLE_TUNNEL`).**

```
cd ~/paresia
bash deploy/backend-relais/installer-backend-relais.sh --alpha-test --session-secours oui --activer \
  --adresse-admin 192.0.2.10 \
  --cle-publique-tunnel 'CLE_PUBLIQUE_TUNNEL' \
  --empreinte-cle-tunnel 'EMPREINTE_CLE_TUNNEL'
```

Puis sur yang, en root.

**À personnaliser : les mêmes valeurs qu'à l'[étape 11](#11-sur-yang--poser-le-tunnel-passe-3) (`192.0.2.20`, `EMPREINTE_HOTE_RELAIS`).**

```
cd ~/paresia
bash deploy/backend-admin/installer-backend-admin.sh --alpha-test --session-secours oui --activer \
  --adresse-relais 192.0.2.20 \
  --empreinte-hote-relais 'EMPREINTE_HOTE_RELAIS'
```

Résultat attendu : « déjà en place » pour tout ce qui est conforme, et les deux scripts se terminent sans erreur.

Les unités démarrent désormais avec les machines ; il reste à autoriser un administrateur à l'[étape 15](#15-sur-yang--autoriser-la-clé-dun-administrateur).

# V. Autoriser votre clé d'administrateur et premier usage

### 15. Sur yang : autoriser la clé d'un administrateur

Pour qu'un administrateur ouvre une session de présence, sa clé publique doit être listée. Machine : yang, en root. Le fichier `/var/lib/paresia-app/.ssh/authorized_keys` est créé vide. Ajoutez-y une ligne par administrateur.

**À personnaliser : ouvrez le fichier `.pub` de l'administrateur dans un éditeur : il contient une ligne de trois mots séparés par des espaces (`ssh-ed25519`, une longue suite qui commence par `AAAA`, puis un nom). Remplacez `CLE_PUBLIQUE_ADMIN` par le deuxième mot, la partie centrale (sans le `ssh-ed25519` déjà écrit dans la commande), et `COMMENTAIRE` par un nom court (1 à 64 caractères : lettres, chiffres, `.`, `_`, `@`, `-`).**

```
echo 'restrict,command="/usr/local/bin/pollux-session" ssh-ed25519 CLE_PUBLIQUE_ADMIN COMMENTAIRE' >> /var/lib/paresia-app/.ssh/authorized_keys
```

Cette commande n'affiche rien. **Aucune sortie signifie : la ligne a été ajoutée au fichier.** Le contrôle ci-dessous le confirme.

La clé est la clé **publique** de l'administrateur, prise sur son poste (fichier `.pub`) : celle que vous employez, selon votre propre politique de clés. Si vous n'en avez pas, nous conseillons d'en créer une dédiée à Paresia, à l'étape 3 du [guide du client](docs/wiki/Installer-client.md#3-préparer-la-clé-ssh-et-lagent) ; le client utilise la clé désignée par son réglage `cle_publique`. La clé privée reste dans l'agent SSH de l'administrateur. L'application Paresia-admin affiche cette ligne (menu « Ligne de clé à remettre »).

```
ls -l /var/lib/paresia-app/.ssh/authorized_keys
```

Résultat attendu :

```
-rw-r--r-- 1 root root 112 nov.  9 00:12 /var/lib/paresia-app/.ssh/authorized_keys
```

Un autre propriétaire fait refuser la connexion. Ce contrôle ne prouve que le propriétaire et les droits, non la clé ajoutée. Pour la vérifier :

```
ssh-keygen -lf /var/lib/paresia-app/.ssh/authorized_keys
```

Résultat attendu (une ligne par clé) :

```
256 SHA256:abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG COMMENTAIRE (ED25519)
```

Comparez cette empreinte à celle de la clé de l'administrateur, sur son poste : `ssh-keygen -lf <fichier .pub>`. Les deux empreintes doivent être identiques.

La clé est autorisée quand les empreintes coïncident et que le propriétaire du fichier est `root` (sinon, corrigez-le avec `chown root:root` sur ce fichier ; si les empreintes diffèrent, retirez la ligne ajoutée et recommencez l'ajout). L'installation est terminée : la suite est ci-dessous.

## Suite

- Installer le serveur web lighttpd sur yang, avant le client : [Installer et configurer lighttpd](docs/wiki/Installer-lighttpd.md), puis régler le frontal : [Régler HAProxy pour Paresia](docs/wiki/Installer-haproxy.md).
- Installer le client sur le poste de l'administrateur : [Installer le client](docs/wiki/Installer-client.md).
- Premier usage : [Premier usage](docs/wiki/Premier-usage.md).
- Configurer Paresia (fichiers de yin et de yang, réglages courants) : [Configuration](docs/wiki/Configuration.md).
- Mise à jour d'une installation existante : [annexe A](#annexe-a--mettre-à-jour-une-installation-existante).
- Retour arrière : [annexe B](#annexe-b--retour-arrière).
- Greffons (strfry, Nisaba, bunker) et tout le reste du guide : [Accueil du wiki](docs/wiki/Accueil.md), parties « Installer le noyau » et « Installer les greffons ».

## Annexe A : mettre à jour une installation existante

Chaque machine se met à jour séparément, avec le même script et `--mise-a-jour`, depuis un clone propre de la version voulue. Machine : celle à mettre à jour, dans le nouveau clone (`~/paresia`). Les scripts gardent leurs noms d'origine : `backend-admin` pour yang, `backend-relais` pour yin.

Sur yang, en root :

```
cd ~/paresia
bash deploy/backend-admin/installer-backend-admin.sh --verifier
bash deploy/backend-admin/installer-backend-admin.sh --mise-a-jour --session-secours oui
```

Sur yin, avec votre compte :

```
cd ~/paresia
bash deploy/backend-relais/installer-backend-relais.sh --verifier
bash deploy/backend-relais/installer-backend-relais.sh --mise-a-jour --session-secours oui
```

Ouvrez et testez d'abord une session de secours. Relisez le [CHANGELOG](CHANGELOG.md) avant de lancer.

- **Interruption.** Demander la mise à jour vaut accepter l'arrêt des unités de Paresia : sur yang, Pollux puis Romulus ; sur yin, Remus puis Castor. strfry, Docker, lighttpd et bunkerd ne sont jamais touchés. L'activation au démarrage n'est pas modifiée.
- **Tunnel.** Sur yang, la partie tunnel n'est mise à jour que si vous redonnez `--adresse-relais` et `--empreinte-hote-relais`. Sur yin, il faut redonner `--adresse-admin`, `--cle-publique-tunnel` et `--empreinte-cle-tunnel`.
- **Versions.** Le script affiche « installée X, livrée Y ». Une version livrée plus ancienne, un fichier de version illisible ou un format de sauvegarde incompatible : refus (code 78) avant toute modification.
- **Configuration.** Un fichier de `/etc/paresia` inchangé est remplacé ; un fichier que vous avez modifié est conservé, la version livrée étant déposée à côté en `<fichier>.paresia-nouveau`. Pour une installation faite avec une version plus ancienne, tout fichier qui diffère est conservé : comparez-le à son `.paresia-nouveau`.
- **Échec d'une vérification.** Retour arrière automatique du code et de la configuration, sortie 78 avec le nom du jeu.
- **Données.** Les scripts ne migrent aucune donnée ; chaque démon migre les siennes au démarrage. Si le journal montre une migration (`state_migrated`) ou est illisible, rien n'est restauré : le retour arrière est alors manuel.
- **Relais.** La table `nftables` d'une installation existante n'est jamais modifiée (un écart est signalé). Si Pollux ou Romulus tournent sur la même machine, le script refuse : arrêtez-les d'abord.
- `--mise-a-jour` ne se combine pas avec `--retour-arriere` ni `--verifier` (code 64).

## Annexe B : retour arrière

Listez d'abord les jeux de sauvegarde disponibles. Sur yang, en root :

```
ls -1 /var/backups/paresia/admin
```

Sur yin, avec votre compte :

```
sudo ls -1 /var/backups/paresia/relais
```

Exemple de sortie (un nom par jeu, du plus ancien au plus récent) :

```
20261109-101500
20261109-143200
```

**À personnaliser : remplacez `AAAAMMJJ-HHMMSS` par le nom du jeu retenu, tel qu'il figure dans cette liste (reportez-le sans le modifier).** Un assistant interactif, qui proposera le choix du jeu, viendra en v0.2.

Sur yang, en root :

```
cd ~/paresia
bash deploy/backend-admin/installer-backend-admin.sh --retour-arriere --jeu AAAAMMJJ-HHMMSS --confirme
```

Sur yin, avec votre compte :

```
cd ~/paresia
bash deploy/backend-relais/installer-backend-relais.sh --retour-arriere --jeu AAAAMMJJ-HHMMSS --confirme
```

`--jeu` et `--confirme` sont obligatoires. Le script restaure dans l'ordre inverse de la pose et ne supprime que les comptes créés par l'installation. Détail : [Sauvegarde et retour arrière](docs/wiki/Sauvegarde-et-retour-arriere.md).

## Annexe C : réserves et variantes

- **Root et sudo.** Sur yang, le script exige l'UID 0 ; lancé par `sudo`, il convient aussi (déduit du code, non essayé). Sur yin, il refuse root et appelle lui-même `sudo` (1.9.10 au moins ; Debian 13 fournit la 1.9.16).
- **Rejouable.** Une étape déjà conforme ne fait rien ; un état qui diffère est refusé (code 78), jamais écrasé. Les unités sont démarrées par `start`, jamais `restart`.
- **Essai du noyau seul, sans strfry.** Ajoutez `--sauter produit` aux commandes de yin ; sautez l'[étape 6](#6-sur-yin--installer-et-vérifier-strfry).
- **Image strfry.** Le conteneur doit s'appeler `strfry` et venir de `z0brak/paresia-yin-strfry:4cd3cf6` ; sinon le script s'arrête avant toute modification (code 78).
- **Serveur web et proxy.** Paresia n'installe ni lighttpd ni HAProxy. Les exigences sont dans [Serveur web](docs/serveur-web.md) un guide pas à pas pour lighttpd dans [Installer et configurer lighttpd](docs/wiki/Installer-lighttpd.md) et les exigences du frontal dans [Régler HAProxy pour Paresia](docs/wiki/Installer-haproxy.md). Les pages à servir sont sous `/usr/local/share/paresia/web/`. Sans serveur web, un poste distant ne joint pas l'API.
- **Non livré.** Installation des deux machines en une seule commande ; unités de bunkerd et de Nisaba ; page d'administration du relais dans le client. Le mode `--alpha-test` est temporaire.
- **Poste de l'administrateur.** L'application se lance par `python3 -m admin.app` ; elle exige PyQt6 avec QtWebEngine, un agent SSH actif et `openssh-client` ([Prérequis](docs/prerequis.md), § 4). Essai de bout en bout : [essai de présence](deploy/essai-presence.md).
- **Références.** Principe des scripts, options et codes de sortie : [Installation](docs/wiki/Installation.md). Prérequis : [Prérequis](docs/prerequis.md). Manuel : `installer-backend-admin(8)` et `installer-backend-relais(8)`.
