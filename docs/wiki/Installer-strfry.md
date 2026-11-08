# Installer le relais strfry

Version du document : 0.1.19 · 2026-11-08.

Suivi, 2026-11-08 : réécrite pas à pas, dépôt récupéré dès le début ; numéro du document inchangé.

Cette page prépare `backend-relais`, de zéro, avant `INSTALL.md`. Elle suit un seul fil : rien d'autre à ouvrir.

Alpha : à essayer sur une machine jetable. Les noms et adresses (`backend-relais`, `relay.example.org`, `192.0.2.20`) sont des exemples génériques (RFC 2606, RFC 5737).

## Avant de commencer

Il vous faut :

- `backend-relais` sous Debian 13 ;
- un compte ordinaire, membre du groupe `sudo`, avec `curl` installé ;
- l'adresse IP de cette machine ;
- l'adresse publique du relais.

Toutes les commandes se lancent sur `backend-relais`, avec ce compte.

### À personnaliser obligatoirement

| Valeur | Où | Exemple du guide | Ce qu'il faut mettre |
| --- | --- | --- | --- |
| adresse IP de la machine | `compose.yml` (étape 5) et contrôle `curl` (étape 10) | `192.0.2.20` | l'adresse IP de `backend-relais` joignable par le proxy ; jamais `0.0.0.0` |
| `relay.auth.serviceUrl` | `strfry.conf`, étape 8 | `wss://relay.example.org` | l'adresse publique exacte du relais, en `wss://` ; sinon l'authentification échoue pour tous |
| `relay.info.self` | `strfry.conf`, étape 8 | `""` (vide) | la clé publique du relais, créée à l'étape 7 |

## 1. Récupérer le dépôt

Les fichiers à copier plus loin viennent du dépôt. Machine : `backend-relais`.

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

Machine : `backend-relais`.

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

Machine : `backend-relais`.

```
sudo docker pull z0brak/paresia-yin-strfry:4cd3cf6
```

Gardez l'étiquette `4cd3cf6` : l'installateur la compare.

Résultat attendu : la fin de la sortie indique que l'image est téléchargée ou déjà à jour.

## 4. Préparer les dossiers

Machine : `backend-relais`. Les droits se règlent **avant** le premier démarrage.

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

```
sudo ls -ld data journal
```

Résultat attendu :

```
drwxr-xr-x 2 10001 10001 4096 nov.  9 00:12 data
drwxr-xr-x 2 10001 10001 4096 nov.  9 00:12 journal
```

## 5. Écrire `compose.yml`

Machine : `backend-relais`, dans `/srv/strfry`.

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
grep ':7777:7777' compose.yml
```

Résultat attendu (votre adresse devant `:7777:7777`) :

```
      - "192.0.2.20:7777:7777"
```

## 6. Installer `nak`

Machine : `backend-relais`. Version v0.22.3, licence The Unlicense.

```
cd ~
```

```
curl -fLO https://github.com/fiatjaf/nak/releases/download/v0.22.3/nak-v0.22.3-linux-amd64
```

```
echo "2eb9a16f86c865275983459b2c705d22d5dfbcf527026a279449cbf204d164fe  nak-v0.22.3-linux-amd64" | sha256sum -c -
```

Résultat attendu (`Réussi` au lieu de `OK` si le système est en français). Sinon, arrêtez-vous.

```
nak-v0.22.3-linux-amd64: OK
```

```
sudo install -m 0755 -o root -g root nak-v0.22.3-linux-amd64 /usr/local/bin/nak
```

```
nak --help
```

Résultat attendu : l'aide de `nak`.

## 7. Créer la clé du relais

Machine : `backend-relais`, dans `bash`. Rien n'est enregistré : la clé est seulement affichée.

> **Attention.** La commande affiche deux lignes : **la première est la clé privée, la seconde la clé publique**.
> Rien n'est enregistré : une fois l'écran effacé, la clé privée est perdue.
> Copiez la **clé privée** en lieu sûr (coffre de mots de passe), jamais dans un fichier de cette machine, un terminal partagé ou une conversation.
> Mettez la **clé publique**, et elle seule, dans `strfry.conf`.

```bash
SECRET=$(nak key generate); printf 'CLE PRIVEE (a conserver en lieu sur) : %s\n' "$SECRET"; printf 'CLE PUBLIQUE (pour strfry.conf)      : %s\n' "$(nak key public "$SECRET")"; unset SECRET
```

Résultat attendu : deux lignes libellées, chacune suivie de sa valeur.

```
CLE PRIVEE (a conserver en lieu sur) : …
CLE PUBLIQUE (pour strfry.conf)      : …
```

## 8. Régler `strfry.conf`

Machine : `backend-relais`. Dans `/srv/strfry/strfry.conf`, modifiez ces deux lignes avec votre éditeur :

**À personnaliser : remplacez `VOTRE_DOMAINE` par l'adresse publique du relais, et `CLE_PUBLIQUE` par la valeur de la ligne « CLE PUBLIQUE » de l'étape 7. N'y mettez jamais la clé privée.**

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

La clé privée sera importée dans le bunker lors de son installation sur `backend-admin`, qui la chiffrera.

## 9. Démarrer

Machine : `backend-relais`, dans `/srv/strfry`.

```
cd /srv/strfry
```

```
sudo docker compose up -d
```

```
sudo docker ps --filter name=^strfry$
```

Résultat attendu : une ligne pour le conteneur `strfry`, dont l'état passe à `healthy` après une minute.

## 10. Contrôler

Machine : `backend-relais`.

```
sudo docker exec strfry wget -qO- http://127.0.0.1:7777/metrics
```

Résultat attendu : des métriques au format texte Prometheus.

```
sudo ss -ltn 'sport = :7777'
```

Résultat attendu : une ligne d'écoute (`LISTEN`) sur votre adresse et le port 7777, jamais sur `0.0.0.0:7777`.

**À personnaliser : remplacez `192.0.2.20` par l'adresse de l'étape 5.**

```
curl -s -H 'Accept: application/nostr+json' http://192.0.2.20:7777/
```

Résultat attendu : un objet JSON dont le champ `name` vaut `Paresia`.

En cas d'échec : `sudo journalctl -t strfry`.

## Suite

`backend-relais` est prêt. Passez à `INSTALL.md`, étape « Contrôler que strfry tourne », puis suivez la suite : le dépôt est déjà récupéré sur cette machine.

## Annexe : raisons et réserves

- **Nom et image.** Le conteneur doit s'appeler `strfry` et venir de l'image `z0brak/paresia-yin-strfry:4cd3cf6` : l'installateur s'arrête sinon (code 78) et ne crée ni ne modifie ce conteneur. L'étiquette est l'identifiant court du commit de strfry. L'image est modifiée par le projet (Alpine 3.24, OpenSSL au lieu de LibreSSL).
- **Docker.** Le dépôt `docker-ce` par `extrepo` est un conseil, non une obligation.
- **Droits.** Le conteneur tourne sous `10001:10001` sans capacité (`cap_drop: ALL`) : ce compte doit être propriétaire de `data` et `journal`. Sinon strfry s'arrête sur `mdb_env_open: Permission denied`.
- **Port.** strfry n'est joignable que par le proxy inverse, qui doit écraser l'en-tête d'adresse du client. Jamais `0.0.0.0`.
- **Chemins dans l'image.** Programme `/app/strfry`, base `/app/strfry-db`, configuration cherchée dans l'ordre : `--config`, `STRFRY_CONFIG`, `/etc/strfry.conf`, `./strfry.conf`.
- **`strfry.conf` : à ne pas changer sans raison.** `db`, `relay.port = 7777`, `relay.bind = "0.0.0.0"` (adresse dans le conteneur), `relay.realIpHeader`, `relay.writePolicy.plugin` (doit coïncider avec le montage), `restrictedReadKinds = "4"` et `filterValidation.enabled = false` (compatibilité bitchat). Ne créez jamais d'arbre negentropy (`strfry negentropy add`, `build`).
- **Annonce NIP-11.** Les champs `relay.info.*` (`name`, `description`, `pubkey`, `self`, `contact`, `icon`, `banner`, `privacy`, `terms`) sont à votre convenance, sauf `self` (étape 8) ; les champs vides sont des valeurs d'installation. `pubkey` est la clé publique de l'administrateur (facultative), distincte de la clé du relais (`self`).
- **Clé.** La clé privée du relais est une identité du bunker (`[bunkerd] relay_identity`) ; bunkerd n'en garde que la forme chiffrée. Ne collez jamais une clé privée dans un fichier, un terminal partagé ou une conversation ; seule la clé publique se publie. Sur cette machine, rien n'est enregistré : la clé privée n'existe que le temps de la commande et de son affichage.
- **`nak`.** Il n'est pas fourni par Debian ; il vient de l'amont `fiatjaf/nak` (https://github.com/fiatjaf/nak), v0.22.3, The Unlicense (empreinte et licence vérifiées à l'API GitHub le 2026-11-08). Les commandes de l'étape 6 ne font que télécharger, vérifier et installer ; aucune n'a été essayée.
- **Création de la clé (étape 7).** La commande n'a pas été essayée. `nak key generate` et `nak key public <clé>` sont attestés par le README de `nak`. L'historique du shell ne contient que la commande, non la clé. La clé passe brièvement en argument de `nak key public` : elle est alors visible dans la liste des processus ; lancez la commande sur une machine sans autre utilisateur.
- **Non établi, à compléter :** présence de `python3` dans l'image publiée (le plugin du journal légal l'exige) ; limites de ressources de la production ; valeur de `ulimits.nofile` si strfry se plaint de `nofiles = 524288` ; forme du fichier `blocklist.txt` du plugin ; essai de ce `compose.yml` tel quel sur une machine.
