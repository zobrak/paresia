# Architecture et sécurité expliquées simplement

Version du document : 0.1.19 · 2026-11-08 · [Accueil](Accueil.md)

Référence technique : [architecture](../architecture.md), [cahier des charges](../cahier-des-charges.md), [SECURITY](../../SECURITY.md).

## Vue d'ensemble

```
navigateur ──HTTPS──► pare-feu (HAProxy) ──► lighttpd ──► Romulus ──┬──► bunkerd
                                                                    ├──► Nisaba (journal légal)
                                                                    └──► tunnel SSH ──► Remus ──► strfry
application ──SSH──► pollux-session ──► Pollux ◄──► Romulus
                                          └──► tunnel SSH ──► Castor
```

Quatre machines ou rôles : `poste client` (l'application de l'administrateur), `pare-feu` (le reverse proxy, hors Paresia), `backend-admin` (yang) et `backend-relais` (yin). Les noms sont génériques ; chez vous, ils portent vos noms.

## Une session de présence, pas à pas

1. L'application de l'administrateur ouvre une session SSH vers `backend-admin`, sur un compte `app` qui ne sert qu'à cela. La clé SSH reste dans un agent SSH (elle ne passe pas par l'application).
2. Le serveur envoie un **défi** (une suite aléatoire) ; l'application le signe avec la clé SSH (format SSHSIG) : c'est la **preuve de possession** de la clé. Le défi vaut 60 s par défaut et ne sert qu'une fois.
3. Si la signature correspond à une clé autorisée, Romulus émet un **jeton** aléatoire, renvoyé à l'application par la session SSH.
4. Chaque commande d'administration porte ce jeton. Sans jeton, ou avec un jeton inconnu : refus.
5. Toutes les 30 secondes, l'application envoie un « ping » : c'est le battement. Pollux le relaie à Castor.
6. À la fin de la session SSH (fermeture, veille, coupure), le jeton est détruit et le robinet se referme.

Plusieurs sessions simultanées sont possibles, chacune avec son propre jeton.

## Les services greffés de Romulus

Romulus ne sait pas, par lui-même, à quels services il parle. Chaque service (bunkerd, le journal légal, le relais) est décrit par un petit fichier texte de **déclaration**, `paresia-yang-<nom>.toml`, posé dans `/usr/local/lib/paresia/romulus/services/` (cinq fichiers livrés ; des déclarations locales sont possibles dans `/etc/paresia/romulus/services.d/`). Une déclaration dit : quel domaine d'actions, quelle section de configuration, quelles actions et quels paramètres, quels codes d'erreur le service peut renvoyer.

Ce que cela change pour vous :

- **Sans déclaration, pas de route.** Une section de configuration d'un service dont la déclaration n'est pas installée est refusée, et Romulus ne démarre pas (code 78). Le script d'installation de `backend-admin` pose les cinq déclarations (dont celle de l'interface web, qui n'ouvre aucune route).
- **Les déclarations sont des données, jamais du code**, et sont contrôlées comme des programmes : propriétaire root, pas d'écriture pour les autres, pas de lien symbolique. Une déclaration livrée défectueuse empêche le démarrage ; une déclaration locale défectueuse est ignorée et signalée dans le journal.
- **L'identité du service est toujours vérifiée.** Pour chaque service, la configuration donne le socket **et** le numéro d'utilisateur (uid) du compte attendu en face. Un socket sans uid est refusé au démarrage : Romulus ne parle jamais à un processus dont il n'a pas vérifié l'identité (`SO_PEERCRED`).
- **Un service peut être facultatif.** C'est le cas du journal légal (Nisaba) : sans sa section, ses actions répondent « non disponible » (501).

Référence : page de manuel `paresia-romulus(8)`, [développement](../developpement.md), § 6.3.

## Les pages des greffons dans l'application

L'application d'administration ne connaît aucun produit : ni le relais, ni le bunker, ni le journal légal. Chaque greffon installé sur le serveur apporte ses propres pages. Au démarrage, la vue web lit un petit index (`/admin/greffons/index.json`) qui liste les greffons et leurs pages, charge leurs textes (français et anglais) puis le script de chaque page, et construit le menu.

Ce que cela change pour vous :

- **Un greffon installé est du code d'administration.** Son script s'exécute dans la page avec les mêmes droits que l'application : n'installez que des greffons dont vous connaissez la provenance.
- **Un greffon défaillant ne bloque rien.** Index absent, texte invalide, script muet : le greffon ou la page est écarté et signalé dans la zone de diagnostic, les pages du noyau restent utilisables. Tout est borné dans le temps (10 secondes par fichier, 30 secondes pour l'ensemble).
- **Les textes d'un greffon ne remplacent jamais ceux de l'application** : chaque clé de texte d'un greffon porte son nom, et une collision fait refuser le greffon.

Référence : page de manuel `paresia-admin(1)`, [développement](../developpement.md), § 6.4.

## Le tunnel SSH

Un seul tunnel SSH permanent relie `backend-admin` à `backend-relais`. C'est l'unique flux réseau ajouté entre les deux : TCP 22, chiffré par SSH. Il porte deux sockets Unix (des « prises » locales, qui ne sont pas des ports réseau) : une vers Remus, une vers Castor.

Choix de sécurité :

- le compte `tunnel` côté relais n'a **pas de shell** (`command="/bin/false"`), n'accepte que la redirection de sockets, et seulement depuis l'adresse de `backend-admin` ;
- les sockets ne sont accessibles qu'à ce compte ; chaque démon vérifie qui l'appelle (`SO_PEERCRED`, l'identité que le noyau Linux atteste pour l'autre bout d'une socket Unix) ;
- rien n'écoute sur le réseau ni sur la boucle locale ;
- une limite d'OpenSSH fait que la clé du tunnel pourrait aussi ouvrir des connexions TCP depuis le relais : une règle **nftables** sur `backend-relais` l'interdit ;
- la clé du tunnel reste sur `backend-admin`, lisible par le seul compte du service ;
- l'empreinte de la clé d'hôte est vérifiée (`StrictHostKeyChecking yes`) : une clé inconnue est refusée.

## Le feu de Castor

Castor se comporte comme un feu de circulation, un par session de présence.

| Feu | Quand | Conséquence |
| --- | --- | --- |
| vert | un ping de Pollux est arrivé il y a moins de 35 s (30 s de battement + 5 s de marge, réglables) | Remus peut exécuter les commandes de cette session |
| rouge | pas de ping récent, ou Castor redémarré | les commandes sont refusées (`relay_light_red`) |
| fermé | la session a été fermée proprement | refus immédiat pendant 10 s |

Autrement dit : même si quelqu'un parvenait à parler à Remus, il ne ferait rien sans qu'une session de présence **vivante** soit attestée par le feu de Castor. Le relais décide lui-même de se fermer 35 s après le dernier battement.

## Le cloisonnement

- **Deux machines** : la compromission d'une machine ne donne pas l'autre. `backend-admin` ne joint le relais que par le tunnel ; l'application ne se connecte qu'à `backend-admin`.
- **Un compte par démon**, sans répertoire personnel sous `/home` (comptes sous `/var/lib/paresia-<compte>` ou `/nonexistent`), sans mot de passe.
- **Moindre privilège** : Remus s'exécute sous le compte `chef` avec un `sudo` limité à une liste fermée de commandes (générée à partir des manifestes des fonctions, jamais écrite à la main) ; chaque unité systemd est durcie (accès aux dossiers restreints).
- **Liste fermée d'opérations** : jamais de commande libre ; arguments vérifiés.
- **Aucun secret dans les journaux** : ni jetons, ni phrases secrètes, ni clés.
- **Aucun texte non filtré à l'écran** : l'interface n'insère jamais de texte reçu comme du HTML, et les démons nettoient les caractères de contrôle.
- **Refus par défaut** : à toute erreur, le choix de repli est le refus.

## Limites connues

Elles sont décrites honnêtement dans [SECURITY](../../SECURITY.md) (modèle de menace provisoire). Par exemple : le plugin d'écriture de strfry ne valide pas l'adresse de connexion qu'il reçoit. Votre reverse proxy DOIT donc écraser l'en-tête d'adresse du client, et le port de strfry ne doit être publié que vers ce proxy.

## À venir

- Modèle de menace complet ([SECURITY](../../SECURITY.md), provisoire).
- Chiffrement TLS du tronçon pare-feu vers `backend-admin` (prévu « plus tard » au cahier).
- Privilèges par fonction sans `sudo` (socket systemd par fonction), avant l'ouverture des greffons aux tiers, après la 1.0.
