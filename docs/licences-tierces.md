# Licences des dépendances et outils

Version du document : 0.1.16 · 2026-11-08 · public : développeur.

Projet : AGPL-3.0-or-later (`LICENSE`, décision D30). Ce document liste ce qui est vérifiable dans le dépôt (code, `.github/workflows/ci.yml`) et la licence établie à la source citée ; ce qui n'a pas pu être vérifié est marqué « non vérifié ». La vérification est une recherche factuelle ; le mainteneur ne tranche que les cas d'incompatibilité ou de dépendance propriétaire.

Critère : Paresia (AGPL-3.0-or-later) doit pouvoir utiliser chaque dépendance, c'est-à-dire que la licence de la dépendance doit être compatible avec la redistribution de l'ensemble sous AGPL-3.0-or-later. Une licence permissive (MIT, BSD, Apache-2.0, PSF…) est admise si elle est compatible ; ce n'est pas un critère en soi. Seule une dépendance propriétaire ou incompatible est écartée.

Principe (`docs/conventions.md`) : aucune dépendance propriétaire ; une exception n'est possible qu'en cas d'impasse, par décision du mainteneur, inscrite au registre. Les outils de développement ne sont pas des dépendances de Paresia : ni distribués, ni requis pour l'installer ou l'exécuter ; leur licence n'appelle ni exception ni alternative.

## Méthode et sources

Les imports du code (`server/`, `admin/`, `tests/`, `tools/`) ont été relevés. En dehors de la bibliothèque standard de Python, le code importe seulement `cryptography` (serveur), `PyQt6` (client), `qrcode` (facultatif, page web de bunkerd) et, pour les tests, `pytest`. Les programmes appelés (SSH, nftables, sudo, etc.) sont lancés comme processus séparés et ne sont pas liés au code de Paresia.

La licence d'un paquet Debian est celle que déclare le fichier `/usr/share/doc/<paquet>/copyright` de Debian 13 ; la version est celle du paquet Debian 13 où ce fichier a été lu. Un élément dont ce fichier n'a pas pu être lu est marqué **non vérifié** : aucune licence n'est alors affirmée. La colonne « Compatible » applique le critère ci-dessus : « oui » pour les licences que la FSF classe compatibles avec la GPL version 3 (https://www.gnu.org/licenses/license-list.html), dont l'AGPL-3.0 hérite par son § 13.

## Dépendances importées par le code

| Élément | Version (Debian 13) | Où il apparaît | Licence déclarée | Compatible AGPL-3.0-or-later |
| --- | --- | --- | --- | --- |
| Bibliothèque standard de Python (`python3`) | 3.13 (Debian 13) | tout le code | licence de Python (PSF, historique dans `/usr/share/doc/python3/copyright`) | oui (licence de Python classée compatible GPL par la FSF) |
| `python3-cryptography` | 43.0.0-3+deb13u1 | `server/bunkerd/signature.py`, `server/commun/sshsig.py` | Apache-2.0 (paquetage Debian : Expat) | oui (Apache-2.0 est compatible avec la GPL version 3) |
| `libssl3t64` (OpenSSL, utilisé par `cryptography`) | 3.5.7-1~deb13u3 | indirect | Apache-2.0 pour l'essentiel ; autres fichiers sous Artistic ou GPL-1+, BSD-3-clause, Zlib, LGPL-2.1+ (d'après `/usr/share/doc/libssl3t64/copyright`, lu en partie) | oui (processus de l'interpréteur, bibliothèque chargée dynamiquement) |
| `python3-pyqt6` | 6.9.0-2 | `admin/app/` (client) | GPL-3 (Riverbank Computing) ; l'auteur propose aussi une licence commerciale, non utilisée | oui : GPL-3.0 et AGPL-3.0 se combinent (§ 13) ; l'ensemble du client reste sous AGPL-3.0-or-later |
| `python3-pyqt6.qtwebengine` | 6.9.0-1 | `admin/app/fenetre.py` | GPL-3 | oui, même raison |
| Qt 6 et Qt WebEngine (bibliothèques chargées par PyQt6) | 6.8.2 (paquets Debian 13) | indirect | non vérifié (copyright de Qt non lu) | non vérifié |
| `python3-qrcode` | paquet Debian (version non relevée) | `server/bunkerd/web.py` (import facultatif) | BSD-3-clause (fichier copyright du paquet Debian, lu) | oui (BSD-3-clause est compatible avec la GPL version 3) ; dépendance facultative importée |
| `pytest` | non vérifié | tests, `.github/workflows/ci.yml` | non vérifié (outil de test, non distribué) | sans objet : outil de développement |

## Programmes appelés (processus séparés, non liés au code de Paresia)

| Programme (paquet Debian 13) | Version | Licence déclarée | Compatible |
| --- | --- | --- | --- |
| OpenSSH (`openssh-client`, `openssh-server`) | 1:10.0p1-7+deb13u4 | licence OpenSSH, plusieurs licences de type BSD, ISC, domaine public, et une licence « Expat avec clause de publicité » (d'après le fichier copyright) | oui comme programme appelé en processus séparé ; compatibilité de la clause de publicité non analysée |
| `nftables` | 1.1.3-1 | GPL-2 | oui (processus séparé) |
| `sudo` | 1.9.16p2-3+deb13u2 | ISC et BSD (d'après le fichier copyright) | oui |
| `acl` (`setfacl`, `getfacl`) | 2.3.2-2+b1 | GPL-2+ (LGPL-2+ pour les bibliothèques) | oui (processus séparé) |
| `rsync` | 3.5.0+ds1-0+deb13u1 | GPL-3+ | oui |
| `curl` | 8.14.1-2+deb13u7 | licence curl (type MIT) | oui |
| `git` | 1:2.47.3-0+deb13u1 | GPL-2 | sans objet : outil de développement |
| `nak` (signataire NIP-46, non fourni par Debian ; amont https://github.com/fiatjaf/nak) | v0.22.3 ; binaire `nak-v0.22.3-linux-amd64` téléchargé par l'administrateur, SHA-256 `2eb9a16f86c865275983459b2c705d22d5dfbcf527026a279449cbf204d164fe` | The Unlicense (identifiant SPDX `Unlicense`, lu par l'API GitHub `repos/fiatjaf/nak/license` le 2026-11-08) | oui comme programme appelé en processus séparé (signataires NIP-46 de bunkerd) ; non distribué par Paresia |
| `rbw` (client de coffre, non fourni par Debian) | non vérifié | non vérifié | non vérifié |
| lighttpd, HAProxy, Docker | non vérifié | non vérifié | non vérifié |

Les prérequis par machine (paquets, versions, images) sont dans `docs/prerequis.md`.

**Aucune dépendance propriétaire ni incompatible n'est constatée.** Les cas non vérifiés ci-dessus (Qt, `rbw`, lighttpd, HAProxy, Docker, `pytest`) doivent l'être avant la publication.

## strfry (relais Nostr)

| Élément | Licence | Source | Compatible AGPL-3.0-or-later |
| --- | --- | --- | --- |
| strfry (`hoytech/strfry`, commit `4cd3cf6`) | GPL-3.0 | fichier `LICENSE` du dépôt amont au commit `4cd3cf6` (https://github.com/hoytech/strfry), relevé le 2026-11-06 | oui : GPL-3.0 § 13 et AGPL-3.0 § 13 (« Use with the GNU General Public License ») permettent de combiner une œuvre sous GPL-3.0 avec une œuvre sous AGPL-3.0 ; les conditions de l'AGPL s'appliquent à la partie AGPL, celles de la GPL à la partie GPL |

- Paresia n'incorpore pas le code de strfry : le relais tourne dans son propre conteneur et Paresia le pilote par commandes et par fichier de configuration (cahier des charges, § Remus et Castor). La question de la combinaison de code ne se pose donc pas pour le code de Paresia ; elle est notée ici par prudence. Texte des deux licences : `LICENSE` (AGPL-3.0) et `/usr/share/common-licenses/GPL-3` (GPL-3.0, Debian).
- **Image diffusée (D175).** L'image `z0brak/paresia-yin-strfry:4cd3cf6` est diffusée publiquement : sa licence reste à vérifier à la source, et le `Dockerfile` et les sources correspondantes sont à publier si elle l'exige (suivi dans `TODO.md`).
- **Obligation en cas de distribution.** L'image Docker de strfry requise par Paresia n'est pas l'image d'origine. Si Paresia distribue une image de strfry (mode Docker tout-en-un, après la 1.0, D151), il distribue un exécutable sous GPL-3.0 : il DOIT fournir les sources correspondantes de cette image (GPL-3.0 § 6), c'est-à-dire strfry au commit fixé et les modifications de la recette de construction, et conserver la licence et les mentions de droits d'auteur. Une archive des sources de strfry est à prévoir : la reconstruction à l'identique dépend d'un dépôt amont qui peut disparaître.
- Les licences des composants embarqués dans l'image (LMDB, uWebSockets, Alpine, etc.) restent à vérifier : non établies ici.

## Outils de développement

| Outil | Rôle | Licence | Statut |
| --- | --- | --- | --- |
| git | gestion des branches | GPL-2 (Debian 13, 1:2.47.3-0+deb13u1) | sans objet : outil de développement, ni distribué ni requis à l'installation ou à l'exécution |
| Node.js | tests JavaScript de l'interface web | Expat, Apache-2.0, CC0, BSD-3-clause et autres selon les composants (Debian 13, 20.19.2+dfsg-1+deb13u3) | sans objet : outil de développement |
| ShellCheck | contrôle des scripts shell (CI) | GPL-3+ (Debian 13, 0.10.0-1) | sans objet : outil de développement |

## Autres outils cités par la spécification

Un agent SSH, indépendant du client, est requis sur le poste de l'administrateur (`docs/prerequis.md`) ; sa licence dépend du produit choisi et n'est pas inventoriée ici.

## Code issu d'une version antérieure

Le code repris d'une version antérieure de Paresia (bunkerd, scripts du journal légal) a une licence à établir avant tout nouvel import.

## Crédits

- `nak` : outil en ligne de commande pour Nostr, par fiatjaf (https://github.com/fiatjaf/nak), licence The Unlicense. Paresia l'appelle en processus séparé pour les signataires NIP-46 de bunkerd et ne le distribue pas.
- strfry : amont `hoytech/strfry` (https://github.com/hoytech/strfry), GPL-3.0 (voir plus haut).
