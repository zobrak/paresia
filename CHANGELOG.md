# Journal des modifications — Paresia

Format : « Keep a Changelog » 1.1.0, en français. Numérotation : « Semantic Versioning » 2.0.0 (`0.MINEUR.CORRECTIF` jusqu'à la 1.0.0).

Paresia est en alpha : ce journal décrit les changements visibles par un administrateur ou un contributeur.

## Développement assisté par IA

Paresia est dirigé par un mainteneur humain, qui en fixe l'orientation, les exigences et les limites. La plus grande partie du code et de la documentation est écrite par des outils d'IA (Claude Code d'Anthropic et Codex d'OpenAI), sous cette direction. Le code passe par une suite de tests automatisés et une intégration continue. Il peut contenir des erreurs, y compris de sécurité, et n'a fait l'objet d'aucun audit de sécurité externe.

## [0.1.19] - 2026-11-08

Première version publiée : une preuve de concept, à essayer sur des machines jetables, pas en production. Elle installe le noyau de Paresia sur deux machines Debian 13 et montre le principe de bout en bout.

### Ajouté
- Installation sur deux machines : `backend-admin` (Pollux, Romulus) et `backend-relais` (Castor, Remus), reliées par un tunnel SSH. Les scripts `installer-backend-admin.sh` et `installer-backend-relais.sh` ont un mode `--alpha-test` (arrêt après chaque étape, journal horodaté sans secret), un mode `--verifier` et un mode `--retour-arriere`. Guide : `INSTALL.md`.
- Mise à jour d'une installation existante par `--mise-a-jour` : arrêt des seules unités de Paresia, sauvegarde, remplacement du code, empreintes SHA-256 des fichiers de configuration (un fichier modifié est conservé et le nouveau est déposé en `.paresia-nouveau`), retour arrière automatique si une vérification échoue (`INSTALL.md`, § 12).
- Session de présence prouvée par votre clé : le client demande un défi, le fait signer par `ssh-keygen` (clé privée dans l'agent SSH) et ouvre la session avec la signature.
- Client Paresia-admin : fenêtre en profil privé, navigation limitée à l'origine configurée, indicateur à trois états (fermée, ouverte, perdue), pages État, Journaux de Paresia et Catalogue des actions.
- Greffons : Romulus aiguille selon des déclarations de services greffés ; Remus charge des fonctions enfichables, chacune avec son manifeste ; les pages des greffons sont posées et indexées par l'installation de `backend-admin` (`paresia-romulus-pages(8)`).
- Greffon strfry de base : état du relais, arbres negentropy en lecture seule, redémarrage du conteneur (`docs/plugins/strfry.md`). Le script du relais vérifie, avant toute modification, que le conteneur `strfry` existe et que son image est celle que le greffon déclare (étape `produit`, sautable par `--sauter produit`). Image : `z0brak/paresia-yin-strfry:4cd3cf6`.
- Journal d'activité de Romulus : chaque action routée laisse une trace structurée (action, session, résultat), sans secret ni valeur de paramètre.
- Journal légal : scellement, vérification et état par Nisaba ; scripts `journal-legal-pull`, `-seal`, `-acl` et `-purge` (`journal-legal(8)`). La recherche et l'export ne sont pas encore servis par HTTP (`legal/*` répond 501).
- Socle commun des démons : unités en `Type=notify`, options communes (`--check`, `--debug`, `--help`, `--version`), codes de sortie `sysexits`, métriques au format texte Prometheus, arrêt ordonné sur `SIGTERM`.
- Exigences du serveur web (lighttpd, HAProxy) : `docs/serveur-web.md`. Paresia n'installe ni l'un ni l'autre.
- Pages de manuel mdoc, guide d'exploitation (`docs/exploitation.md`) et wiki de l'administrateur.
- Le script de `backend-admin` contrôle `libssl3t64` parmi ses prérequis.

### Modifié
- Le tunnel démarre et s'arrête avec les services qui l'utilisent (`pollux.service`, `romulus.service`) ; `--activer` ne l'active plus pour lui-même.
- Les identifiants des comptes et groupes sont attribués par le système (plage système de `login.defs(5)`), sans compte sous `/home`.
- Une exception levée dans le client ne le termine plus ; le cookie est effacé et seul le nom du type d'exception est journalisé.
- Un socket de service sans uid du pair est refusé au démarrage (code 78).

### Sécurité
- Interface web du client durcie : attributs de chargement dangereux refusés, conteneur propre à chaque page, réponses d'une page quittée ignorées.
- Contrôle automatique contre les références privées avant tout commit (`CONTRIBUTING.md`).

### Limites connues
- Aucune page d'administration du relais n'existe encore dans le client ; le serveur web et le proxy sont à votre charge.
- Aucun audit de sécurité externe.
