# Installer le relais strfry

Version du document : 0.1.19 · 2026-11-08.

Suivi, 2026-11-08 : réécrite pas à pas, dépôt récupéré dès le début ; numéro du document inchangé.

Cette page prépare `backend-relais`, de zéro, avant `INSTALL.md`. Elle suit un seul fil : rien d'autre à ouvrir.

Alpha : à essayer sur une machine jetable. Les noms et adresses (`backend-relais`, `relay.example.org`, `192.0.2.20`) sont des exemples génériques (RFC 2606, RFC 5737).

## Avant de commencer

Il vous faut :

- `backend-relais` sous Debian 13, avec un accès `root` pour l'étape 1 ;
- l'adresse IP de cette machine (`192.0.2.20` dans les exemples) ;
- l'adresse publique du relais (`relay.example.org` dans les exemples).

Toutes les commandes se lancent sur `backend-relais`.

## 1. Préparer le compte

Donne `sudo` à votre compte ordinaire. Machine : `backend-relais`, en root.

```
apt install sudo curl
```

```
usermod -aG sudo VOTRE_COMPTE
```

Remplacez `VOTRE_COMPTE` par votre compte. Fermez la session, puis ouvrez-en une nouvelle avec ce compte : toutes les étapes suivantes se lancent avec lui.

Résultat attendu : `sudo true` s'exécute sans erreur.

## 2. Récupérer le dépôt

Les fichiers à copier plus loin viennent du dépôt. Machine : `backend-relais`.

```
sudo apt install git
```

```
git clone https://github.com/zobrak/paresia.git paresia
```

```
cd paresia
cat VERSION
```

Résultat attendu : un numéro de version. Le dépôt est dans `~/paresia`.

## 3. Installer Docker

Machine : `backend-relais`.

```
sudo apt install extrepo
sudo extrepo enable docker-ce
sudo apt update
```

```
sudo apt install docker-ce docker-ce-cli containerd.io docker-compose-plugin
```

Résultat attendu :

```
sudo docker compose version
```

affiche un numéro de version.

## 4. Télécharger l'image

Machine : `backend-relais`.

```
sudo docker pull z0brak/paresia-yin-strfry:4cd3cf6
```

Gardez l'étiquette `4cd3cf6` : l'installateur la compare.

Résultat attendu : `Status: Downloaded newer image` ou `Image is up to date`.

## 5. Préparer les dossiers

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

Résultat attendu :

```
ls -ld data journal
```

montre le propriétaire `10001` pour les deux dossiers.

## 6. Écrire `compose.yml`

Machine : `backend-relais`, dans `/srv/strfry`. Indiquez d'abord l'adresse IP de la machine.

```
ADRESSE_RELAIS=192.0.2.20
```

```
cat > compose.yml <<EOF
services:
  strfry:
    container_name: strfry
    image: z0brak/paresia-yin-strfry:4cd3cf6
    user: "10001:10001"
    restart: unless-stopped
    ports:
      - "${ADRESSE_RELAIS}:7777:7777"
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
EOF
```

Résultat attendu :

```
grep 7777 compose.yml
```

montre votre adresse devant `:7777:7777`.

## 7. Installer `nak`

Machine : `backend-admin`, en root. Version v0.22.3, licence The Unlicense.

```
apt install curl
```

```
curl -fLO https://github.com/fiatjaf/nak/releases/download/v0.22.3/nak-v0.22.3-linux-amd64
```

```
echo "2eb9a16f86c865275983459b2c705d22d5dfbcf527026a279449cbf204d164fe  nak-v0.22.3-linux-amd64" | sha256sum -c -
```

Résultat attendu : `Réussi` ou `OK`, selon la langue. Sinon, arrêtez-vous.

```
install -m 0755 -o root -g root nak-v0.22.3-linux-amd64 /usr/local/bin/nak
```

Résultat attendu : `nak --help` affiche l'aide.

## 8. Créer la clé

Machine : `backend-admin`, en root, dans `bash`. La phrase de passe est saisie sans écho.

```
read -r -s -p "Phrase de passe : " PHRASE; echo
```

```
SECRET=$(nak key generate)
```

```
nak key public "$SECRET"
```

Résultat attendu : la clé publique du relais. Notez-la.

```
nak key encrypt "$SECRET" "$PHRASE"
```

Résultat attendu : le `ncryptsec`. Conservez-le sur `backend-admin`.

```
unset SECRET PHRASE
```

## 9. Régler `strfry.conf`

Machine : `backend-relais`, dans `/srv/strfry`. Indiquez l'adresse publique du relais.

```
sed -i 's|wss://relay.example.org|wss://VOTRE_DOMAINE|' strfry.conf
```

Remplacez `VOTRE_DOMAINE` par l'adresse publique.

Résultat attendu :

```
grep serviceUrl strfry.conf
```

affiche `wss://` suivi de votre adresse.

Facultatif : écrire la clé publique de l'étape 8 dans `relay.info.self` (laissez vide sinon).

## 10. Démarrer

Machine : `backend-relais`, dans `/srv/strfry`.

```
sudo docker compose up -d
```

Résultat attendu :

```
sudo docker ps --filter name=^strfry$
```

montre le conteneur `strfry`. Il passe à `healthy` après une minute.

## 11. Contrôler

Machine : `backend-relais`.

```
sudo docker exec strfry wget -qO- http://127.0.0.1:7777/metrics
```

Résultat attendu : des métriques en texte.

```
sudo ss -ltn 'sport = :7777'
```

Résultat attendu : une écoute sur votre adresse, jamais sur `0.0.0.0:7777`.

```
curl -s -H 'Accept: application/nostr+json' http://ADRESSE_RELAIS:7777/
```

Remplacez `ADRESSE_RELAIS` par l'adresse de l'étape 6. Résultat attendu : un objet JSON dont `name` vaut `Paresia`.

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
- **Annonce NIP-11.** Les champs `relay.info.*` (`name`, `description`, `pubkey`, `self`, `contact`, `icon`, `banner`, `privacy`, `terms`) sont à votre convenance ; les champs vides sont des valeurs d'installation.
- **Clé.** La clé privée du relais est une identité du bunker (`[bunkerd] relay_identity`) ; bunkerd n'en garde que la forme chiffrée. Ne collez jamais une clé privée dans un fichier, un terminal partagé ou une conversation ; seule la clé publique se publie. `nak` n'est pas fourni par Debian ; il vient de l'amont `fiatjaf/nak` (v0.22.3, The Unlicense, empreinte vérifiée à l'API GitHub). Les commandes des étapes 7 et 8 n'ont pas été essayées ; l'étape 7 ne fait que télécharger, vérifier et installer. La forme par arguments de l'étape 8 est attestée par le README de `nak`. Mise en garde : le secret passe brièvement en argument (`nak key public`, `nak key encrypt <secret> <mot-de-passe>`) ; il est alors visible dans la liste des processus et, selon le shell, dans l'historique. Ne lancez ces commandes que sur une machine sans autre utilisateur.
- **Non établi, à compléter :** présence de `python3` dans l'image publiée (le plugin du journal légal l'exige) ; limites de ressources de la production ; valeur de `ulimits.nofile` si strfry se plaint de `nofiles = 524288` ; forme du fichier `blocklist.txt` du plugin ; essai de ce `compose.yml` tel quel sur une machine.
