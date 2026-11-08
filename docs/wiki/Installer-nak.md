# Installer `nak` sur backend-admin

Version du document : 0.1.19 · 2026-11-08.

**À faire sur `backend-admin`.** `nak` y sert aux signataires du bunker (NIP-46). `backend-relais` a sa propre installation de `nak`, dans le guide strfry (`Installer-strfry.md`, étapes 6 et 7), avec la création de la clé du relais.

Alpha : à essayer sur une machine jetable. Toutes les commandes se lancent en root.

## 1. Installer `nak`

Machine : `backend-admin`. Version v0.22.3, licence The Unlicense.

```
apt install curl
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
install -m 0755 -o root -g root nak-v0.22.3-linux-amd64 /usr/local/bin/nak
```

```
nak --help
```

Résultat attendu : l'aide de `nak`.

## Annexe : raisons et réserves

- **Origine.** `nak` n'est pas fourni par Debian ; il vient de l'amont `fiatjaf/nak` (https://github.com/fiatjaf/nak), v0.22.3, The Unlicense (empreinte et licence vérifiées à l'API GitHub le 2026-11-08). Chemin attendu par la configuration : `/usr/local/bin/nak`.
- **Non essayé.** Ces commandes ne font que télécharger, vérifier et installer ; aucune n'a été essayée.
- **Clé du relais.** Elle se crée sur `backend-relais` (guide strfry). Le `ncryptsec` est ensuite importé dans le bunker ; la clé privée du relais est une identité du bunker (`[bunkerd] relay_identity`), dont bunkerd ne garde que la forme chiffrée.
