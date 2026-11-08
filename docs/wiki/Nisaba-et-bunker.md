# Nisaba et le bunker

Version du document : 0.1.19 · 2026-11-08 · [Accueil](Accueil.md)

Référence : `docs/cahier-des-charges.md` (§ Journal légal, § Administration de bunkerd), `docs/protocole.md` § 5.1 et 5.2, `docs/configuration.md`, `paresia-nisaba(8)`, `nisaba-ctl(1)`, `paresia-bunkerd(8)`.

Nisaba et le bunker sont deux greffons yang, avec strfry les premiers greffons d'illustration. Ils tournent sur `backend-admin`.

## Nisaba : le journal légal

### À quoi ça sert

Un relais hébergeant des contenus du public a des obligations de conservation de journaux (le projet vise la législation française ; cette page n'est pas un avis juridique). Le plugin d'écriture de strfry inscrit chaque événement publié dans un **journal légal**. Nisaba en assure ensuite la **conservation probante** sur `backend-admin`.

### Ce que fait Nisaba

Quatre tâches planifiées, toutes en UTC :

| Tâche | En clair |
| --- | --- |
| **copie** | rapatrie le journal depuis `backend-relais` (rsync par ssh, avec une clé dédiée en lecture seule) ; toutes les 60 s par défaut |
| **scellement** | fige chaque journée terminée : empreintes, registre `MANIFEST`, sceaux. En cas de retard, il rattrape depuis la dernière journée scellée jusqu'à la veille |
| **horodatage** | demande une preuve d'existence à date certaine par **OpenTimestamps** ; seule l'empreinte de la ligne du registre part sur Internet ; une preuve incomplète après 3 jours donne `ECHEC_HORODATAGE` |
| **purge** | supprime les journées au-delà de la conservation (365 jours par défaut ; la journée D est supprimée à D + 366 jours) |

Nisaba assure aussi la **consultation** du journal légal (recherche, export, état, vérification) : Romulus ne fait que router les demandes vers lui. Aujourd'hui, l'état et la vérification sont livrés ; la recherche et l'export restent à faire, et les actions `legal/*` répondent encore 501.

Nisaba gère aussi les **droits** : modes, ACL, et attribut d'immuabilité (`chattr +i`) du journal, pour qu'un fichier scellé ne soit plus modifiable. L'immuabilité exige la capacité `CAP_LINUX_IMMUTABLE`, que devra donner l'unité systemd de Nisaba (cette unité n'est pas encore livrée).

### La commande `nisaba-ctl`

```
python3 -m server.nisaba.ctl status       # état des tâches et des échecs
python3 -m server.nisaba.ctl verify       # vérifie le MANIFEST et les sceaux (lecture seule)
python3 -m server.nisaba.ctl run <tâche>  # lance copie, scellement (avec une date), horodatage ou purge
python3 -m server.nisaba.ctl metrics      # métriques
python3 -m server.nisaba.ctl acl check    # contrôle des modes et ACL
python3 -m server.nisaba.ctl acl apply    # rétablit les modes et ACL conformes
```

Codes de sortie : 0 succès, 1 échec, 2 usage, 3 Nisaba injoignable. `verify` se termine par `RÉSULTAT : registre intègre (<n> journées)` ou par le nombre d'erreurs.

Les échecs sont écrits dans journald avec un code stable en tête de ligne : `ECHEC_COPIE`, `ECHEC_ACL`, `ECHEC_SCELLEMENT`, `ECHEC_HORODATAGE`, `ECHEC_PURGE`.

### Anciens scripts

Nisaba reprend les fonctions des anciens scripts `journal-legal-pull`, `-seal`, `-acl` et `-purge`. Si vous utilisez encore ces scripts, **arrêtez leurs minuteries avant de démarrer Nisaba**.

## Le bunker (bunkerd)

### À quoi ça sert

bunkerd est un **bunker NIP-46** : un service qui garde des clés Nostr chiffrées et signe à distance pour les clients que vous autorisez, sans que la clé quitte le serveur. Une **identité** est une clé chiffrée (NIP-49, `ncryptsec`) avec ses relais et ses clients autorisés. Une identité est **verrouillée** par défaut ; elle ne se déverrouille que par la phrase secrète, pour une durée limitée (15 minutes par défaut, de 1 à 1440).

### Ce que Paresia ajoute

Sans changer le verrouillage, le déverrouillage ni l'affichage de l'URI et du code QR, Paresia ajoute l'**administration des identités** derrière la session de présence : lister, ajouter, changer le secret ou les relais, autoriser ou révoquer un client, régler le délai, supprimer. Les contrôles sont stricts (nom d'identité de 1 à 32 caractères, relais en `wss://`, un maximum de 10) et un secret n'est jamais renvoyé ni journalisé.

Une identité particulière peut être désignée **clé du relais** ; on ne peut pas la supprimer par l'administration. Avec elle, bunkerd **signe la liste de sourdine** du relais (kind 10000, jusqu'à 500 clés) à partir de la phrase secrète que l'administrateur envoie ; le déchiffrement est sérialisé et une phrase refusée est suivie d'une pause de 2 s.

L'état est dans `bunker.json`, versionné : au démarrage, un ancien format est migré après une copie de sûreté.

### Prérequis du bunker

L'exécutable `nak`, `python3-cryptography` et `libssl3t64` 3.5.7-1~deb13u3 au moins (voir [Prérequis](Prerequis.md)).

## À venir

- **Unités systemd de bunkerd et de Nisaba** : non livrées dans le dépôt ; procédure d'installation et de migration des anciens scripts à venir.
- **Exposition par l'interface web** : Romulus route par HTTP l'état (`nisaba/state/status`) et la vérification (`nisaba/state/verify`) de Nisaba, si la section `[romulus.nisaba]` est configurée ; sans elle, ces actions répondent `not_available`. Le lancement d'une tâche et la gestion des ACL ne passent que par `nisaba-ctl`. La consultation et l'export du journal légal par l'interface (recherche, export d'une archive de réquisition) sont **prévus** : les actions `legal/…` répondent `not_available`.
- Outil de contrôle de bunkerd (`bunkerctl`) et page `bunker.json(5)` : à écrire.
- Pages web d'administration des identités.
