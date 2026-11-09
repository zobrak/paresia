# Régler HAProxy pour Paresia

Version du document : 0.1.19 · 2026-11-09 · [Accueil](Accueil.md)

Suivi, 2026-11-09 : première version de la page ; elle reprend l'ancienne étape 10 de [Installer et configurer lighttpd](Installer-lighttpd.md) ; numéro du document inchangé (aucun numéro donné).

Cette page ne présente pas HAProxy : elle dit seulement **ce que Paresia exige du frontal** (le proxy inverse HAProxy placé devant yang et devant le relais). Paresia ne livre aucune configuration de HAProxy et ne l'installe pas ; les exigences et leurs sources sont dans [Serveur web](../serveur-web.md).

**Alpha : à essayer sur une machine jetable. Les réglages et les résultats des contrôles ci-dessous sont établis par le [manuel de HAProxy 3.0](https://docs.haproxy.org/3.0/configuration.html) et observés lors d'un essai réel. Seule la sortie de `haproxy -c` n'a pas été observée : elle reste à confirmer.** Les noms et adresses (`yang`, `bunker.example.org`, `192.0.2.10`, `192.0.2.254`) sont des exemples génériques (RFC 2606, RFC 5737).

## Sommaire

1. [Avant de commencer](#avant-de-commencer)
2. [Le backend de yang : l'adresse du client](#1-le-backend-de-yang--ladresse-du-client)
3. [Le backend de yang : ce qu'il ne faut pas poser](#2-le-backend-de-yang--ce-quil-ne-faut-pas-poser)
4. [Poser `Access-Control-Allow-Origin` dans les relais seulement](#3-poser-access-control-allow-origin-dans-les-relais-seulement)
5. [L'adresse du frontal vue par lighttpd](#4-ladresse-du-frontal-vue-par-lighttpd)
6. [Recharger et contrôler](#5-recharger-et-contrôler)
7. [Si HAProxy est géré par une interface](#6-si-haproxy-est-géré-par-une-interface)
8. [Retour arrière](#retour-arrière)

## Avant de commencer

Il vous faut :

- un HAProxy déjà installé et qui fournit l'adresse `https://` de yang (le client exige du `https://`) ;
- lighttpd réglé sur yang : [Installer et configurer lighttpd](Installer-lighttpd.md), étapes 1 à 8 ;
- un accès en écriture à la configuration de HAProxy, et la commande de contrôle de HAProxy (`haproxy -c -f <fichier>`).

Machine pour toutes les étapes de configuration : **le frontal**. Les contrôles de l'étape 5 se lancent depuis un poste que le frontal autorise.

### À personnaliser obligatoirement

| Valeur | Où | Exemple du guide | Ce qu'il faut mettre |
| --- | --- | --- | --- |
| nom de la section de yang | extraits des étapes 1 et 2 | `backend yang` | le nom de votre section `backend` qui relaie vers yang |
| nom d'hôte | contrôles de l'étape 5 | `bunker.example.org` | l'adresse web de l'administration (la même que dans le client, sans `https://`) |

## 1. Le backend de yang : l'adresse du client

Machine : le frontal. Dans la section `backend` qui relaie vers yang, ajoutez la ligne ci-dessous (le reste de la section est le vôtre : ne le changez pas).

```
backend yang
    http-request set-header X-Paresia-Client-IP %[src]
```

Ce que fait la ligne : elle écrit l'adresse réelle du client (`%[src]`, l'adresse source de la connexion que HAProxy reçoit) dans l'en-tête `X-Paresia-Client-IP`. Avec `set-header`, toute valeur que le client aurait envoyée dans cet en-tête est **remplacée** : un client ne peut donc pas se faire passer pour une autre adresse. Romulus lit cette adresse (réglage `client_ip_header` de `paresia.conf`) et la journalise. Sans cet en-tête, l'adresse est absente et Romulus journalise une adresse de repli.

## 2. Le backend de yang : ce qu'il ne faut pas poser

Machine : le frontal. Rien à écrire : cette étape se lit. Dans le backend de yang, ne posez pas :

- **`option forwardfor`**, et aucun en-tête `X-Forwarded-For`. Romulus ne lit que l'en-tête `X-Paresia-Client-IP` et ignore `X-Forwarded-For` (que lighttpd complète de toute façon) : un en-tête d'adresse de plus ne lui sert à rien. De plus, HAProxy ne documente pas l'ordre dans lequel `option forwardfor` et une règle `http-request` s'appliquent : ne combinez donc jamais les deux ;
- **`Access-Control-Allow-Origin`**. Les pages et l'API de yang sont servies par le même lighttpd, donc à la même adresse : le navigateur n'a pas besoin de cet en-tête, et l'ouvrir élargirait l'accès sans raison.

Ne laissez lighttpd joignable que depuis le frontal (pare-feu) : sinon un poste pourrait écrire lui-même `X-Paresia-Client-IP`.

## 3. Poser `Access-Control-Allow-Origin` dans les relais seulement

Machine : le frontal. Cette étape ne concerne que vous si votre frontal pose déjà `Access-Control-Allow-Origin` pour un relais Nostr.

**Constat de l'essai réel.** Une ligne `http-response set-header Access-Control-Allow-Origin …` écrite dans une section `frontend` s'applique à **tous les sites** de ce frontend, yang compris. La retirer dans le backend de yang (`http-response del-header …`) **ne suffit pas** : HAProxy applique les règles de réponse du backend **avant** celles du frontend, donc la ligne du frontend repose l'en-tête après le retrait. Le [manuel de HAProxy 3.0](https://docs.haproxy.org/3.0/configuration.html), à la section `http-response`, le dit : « the backend rules are applied first, followed by the frontend's rules ».

**Remède.** Retirez la ligne du `frontend` et posez-la seulement dans le backend de chaque relais :

```
backend relais
    http-response set-header Access-Control-Allow-Origin *
```

Le backend de yang n'en porte alors aucune. Cet en-tête est utile au relais : le protocole Nostr (NIP-11) demande aux relais d'accepter les requêtes venues d'autres sites, en envoyant notamment `Access-Control-Allow-Origin`. Veillez donc à ce qu'il ne soit pas perdu pour le relais en retirant la ligne du `frontend` : posez-la dans le backend du relais, et contrôlez-la à l'étape 5. Les exigences propres au relais (délais, adresse du client) sont dans [Installer le relais strfry](Installer-strfry.md#ce-que-le-frontal-doit-faire-pour-le-relais).

## 4. L'adresse du frontal vue par lighttpd

Machine : yang. Aucune commande : cette étape se lit. Le filtre `remoteip` de lighttpd (étape 2 de [Installer et configurer lighttpd](Installer-lighttpd.md#2-sur-yang--écrire-la-configuration)) n'admet que l'adresse du frontal **telle que yang la voit**, côté réseau interne : jamais l'adresse WAN ; `127.0.0.1` si HAProxy tourne sur yang. Si cette adresse n'est pas la bonne, lighttpd répond `403` à tout. La valeur se règle dans le [tableau « À personnaliser » du guide lighttpd](Installer-lighttpd.md#à-personnaliser-obligatoirement).

## 5. Recharger et contrôler

Machine : le frontal pour la syntaxe et le rechargement.

```
haproxy -c -f /etc/haproxy/haproxy.cfg
```

Résultat attendu (non observé lors de l'essai : à confirmer) : le code de sortie zéro (`echo $?` affiche `0`) et aucune erreur ; en cas d'erreur, ne rechargez pas. Le chemin du fichier est celui d'une installation Debian ordinaire : adaptez-le au vôtre. Rechargez ensuite HAProxy avec la méthode de votre installation.

Contrôles. **À lancer depuis un poste autorisé par le frontal, pas depuis yang** : depuis yang, la commande peut ne rien afficher. Les commandes emploient `-k` (le certificat n'est pas vérifié : c'est un essai).

**À personnaliser : remplacez `bunker.example.org` par votre nom d'hôte.**

Contrôle 1, le catalogue répond par lighttpd, à travers le frontal :

```
curl -skI https://bunker.example.org/admin/greffons/index.json
```

Résultat attendu (l'ordre des lignes peut varier) :

```
HTTP/2 200
content-type: application/json
server: lighttpd/1.4.79
```

Contrôle 2, le backend de yang ne pose pas `Access-Control-Allow-Origin` :

```
curl -skI https://bunker.example.org/admin/ | grep -ic access-control-allow-origin
```

Résultat attendu :

```
0
```

Le `0` est le nombre de lignes `access-control-allow-origin` reçues. Autre chiffre : l'en-tête est encore posé quelque part (relisez l'étape 3, et cherchez une ligne dans le `frontend`).

Contrôle 3, le relais, lui, pose `Access-Control-Allow-Origin` :

**À personnaliser : remplacez `relais.example.org` par l'adresse publique de votre relais.**

```
curl -skI -H 'Accept: application/nostr+json' https://relais.example.org/
```

Résultat attendu : parmi les lignes reçues,

```
access-control-allow-origin: *
```

Le frontal est prêt. La suite est le client : [Installer le client](Installer-client.md).

## 6. Si HAProxy est géré par une interface

Si votre HAProxy est géré par une interface graphique, ces lignes vont dans le champ de configuration libre du pool concerné.

## Retour arrière

Machine : le frontal. Retirez du backend de yang la ligne `http-request set-header X-Paresia-Client-IP %[src]`, puis, si vous aviez déplacé `Access-Control-Allow-Origin`, remettez la ligne où elle était. Contrôlez avec `haproxy -c -f <votre fichier>` et rechargez. Sans cette ligne, yang n'a plus l'adresse réelle du client.
