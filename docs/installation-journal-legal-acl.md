# Installation des scripts `journal-legal-*` (pull 1.2.1, seal 1.3.0, acl 1.1.0, purge 1.1.0 ; modes et ACL, D22, D24)

Version du document : 0.1.16 · 2026-11-08 · public : administrateur.

Procédure à exécuter **par vous seul, sur yang (`backend-admin` dans les noms de scripts et de dossiers), en root, une étape à la fois**.
Lisez le résultat de chaque étape avant de passer à la suivante : une étape qui a échoué
sans que vous le voyiez fausserait les suivantes. Pour l'installation complète de yang, voir
[INSTALL.md](../INSTALL.md). Les commandes destructives sont précédées d'un
**Avertissement** ; les autres sont en lecture seule ou réversibles.

Objet : le compte `paresia-romulus` (Romulus) doit lire le journal légal **en lecture
seule, par ACL, sans groupe** (D22). Les scripts fixent désormais explicitement modes et
ACL (D24 : chaque `chmod` est suivi d'un `setfacl`, car un `chmod` recalcule le masque
et neutraliserait l'ACL). Livrables (dossier `deploy/backend-admin/usr/local/sbin/` du
dépôt) :

| Script | Version | Rôle |
| --- | --- | --- |
| `journal-legal-pull.sh` | 1.2.1 | copie ; mode 0640 et ACL des journaux non scellés ; `PATH` fixe |
| `journal-legal-seal.sh` | 1.3.0 | scellement ; modes/ACL de `MANIFEST`, `seals/` ; `--verifier` utilisable sans privilège |
| `journal-legal-purge.sh` | 1.1.0 | inchangé (aucun fichier créé) ; à réinstaller seulement si vous le souhaitez |
| `journal-legal-acl.sh` | 1.1.0 | nouveau : `--appliquer` (existant) et `--verifier` (ACL, lecture effective, attributs `i` et `a`) |

Droits visés (propriétaire `root`, aucune entrée pour d'autres comptes, `other::---`) :

| Élément | Mode | ACL nommée `paresia-romulus` | ACL par défaut |
| --- | --- | --- | --- |
| `/var/log/paresia` | 0700 | `x` | aucune |
| `/var/log/paresia/journal-legal` | 0700 | `rx` | `r` |
| `journal-AAAA-MM-JJ.jsonl` | 0640 | `r` | — |
| `MANIFEST` | 0600 | `r` | — |
| `seals/` | 0700 | `rx` | `r` |
| `seals/<D>.txt`, `seals/<D>.txt.ots` | 0600 | `r` | — |

Avec une ACL nommée, le groupe affiché par `ls -l` et `stat` est le **masque**, non le
groupe propriétaire : un fichier 0600 avec ACL s'affiche donc `-rw-r-----`. C'est normal ;
le contrôle se fait avec `getfacl`, jamais avec les seuls bits de `ls`.

## Étape 1 — Prérequis

Vérifiez les outils et le compte (rien n'est modifié si tout est présent).

```sh
command -v setfacl getfacl chattr lsattr runuser flock logger
getent passwd paresia-romulus
```

Si une commande manque : `apt install acl e2fsprogs util-linux` (paquets Debian).
Si `getent` ne renvoie rien, le compte n'existe pas. Le script `installer-backend-admin.sh`
le crée (voir [`installer-backend-admin.8`](man/installer-backend-admin.8)) ; la procédure de bunkerd n'est pas
encore écrite. Hors de ce script, la forme usuelle est la suivante (compte système verrouillé,
sans shell de connexion, sans mot de passe, sans dossier personnel) :

```sh
useradd --system --no-create-home --shell /usr/sbin/nologin paresia-romulus
```

Contrôle : `getent passwd paresia-romulus` doit afficher une ligne.

## Étape 2 — Sauvegarde

Les relevés sont écrits **hors** du dossier du journal. Remplacez `AAAAMMJJ` par la date du jour.

```sh
for s in pull seal purge; do
  cp -p /usr/local/sbin/journal-legal-$s.sh /usr/local/sbin/journal-legal-$s.sh.bak-AAAAMMJJ
done
getfacl -R -p /var/log/paresia > /root/journal-legal-acl-avant-AAAAMMJJ.txt
find /var/log/paresia -printf '%m %p\n' > /root/journal-legal-modes-avant-AAAAMMJJ.txt
lsattr -R /var/log/paresia > /root/journal-legal-attributs-avant-AAAAMMJJ.txt 2>&1
```

Contrôle : les trois fichiers `/root/journal-legal-*-avant-AAAAMMJJ.txt` sont non vides et
les trois `*.bak-AAAAMMJJ` existent. **Conservez-les** : ils servent au retour arrière (étape 10).

## Étape 3 — Arrêt des deux minuteries

Pendant l'opération il n'y a plus ni copie ni scellement ; un scellement manqué est
rattrapé au passage suivant (les journées sont scellées dans l'ordre).

```sh
systemctl stop journal-legal-pull.timer journal-legal-seal.timer
systemctl is-active journal-legal-pull.service journal-legal-seal.service
```

Contrôle : les deux services doivent être `inactive` (sinon attendez la fin du passage en cours).

## Étape 4 — Copie des nouveaux scripts

**Avertissement : cette commande remplace les scripts installés (la sauvegarde de l'étape 2 est indispensable).** Exécutez-la depuis le dossier du dépôt qui contient `deploy/`.

```sh
for s in pull seal purge acl; do
  install -m 0755 -o root -g root deploy/backend-admin/usr/local/sbin/journal-legal-$s.sh /usr/local/sbin/journal-legal-$s.sh
done
sh -n /usr/local/sbin/journal-legal-pull.sh && sh -n /usr/local/sbin/journal-legal-seal.sh && sh -n /usr/local/sbin/journal-legal-acl.sh && echo syntaxe-ok
```

Le script `journal-legal-purge.sh` est livré à l'identique de la 1.1.0 (seuls des noms
génériques changent dans les commentaires) : vous pouvez aussi conserver le vôtre.

## Étape 5 — Adaptation des variables de tête

Les scripts livrés portent des valeurs génériques en tête (une variable par ligne). Relevez-les :

```sh
grep -n '^SOURCE=\|^SSH_KEY=\|^ACL_USER=' /usr/local/sbin/journal-legal-pull.sh /usr/local/sbin/journal-legal-seal.sh
```

Éditez **les deux scripts** (`pull` et `seal`) avec votre éditeur pour remplacer :

- `SOURCE` : `journalpull@192.0.2.200:/` par la vraie adresse de yin (reprenez la valeur de vos scripts sauvegardés à l'étape 2) ;
- `SSH_KEY` : `/root/.ssh/journal_legal_pull` par le chemin de la clé **actuellement en place** (même valeur que dans vos scripts sauvegardés). Vous conservez ainsi le nom de fichier existant en ne modifiant que la variable. Variante : renommer le fichier de clé en `/root/.ssh/journal_legal_pull` ; elle n'est pas recommandée (la clé peut être référencée ailleurs, par exemple dans `/root/.ssh/config`) ;
- `ACL_USER` : laissez `paresia-romulus` (D21).

Ne modifiez pas les autres variables. Contrôle : relancez la commande `grep` ci-dessus, puis `sh -n` sur les deux scripts.

## Étape 6 — Pose des modes et ACL sur l'existant

**Avertissement : cette commande retire puis rétablit temporairement l'immutabilité (`chattr -i`) des journaux et des fichiers de `seals/` déjà scellés, et l'attribut « ajout seul » (`chattr -a`) du `MANIFEST`, un fichier à la fois (rétablissement garanti par `trap`, même si vous l'interrompez par Ctrl-C). Les minuteries doivent être arrêtées (étape 3). Aucun contenu n'est modifié. Si le script s'arrête sur un message `rétablissement … IMPOSSIBLE` suivi de `ARRÊT`, rétablissez à la main l'attribut indiqué (`chattr +i` ou `chattr +a`) avant toute autre action. Le répertoire `/var/log/paresia` lui-même reçoit aussi `chmod 0700` puis `setfacl -b` avant la pose de l'ACL : tout ACL préexistant sur ce dossier est effacé, et un autre composant, non root, qui y écrit des journaux perdrait son accès (le relevé `getfacl -R` de l'étape 2 permet de le rétablir).**

```sh
/usr/local/sbin/journal-legal-acl.sh --appliquer
```

Le script s'arrête de lui-même si `journal-legal-pull` ou `-seal` tourne (verrou). Il est
idempotent : un élément déjà conforme n'est pas touché. Chaque élément traité est tracé
dans syslog (`journalctl -t journal-legal-acl`). Code de sortie non nul = au moins un
`ECHEC_ACL` : lisez le message, corrigez, relancez. Si le script s'arrête sur `ARRÊT`
(rétablissement d'un attribut impossible), aucun autre fichier n'est traité : rétablissez
l'attribut à la main, puis relancez `--appliquer`.

Relevé des attributs **après** l'opération, à comparer au relevé « avant » de l'étape 2
(seules les ACL et modes doivent différer, jamais les attributs `i` et `a`) :

```sh
lsattr -R /var/log/paresia > /root/journal-legal-attributs-apres-AAAAMMJJ.txt 2>&1
diff /root/journal-legal-attributs-avant-AAAAMMJJ.txt /root/journal-legal-attributs-apres-AAAAMMJJ.txt && echo attributs-identiques
```

Après tout arrêt brutal (coupure d'alimentation, `kill -9`, mémoire saturée) pendant
`--appliquer`, le rétablissement par `trap` n'a pas pu s'exécuter : un fichier peut être
resté déverrouillé. Relancez `--appliquer` (idempotent, il rétablit les attributs des
éléments qu'il traite), puis `--verifier` (étape 7), qui contrôle les attributs.

Hypothèse à confirmer ici : un attribut `i` (selon `chattr(1)`, les métadonnées du fichier
ne peuvent plus être modifiées) ou `a` interdit de changer l'ACL, d'où le retrait préalable
dans `--appliquer` et l'ordre « `setfacl` puis `chattr +a` » dans `journal-legal-seal.sh`.
Si `--appliquer` réussit sur le `MANIFEST` sans retrait préalable d'`a`, ou si `setfacl`
échoue malgré le retrait, signalez-le : l'ordre serait à revoir.

## Étape 7 — Contrôle des ACL et de la lecture effective

Lecture seule.

```sh
/usr/local/sbin/journal-legal-acl.sh --verifier
```

Attendu : des lignes `OK …` et `RÉSULTAT : conforme` (code 0). Toute ligne `ERREUR …` est
détaillée (entrée ACL manquante ou non prévue, propriétaire, lecture refusée à
`paresia-romulus`, attribut manquant : `MANIFEST` sans `a`, journal inscrit au `MANIFEST`
ou `seals/*.txt` sans `i`). Vous pouvez aussi regarder un élément à la main :

```sh
getfacl -p /var/log/paresia/journal-legal/MANIFEST
```

Attendu : `user::rw-`, `user:paresia-romulus:r--`, `group::---`, `mask::r--`, `other::---`.

## Étape 8 — Comparaison de `--verifier` sous root et sous `paresia-romulus`

Lecture seule, aucun avertissement nécessaire. Les deux sorties doivent être identiques.

```sh
/usr/local/sbin/journal-legal-seal.sh --verifier > /root/verif-root.txt; echo "code root : $?"
runuser -u paresia-romulus -- /usr/local/sbin/journal-legal-seal.sh --verifier > /root/verif-romulus.txt; echo "code romulus : $?"
diff /root/verif-root.txt /root/verif-romulus.txt && echo identiques
```

Attendu : mêmes codes, `identiques`. Une ligne `ERREUR … lecture impossible … (droits ou ACL
manquants)` sous `paresia-romulus` signale une ACL absente : relancez l'étape 6 ou 7. Si
`lsattr` échoue sous ce compte (`attributs illisibles`), signalez-le au mainteneur.
Vérifiez enfin la lecture de chaque élément du tableau ci-dessus (l'étape 7 le fait pour le
dernier journal, `MANIFEST`, le dernier `seals/*.txt` et `*.ots`).

## Étape 9 — Relance des minuteries et contrôles

```sh
systemctl start journal-legal-pull.timer journal-legal-seal.timer
systemctl list-timers 'journal-legal-*'
```

Après une minute, contrôlez un passage de `pull` : mode et ACL du journal du jour, et
absence d'alerte.

```sh
ls -l /var/log/paresia/journal-legal/ | tail -n 3
getfacl -p /var/log/paresia/journal-legal/journal-$(date -u +%Y-%m-%d).jsonl
journalctl -t journal-legal-pull --since '10 minutes ago' | grep -E 'ECHEC' || echo aucune-alerte
```

Attendu pour le journal du jour : `user:paresia-romulus:r--`, `group::r--`, `mask::r--`,
`other::---`. **Le lendemain**, contrôlez le premier scellement (`MANIFEST` et `seals/` créés
ou mis à jour sans `ECHEC_ACL`), puis relancez l'étape 7 :

```sh
journalctl -t journal-legal-seal --since yesterday | grep -E 'ECHEC|SCELLE'
/usr/local/sbin/journal-legal-acl.sh --verifier
systemctl status journal-legal-seal.service
```

Un `ECHEC_ACL` met le service en échec dans `systemctl status` (code non nul) sans
interrompre le scellement ; corrigez la cause, lancez l'étape 6 puis **toujours** l'étape 7
(`journal-legal-acl.sh --verifier`). Cela vaut aussi pour le `MANIFEST` : son ACL n'est posée
qu'à sa création, un `ECHEC_ACL` à ce moment n'est pas retenté par les scellements suivants,
et Romulus ne pourrait plus le lire.

## Étape 10 — Retour arrière

À n'effectuer qu'en cas de problème, minuteries arrêtées :

```sh
systemctl stop journal-legal-pull.timer journal-legal-seal.timer
```

**Avertissement : la commande suivante remplace les scripts installés par les sauvegardes de l'étape 2.** Remplacez `AAAAMMJJ` par la date de vos sauvegardes.

```sh
# RESTAURATION des scripts
for s in pull seal purge; do
  cp -p /usr/local/sbin/journal-legal-$s.sh.bak-AAAAMMJJ /usr/local/sbin/journal-legal-$s.sh
done
rm -f /usr/local/sbin/journal-legal-acl.sh
```

Les ACL posées donnent seulement la lecture à `paresia-romulus` ; les laisser en place est
sans danger pour l'ancien fonctionnement, mais Romulus ne doit plus être utilisé pour le
journal légal. Pour les retirer, **un fichier à la fois** :

**Avertissement : `setfacl -b` est irréversible (il efface toutes les entrées ACL étendues du fichier) ; n'effectuez ce retrait qu'avec les relevés de l'étape 2 sous la main : le mode d'origine de chaque fichier est dans `/root/journal-legal-modes-avant-AAAAMMJJ.txt` et ses attributs dans `/root/journal-legal-attributs-avant-AAAAMMJJ.txt`. Un fichier scellé (`i`) ou en ajout seul (`a`) refuse la modification : il faut retirer l'attribut, retirer l'ACL, rétablir le mode d'origine, puis rétablir l'attribut. Essayez d'abord sur UN seul fichier ; ne lancez pas de boucle sur tout le dossier sans l'avoir comprise.**

```sh
# Exemple pour UN fichier scellé (adaptez le chemin et MODE : lisez-le dans le relevé des modes).
f=/var/log/paresia/journal-legal/journal-AAAA-MM-JJ.jsonl
chattr -i -- "$f" && setfacl -b -- "$f" && chmod MODE -- "$f" ; chattr +i -- "$f"
# Fichier du MANIFEST (ajout seul) : même suite avec -a puis +a.
```

La ligne `chattr +i` s'exécute même en cas d'échec d'une commande précédente, pour ne
jamais laisser le fichier déverrouillé. Pour les dossiers (`/var/log/paresia`, `journal-legal`,
`seals`), même suite sans attribut ; `setfacl -b` retire aussi l'ACL par défaut (`-k` la retire
seule) ; rétablissez ensuite le mode relevé (`chmod`). Comparez enfin avec `getfacl -R -p /var/log/paresia` et votre relevé d'origine.

Pour terminer, relancez les minuteries arrêtées au début de cette étape :

```sh
systemctl start journal-legal-pull.timer journal-legal-seal.timer
systemctl list-timers 'journal-legal-*'
```
