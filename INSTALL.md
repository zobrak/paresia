# Installer Paresia

Version du document : 0.1.19 · 2026-11-08.

Suivi, 2026-11-08 : réécrit pas à pas, dépôt récupéré dès le début ; numéro du document inchangé.

**Alpha : pas en production. À essayer sur des machines jetables.**

Ce guide installe Paresia sur deux machines Debian 13, de zéro : `backend-admin` (côté yang : Pollux, Romulus) et `backend-relais` (côté yin : Castor, Remus), reliées par un tunnel SSH.

## Avant de commencer

Il vous faut :

- deux machines Debian 13 avec `systemd`. Exemples : `backend-admin` en `192.0.2.10`, `backend-relais` en `192.0.2.20` (RFC 5737) ;
- `backend-admin` qui joint `backend-relais` en TCP sur le port 22 ;
- un accès `root` sur `backend-admin`, et sur `backend-relais` un compte ordinaire avec `sudo` (créé à l'étape 4) ;
- pour chaque machine, un second terminal SSH (ou la console) ouvert et testé : le script recharge `sshd` ;
- le conteneur `strfry` déjà en marche sur `backend-relais` (page « Installer le relais strfry » du wiki, `docs/wiki/Installer-strfry.md`), ou, pour un essai du noyau seul, voir l'annexe.

Les valeurs en majuscules (`https://github.com/zobrak/paresia.git`, `CLE_PUBLIQUE_TUNNEL`…) sont à remplacer par les vôtres ou par ce que vos scripts affichent.

L'installation se fait en trois passes, car chaque machine a besoin d'une valeur produite par l'autre : `backend-admin`, puis `backend-relais`, puis `backend-admin` de nouveau.

## 1. Installer git sur backend-admin

Machine : `backend-admin`, en root.

```
apt install git
```

Résultat attendu : `git --version` affiche une version.

## 2. Récupérer le dépôt sur backend-admin

Machine : `backend-admin`, en root.

```
git clone https://github.com/zobrak/paresia.git paresia
```

```
cd paresia
cat VERSION
```

Résultat attendu : un numéro de version. Le dépôt est dans `~/paresia`.

## 3. Installer les paquets de backend-admin

Machine : `backend-admin`, en root.

```
apt install ca-certificates python3 python3-cryptography curl openssh-client openssh-server iproute2
```

Résultat attendu : aucune erreur.

## 4. Préparer le compte de backend-relais

Machine : `backend-relais`, en root.

```
apt install sudo
```

```
usermod -aG sudo VOTRE_COMPTE
```

Remplacez `VOTRE_COMPTE` par votre compte ordinaire. Fermez la session, puis ouvrez-en une avec ce compte : le script du relais refuse de tourner en root.

Résultat attendu : `sudo true` s'exécute sans erreur.

## 5. Récupérer le dépôt sur backend-relais

Machine : `backend-relais`, avec votre compte.

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

Résultat attendu : le même numéro de version que sur `backend-admin`.

## 6. Installer les paquets de backend-relais

Machine : `backend-relais`, avec votre compte.

```
sudo apt install ca-certificates python3 nftables openssh-client openssh-server iproute2
```

Résultat attendu : aucune erreur.

## 7. Contrôler que strfry tourne

Machine : `backend-relais`.

```
sudo docker ps --filter name=^strfry$
```

Résultat attendu : une ligne pour le conteneur `strfry`. Sinon, revenez à la page strfry du wiki avant de continuer.

## 8. Vérifier backend-admin

Machine : `backend-admin`, en root, dans `~/paresia`. La commande ne modifie rien.

```
cd ~/paresia
bash deploy/backend-admin/installer-backend-admin.sh --verifier
```

Résultat attendu : aucun message d'erreur. Un prérequis manquant arrête le script (code 69) et le nomme.

## 9. Passe 1 : installer backend-admin

Machine : `backend-admin`, en root, dans `~/paresia`. Le script fait une pause après chaque étape et exige un terminal.

```
bash deploy/backend-admin/installer-backend-admin.sh --alpha-test --session-secours oui
```

Résultat attendu : à la fin, deux lignes à copier telles quelles pour l'étape 11.

```
CLE_PUBLIQUE_TUNNEL=ssh-ed25519 AAAA…
EMPREINTE_CLE_TUNNEL=SHA256:…
```

Notez aussi le nom du jeu de sauvegarde affiché (`/var/backups/paresia/admin/AAAAMMJJ-HHMMSS`) : il sert au retour arrière.

## 10. Vérifier backend-relais

Machine : `backend-relais`, avec votre compte, dans `~/paresia`. La commande ne modifie rien.

```
cd ~/paresia
bash deploy/backend-relais/installer-backend-relais.sh --verifier
```

Résultat attendu : aucun message d'erreur.

## 11. Passe 2 : installer backend-relais

Machine : `backend-relais`, avec votre compte (sans `sudo` devant), dans `~/paresia`. Remplacez les trois valeurs par celles de l'étape 9 : ce qui suit le signe `=`, copié sans retranscrire.

```
bash deploy/backend-relais/installer-backend-relais.sh --alpha-test --session-secours oui \
  --adresse-admin 192.0.2.10 \
  --cle-publique-tunnel 'CLE_PUBLIQUE_TUNNEL' \
  --empreinte-cle-tunnel 'EMPREINTE_CLE_TUNNEL'
```

Résultat attendu : à la fin, une ligne à noter pour l'étape 12.

```
EMPREINTE_HOTE_RELAIS=SHA256:…
```

Transmettez-la à `backend-admin` par un autre canal que le tunnel, par exemple en la lisant sur la console de la machine.

## 12. Passe 3 : le tunnel sur backend-admin

Machine : `backend-admin`, en root, dans `~/paresia`. Les adresses sont des adresses IP, non des noms.

```
bash deploy/backend-admin/installer-backend-admin.sh --alpha-test --session-secours oui \
  --adresse-relais 192.0.2.20 \
  --empreinte-hote-relais 'EMPREINTE_HOTE_RELAIS'
```

Résultat attendu : le script compare l'empreinte à celle que lit `ssh-keyscan` sur le relais, puis pose le tunnel et le démarre. Une différence l'arrête.

## 13. Vérifier backend-admin

Machine : `backend-admin`, en root.

```
systemctl status pollux.service romulus.service paresia-tunnel.service
```

Résultat attendu : les trois unités sont `active`.

```
ss -xl | grep paresia-tunnel
```

Résultat attendu : deux sockets, `/run/paresia-tunnel/romulus/remus.sock` et `/run/paresia-tunnel/pollux/castor.sock`.

## 14. Vérifier backend-relais

Machine : `backend-relais`, avec votre compte.

```
sudo /usr/bin/systemctl status castor.service remus.service
```

Résultat attendu : les deux unités sont `active`.

## 15. Activer au démarrage

Quand tout est conforme, relancez chaque script avec `--activer` et les mêmes paramètres qu'aux étapes 11 et 12. Machine : `backend-relais` d'abord, dans `~/paresia`.

```
bash deploy/backend-relais/installer-backend-relais.sh --alpha-test --session-secours oui --activer \
  --adresse-admin 192.0.2.10 \
  --cle-publique-tunnel 'CLE_PUBLIQUE_TUNNEL' \
  --empreinte-cle-tunnel 'EMPREINTE_CLE_TUNNEL'
```

Puis sur `backend-admin`, en root, dans `~/paresia` :

```
bash deploy/backend-admin/installer-backend-admin.sh --alpha-test --session-secours oui --activer \
  --adresse-relais 192.0.2.20 \
  --empreinte-hote-relais 'EMPREINTE_HOTE_RELAIS'
```

Résultat attendu : « déjà en place » pour tout ce qui est conforme.

## 16. Autoriser la clé d'un administrateur

Machine : `backend-admin`, en root. Le fichier `/var/lib/paresia-app/.ssh/authorized_keys` est créé vide. Ajoutez-y une ligne par administrateur.

```
echo 'restrict,command="/usr/local/bin/pollux-session" ssh-ed25519 CLE_PUBLIQUE_ADMIN COMMENTAIRE' >> /var/lib/paresia-app/.ssh/authorized_keys
```

`CLE_PUBLIQUE_ADMIN` est la clé **publique** de l'administrateur ; `COMMENTAIRE` un nom court (1 à 64 caractères : lettres, chiffres, `.`, `_`, `@`, `-`). L'application Paresia-admin affiche cette ligne (menu « Ligne de clé à remettre »).

Résultat attendu :

```
ls -l /var/lib/paresia-app/.ssh/authorized_keys
```

montre `root root` et les droits `-rw-r--r--`. Un autre propriétaire fait refuser la connexion.

## Suite

- Premier usage : `docs/wiki/Premier-usage.md`.
- Mise à jour d'une installation existante : annexe A.
- Retour arrière : annexe B.

## Annexe A : mettre à jour une installation existante

Chaque machine se met à jour séparément, avec le même script et `--mise-a-jour`, depuis un clone propre de la version voulue. Machine : celle à mettre à jour, dans le nouveau clone.

```
bash deploy/backend-<machine>/installer-backend-<machine>.sh --verifier
```

```
bash deploy/backend-<machine>/installer-backend-<machine>.sh --mise-a-jour --session-secours oui
```

Ouvrez et testez d'abord une session de secours. Relisez `CHANGELOG.md` avant de lancer.

- **Interruption.** Demander la mise à jour vaut accepter l'arrêt des unités de Paresia : sur `backend-admin`, Pollux puis Romulus ; sur `backend-relais`, Remus puis Castor. strfry, Docker, lighttpd et bunkerd ne sont jamais touchés. L'activation au démarrage n'est pas modifiée.
- **Tunnel.** Sur `backend-admin`, la partie tunnel n'est mise à jour que si vous redonnez `--adresse-relais` et `--empreinte-hote-relais`. Sur `backend-relais`, il faut redonner `--adresse-admin`, `--cle-publique-tunnel` et `--empreinte-cle-tunnel`.
- **Versions.** Le script affiche « installée X, livrée Y ». Une version livrée plus ancienne, un fichier de version illisible ou un format de sauvegarde incompatible : refus (code 78) avant toute modification.
- **Configuration.** Un fichier de `/etc/paresia` inchangé est remplacé ; un fichier que vous avez modifié est conservé, la version livrée étant déposée à côté en `<fichier>.paresia-nouveau`. Pour une installation faite avec une version plus ancienne, tout fichier qui diffère est conservé : comparez-le à son `.paresia-nouveau`.
- **Échec d'une vérification.** Retour arrière automatique du code et de la configuration, sortie 78 avec le nom du jeu.
- **Données.** Les scripts ne migrent aucune donnée ; chaque démon migre les siennes au démarrage. Si le journal montre une migration (`state_migrated`) ou est illisible, rien n'est restauré : le retour arrière est alors manuel.
- **Relais.** La table `nftables` d'une installation existante n'est jamais modifiée (un écart est signalé). Si Pollux ou Romulus tournent sur la même machine, le script refuse : arrêtez-les d'abord.
- `--mise-a-jour` ne se combine pas avec `--retour-arriere` ni `--verifier` (code 64).

## Annexe B : retour arrière

```
bash deploy/backend-<machine>/installer-backend-<machine>.sh --retour-arriere --jeu AAAAMMJJ-HHMMSS --confirme
```

`--jeu` et `--confirme` sont obligatoires. Le script restaure dans l'ordre inverse de la pose et ne supprime que les comptes créés par l'installation. Détail : `docs/wiki/Sauvegarde-et-retour-arriere.md`.

## Annexe C : réserves et variantes

- **Root et sudo.** Sur `backend-admin`, le script exige l'UID 0 ; lancé par `sudo`, il convient aussi (déduit du code, non essayé). Sur `backend-relais`, il refuse root et appelle lui-même `sudo` (1.9.10 au moins ; Debian 13 fournit la 1.9.16).
- **Rejouable.** Une étape déjà conforme ne fait rien ; un état qui diffère est refusé (code 78), jamais écrasé. Les unités sont démarrées par `start`, jamais `restart`.
- **Essai du noyau seul, sans strfry.** Ajoutez `--sauter produit` aux commandes du relais ; sautez l'étape 7.
- **Image strfry.** Le conteneur doit s'appeler `strfry` et venir de `z0brak/paresia-yin-strfry:4cd3cf6` ; sinon le script s'arrête avant toute modification (code 78).
- **Serveur web et proxy.** Paresia n'installe ni lighttpd ni HAProxy. Les exigences sont dans `docs/serveur-web.md`. Les pages à servir sont sous `/usr/local/share/paresia/web/`. Sans serveur web, un poste distant ne joint pas l'API.
- **Non livré.** Installation des deux machines en une seule commande ; unités de bunkerd et de Nisaba ; page d'administration du relais dans le client. Le mode `--alpha-test` est temporaire.
- **Poste de l'administrateur.** L'application se lance par `python3 -m admin.app` ; elle exige PyQt6 avec QtWebEngine, un agent SSH actif et `openssh-client` (`docs/prerequis.md`, § 4). Essai de bout en bout : `deploy/essai-presence.md`.
- **Références.** Raisons des choix : `docs/wiki/Installation.md`. Prérequis : `docs/prerequis.md`. Manuel : `installer-backend-admin(8)` et `installer-backend-relais(8)`.
