# Installer le client Paresia-admin

Version du document : 0.1.19 · 2026-11-09 · [Accueil](Accueil.md)

Public : l'administrateur, sur son propre poste. Objet : installer et lancer l'application de bureau Paresia-admin, puis la relier à yang. Sources : `admin/app/` (dont `config.py` et `conf/paresia-admin.conf`), la page de manuel `paresia-admin(1)`, [Prérequis](../prerequis.md) (§ 4), `.github/workflows/ci.yml` (noms des paquets Debian).

**Alpha : pas en production. À essayer sur des machines jetables.**

## Ce que vous obtenez

À la fin de ce parcours, l'application Paresia-admin tourne sur votre poste. Elle ouvre une **session de présence** sur yang : elle prouve que c'est bien vous, grâce à votre clé SSH, puis affiche les pages d'administration du noyau (état de Paresia, journaux, catalogue des actions). Les pages d'administration du relais, du bunker et du journal légal ne sont pas encore livrées : voir [Premier usage](Premier-usage.md).

## Ce qu'il faut avant

- **Une station sous Linux.** Avec un bureau graphique, c'est le client graphique (GUI) décrit ici ; sans bureau graphique, un client en ligne de commande (CLI) est prévu, mais n'existe pas encore. Les commandes de cette page sont celles de Debian 13 ; sur une autre distribution, adaptez le nom des paquets. Python 3.11 au moins (Debian 13 fournit la 3.13). Exemple du parcours : un compte nommé `utilisateur`, dont le dossier personnel est `/home/utilisateur`.
- **Yin et yang installés** : les étapes 1 à 14 d'[INSTALL.md](../../INSTALL.md) sont terminées (l'[étape 15](../../INSTALL.md#15-sur-yang--autoriser-la-clé-dun-administrateur), autoriser une clé, se fait à l'étape 7 de ce parcours). Dans ce parcours, yang est joint à l'adresse `192.0.2.10` (adresse d'exemple, RFC 5737).
- **Un accès administrateur sur yang** (le compte root de yang), pour l'étape 6 : ajouter votre clé publique.
- **Une adresse web de l'administration** : le nom, en HTTPS, par lequel on joint le serveur web de yang. Ce serveur web n'est pas installé par les scripts de Paresia ; le guide pas à pas est [Installer et configurer lighttpd](Installer-lighttpd.md), les exigences sont dans [Serveur web](../serveur-web.md). Exemple : `https://bunker.example.org`.
- **Une clé SSH, autorisée sur yang et disponible dans votre agent SSH** : utilisez celle que vous voulez, selon votre propre politique de clés. Si vous n'en avez pas, nous conseillons d'en créer une dédiée à Paresia (étape 3). Si elle est déjà autorisée sur yang à l'[étape 15 d'INSTALL.md](../../INSTALL.md#15-sur-yang--autoriser-la-clé-dun-administrateur), vous n'avez pas à l'autoriser de nouveau.

Notions : une **clé SSH** est une paire, une clé **privée** qui reste chez vous et une clé **publique** que l'on peut donner. Un **agent SSH** est un petit programme de votre session qui garde la clé privée en mémoire et signe à votre place : l'application ne lit jamais la clé privée, elle demande la signature à l'agent.

## Sommaire

1. [Installer les paquets](#1-installer-les-paquets)
2. [Récupérer le dépôt](#2-récupérer-le-dépôt)
3. [Préparer la clé SSH et l'agent](#3-préparer-la-clé-ssh-et-lagent)
4. [Enregistrer la clé de yang](#4-enregistrer-la-clé-de-yang)
5. [Configurer l'application](#5-configurer-lapplication)
6. [Lancer l'application](#6-lancer-lapplication)
7. [Autoriser votre clé sur yang](#7-autoriser-votre-clé-sur-yang)
8. [Ouvrir la session et vérifier](#8-ouvrir-la-session-et-vérifier)
9. [En cas de problème](#en-cas-de-problème)

## À personnaliser

| Valeur | Où | Exemple du guide | Ce qu'il faut mettre |
| --- | --- | --- | --- |
| adresse de yang | étapes [4](#4-enregistrer-la-clé-de-yang) et [5](#5-configurer-lapplication) (`hote_ssh`) | `192.0.2.10` | l'adresse de yang, la même qu'à l'[installation](../../INSTALL.md#à-personnaliser-obligatoirement) |
| adresse web de l'administration | étape 5 (`url`) | `https://bunker.example.org` | l'adresse HTTPS de votre serveur web, sans chemin |
| dossier personnel | étape 5 (`cle_publique`, `dossier_i18n`) | `/home/utilisateur` | le dossier personnel de votre compte sur le poste (`echo "$HOME"` l'affiche) |
| nom de la clé | étape 3 (`-C`) | `utilisateur` | un nom court : 1 à 64 caractères, lettres, chiffres, `.`, `_`, `@`, `-` ; ce nom identifie l'administrateur sur yang |

# Le parcours

**Tout se passe sur votre poste**, sauf deux endroits où une commande se lance sur yang, signalés par « **Sur yang** » en gras : le contrôle d'empreinte de l'étape 4 et l'étape 7.

## 1. Installer les paquets

L'application est écrite en Python avec la bibliothèque graphique Qt (PyQt6) et une vue web intégrée (QtWebEngine). Machine : votre poste, avec `sudo` (en root, retirez `sudo`).

```
sudo apt install ca-certificates git openssh-client python3 python3-pyqt6 python3-pyqt6.qtsvg python3-pyqt6.qtwebengine
```

```
python3 -c "from PyQt6.QtWebEngineWidgets import QWebEngineView; print('PyQt6 et QtWebEngine : présents')"
```

Résultat attendu :

```
PyQt6 et QtWebEngine : présents
```

Les paquets sont en place quand cette ligne s'affiche ; une erreur `ModuleNotFoundError` signale un paquet manquant, à installer (un paquet déjà présent est simplement signalé par `apt`). L'[étape 2](#2-récupérer-le-dépôt) récupère le code.

## 2. Récupérer le dépôt

Le dépôt contient l'application et les catalogues de textes qu'elle affiche. Machine : votre poste, avec votre compte ordinaire (pas besoin de root).

```
cd ~
git clone https://github.com/zobrak/paresia.git ~/paresia
```

```
cat ~/paresia/VERSION
```

Résultat attendu : le numéro de version du dépôt, par exemple :

```
0.1.19
```

Le code est copié quand la version s'affiche (si `git clone` échoue, vérifiez la connexion à Internet de votre poste et relancez-le) ; l'[étape 3](#3-préparer-la-clé-ssh-et-lagent) prépare votre clé.

## 3. Préparer la clé SSH et l'agent

C'est avec cette clé que vous prouverez votre présence. Machine : votre poste, compte ordinaire.

D'abord, regardez si un agent SSH tourne déjà dans votre session :

```
echo "$SSH_AUTH_SOCK"
```

Résultat attendu : un chemin de socket, par exemple `/run/user/1000/keyring/ssh` (la forme dépend de votre bureau). Si rien ne s'affiche, aucun agent n'est actif : démarrez-en un **dans ce terminal** (la page [Tips](Tips.md#1-ajouter-une-clé-à-son-agent-ssh) montre comment), puis lancez l'application depuis ce même terminal (étape 6).

**Deux cas.** Chacun emploie la clé qu'il souhaite.

- **Vous avez déjà une clé à employer** (par exemple celle que vous avez autorisée à l'[étape 15 d'INSTALL.md](../../INSTALL.md#15-sur-yang--autoriser-la-clé-dun-administrateur)) : passez la commande `ssh-keygen` ci-dessous, vérifiez qu'elle est dans votre agent, puis lancez le contrôle `ssh-add -L`. À l'étape 5, `cle_publique` désigne le fichier `.pub` de cette clé.
- **Vous n'avez pas de clé** : nous conseillons d'en créer une dédiée à Paresia, ici. **À personnaliser : remplacez `utilisateur` après `-C` par le nom court qui vous identifiera sur yang.** Le programme vous demande une phrase de passe : choisissez-en une, elle protège la clé privée.

```
ssh-keygen -t ed25519 -C utilisateur -f ~/.ssh/paresia-admin
```

Résultat attendu (clé créée ici seulement) : deux fichiers, `/home/utilisateur/.ssh/paresia-admin` (clé privée, à ne jamais copier ni envoyer) et `/home/utilisateur/.ssh/paresia-admin.pub` (clé publique), avec le message « Your identification has been saved in … » (la sortie complète de `ssh-keygen` n'est pas reproduite ici).

**La clé employée par l'application.** L'application signe avec la commande `ssh-keygen -Y sign -f <cle_publique>` : le réglage `cle_publique` de l'étape 5 désigne la clé qu'elle utilise (source : `admin/app/signature.py`). Le code ne contrôle pas le nombre de clés de l'agent ; ce que fait `ssh-keygen` quand l'agent en détient plusieurs n'a pas été relu dans son manuel : non vérifié.

**Si votre clé vit dans un gestionnaire de mots de passe qui fait aussi agent SSH**, il n'y a ni `ssh-keygen` ni ajout à l'agent à faire : déverrouillez le coffre, et `ssh-add -L` doit montrer la clé. Comme l'application lit le fichier désigné par `cle_publique` (source : `admin/app/controleur.py`), copiez la clé publique du coffre, sur une seule ligne, dans `~/.ssh/paresia-admin.pub`, puis contrôlez : `ssh-keygen -lf ~/.ssh/paresia-admin.pub`. Un tel agent peut demander une autorisation à chaque signature : acceptez-la pendant l'ouverture de la session. Le délai de la signature n'a pas de valeur par défaut propre : c'est le temps restant de l'ouverture (`ouverture_s`, 90 s par défaut), borné par la durée de validité du défi donnée par yang (source : `admin/app/presence.py`, `admin/app/signature.py`) ; répondez donc sans attendre.

Ajoutez la clé de l'administrateur (par exemple `~/.ssh/paresia-admin`) à votre agent, comme d'habitude (si vous ne savez pas faire, la page [Tips](Tips.md#1-ajouter-une-clé-à-son-agent-ssh) l'explique pas à pas). Contrôlez ensuite :

```
ssh-add -L
```

Résultat attendu : une ligne qui commence par `ssh-ed25519 AAAA` et se termine par le nom choisi.

La clé est prête quand `ssh-add -L` la montre ; l'[étape 4](#4-enregistrer-la-clé-de-yang) apprend à votre poste à reconnaître yang. Pourquoi : l'application se connecte à yang sans jamais poser de question ; si votre poste ne connaît pas encore yang, la connexion est refusée en silence.

## 4. Enregistrer la clé de yang

Chaque serveur SSH a sa propre clé, son « visage ». Votre poste doit l'avoir enregistrée, sinon la connexion de l'application est refusée. On la récupère puis on **compare son empreinte** avec celle que yang annonce, pour ne pas enregistrer le visage d'un imposteur.

**À personnaliser : remplacez `192.0.2.10` par l'adresse de yang.** Machine : votre poste.

```
ssh-keyscan -t ed25519 192.0.2.10 2>/dev/null | ssh-keygen -lf -
```

Résultat attendu : une ligne du type `256 SHA256:… 192.0.2.10 (ED25519)` (la valeur après `SHA256:` est propre à yang).

**Sur yang**, en root, affichez l'empreinte de sa propre clé d'hôte :

```
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

Résultat attendu : une ligne du type `256 SHA256:… root@… (ED25519)`. **Les deux valeurs `SHA256:…` doivent être identiques.** Si elles diffèrent, arrêtez-vous : ne continuez pas.

Si elles sont identiques, enregistrez la clé de yang sur le poste :

```
mkdir -p ~/.ssh
ssh-keyscan -t ed25519 192.0.2.10 >> ~/.ssh/known_hosts
```

Résultat attendu : une ligne de commentaire `# 192.0.2.10:22 SSH-2.0-OpenSSH_…` sur la sortie d'erreur ; la ligne de clé va dans `~/.ssh/known_hosts` (la forme exacte de la sortie d'erreur n'est pas établie ici).

Yang est connu de votre poste ; l'[étape 5](#5-configurer-lapplication) écrit la configuration de l'application.

## 5. Configurer l'application

L'application lit un petit fichier de réglages, que vous créez. Machine : votre poste, compte ordinaire. Le fichier se place dans `~/.config/paresia/` (le dossier `$XDG_CONFIG_HOME/paresia/` s'il est défini) ; il doit vous appartenir et n'être modifiable par personne d'autre (la commande de droits ci-dessous le garantit). Le nom doit finir par `.conf`.

Créez le dossier, puis le fichier vide :

```
mkdir -p ~/.config/paresia
touch ~/.config/paresia/paresia-admin.conf
```

Fixez maintenant les droits : sur un poste dont le masque de création de fichiers est `002` (courant), les deux commandes précédentes créent des droits trop larges.

```
chmod 700 ~/.config/paresia
chmod 600 ~/.config/paresia/paresia-admin.conf
ls -ld ~/.config/paresia ~/.config/paresia/paresia-admin.conf
```

Résultat attendu (le propriétaire est votre compte ; votre dossier personnel à la place de `/home/utilisateur`) :

```
drwx------ 2 utilisateur utilisateur 4096 nov.  9 10:00 /home/utilisateur/.config/paresia
-rw------- 1 utilisateur utilisateur    0 nov.  9 10:00 /home/utilisateur/.config/paresia/paresia-admin.conf
```

Pourquoi : sans ces droits, l'application refuse le fichier, car un autre compte de votre poste pourrait le modifier (elle refuse aussi un lien symbolique à leur place). La taille et la date de la sortie varient.

Ouvrez `~/.config/paresia/paresia-admin.conf` avec votre éditeur de texte (par exemple `nano ~/.config/paresia/paresia-admin.conf`, installé par `sudo apt install nano` s'il manque) et collez ce contenu. **À personnaliser : `url`, `hote_ssh`, `cle_publique` et `dossier_i18n`, selon le tableau [À personnaliser](#à-personnaliser) ; les autres valeurs sont celles de l'installation par défaut.**

Chaque réglage est précédé d'une ligne de commentaire (elle commence par `#`) qui dit à quoi il sert. Le réglage `ouverture_s` a une valeur par défaut : il est commenté. Pour le changer, retirez le `#` au début de sa ligne et modifiez la valeur. Les autres réglages n'ont pas de valeur par défaut : ils restent actifs, sinon l'application refuserait le fichier.

```
[admin.connexion]
# L'adresse HTTPS du serveur web de yang, sans identifiant, sans chemin ni "/" final.
# L'application ne navigue que vers cette adresse.
url = https://bunker.example.org
# L'adresse de yang, pour la connexion SSH.
hote_ssh = 192.0.2.10
# Le compte de yang auquel on se connecte ; "app" est celui que l'installation crée.
compte_ssh = app
# Le chemin du programme ssh de votre poste (chemin absolu obligatoire).
ssh = /usr/bin/ssh

[admin.cle]
# Le chemin de votre clé publique (étape 3), en chemin complet : le "~" n'est pas remplacé.
cle_publique = /home/utilisateur/.ssh/paresia-admin.pub
# La commande que yang impose à votre clé ; elle sert à construire la ligne de l'étape 7.
# Ne la changez pas.
commande_forcee = /usr/local/bin/pollux-session
# Le chemin du programme ssh-keygen, qui signe le défi.
ssh_keygen = /usr/bin/ssh-keygen

[admin.presence]
# Le temps total accordé à l'ouverture de la session, en secondes (valeur par défaut : 90).
# ouverture_s = 90

[admin.interface]
# La langue des textes affichés.
langue = fr-FR
# Le dossier des catalogues de textes : c'est le dossier "i18n" du dépôt de l'étape 2 (chemin complet).
dossier_i18n = /home/utilisateur/paresia/i18n
```

Le détail de chaque réglage est dans les commentaires du fichier ; retenez seulement que les chemins sont absolus, et que `commande_forcee` ne se change pas.

Pour contrôler les chemins des deux programmes :

```
command -v ssh ssh-keygen
```

Résultat attendu :

```
/usr/bin/ssh
/usr/bin/ssh-keygen
```

Aucun secret ne figure dans ce fichier : il ne contient que des adresses et des chemins. Les réglages sont en place ; l'[étape 6](#6-lancer-lapplication) lance l'application. Si un réglage est invalide, elle refuse de démarrer et nomme le réglage fautif (jamais sa valeur).

## 6. Lancer l'application

Machine : votre poste, dans une session graphique, avec le **même terminal** que l'étape 3 si vous y avez démarré un agent. Le programme se lance depuis le dossier du dépôt.

```
cd ~/paresia
python3 -m admin.app
```

Résultat attendu : une fenêtre s'ouvre, avec un menu de quatre entrées (« Ouvrir l'administration », « Fermer l'administration », « Ligne de clé à remettre », « Quitter ») et un indicateur d'état **gris** : aucune session n'est ouverte. Ce que la fenêtre affiche avant l'ouverture d'une session n'est pas établi. Le terminal reste occupé tant que la fenêtre est ouverte.

Si la fenêtre ne s'ouvre pas et qu'un message `Configuration invalide : <réglage>` apparaît dans le terminal, corrigez le réglage nommé dans le fichier de l'étape 5 et relancez. La fenêtre est ouverte ; l'[étape 7](#7-autoriser-votre-clé-sur-yang) autorise votre clé, car sans cela yang refuserait l'ouverture.

## 7. Autoriser votre clé sur yang

Yang n'accepte que les clés qu'on lui a déclarées. Cette étape est l'[étape 15 de l'installation](../../INSTALL.md#15-sur-yang--autoriser-la-clé-dun-administrateur) : lisez-la, elle donne la commande et les contrôles.

**Si la clé que vous employez est déjà autorisée sur yang** (étape 15 d'INSTALL.md) : inutile de la déclarer une seconde fois. Il vous suffit de comparer les empreintes : celle de votre poste (`ssh-keygen -lf ~/.ssh/paresia-admin.pub`, en remplaçant le chemin par celui de votre fichier `.pub`) doit être identique à celle que yang affiche pour le fichier `authorized_keys` ; puis passez à l'[étape 8](#8-ouvrir-la-session-et-vérifier).

**Sinon**, la clé que vous employez n'est pas encore autorisée : copiez le contenu de votre fichier `.pub` depuis votre éditeur (ou depuis votre coffre), puis suivez l'[étape 15 d'INSTALL.md](../../INSTALL.md#15-sur-yang--autoriser-la-clé-dun-administrateur), **sur yang**, en root. La fenêtre de l'application affiche aussi la ligne complète à ajouter (menu « Ligne de clé à remettre »).

Votre clé est autorisée quand l'empreinte de yang correspond à celle de votre poste (`ssh-keygen -lf ~/.ssh/paresia-admin.pub`) ; l'[étape 8](#8-ouvrir-la-session-et-vérifier) ouvre la session.

Cette étape sera faite par l'installation de yang dans une prochaine version : les clés des administrateurs, dont celle du superadmin, y seront installées sans rien recopier.

## 8. Ouvrir la session et vérifier

Machine : votre poste, dans la fenêtre de l'application.

1. Menu « Ouvrir l'administration ». Si votre clé a une phrase de passe et que l'agent ne l'a pas encore déverrouillée, l'agent la demande à ce moment (selon votre agent, la demande peut aussi se faire à l'étape 3).
2. Attendez : l'ouverture dure quelques secondes, au plus `ouverture_s` (90 par défaut).
3. L'indicateur passe au **vert** : la session de présence est ouverte et la vue est chargée.
4. Ouvrez la page « État de Paresia » : elle affiche la version de Paresia et la liste des démons de yang.

Résultat attendu : l'indicateur vert et, sur la page, la version et les démons du noyau. La présence est ouverte et vous lisez l'état de votre installation. L'indicateur **rouge** signale une session perdue : la fenêtre propose de la rouvrir, elle ne le fait jamais seule. Pour la suite, voir [Premier usage](Premier-usage.md), qui décrit les trois pages du noyau.

Pour fermer proprement : menu « Fermer l'administration », puis « Quitter ».

## En cas de problème

- **Message « Configuration invalide » sans nom de réglage** : le fichier a été refusé avant la lecture des réglages. Vérifiez, dans l'ordre : les droits du dossier `~/.config/paresia` et du fichier (refaites les commandes de droits de l'[étape 5](#5-configurer-lapplication)) ; avec `ls -ld`, qu'ils vous appartiennent et qu'aucun des deux n'est un lien symbolique ; la syntaxe du fichier (ligne sans `=`, clé ou section en double, section `[DEFAULT]`, interdite) ; sa taille, si le fichier est anormalement gros.
- **Message « Configuration invalide » suivi d'un nom de réglage** : relisez ce réglage dans le fichier de l'étape 5 (chemin non absolu, adresse `url` avec un chemin ou un `/` final, langue qui n'est pas de la forme `fr-FR`).
- **« Connexion SSH impossible ou interrompue »** : vérifiez, dans l'ordre : que l'agent détient la clé (`ssh-add -L`, étape 3), que la clé de yang est enregistrée (étape 4), que la clé est autorisée sur yang (étape 7), que yang est joignable sur le port 22.
- **Signature impossible** : l'agent est absent de ce terminal (`echo "$SSH_AUTH_SOCK"` vide) ou ne connaît pas la clé : relancez l'étape 3, puis l'application depuis ce terminal.
- **Autre message de la fenêtre** : la liste des messages est dans `paresia-admin(1)`, section DIAGNOSTICS ; le dépannage des démons de yang est dans [Journaux, métriques, dépannage](Journaux-metriques-depannage.md).

## À venir

- Installation automatique du client, qui pilotera yin et yang par SSH (prévue pour la 1.0, voir [INSTALL.md](../../INSTALL.md)).
- Pages d'administration du relais, du bunker et du journal légal dans la fenêtre : voir [Premier usage](Premier-usage.md).
