# Premier usage

Version du document : 0.1.19 · 2026-11-08 · [Accueil](Accueil.md)

Référence : [exploitation](../exploitation.md), [essai de présence](../../deploy/essai-presence.md), pages de manuel `paresia-admin(1)`, `paresia-pollux(8)`, `paresia-castor(8)`, `nisaba-ctl(1)`.

Suivi, 2026-11-09 : chemin le plus court placé en tête, description de l'interface séparée ; numéro du document inchangé.

Cette page décrit ce que vous pouvez faire **aujourd'hui**, état alpha. L'application de bureau n'est pas encore complète : voir la fin de la page.

## Le chemin le plus court vers un premier résultat

Prérequis : l'installation de [INSTALL.md](../../INSTALL.md) est terminée (étapes [1](../../INSTALL.md#1-sur-yang--installer-git) à [15](../../INSTALL.md#15-sur-yang--autoriser-la-clé-dun-administrateur)), et votre poste a PyQt6 avec QtWebEngine, un agent SSH actif qui détient votre clé, et `openssh-client` ; l'installation du client est décrite dans [Installer le client](Installer-client.md).

1. Sur yang, contrôlez que les démons tournent : `systemctl status pollux.service romulus.service paresia-tunnel.service` doit montrer trois unités `active`.
2. Sur yin, contrôlez de même : `sudo /usr/bin/systemctl status castor.service remus.service` doit montrer deux unités `active`.
3. Sur votre poste, lancez l'application : `python3 -m admin.app`.
4. Dans son menu, choisissez « Ouvrir l'administration » : l'indicateur passe au vert.
5. Ouvrez la page « État de Paresia » : elle affiche la version et la liste des démons.

Résultat : une session de présence ouverte et la lecture de l'état de votre installation. Si une étape échoue, la section suivante la détaille, puis [le dépannage](Journaux-metriques-depannage.md).

# Description détaillée

## 1. Démarrer les démons

Les scripts d'installation démarrent déjà les unités qu'ils posent ; les commandes ci-dessous servent à les relancer à la main (par exemple après un redémarrage de la machine, si vous n'avez pas utilisé `--activer`). Les unités se démarrent avec `start`. L'activation au démarrage du système (`enable`) ne se fait qu'après vérification. Sur `backend-admin` (root), retirez le préfixe `sudo` des commandes.

Sur `backend-relais`, dans cet ordre conseillé (l'ordre n'est pas imposé : chaque démon se reconnecte à la demande) :

```
sudo /usr/bin/systemctl start castor.service
sudo /usr/bin/systemctl start remus.service
sudo /usr/bin/systemctl status castor.service remus.service
```

Sur `backend-admin` :

```
sudo /usr/bin/systemctl start pollux.service
sudo /usr/bin/systemctl start romulus.service
sudo /usr/bin/systemctl start paresia-tunnel.service
sudo /usr/bin/systemctl status pollux.service romulus.service paresia-tunnel.service
```

Les deux couples de jumeaux répondent `peer_unavailable` si leur pair n'est pas encore là : ce n'est pas une panne, c'est l'attente.

## 2. Vérifier que le tunnel est monté

Sur `backend-admin` :

```
ss -xl | grep paresia-tunnel
```

Vous devez voir deux sockets : `/run/paresia-tunnel/romulus/remus.sock` et `/run/paresia-tunnel/pollux/castor.sock`. Si elles manquent : [dépannage](Journaux-metriques-depannage.md).

## 3. Ouvrir une session de présence

L'application officielle (Paresia-admin) ouvre la session : `ssh -T app@backend-admin`, signature du défi par l'agent SSH, réception du jeton. Cette application est **commencée** : le socle, la session de présence (avec la signature du défi par `ssh-keygen`, la clé privée restant dans l'agent SSH), la lecture de la clé publique et la **fenêtre principale** sont écrits, ainsi que trois pages du noyau ; les pages d'administration des greffons ne le sont pas. Elle se lance par `python3 -m admin.app` (option `--config <fichier>`) et exige PyQt6 avec QtWebEngine.

La fenêtre a un menu : « Ouvrir l'administration », « Fermer l'administration », « Ligne de clé à remettre » (la ligne à faire ajouter au fichier des clés autorisées du serveur, affichée dans un champ en lecture seule) et « Quitter ». Un indicateur montre trois états : fermée (gris), ouverte (vert), perdue (rouge). Si la session est perdue, la fenêtre vous propose de la rouvrir ; elle ne le fait jamais seule. La fenêtre ne navigue que vers l'adresse de votre serveur ; toute autre adresse est refusée avec un message. Une fois la session ouverte, elle affiche les pages du noyau (voir [Les pages du noyau](#les-pages-du-noyau)) et celles que les greffons installés déclarent (aucun greffon livré n'en apporte pour l'instant). Le poste client doit avoir un agent SSH actif (`SSH_AUTH_SOCK`) qui détient votre clé, et l'option `ssh_keygen` de la configuration du client doit désigner l'outil `ssh-keygen`.

En attendant, la procédure [essai de présence](../../deploy/essai-presence.md) fait un essai réel de la présence avec un **client de banc** : elle ouvre une session, obtient un jeton et vérifie l'enchaînement Pollux, tunnel, Castor. Lisez-la entièrement avant de la lancer ; elle avertit avant chaque étape risquée.

Avant la première session, il faut que votre **clé publique d'administrateur** figure dans le fichier des clés autorisées du compte `app` (`/var/lib/paresia-app/.ssh/authorized_keys`, propriété de root, dans l'exemple de configuration). Une gestion des utilisateurs, où Romulus tient ce fichier à votre place, est prévue (voir ci-dessous).

## Les pages du noyau

Trois pages sont livrées avec l'application ; elles ne dépendent d'aucun produit (strfry, bunker, journal légal) et ne montrent jamais de secret. Rien n'est actualisé tout seul : chaque section a un bouton « Actualiser ».

- **État de Paresia.** Le *résumé* : version, durée de fonctionnement, sessions ouvertes, niveau de détail du journal d'activité, et la liste des démons du noyau avec l'état de leurs métriques. En choisissant un démon, vous voyez ses *métriques* (désactivées par défaut : la page vous le rappelle quand il n'y en a pas) et sa *configuration* en lecture seule. Une valeur que le serveur masque s'affiche « masquée » ; la page ne la reconstitue jamais.
- **Journaux de Paresia.** Le journal d'activité de Romulus : qui a fait quoi, quand, avec quel résultat. Vous choisissez le nombre d'entrées (10, 50, 100 ou 200), le niveau de détail (1 à 3) et, si vous voulez, un domaine. Un niveau plus élevé que celui que le serveur enregistre n'a pas d'entrées : la page le signale, ainsi qu'un résultat tronqué.
- **Catalogue des actions.** Les services déclarés sur le serveur et les actions que chacun annonce, avec leur description (privilège, délai, paramètres, erreurs). Vous pouvez lancer une action **sans paramètre**, après une confirmation. Prudence : le catalogue ne dit pas si une action ne fait que lire ou si elle modifie quelque chose ; la confirmation vous avertit que l'action peut modifier le serveur. Les actions avec paramètres s'affichent mais ne se lancent pas encore depuis cette page.

Si le serveur répond quelque chose d'inattendu, la page affiche « Réponse inattendue (données invalides) » au lieu de montrer des données douteuses. Référence : page de manuel `paresia-admin(1)`, section PAGES DU NOYAU.

## 4. Regarder le feu de Castor

Pendant qu'une session est ouverte, le journal de Castor montre `light_green` ; quand le dernier ping a plus de 35 s, `light_expired`.

```
sudo /usr/bin/journalctl -u castor.service -o cat -f
```

## 5. Interroger Nisaba

Si Nisaba tourne (voir [Nisaba et le bunker](Nisaba-et-bunker.md)) :

```
sudo python3 -m server.nisaba.ctl status
```

La commande `nisaba-ctl` est décrite dans `nisaba-ctl(1)`.

## À venir

- Pages web du bunker, du journal légal et du relais (apportées par les greffons) dans la fenêtre de Paresia-admin.
- Marquer les actions du catalogue qui ne font que lire, pour ne demander confirmation que pour les autres.
- Gestion des utilisateurs : ajout et retrait d'administrateurs et de leurs clés par un module de Paresia-admin ; privilège « utilisateurs ».
- Capture d'écran et parcours pas à pas de l'interface.
