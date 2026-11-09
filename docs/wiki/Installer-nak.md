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

## 2. Comprendre les formats de clés

Une identité Nostr est une paire de clés secp256k1, de 32 octets chacune. La clé publique se déduit de la clé privée, jamais l'inverse. Une même clé s'écrit de plusieurs façons :

| Format | Ce que c'est | Nature | À savoir |
| --- | --- | --- | --- |
| hex | la clé en 64 caractères hexadécimaux, sans préfixe | publique ou privée | forme du protocole (NIP-01) et de `strfry.conf` ; rien ne distingue à l'œil une clé publique d'une privée : risque de confusion |
| `npub1…` | clé publique en bech32 (NIP-19) | **publique** | pour l'affichage et la saisie ; à partager librement |
| `nsec1…` | clé privée en clair en bech32 (NIP-19) | **privée** | le préfixe évite la confusion, pas le danger : qui la lit possède l'identité |
| `ncryptsec1…` | clé privée **chiffrée** par une phrase de passe (NIP-49) | privée, protégée | la phrase est étirée par scrypt, la clé chiffrée par XChaCha20-Poly1305 ; sans la phrase, inutilisable |

Hex et `npub` : la même clé publique écrite autrement. Hex et `nsec` : la même clé privée écrite autrement.

> **Il est toujours préférable de transporter ou conserver le `ncryptsec`, protégé par une phrase de passe longue, plutôt que le `nsec` ou la clé privée en hex.** Une phrase courte se casse par essais hors ligne ; une phrase perdue, c'est la clé perdue.

## 3. Générer une clé

Machine : le poste de vos clés privées, dans `bash`. Rien n'est enregistré : les valeurs sont seulement affichées.

> **Attention.**
> Rien n'est enregistré : une fois l'écran effacé, le `ncryptsec` est perdu si vous ne l'avez pas copié.
> La clé privée en clair n'est jamais affichée.
> Conservez le `ncryptsec` et la phrase de passe **séparément** : la phrase, longue, dans un coffre de mots de passe.
> La ligne `CLE PUBLIQUE HEX` va dans `relay.info.self` ; le `NPUB` se partage.

```bash
read -r -s -p "Phrase de passe longue : " PHRASE; echo
```

```bash
SECRET=$(nak key generate); PUB=$(nak key public "$SECRET"); printf 'NCRYPTSEC (a conserver)             : %s\n' "$(nak key encrypt "$SECRET" "$PHRASE")"; printf 'CLE PUBLIQUE HEX (pour strfry.conf) : %s\n' "$PUB"; printf 'NPUB (a partager)                   : %s\n' "$(printf '%s' "$PUB" | nak encode npub)"; unset SECRET PHRASE PUB
```

Résultat attendu : trois lignes libellées, de valeurs `ncryptsec1…`, 64 caractères hexadécimaux, `npub1…`.

```
NCRYPTSEC (a conserver)             : ncryptsec1…
CLE PUBLIQUE HEX (pour strfry.conf) : (64 caractères hexadécimaux)
NPUB (a partager)                   : npub1…
```

Pour la clé d'un relais, retournez à [Installer le relais strfry](Installer-strfry.md), étape 6, avec la ligne `CLE PUBLIQUE HEX`.

## 4. Sur `backend-admin` (bunker)

`backend-admin` a aussi besoin de `nak` : le bunker (NIP-46) l'utilise, au chemin `/usr/local/bin/nak`. Machine : `backend-admin`, en root. Version v0.22.3.

Reprenez les trois commandes de l'étape 1 (`curl -fLO`, contrôle `sha256sum -c`, puis `install -m 0755 -o root -g root nak-v0.22.3-linux-amd64 /usr/local/bin/nak`, sans `sudo`). `curl` s'installe au besoin par `apt install curl`. Ne générez aucune clé sur cette machine.

## Annexe : raisons et réserves

- **Origine.** `nak` n'est pas fourni par Debian ; il vient de l'amont `fiatjaf/nak` (https://github.com/fiatjaf/nak), v0.22.3, The Unlicense (empreinte et licence vérifiées à l'API GitHub le 2026-11-08). Chemin attendu par la configuration du bunker : `/usr/local/bin/nak`.
- **Non essayé.** Les commandes d'installation ne font que télécharger, vérifier et installer ; aucune n'a été essayée.
- **Formats de clés.** Sources : NIP-01, NIP-19 (https://github.com/nostr-protocol/nips/blob/master/19.md) et NIP-49 (https://github.com/nostr-protocol/nips/blob/master/49.md). Exemple public du NIP-19 : hex `3bf0c63fcb93463407af97a5e5ee64fa883d107ef9e558472c4eb9aaaefa459d` = `npub180cvv07tjdrrgpa0j7j7tmnyl2yr6yr7l8j4s3evf6u64th6gkwsyjh6w6`.
- **Génération (étape 3).** Les commandes n'ont pas été essayées. `nak key generate`, `nak key public`, `nak key encrypt <secret> <mot-de-passe>`, `nak encode npub` en tube et `nak key decrypt` avec invite sont attestés par le README de `nak`. L'historique du shell ne contient que les commandes, ni la clé ni la phrase. Le secret et la phrase passent brièvement en argument de `nak key encrypt` et la clé de `nak key public` : ils sont alors visibles dans la liste des processus ; utilisez un poste sans autre utilisateur. `nak key decrypt <ncryptsec>` permet de vérifier, mais affiche la clé privée à l'écran.
- **Clé du relais.** Le `ncryptsec` est ensuite importé dans le bunker ; la clé privée du relais est une identité du bunker (`[bunkerd] relay_identity`), dont bunkerd ne garde que la forme chiffrée.
