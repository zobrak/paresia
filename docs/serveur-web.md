# Exigences pour le serveur web de l'interface d'administration

Version du document : 0.1.19 · 2026-11-08. Public : administrateur.

Suivi des versions
- 0.1.0 (2026-11-08) : première version, exigences, extrait d'exemple sourcé et vérifications.

Paresia **n'installe pas** de serveur web et n'en configure aucun. Cette page décrit ce que Paresia exige du serveur web placé devant l'interface d'administration, avec un extrait d'exemple pour lighttpd. L'extrait est un **exemple non livré, à adapter par l'administrateur** : aucun fichier de configuration de serveur web n'est livré dans `deploy/`, aucun script de Paresia ne l'installe, ne le pose ni ne le recharge.

Sources : documentation officielle de lighttpd (wiki du projet, pages de manuel `lighttpd(8)`) lue pour la version 1.4.79 de Debian 13 (paquet 1.4.79-2), code source de l'étiquette `lighttpd-1.4.79`, et documentation de HAProxy. Chaque exigence porte son état : **établi** (page officielle ou essai du banc, seulement pour ce que le banc vérifie réellement), **déduit du code de 1.4.79** (lecture du code source, non éprouvée) ou **non vérifié**. Versions : le banc d'essai (`tests/banc/`) a tourné avec lighttpd 1.4.82 (paquet 1.4.82-2 de l'image de la CI) ; la version 1.4.79 de Debian 13 n'a pas été exécutée : un état « essai du banc » vaut pour 1.4.82 et, pour 1.4.79, reste à confirmer. Les citations décisives viennent d'un outil de lecture qui renvoie des extraits courts : une citation non relue sur la page est signalée « non relue ». Protocole de l'API : [protocole](protocole.md), § 6. Vue d'ensemble pour l'administrateur : [Architecture et sécurité](wiki/Architecture-et-securite.md) ; installation de la machine d'administration : [INSTALL.md](../INSTALL.md).

## Exigences

### Exigence 1 : version

lighttpd 1.4.51 ou plus récent (couvre `proxy.forwarded` et les options citées) ; Debian 13 fournit 1.4.79-2 ; ce paquet peut porter des correctifs Debian non documentés par lighttpd ; le banc d'essai a tourné en 1.4.82. Contrôler la syntaxe avec `lighttpd -tt -f <fichier>` avant tout rechargement. Source : documentation de lighttpd (versions minimales de chaque option, option `-t`/`-tt`). État : établi (version minimale) ; correctifs du paquet : non vérifié.

### Exigence 2 : même origine

`/admin/` (pages), `/admin/greffons/` (pages, catalogues et `index.json` des greffons) et `/api/admin/` (API) sont servis par le même serveur, sous le même schéma, hôte et port. `Host` est transmis tel que reçu : `proxy.replace-http-host` reste désactivé (Romulus compare `Origin` et `Host`, D15) ; aucune option de `proxy.header` pour `/api/admin/` (pas de remappage de chemin ou d'hôte, ni `https-remap`, `upgrade`, `force-http10`) ; le frontal n'ajoute pas `Access-Control-Allow-Origin`. Source : documentation du module `mod_proxy` (options `proxy.header` et `proxy.replace-http-host`). `Origin` est transmis intact (`mod_proxy` copie les en-têtes de la requête, sauf ceux qu'il traite lui-même : code de 1.4.79). État : établi pour `Host` (essai du banc) ; `Origin` : déduit du code de 1.4.79.

### Exigence 3 : relais de `/api/admin/`

Relais vers la socket Unix de Romulus (`[romulus.http] socket`) par `mod_proxy` (`proxy.server`, hôte commençant par `/`, depuis 1.4.36). Seul `POST` est utile (Romulus répond `405` aux autres). `server.stream-request-body = 0` (défaut) : le corps est reçu en entier et transmis avec `Content-Length`, jamais en `Transfer-Encoding` (refusé par Romulus). `server.max-request-size = 64` (kio, « en-tête + corps ») : la marge exacte est non vérifiée. Source : documentation des modules `mod_proxy` et des options `server.*`. La socket Unix est celle de `[romulus.http] socket` (défaut `/run/paresia-romulus/romulus-http.sock`) : Romulus la crée en mode `0660`, groupe `paresia-http` (seuls les membres de ce groupe peuvent s'y connecter ; l'installation de yang (`backend-admin` dans les noms de scripts) y ajoute le compte `www-data`, celui de lighttpd sous Debian, sauf étape sautée) et n'écoute sur aucun port TCP ; l'administrateur n'élargit pas ces droits et n'ajoute aucune écoute TCP à Romulus. État : établi pour la syntaxe de la socket et la transmission de `Content-Length` (essai du banc) ; corps trop gros refusé et corps `chunked` non transmis comme tel : établi (essai du banc) ; marge de `server.max-request-size` : non vérifié. Un corps `chunked` envoyé par le client est reçu en entier et transmis avec `Content-Length`, sans `Transfer-Encoding` (établi, banc, 1.4.82). Méthodes : seul `POST` est utile sur l'API (Romulus répond `405` aux autres) ; l'extrait ne restreint pas les méthodes (aucune directive documentée par lighttpd n'est retenue) : non vérifié.

### Exigence 4 : pages statiques

`/admin/` reçoit le dossier de la web-ui (`/usr/local/share/paresia/web/`), `/admin/greffons/` le dossier `…/web/greffons/`, par `alias.url` avec une `/` finale **des deux côtés**, l'alias le plus long déclaré avant le plus court. Liste de dossier désactivée (`dir-listing.activate = "disable"`), `index-file.names = ( "index.html" )` seul, **`static-file.disable-pathinfo = "enable"` obligatoire sur lighttpd 1.4.79** (le défaut ne devient « enable » qu'à partir de 1.4.80). Aucun module d'exécution (`mod_cgi`, `mod_fastcgi`, `mod_scgi`, `mod_ssi`, `mod_webdav`) sur ces chemins. Dossiers en lecture seule, sans lien symbolique sortant (le suivi des liens est actif par défaut ; sa désactivation par bloc conditionnel est non vérifiée). Types de contenu : `.js` en `text/javascript`, `.json` en `application/json` : l'administrateur contrôle l'en-tête par une requête réelle (la table générée par Debian n'est pas documentée par lighttpd : non vérifié). Les dossiers de pages appartiennent à root et ne sont pas modifiables par le compte de lighttpd. Aucun lien symbolique sortant : contrôle de l'administrateur ; `server.follow-symlink = "disable"` n'est pas dans l'extrait (non éprouvé) : non vérifié. Les pages s'ouvrent à `/admin/` : `/admin` sans barre finale ne correspond à aucun alias de l'extrait et n'est pas servi (aucune redirection prévue ; comportement non vérifié). Méthodes sur les pages : l'extrait n'ajoute aucune restriction ; un `POST` sur une page est servi comme un `GET` (réponse `200`, établi par le banc en 1.4.82), sans effet : aucune directive de l'extrait ne le refuse, il n'est donc pas refusé. Source : documentation des modules `mod_alias`, `mod_dirlisting`, `mod_staticfile`, `mod_indexfile`. État : déduit du code de 1.4.79 pour `disable-pathinfo` ; cohabitation des deux alias, types de contenu, liste de dossier désactivée, aucun fichier servi par `…/fichier.js/suite` : établi (essai du banc) ; liens symboliques : non vérifié.

### Exigence 5 : adresse du client

Le frontal HAProxy pose un en-tête dédié, `X-Paresia-Client-IP` (valeur de `[romulus.http] client_ip_header`), que l'administrateur règle explicitement (`client_ip_header = X-Paresia-Client-IP` dans `[romulus.http]`, valeur du fichier de configuration livré `server/conf/paresia.conf`). HAProxy le pose par `http-request set-header X-Paresia-Client-IP %[src]`, qui remplace toute valeur reçue. lighttpd laisse cet en-tête passer tel quel (`mod_proxy` copie les en-têtes inconnus). Romulus ne lit que cet en-tête, et seulement sur sa socket de confiance. lighttpd n'est joignable que depuis HAProxy : écoute limitée à l'interface atteignable par HAProxy et pare-feu limitant la source (les directives `server.bind` et `$SERVER["socket"]` ne sont pas documentées ici par lighttpd : non vérifié). Un `X-Forwarded-For` posé par le frontal pour tous ses services est sans effet sur l'adresse retenue : la capture de l'essai réel sur yang montre `x-paresia-client-ip` correct et les valeurs forgées écrasées (état : établi par cette capture). `mod_extforward` n'est pas utilisé pour l'adresse du client. `X-Forwarded-For`, toujours ajouté par `mod_proxy`, est ignoré de Romulus. **Sans HAProxy**, l'adresse du client n'est pas fiable (l'en-tête serait forgeable) : Romulus lit l'en-tête configuré sur sa socket quoi qu'il arrive : la protection vient de lighttpd, non de Romulus. Sans HAProxy, un client peut donc forger l'en-tête dédié ; l'administrateur le supprime côté lighttpd par `setenv.set-request-header = ( "X-Paresia-Client-IP" => "" )` (une valeur vide supprime l'en-tête ; depuis 1.4.46 ; `mod_setenv` placé avant `mod_proxy`), ou limite l'accès à des pairs de confiance. Source : documentation de `mod_proxy`, `mod_setenv` et de HAProxy (`http-request set-header`). État : le passage inchangé de l'en-tête dédié est établi (essai du banc) ; la règle `set-header` de HAProxy est établie par la documentation de HAProxy, non éprouvée par le banc d'essai (frontal simulé) ; restriction par adresse du pair : établi (essai du banc) ; neutralisation sans HAProxy et directives d'écoute : non vérifié.

### Exigence 6 : normalisation de l'URL

Conserver à `"enable"` `header-strict`, `host-strict`, `host-normalize`, `url-normalize-unreserved`, `url-normalize-required`, `url-ctrls-reject`, `url-path-dotseg-remove` et `url-invalid-utf8-reject` (valeurs de la configuration Debian). **`url-path-2f-reject`** est retenu à la place de `url-path-2f-decode` (Romulus compare le chemin exactement) : les deux ne figurent jamais ensemble. Dans l'extrait, `url-path-2f-decode` est mis explicitement à `"disable"` : lighttpd 1.4.82 refuse de démarrer (`conflicting options`) si `url-path-2f-reject` est posé sans cela. Source : documentation de `server.http-parseopts`. État : démarrage avec cette combinaison, refus de `%2F`, traversées par `..` et `%2e%2e` sans sortie de la racine : établi (essai du banc, 1.4.82).

### Exigence 7 : journaux

`accesslog.format` explicite **sans** `%r`, `%q`, `%{…}i` ni `%C` (`%r` inclut la chaîne de requête), par exemple `"%h %t %m %U %>s %b"` (`%U` est sans chaîne de requête). `accesslog.escaping` échappe les caractères de contrôle (depuis 1.4.66). Jamais `debug.log-request-header` en production. Destination (journald, `accesslog.use-syslog`) : le mode sous systemd n'est pas documenté par lighttpd : non vérifié. Source : documentation de `mod_accesslog` et code de 1.4.79 pour `%r`. État : `%r` : déduit du code de 1.4.79 ; absence de cookie et de jeton dans les journaux : établi (essai du banc) ; destination : non vérifié.

### Exigence 8 : flux `text/event-stream`

`server.stream-response-body = 2` (la valeur 0 retient la réponse entière : le flux ne démarre jamais). Si `mod_deflate` est chargé : jamais de préfixe `text/` dans `deflate.mimetypes` pour ces chemins, jamais `text/event-stream`, aucune compression de `/api/admin/`. Effet de `server.max-read-idle` (60 s par défaut) sur un flux silencieux : mesuré par l'essai de silence du banc (job dédié de la CI) ; tant que l'essai n'est pas concluant, l'administrateur choisit une valeur supérieure au double de la période du commentaire SSE de Romulus. Délais côté HAProxy : voir la documentation de HAProxy. Source : documentation de `server.stream-response-body` et de `mod_deflate`. État : flux reçu événement par événement : établi (essai du banc) ; effet du silence prolongé : mesuré par le job dédié, non vérifié tant que le résultat n'est pas consigné ; `mod_deflate` : non éprouvé.

### Exigence 9 : en-têtes des pages et ordre des modules

`x-content-type-options: nosniff` par `mod_setenv` sur `/admin/`. La politique de sécurité du contenu de la page est posée par la page elle-même (balise `<meta>`), mais une balise `<meta>` ne peut pas porter `frame-ancestors` : l'anti-encadrement est donc posé par le serveur web, sur `/admin/`, par `X-Frame-Options: DENY` et `Content-Security-Policy: frame-ancestors 'none'` (`setenv.add-response-header`). Ordre des modules : `mod_access` au début, `mod_setenv` avant tout module qui termine la requête, `mod_proxy` ensuite, `mod_accesslog` en dernier. L'extrait utilise `server.modules += (…)` et `+=` pour `alias.url` afin de ne pas écraser une configuration existante. Source : documentation des modules `mod_setenv` et de l'ordre de chargement. État : `nosniff` et en-têtes d'anti-encadrement : établi (essai du banc) ; ordre des modules : établi (page officielle, non éprouvé par le banc).

### Exigence 10 : nom d'hôte attendu (rebinding DNS)

Toute requête dont l'en-tête `Host` n'est pas le nom attendu est refusée, par un test `$HTTP["host"]` suivi de `url.access-deny = ( "" )` (dans l'extrait : `bunker.example.org`, à remplacer par le nom réel). `Host` et `Origin` sont transmis intacts à Romulus, qui compare les deux (D15). Source : condition `$HTTP["host"]` non documentée par lighttpd (non vérifiée) ; `url.access-deny` : documentation de `mod_access`. État : refus d'un `Host` inattendu : établi (essai du banc, 1.4.82).

## Extrait d'exemple

**Exemple non livré, non installé, à adapter par l'administrateur.** Il est composé de directives de la documentation de lighttpd ; l'adresse `192.0.2.254` est celle du pair admis (le frontal), à remplacer ; le chemin de la socket, les dossiers et la source de chaque directive sont indiqués dans le tableau suivant. Le banc de test exécute cet extrait, tel quel, avec un lighttpd éphémère.

<!-- extrait-lighttpd:debut -->
```
server.modules += ( "mod_access", "mod_setenv", "mod_alias", "mod_proxy", "mod_accesslog" )

server.stream-request-body  = 0
server.stream-response-body = 2
server.max-request-size     = 64
server.http-parseopts = (
    "header-strict" => "enable", "host-strict" => "enable", "host-normalize" => "enable",
    "url-normalize-unreserved" => "enable", "url-normalize-required" => "enable",
    "url-ctrls-reject" => "enable", "url-path-2f-reject" => "enable", "url-path-2f-decode" => "disable",
    "url-path-dotseg-remove" => "enable", "url-invalid-utf8-reject" => "enable" )

accesslog.format   = "%h %t %m %U %>s %b"
accesslog.escaping = "default"

mimetype.assign += ( ".html" => "text/html", ".js" => "text/javascript", ".json" => "application/json" )

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
<!-- extrait-lighttpd:fin -->

| Directive | Source dans la documentation de lighttpd |
| --- | --- |
| `server.modules`, ordre des modules | ordre de chargement des modules |
| `server.stream-request-body`, `server.max-request-size` | documentation de lighttpd (module ou option correspondant) |
| `server.stream-response-body` | documentation de lighttpd (module ou option correspondant) |
| `server.http-parseopts` | documentation de lighttpd (module ou option correspondant) |
| `accesslog.format`, `accesslog.escaping` | documentation de lighttpd (module ou option correspondant) |
| `mimetype.assign` | documentation de lighttpd (module ou option correspondant) |
| `$HTTP["remoteip"]`, `url.access-deny` | documentation de `mod_access` et des conditions |
| `$HTTP["host"]` | condition de la documentation de lighttpd (non documentée par lighttpd : établie par le banc d'essai) |
| `alias.url` | documentation de lighttpd (module ou option correspondant) |
| `dir-listing.activate` | documentation de lighttpd (module ou option correspondant) |
| `static-file.disable-pathinfo` | documentation de lighttpd (module ou option correspondant) |
| `index-file.names` | documentation de lighttpd (module ou option correspondant) |
| `setenv.set-response-header` | documentation de lighttpd (module ou option correspondant) |
| `proxy.server` | documentation de lighttpd (module ou option correspondant) |

La restriction par `$HTTP["remoteip"]` complète, sans la remplacer, la limitation de l'écoute et du pare-feu (exigence 5). Pour que le serveur de l'administrateur n'écrase pas sa configuration existante, l'extrait n'est pas un fichier complet : l'écoute, la racine du site, les journaux et le reste restent à sa charge.

## Vérifications de bout en bout

Après tout changement, avec une requête réelle (valeurs d'essai à générer pour l'occasion, jamais un secret réel) :

1. `lighttpd -tt -f <fichier>` ne signale aucune erreur.
2. `/admin/` et `/admin/greffons/index.json` répondent avec les types attendus (`text/html`, `application/json`) ; un script `.js` répond en `text/javascript`.
3. `POST /api/admin/…` atteint Romulus avec `Host`, `Cookie`, corps et `Content-Length` intacts.
4. `/admin/greffons/<greffon>/script.js/suite`, `/admin/greffons/../…` et `%2f` ne servent aucun fichier.
5. Un dossier sans `index.html` ne produit pas de liste.
6. Un corps de plus de 64 Kio est refusé.
7. Le journal d'accès ne contient ni cookie, ni jeton, ni chaîne de requête.

Le dépôt exécute ces contrôles dans un banc de test (`tests/test_serveur_web_banc.py`) avec un lighttpd éphémère : il vérifie que les exigences sont satisfaisables, il ne configure aucune installation.

## Retour arrière

Retirer de la configuration du serveur web les directives ajoutées pour Paresia, contrôler avec `lighttpd -tt -f <fichier>`, puis recharger. Paresia ne modifie rien dans cette configuration : il n'y a rien d'autre à défaire.

## Frontal HAProxy

Mêmes principes : Paresia ne livre aucune configuration de HAProxy. Exigences : poser `X-Paresia-Client-IP` par `http-request set-header X-Paresia-Client-IP %[src]` ; `X-Forwarded-For` n'est pas utilisé par Paresia : le poser pour yang, comme pour les autres services, est sans conséquence (établi par la capture de l'essai réel) ; ne pas ajouter `Access-Control-Allow-Origin` ; ne laisser lighttpd joignable que depuis HAProxy. Ordre des règles de réponse : HAProxy applique celles du backend avant celles du frontend (« the backend rules are applied first, followed by the frontend's rules », manuel de HAProxy 3.0, section `http-response`, https://docs.haproxy.org/3.0/configuration.html) ; une ligne `http-response set-header Access-Control-Allow-Origin` d'un `frontend` rétablit donc l'en-tête malgré un retrait dans le backend de yang : ne la poser que dans les backends des relais. État : établi par le manuel. Détails des délais du flux : voir la documentation de HAProxy.
