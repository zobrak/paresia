# Installer le relais strfry

Version du document : 0.1.19 · 2026-11-08.

Suivi, 2026-11-08 : réécrite pas à pas, dépôt récupéré dès le début ; numéro du document inchangé.

Suivi, 2026-11-09 : `nak` n'est plus installé sur yin ; la clé du relais se crée sur le poste des clés privées (étape 6) ; étapes renumérotées ; numéro du document inchangé (aucun numéro donné).

Cette page prépare **yin** (la machine du relais, `backend-relais` dans les noms de scripts et de dossiers), de zéro, avant `INSTALL.md`. Elle suit un seul fil : rien d'autre à ouvrir.

Alpha : à essayer sur une machine jetable. Les noms et adresses (`yin`, `relay.example.org`, `192.0.2.20`) sont des exemples génériques (RFC 2606, RFC 5737).

## Avant de commencer

Il vous faut :

- yin sous Debian 13 ;
- un compte ordinaire, membre du groupe `sudo`, avec `curl` installé ;
- l'adresse IP de cette machine ;
- l'adresse publique du relais.

Toutes les commandes se lancent sur yin, avec ce compte.

### À personnaliser obligatoirement

| Valeur | Où | Exemple du guide | Ce qu'il faut mettre |
| --- | --- | --- | --- |
| adresse IP de la machine | `compose.yml` (étape 5) et contrôle `curl` (étape 9) | `192.0.2.20` | l'adresse IP de yin joignable par le proxy ; jamais `0.0.0.0` |
| `relay.auth.serviceUrl` | `strfry.conf`, étape 7 | `wss://relay.example.org` | l'adresse publique exacte du relais, en `wss://` ; sinon l'authentification échoue pour tous |
| `relay.info.self` | `strfry.conf`, étape 7 | `""` (vide) | la clé publique du relais, créée à l'étape 6 sur le poste de vos clés |

## 1. Récupérer le dépôt

Les fichiers à copier plus loin viennent du dépôt. Machine : yin.

Le clone, dans le dossier de votre compte, ne sert qu'à copier les fichiers livrés. Le relais tourne dans `/srv/strfry` et ne dépend plus du clone une fois les fichiers copiés.

```
sudo apt install git
```

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

## 2. Installer Docker

Machine : yin.

```
sudo apt install extrepo
sudo extrepo enable docker-ce
sudo apt update
```

```
sudo apt install docker-ce docker-ce-cli containerd.io docker-compose-plugin
```

```
sudo docker compose version
```

Résultat attendu (ou une version plus récente) :

```
Docker Compose version v5.7.0
```

## 3. Télécharger l'image

Machine : yin.

```
sudo docker pull z0brak/paresia-yin-strfry:4cd3cf6
```

Gardez l'étiquette `4cd3cf6` : l'installateur la compare.

Résultat attendu : la fin de la sortie indique que l'image est téléchargée ou déjà à jour.

## 4. Préparer les dossiers

Machine : yin. Les droits se règlent **avant** le premier démarrage.

```
sudo install -d -o "$USER" /srv/strfry
cd /srv/strfry
mkdir -p data journal plugins
```

```
sudo chown -R 10001:10001 data journal
```

```
cp ~/paresia/server/strfry/journal_legal.py plugins/
cp ~/paresia/deploy/backend-relais/strfry/strfry.conf strfry.conf
```

Rendez les fichiers lisibles par le conteneur :

```
sudo chmod 644 strfry.conf
sudo chmod 755 plugins plugins/journal_legal.py
```

```
ls -l strfry.conf plugins/journal_legal.py
```

Résultat attendu (la date et la taille varient) :

```
-rw-r--r-- 1 votre_compte votre_compte ... strfry.conf
-rwxr-xr-x 1 votre_compte votre_compte ... plugins/journal_legal.py
```

```
sudo ls -ld data journal
```

Résultat attendu :

```
drwxr-xr-x 2 10001 10001 4096 nov.  9 00:12 data
drwxr-xr-x 2 10001 10001 4096 nov.  9 00:12 journal
```

## 5. Écrire `compose.yml`

Machine : yin.

Créez `/srv/strfry/compose.yml` avec votre éditeur, avec ce contenu :

**À personnaliser : remplacez `192.0.2.20` par l'adresse IP de cette machine (jamais `0.0.0.0`).**

```yaml
services:
  strfry:
    container_name: strfry
    image: z0brak/paresia-yin-strfry:4cd3cf6
    user: "10001:10001"
    restart: unless-stopped
    ports:
      - "192.0.2.20:7777:7777"
    volumes:
      - ./strfry.conf:/etc/strfry.conf:ro
      - ./data:/app/strfry-db
      - ./plugins:/app/plugins:ro
      - ./journal:/app/journal
    read_only: true
    tmpfs:
      - /tmp
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true
    stop_grace_period: 2m
    logging:
      driver: journald
      options:
        tag: strfry
    healthcheck:
      test: ["CMD", "wget", "-q", "-O", "/dev/null", "http://127.0.0.1:7777/"]
      interval: 60s
```

Contrôlez le fichier :

```
cd /srv/strfry
grep ':7777:7777' compose.yml
```

Résultat attendu (votre adresse devant `:7777:7777`) :

```
      - "192.0.2.20:7777:7777"
```

## 6. Créer la clé du relais

À faire sur le poste où vous conservez vos clés privées, jamais sur cette machine : suivez [Installer nak](Installer-nak.md), puis revenez ici avec la ligne « CLE PUBLIQUE HEX ».

Résultat attendu : vous avez noté la ligne « CLE PUBLIQUE HEX ». Le `ncryptsec` reste en lieu sûr sur ce poste : c'est lui qui sera importé dans le bunker.

## 7. Régler `strfry.conf`

Machine : yin. Le fichier `/srv/strfry/strfry.conf` est livré complet : les réglages techniques (base, port, limites) fonctionnent tels quels. Ouvrez-le avec votre éditeur et renseignez les réglages ci-dessous. Chacun se trouve dans le bloc indiqué (`relay`, puis `auth` ou `info`).

| Réglage | À quoi il sert | Valeur à écrire | Obligatoire |
| --- | --- | --- | --- |
| `serviceUrl` (bloc `auth`) | l'adresse publique du relais, que les utilisateurs saisissent dans leur application ; strfry la compare à celle que l'utilisateur prouve avoir utilisée pour se connecter | `"wss://` suivi de votre domaine, puis `"` ; exemple : `"wss://relay.example.org"` | oui : sinon l'authentification échoue pour tous |
| `self` (bloc `info`) | la clé publique du relais, qui l'identifie en tant que relais | la ligne « CLE PUBLIQUE HEX » de l'étape 6 (64 caractères), entre guillemets | oui |
| `name` (bloc `info`) | le nom affiché aux utilisateurs dans leur application | par exemple `"Relais de l'association"` ; livré : `"Paresia"` | non |
| `description` (bloc `info`) | une phrase qui présente le relais | par exemple `"Relais privé de la famille."` ; livré : `"Relais Nostr du projet Paresia."` | non |
| `pubkey` (bloc `info`) | la clé publique de la personne qui administre, pour que l'on sache à qui s'adresser (différente de `self`) | la clé publique en hexadécimal (64 caractères) de l'administrateur, ou `""` | non |
| `contact` (bloc `info`) | un moyen de joindre l'administrateur | une adresse électronique ou un lien, par exemple `"mailto:admin@example.org"`, ou `""` | non |
| `icon` (bloc `info`) | une petite image du relais | l'adresse `https://…` d'une image, ou `""` | non |
| `banner` (bloc `info`) | une grande image d'en-tête | l'adresse `https://…` d'une image, ou `""` | non |
| `privacy` (bloc `info`) | la page qui explique ce que le relais conserve | l'adresse `https://…` de votre politique de confidentialité, ou `""` | non |
| `terms` (bloc `info`) | la page des règles d'usage de votre relais | l'adresse `https://…` de vos conditions d'utilisation, ou `""` | non |

Laissez les autres réglages tels qu'ils sont livrés. Voici les deux lignes obligatoires :

**À personnaliser : remplacez `VOTRE_DOMAINE` par l'adresse publique du relais, et `CLE_PUBLIQUE` par la valeur de la ligne « CLE PUBLIQUE HEX » obtenue à l'étape 6. N'y mettez jamais la clé privée.**

```
        serviceUrl = "wss://VOTRE_DOMAINE"
        self = "CLE_PUBLIQUE"
```

Contrôlez le fichier :

```
grep -E 'serviceUrl|self =' /srv/strfry/strfry.conf
```

Résultat attendu (vos valeurs à la place de `VOTRE_DOMAINE` et `CLE_PUBLIQUE`) :

```
        serviceUrl = "wss://VOTRE_DOMAINE"
        self = "CLE_PUBLIQUE"
```

Le `ncryptsec` sera importé dans le bunker lors de son installation sur yang.

## 8. Démarrer

Machine : yin.

```
cd /srv/strfry
sudo docker compose up -d
```

```
sudo docker ps --filter name=^strfry$
```

Résultat attendu : une ligne pour le conteneur `strfry`, dont l'état passe à `healthy` après une minute.

```
sudo docker compose logs --tail 20
```

Résultat attendu : la fin de la sortie contient ces deux lignes (l'adresse `0.0.0.0` est celle du conteneur, non de la machine) :

```
CONFIG: successfully installed
Started websocket server on 0.0.0.0:7777
```

## 9. Contrôler

Machine : yin.

```
sudo docker exec strfry wget -qO- http://127.0.0.1:7777/metrics
```

Résultat attendu : des métriques au format texte Prometheus.

```
sudo ss -ltn 'sport = :7777'
```

Résultat attendu (votre adresse devant `:7777`, jamais `0.0.0.0:7777`) :

```
LISTEN 0 4096 192.0.2.20:7777 0.0.0.0:*
```

**À personnaliser : remplacez `192.0.2.20` par l'adresse de l'étape 5.**

```
curl -s -H 'Accept: application/nostr+json' http://192.0.2.20:7777/
```

Résultat attendu : une réponse JSON comportant les champs `name`, `self`, `limitation`, `supported_nips` et `version`. Elle commence par `{"contact":` si vous avez renseigné un contact.

En cas d'échec : `sudo journalctl -t strfry`.

## 10. Publier un message d'essai

À faire sur le poste où `nak` est installé ([Installer nak](Installer-nak.md)), avec une clé jetable : elle est créée pour l'occasion, sans rien enregistrer, et ne sert qu'à cet essai.

**À personnaliser : remplacez `192.0.2.20` par l'adresse de l'étape 5.**

```bash
nak event --sec "$(nak key generate)" -c 'essai' ws://192.0.2.20:7777
```

Résultat attendu (la ligne JSON de l'événement varie) :

```
ws://192.0.2.20:7777... ok.
{"kind":1,...}
publishing to ws://192.0.2.20:7777... success.
```

## Suite

Yin est prêt pour le relais. Passez à `INSTALL.md`, étape 6 « Sur yin : contrôler que strfry tourne », puis suivez la suite : le dépôt est déjà récupéré sur cette machine.

## Si vous n'utilisez pas notre image

Cette section décrit ce que Paresia attend d'un conteneur strfry que vous avez construit ou installé vous-même. Elle est établie en lisant le code livré (installateur de yin, manifestes des fonctions de Remus, `strfry.conf`, plugin du journal légal) ; ce que le code n'établit pas est dit tel quel.

### Requis

| Attente | Pourquoi | Source dans le code |
| --- | --- | --- |
| Le conteneur s'appelle `strfry`. | Les fonctions de Remus lancent `docker exec strfry …` et `docker restart strfry`, seules commandes `sudo` autorisées ; l'installateur cherche ce nom. | `deploy/backend-relais/etc/sudoers.d/paresia-remus` ; étape « produit » de `installer-backend-relais.sh` |
| L'étiquette de l'image se termine par `4cd3cf6` (exemple : `mon-depot/strfry:4cd3cf6`). | L'installateur compare l'étiquette à la version déclarée par le greffon (`4cd3cf6`, l'identifiant court d'un commit de strfry) et s'arrête sinon (code 78). Pour ne pas poser cette condition, ajoutez `--sauter produit` aux commandes de yin : le contrôle est alors à votre charge. | `strfry_etat.toml`, section `[produit]` ; installateur |
| Le programme est `/app/strfry` dans le conteneur et comprend les sous-commandes `info` et `negentropy list`. | Ce sont les deux commandes lancées par les fonctions « état » et « arbres de synchronisation ». Les versions de strfry autres que le commit `4cd3cf6` ne sont pas vérifiées par le code : à essayer chez vous. | `strfry_etat`, `strfry_arbres` |
| `python3` est installé, à `/usr/bin/python3`. | Le plugin du journal légal est un script Python dont la première ligne est `#!/usr/bin/python3`. Il n'emploie que la bibliothèque standard (`json`, `os`, `re`, `time`…) et aucun sous-processus. Version minimale : le code ne la contrôle pas ; `docs/prerequis.md` indique que le plugin reste exécutable par Python 3.9 et plus, et l'image publiée a été relevée avec `Python 3.14.10`. | `server/strfry/journal_legal.py` |
| Le compte qui fait tourner le conteneur peut lire `/etc/strfry.conf` et `/app/plugins/journal_legal.py` (exécutable), écrire dans `/app/strfry-db` et dans `/app/journal`. | Sans cela, strfry s'arrête sur `Permission denied`. Le guide emploie `10001:10001` ; Paresia ne contrôle pas ce numéro. | guide, étapes 4 et 5 |
| La configuration est lue en `/etc/strfry.conf` (montée en lecture seule) et le plugin à `/app/plugins/journal_legal.py`. | `relay.writePolicy.plugin` doit désigner le chemin réel du plugin dans le conteneur. | `deploy/backend-relais/strfry/strfry.conf` |

### Recommandé (non vérifié par Paresia)

- **Écoute sur le port 7777**, publiée vers votre proxy inverse seulement : le guide, le contrôle de santé et la page du proxy l'attendent. Paresia elle-même n'ouvre aucune connexion vers ce port. Si vous changez le port, changez ensemble `relay.port` dans `strfry.conf`, la ligne `ports` du `compose.yml` et le contrôle de santé.
- **`wget`** dans l'image : il ne sert qu'au contrôle de santé (`healthcheck`) du `compose.yml` du guide.
- **`jq` : plus nécessaire.** Seul l'ancien plugin en shell (`journal-legal.sh`) l'exigeait. Le plugin actuel est en Python et le code du dépôt n'emploie plus `jq` ; la variante d'image « avec `jq` » n'a donc plus d'objet pour cette version.
- **Journaux par journald** (`logging.driver: journald`), système de fichiers en lecture seule, `cap_drop: ALL`, `no-new-privileges` : durcissement du guide, non exigé par le code.

### Arborescence du dossier `strfry` (celle du guide)

Le dossier `/srv/strfry` est une convention du guide : Paresia n'impose pas son emplacement. Ce que contient le guide, avec propriétaire et droits tels que le guide les fait obtenir :

| Chemin | Propriétaire | Droits | Contenu et montage dans le conteneur |
| --- | --- | --- | --- |
| `/srv/strfry` | votre compte | `755` | dossier de travail |
| `/srv/strfry/compose.yml` | votre compte | selon votre `umask` (lisible par vous suffit) | définition du conteneur |
| `/srv/strfry/strfry.conf` | votre compte | `644` | monté en lecture seule sur `/etc/strfry.conf` |
| `/srv/strfry/plugins/` | votre compte | `755` | monté en lecture seule sur `/app/plugins` |
| `/srv/strfry/plugins/journal_legal.py` | votre compte | `755` | plugin d'écriture (journal légal et liste noire) |
| `/srv/strfry/plugins/blocklist.txt` | votre compte | `644` (conseillé) | liste noire facultative : un fichier absent est toléré ; son contenu est une clé publique en hexadécimal (64 caractères) par ligne, `#` pour un commentaire |
| `/srv/strfry/data/` | `10001:10001` | `755` | base de données, montée sur `/app/strfry-db` |
| `/srv/strfry/journal/` | `10001:10001` | `755` | journal légal du jour, monté sur `/app/journal` ; le plugin crée ses fichiers en `640` |

Les modes de `data` et de `journal` viennent du relevé de l'étape 4 ; ceux de `compose.yml` et de `blocklist.txt` ne sont pas imposés par le code. Le plugin accepte aussi les variables d'environnement facultatives `JOURNAL_DIR`, `BLOCKLIST_FILE` et `UNJOURNALED_KINDS` si vos chemins diffèrent.

### Réglages de `strfry.conf` à adapter à vos paramètres locaux

Dans le fichier livré (`deploy/backend-relais/strfry/strfry.conf`) :

| Réglage | À adapter si… |
| --- | --- |
| `db` | votre base n'est pas à `/app/strfry-db/` dans le conteneur. |
| `relay.port` | vous n'employez pas le port 7777 (voir plus haut). |
| `relay.bind` | rarement : c'est l'adresse **dans** le conteneur ; l'exposition réelle se règle dans `compose.yml`. |
| `relay.realIpHeader` | votre proxy inverse pose l'adresse du client dans un autre en-tête que `x-forwarded-for`. |
| `relay.nofiles` | votre conteneur n'autorise pas 524288 descripteurs de fichiers (ajoutez `ulimits` au `compose.yml`, ou baissez la valeur). |
| `relay.auth.serviceUrl` | toujours : mettez l'adresse publique de votre relais (étape 7). |
| `relay.info.*` | selon vos préférences (étape 7). |
| `relay.writePolicy.plugin` | votre plugin n'est pas à `/app/plugins/journal_legal.py`. |
| `relay.auth.restrictedReadKinds`, `relay.filterValidation.*` | vous ne cherchez pas la compatibilité avec l'application bitchat (réglages livrés pour elle). |

## Annexe : raisons et réserves

- **Nom et image.** Le conteneur doit s'appeler `strfry` et venir de l'image `z0brak/paresia-yin-strfry:4cd3cf6` : l'installateur s'arrête sinon (code 78) et ne crée ni ne modifie ce conteneur. L'étiquette est l'identifiant court du commit de strfry. L'image est modifiée par le projet (Alpine 3.24, OpenSSL au lieu de LibreSSL).
- **Docker.** Le dépôt `docker-ce` par `extrepo` est un conseil, non une obligation.
- **Droits des fichiers copiés.** `cp` garde les droits limités par l'`umask` de votre compte ; or le conteneur tourne sous `10001`, un autre compte. Sans `chmod 644` et `chmod 755`, strfry s'arrête sur `Permission denied` en lisant `/etc/strfry.conf` ou le plugin.
- **Droits.** Le conteneur tourne sous `10001:10001` sans capacité (`cap_drop: ALL`) : ce compte doit être propriétaire de `data` et `journal`. Sinon strfry s'arrête sur `mdb_env_open: Permission denied`.
- **Port.** strfry n'est joignable que par le proxy inverse, qui doit écraser l'en-tête d'adresse du client. Jamais `0.0.0.0`.
- **Chemins dans l'image.** Programme `/app/strfry`, base `/app/strfry-db`, configuration cherchée dans l'ordre : `--config`, `STRFRY_CONFIG`, `/etc/strfry.conf`, `./strfry.conf`.
- **`strfry.conf` : réglages livrés, à ne changer qu'en connaissance de cause.** `db`, `relay.port = 7777`, `relay.bind = "0.0.0.0"` (adresse dans le conteneur), `relay.realIpHeader`, `relay.writePolicy.plugin` (doit coïncider avec le montage), `restrictedReadKinds = "4"` et `filterValidation.enabled = false` (choisis pour rester compatible avec l'application bitchat).

  > **Bon à savoir.** Paresia ne crée aucun arbre de synchronisation entre relais. Si vous en ajoutez un, sachez que n'importe qui pourra voir quand des messages privés ont été échangés (pas leur contenu). C'est votre choix.
- **Annonce NIP-11.** Les champs `relay.info.*` (`name`, `description`, `pubkey`, `self`, `contact`, `icon`, `banner`, `privacy`, `terms`) sont à votre convenance, sauf `self` (étape 7) ; les champs vides sont des valeurs d'installation. `pubkey` est la clé publique de l'administrateur (facultative), distincte de la clé du relais (`self`).
- **Clé.** La clé privée du relais est une identité du bunker (`[bunkerd] relay_identity`) ; bunkerd n'en garde que la forme chiffrée. Ne collez jamais une clé privée dans un fichier, un terminal partagé ou une conversation ; seule la clé publique se publie. `nak` n'est pas installé sur yin : la clé se crée sur le poste de vos clés (page [Installer nak](Installer-nak.md)).
- **Non établi, à compléter :** limites de ressources de la production ; valeur de `ulimits.nofile` si strfry se plaint de `nofiles = 524288` ; forme du fichier `blocklist.txt` du plugin.
