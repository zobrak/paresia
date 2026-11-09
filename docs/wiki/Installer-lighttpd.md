# Installer et configurer lighttpd

Version du document : 0.1.19 · 2026-11-09 · [Accueil](Accueil.md)

Suivi, 2026-11-09 : première version de la page ; numéro du document inchangé (aucun numéro donné).

Suivi, 2026-11-09 : l'étape 10 (frontal HAProxy) est remplacée par un renvoi vers [Régler HAProxy pour Paresia](Installer-haproxy.md) ; numéro du document inchangé (aucun numéro donné).

Cette page prépare **yang** (la machine d'administration, `backend-admin` dans les noms de scripts et de dossiers) : elle installe et règle le serveur web **lighttpd**. Elle suit un seul fil. Source de vérité des réglages : [Serveur web](../serveur-web.md) (exigences et extrait d'exemple repris tel quel ci-dessous).

**Alpha : à essayer sur une machine jetable. Cette page n'a pas encore été éprouvée de bout en bout sur une machine réelle : les sorties marquées « à relever » seront confirmées à l'essai.** Les noms et adresses (`yang`, `bunker.example.org`, `192.0.2.10`, `192.0.2.254`) sont des exemples génériques (RFC 2606, RFC 5737).

## Ce que vous obtenez

À la fin de ce parcours, lighttpd sert, sur yang, les pages d'administration (`/admin/`) et transmet les appels de l'application (`/api/admin/`) au démon Romulus. Les pages et l'API partagent ainsi la même adresse, ce que le navigateur intégré et Romulus exigent.

**Pourquoi ce serveur est indispensable.** Romulus n'écoute sur aucun port réseau : il n'a qu'une socket Unix, locale à yang. Sans serveur web, un poste distant ne peut donc ni afficher les pages ni joindre l'API. Paresia n'installe ni ne configure ce serveur ; cette page vous guide pour le faire à la main. L'installation automatique arrive en v0.2.

## Sommaire

1. [Installer lighttpd](#1-sur-yang--installer-lighttpd)
2. [Écrire la configuration](#2-sur-yang--écrire-la-configuration)
3. [Comprendre et régler chaque réglage](#3-sur-yang--comprendre-et-régler-chaque-réglage)
4. [Variante : pas de frontal](#4-variante--pas-de-frontal)
5. [Activer la configuration](#5-sur-yang--activer-la-configuration)
6. [Retirer la page par défaut](#6-sur-yang--retirer-la-page-par-défaut)
7. [Contrôler la syntaxe](#7-sur-yang--contrôler-la-syntaxe)
8. [Redémarrer lighttpd](#8-sur-yang--redémarrer-lighttpd)
9. [Vérifier de bout en bout](#9-vérifier-de-bout-en-bout)
10. [Régler le frontal HAProxy](#10-sur-le-frontal--régler-haproxy)
11. [Retour arrière](#retour-arrière)
12. [Annexe : réserves](#annexe--réserves)

## Avant de commencer

Il vous faut :

- **yang installé** : les étapes 1 à 14 d'[INSTALL.md](../../INSTALL.md) sont terminées (le dossier `/usr/local/share/paresia/web/` et la socket de Romulus existent) ;
- un **frontal** : un proxy inverse HAProxy, placé devant yang, qui fournit l'adresse `https://` (le client exige une adresse `https://`). Le frontal sert aussi à transmettre l'adresse du client à Romulus. Sans frontal, voir la [variante de l'étape 4](#4-variante--pas-de-frontal) et sa limite ;
- un compte ordinaire, membre du groupe `sudo`, sur yang ;
- l'adresse IP du frontal, vue de yang.

Les étapes 1 à 8 se lancent sur yang, avec ce compte. L'étape 9 se lance depuis le frontal, l'étape 10 sur le frontal.

### À personnaliser obligatoirement

| Valeur | Où | Exemple du guide | Ce qu'il faut mettre |
| --- | --- | --- | --- |
| adresse du frontal | `90-paresia.conf`, ligne `$HTTP["remoteip"]` (étapes 2 et 3), commandes de l'étape 9 | `192.0.2.254` | l'adresse que yang voit côté réseau interne pour le frontal, **jamais l'adresse WAN** ; `127.0.0.1` si le proxy tourne sur yang ; points échappés (`\.`) dans la ligne de configuration |
| nom d'hôte | `90-paresia.conf`, ligne `$HTTP["host"]` (étapes 2 et 3), commandes de l'étape 9 | `bunker.example.org` | le nom de l'adresse web de l'administration (le même que `url` du client, sans `https://`), avec ses points échappés (`\.`) |
| adresse de yang | commandes de l'étape 9 | `192.0.2.10` | l'adresse IP de yang |

## 1. Sur yang : installer lighttpd

Machine : yang.

```
sudo apt install -y lighttpd
```

```
lighttpd -v
```

Résultat attendu : une ligne qui commence par `lighttpd/1.4.` (Debian 13 fournit la 1.4.79 ; la version minimale est la 1.4.51). Version exacte à relever à l'essai.

```
systemctl is-active lighttpd
```

Résultat attendu :

```
active
```

Lighttpd est installé avec la configuration par défaut de Debian ; la suivante la complète sans la remplacer. Étape suivante : écrire la configuration de Paresia.

## 2. Sur yang : écrire la configuration

Machine : yang.

Créez le fichier `/etc/lighttpd/conf-available/90-paresia.conf` avec votre éditeur (par exemple `sudoedit /etc/lighttpd/conf-available/90-paresia.conf`), avec le contenu complet ci-dessous. C'est l'extrait d'exemple de [Serveur web](../serveur-web.md), avec deux écarts que l'essai sur Debian 13 a rendus nécessaires, car la configuration Debian par défaut définit déjà ces réglages : `server.http-parseopts` s'écrit avec `:=` (avec `=`, lighttpd refuse `Duplicate config variable`), et la ligne `mimetype.assign` est retirée (Debian déclare déjà ces types ; la reposer donne `Duplicate array-key`). Le document de référence garde l'extrait d'origine.

**À personnaliser : remplacez `192.0.2.254` (ligne `remoteip`) par l'adresse du frontal et `bunker.example.org` (ligne `host`) par votre nom d'hôte. Gardez les `\.` entre les nombres et les mots : ils sont indispensables.**

```
server.modules += ( "mod_access", "mod_setenv", "mod_alias", "mod_proxy", "mod_accesslog" )

server.stream-request-body  = 0
server.stream-response-body = 2
server.max-request-size     = 64
server.http-parseopts := (
    "header-strict" => "enable", "host-strict" => "enable", "host-normalize" => "enable",
    "url-normalize-unreserved" => "enable", "url-normalize-required" => "enable",
    "url-ctrls-reject" => "enable", "url-path-2f-reject" => "enable", "url-path-2f-decode" => "disable",
    "url-path-dotseg-remove" => "enable", "url-invalid-utf8-reject" => "enable" )

accesslog.format   = "%h %t %m %U %>s %b"
accesslog.escaping = "default"

$HTTP["remoteip"] !~ "^192\.0\.2\.254$" {
    url.access-deny = ( "" )
}

$HTTP["host"] !~ "^bunker\.example\.org$" {
    url.access-deny = ( "" )
}

alias.url += (
    "/admin/greffons/" => "/usr/local/share/paresia/web/greffons/",
    "/admin/"          => "/usr/local/share/paresia/web/" )

$HTTP["url"] =~ "^/admin/" {
    dir-listing.activate         = "disable"
    static-file.disable-pathinfo = "enable"
    index-file.names             = ( "index.html" )
    setenv.set-response-header  += ( "X-Content-Type-Options" => "nosniff" )
    setenv.add-response-header  += ( "X-Frame-Options" => "DENY",
                                     "Content-Security-Policy" => "frame-ancestors 'none'" )
}

$HTTP["url"] =~ "^/api/admin/" {
    proxy.server = ( "" => ( ( "host" => "/run/paresia-romulus/romulus-http.sock" ) ) )
}
```

Contrôlez que le fichier existe et que les deux valeurs sont les vôtres :

```
grep -nE 'remoteip|"host"' /etc/lighttpd/conf-available/90-paresia.conf
```

Résultat attendu (votre adresse et votre nom à la place des exemples) :

```
14:$HTTP["remoteip"] !~ "^192\.0\.2\.254$" {
18:$HTTP["host"] !~ "^bunker\.example\.org$" {
```

Le fichier est écrit. Étape suivante : comprendre chaque réglage, pour savoir ce que vous pouvez changer.

## 3. Sur yang : comprendre et régler chaque réglage

Machine : yang. Aucune commande : cette étape se lit. Seuls deux réglages se personnalisent (les lignes `remoteip` et `host`, étape 2) ; **les autres se laissent tels quels**.

| Réglage | À quoi il sert (en clair) | Se modifie ? |
| --- | --- | --- |
| `server.modules += (…)` | ajoute à lighttpd les cinq « briques » dont Paresia a besoin : contrôle d'accès, en-têtes, redirection de chemins, relais vers Romulus, journal d'accès. Le `+=` ajoute sans effacer ce que Debian a déjà chargé | non |
| `server.stream-request-body = 0` | lighttpd reçoit la requête en entier avant de la transmettre à Romulus, qui refuse les envois découpés | non |
| `server.stream-response-body = 2` | transmet la réponse de Romulus au fur et à mesure : indispensable pour le flux d'événements (sans cela, il ne démarre jamais) | non |
| `server.max-request-size = 64` | taille maximale d'une requête, en kio : au-delà, elle est refusée | non (sauf besoin précis) |
| `server.http-parseopts :=` | rend lighttpd strict sur les adresses et les en-têtes mal formés (`..`, `%2F`, caractères de contrôle, texte invalide) et refuse les `%2F` : Romulus compare le chemin exactement. `url-path-2f-decode` est mis à `disable` explicitement, sinon lighttpd refuse de démarrer. Le `:=` remplace la valeur déjà définie par Debian (avec `=`, lighttpd refuse : `Duplicate config variable`) | non |
| `accesslog.format` | ce qui est écrit dans le journal d'accès : adresse, heure, méthode, chemin **sans** la chaîne de requête, code, taille. Aucun cookie, aucun jeton n'y figure | non |
| `accesslog.escaping` | neutralise les caractères de contrôle dans le journal | non |
| types de fichiers (`.html`, `.js`, `.json`) | pas de ligne dans notre fichier : la configuration Debian déclare déjà ces types, qui disent au navigateur la nature de chaque fichier ; on le contrôle à l'étape 9 | non |
| `$HTTP["remoteip"] !~ …` | refuse toute requête qui ne vient pas du frontal : lighttpd n'est joignable que par lui | **oui** : l'adresse du frontal |
| `$HTTP["host"] !~ …` | refuse toute requête dont le nom d'hôte n'est pas le vôtre : protège contre le « rebinding DNS » (un site hostile qui se fait passer pour votre adresse) | **oui** : votre nom d'hôte |
| `alias.url += (…)` | relie `/admin/` et `/admin/greffons/` aux dossiers du disque (`/usr/local/share/paresia/web/`) ; le chemin le plus long vient en premier | non |
| `dir-listing.activate = "disable"` | n'affiche jamais la liste des fichiers d'un dossier. À garder : `lighttpd -tt` affiche alors normalement `WARNING: unknown config-key: dir-listing.activate (ignored)` (le module de liste de dossiers n'est pas chargé) ; la ligne s'applique dès que le module est chargé | non |
| `static-file.disable-pathinfo = "enable"` | empêche de servir `fichier.js/suite` comme si c'était `fichier.js` (obligatoire sur lighttpd 1.4.79) | non |
| `index-file.names` | la page servie quand on ouvre un dossier : `index.html` | non |
| `setenv.set-response-header` et `add-response-header` | ajoutent aux pages des en-têtes de protection : le navigateur ne devine pas le type des fichiers, et la page ne peut pas être affichée dans un cadre d'un autre site | non |
| `proxy.server` | envoie les appels `/api/admin/` à la socket Unix de Romulus (`/run/paresia-romulus/romulus-http.sock`) | non (sauf si vous avez changé `[romulus.http] socket`) |

Pourquoi `remoteip` porte l'adresse du frontal et non celle des utilisateurs : le frontal parle à lighttpd, qui ne voit alors que **son** adresse. C'est elle que `remoteip` autorise. L'adresse du vrai client est transmise à part, par un en-tête (voir [Régler HAProxy pour Paresia](Installer-haproxy.md)).

Les réglages sont compris. Étape suivante : le cas sans frontal, ou l'activation (étape 5).

## 4. Variante : pas de frontal

Machine : yang. À lire seulement si vous n'avez pas de frontal HAProxy.

**Limite.** Le client exige une adresse `https://`. Cette configuration ne fournit **pas** TLS (le chiffrement) : il faut donc un frontal qui le fournit. Sans lui, le client Paresia-admin ne se connecte pas ; cette variante ne convient qu'à un essai de la page en `http://`, sans le client.

Sans frontal, personne ne pose `X-Paresia-Client-IP` : un poste pourrait la forger lui-même, et Romulus la lit sur sa socket quoi qu'il arrive. Il faut la supprimer côté lighttpd. Dans le fichier de l'étape 2, remplacez le bloc `/api/admin/` par ceci (une ligne ajoutée) :

```
$HTTP["url"] =~ "^/api/admin/" {
    setenv.set-request-header = ( "X-Paresia-Client-IP" => "" )
    proxy.server = ( "" => ( ( "host" => "/run/paresia-romulus/romulus-http.sock" ) ) )
}
```

Une valeur vide supprime l'en-tête (lighttpd 1.4.46 et plus). Remplacez aussi l'adresse de la ligne `remoteip` par celle du poste qui se connecte. Ce réglage de neutralisation est établi par la documentation de lighttpd, non éprouvé ; sans frontal, l'adresse du client n'est de toute façon pas fiable.

Étape suivante : activer la configuration.

## 5. Sur yang : activer la configuration

Machine : yang.

```
sudo lighty-enable-mod paresia
```

Résultat attendu : la commande confirme l'activation du module `paresia` et vous invite à recharger lighttpd (ignorez : l'étape 8 redémarre complètement ; texte exact à relever à l'essai). Elle met le fichier de `conf-available/` à la disposition de lighttpd, dans `conf-enabled/`.

```
ls -l /etc/lighttpd/conf-enabled/ | grep paresia
```

Résultat attendu : une ligne `90-paresia.conf -> ../conf-available/90-paresia.conf` (lien symbolique ; forme exacte à relever à l'essai).

La configuration est activée, pas encore appliquée. Étape suivante : retirer la page par défaut.

## 6. Sur yang : retirer la page par défaut

Machine : yang. Sous Debian 13, le paquet active `/etc/lighttpd/conf-enabled/99-unconfigured.conf` : lighttpd sert alors sa page « site non configuré » à la place de la vôtre. Désactivez-la :

```
sudo lighty-disable-mod unconfigured
```

Résultat attendu : la commande confirme la désactivation (texte exact à relever à l'essai).

```
ls -l /etc/lighttpd/conf-enabled/
```

Résultat attendu : seul `90-paresia.conf` y reste (lien vers `../conf-available/90-paresia.conf` ; sortie exacte à relever à l'essai) :

```
lrwxrwxrwx 1 root root 33 nov.  9 00:12 90-paresia.conf -> ../conf-available/90-paresia.conf
```

Si d'autres lignes subsistent, notez-les : elles viennent de la configuration Debian et ne sont pas touchées par cette page.

La page par défaut est retirée. Étape suivante : contrôler la syntaxe.

## 7. Sur yang : contrôler la syntaxe

Machine : yang. À faire **avant** tout redémarrage.

```
sudo lighttpd -tt -f /etc/lighttpd/lighttpd.conf; echo "code : $?"
```

Résultat attendu (essai sur Debian 13) : cette seule ligne d'avertissement, puis le code zéro :

```
WARNING: unknown config-key: dir-listing.activate (ignored)
code : 0
```

L'avertissement est normal : le module de liste de dossiers n'est pas chargé, la ligne `dir-listing.activate` s'appliquerait s'il l'était. Toute autre ligne, ou un code différent de zéro (par exemple `Duplicate config variable` ou `Duplicate array-key`), est une erreur : lisez l'[annexe](#annexe--réserves) avant de continuer. Ne redémarrez jamais sur une erreur.

La syntaxe est bonne. Étape suivante : redémarrer.

## 8. Sur yang : redémarrer lighttpd

Machine : yang. Un **redémarrage complet** (et non un simple rechargement) : une configuration Debian neuve ne prend pas les modules ajoutés par un rechargement.

```
sudo systemctl restart lighttpd
```

```
systemctl is-active lighttpd
```

Résultat attendu :

```
active
```

Lighttpd applique la configuration. Étape suivante : vérifier que tout répond comme prévu.

## 9. Vérifier de bout en bout

Machine : **le frontal** (ou toute machine dont l'adresse est celle autorisée à l'étape 2). Les requêtes viennent de l'adresse admise ; depuis une autre machine, y compris yang elle-même, la réponse est `403` : c'est le filtre `remoteip`, normal et voulu. Un `curl` lancé depuis yang reçoit donc `403` (sauf si l'adresse admise est `127.0.0.1`, proxy sur yang) : le contrôle réel passe par le frontal.

**À personnaliser : remplacez `192.0.2.10` par l'adresse de yang et `bunker.example.org` par votre nom d'hôte.** Les commandes emploient `--resolve` : `curl` joint yang par son adresse tout en envoyant le nom d'hôte attendu, sans toucher aux réglages DNS.

Contrôle 1, les pages :

```
curl -si --resolve bunker.example.org:80:192.0.2.10 http://bunker.example.org/admin/ | head -n 8
```

Résultat attendu : `HTTP/1.1 200 OK`, un en-tête `Content-Type: text/html`, et les en-têtes `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` et `Content-Security-Policy: frame-ancestors 'none'` (affichage exact à relever).

Contrôle 2, le catalogue des greffons :

```
curl -si --resolve bunker.example.org:80:192.0.2.10 http://bunker.example.org/admin/greffons/index.json | head -n 4
```

Résultat attendu : `HTTP/1.1 200 OK` et `Content-Type: application/json`.

Contrôle 2 bis, le type des fichiers `.js` (la ligne `mimetype.assign` ayant été retirée, ce contrôle vérifie que Debian déclare le bon type). Sur yang, repérez un script :

```
find /usr/local/share/paresia/web -name '*.js' | head -n 1
```

Puis, depuis le frontal, en remplaçant `CHEMIN` par ce chemin sans le début `/usr/local/share/paresia/web/` (par exemple `/admin/app.js` pour `…/web/app.js`) :

```
curl -si --resolve bunker.example.org:80:192.0.2.10 http://bunker.example.org/admin/CHEMIN | head -n 4
```

Résultat attendu : `HTTP/1.1 200 OK` et `Content-Type: text/javascript`. Si le type est autre, ne poursuivez pas : relevez-le.

Contrôle 3, l'API atteint Romulus :

```
curl -si -X POST --resolve bunker.example.org:80:192.0.2.10 http://bunker.example.org/api/admin/ -d '{}' | head -n 1
```

Résultat attendu : une réponse de Romulus, c'est-à-dire un code **autre que `403` et `502`/`503`** (le code exact dépend de l'action demandée : à relever). Un `502` ou `503` signifie que lighttpd ne joint pas la socket : contrôlez avec `id www-data` sur yang que le compte est membre du groupe `paresia-http`, et avec `ls -l /run/paresia-romulus/romulus-http.sock` que la socket existe.

Contrôle 4, un nom d'hôte inattendu est refusé :

```
curl -si -H 'Host: autre.example.org' http://192.0.2.10/admin/ | head -n 1
```

Résultat attendu : `HTTP/1.1 403 Forbidden`.

Contrôle 5, les chemins piégés ne servent rien :

```
curl -si --path-as-is --resolve bunker.example.org:80:192.0.2.10 'http://bunker.example.org/admin/greffons/%2f..%2f' | head -n 1
```

Résultat attendu : un code `4xx`, jamais `200` (code exact à relever).

Contrôle 6, une requête de plus de 64 Kio est refusée :

```
head -c 70000 /dev/zero | tr '\0' 'a' | curl -si -X POST --resolve bunker.example.org:80:192.0.2.10 http://bunker.example.org/api/admin/ --data-binary @- | head -n 1
```

Résultat attendu : un refus, probablement `HTTP/1.1 413 Content Too Large` (code exact à relever).

Contrôle 7, le journal d'accès ne contient ni cookie, ni jeton, ni chaîne de requête : relisez le journal de votre installation. Son emplacement dépend de la configuration Debian de lighttpd, que cette page ne modifie pas : à relever à l'essai.

Lighttpd répond comme attendu. Étape suivante : régler le frontal.

## 10. Sur le frontal : régler HAProxy

Machine : le frontal. Ce que Paresia exige de HAProxy se trouve dans [Régler HAProxy pour Paresia](Installer-haproxy.md).

Le frontal est prêt. La suite est le client : [Installer le client](Installer-client.md).

## Retour arrière

Machine : yang. Paresia ne modifie rien d'autre dans la configuration de lighttpd : il n'y a rien d'autre à défaire.

```
sudo lighty-disable-mod paresia
```

```
sudo lighttpd -tt -f /etc/lighttpd/lighttpd.conf
```

Résultat attendu : le même qu'à l'étape 7 (l'avertissement ne s'affiche plus s'il ne concernait que notre fichier ; sortie à relever à l'essai).

```
sudo systemctl restart lighttpd
```

Lighttpd ne sert plus les pages d'administration (il sert de nouveau sa page par défaut si vous réactivez `unconfigured` par `sudo lighty-enable-mod unconfigured`, commande à relever à l'essai). Le fichier `/etc/lighttpd/conf-available/90-paresia.conf` reste en place, inactif ; supprimez-le seulement si vous n'en avez plus besoin. Retirez aussi la ligne `set-header` du frontal ([retour arrière de la page HAProxy](Installer-haproxy.md#retour-arrière)) si vous abandonnez l'administration.

## Annexe : réserves

- **Mécanisme non essayé avec cet extrait.** Le dispositif `conf-available` et `lighty-enable-mod` de Debian n'a pas été essayé avec cet extrait ; le banc d'essai de Paresia exécute l'extrait avec un lighttpd éphémère, non par ce mécanisme.
- **Conflit possible de modules.** La configuration Debian par défaut charge déjà certains modules. Charger de nouveau un même module (par exemple `mod_access`, `mod_alias`, `mod_proxy`, `mod_setenv` ou `mod_accesslog`) peut faire refuser la configuration à lighttpd, ou en changer l'ordre. Constat de l'essai sur Debian 13 : les réglages déjà définis par Debian (`server.http-parseopts`, types de fichiers) donnent `Duplicate config variable` ou `Duplicate array-key` ; c'est pourquoi la page emploie `:=` et ne pose pas `mimetype.assign`. Un autre conflit reste possible : **il se voit** à l'étape 7, où `lighttpd -tt` signale une erreur (module déjà chargé, option en conflit) au lieu de la seule ligne d'avertissement et de `code : 0`. Dans ce cas, ne rechargez pas, faites le [retour arrière](#retour-arrière) et signalez la sortie exacte : aucune correction n'est présentée ici tant qu'elle n'est pas établie.
- **Versions.** Debian 13 fournit lighttpd 1.4.79 ; le banc a tourné avec la 1.4.82. La 1.4.79 n'a pas été exécutée par le banc.
- **Journal d'accès.** Sa destination sous systemd n'est pas documentée par lighttpd : non vérifié.
- **Chemin d'`/admin` sans barre finale.** Il n'est pas servi (aucune redirection prévue) : ouvrez toujours `/admin/`.
- **Détail des exigences et sources.** [Serveur web](../serveur-web.md), avec l'état (établi, déduit, non vérifié) de chacune.
