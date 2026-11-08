# Installer `nak` et créer une clé

Version du document : 0.1.19 · 2026-11-08.

Suivi, 2026-11-09 : réécrite ; `nak` s'installe sur le poste où les clés privées sont conservées (et sur `backend-admin` pour le bunker), plus sur `backend-relais` ; numéro du document inchangé.

**À faire sur le poste où vous conservez vos clés privées.**

Alpha : à essayer sur une machine jetable. Les commandes d'installation demandent `sudo` ; si vous êtes déjà root, retirez `sudo`.

## 1. Installer `nak`

Machine : le poste de vos clés privées. Version v0.22.3, licence The Unlicense. Ces commandes valent pour un binaire Linux amd64 ; pour un autre système, prenez le binaire correspondant sur https://github.com/fiatjaf/nak/releases (et vérifiez son empreinte).

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

## 2. Créer une clé

Machine : le poste de vos clés privées, dans `bash`. Rien n'est enregistré : la clé est seulement affichée.

> **Attention.** La commande affiche deux lignes : **la première est la clé privée, la seconde la clé publique**.
> Rien n'est enregistré : une fois l'écran effacé, la clé privée est perdue.
> Copiez la **clé privée** en lieu sûr (coffre de mots de passe), jamais dans un fichier d'une machine de service, un terminal partagé ou une conversation.
> Ne publiez ou ne configurez que la **clé publique** (par exemple dans `strfry.conf`).

```bash
SECRET=$(nak key generate); printf 'CLE PRIVEE (a conserver en lieu sur) : %s\n' "$SECRET"; printf 'CLE PUBLIQUE (pour strfry.conf)      : %s\n' "$(nak key public "$SECRET")"; unset SECRET
```

Résultat attendu : deux lignes libellées, chacune suivie de sa valeur.

```
CLE PRIVEE (a conserver en lieu sur) : …
CLE PUBLIQUE (pour strfry.conf)      : …
```

Pour la clé d'un relais, retournez à [Installer le relais strfry](Installer-strfry.md), étape 6, avec la clé publique.

## 3. Sur `backend-admin` (bunker)

`backend-admin` a aussi besoin de `nak` : le bunker (NIP-46) l'utilise, au chemin `/usr/local/bin/nak`. Machine : `backend-admin`, en root. Version v0.22.3.

Reprenez les trois commandes de l'étape 1 (`curl -fLO`, contrôle `sha256sum -c`, puis `install -m 0755 -o root -g root nak-v0.22.3-linux-amd64 /usr/local/bin/nak`, sans `sudo`). `curl` s'installe au besoin par `apt install curl`. Ne générez aucune clé sur cette machine.

## Annexe : raisons et réserves

- **Origine.** `nak` n'est pas fourni par Debian ; il vient de l'amont `fiatjaf/nak` (https://github.com/fiatjaf/nak), v0.22.3, The Unlicense (empreinte et licence vérifiées à l'API GitHub le 2026-11-08). Chemin attendu par la configuration du bunker : `/usr/local/bin/nak`.
- **Non essayé.** Les commandes d'installation ne font que télécharger, vérifier et installer ; aucune n'a été essayée.
- **Création de la clé (étape 2).** La commande n'a pas été essayée. `nak key generate` et `nak key public <clé>` sont attestés par le README de `nak`. L'historique du shell ne contient que la commande, non la clé. La clé passe brièvement en argument de `nak key public` : elle est alors visible dans la liste des processus ; lancez la commande sur un poste sans autre utilisateur.
- **Clé du relais.** Le `ncryptsec` est ensuite importé dans le bunker ; la clé privée du relais est une identité du bunker (`[bunkerd] relay_identity`), dont bunkerd ne garde que la forme chiffrée.
