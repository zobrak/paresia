# Pages de manuel

Version du document : 0.1.19 · 2026-11-08.

Référence : man-pages(7) pour les sections et la structure générale ; mdoc(7) pour le format retenu par le projet (`docs/conventions.md`).

## Pages écrites

Les pages décrivent l'**état actuel du code** des composants fusionnés dans `alpha`. Pollux, Romulus, Castor, Remus et Nisaba sont sur le socle commun (`Type=notify`, `--check`, `--debug`, `--version`, `--help`, codes `sysexits`, sections `[<démon>.journal]` et `[<démon>.metriques]`) depuis 0.1.6, bunkerd depuis 0.1.10 ; leurs pages le décrivent. `sauvegarde` et `nisaba-ctl` reconnaissent `--help` et `--version` comme argument unique (0.1.10).

| Page | Objet |
| --- | --- |
| `paresia-pollux.8` | Pollux, session de présence (backend-admin) |
| `paresia-romulus.8` | Romulus, point de contact HTTP et présence (backend-admin) |
| `paresia-tunnel.8` | tunnel SSH, `tmpfiles.d`, sockets (backend-admin vers backend-relais) |
| `paresia-bunkerd.8` | bunkerd, superviseur de signataires NIP-46 (backend-admin) |
| `paresia-nisaba.8` | Nisaba, processus annexe du journal légal (backend-admin) |
| `journal-legal.8` | scripts d'origine `journal-legal-pull`, `-seal`, `-acl`, `-purge` (backend-admin) |
| `paresia-romulus-pages.8` | outil qui génère et vérifie l'index des pages des greffons (backend-admin) |
| `paresia-castor.8` | Castor, feu de session (backend-relais) |
| `paresia-remus.8` | Remus enfiché : fonctions livrées et locales, manifeste, `[remus.plugins]`, `sudoers` généré (backend-relais) |
| `paresia-sauvegarde.8` | outil de sauvegarde et de restauration des procédures |
| `pollux-session.1` | relais SSH de présence (commande forcée du compte `app`) |
| `paresia-admin.1` | Paresia-admin, poste client : configuration et ouverture de présence par défi signé (fenêtre ; pages d'administration à venir) |
| `nisaba-ctl.1` | contrôle de Nisaba (`status`, `verify`, `run`, `metrics`, `acl`) |
| `installer-backend-admin.8` | script d'installation de backend-admin |
| `installer-backend-relais.8` | script d'installation de backend-relais |
| `paresia.conf.5` | configuration en couches, sections, variables d'environnement |

À rédiger avec le code qu'elles décrivent : la suite de `paresia-admin.1` (pages d'administration), `bunker.json.5`, et la page de `bunkerctl` (aucun `bunkerctl` n'est dans le dépôt : la socket de contrôle de bunkerd n'a pas de client livré).

Guide d'exploitation, qui renvoie à ces pages : `docs/exploitation.md`.

## Format et conventions

Format mdoc (`man 7 mdoc`), une page par fichier, nommée `<nom>.<section>`. Sections : 1 commandes utilisateur, 5 formats de fichiers, 8 démons et administration.

Contenu : NAME, SYNOPSIS, DESCRIPTION, OPTIONS, ENVIRONMENT, FILES, EXIT STATUS, DIAGNOSTICS (événements du journal), SECURITY (compte, groupes, `SO_PEERCRED`, durcissement de l'unité), SEE ALSO. Les chemins, uid et gid des exemples sont des illustrations : le code n'en fixe aucun.

Ce que le code n'établit pas est écrit comme tel dans la page (par exemple : unité systemd de bunkerd et de Nisaba, absente de `deploy/`).

## Lire une page

```
man -l docs/man/paresia-castor.8
```

## Installer les pages

Procédure standard (FHS 3.0) : pages dans `/usr/local/share/man/man<section>/`, puis mise à jour de l'index.

```
sudo install -d -m 0755 /usr/local/share/man/man1 /usr/local/share/man/man5 /usr/local/share/man/man8
sudo install -m 0644 docs/man/*.1 /usr/local/share/man/man1/
sudo install -m 0644 docs/man/*.5 /usr/local/share/man/man5/
sudo install -m 0644 docs/man/*.8 /usr/local/share/man/man8/
sudo mandb
```

L'installation des pages par un paquet n'est pas décidée.

## Vérification

`mandoc -T lint <page>` sans avertissement ; aperçu : `man -l <page>`. À défaut de `mandoc`, les pages ont été vérifiées avec `groff -K utf8 -mdoc -z -ww <page>` : aucune alerte, hors « cannot adjust line ». Un `mandoc -T lint` reste à lancer quand l'outil est disponible.

Une page est mise à jour avec le code qu'elle décrit.
