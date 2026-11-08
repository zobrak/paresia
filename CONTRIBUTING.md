# Contribuer à Paresia

Version du document : 0.1.19 · 2026-11-08.

Merci de l'intérêt que vous portez à Paresia. Ce document dit comment signaler un bogue, proposer une modification et ce que le mainteneur attend d'une contribution. Paresia est en développement (versions 0.x) : les interfaces peuvent changer.

Mots normatifs (DOIT, DEVRAIT, PEUT) : sens des RFC 2119 et RFC 8174.

## Sommaire

1. Signaler un bogue
2. Proposer une modification
3. Licence et origine des contributions
4. Sécurité
5. Données personnelles et secrets
6. Documentation de référence

## 1. Signaler un bogue

Avant d'ouvrir un ticket, vérifiez qu'il n'existe pas déjà, et lisez le `CHANGELOG.md` et `SECURITY.md` (changements récents, limites connues). La liste des travaux prévus est tenue par le mainteneur ; en cas de doute, demandez dans le ticket.

Un ticket DEVRAIT contenir :

- la version (fichier `VERSION`) et le commit, si vous travaillez sur le dépôt ;
- le système (Paresia vise Debian 13) et le composant concerné ;
- les étapes pour reproduire, le résultat obtenu et le résultat attendu ;
- les lignes de journal utiles, après retrait de tout secret et de toute donnée personnelle (§ 5).

Une faille de sécurité ne se signale pas par un ticket public : voir le § 4.

## 2. Proposer une modification

Pour une modification importante (nouvelle fonctionnalité, changement d'interface ou de protocole), ouvrez d'abord un ticket afin d'en discuter avec le mainteneur. Le périmètre du projet est fixé par `docs/cahier-des-charges.md` ; une idée hors de ce périmètre peut être différée.

### Branches et demandes de fusion

- `main` est la branche des versions publiées ; elle est gérée par le mainteneur. N'y proposez rien directement.
- Dupliquez le dépôt (fork), créez une branche par sujet, puis ouvrez une demande de fusion (pull request) vers la branche de développement indiquée par le mainteneur dans le ticket ou la description du dépôt.
- Une demande de fusion traite un seul sujet. Ne réécrivez pas l'historique d'une branche déjà publiée.

### Commits

- Des commits atomiques, avec un message en français : une première ligne courte, à l'impératif (par exemple « Ajoute la vérification du jeton à Romulus »), puis, si utile, un corps qui explique le pourquoi.
- Avant chaque commit, lancez `python3 tools/hooks/scan_secrets.py --staged` : il refuse un secret ou une référence à une installation privée dans les fichiers indexés. Le crochet `tools/hooks/pre-commit` (activé par `git config core.hooksPath tools/hooks`) appelle le même outil en mode strict, qui exige en plus un fichier local de motifs privés tenu par le mainteneur. Sans ce fichier, désactivez le mode strict par `git config paresia.gardeStricte false` : le crochet applique alors les secrets et les motifs génériques seuls (voir `docs/developpement.md`, § 5.1).

### Tests

- La suite se lance depuis la racine du dépôt : `python3 -m pytest -q` (configuration dans `pytest.ini`, tests dans `tests/`).
- Tout correctif ou toute fonctionnalité DOIT s'accompagner de tests. Les clés et identités de test sont générées pour l'occasion ; les tests n'ouvrent aucune connexion réseau sortante et lancent les démons sur des sockets temporaires.
- L'intégration continue (`.github/workflows/ci.yml`) rejoue la recherche de secrets, la suite de tests sous Debian 13 et un compte non privilégié, puis un banc d'essai à conteneurs. Une demande de fusion dont la CI est rouge ne sera pas fusionnée.

### Style

- Python 3.13 (Debian 13), bibliothèque standard d'abord ; sinon paquet Debian 13 ; sinon dépendance épinglée, sous licence compatible avec AGPL-3.0-or-later et mentionnée dans `docs/licences-tierces.md`. Aucune dépendance ni outil requis ne DOIT être propriétaire.
- Identifiants de code (fonctions, variables, classes) en français, comme dans le code existant ; noms de démons, de composants et de fichiers en minuscules (`docs/conventions.md`, § Code).
- Commentaires, messages de commit, tickets et documentation en français.
- Chaque fichier source porte l'en-tête `SPDX-License-Identifier: AGPL-3.0-or-later`.
- Aucune valeur propre à une machine en dur (chemins, hôtes, ports) : fichier de configuration, puis variables d'environnement (`docs/configuration.md`).
- Aucun texte affiché en dur : les messages passent par les catalogues `i18n/<langue>.json`. Les démons renvoient des codes d'erreur stables. Tout texte reçu de l'extérieur est nettoyé des caractères de contrôle avant affichage.
- Refus par défaut ; entrées validées par liste blanche ; comparaisons de jetons en temps constant ; aucun secret en argument de commande ni dans un journal.
- Exemples et documentation : noms génériques (`backend-admin`, `backend-relais`, `pare-feu`, `poste client`), adresses de la RFC 5737 (ou RFC 3849), domaines de la RFC 2606 (`bunker.example.org`).

### Documentation

Toute option, variable de configuration, code d'erreur, commande ou démon ajouté ou modifié DOIT être documenté dans la même demande de fusion : page de manuel au format mdoc dans `docs/man/` (sections 1, 5 et 8), document concerné de `docs/`, et entrée dans `CHANGELOG.md` (Keep a Changelog 1.1.0, dates ISO 8601). Les normes à citer sont listées dans `docs/conventions.md`, § Normes et usages de référence. Le mainteneur ajuste `VERSION` ; ne la modifiez pas, sauf demande.

## 3. Licence et origine des contributions

Paresia est publié sous AGPL-3.0-or-later (fichier `LICENSE`). En soumettant une contribution, vous déclarez :

- en être l'auteur, ou avoir le droit de la soumettre ;
- l'accepter sous AGPL-3.0-or-later ;
- ne reprendre aucun code ni contenu dont la licence serait incompatible. Indiquez la source et la licence de tout élément tiers.

Une contribution reste de la responsabilité de son auteur, qu'elle ait été écrite avec ou sans outil d'IA : vous répondez de ce que vous soumettez, de son exactitude et de sa licence. Paresia lui-même est développé avec l'aide d'outils d'IA (voir le `README.md`, section « Développement assisté par IA »).

Les dépendances et leurs licences sont recensées dans `docs/licences-tierces.md`.

## 4. Sécurité

Ne signalez jamais une vulnérabilité par un ticket, une demande de fusion ou une discussion publics. Suivez la procédure de `SECURITY.md`, qui décrit aussi le modèle de menace.

## 5. Données personnelles et secrets

Un ticket, un journal joint ou un correctif ne DOIT contenir :

- aucun secret : clé privée, `nsec`, `ncryptsec`, phrase secrète, mot de passe, jeton ;
- aucune donnée personnelle, ni référence à votre installation (noms d'hôtes, adresses, domaines, comptes, chemins personnels).

Remplacez ces éléments par des valeurs d'exemple. Si un secret a été publié par erreur, considérez-le comme compromis et révoquez-le.

## 6. Documentation de référence

| Sujet | Document |
| --- | --- |
| Périmètre et architecture | `docs/cahier-des-charges.md` |
| Protocole entre composants | `docs/protocole.md` |
| Conventions de code, de tests et de documentation | `docs/conventions.md` |
| Configuration | `docs/configuration.md` |
| Outillage de développement | `docs/developpement.md` |
| Décisions de conception | `docs/decisions.md` |
| Index de la documentation | `docs/README.md` |
