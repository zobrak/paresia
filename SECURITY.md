# SECURITY — Paresia

Version du document : 0.1.19 · 2026-11-08. Version provisoire : le modèle de menace complet reste à rédiger.

Paresia est développé avec l'aide d'outils d'IA et n'a fait l'objet d'aucun audit de sécurité externe : il peut contenir des erreurs, y compris de sécurité. Voir le `README.md`, section « Développement assisté par IA ».

## Signaler une vulnérabilité

Ne pas ouvrir de ticket public. Écrire au mainteneur (paresia@zobrak.net).

Versions prises en charge : à définir avant la publication (projet en alpha : seule la dernière version est suivie). Un fichier `security.txt` conforme à la RFC 9116 est prévu à la publication.

## Actifs à protéger

| Actif | Où | Protection |
| --- | --- | --- |
| ncryptsec des identités | backend-admin, `/var/lib/nostr-bunker` (0700, `nostr-bunker`) | chiffré ; jamais renvoyé ni journalisé |
| clés déchiffrées | mémoire de bunkerd / nak | durée limitée par le verrouillage automatique |
| passphrases | gestionnaire de mots de passe de l'administrateur | saisies, jamais écrites |
| clés SSH des administrateurs | agent SSH de l'administrateur (par exemple servi par un gestionnaire de mots de passe) | une par administrateur, compte `app` sur backend-admin seulement, commande forcée `pollux-session` |
| jetons de session | mémoire de Romulus, cookie de la vue web | jamais écrits ; détruits à la fin de la session SSH ou après 90 s sans battement |
| clé du tunnel | backend-admin, compte du service `paresia-tunnel` | `from=` backend-admin ; sockets Unix de Remus et Castor accessibles au seul compte `tunnel` (contrôle `SO_PEERCRED`) ; connexions TCP du compte `tunnel` interdites par nftables sur backend-relais |
| journal légal | service journal-legal (backend-admin) | scripts `journal-legal-*`, remplacés à terme par Nisaba ; consultation en lecture seule |

## Principes

Robinet fermé par défaut, présence prouvée par clé SSH, jeton par session, liste fermée d'opérations, aucun secret dans les journaux ni en argument de commande. Détail : `docs/cahier-des-charges.md`.

## Risques résiduels

**Usurpation de l'identité de l'administrateur par `SSH_USER_AUTH` (risque résiduel connu).**
`pollux-session` retrouve le nom de l'administrateur à partir du fichier désigné par `SSH_USER_AUTH`. Tout processus du compte `app` peut forger ce fichier et la variable, donc se présenter sous un autre nom d'administrateur.

Parades décidées :

- (a) le compte `app` ne sert qu'à `pollux-session` : aucun autre service, cron ni shell utile ;
- (c) preuve par signature, en place côté serveur et côté client : à l'ouverture de session, défi aléatoire à usage unique signé sur le poste client avec la clé de l'administrateur (format SSHSIG, espace de noms `paresia-presence`), vérifié par Pollux avec la clé publique figurant dans `authorized_keys` ; un seul essai par connexion, aucune cause de refus révélée au client (`docs/protocole.md`, § 4.1).

Le nom de l'administrateur n'est une preuve d'identité qu'avec (c), donc seulement quand le client signe le défi : Paresia-admin le fait (`ssh-keygen -Y sign`, clé privée dans l'agent SSH ; `paresia-admin(1)`). Le fichier des clés autorisées DOIT appartenir à root et n'être modifiable ni par le compte `app`, ni par le groupe, ni par les autres ; son emplacement définitif et sa tenue par Romulus restent à concevoir.

**Page web publique de bunkerd (déverrouillage, sans session).** Elle n'est pas conforme à une exposition à Internet : l'URI d'inscription et le QR code, ainsi que les actions `lock`, `timeout` et `status`, sont servis sans authentification ; la limite d'essais est contournable en parallèle et son compteur est global. Tant que les corrections ne sont pas faites (jeton de session posé après le déverrouillage, compteurs par adresse et par identité, contrôle sous verrou ; prévu pour la v0.2), cette page ne doit pas être exposée sans restriction réseau (liste d'adresses admises, VPN ou tunnel). Elle reste une option, jamais activée d'office.

**Greffons : modèle de confiance actuel.** Un greffon installé est du code d'administration, et il n'est pas isolé des autres greffons dans la version 0.1. Côté serveur, le script d'un greffon de relais s'exécute sous le même compte système que Remus ; côté client, la page d'un greffon s'exécute avec les mêmes droits que le noyau de l'interface. N'installer que des greffons dont la provenance est connue. Le modèle de menace complet reste à rédiger.

## Exigences sshd (compte `app`, backend-admin)

- `ExposeAuthInfo yes`, dans le bloc `Match User app` : `pollux-session` lit `SSH_USER_AUTH`.
- `AcceptEnv` vide : le client ne transmet aucune variable d'environnement.
- `PermitUserEnvironment no`.
- `StrictModes yes`.

## Développement

- Aucun secret dans le dépôt ni dans les journaux.
- Recherche de secrets : crochet `tools/hooks/pre-commit` et CI (`tools/hooks/scan_secrets.py`). Le même outil refuse les références à une installation réelle (noms d'hôtes, adresses, domaines) ; le crochet exige un fichier local de motifs privés, tenu hors dépôt.
- Tests avec des clés générées pour l'occasion uniquement.