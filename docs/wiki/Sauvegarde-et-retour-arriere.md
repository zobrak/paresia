# Sauvegarde et retour arrière

Version du document : 0.1.16 · 2026-11-08 · [Accueil](Accueil.md)

Référence : `paresia-sauvegarde(8)`, `docs/exploitation.md` § 6, `docs/decisions.md`.

## Règle d'or

**Toute procédure de Paresia sauvegarde avant de modifier.** Rien n'est écrasé sans copie ; un état qui diffère de l'attendu est refusé, non écrasé.

## L'outil de sauvegarde des procédures

Les scripts d'installation emploient l'outil `paresia-sauvegarde`.

- Il range des **jeux datés** dans `/var/backups/paresia/<machine>/AAAAMMJJ-HHMMSS/` (`admin` ou `relais`), dossiers `root` en `0700`.
- Chaque jeu a un **manifeste** qui porte l'empreinte SHA-256 de chaque fichier copié. La restauration **vérifie** l'empreinte avant d'écrire et refuse (`backup_integrity_failed`) si elle diffère ou manque.
- **Aucune clé privée n'est jamais copiée.**
- Taille totale limitée (64 Mio par défaut) : au-delà, les jeux les plus anciens sont supprimés, jamais le jeu en cours ni le plus récent. Réglable dans `[sauvegarde.stockage]`, désactivable (`actif = non`) ; la restauration de sauvegardes existantes reste alors possible.
- L'outil est lancé depuis une copie du code appartenant à root, dans `/run/paresia-installation`, jamais depuis le clone du dépôt.
- Un fichier **créé** par la procédure est supprimé par la restauration (marque d'absence). Sans sauvegarde retrouvée, la restauration échoue et ne modifie rien.

## Retour arrière d'une installation

Chaque script d'installation sait revenir en arrière.

Listez d'abord les jeux de sauvegarde disponibles. Sur yang, en root :

```
ls -1 /var/backups/paresia/admin
```

Sur yin, avec votre compte :

```
sudo ls -1 /var/backups/paresia/relais
```

Exemple de sortie (un nom par jeu, du plus ancien au plus récent) :

```
20261109-101500
20261109-143200
```

**À personnaliser : remplacez `AAAAMMJJ-HHMMSS` par le nom du jeu retenu, tel qu'il figure dans cette liste (reportez-le sans le modifier).** Un assistant interactif, qui proposera le choix du jeu, viendra en v0.2.

Sur yang, en root :

```
cd ~/paresia
bash deploy/backend-admin/installer-backend-admin.sh --retour-arriere --jeu AAAAMMJJ-HHMMSS --confirme
```

Sur yin, avec votre compte :

```
cd ~/paresia
bash deploy/backend-relais/installer-backend-relais.sh --retour-arriere --jeu AAAAMMJJ-HHMMSS --confirme
```

Il arrête les unités posées, restaure dans l'ordre inverse de la pose, contrôle `sshd -t` (puis `reload ssh`, avec session de secours) et `visudo -c`, et supprime **seulement** les comptes et groupes créés par cette installation (jamais le contenu de leurs dossiers). Le nom du jeu est affiché au début de l'installation. `--jeu` et `--confirme` sont tous deux obligatoires : sans eux, le script refuse.

Limites à connaître :

- les dossiers déjà créés sous `/run` gardent leurs modes jusqu'au redémarrage du système ;
- un retour arrière avec `--stockage-actif non` à l'installation échoue (rien n'a été sauvegardé).

## Retour arrière manuel d'un fichier

Pour une unité ou un fichier précis, l'outil restaure un chemin d'un jeu (`restaurer --jeu <nom> <chemin>`), puis `systemctl daemon-reload`. Avant d'arrêter une unité, relisez l'effet d'un arrêt (voir [Dépannage](Journaux-metriques-depannage.md)).

## Retour à une version du code

Après une **mise à jour par script** (`--mise-a-jour`, voir [Installation](Installation.md)), le script a créé un jeu de sauvegarde daté et affiche son nom. Pour revenir à la version précédente (même valeur à personnaliser que ci-dessus), sur yang, en root :

```
cd ~/paresia
bash deploy/backend-admin/installer-backend-admin.sh --retour-arriere --jeu AAAAMMJJ-HHMMSS --confirme
```

Sur yin, avec votre compte :

```
cd ~/paresia
bash deploy/backend-relais/installer-backend-relais.sh --retour-arriere --jeu AAAAMMJJ-HHMMSS --confirme
```

Sur un jeu de mise à jour, le script arrête les seules unités de Paresia, restaure le code, le fichier `VERSION`, les unités et la configuration (y compris les fichiers `.paresia-nouveau`), recharge systemd, reprend les unités qui étaient actives et contrôle la version. Il ne supprime aucun compte.

Si le script a échoué en cours de mise à jour (une vérification après l'arrêt des unités), il a **déjà** fait ce retour arrière tout seul et s'est terminé en code 78 avec le nom du jeu.

**Exception importante : migration de données.** Certains démons migrent leurs propres données quand ils redémarrent. Si le journal d'un démon montre `state_migrated`, le script ne restaure rien : il arrête les unités redémarrées et vous donne la marche à suivre. Un retour est alors manuel : restaurez la sauvegarde propre que le démon a faite avant de migrer, puis revenez au code précédent. Ne relancez pas l'ancien code sur des données migrées.

Un retour à la main, sans le script, exige le dossier du code précédent avec son fichier `VERSION` à côté de `server/` (sans lui, les démons sortent en 70).

## Retour arrière d'une décision de conception

`docs/decisions.md` indique, pour chaque décision, ce qu'il faudrait défaire. Un retour en arrière de cette nature est une décision du mainteneur.

## Sauvegarder vos données

L'outil des procédures ne sauvegarde **pas** vos données d'exploitation. À sauvegarder vous-même, en attendant l'outil prévu :

- la base de strfry (côté relais) ;
- `bunker.json` (identités du bunker, chiffrées) et la copie de sûreté de migration qui l'accompagne ;
- le journal légal et ses sceaux (`MANIFEST`, `seals/`, preuves `.ots`) : le journal est une donnée probante ;
- la configuration `/etc/paresia/`.

Testez la restauration. Une sauvegarde jamais restaurée n'est pas une sauvegarde.

## À venir

- Sauvegarde des données d'état par **BorgBackup** (profils du bunker, base de strfry, journal légal) : à concevoir, licence à vérifier (principe 8 du cahier).
- Opérations de sauvegarde et d'import du relais (`backup/export`, `backup/import`) : prévues, non livrées (voir [Administrer le relais strfry](Administration-du-relais-strfry.md)).
