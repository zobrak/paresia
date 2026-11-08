#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# installer-backend-admin.sh : installation complète de Pollux, de pollux-session, de Romulus et
# de la partie « tunnel » de backend-admin (D42, D44, D82, D83, D103, D114, D138).
#
# Suivi des versions
#   0.1.19  2026-11-08  Prérequis OpenSSL : une version mal formée est refusée avant la comparaison (dpkg ne l'écarte qu'avec un avertissement).
#   0.1.19  2026-11-08  Prérequis OpenSSL, journal d’essai remis à l’appelant et tunnel lié aux services.
#   0.2.0  2026-11-08  Option --mise-a-jour (versions, arrêt et reprise des seules unités de Paresia, empreintes de configuration, retour arrière automatique) ; prérequis signalés en une fois (ss compris) ; copie périmée sous /run/paresia-installation déplacée.
#   0.1.9  2026-11-08  Étape web : pages de l'interface et des greffons yang dans le dossier de Paresia, index des pages (aucun serveur web touché).
#   0.1.8  2026-11-07  Étape configuration : pose des déclarations de services de Romulus (dossier, quatre fichiers, retour arrière).
#   0.1.1  2026-11-07  Dossiers d'état de Pollux et Romulus : contrôle des directives et des droits.
#   0.1.0  2026-11-07  Création : script complet et commenté qui remplace la procédure pas à pas ; étapes
#                      rejouables, sauvegarde avant toute modification, retour arrière, option temporaire --alpha-test.
#
# Rôle. Le script s'exécute depuis un clone du dépôt, fait au préalable par l'administrateur ; il ne
# clone, ne télécharge et ne met à jour rien. Il ne pose aucune question : option de ligne de commande,
# sinon variable d'environnement, sinon valeur par défaut. Une valeur absente ou invalide arrête le
# script avant toute modification. Toute sortie est un message du catalogue i18n/<langue>.json du clone.
#
# Paramètres (option > variable d'environnement > défaut)
#   NOM                         OPTION                     DÉFAUT et rôle
#   DEPOT                       --depot                    racine du clone qui contient ce script ; copie propre du dépôt
#   LANGUE                      --langue                   dérivée de LC_ALL ou LANG (fr-FR, en-US), repli fr-FR
#   DOSSIER_JOURNAL             --dossier-journal          dossier courant au lancement ; journal de --alpha-test (créé par root en 0600 puis remis à l’appelant sous `sudo`)
#   REPERTOIRE_APP              --repertoire-app           /var/lib/paresia-app ; toute autre valeur est refusée
#   CODE_REMPLACEMENT_CONFIRME  --code-remplacement-confirme  non ; oui autorise le remplacement de fichiers installés différents
#   MISE_A_JOUR                 --mise-a-jour             non ; oui : met à jour une installation existante (voir « Mise à jour »)
#   SESSION_SECOURS             --session-secours          non ; oui : deuxième session ouverte et testée (obligatoire pour sshd)
#   PARESIA_SAUVEGARDE_STOCKAGE_ACTIF  --stockage-actif    oui ; non désactive les sauvegardes (le retour arrière échoue alors)
#   ADRESSE_RELAIS              --adresse-relais           aucun ; adresse IP de backend-relais (avec EMPREINTE_HOTE_RELAIS)
#   EMPREINTE_HOTE_RELAIS       --empreinte-hote-relais    aucun ; empreinte SHA256 de la clé d'hôte, lue sur backend-relais
# Autres options : --aide, --version, --verifier (paramètres et prérequis, lecture seule), --alpha-test,
# --retour-arriere, --jeu <nom>, --confirme, --activer, --sauter <étape> (sudoers, nftables, isolation_remus,
# www-data ; liste fermée).
#
# Exécution. Le script s'exécute en root, sans sudo : il refuse tout autre compte (code 77). Aucun shell
# root n'est ouvert par un tiers : les commandes privilégiées restent écrites « sudo /usr/bin/… » (une
# commande par ligne, chemin absolu) ; la fonction sudo() les exécute directement seulement si l'exécutable
# sudo est absent et que l'UID vaut 0. Les commandes ci-dessous sont lancées par sudo ; si sudo n'est pas
# installé (cas d'un backend-admin sans ce paquet) elles le sont directement, sans `sudo`.
#
# Commandes lancées par `sudo` : liste descriptive, pas un sudoers à recopier. Plusieurs entrées valent root si
# on les autorise sans arguments figés (env, python3, tee, install, sed -i, chown, runuser, find -exec, tar,
# systemctl sans unité) ; `env … python3 -P -m server.sauvegarde` et `runuser … python3 -I -c`
# ne peuvent pas être restreintes et sont propres à cette installation. Pour un sudoers, figez un par un l'exécutable, le
# compte cible et les arguments exacts.
#
# - outil de sauvegarde : /usr/bin/env PYTHONPATH=/run/paresia-installation PARESIA_SAUVEGARDE_CONFIG=… /usr/bin/python3 -P -m server.sauvegarde (jeu, copier, releve, retrouver, restaurer) ;
# - comptes : /usr/sbin/groupadd, /usr/sbin/useradd, /usr/sbin/usermod, /usr/bin/gpasswd, /usr/sbin/userdel, /usr/sbin/groupdel ;
# - fichiers : /usr/bin/install, /usr/bin/tar, /usr/bin/chown, /usr/bin/find … -exec /usr/bin/chmod, /usr/bin/chmod, /usr/bin/tee, /usr/bin/rm, /usr/bin/rmdir, /usr/bin/sed, /usr/bin/diff, /usr/bin/cat, /usr/bin/grep, /usr/bin/stat, /usr/bin/ls, /usr/bin/test, /usr/bin/namei -l, /usr/bin/getent group, /usr/bin/systemd-tmpfiles --create, /usr/bin/mv -T (copie périmée de l'outil), /usr/bin/sha256sum (empreintes de configuration) ;
# - sshd et clés : /usr/sbin/sshd (-t, -T -C user=…), /usr/bin/ssh-keygen (génération de la clé du tunnel, -lf), /usr/bin/ssh-keyscan, /usr/bin/ssh (-G) ;
# - services : /usr/bin/systemctl (reload ssh, daemon-reload, start, stop, status, enable, disable, is-active, is-enabled pour pollux, romulus et paresia-tunnel), /usr/bin/systemd-analyze verify, /usr/bin/journalctl -u <unité> -n 30 --no-pager ;
# - prérequis : /usr/bin/dpkg-query, /usr/bin/dpkg ;
# - lecture et essais : /usr/bin/nsenter -t <pid de pollux> -m -- /usr/bin/ls -l …, /usr/sbin/runuser -u nobody|www-data|paresia-romulus|paresia-pollux -- /usr/bin/python3 -I -c … ou /usr/bin/curl ….
#
# Étapes (une fonction etape_<nom>, précédée de deja_conforme_<nom> et suivie de verifier_<nom>) :
# prerequis, [mise_a_jour_etat sous --mise-a-jour,] sauvegarde, identifiants_comptes, appartenances, dossier_app, code, configuration, web, sshd_app,
# unites, demarrage, refus, tunnel_releves, tunnel_cle, [tunnel_client, tunnel_known_hosts, tunnel_unite,
# tunnel_sockets avec ADRESSE_RELAIS et EMPREINTE_HOTE_RELAIS], activation (sous --activer).
# L'essai de bout en bout de la présence reste la procédure deploy/essai-presence.md.
# Ordre entre machines : backend-admin (1re passe, clé du tunnel) > backend-relais (clé publique et
# empreintes) > backend-admin (2e passe, avec les deux paramètres du tunnel).
#
# Rejouable. Chaque étape lit d'abord l'état : identique à l'attendu, elle est « déjà en place » (aucune
# commande modifiante, aucune sauvegarde) ; différent, elle est refusée avant toute modification (code 78).
# Sauf sous --mise-a-jour, le script n'arrête ni ne redémarre aucune unité : un démon actif dont le code ou la
# configuration changerait doit d'abord être arrêté par l'administrateur. Seul `reload ssh` est lancé, après `sshd -t` et
# avec SESSION_SECOURS=oui. strfry, Docker, lighttpd, bunkerd et les unités de la version précédente
# ne sont jamais touchés, avec ou sans --mise-a-jour.
#
# Mise à jour (--mise-a-jour). Sur une installation existante, le script lit la version installée
# (/usr/local/lib/paresia/VERSION, forme X.Y.Z) et la version livrée (VERSION du clone), affiche « installée X, livrée Y »
# et ne remplace que ce qui diffère. Une version livrée plus ancienne, un VERSION installé illisible ou absent, ou un format
# de manifeste de sauvegarde différent entre l'outil installé et l'outil livré sont refusés (78) avant toute modification ;
# un état identique est « déjà en place ». Demander la mise à jour vaut acceptation de l'interruption des unités de Paresia :
# avant toute modification, le script annonce sur l'erreur standard les unités qui seront arrêtées (pollux puis romulus, et paresia-tunnel seulement si son unité ou la configuration du tunnel change), l'effet
# (fermeture des sessions de présence) et le nom du jeu de sauvegarde. Ordre : sauvegarde complète du jeu, arrêt
# (systemctl stop, jamais restart, kill, enable ni disable), remplacement, daemon-reload, démarrage dans l'ordre inverse des
# seules unités qui étaient actives, attente de l'état actif, vérifications, contrôle de la version. Aucun service tiers n'est
# arrêté ni redémarré. Configuration : les empreintes SHA-256 des fichiers livrés sont enregistrées dans
# /usr/local/lib/paresia/empreintes-conf (comme les conffiles de dpkg). Un fichier de /etc/paresia inchangé depuis la pose est
# remplacé ; un fichier modifié par l'administrateur, ou sans empreinte enregistrée, est conservé octet pour octet et la
# version livrée est déposée à côté, en <fichier>.paresia-nouveau ; les options nouvelles et supprimées sont affichées par
# nom, jamais par valeur. Échec d'une vérification après l'arrêt des unités : retour arrière automatique du code et de la
# configuration (aucun compte ni groupe supprimé), sortie 78 avec le nom du jeu. Exception : si le journal d'une unité
# redémarrée montre une migration de données du démon (state_migrated), rien n'est restauré, les unités redémarrées sont
# arrêtées et la marche à suivre est affichée (retour arrière manuel, sauvegarde propre du démon à restaurer par
# l'administrateur). En fin de mise à jour, la commande de lecture du journal de chaque unité redémarrée est affichée.
# Incompatible avec --retour-arriere et --verifier (64) ; l'étape activation n'est jamais lancée (l'état d'activation est
# conservé). Les scripts ne migrent aucune donnée : chaque démon migre les siennes au démarrage.
#
# Sauvegarde. Avant toute modification, le jeu daté /var/backups/paresia/admin/AAAAMMJJ-HHMMSS est créé
# (son nom est affiché sur la sortie standard) et l'outil du dépôt copie chaque fichier concerné.
# Retour arrière. --retour-arriere --jeu <nom> --confirme : arrêt des unités posées, restauration dans l'ordre
# inverse de la pose, sshd -t puis reload ssh, suppression des seuls comptes et groupes créés par cette
# installation. Sur un jeu de mise à jour (relevé mise-a-jour) : arrêt des seules unités de la liste, restauration (code,
# VERSION, unités, configuration, empreintes, fichiers .paresia-nouveau), daemon-reload, reprise des unités actives avant,
# contrôle de la version ; aucun compte ni groupe n'est supprimé et l'état d'activation est conservé.
#
# Prérequis, tous signalés en une fois (un seul message, sortie 69) : Debian 13, systemd, Python 3.11 ou plus, bash,
# libssl3t64 >= 3.5.7-1~deb13u3,
# python3 (bibliothèque standard) pour lire les catalogues, python3-cryptography (module « cryptography », requis par
# Pollux), ss (iproute2) et les exécutables de la liste ci-dessus (curl, ssh, ssh-keygen, ssh-keyscan, sshd, systemctl,
# journalctl, systemd-analyze, systemd-tmpfiles, nsenter, namei, runuser, groupadd, useradd, usermod, userdel, groupdel,
# gpasswd, install, tar, mv, chown, chmod, find, tee, rm, rmdir, sed, diff, cat, grep, stat, ls, test, getent, sha256sum),
# dont la présence est testée sans sudo.
# Codes de sortie (sysexits.h) : 0 succès ; 64 usage (paramètre absent, option inconnue, combinaison refusée) ; 65 valeur invalide ;
# 66 catalogue illisible ; 69 prérequis manquant (tous listés en un seul message) ; 73 journal déjà existant ; 74 sauvegarde en échec ; 77 compte
# d'exécution refusé ; 78 état différent de l'attendu (refus ou écart) ; autres : code de la commande en échec.
#
# Option --alpha-test (temporaire, retirable : bloc « alpha-test » ci-dessous) : points de contrôle après chaque
# étape, arrêt au premier écart, journal horodaté sans secret dans DOSSIER_JOURNAL.
# Aucune clé privée n'est lue, copiée, affichée ni journalisée ; seules la clé publique et les empreintes sortent.
set -euo pipefail
umask 0022
# DEBUT commun
# ---------------------------------------------------------------------------
# Partie commune aux deux scripts d'installation (même texte dans les deux).
# Messages : aucun texte n'est écrit en dur ; chaque message est une clé
# « install_* » lue dans i18n/<langue>.json du clone par python3 -I -P.
# ---------------------------------------------------------------------------
EX_USAGE=64        # sysexits.h : paramètre absent, option inconnue
EX_DATAERR=65      # valeur invalide
EX_NOINPUT=66      # catalogue illisible
EX_UNAVAILABLE=69  # prérequis manquant
EX_CANTCREAT=73    # journal déjà existant
EX_NOPERM=77       # mauvais compte d'exécution
EX_CONFIG=78       # état différent de l'attendu (refus ou écart)
EX_IOERR=74        # sauvegarde en échec
export TZ=UTC

AIDE=non
VERSION_DEMANDEE=non
VERIFIER=non
ALPHA=non
RETOUR=non
ACTIVER=non
CONFIRME=non
JEU=''
JEU_OPTION=''
SAUTER_BRUT=''
SAUTER=' '
CATALOGUE_PRET=non
RACINE_CLONE=''
CATALOGUE=''
ETAPE_COURANTE='-'
ARRET_MESSAGE=non
PAS=2
SYSTEMD_VERSION=0
NORMALISER_UNITE=non
TRAVAIL=/run/paresia-installation
INSTALLE_CODE=/usr/local/lib/paresia/server
INSTALLE_VERSION=/usr/local/lib/paresia/VERSION
INSTALLE_EMPREINTES=/usr/local/lib/paresia/empreintes-conf
MANQUES=()
MAJ_PHASE=''
MAJ_ARRETE=non
MAJ_HEURE=''
MAJ_CODE_ECHEC=0
MAJ_VERSION_INSTALLEE=''
MAJ_VERSION_LIVREE=''
MAJ_MOTIF_MIGRATION='state_migrated'
MAJ_ACTIVES=()
MAJ_REDEMARREES=()
MAJ_DIFFERENCES=()
MAJ_SAUVEGARDE=()
POSE=()
declare -A EMPREINTES=()

# Programme python de lecture du catalogue (bibliothèque standard seule, un seul appel par exécution) :
# il écrit les clés install_* et leurs textes, séparés par des octets nuls, sans caractère de contrôle
# (hors fin de ligne). Les emplacements {nom} sont remplis dans le shell par formater().
PYCAT='import json, re, sys
try:
    with open(sys.argv[1], encoding="utf-8") as f:
        brut = json.load(f)
except (OSError, ValueError):
    sys.exit(3)
if not isinstance(brut, dict):
    sys.exit(3)
for cle, texte in brut.items():
    if cle.startswith("install_") and isinstance(texte, str):
        sys.stdout.write(cle + "\0" + re.sub(r"[\x00-\x09\x0b-\x1f\x7f-\x9f]", "", texte) + "\0")'

declare -A CAT=()
shopt -u patsub_replacement 2> /dev/null || true    # « & » n'a aucun sens spécial dans les valeurs insérées

# formater CLE [nom=valeur ...] : texte du catalogue (la clé elle-même si elle manque), emplacements remplis,
# caractères de contrôle des valeurs retirés.
formater() {
    local LC_ALL=C.UTF-8
    local cle=$1 texte argument nom valeur
    shift
    if [[ ! -v CAT[$cle] ]]; then
        printf '%s\n' "$cle"
        return 0
    fi
    texte=${CAT[$cle]}
    for argument in "$@"; do
        nom=${argument%%=*}
        valeur=${argument#*=}
        if [ "$nom" != "$argument" ]; then
            valeur=${valeur//[[:cntrl:]]/}
            texte=${texte//"{$nom}"/$valeur}
        fi
    done
    printf '%s\n' "$texte"
}

# msg CLE [nom=valeur ...] : message du catalogue sur l'erreur standard.
msg() {
    if [ "$CATALOGUE_PRET" = oui ]; then
        formater "$@" >&2
    else
        printf '%s\n' "$1" >&2
    fi
}

# msg_out CLE [nom=valeur ...] : même message, sur la sortie standard (données).
msg_out() {
    if [ "$CATALOGUE_PRET" = oui ]; then
        formater "$@"
    else
        printf '%s\n' "$1"
    fi
}

# filtre_sortie : retire les caractères de contrôle (sauf la fin de ligne) d'une sortie de commande.
filtre_sortie() {
    tr -d '\000-\010\013-\037\177'
}

# arreter CODE CLE [nom=valeur ...] : message puis sortie.
arreter() {
    local code=$1
    shift
    msg "$@"
    ARRET_MESSAGE=oui
    exit "$code"
}

# hook FONCTION [arguments] : appelle la fonction du bloc alpha-test si l'option est active et si le
# bloc est présent (le bloc est retirable sans toucher aux étapes).
hook() {
    if [ "$ALPHA" = oui ] && declare -F "$1" > /dev/null; then
        "$@"
    fi
}

ecart() {            # ELEMENT ATTENDU RELEVE
    arreter "$EX_CONFIG" install_ecart "element=$1" "attendu=$2" "releve=$3"
}

manque() {           # ELEMENT : prérequis absent, arrêt immédiat (hors du contrôle de l'étape prerequis)
    arreter "$EX_UNAVAILABLE" install_err_prerequis "element=$1"
}

# accumuler ELEMENT : prérequis absent ou version insuffisante, consigné pour un message unique (controle_manques).
accumuler() {
    MANQUES+=("$1")
}

# controle_manques : un seul message avec tous les éléments consignés (liste séparée par des virgules, caractères de
# contrôle retirés par le formatage), sortie 69 ; aucun autre effet.
controle_manques() {
    local liste='' element
    if [ "${#MANQUES[@]}" -eq 0 ]; then
        return 0
    fi
    for element in "${MANQUES[@]}"; do
        liste="$liste$element, "
    done
    arreter "$EX_UNAVAILABLE" install_err_prerequis_liste "elements=${liste%, }"
}

# executables_requis CHEMIN... : présence testée sans sudo ([ -x ]) : les exécutables de /usr/bin et /usr/sbin sont lisibles
# de tous, et l'absence de sudo lui-même est ainsi signalée avec les autres manques.
executables_requis() {
    local chemin
    for chemin in "$@"; do
        if [ ! -x "$chemin" ]; then
            accumuler "$chemin"
        fi
    done
}

# verifie ELEMENT ATTENDU RELEVE : contrôle bloquant dans les deux modes.
verifie() {
    if [ "$2" = "$3" ]; then
        hook alpha_verifie "$1" "$2"
    else
        ecart "$1" "$2" "$3"
    fi
}

# releve_info ELEMENT VALEUR : valeur relevée, jamais une assertion (affichée en alpha-test).
releve_info() {
    hook alpha_releve "$1" "$2"
}

# attention COMMANDE OBJET : avertissement affiché en alpha-test avant une commande destructive ou risquée.
attention() {
    hook alpha_attention "$1" "$2"
}

# ---------------------------------------------------------------------------
# Paramètres : valeur par défaut, puis option ou variable, puis validation, puis usage.
# ---------------------------------------------------------------------------
# resoudre_racine_clone : racine du clone dont le script fait partie (chemin résolu du script, deux niveaux au-dessus
# de deploy/<machine>/), mémorisée dans RACINE_CLONE avant que le dossier courant ne change (le chemin du script peut
# être relatif).
resoudre_racine_clone() {
    local chemin
    chemin=$(readlink -f -- "${BASH_SOURCE[0]}") || return 0
    chemin=$(dirname -- "$chemin")
    RACINE_CLONE=$(dirname -- "$(dirname -- "$chemin")")
}

racine_clone() {
    printf '%s\n' "$RACINE_CLONE"
}

langue_defaut() {
    local valeur
    for valeur in "${LC_ALL:-}" "${LC_MESSAGES:-}" "${LANG:-}"; do
        if [ -n "$valeur" ]; then
            case $valeur in
                en*) printf 'en-US\n' ;;
                *) printf 'fr-FR\n' ;;
            esac
            return 0
        fi
    done
    printf 'fr-FR\n'
}

valeur_requise() {
    if [ "$#" -lt 2 ] || [ -z "$2" ]; then
        arreter "$EX_USAGE" install_err_param_absent "nom=$1"
    fi
}

analyser() {
    while [ "$#" -gt 0 ]; do
        PAS=2
        case $1 in
            --aide | --help) AIDE=oui; PAS=1 ;;
            --version) VERSION_DEMANDEE=oui; PAS=1 ;;
            --verifier) VERIFIER=oui; PAS=1 ;;
            --alpha-test) ALPHA=oui; PAS=1 ;;
            --retour-arriere) RETOUR=oui; PAS=1 ;;
            --activer) ACTIVER=oui; PAS=1 ;;
            --mise-a-jour) MISE_A_JOUR=oui; PAS=1 ;;
            --confirme) CONFIRME=oui; PAS=1 ;;
            --depot) valeur_requise "$@"; DEPOT=$2 ;;
            --langue) valeur_requise "$@"; LANGUE=$2 ;;
            --dossier-journal) valeur_requise "$@"; DOSSIER_JOURNAL=$2 ;;
            --code-remplacement-confirme) valeur_requise "$@"; CODE_REMPLACEMENT_CONFIRME=$2 ;;
            --session-secours) valeur_requise "$@"; SESSION_SECOURS=$2 ;;
            --stockage-actif) valeur_requise "$@"; PARESIA_SAUVEGARDE_STOCKAGE_ACTIF=$2 ;;
            --jeu) valeur_requise "$@"; JEU_OPTION=$2 ;;
            --sauter) valeur_requise "$@"; SAUTER_BRUT="$SAUTER_BRUT,$2" ;;
            *)
                if ! option_machine "$@"; then
                    arreter "$EX_USAGE" install_err_option_inconnue "option=$1"
                fi
                ;;
        esac
        shift "$PAS"
    done
}

# chemin_normalise NOM VALEUR [depot|journal] : chemin absolu normalisé, sinon code 65. Les chemins sous /home et sous
# /root sont refusés (aucun compte ne doit y avoir son répertoire) sauf pour DEPOT et DOSSIER_JOURNAL (troisième
# argument « depot » ou « journal ») : le clone source et le dossier d'exécution sont souvent sous un dossier personnel.
chemin_normalise() {         # NOM VALEUR [depot]
    local normalise
    # liste blanche de caractères : aucun espace, guillemet, métacaractère ni caractère de contrôle (le chemin est
    # ensuite employé dans des commandes privilégiées et dans le nom du journal)
    if ! [[ $2 =~ ^/[A-Za-z0-9._/-]+$ ]]; then
        arreter "$EX_DATAERR" install_err_param_invalide "nom=$1" "valeur=$2"
    fi
    normalise=$(realpath -m -- "$2") || arreter "$EX_DATAERR" install_err_param_invalide "nom=$1" "valeur=$2"
    if ! [[ $normalise =~ ^/[A-Za-z0-9._/-]+$ ]]; then
        arreter "$EX_DATAERR" install_err_param_invalide "nom=$1" "valeur=$2"
    fi
    if [ "${3:-}" != depot ] && [ "${3:-}" != journal ]; then
        case $normalise in
            /home | /home/*) arreter "$EX_DATAERR" install_err_home "nom=$1" "valeur=$2" ;;
            /root | /root/*) arreter "$EX_DATAERR" install_err_param_invalide "nom=$1" "valeur=$2" ;;
        esac
    fi
    printf '%s\n' "$normalise"
}

valeur_oui_non() {           # NOM VALEUR
    case $2 in
        oui | non) ;;
        *) arreter "$EX_DATAERR" install_err_param_invalide "nom=$1" "valeur=$2" ;;
    esac
}

valider_adresse() {          # NOM VALEUR : adresse IP valide (module ipaddress), caractères 0-9A-Fa-f.: seulement
    case $2 in
        '' | *[!0-9A-Fa-f.:]*) arreter "$EX_DATAERR" install_err_param_invalide "nom=$1" "valeur=$2" ;;
    esac
    if ! /usr/bin/python3 -I -P -c 'import ipaddress, sys; ipaddress.ip_address(sys.argv[1])' "$2" 2> /dev/null; then
        arreter "$EX_DATAERR" install_err_param_invalide "nom=$1" "valeur=$2"
    fi
}

valider_empreinte() {        # NOM VALEUR : empreinte SHA256 de ssh-keygen
    if ! [[ $2 =~ ^SHA256:[A-Za-z0-9+/]{43}$ ]]; then
        arreter "$EX_DATAERR" install_err_param_invalide "nom=$1" "valeur=$2"
    fi
}

valider_cle_publique() {     # NOM VALEUR : clé publique ssh-ed25519 de forme stricte, une seule ligne
    # forme : « ssh-ed25519 », corps base64 de 64 à 128 caractères commençant par AAAA, commentaire facultatif de
    # 64 caractères imprimables au plus ; sous LC_ALL=C, [:print:] exclut retour chariot, tabulation, tout caractère
    # de contrôle et saut de ligne ; l'empreinte reste calculée par ssh-keygen -lf et comparée à l'empreinte lue sur
    # l'autre machine
    local LC_ALL=C
    local motif='^ssh-ed25519 AAAA[A-Za-z0-9+/]{64,128}={0,2}( [[:print:]]{0,64})?$'
    if ! [[ $2 =~ $motif ]]; then
        arreter "$EX_DATAERR" install_err_param_invalide "nom=$1" "valeur=${2:0:12}"
    fi
}

valider_port() {             # NOM VALEUR : entier de 1024 à 65535
    if ! [[ $2 =~ ^[0-9]{1,5}$ ]] || [ "$2" -lt 1024 ] || [ "$2" -gt 65535 ]; then
        arreter "$EX_DATAERR" install_err_param_invalide "nom=$1" "valeur=$2"
    fi
}

normaliser_sauter() {
    local mot
    SAUTER_BRUT=${SAUTER_BRUT//,/ }
    for mot in $SAUTER_BRUT; do
        case $mot in
            produit | fonctions | sudoers | nftables | isolation_remus | www-data) SAUTER="$SAUTER$mot " ;;
            *) arreter "$EX_DATAERR" install_err_param_invalide "nom=--sauter" "valeur=$mot" ;;
        esac
    done
}

etape_sautee() {
    case $1 in
        produit | fonctions | sudoers | nftables | isolation_remus) [[ $SAUTER == *" $1 "* ]] ;;
        activation) [ "$ACTIVER" != oui ] || [ "$MISE_A_JOUR" = oui ] ;;
        *) return 1 ;;
    esac
}

# Contrôle de DEPOT : chemin absolu physique (aucun lien symbolique), dossiers server/ et i18n/ présents.
valider_depot() {
    local physique
    # forme (absolu, liste blanche de caractères) avant tout usage ; /home n'est pas refusé pour DEPOT
    chemin_normalise DEPOT "$DEPOT" depot > /dev/null
    physique=$(cd -- "$DEPOT" 2> /dev/null && pwd -P) || arreter "$EX_DATAERR" install_err_depot
    # le code copié en root vient de ce dossier : ni modifiable par le groupe ou les autres, ni à un autre compte
    local proprietaire mode
    read -r proprietaire mode < <(stat -c '%u %a' -- "$DEPOT")
    if { [ "$proprietaire" != 0 ] && [ "$proprietaire" != "$EUID" ]; } || (( 8#$mode & 8#022 )); then
        arreter "$EX_DATAERR" install_err_depot
    fi
    if [ "$physique" != "$DEPOT" ] || [ -L "$DEPOT/server" ] || [ -L "$DEPOT/i18n" ] \
        || [ ! -d "$DEPOT/server" ] || [ ! -d "$DEPOT/i18n" ] || [ ! -f "$DEPOT/VERSION" ] || [ -L "$DEPOT/VERSION" ]; then
        arreter "$EX_DATAERR" install_err_depot
    fi
    if [ ! -x /usr/bin/python3 ]; then
        arreter "$EX_UNAVAILABLE" install_err_prerequis "element=/usr/bin/python3"
    fi
}

charger_catalogue() {
    if ! [[ $LANGUE =~ ^[a-z]{2}-[A-Z]{2}$ ]]; then
        arreter "$EX_DATAERR" install_err_param_invalide "nom=LANGUE" "valeur=$LANGUE"
    fi
    CATALOGUE="$DEPOT/i18n/$LANGUE.json"
    local cle valeur
    while IFS= read -r -d '' cle && IFS= read -r -d '' valeur; do
        CAT[$cle]=$valeur
    done < <(/usr/bin/python3 -I -P -c "$PYCAT" "$CATALOGUE" 2> /dev/null)
    if [ "${#CAT[@]}" -eq 0 ]; then
        arreter "$EX_NOINPUT" install_err_catalogue
    fi
    CATALOGUE_PRET=oui
}

valider_communs() {
    valeur_oui_non CODE_REMPLACEMENT_CONFIRME "$CODE_REMPLACEMENT_CONFIRME"
    valeur_oui_non MISE_A_JOUR "$MISE_A_JOUR"
    valeur_oui_non SESSION_SECOURS "$SESSION_SECOURS"
    valeur_oui_non PARESIA_SAUVEGARDE_STOCKAGE_ACTIF "$PARESIA_SAUVEGARDE_STOCKAGE_ACTIF"
    DOSSIER_JOURNAL=$(chemin_normalise DOSSIER_JOURNAL "$DOSSIER_JOURNAL" journal)
    case $DOSSIER_JOURNAL in
        /var/log/paresia | /var/log/paresia/*) arreter "$EX_DATAERR" install_err_param_invalide "nom=DOSSIER_JOURNAL" "valeur=$DOSSIER_JOURNAL" ;;
    esac
    if [ -n "$JEU_OPTION" ] && ! [[ $JEU_OPTION =~ ^[0-9]{8}-[0-9]{6}$ ]]; then
        arreter "$EX_DATAERR" install_err_param_invalide "nom=--jeu" "valeur=$JEU_OPTION"
    fi
    if [ "$VERIFIER" = oui ] && { [ "$ALPHA" = oui ] || [ "$RETOUR" = oui ]; }; then
        arreter "$EX_USAGE" install_err_combinaison
    fi
    if [ "$MISE_A_JOUR" = oui ] && { [ "$VERIFIER" = oui ] || [ "$RETOUR" = oui ]; }; then
        arreter "$EX_USAGE" install_err_combinaison
    fi
    if [ "$RETOUR" = oui ]; then
        if [ -z "$JEU_OPTION" ]; then
            arreter "$EX_USAGE" install_err_jeu_requis
        fi
        if [ "$CONFIRME" != oui ]; then
            arreter "$EX_USAGE" install_err_confirme_requis
        fi
    elif [ "$CONFIRME" = oui ]; then
        arreter "$EX_USAGE" install_err_combinaison
    fi
    normaliser_sauter
}

# ---------------------------------------------------------------------------
# Lecture du système, attributs et comparaisons (lecture seule).
# ---------------------------------------------------------------------------
lire_systeme() {             # lecture d'un fichier du système
    sudo /usr/bin/cat -- "$1"
}

attributs() {                # CHEMIN -> « proprietaire:groupe mode », vide si absent
    sudo /usr/bin/stat -c '%U:%G %a' -- "$1" 2> /dev/null | filtre_sortie || true
}

existe() {
    sudo /usr/bin/test -e "$1"
}

contenu_identique() {        # SOURCE DESTINATION
    if [ "$NORMALISER_UNITE" = oui ] && [[ $2 == *.service ]]; then
        sed 's/^ConfigurationDirectory=paresia::ro$/ConfigurationDirectory=paresia/' -- "$1" \
            | sudo /usr/bin/diff -q - "$2" > /dev/null 2>&1
    else
        sudo /usr/bin/diff -q -- "$1" "$2" > /dev/null 2>&1
    fi
}

refuser_difference() {       # ELEMENT : état différent, refus avant toute modification
    arreter "$EX_CONFIG" install_err_difference "element=$1"
}

# a_poser SOURCE DESTINATION MODE : 0 = à poser, 1 = déjà conforme ; refus (78) si différent sans autorisation.
a_poser() {
    if ! existe "$2"; then
        return 0
    fi
    if contenu_identique "$1" "$2" && [ "$(attributs "$2")" = "root:root ${3#0}" ]; then
        return 1
    fi
    if [ "$MISE_A_JOUR" = oui ]; then
        return 0
    fi
    if [ "$CODE_REMPLACEMENT_CONFIRME" = oui ]; then
        return 0
    fi
    refuser_difference "$2"
}

# unite_active UNITE : 0 si l'unité est active.
unite_active() {
    sudo /usr/bin/systemctl is-active --quiet "$1" > /dev/null 2>&1
}

# refuser_si_active UNITE... : une unité active n'est jamais redémarrée ; l'arrêt est à faire par l'administrateur. Sous
# --mise-a-jour, les unités de la liste fermée de la machine sont arrêtées par le script lui-même (maj_arreter_unites) ;
# toute autre unité de Paresia active reste un refus.
refuser_si_active() {
    local unite
    for unite in "$@"; do
        if unite_active "$unite" && ! maj_dans_liste "$unite"; then
            arreter "$EX_CONFIG" install_err_unite_active "unite=$unite"
        fi
    done
}

# ---------------------------------------------------------------------------
# Outil de sauvegarde (D83, D103, D114) : copie root du code, jeu, copies, relevés.
# ---------------------------------------------------------------------------
outil() { sudo /usr/bin/env PYTHONPATH=/run/paresia-installation PARESIA_SAUVEGARDE_CONFIG="$CONF_OUTIL" ${PARESIA_SAUVEGARDE_STOCKAGE_ACTIF:+PARESIA_SAUVEGARDE_STOCKAGE_ACTIF="$PARESIA_SAUVEGARDE_STOCKAGE_ACTIF"} /usr/bin/python3 -P -m server.sauvegarde "$@"; }

# outil_q : comme outil, sans bruit si tout va bien ; les messages de l'outil ne sont affichés qu'en cas d'échec.
outil_q() {
    local erreur rc=0
    { erreur=$(outil "$@" 2>&1 >&3 3>&-) || rc=$?; } 3>&1
    if [ "$rc" -ne 0 ]; then
        printf '%s\n' "$erreur" | filtre_sortie >&2
    fi
    return "$rc"
}

# code_outil_en_place : 0 si la copie root du code est présente et identique au dépôt.
code_outil_en_place() {
    existe "$TRAVAIL/server" && sudo /usr/bin/diff -qr --exclude=__pycache__ "$DEPOT/server" "$TRAVAIL/server" > /dev/null 2>&1 \
        && contenu_identique "$DEPOT/VERSION" "$TRAVAIL/VERSION"
}

# copie_perimee_conforme : 0 si tout ce qui se trouve sous /run/paresia-installation appartient à root et ne contient ni
# lien symbolique ni fichier spécial (find ne suit aucun lien : un lien est reconnu comme tel).
copie_perimee_conforme() {
    [ -z "$(sudo /usr/bin/find "$TRAVAIL" \( ! -user root -o \( ! -type d ! -type f \) \) -print -quit)" ]
}

# ATTENTION : crée des dossiers root et copie le code du dépôt sous /run/paresia-installation (D114) ;
# refus de tout lien symbolique ou fichier spécial dans la source. Une copie existante différente est déplacée (jamais
# supprimée) vers $TRAVAIL/code-retire-<horodatage> si elle est entièrement sous /run/paresia-installation, de propriétaire
# root, sans lien symbolique ni fichier spécial ; sinon elle est refusée. Les copies retirées disparaissent au redémarrage
# (/run est un tmpfs) ; le script ne les supprime jamais.
copier_code_outil() {
    local entree retire
    if code_outil_en_place; then
        return 0
    fi
    if [ -L "$DEPOT/server" ] || [ -n "$(find "$DEPOT/server" ! -type d ! -type f -print -quit)" ]; then
        arreter "$EX_CONFIG" install_err_copie_code
    fi
    if existe "$TRAVAIL/server"; then
        if ! copie_perimee_conforme; then
            arreter "$EX_CONFIG" install_err_copie_code
        fi
        printf -v retire '%s/code-retire-%(%Y%m%d-%H%M%S)T' "$TRAVAIL" -1
        attention mv "$TRAVAIL/server"
        sudo /usr/bin/install -d -o root -g root -m 0700 "$retire"
        sudo /usr/bin/mv -T "$TRAVAIL/server" "$retire/server"
        if existe "$TRAVAIL/VERSION"; then
            sudo /usr/bin/mv -T "$TRAVAIL/VERSION" "$retire/VERSION"
        fi
    fi
    attention install "$TRAVAIL"
    sudo /usr/bin/install -d -o root -g root -m 0700 "$TRAVAIL"
    while IFS= read -r -d '' entree; do
        sudo /usr/bin/install -d -o root -g root -m 0755 "$TRAVAIL/server/$entree" < /dev/null
    done < <(find "$DEPOT/server" -name __pycache__ -prune -o -type d -printf '%P\0')
    while IFS= read -r -d '' entree; do
        sudo /usr/bin/install -o root -g root -m 0644 -- "$DEPOT/server/$entree" "$TRAVAIL/server/$entree" < /dev/null
    done < <(find "$DEPOT/server" -name __pycache__ -prune -o -type f -printf '%P\0')
    # VERSION se trouve à côté de server/ (les démons la lisent à la racine du code installé)
    sudo /usr/bin/install -o root -g root -m 0644 -- "$DEPOT/VERSION" "$TRAVAIL/VERSION"
}

# ATTENTION : crée /var/backups/paresia et son dossier de machine (root:root 0700) et un jeu daté ; aucune clé n'y est copiée.
jeu_pret() {
    local dossier
    if [ -n "$JEU" ]; then
        return 0
    fi
    copier_code_outil
    if [ -n "$JEU_OPTION" ]; then
        JEU=$JEU_OPTION
        maj_noter_jeu
        return 0
    fi
    attention jeu "$MACHINE"
    dossier=$(outil_q jeu) || arreter "$EX_IOERR" install_err_sauvegarde
    JEU=${dossier##*/}
    msg_out install_jeu "jeu=$JEU"
    apres_creation_jeu
    maj_noter_jeu
}

# sauvegarder CHEMIN... : copie (ou marque d'absence) avant tout écrasement, création ou suppression.
sauvegarder() {
    jeu_pret
    outil_q copier --si-absent --jeu "$JEU" "$@" > /dev/null
}

sauvegarder_arbre() {
    jeu_pret
    outil_q copier --arbre --si-absent --jeu "$JEU" "$@" > /dev/null
}

# releve NOM : enregistre l'entrée standard comme relevé du jeu.
releve() {
    jeu_pret
    outil_q releve "$1" --jeu "$JEU" > /dev/null
}

noter_creation() {           # TYPE NOM : consigne ce que l'installation a créé
    jeu_pret
    printf '%s\n' "$2" | releve "cree-$1-$2"
}

# ATTENTION : la restauration écrase ou retire un fichier ; elle s'arrête sans rien modifier si la sauvegarde manque (code 5).
restaurer() {
    outil_q restaurer --jeu "$JEU" "$1" > /dev/null
}

# restaurer_si_pose CHEMIN : 0 si restauré, 1 si l'installation n'avait pas touché ce chemin.
restaurer_si_pose() {
    local rc=0
    outil_q retrouver --jeu "$JEU" "$1" > /dev/null 2>&1 || rc=$?
    if [ "$rc" -eq 5 ]; then
        return 1
    elif [ "$rc" -ne 0 ]; then
        arreter "$EX_IOERR" install_err_retour "chemin=$1"
    fi
    restaurer "$1"
}

cree_par_installation() {    # TYPE NOM
    outil_q retrouver --releve "cree-$1-$2" --jeu "$JEU" > /dev/null 2>&1
}

# ATTENTION : poser_fichier remplace un fichier installé (copie préalable par l'outil) ; install écrase la cible.
poser_fichier() {            # SOURCE DESTINATION MODE
    sauvegarder "$2"
    sudo /usr/bin/install -m "$3" -o root -g root "$1" "$2"
    if [ "$NORMALISER_UNITE" = oui ] && [[ $2 == *.service ]]; then
        # ATTENTION : sed -i modifie la copie installée de l'unité (pas celle du dépôt).
        sudo /usr/bin/sed -i 's/^ConfigurationDirectory=paresia::ro$/ConfigurationDirectory=paresia/' "$2"
    fi
}

# controle_attributs CHEMIN ATTENDU : « proprietaire:groupe mode » bloquant.
controle_attributs() {
    verifie "$1" "$2" "$(attributs "$1")"
}

# sshd_t : contrôle de la configuration avant tout rechargement.
sshd_t() {
    sudo /usr/sbin/sshd -t
}

# ATTENTION : systemctl reload ssh recharge sshd ; une configuration invalide ferme l'accès.
# Précédé de sshd -t ; réservé à une session de secours ouverte (SESSION_SECOURS=oui). Jamais de restart.
recharger_ssh() {
    if [ "$SESSION_SECOURS" != oui ]; then
        arreter "$EX_CONFIG" install_err_session_secours
    fi
    sshd_t
    attention "reload ssh" sshd
    sudo /usr/bin/systemctl reload ssh
}

# sshd_t_ou_restaurer FICHIER... : sshd -t ; en échec, les fichiers posés sont restaurés (ordre donné) et le script s'arrête.
sshd_t_ou_restaurer() {
    local fichier
    if ! sshd_t; then
        for fichier in "$@"; do
            restaurer "$fichier"
        done
        arreter "$EX_CONFIG" install_err_sshd_t
    fi
}

# releves_systeme_avant : relevés d'état avant toute modification, consignés dans le jeu à sa création.
releves_systeme_avant() {
    sudo /usr/bin/systemctl list-units --type=service --state=active --no-pager | filtre_sortie | releve unites-actives-avant
    sudo /usr/sbin/sshd -T -C user=app,host=backend-admin.example.org,addr=192.0.2.50 | filtre_sortie | releve sshd-app-avant
    sudo /usr/sbin/sshd -T -C user=tunnel,host=backend-admin.example.org,addr=192.0.2.50 | filtre_sortie | releve sshd-tunnel-avant
}

exiger_session_secours() {
    if [ "$SESSION_SECOURS" != oui ]; then
        arreter "$EX_CONFIG" install_err_session_secours
    fi
}

# version de systemd : nombre ; unités normalisées avant 257 (::ro retiré).
lire_systemd() {
    SYSTEMD_VERSION=0
    if ! command -v systemctl > /dev/null; then
        return 0
    fi
    SYSTEMD_VERSION=$(systemctl --version | awk 'NR==1 {print $2}')
    if ! [[ $SYSTEMD_VERSION =~ ^[0-9]+$ ]]; then
        SYSTEMD_VERSION=0
        accumuler systemd
        return 0
    fi
    if [ "$SYSTEMD_VERSION" -lt 257 ]; then
        NORMALISER_UNITE=oui
    fi
}

# ---------------------------------------------------------------------------
# Groupes et comptes : état relevé en lecture seule, création de ce qui manque.
# Un compte ou un groupe existant sous le bon nom et conforme est accepté (« déjà en place »),
# tout autre état est refusé avant toute création.
# ---------------------------------------------------------------------------
# groupes et comptes sont créés sans numéro imposé (groupadd --system, useradd --system) : le système choisit des
# identifiants libres dans la plage système de login.defs(5) ; ils sont relevés puis inscrits dans la configuration installée.
# Un groupe ou un compte déjà présent sous le bon nom est repris tel quel, s'il est dans la plage système, si le groupe
# primaire du compte est le groupe du même nom et si répertoire et interpréteur sont ceux de la table ; sinon refus (78).
# Sources, pages installées (man -L en) : useradd(8), « -r, --system : Create a system account. [...] their numeric
# identifiers are chosen in the SYS_UID_MIN-SYS_UID_MAX range, defined in /etc/login.defs » ; groupadd(8), « -r, --system :
# Create a system group. » ; login.defs(5), « SYS_UID_MAX (number), SYS_UID_MIN (number) : Range of user IDs used for the
# creation of system users by useradd or newusers » (de même SYS_GID_MIN et SYS_GID_MAX pour les groupes).
declare -A IDENT=()          # « compte:NOM » et « groupe:NOM » -> identifiant relevé

borne() {                    # FICHIER NOM -> valeur numérique ou vide
    { lire_systeme "$1" 2> /dev/null | sed -n -E "s/^[[:space:]]*$2[[:space:]]*=?[[:space:]]*([0-9]+).*/\1/p" | awk 'NR==1' | filtre_sortie; } || true
}

# plage_systeme UID|GID -> « bas haut » : bornes de login.defs(5), repli 100 et 999 (Debian) si une clé manque.
plage_systeme() {
    local bas haut
    bas=$(borne /etc/login.defs "SYS_$1_MIN")
    haut=$(borne /etc/login.defs "SYS_$1_MAX")
    printf '%s %s\n' "${bas:-100}" "${haut:-999}"
}

plage_texte() {              # UID|GID -> « bas-haut »
    local bas haut
    read -r bas haut <<< "$(plage_systeme "$1")"
    printf '%s-%s\n' "$bas" "$haut"
}

# dans_plage UID|GID VALEUR : 0 si VALEUR est un entier décimal dans la plage système.
dans_plage() {
    local bas haut
    [[ $2 =~ ^[0-9]{1,10}$ ]] || return 1
    read -r bas haut <<< "$(plage_systeme "$1")"
    [[ $bas =~ ^[0-9]{1,10}$ && $haut =~ ^[0-9]{1,10}$ ]] || return 1
    [ $((10#$2)) -ge $((10#$bas)) ] && [ $((10#$2)) -le $((10#$haut)) ]
}

# groupe_etat NOM : 0 = présent et conforme, 1 = absent ; arrêt 78 si le numéro est hors de la plage système.
groupe_etat() {
    local ligne gid
    if ! ligne=$(getent group "$1"); then
        return 1
    fi
    gid=$(cut -d: -f3 <<< "$ligne")
    if ! dans_plage GID "$gid"; then
        ecart "gid $1" "$(plage_texte GID)" "$gid"
    fi
    return 0
}

# compte_etat NOM HOME SHELL : même convention ; le groupe primaire est le groupe du même nom.
compte_etat() {
    local ligne uid attendu
    if ! ligne=$(getent passwd "$1"); then
        return 1
    fi
    uid=$(cut -d: -f3 <<< "$ligne")
    if ! dans_plage UID "$uid"; then
        ecart "uid $1" "$(plage_texte UID)" "$uid"
    fi
    attendu=$({ getent group "$1" || true; } | cut -d: -f3)
    verifie "gid primaire $1" "$attendu" "$(cut -d: -f4 <<< "$ligne")"
    verifie "home $1" "$2" "$(cut -d: -f6 <<< "$ligne")"
    verifie "shell $1" "$3" "$(cut -d: -f7 <<< "$ligne")"
    return 0
}

# ATTENTION : groupadd modifie /etc/group.
creer_groupe() {             # NOM
    jeu_pret
    attention groupadd "$1"
    sudo /usr/sbin/groupadd --system "$1"
    noter_creation groupe "$1"
}

# ATTENTION : useradd modifie /etc/passwd et /etc/shadow ; le compte est créé sans mot de passe (verrouillé).
# Sources, pages installées (man -L en) : useradd(8), « -g, --gid GROUP : The group name or number of the user's initial
# login group. The group name must exist. » ; « -b, --base-dir BASE_DIR : The default base directory for the
# system if -d HOME_DIR is not specified. BASE_DIR is concatenated with the account name to define the home
# directory. » ; « -d, --home-dir HOME_DIR : The new user will be created using HOME_DIR as the value for the
# user's login directory. » ; « -M, --no-create-home : Do not create the user's home directory, even if the system
# wide setting from /etc/login.defs (CREATE_HOME) is set to yes. » ; adduser(8) : « If no home directory is
# specified, the default home directory for a new system user is /nonexistent. This directory should never exist
# on any Debian system, and adduser will never create it automatically. » Sans --home-dir, le répertoire serait
# sous le répertoire de base (/home).
creer_compte() {             # NOM HOME SHELL
    jeu_pret
    attention useradd "$1"
    sudo /usr/sbin/useradd --system --gid "$1" --no-create-home --home-dir "$2" --shell "$3" "$1"
    noter_creation compte "$1"
}

# comptes_conformes : 0 si tous les groupes et comptes des tables existent, conformes.
comptes_conformes() {
    local ligne nom home shell rc=0
    for nom in "${TABLE_GROUPES[@]}"; do
        groupe_etat "$nom" || rc=1
    done
    for ligne in "${TABLE_COMPTES[@]}"; do
        read -r nom home shell <<< "$ligne"
        compte_etat "$nom" "$home" "$shell" || rc=1
    done
    return "$rc"
}

# creer_comptes : crée seulement ce qui manque, groupes d'abord puis comptes.
creer_comptes() {
    local ligne nom home shell
    for nom in "${TABLE_GROUPES[@]}"; do
        if ! groupe_etat "$nom"; then
            creer_groupe "$nom"
        fi
    done
    for ligne in "${TABLE_COMPTES[@]}"; do
        read -r nom home shell <<< "$ligne"
        if ! compte_etat "$nom" "$home" "$shell"; then
            creer_compte "$nom" "$home" "$shell"
        fi
    done
}

# releve_identifiants : uid et gid réels des tables, entiers décimaux dans la plage système (arrêt 78 sinon).
releve_identifiants() {
    local ligne nom home shell valeur
    IDENT=()
    for nom in "${TABLE_GROUPES[@]}"; do
        valeur=$({ getent group "$nom" || true; } | cut -d: -f3)
        if ! dans_plage GID "$valeur"; then
            ecart "gid $nom" "$(plage_texte GID)" "${valeur:-absent}"
        fi
        IDENT["groupe:$nom"]=$((10#$valeur))
    done
    for ligne in "${TABLE_COMPTES[@]}"; do
        read -r nom home shell <<< "$ligne"
        valeur=$({ getent passwd "$nom" || true; } | cut -d: -f3)
        if ! dans_plage UID "$valeur"; then
            ecart "uid $nom" "$(plage_texte UID)" "${valeur:-absent}"
        fi
        IDENT["compte:$nom"]=$((10#$valeur))
    done
}

# verifier_comptes : identifiants relevés après création (bloquant).
verifier_comptes() {
    local ligne nom home shell
    releve_identifiants
    for ligne in "${TABLE_COMPTES[@]}"; do
        read -r nom home shell <<< "$ligne"
        verifie "id -g $nom" "${IDENT[groupe:$nom]}" "$(id -g "$nom")"
    done
}

# Programme python de composition de la configuration (bibliothèque standard seule) : lit le fichier livré et ne
# remplace que la valeur de chaque clé ciblée dans sa section ; arrêt 3 (avec « section.clé » sur la sortie) si un
# couple est absent, ambigu ou de valeur non numérique. Commentaires, ordre et autres clés sont conservés.
PYCONF='import re, sys
try:
    with open(sys.argv[1], encoding="utf-8") as f:
        lignes = "".join(f).split("\n")
except (OSError, ValueError):
    sys.exit(3)
couples = [tuple(sys.argv[i:i + 3]) for i in range(2, len(sys.argv), 3)]
vus = {}
for section, cle, valeur in couples:
    if (section, cle) in vus or not re.fullmatch("[0-9]{1,10}", valeur):
        sys.stdout.write(section + "." + cle)
        sys.exit(3)
    vus[(section, cle)] = 0
section = None
sortie = []
for ligne in lignes:
    m = re.match(r"^\s*\[([^\[\]]+)\]\s*$", ligne)
    if m:
        section = m.group(1).strip()
    else:
        for (sec, cle, valeur) in couples:
            k = re.match(r"^(\s*" + re.escape(cle) + r"\s*=\s*)[0-9]+(\s*(?:#.*)?)$", ligne)
            if sec == section and k:
                ligne = k.group(1) + valeur + k.group(2)
                vus[(sec, cle)] += 1
    sortie.append(ligne)
for (sec, cle), n in vus.items():
    if n != 1:
        sys.stdout.write(sec + "." + cle)
        sys.exit(3)
sys.stdout.write("\n".join(sortie))'

# composer_configuration SOURCE : compose, dans COMPOSEE, la configuration livrée où les numéros de TABLE_CONFIG
# (« section clé compte|groupe NOM ») sont ceux relevés sur le système. Rien n'est écrit. Avec « essai » en second
# argument, seule la présence unique de chaque couple dans le fichier livré est contrôlée (avant toute création).
COMPOSEE=''
composer_configuration() {      # SOURCE [essai]
    local ligne section cle genre nom contenu rc=0 valeur=1
    local -a args=()
    if [ "${2:-}" != essai ]; then
        releve_identifiants
    fi
    for ligne in "${TABLE_CONFIG[@]}"; do
        read -r section cle genre nom <<< "$ligne"
        if [ "${2:-}" != essai ]; then
            valeur=${IDENT[$genre:$nom]:-}
            if [ -z "$valeur" ]; then
                ecart "$section.$cle" "$genre $nom" "absent"
            fi
        fi
        args+=("$section" "$cle" "$valeur")
    done
    contenu=$(/usr/bin/python3 -I -P -c "$PYCONF" "$1" "${args[@]}") || rc=$?
    if [ "$rc" -ne 0 ]; then
        ecart "configuration $(basename -- "$1") : $(printf '%s' "$contenu" | filtre_sortie)" "un couple" "absent ou ambigu"
    fi
    if [ "${2:-}" != essai ]; then
        COMPOSEE=$contenu
    fi
}

# a_poser_composee DESTINATION MODE : 0 = à poser (la configuration composée est alors écrite dans CONF_COMPOSEE, dossier
# de travail de root), 1 = déjà conforme (rien n'est écrit) ; refus (78) si différent sans autorisation (a_poser).
a_poser_composee() {
    if existe "$1" && [ "$(lire_systeme "$1")" = "$COMPOSEE" ] && [ "$(attributs "$1")" = "root:root ${2#0}" ]; then
        return 1
    fi
    printf '%s\n' "$COMPOSEE" | sudo /usr/bin/tee "$CONF_COMPOSEE" > /dev/null
    a_poser "$CONF_COMPOSEE" "$1" "$2"
}

membre() {                   # COMPTE GROUPE : 0 si le compte appartient au groupe
    [[ " $(id -nG "$1") " == *" $2 "* ]]
}

# dossier_etat CHEMIN ATTENDU : 0 conforme, 1 absent ; arrêt 78 si différent.
dossier_etat() {
    local releve
    if ! existe "$1"; then
        return 1
    fi
    releve=$(attributs "$1")
    if [ "$releve" != "$2" ]; then
        ecart "$1" "$2" "$releve"
    fi
    return 0
}

# retrouve_dans_jeu CHEMIN : 0 si l'installation a sauvegardé ou marqué ce chemin dans le jeu.
dans_jeu() {
    outil_q retrouver --jeu "$JEU" "$1" > /dev/null 2>&1
}

# supprimer_comptes_crees : comptes puis groupes que cette installation a créés (jamais userdel -r).
# ATTENTION : userdel et groupdel sont destructifs ; ne visent que ce que le jeu a consigné.
supprimer_comptes_crees() {
    local ligne nom home shell
    for ligne in "${TABLE_COMPTES_ARRIERE[@]}"; do
        read -r nom home shell <<< "$ligne"
        if cree_par_installation compte "$nom" && getent passwd "$nom" > /dev/null; then
            attention userdel "$nom"
            sudo /usr/sbin/userdel "$nom"
        fi
    done
    for nom in "${TABLE_GROUPES_ARRIERE[@]}"; do
        if cree_par_installation groupe "$nom" && getent group "$nom" > /dev/null; then
            attention groupdel "$nom"
            sudo /usr/sbin/groupdel "$nom"
        fi
    done
}

# ---------------------------------------------------------------------------
# Mise à jour d'une installation existante (--mise-a-jour) : versions, unités de Paresia, fichiers de
# configuration de l'administrateur, retour arrière. Sans cette option, rien de ce bloc n'agit.
# Les listes d'unités sont fermées et écrites dans chaque script (MAJ_UNITES, MAJ_POSSIBLES) : jamais lues d'un fichier
# ni d'un paramètre. Seuls systemctl stop et systemctl start sont lancés, jamais restart, enable ou disable.
# ---------------------------------------------------------------------------

# lire_version CHEMIN [root] : version X.Y.Z du fichier, contrôlée comme server/commun/version.py (128 octets au plus,
# un seul saut de ligne final accepté) ; rien sur la sortie standard si le contenu est invalide.
lire_version() {
    local LC_ALL=C contenu taille
    if [ "${2:-}" = root ]; then
        taille=$(sudo /usr/bin/stat -c '%s' -- "$1")
        contenu=$(lire_systeme "$1"; printf x)
    else
        taille=$(stat -c '%s' -- "$1")
        contenu=$(cat -- "$1"; printf x)
    fi
    contenu=${contenu%x}
    contenu=${contenu%$'\n'}
    # la taille du fichier rejette un octet nul, que l'interpréteur retirerait de la lecture
    if [ "${#contenu}" -le 128 ] && [[ $contenu =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] \
        && { [ "$taille" = "${#contenu}" ] || [ "$taille" = "$((${#contenu} + 1))" ]; }; then
        printf '%s\n' "$contenu"
    fi
}

# ordre_versions A B : -1 si A est plus ancienne que B, 0 si elles sont égales, 1 si A est plus récente.
ordre_versions() {
    local -a a b
    local i
    IFS=. read -ra a <<< "$1"
    IFS=. read -ra b <<< "$2"
    for i in 0 1 2; do
        if [ $((10#${a[i]})) -lt $((10#${b[i]})) ]; then
            printf '%s\n' -1
            return 0
        elif [ $((10#${a[i]})) -gt $((10#${b[i]})) ]; then
            printf '%s\n' 1
            return 0
        fi
    done
    printf '%s\n' 0
}

# format_manifeste FICHIER [root] : valeur de VERSION_MANIFESTE dans le module server.sauvegarde (lecture seule, jamais
# présumée) ; vide si la constante manque.
format_manifeste() {
    local ligne
    if [ "${2:-}" = root ]; then
        ligne=$(sudo /usr/bin/grep -E '^VERSION_MANIFESTE = [0-9]+$' -- "$1" | awk 'NR==1' | filtre_sortie || true)
    else
        ligne=$(grep -E '^VERSION_MANIFESTE = [0-9]+$' -- "$1" | awk 'NR==1' | filtre_sortie || true)
    fi
    printf '%s\n' "${ligne#VERSION_MANIFESTE = }"
}

# --- empreintes SHA-256 des fichiers de configuration livrés (style conffiles de dpkg) ---------------------------------
empreinte_valide() {         # VALEUR : 64 chiffres hexadécimaux minuscules
    [[ $1 =~ ^[0-9a-f]{64}$ ]]
}

empreinte_de() {             # FICHIER -> empreinte SHA-256
    local valeur
    valeur=$(sudo /usr/bin/sha256sum -- "$1" | awk 'NR==1 {print $1}' | filtre_sortie)
    if ! empreinte_valide "$valeur"; then
        ecart "sha256sum:$1" "64 hex" "illisible"
    fi
    printf '%s\n' "$valeur"
}

empreinte_texte() {          # empreinte SHA-256 de l'entrée standard
    local valeur
    valeur=$(sudo /usr/bin/sha256sum | awk 'NR==1 {print $1}' | filtre_sortie)
    if ! empreinte_valide "$valeur"; then
        ecart "sha256sum" "64 hex" "illisible"
    fi
    printf '%s\n' "$valeur"
}

# charger_empreintes : relit le fichier d'empreintes (une ligne « <empreinte>  <chemin> » par fichier) ; une ligne
# illisible, mal formée ou en double est un écart (78), sans rien modifier.
charger_empreintes() {
    local contenu ligne numero=0
    EMPREINTES=()
    if ! existe "$INSTALLE_EMPREINTES"; then
        return 0
    fi
    contenu=$(lire_systeme "$INSTALLE_EMPREINTES"; printf x)
    contenu=${contenu%x}
    while IFS= read -r ligne || [ -n "$ligne" ]; do
        numero=$((numero + 1))
        if ! [[ $ligne =~ ^([0-9a-f]{64})\ \ (/[A-Za-z0-9._/-]+)$ ]]; then
            ecart "$INSTALLE_EMPREINTES" "empreinte et chemin" "ligne $numero"
        fi
        if [[ -v EMPREINTES[${BASH_REMATCH[2]}] ]]; then
            ecart "$INSTALLE_EMPREINTES" "une ligne par fichier" "ligne $numero"
        fi
        EMPREINTES[${BASH_REMATCH[2]}]=${BASH_REMATCH[1]}
    done < <(printf '%s' "$contenu")
}

# ecrire_empreintes : écrit le fichier d'empreintes (root:root 0644) par install, jamais par redirection ; sauvegardé avant.
ecrire_empreintes() {
    local chemin sortie=''
    if sudo /usr/bin/test -L "$INSTALLE_EMPREINTES"; then
        arreter "$EX_CONFIG" install_err_copie_code
    fi
    sauvegarder "$INSTALLE_EMPREINTES"
    while IFS= read -r chemin; do
        if [ -n "$chemin" ]; then
            sortie="$sortie${EMPREINTES[$chemin]}  $chemin"$'\n'
        fi
    done < <(printf '%s\n' "${!EMPREINTES[@]}" | sort)
    printf '%s' "$sortie" | sudo /usr/bin/tee "$TRAVAIL/empreintes-conf.nouveau" > /dev/null
    # ATTENTION : install écrase le fichier d'empreintes (copie préalable par l'outil de sauvegarde).
    attention install "$INSTALLE_EMPREINTES"
    sudo /usr/bin/install -m 0644 -o root -g root -- "$TRAVAIL/empreintes-conf.nouveau" "$INSTALLE_EMPREINTES"
}

# conf_conforme DEST EMPREINTE_LIVREE : 0 si rien n'est à faire sous mise à jour. Le fichier installé est identique à la
# version livrée (propriétaire et droits compris), ou il a été modifié par l'administrateur (empreinte différente de
# l'empreinte enregistrée, ou absente) et la version livrée est déjà à côté, en .paresia-nouveau.
conf_conforme() {
    local actuelle
    if ! existe "$1"; then
        return 1
    fi
    actuelle=$(empreinte_de "$1")
    if [ "$actuelle" = "$2" ]; then
        [ "$(attributs "$1")" = "root:root 644" ]
        return
    fi
    if [ "${EMPREINTES[$1]:-}" != "$actuelle" ] && existe "$1.paresia-nouveau" && [ "$(empreinte_de "$1.paresia-nouveau")" = "$2" ]; then
        return 0
    fi
    return 1
}

# PYOPT : noms des sections et options du premier fichier (installé) et du second (livré) ; affiche « +nom » pour une
# option nouvelle et « -nom » pour une option supprimée, jamais une valeur. Format lu comme server/commun/config.py
# (configparser, sans interpolation).
PYOPT='import configparser, sys
def noms(chemin):
    fichier = configparser.ConfigParser(interpolation=None, strict=True)
    with open(chemin, encoding="utf-8") as entree:
        fichier.read_file(entree)
    sortie = set()
    for section in fichier.sections():
        sortie.add("[" + section + "]")
        for cle in fichier[section]:
            sortie.add(section + "." + cle)
    return sortie
try:
    ancien = noms(sys.argv[1])
    nouveau = noms(sys.argv[2])
except (OSError, ValueError, configparser.Error):
    sys.exit(3)
for nom in sorted(nouveau - ancien):
    sys.stdout.write("+" + nom + "\n")
for nom in sorted(ancien - nouveau):
    sys.stdout.write("-" + nom + "\n")'

# conf_options INSTALLE LIVRE : affiche sur la sortie standard les options nouvelles et supprimées (noms seulement).
conf_options() {
    local ligne rc=0 sortie
    # les contenus passent par des descripteurs de fichier (jamais par argv, lisible dans /proc/<pid>/cmdline)
    sortie=$(/usr/bin/python3 -I -P -c "$PYOPT" <(lire_systeme "$1") <(lire_systeme "$2") | filtre_sortie) || rc=$?
    if [ "$rc" -ne 0 ]; then
        msg install_maj_options_illisibles "chemin=$1"
        return 0
    fi
    while IFS= read -r ligne; do
        case $ligne in
            +*) msg_out install_maj_option_nouvelle "chemin=$1" "option=${ligne#+}" ;;
            -*) msg_out install_maj_option_supprimee "chemin=$1" "option=${ligne#-}" ;;
        esac
    done <<< "$sortie"
}

# conf_appliquer DEST SOURCE : règle des fichiers de configuration sous mise à jour. Non modifié par l'administrateur
# (empreinte installée égale à l'empreinte enregistrée) : remplacé par la version livrée après sauvegarde. Modifié, ou
# empreinte absente : conservé octet pour octet, version livrée déposée à côté en DEST.paresia-nouveau et options nouvelles
# ou supprimées signalées. L'empreinte enregistrée est toujours celle de la version livrée.
conf_appliquer() {
    local dest=$1 source=$2 livree actuelle nouveau
    nouveau=$dest.paresia-nouveau
    livree=$(empreinte_de "$source")
    if sudo /usr/bin/test -L "$dest" || sudo /usr/bin/test -L "$nouveau"; then
        arreter "$EX_CONFIG" install_err_copie_code
    fi
    if ! existe "$dest"; then
        poser_fichier "$source" "$dest" 0644
        EMPREINTES[$dest]=$livree
        return 0
    fi
    actuelle=$(empreinte_de "$dest")
    if [ "$actuelle" = "$livree" ]; then
        if [ "$(attributs "$dest")" != "root:root 644" ]; then
            poser_fichier "$source" "$dest" 0644
        fi
    elif [ "${EMPREINTES[$dest]:-}" = "$actuelle" ]; then
        poser_fichier "$source" "$dest" 0644
    else
        if ! existe "$nouveau" || [ "$(empreinte_de "$nouveau")" != "$livree" ]; then
            sauvegarder "$nouveau"
            # ATTENTION : install écrit la version livrée à côté du fichier de l'administrateur, qui n'est pas touché.
            attention install "$nouveau"
            sudo /usr/bin/install -m 0644 -o root -g root -- "$source" "$nouveau"
        fi
        msg install_maj_conf_conservee "chemin=$dest" "nouveau=$nouveau"
        conf_options "$dest" "$nouveau"
    fi
    EMPREINTES[$dest]=$livree
}

# ecrire_composee : écrit la configuration composée (COMPOSEE) dans la zone de travail de root.
ecrire_composee() {
    printf '%s\n' "$COMPOSEE" | sudo /usr/bin/tee "$CONF_COMPOSEE" > /dev/null
}

# --- unités de Paresia -----------------------------------------------------------------------------------------------
maj_dans_liste() {           # UNITE : 0 si, sous mise à jour, l'unité est dans la liste fermée de la machine
    local u
    if [ "$MISE_A_JOUR" != oui ]; then
        return 1
    fi
    for u in "${MAJ_UNITES[@]}"; do
        if [ "$u" = "$1" ]; then
            return 0
        fi
    done
    return 1
}

maj_dans_actives() {         # UNITE : 0 si l'unité était active avant la mise à jour (relevé)
    local u
    for u in "${MAJ_ACTIVES[@]}"; do
        if [ "$u" = "$1" ]; then
            return 0
        fi
    done
    return 1
}

# unite_visee UNITE : 0 si l'unité doit être active en fin de passe (installation : toujours ; mise à jour : si elle
# l'était avant, une unité inactive avant restant inactive).
unite_visee() {
    if [ "$MISE_A_JOUR" != oui ]; then
        return 0
    fi
    maj_dans_actives "$1"
}

maj_attendre_active() {      # UNITE : attente de l'état actif (start des unités Type=notify revient à READY=1)
    local essai=0
    until unite_active "$1"; do
        essai=$((essai + 1))
        if [ "$essai" -gt 30 ]; then
            arreter "$EX_CONFIG" install_err_maj_inactive "unite=$1"
        fi
        sleep 1
    done
}

# maj_avant_demarrage / maj_apres_demarrage UNITE : encadrent chaque systemctl start (jamais restart) d'une mise à jour. L'heure
# du premier démarrage borne la lecture du journal ; l'unité est consignée puis attendue à l'état actif. Sans mise à jour,
# aucun effet.
maj_avant_demarrage() {
    if [ "$MISE_A_JOUR" = oui ]; then
        if [ -z "$MAJ_HEURE" ]; then
            printf -v MAJ_HEURE '%(%Y-%m-%d %H:%M:%S)T' -1
        fi
        # consignée avant le start : un démarrage qui échoue après une migration de données doit rester connu
        MAJ_REDEMARREES+=("$1")
    fi
}

maj_apres_demarrage() {
    if [ "$MISE_A_JOUR" = oui ]; then
        maj_attendre_active "$1"
    fi
}

# maj_arreter_unites : une seule fois, avant le premier remplacement. Sauvegarde complète du jeu, puis arrêt des seules
# unités de la liste qui étaient actives, dans l'ordre de la liste. Dès l'arrêt, tout échec déclenche le retour arrière
# automatique (sortie_script).
maj_arreter_unites() {
    local unite
    if [ "$MISE_A_JOUR" != oui ] || [ "$MAJ_ARRETE" = oui ]; then
        return 0
    fi
    MAJ_ARRETE=oui
    maj_liste_sauvegarde
    sauvegarder_arbre "${MAJ_SAUVEGARDE[@]}"
    MAJ_PHASE=remplacement
    for unite in "${MAJ_ACTIVES[@]}"; do
        msg install_maj_arret "unite=$unite" "effet=$(formater "$(maj_cle_effet "$unite")")"
        # ATTENTION : arrêter une unité de Paresia ; l'effet est annoncé ci-dessus.
        attention "systemctl stop" "$unite"
        sudo /usr/bin/systemctl stop "$unite"
    done
}

maj_ajouter() {              # NOM : consigne un fichier livré qui diffère (une seule fois)
    if [[ " ${MAJ_DIFFERENCES[*]:-} " != *" $1 "* ]]; then
        MAJ_DIFFERENCES+=("$1")
    fi
}

# --- détection (étape mise_a_jour_etat) ---------------------------------------------------------------------------------
# maj_detecter : relève sans rien modifier les versions, les unités de la liste actives et les fichiers livrés qui
# diffèrent ; refuse (78) avant toute modification.
maj_detecter() {
    local unite ancienne livree
    MAJ_DIFFERENCES=()
    MAJ_ACTIVES=()
    if ! existe "$INSTALLE_VERSION"; then
        if existe "$INSTALLE_CODE"; then
            ecart "$INSTALLE_VERSION" "X.Y.Z" "absent"
        fi
        arreter "$EX_CONFIG" install_err_maj_absente
    fi
    ancienne=$(lire_version "$INSTALLE_VERSION" root)
    if [ -z "$ancienne" ]; then
        ecart "$INSTALLE_VERSION" "X.Y.Z" "illisible"
    fi
    livree=$(lire_version "$DEPOT/VERSION")
    if [ -z "$livree" ]; then
        ecart "$DEPOT/VERSION" "X.Y.Z" "illisible"
    fi
    MAJ_VERSION_INSTALLEE=$ancienne
    MAJ_VERSION_LIVREE=$livree
    msg_out install_maj_versions "installee=$ancienne" "livree=$livree"
    if [ "$(ordre_versions "$livree" "$ancienne")" = -1 ]; then
        arreter "$EX_CONFIG" install_err_maj_retrograde "installee=$ancienne" "livree=$livree"
    fi
    if [ "$livree" != "$ancienne" ]; then
        ancienne=$(format_manifeste "$INSTALLE_CODE/sauvegarde/__init__.py" root)
        livree=$(format_manifeste "$DEPOT/server/sauvegarde/__init__.py")
        if [ -z "$ancienne" ] || [ -z "$livree" ]; then
            ecart "VERSION_MANIFESTE" "un entier" "absent"
        fi
        if [ "$ancienne" != "$livree" ]; then
            arreter "$EX_CONFIG" install_err_maj_manifeste "installe=$ancienne" "livre=$livree"
        fi
    fi
    maj_unites_liste
    for unite in "${MAJ_UNITES[@]}"; do
        if unite_active "$unite"; then
            MAJ_ACTIVES+=("$unite")
        fi
    done
    charger_empreintes
    maj_differences
    if [ "${#MAJ_DIFFERENCES[@]}" -gt 0 ]; then
        refuser_si_active "${MAJ_HORS_LISTE[@]}"
        if [[ " ${MAJ_DIFFERENCES[*]} " == *" sshd "* ]]; then
            exiger_session_secours
        fi
    fi
}

# maj_noter_jeu : relevé « mise-a-jour » du jeu (versions, unités actives avant, fichiers qui diffèrent), écrit à la
# création du jeu ; il distingue un jeu de mise à jour d'un jeu d'installation au retour arrière.
maj_noter_jeu() {
    if [ "$MISE_A_JOUR" != oui ] || [ -z "$MAJ_VERSION_LIVREE" ]; then
        return 0
    fi
    printf 'avant=%s\napres=%s\nactives=%s\ndifferences=%s\n' "$MAJ_VERSION_INSTALLEE" "$MAJ_VERSION_LIVREE" \
        "${MAJ_ACTIVES[*]}" "${MAJ_DIFFERENCES[*]}" | releve mise-a-jour
}

deja_conforme_mise_a_jour_etat() {
    maj_detecter
    [ "${#MAJ_DIFFERENCES[@]}" -eq 0 ]
}

# Annonce avant toute modification et avant tout arrêt : unités qui vont être arrêtées, effet, nom du jeu. Le jeu est créé
# ici pour que son nom soit connu ; aucun fichier du système n'est modifié.
etape_mise_a_jour_etat() {
    local unite
    jeu_pret
    msg install_maj_annonce "installee=$MAJ_VERSION_INSTALLEE" "livree=$MAJ_VERSION_LIVREE" "jeu=$JEU"
    for unite in "${MAJ_ACTIVES[@]}"; do
        msg install_maj_annonce_unite "unite=$unite" "effet=$(formater "$(maj_cle_effet "$unite")")"
    done
    if [ "${#MAJ_ACTIVES[@]}" -eq 0 ]; then
        msg install_maj_aucune_unite
    fi
}

verifier_mise_a_jour_etat() {
    releve_info "mise-a-jour" "$MAJ_VERSION_INSTALLEE -> $MAJ_VERSION_LIVREE"
}

# maj_terminer : fin d'une mise à jour réussie ; version installée égale à la version livrée (lecture contrôlée de VERSION,
# que les démons lisent à cet endroit : aucun code installé n'est exécuté en root pour la lire), commande de lecture du
# journal de chaque unité redémarrée (un éventuel message de migration des données y figure).
maj_terminer() {
    local unite
    if [ "$MISE_A_JOUR" != oui ] || [ "$MAJ_ARRETE" != oui ]; then
        return 0
    fi
    verifie "version-installee" "$MAJ_VERSION_LIVREE" "$(lire_version "$INSTALLE_VERSION" root)"
    MAJ_PHASE=''
    for unite in "${MAJ_REDEMARREES[@]}"; do
        msg_out install_maj_journal "unite=$unite" "commande=sudo /usr/bin/journalctl -u $unite -n 30 --no-pager"
    done
    msg_out install_maj_terminee "installee=$MAJ_VERSION_INSTALLEE" "livree=$MAJ_VERSION_LIVREE" "jeu=$JEU"
}

# --- retour arrière d'une mise à jour (automatique ou manuel) -------------------------------------------------------------
# maj_jeu_de_mise_a_jour : 0 si le jeu JEU porte le relevé « mise-a-jour », 1 s'il s'agit d'un jeu d'installation ; un jeu
# que l'outil refuse (format de manifeste ancien) arrête le script sans rien modifier.
maj_jeu_de_mise_a_jour() {
    local rc=0
    outil_q retrouver --releve mise-a-jour --jeu "$JEU" > /dev/null 2>&1 || rc=$?
    case $rc in
        0) return 0 ;;
        5) return 1 ;;
        *) arreter "$EX_IOERR" install_err_retour "chemin=mise-a-jour" ;;
    esac
}

# maj_charger_releve : relit les versions et les unités actives avant, consignées dans le jeu ; seules les unités de la
# liste fermée MAJ_POSSIBLES sont retenues.
maj_charger_releve() {
    local copie ligne unite possible
    local -a liste
    copie=$(outil_q retrouver --releve mise-a-jour --jeu "$JEU" | cut -f3)
    MAJ_ACTIVES=()
    while IFS= read -r ligne; do
        case $ligne in
            avant=*) MAJ_VERSION_INSTALLEE=${ligne#avant=} ;;
            apres=*) MAJ_VERSION_LIVREE=${ligne#apres=} ;;
            actives=*)
                read -ra liste <<< "${ligne#actives=}"
                for unite in "${liste[@]}"; do
                    for possible in "${MAJ_POSSIBLES[@]}"; do
                        if [ "$unite" = "$possible" ]; then
                            MAJ_ACTIVES+=("$unite")
                        fi
                    done
                done
                ;;
        esac
    done < <(sudo /usr/bin/cat -- "$copie")
    if ! [[ $MAJ_VERSION_INSTALLEE =~ ^[0-9]+\.[0-9]+\.[0-9]+$ && $MAJ_VERSION_LIVREE =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        arreter "$EX_IOERR" install_err_retour "chemin=mise-a-jour"
    fi
}

# maj_migration_detectee : 0 si le journal d'une unité redémarrée montre une migration de données (ou s'il est illisible :
# dans le doute, rien n'est restauré) ; l'unité est écrite sur la sortie standard.
maj_migration_detectee() {
    local unite journal
    for unite in "${MAJ_REDEMARREES[@]}"; do
        if ! journal=$(sudo /usr/bin/journalctl -u "$unite" --since "$MAJ_HEURE" --no-pager); then
            printf '%s\n' "$unite"
            return 0
        fi
        if [ "$(grep -c -E "$MAJ_MOTIF_MIGRATION" <<< "$journal" || true)" != 0 ]; then
            printf '%s\n' "$unite"
            return 0
        fi
    done
    return 1
}

# maj_restaurer : arrêt des seules unités de la liste, restauration du jeu en ordre inverse (code, VERSION, unités,
# configuration, fichier d'empreintes, fichiers .paresia-nouveau), rechargement, reprise des unités actives avant. Aucun
# compte ni groupe n'est supprimé. Retourne 1 si une étape échoue.
maj_restaurer() {
    local indice chemin unite pose_sshd=non
    pose_complete
    maj_charger_releve
    if sshd_dans_jeu; then
        pose_sshd=oui
        exiger_session_secours
    fi
    for unite in "${MAJ_POSSIBLES[@]}"; do
        if unite_active "$unite" && { [ "$unite" != paresia-tunnel.service ] || maj_dans_actives "$unite"; }; then
            msg install_maj_arret "unite=$unite" "effet=$(formater "$(maj_cle_effet "$unite")")"
            # ATTENTION : arrêter une unité de Paresia avant de restaurer son code ; l'effet est annoncé ci-dessus.
            attention "systemctl stop" "$unite"
            sudo /usr/bin/systemctl stop "$unite" || return 1
        fi
    done
    for ((indice = ${#POSE[@]} - 1; indice >= 0; indice--)); do
        chemin=${POSE[$indice]}
        if restaurer_si_pose "$chemin"; then
            hook alpha_verifie "restored" "$chemin"
        fi
    done
    maj_apres_restauration || return 1
    if [ "$pose_sshd" = oui ]; then
        recharger_ssh
    fi
    sudo /usr/bin/systemctl daemon-reload || return 1
    for ((indice = ${#MAJ_ACTIVES[@]} - 1; indice >= 0; indice--)); do
        unite=${MAJ_ACTIVES[$indice]}
        # ATTENTION : reprise d'une unité de Paresia qui était active avant la mise à jour.
        attention "systemctl start" "$unite"
        sudo /usr/bin/systemctl start "$unite" || return 1
        maj_attendre_active "$unite"
    done
    [ "$(lire_version "$INSTALLE_VERSION" root)" = "$MAJ_VERSION_INSTALLEE" ] || return 1
}

# maj_retour_manuel : --retour-arriere sur un jeu de mise à jour.
maj_retour_manuel() {
    msg install_maj_retour_arret
    if ! maj_restaurer; then
        arreter "$EX_CONFIG" install_err_maj_retour_echec "jeu=$JEU"
    fi
    msg install_retour_fait
}

# maj_echec_apres_arret : appelé dans un sous-shell par sortie_script quand le script échoue après l'arrêt des unités ; son
# code de retour est le code de sortie du script.
# Migration de données constatée au journal : aucun retour arrière, unités redémarrées arrêtées, marche à suivre. Sinon :
# retour arrière automatique du code et de la configuration (aucun compte supprimé). 
maj_echec_apres_arret() {
    local unite i
    if unite=$(maj_migration_detectee); then
        for ((i = ${#MAJ_REDEMARREES[@]} - 1; i >= 0; i--)); do
            # ATTENTION : arrêt des unités redémarrées pour que le nouveau code n'écrive plus dans les données migrées.
            attention "systemctl stop" "${MAJ_REDEMARREES[$i]}"
            sudo /usr/bin/systemctl stop "${MAJ_REDEMARREES[$i]}" || true
        done
        msg install_maj_migration "jeu=$JEU" "unite=$unite" \
            "commande=--retour-arriere --jeu $JEU --confirme"
        return "$EX_CONFIG"
    fi
    msg install_maj_retour_auto "jeu=$JEU" "code=$MAJ_CODE_ECHEC"
    if ! maj_restaurer; then
        msg install_err_maj_retour_echec "jeu=$JEU"
        return "$MAJ_CODE_ECHEC"
    fi
    msg install_maj_retour_auto_fait "jeu=$JEU"
    return "$EX_CONFIG"
}

# DEBUT alpha-test
# ---------------------------------------------------------------------------
# Option --alpha-test (temporaire) : affichage des vérifications, pause après chaque étape et
# journal horodaté sans secret. Tout ce bloc est retirable sans toucher aux étapes.
# ---------------------------------------------------------------------------
ALPHA_FICHIER=''
ALPHA_PID_ENTREE=''
ALPHA_PID_SORTIE=''
ALPHA_PID_TEE=''

alpha_flux() {               # DESCRIPTEUR : copie chaque ligne vers l'original et vers le journal horodaté
    local ligne
    while IFS= read -r ligne; do
        ligne=${ligne//[[:cntrl:]]/}
        printf '%s\n' "$ligne" >&"$1"
        printf '%(%Y-%m-%dT%H:%M:%SZ)T %s\n' -1 "$ligne" >&5
    done
}

# Le journal est créé en 0600 puis remis à l’appelant sous sudo ; dossier existant inchangé, jamais écrasé.
alpha_demarrer() {
    if [ ! -t 0 ]; then
        arreter "$EX_USAGE" install_err_terminal
    fi
    local fichier horodatage proprietaire mode
    printf -v horodatage '%(%Y%m%d-%H%M%S)T' -1
    fichier="$DOSSIER_JOURNAL/alpha-test-$MACHINE-$horodatage.log"
    # le dossier doit exister, appartenir à ce compte ou à root et n'être modifiable ni par le groupe ni par les autres,
    # avant toute création ; il n'est jamais modifié
    if [ ! -d "$DOSSIER_JOURNAL" ] || [ -L "$DOSSIER_JOURNAL" ]; then
        arreter "$EX_CONFIG" install_err_journal_dossier "chemin=$DOSSIER_JOURNAL"
    fi
    read -r proprietaire mode < <(stat -c '%u %a' -- "$DOSSIER_JOURNAL")
    if { [ "$proprietaire" != 0 ] && [ "$proprietaire" != "$EUID" ]; } || ! [[ $mode =~ ^[0-7]{3,4}$ ]] \
        || (( 8#$mode & 8#022 )); then
        arreter "$EX_CONFIG" install_err_journal_dossier "chemin=$DOSSIER_JOURNAL"
    fi
    if [ -e "$fichier" ]; then
        arreter "$EX_CANTCREAT" install_err_journal_existe "chemin=$fichier"
    fi
    # noclobber : création exclusive, jamais d'écrasement ; umask 077 puis chmod 0600 : droits 0600 même sous ACL par défaut
    if ! ( set -C; umask 077; : > "$fichier" && /usr/bin/chmod 0600 -- "$fichier" ) 2> /dev/null; then
        arreter "$EX_CONFIG" install_err_journal_dossier "chemin=$DOSSIER_JOURNAL"
    fi
    if [[ ${SUDO_UID:-} =~ ^[1-9][0-9]{0,9}$ && ${SUDO_GID:-} =~ ^[1-9][0-9]{0,9}$ ]] &&
        (( SUDO_UID <= 4294967294 && SUDO_GID <= 4294967294 )); then
        if ! sudo /usr/bin/chown -h -- "$SUDO_UID:$SUDO_GID" "$fichier"; then
            arreter "$EX_CONFIG" install_err_journal_dossier "chemin=$DOSSIER_JOURNAL"
        fi
    fi
    ALPHA_FICHIER=$fichier
    exec 3>&1 4>&2
    exec 5> >(/usr/bin/tee -a "$ALPHA_FICHIER" > /dev/null)
    ALPHA_PID_TEE=$!
    exec > >(alpha_flux 3)
    ALPHA_PID_SORTIE=$!
    exec 2> >(alpha_flux 4)
    ALPHA_PID_ENTREE=$!
    msg_out install_journal "chemin=$fichier"
}

alpha_verifie() {            # ELEMENT VALEUR
    msg install_verifie "element=$1" "valeur=$2"
}

alpha_releve() {             # ELEMENT VALEUR (peut tenir sur plusieurs lignes)
    local ligne
    while IFS= read -r ligne; do
        msg install_releve "element=$1" "valeur=$ligne"
    done <<< "$2"
}

alpha_attention() {          # COMMANDE OBJET
    msg install_attention "commande=$1" "objet=$2"
}

alpha_pause() {
    msg install_pause
    IFS= read -r _ < /dev/tty
}

alpha_fin() {
    if [ -z "$ALPHA_FICHIER" ]; then
        return 0
    fi
    msg_out install_journal_fin "chemin=$ALPHA_FICHIER" "commande=/usr/bin/cat $ALPHA_FICHIER"
    exec 1>&3 2>&4
    wait "$ALPHA_PID_SORTIE" "$ALPHA_PID_ENTREE" 2> /dev/null || true
    exec 5>&-
    wait "$ALPHA_PID_TEE" 2> /dev/null || true
    ALPHA_FICHIER=''
}
# FIN alpha-test

# ---------------------------------------------------------------------------
# Déroulement.
# ---------------------------------------------------------------------------
sortie_script() {
    local code=$?
    trap - EXIT
    if [ "$code" -ne 0 ] && { [ "$ARRET_MESSAGE" != oui ] || [ "$ALPHA" = oui ]; }; then
        msg install_echec "etape=$ETAPE_COURANTE" "code=$code"
    fi
    if [ "$code" -ne 0 ] && [ -n "$MAJ_PHASE" ]; then
        # échec après l'arrêt des unités de la mise à jour : migration constatée (rien n'est restauré) ou retour arrière
        MAJ_CODE_ECHEC=$code
        MAJ_PHASE=''
        ( maj_echec_apres_arret ) || code=$?
    fi
    hook alpha_fin
    exit "$code"
}

lancer_etapes() {
    local total=${#ETAPES[@]} numero=0 nom etat
    for nom in "${ETAPES[@]}"; do
        numero=$((numero + 1))
        ETAPE_COURANTE=$nom
        if etape_sautee "$nom"; then
            msg install_etape_sautee "numero=$numero" "total=$total" "nom=$nom"
            continue
        fi
        if "deja_conforme_$nom"; then
            etat=install_etape_deja
        else
            "etape_$nom"
            etat=install_etape_faite
        fi
        "verifier_$nom"
        msg "$etat" "numero=$numero" "total=$total" "nom=$nom"
        hook alpha_pause
    done
    ETAPE_COURANTE='-'
}

principal() {
    # le chemin du script (qui sert au défaut de DEPOT) est résolu d'abord, puis le dossier courant devient « / » :
    # aucune commande suivante ne lit ni n'exécute un fichier du dossier de lancement
    resoudre_racine_clone
    # le dossier d'exécution (défaut du journal) est relevé avant de passer à « / »
    DOSSIER_LANCEMENT=$(pwd -P 2> /dev/null || true)
    cd /
    trap sortie_script EXIT
    defauts_machine
    analyser "$@"
    if [ "$VERSION_DEMANDEE" = oui ]; then
        printf '%s %s\n' "$NOM_SCRIPT" "$VERSION_SCRIPT"
        exit 0
    fi
    valider_depot
    charger_catalogue
    if [ "$AIDE" = oui ]; then
        msg_out install_aide
        exit 0
    fi
    valider_communs
    valider_machine
    controle_identite
    construire_etapes
    if [ "$VERIFIER" = oui ]; then
        controle_prerequis
        exit 0
    fi
    if [ "$RETOUR" = oui ]; then
        retour_arriere
        exit 0
    fi
    if [ "$ALPHA" = oui ]; then
        hook alpha_demarrer
    fi
    lancer_etapes
    maj_terminer
    fin_machine
}
# FIN commun

# ---------------------------------------------------------------------------
# backend-admin : exécution en root, sans sudo installé (D138).
# Les commandes privilégiées restent écrites « sudo /usr/bin/… » (une par ligne, chemin
# absolu) pour que la liste d'en-tête soit vérifiable ; la fonction sudo() ci-dessous les
# exécute directement quand l'exécutable sudo est absent et que l'UID vaut 0.
# ---------------------------------------------------------------------------
sudo() {
    if type -P "sudo" > /dev/null || [ "$(id -u)" != 0 ]; then
        command "sudo" "$@"
    else
        "$@"
    fi
}

NOM_SCRIPT=installer-backend-admin
VERSION_SCRIPT=0.2.0
MACHINE='admin'
CONF_OUTIL=/run/paresia-installation/server/conf/paresia.conf
TUNNEL_ACTIF=non
ETAPES=()
TABLE_GROUPES=()
TABLE_COMPTES=()
TABLE_GROUPES_ARRIERE=()
TABLE_COMPTES_ARRIERE=()
TABLE_CONFIG=()
ADMIN_UNITES=(pollux romulus)
# Listes fermées de la mise à jour (jamais lues d'un fichier ni d'un paramètre) : unités dans l'ordre d'arrêt ; pollux puis
# romulus, et paresia-tunnel en dernier seulement si son unité ou la configuration du tunnel change.
MAJ_UNITES=(pollux.service romulus.service)
MAJ_POSSIBLES=(pollux.service romulus.service paresia-tunnel.service)
MAJ_HORS_LISTE=()

defauts_machine() {
    DEPOT="${DEPOT:-$(racine_clone)}"
    LANGUE="${LANGUE:-$(langue_defaut)}"
    DOSSIER_JOURNAL="${DOSSIER_JOURNAL:-$DOSSIER_LANCEMENT}"
    CODE_REMPLACEMENT_CONFIRME="${CODE_REMPLACEMENT_CONFIRME:-non}"
    MISE_A_JOUR="${MISE_A_JOUR:-non}"
    SESSION_SECOURS="${SESSION_SECOURS:-non}"
    PARESIA_SAUVEGARDE_STOCKAGE_ACTIF="${PARESIA_SAUVEGARDE_STOCKAGE_ACTIF:-oui}"
    REPERTOIRE_APP="${REPERTOIRE_APP:-/var/lib/paresia-app}"
    ADRESSE_RELAIS="${ADRESSE_RELAIS:-}"
    EMPREINTE_HOTE_RELAIS="${EMPREINTE_HOTE_RELAIS:-}"
}

option_machine() {
    case $1 in
        --repertoire-app) valeur_requise "$@"; REPERTOIRE_APP=$2 ;;
        --adresse-relais) valeur_requise "$@"; ADRESSE_RELAIS=$2 ;;
        --empreinte-hote-relais) valeur_requise "$@"; EMPREINTE_HOTE_RELAIS=$2 ;;
        *) return 1 ;;
    esac
}

valider_machine() {
    REPERTOIRE_APP=$(chemin_normalise REPERTOIRE_APP "$REPERTOIRE_APP")
    if [ "$REPERTOIRE_APP" != /var/lib/paresia-app ]; then
        # la configuration livrée désigne ce chemin (server/conf/paresia.conf)
        arreter "$EX_DATAERR" install_err_param_invalide "nom=REPERTOIRE_APP" "valeur=$REPERTOIRE_APP"
    fi
    if [ -n "$ADRESSE_RELAIS" ] || [ -n "$EMPREINTE_HOTE_RELAIS" ]; then
        if [ -z "$ADRESSE_RELAIS" ]; then
            arreter "$EX_USAGE" install_err_param_absent "nom=ADRESSE_RELAIS"
        fi
        if [ -z "$EMPREINTE_HOTE_RELAIS" ]; then
            arreter "$EX_USAGE" install_err_param_absent "nom=EMPREINTE_HOTE_RELAIS"
        fi
        valider_adresse ADRESSE_RELAIS "$ADRESSE_RELAIS"
        valider_empreinte EMPREINTE_HOTE_RELAIS "$EMPREINTE_HOTE_RELAIS"
        TUNNEL_ACTIF=oui
    fi
}

controle_identite() {
    if [ "$(id -u)" != 0 ]; then
        arreter "$EX_NOPERM" install_err_root_requis
    fi
}

# --- mise à jour : crochets propres à backend-admin (voir le bloc commun) ----------------------------------------------------
maj_cle_effet() {            # UNITE -> clé du catalogue qui décrit l'effet d'un arrêt
    case $1 in
        paresia-tunnel.service) printf '%s\n' install_maj_effet_tunnel ;;
        *) printf '%s\n' install_maj_effet_presence ;;
    esac
}

# maj_tunnel_change : 0 si l'unité du tunnel, son tmpfiles.d ou la configuration cliente du tunnel changent.
maj_tunnel_change() {
    if a_poser "$DEPOT/$TMPFILES_SOURCE" "$TMPFILES_TUNNEL" 0644; then
        return 0
    fi
    if a_poser "$DEPOT/deploy/backend-admin/etc/systemd/system/paresia-tunnel.service" /etc/systemd/system/paresia-tunnel.service 0644; then
        return 0
    fi
    ! tunnel_client_conforme
}

maj_unites_liste() {
    MAJ_UNITES=(pollux.service romulus.service)
    if [ "$TUNNEL_ACTIF" = oui ] && maj_tunnel_change; then
        MAJ_UNITES+=(paresia-tunnel.service)
    fi
}

# maj_differences : fichiers livrés dont le contenu diffère de celui qui est installé (lecture seule).
maj_differences() {
    local nom u livree
    MAJ_DIFFERENCES=()
    lire_declarations
    if ! code_conforme; then
        maj_ajouter code
    fi
    for nom in "${DECLARATIONS_NOMS[@]}"; do
        if a_poser "$DEPOT/$DECLARATIONS_DEPOT/$nom.toml" "$DECLARATIONS_DOSSIER/$nom.toml" 0644; then
            maj_ajouter declarations
        fi
    done
    livree=$(empreinte_de "$DEPOT/server/conf/paresia.conf")
    if ! conf_conforme "$CONF_BASE" "$livree"; then
        maj_ajouter configuration
    fi
    composer_configuration "$DEPOT/deploy/backend-admin/etc/paresia/conf.d/10-backend-admin.conf"
    livree=$(printf '%s\n' "$COMPOSEE" | empreinte_texte)
    if ! conf_conforme "$CONF_ADMIN" "$livree"; then
        maj_ajouter configuration
    fi
    if a_poser "$DEPOT/$SSHD_SOURCE_APP" "$SSHD_APP" 0644; then
        maj_ajouter sshd
    fi
    for u in "${ADMIN_UNITES[@]}"; do
        if a_poser "$DEPOT/$SRC_UNITES/$u.service" "/etc/systemd/system/$u.service" 0644; then
            maj_ajouter unites
        fi
    done
    if [ "$TUNNEL_ACTIF" = oui ] && maj_tunnel_change; then
        maj_ajouter tunnel
    fi
}

# maj_liste_sauvegarde : tout ce que la mise à jour peut remplacer ; sauvegardé en entier avant le premier arrêt. Aucune clé
# privée n'y figure.
maj_liste_sauvegarde() {
    local nom
    lire_declarations
    MAJ_SAUVEGARDE=(/usr/local/lib/paresia/server /usr/local/bin/pollux-session /usr/local/lib/paresia/VERSION "$INSTALLE_EMPREINTES"
        "$CONF_BASE" "$CONF_BASE.paresia-nouveau" "$CONF_ADMIN" "$CONF_ADMIN.paresia-nouveau" "$SSHD_APP"
        /etc/systemd/system/pollux.service /etc/systemd/system/romulus.service)
    for nom in "${DECLARATIONS_NOMS[@]}"; do
        MAJ_SAUVEGARDE+=("$DECLARATIONS_DOSSIER/$nom.toml")
    done
    if [ "$TUNNEL_ACTIF" = oui ]; then
        MAJ_SAUVEGARDE+=(/etc/systemd/system/paresia-tunnel.service "$TMPFILES_TUNNEL" /etc/paresia/tunnel/ssh_config
            /etc/paresia/tunnel/ssh_config.d/10-relais.conf)
    fi
}

sshd_dans_jeu() {            # 0 si le jeu a sauvegardé ou marqué le fichier sshd de cette machine
    dans_jeu "$SSHD_APP"
}

maj_apres_restauration() {   # contrôles propres à la machine après la restauration (aucun ici)
    return 0
}

# Relevés d'état avant, sans secret, consignés dans le jeu à sa création.
apres_creation_jeu() {
    { getent passwd app paresia-pollux paresia-romulus paresia-tunnel www-data || test "$?" -eq 2; } | releve comptes-avant
    { getent group app paresia-sessions paresia-liaison paresia-http paresia-pollux paresia-romulus paresia-tunnel || test "$?" -eq 2; } | releve groupes-avant
    releves_systeme_avant
}

construire_etapes() {
    # Noms fixes (D42), numéros attribués par le système ; le répertoire de app vient de REPERTOIRE_APP.
    TABLE_GROUPES=(paresia-sessions paresia-liaison paresia-http paresia-pollux paresia-romulus paresia-tunnel app)
    TABLE_COMPTES=("paresia-pollux /nonexistent /usr/sbin/nologin" "paresia-romulus /nonexistent /usr/sbin/nologin"
        "paresia-tunnel /nonexistent /usr/sbin/nologin" "app $REPERTOIRE_APP /bin/sh")
    TABLE_COMPTES_ARRIERE=("app $REPERTOIRE_APP /bin/sh" "paresia-tunnel x x" "paresia-romulus x x" "paresia-pollux x x")
    TABLE_GROUPES_ARRIERE=(app paresia-tunnel paresia-romulus paresia-pollux paresia-http paresia-liaison paresia-sessions)
    # Numéros inscrits dans conf.d/10-backend-admin.conf : « section clé compte|groupe NOM » (source unique).
    TABLE_CONFIG=("pollux.sessions uid compte app" "pollux.sessions gid groupe paresia-sessions"
        "pollux.relay uid compte paresia-romulus" "pollux.relay gid groupe paresia-liaison"
        "pollux.romulus uid compte paresia-romulus" "pollux.castor uid compte paresia-tunnel"
        "romulus.presence uid_pollux compte paresia-pollux" "romulus.presence gid groupe paresia-liaison"
        "romulus.http gid groupe paresia-http" "romulus.relay pollux_uid compte paresia-pollux"
        "romulus.relay remus_uid compte paresia-tunnel")
    ETAPES=(prerequis sauvegarde identifiants_comptes appartenances dossier_app code configuration web sshd_app
        unites demarrage refus tunnel_releves tunnel_cle)
    if [ "$TUNNEL_ACTIF" = oui ]; then
        ETAPES+=(tunnel_client tunnel_known_hosts tunnel_unite tunnel_sockets)
    fi
    if [ "$MISE_A_JOUR" = oui ]; then
        # sous mise à jour, le tunnel est remis en route avant Romulus et Pollux (ordre inverse de l'arrêt)
        ETAPES=(prerequis mise_a_jour_etat sauvegarde identifiants_comptes appartenances dossier_app code configuration
            sshd_app unites tunnel_releves tunnel_cle)
        if [ "$TUNNEL_ACTIF" = oui ]; then
            ETAPES+=(tunnel_client tunnel_known_hosts tunnel_unite)
        fi
        ETAPES+=(demarrage refus)
        if [ "$TUNNEL_ACTIF" = oui ]; then
            ETAPES+=(tunnel_sockets)
        fi
    fi
    ETAPES+=(activation)
}

fin_machine() {
    if [ "$TUNNEL_ACTIF" != oui ]; then
        msg install_suite_tunnel_admin
    fi
}

# ---------------------------------------------------------------------------
# Étape prerequis (lecture seule) : Debian 13, systemd, Python 3.11 ou plus, python3-cryptography, curl, ssh-keygen, sshd.
# Retour arrière : sans objet.
# ---------------------------------------------------------------------------
controle_prerequis() {
    local systeme paquet version
    local -r LIBSSL_MINIMUM=3.5.7-1~deb13u3
    executables_requis /usr/bin/python3 /usr/bin/env /usr/bin/curl /usr/bin/ssh /usr/bin/ssh-keygen /usr/bin/ssh-keyscan \
        /usr/sbin/sshd /usr/bin/systemctl /usr/bin/journalctl /usr/bin/systemd-analyze /usr/bin/systemd-tmpfiles \
        /usr/bin/nsenter /usr/bin/namei /usr/sbin/runuser /usr/sbin/groupadd /usr/sbin/useradd /usr/sbin/usermod \
        /usr/sbin/userdel /usr/sbin/groupdel /usr/bin/gpasswd /usr/bin/install /usr/bin/tar /usr/bin/chown /usr/bin/chmod \
        /usr/bin/find /usr/bin/tee /usr/bin/rm /usr/bin/rmdir /usr/bin/sed /usr/bin/diff /usr/bin/cat /usr/bin/grep \
        /usr/bin/stat /usr/bin/ls /usr/bin/test /usr/bin/getent /usr/bin/sha256sum /usr/bin/mv
    if ! command -v ss > /dev/null; then
        accumuler /usr/bin/ss
    fi
    if systeme=$(lire_systeme /etc/os-release); then
        if ! grep -q '^ID=debian$' <<< "$systeme" || ! grep -Eq '^VERSION_ID="?13"?$' <<< "$systeme"; then
            accumuler debian-13
        fi
    else
        accumuler os-release
    fi
    lire_systemd
    if [ -x /usr/bin/python3 ]; then
        if ! /usr/bin/python3 -I -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
            accumuler python-3.11
        fi
        if ! /usr/bin/python3 -I -c 'import cryptography'; then      # Pollux : l'ImportError dans _authentifier donne « not_available »
            accumuler python3-cryptography
        fi
    fi
    if ! paquet=$(sudo /usr/bin/dpkg-query -W -f='${Status}|${Version}' libssl3t64 2>/dev/null) ||
        [[ $paquet != 'install ok installed|'* ]]; then
        accumuler "libssl3t64-$LIBSSL_MINIMUM"
    else
        version=${paquet#*|}
        # dpkg(1) accepte une version mal formée avec un simple avertissement : la syntaxe est donc vérifiée d'abord.
        if [[ ! $version =~ ^([0-9]+:)?[0-9][A-Za-z0-9.+~-]*$ ]] || ! sudo /usr/bin/dpkg --compare-versions "$version" ge "$LIBSSL_MINIMUM" 2>/dev/null; then
            accumuler "libssl3t64-$LIBSSL_MINIMUM"
        fi
    fi
    controle_manques
}

deja_conforme_prerequis() { return 1; }
etape_prerequis() { controle_prerequis; }
verifier_prerequis() { releve_info "systemd" "$SYSTEMD_VERSION"; }

# ---------------------------------------------------------------------------
# Étape sauvegarde : copie root du code de l'outil de sauvegarde (D114). Le jeu daté est créé
# au premier fichier à sauvegarder et son nom est affiché sur la sortie standard.
# Retour arrière : la copie sous /run disparaît au redémarrage ; les jeux sont conservés.
# ---------------------------------------------------------------------------
deja_conforme_sauvegarde() { code_outil_en_place; }
etape_sauvegarde() { copier_code_outil; }
verifier_sauvegarde() { controle_attributs "$TRAVAIL" "root:root 700"; }

# ---------------------------------------------------------------------------
# Étape identifiants_comptes : groupes puis comptes de D42, aux numéros attribués par le système (plage système
# de login.defs(5)) et inscrits ensuite dans la configuration installée ;
# les comptes sans répertoire utile reçoivent /nonexistent (useradd(8) ; adduser(8) précise que ce
# répertoire ne doit jamais exister) ; seul app a un répertoire réel sous /var/lib (FHS).
# Retour arrière : userdel puis groupdel des seuls comptes et groupes créés ici.
# ---------------------------------------------------------------------------
deja_conforme_identifiants_comptes() {
    composer_configuration "$DEPOT/deploy/backend-admin/etc/paresia/conf.d/10-backend-admin.conf" essai
    comptes_conformes
}
etape_identifiants_comptes() { creer_comptes; }
verifier_identifiants_comptes() {
    verifier_comptes
    verifie "getent:www-data" "www-data:33" "$(getent passwd www-data | cut -d: -f1,3)"
}

# ---------------------------------------------------------------------------
# Étape appartenances : app rejoint paresia-sessions, www-data rejoint paresia-http
# (usermod -aG ajoute, il ne remplace jamais ; sautable pour www-data).
# Retour arrière : gpasswd -d.
# ---------------------------------------------------------------------------
deja_conforme_appartenances() {
    membre app paresia-sessions && { [[ $SAUTER == *" www-data "* ]] || membre www-data paresia-http; }
}
etape_appartenances() {
    if ! membre app paresia-sessions; then
        # ATTENTION : usermod modifie /etc/group ; jamais -G sans -a.
        jeu_pret
        attention usermod app
        sudo /usr/sbin/usermod -aG paresia-sessions app
    fi
    if [[ $SAUTER != *" www-data "* ]] && ! membre www-data paresia-http; then
        jeu_pret
        attention usermod www-data
        sudo /usr/sbin/usermod -aG paresia-http www-data
        noter_creation membre www-data
    fi
}
verifier_appartenances() {
    verifie "id -nG app" oui "$(membre app paresia-sessions && echo oui || echo non)"
    if [[ $SAUTER != *" www-data "* ]]; then
        verifie "id -nG www-data" oui "$(membre www-data paresia-http && echo oui || echo non)"
    fi
}

# ---------------------------------------------------------------------------
# Étape dossier_app (D44) : le dossier de app, .ssh et authorized_keys appartiennent à root
# et ne sont pas modifiables par app (StrictModes yes) ; authorized_keys reste vide.
# Le contenu d'authorized_keys n'est pas comparé (il appartient à l'administrateur).
# Retour arrière : restauration (retrait) d'authorized_keys, puis rmdir des dossiers vides.
# ---------------------------------------------------------------------------
deja_conforme_dossier_app() {
    dossier_etat "$REPERTOIRE_APP" "root:root 755" \
        && dossier_etat "$REPERTOIRE_APP/.ssh" "root:root 755" \
        && dossier_etat "$REPERTOIRE_APP/.ssh/authorized_keys" "root:root 644"
}
etape_dossier_app() {
    # ATTENTION : install écrase le fichier cible s'il existe ; l'outil consigne son état avant.
    if existe "$REPERTOIRE_APP/.ssh/authorized_keys"; then
        refuser_difference "$REPERTOIRE_APP/.ssh/authorized_keys"
    fi
    sauvegarder "$REPERTOIRE_APP/.ssh/authorized_keys"
    sudo /usr/bin/install -d -m 0755 -o root -g root "$REPERTOIRE_APP" "$REPERTOIRE_APP/.ssh"
    sudo /usr/bin/install -m 0644 -o root -g root /dev/null "$REPERTOIRE_APP/.ssh/authorized_keys"
}
verifier_dossier_app() {
    controle_attributs "$REPERTOIRE_APP" "root:root 755"
    controle_attributs "$REPERTOIRE_APP/.ssh" "root:root 755"
    controle_attributs "$REPERTOIRE_APP/.ssh/authorized_keys" "root:root 644"
    verifie "ls-A:$REPERTOIRE_APP" ".ssh" "$(sudo /usr/bin/ls -A "$REPERTOIRE_APP" | filtre_sortie)"
}

# ---------------------------------------------------------------------------
# Étape code : code sous /usr/local/lib/paresia/server (sans conf/ ni __pycache__) et
# lanceur /usr/local/bin/pollux-session, tous à root. Aucune compilation, aucun pip.
# Un code installé qui diffère n'est remplacé qu'avec CODE_REMPLACEMENT_CONFIRME=oui et
# après l'arrêt, par l'administrateur, de pollux et romulus (le script ne les arrête pas).
# Retour arrière : restauration du code et du lanceur sauvegardés (ou retrait).
# ---------------------------------------------------------------------------
LANCEUR=/usr/local/bin/pollux-session
VERSION_INSTALLEE=/usr/local/lib/paresia/VERSION
CODE_INSTALLE=/usr/local/lib/paresia/server

code_conforme() {
    existe "$CODE_INSTALLE" && existe "$LANCEUR" \
        && sudo /usr/bin/diff -qr --exclude=__pycache__ --exclude=conf "$DEPOT/server" "$CODE_INSTALLE" > /dev/null 2>&1 \
        && contenu_identique "$DEPOT/server/bin/pollux-session" "$LANCEUR" \
        && [ "$(attributs "$LANCEUR")" = "root:root 755" ] \
        && contenu_identique "$DEPOT/VERSION" "$VERSION_INSTALLEE" \
        && [ "$(attributs "$VERSION_INSTALLEE")" = "root:root 644" ]
}

deja_conforme_code() {
    if code_conforme; then
        return 0
    fi
    if existe "$CODE_INSTALLE" || existe "$LANCEUR" || existe "$VERSION_INSTALLEE"; then
        if [ "$CODE_REMPLACEMENT_CONFIRME" != oui ] && [ "$MISE_A_JOUR" != oui ]; then
            refuser_difference "$CODE_INSTALLE"
        fi
        refuser_si_active pollux.service romulus.service
    fi
    return 1
}

etape_code() {
    maj_arreter_unites
    sudo /usr/bin/install -d -m 0755 -o root -g root /usr/local/lib/paresia
    sauvegarder_arbre /usr/local/lib/paresia/server /usr/local/bin/pollux-session /usr/local/lib/paresia/VERSION
    if [ -n "$(find "$DEPOT/server" ! -type d ! -type f -print -quit)" ]; then
        arreter "$EX_CONFIG" install_err_copie_code
    fi
    if existe "$CODE_INSTALLE"; then
        # ATTENTION : rm -r retire l'ancien code seulement après la réussite de la sauvegarde ; jamais de rm -rf.
        dans_jeu "$CODE_INSTALLE" || arreter "$EX_IOERR" install_err_sauvegarde
        attention rm "$CODE_INSTALLE"
        sudo /usr/bin/rm -r "$CODE_INSTALLE"
    fi
    sudo /usr/bin/tar -C "$DEPOT" --exclude='__pycache__' --exclude='server/conf' -cf - server | sudo /usr/bin/tar -C /usr/local/lib/paresia -xf - --no-same-owner
    sudo /usr/bin/install -m 0755 -o root -g root "$DEPOT/server/bin/pollux-session" /usr/local/bin/pollux-session
    # VERSION du dépôt, à côté de server/ : sans elle les démons refusent de démarrer (code 70)
    sudo /usr/bin/install -m 0644 -o root -g root "$DEPOT/VERSION" /usr/local/lib/paresia/VERSION
    # ATTENTION : chown -R change le propriétaire de tout l'arbre indiqué (code installé seulement).
    attention chown "$CODE_INSTALLE"
    sudo /usr/bin/chown -R root:root /usr/local/lib/paresia/server
    sudo /usr/bin/find /usr/local/lib/paresia/server -type d -exec /usr/bin/chmod 0755 {} +
    sudo /usr/bin/find /usr/local/lib/paresia/server -type f -exec /usr/bin/chmod 0644 {} +
}

verifier_code() {
    local contenu
    verifie "find:/usr/local/lib/paresia:not-root-or-writable" "" \
        "$(sudo /usr/bin/find /usr/local/lib/paresia ! -user root -o -perm /022 | filtre_sortie)"
    controle_attributs "$LANCEUR" "root:root 755"
    controle_attributs "$VERSION_INSTALLEE" "root:root 644"
    controle_attributs "$CODE_INSTALLE" "root:root 755"
    contenu=$(sudo /usr/bin/ls "$CODE_INSTALLE" | filtre_sortie)
    verifie "conf-in:$CODE_INSTALLE" non "$([[ $'\n'$contenu$'\n' == *$'\nconf\n'* ]] && echo oui || echo non)"
}

# ---------------------------------------------------------------------------
# Étape configuration (partagée avec l'installation de bunkerd) : /etc/paresia/paresia.conf et
# conf.d/10-backend-admin.conf (livrée, avec les numéros relevés sur le système à la place des exemples), à root, non inscriptibles. Un fichier existant différent est
# refusé sans CODE_REMPLACEMENT_CONFIRME=oui ; sinon il est sauvegardé avant d'être remplacé.
# Retour arrière : restauration des deux fichiers (ou retrait).
# ---------------------------------------------------------------------------
CONF_BASE=/etc/paresia/paresia.conf
CONF_ADMIN=/etc/paresia/conf.d/10-backend-admin.conf
# Déclarations des services que Romulus aiguille : sans elles, les sections [romulus.<service>] de
# 10-backend-admin.conf sont inconnues et Romulus sort en code 78.
DECLARATIONS_DEPOT=deploy/backend-admin/usr/local/lib/paresia/romulus/services
DECLARATIONS_DOSSIER=/usr/local/lib/paresia/romulus/services
DECLARATIONS_NOMS=()

# lire_declarations : noms (sans extension) des déclarations livrées dans le clone ; au moins une.
lire_declarations() {
    local fichier
    DECLARATIONS_NOMS=()
    while IFS= read -r -d '' fichier; do
        DECLARATIONS_NOMS+=("${fichier%.toml}")
    done < <(find "$DEPOT/$DECLARATIONS_DEPOT" -maxdepth 1 -type f -name '*.toml' -printf '%f\0' | sort -z)
    if [ "${#DECLARATIONS_NOMS[@]}" -eq 0 ]; then
        arreter "$EX_DATAERR" install_err_depot
    fi
}
CONF_COMPOSEE=$TRAVAIL/10-backend-admin.conf.composee    # livrée, numéros du système inscrits

deja_conforme_configuration() {
    local conforme=0 nom livree
    lire_declarations
    charger_empreintes
    dossier_etat /usr/local/lib/paresia/romulus "root:root 755" || conforme=1
    dossier_etat "$DECLARATIONS_DOSSIER" "root:root 755" || conforme=1
    for nom in "${DECLARATIONS_NOMS[@]}"; do
        ! a_poser "$DEPOT/$DECLARATIONS_DEPOT/$nom.toml" "$DECLARATIONS_DOSSIER/$nom.toml" 0644 || conforme=1
    done
    dossier_etat /etc/paresia "root:root 755" || conforme=1
    dossier_etat /etc/paresia/conf.d "root:root 755" || conforme=1
    if [ "$MISE_A_JOUR" = oui ]; then
        # fichiers de l'administrateur : jamais écrasés (empreintes enregistrées, version livrée à côté)
        livree=$(empreinte_de "$DEPOT/server/conf/paresia.conf")
        conf_conforme "$CONF_BASE" "$livree" || conforme=1
        composer_configuration "$DEPOT/deploy/backend-admin/etc/paresia/conf.d/10-backend-admin.conf"
        livree=$(printf '%s\n' "$COMPOSEE" | empreinte_texte)
        conf_conforme "$CONF_ADMIN" "$livree" || conforme=1
    else
        ! a_poser "$DEPOT/server/conf/paresia.conf" "$CONF_BASE" 0644 || conforme=1
        composer_configuration "$DEPOT/deploy/backend-admin/etc/paresia/conf.d/10-backend-admin.conf"
        ! a_poser_composee "$CONF_ADMIN" 0644 || conforme=1
    fi
    return "$conforme"
}

etape_configuration() {
    local nom livree
    maj_arreter_unites
    lire_declarations
    sudo /usr/bin/install -d -m 0755 -o root -g root /etc/paresia /etc/paresia/conf.d
    sudo /usr/bin/install -d -m 0755 -o root -g root /usr/local/lib/paresia /usr/local/lib/paresia/romulus "$DECLARATIONS_DOSSIER"
    for nom in "${DECLARATIONS_NOMS[@]}"; do
        if a_poser "$DEPOT/$DECLARATIONS_DEPOT/$nom.toml" "$DECLARATIONS_DOSSIER/$nom.toml" 0644; then
            poser_fichier "$DEPOT/$DECLARATIONS_DEPOT/$nom.toml" "$DECLARATIONS_DOSSIER/$nom.toml" 0644
        fi
    done
    if [ "$MISE_A_JOUR" = oui ]; then
        conf_appliquer "$CONF_BASE" "$DEPOT/server/conf/paresia.conf"
        composer_configuration "$DEPOT/deploy/backend-admin/etc/paresia/conf.d/10-backend-admin.conf"
        ecrire_composee
        conf_appliquer "$CONF_ADMIN" "$CONF_COMPOSEE"
    else
        if a_poser "$DEPOT/server/conf/paresia.conf" "$CONF_BASE" 0644; then
            poser_fichier "$DEPOT/server/conf/paresia.conf" "$CONF_BASE" 0644
        fi
        EMPREINTES[$CONF_BASE]=$(empreinte_de "$DEPOT/server/conf/paresia.conf")
        composer_configuration "$DEPOT/deploy/backend-admin/etc/paresia/conf.d/10-backend-admin.conf"
        if a_poser_composee "$CONF_ADMIN" 0644; then
            poser_fichier "$CONF_COMPOSEE" "$CONF_ADMIN" 0644
        fi
        livree=$(printf '%s\n' "$COMPOSEE" | empreinte_texte)
        EMPREINTES[$CONF_ADMIN]=$livree
    fi
    ecrire_empreintes
}

verifier_configuration() {
    local nom
    lire_declarations
    controle_attributs /usr/local/lib/paresia/romulus "root:root 755"
    controle_attributs "$DECLARATIONS_DOSSIER" "root:root 755"
    for nom in "${DECLARATIONS_NOMS[@]}"; do
        controle_attributs "$DECLARATIONS_DOSSIER/$nom.toml" "root:root 644"
    done
    controle_attributs /etc/paresia "root:root 755"
    controle_attributs /etc/paresia/conf.d "root:root 755"
    controle_attributs "$CONF_BASE" "root:root 644"
    controle_attributs "$CONF_ADMIN" "root:root 644"
}

# ---------------------------------------------------------------------------
# Étape web : pages de l'interface d'administration (admin/web/) et des greffons yang, posées dans
# le dossier de Paresia /usr/local/share/paresia/web/ (greffons sous greffons/<nom>/), puis index
# greffons/index.json généré et vérifié par python3 -m server.romulus.pages. Tout appartient à root,
# non inscriptible par un autre compte. Un dossier installé qui diffère n'est remplacé qu'avec
# CODE_REMPLACEMENT_CONFIRME=oui, après sauvegarde. Le script ne touche à aucun serveur web : il ne
# l'installe pas, n'écrit aucune configuration de serveur web et ne recharge aucun service ; le
# dossier posé est celui que l'administrateur du serveur web fait servir (documentation).
# Retour arrière : restauration du dossier sauvegardé (ou retrait).
# ---------------------------------------------------------------------------
WEB_DOSSIER=/usr/local/share/paresia/web
WEB_SOURCE=admin/web
WEB_GREFFONS_DEPOT=deploy/backend-admin/usr/local/share/paresia/web/greffons
WEB_NOMS=()

# lire_web : noms des dossiers de greffons du clone (forme contrôlée) ; WEB_NOMS.
lire_web() {
    local nom
    WEB_NOMS=()
    while IFS= read -r -d '' nom; do
        [[ $nom =~ ^[a-z][a-z0-9-]{0,31}$ ]] || arreter "$EX_DATAERR" install_err_depot
        WEB_NOMS+=("$nom")
    done < <(find "$DEPOT/$WEB_GREFFONS_DEPOT" -mindepth 1 -maxdepth 1 -type d -printf '%f\0' | sort -z)
}

# web_index OPTION : --ecrire ou --verifier ; sortie (codes de diagnostic seulement) sur la sortie standard.
web_index() {
    sudo /usr/bin/env PYTHONPATH=/usr/local/lib/paresia /usr/bin/python3 -P -s -B -m server.romulus.pages "$1" "$WEB_DOSSIER/greffons" 2>&1
}

web_conforme() {
    local nom installes
    existe "$WEB_DOSSIER" || return 1
    sudo /usr/bin/diff -qr --exclude=greffons -- "$DEPOT/$WEB_SOURCE" "$WEB_DOSSIER" > /dev/null 2>&1 || return 1
    installes=$(sudo /usr/bin/find "$WEB_DOSSIER/greffons" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' 2> /dev/null | sort | filtre_sortie) || return 1
    [ "$installes" = "$(printf '%s\n' "${WEB_NOMS[@]}" | sort | sed '/^$/d')" ] || return 1
    for nom in "${WEB_NOMS[@]}"; do
        sudo /usr/bin/diff -qr -- "$DEPOT/$WEB_GREFFONS_DEPOT/$nom" "$WEB_DOSSIER/greffons/$nom" > /dev/null 2>&1 || return 1
    done
    web_index --verifier > /dev/null 2>&1 || return 1
    [ -z "$(sudo /usr/bin/find "$WEB_DOSSIER" ! -user root -o -perm /022 | filtre_sortie)" ]
}

deja_conforme_web() {
    lire_web
    if web_conforme; then
        return 0
    fi
    if existe "$WEB_DOSSIER" && [ "$CODE_REMPLACEMENT_CONFIRME" != oui ]; then
        refuser_difference "$WEB_DOSSIER"
    fi
    return 1
}

etape_web() {
    local nom
    lire_web
    if [ -n "$(find "$DEPOT/$WEB_SOURCE" "$DEPOT/$WEB_GREFFONS_DEPOT" ! -type d ! -type f -print -quit)" ]; then
        arreter "$EX_CONFIG" install_err_copie_web
    fi
    sauvegarder_arbre "$WEB_DOSSIER"
    if existe "$WEB_DOSSIER"; then
        # ATTENTION : rm -r retire l'ancien dossier des pages seulement après la réussite de la sauvegarde ; jamais de rm -rf.
        dans_jeu "$WEB_DOSSIER" || arreter "$EX_IOERR" install_err_sauvegarde
        attention rm "$WEB_DOSSIER"
        sudo /usr/bin/rm -r "$WEB_DOSSIER"
    fi
    sudo /usr/bin/install -d -m 0755 -o root -g root /usr/local/share/paresia
    sudo /usr/bin/tar -C "$DEPOT/admin" -cf - web | sudo /usr/bin/tar -C /usr/local/share/paresia -xf - --no-same-owner
    sudo /usr/bin/install -d -m 0755 -o root -g root "$WEB_DOSSIER/greffons"
    for nom in "${WEB_NOMS[@]}"; do
        sudo /usr/bin/tar -C "$DEPOT/$WEB_GREFFONS_DEPOT" -cf - "$nom" | sudo /usr/bin/tar -C "$WEB_DOSSIER/greffons" -xf - --no-same-owner
    done
    # ATTENTION : chown -R change le propriétaire de tout le dossier des pages (copie installée seulement).
    attention chown "$WEB_DOSSIER"
    sudo /usr/bin/chown -R root:root "$WEB_DOSSIER"
    sudo /usr/bin/find "$WEB_DOSSIER" -type d -exec /usr/bin/chmod 0755 {} +
    sudo /usr/bin/find "$WEB_DOSSIER" -type f -exec /usr/bin/chmod 0644 {} +
    web_ecrire_index
    msg_out install_web_dossier "dossier=$WEB_DOSSIER" "nombre=${#WEB_NOMS[@]}"
}

# ATTENTION : rm -f retire le seul fichier d'index (jamais un dossier) ; l'index refusé ne reste pas en place.
web_retirer_index() {
    attention rm "$WEB_DOSSIER/greffons/index.json"
    sudo /usr/bin/rm -f -- "$WEB_DOSSIER/greffons/index.json"
}

# web_ecrire_index : génère l'index ; en échec, aucun index n'est laissé (échec fermé).
web_ecrire_index() {
    local sortie
    if ! sortie=$(web_index --ecrire); then
        web_retirer_index
        arreter "$EX_CONFIG" install_err_web_index "detail=$(printf '%s' "$sortie" | filtre_sortie)"
    fi
}

verifier_web() {
    local sortie
    controle_attributs "$WEB_DOSSIER" "root:root 755"
    controle_attributs "$WEB_DOSSIER/greffons" "root:root 755"
    controle_attributs "$WEB_DOSSIER/greffons/index.json" "root:root 644"
    if ! sortie=$(web_index --verifier); then
        web_retirer_index
        arreter "$EX_CONFIG" install_err_web_index "detail=$(printf '%s' "$sortie" | filtre_sortie)"
    fi
    verifie "find:$WEB_DOSSIER:not-root-or-writable" "" \
        "$(sudo /usr/bin/find "$WEB_DOSSIER" ! -user root -o -perm /022 | filtre_sortie)"
}

# ---------------------------------------------------------------------------
# Étape sshd_app : 50-paresia-app.conf (StrictModes yes et PermitUserEnvironment no hors du bloc,
# puis Match User app). sshd -t avant tout reload ; reload ssh (jamais restart) seulement avec
# SESSION_SECOURS=oui (deuxième session ouverte et testée : le script ne peut pas le vérifier).
# Si la configuration ne passe pas sshd -t, le fichier posé est restauré aussitôt.
# Retour arrière : restauration du fichier, sshd -t, reload ssh.
# AcceptEnv : un bloc Match ne peut pas vider la liste posée par la configuration principale ; le client
# peut donc transmettre LANG et LC_*, sans effet car le lanceur pollux-session vide l'environnement (env -i).
# StrictModes yes et PermitUserEnvironment no sont posés hors du bloc Match (sshd_config(5) ne les permet pas dedans).
# ---------------------------------------------------------------------------
SSHD_APP=/etc/ssh/sshd_config.d/50-paresia-app.conf
SSHD_SOURCE_APP=deploy/backend-admin/etc/ssh/sshd_config.d/50-paresia-app.conf

deja_conforme_sshd_app() {
    ! a_poser "$DEPOT/$SSHD_SOURCE_APP" "$SSHD_APP" 0644
}

controle_sshd_app() {
    local effectif ligne
    effectif=$(sudo /usr/sbin/sshd -T -C user=app,host=backend-admin.example.org,addr=192.0.2.10 \
        | grep -i -E '^(exposeauthinfo|clientaliveinterval|clientalivecountmax|strictmodes|permituserenvironment|passwordauthentication|authenticationmethods) ' | filtre_sortie)
    for ligne in "exposeauthinfo yes" "clientaliveinterval 15" "clientalivecountmax 3" "strictmodes yes" \
        "permituserenvironment no" "passwordauthentication no" "authenticationmethods publickey"; do
        verifie "sshd-T:app:${ligne% *}" "$ligne" "$(grep -x -i -F "$ligne" <<< "$effectif" || true)"
    done
    effectif=$(sudo /usr/sbin/sshd -T -C user=nobody,host=backend-admin.example.org,addr=192.0.2.10 \
        | grep -i -E '^exposeauthinfo ' | filtre_sortie)
    verifie "sshd-T:nobody:exposeauthinfo" "exposeauthinfo no" "$effectif"
}

etape_sshd_app() {
    exiger_session_secours
    if ! sudo /usr/bin/grep -q -i -E '^[[:space:]]*Include[[:space:]]+/etc/ssh/sshd_config\.d/\*\.conf' /etc/ssh/sshd_config; then
        manque "Include sshd_config.d"
    fi
    poser_fichier "$DEPOT/$SSHD_SOURCE_APP" "$SSHD_APP" 0644
    sshd_t_ou_restaurer "$SSHD_APP"
    controle_sshd_app
    recharger_ssh
}
verifier_sshd_app() { controle_sshd_app; }

# ---------------------------------------------------------------------------
# Étape unites : unités pollux.service et romulus.service (ConfigurationDirectory=paresia::ro
# exige systemd 257 ou plus : avant, ::ro est retiré des copies installées). Une unité active
# dont le fichier diffère est refusée : le script ne redémarre jamais ; arrêt à faire par vous.
# Retour arrière : restauration des unités, daemon-reload.
# ---------------------------------------------------------------------------
SRC_UNITES=deploy/backend-admin/etc/systemd/system

deja_conforme_unites() {
    local u conforme=0
    for u in "${ADMIN_UNITES[@]}"; do
        ! a_poser "$DEPOT/$SRC_UNITES/$u.service" "/etc/systemd/system/$u.service" 0644 || conforme=1
    done
    return "$conforme"
}

etape_unites() {
    local u
    maj_arreter_unites
    for u in "${ADMIN_UNITES[@]}"; do
        if a_poser "$DEPOT/$SRC_UNITES/$u.service" "/etc/systemd/system/$u.service" 0644; then
            if existe "/etc/systemd/system/$u.service"; then
                refuser_si_active "$u.service"
            fi
            poser_fichier "$DEPOT/$SRC_UNITES/$u.service" "/etc/systemd/system/$u.service" 0644
        fi
    done
    sudo /usr/bin/systemctl daemon-reload
}

verifier_unites() {
    local sortie
    sortie=$(sudo /usr/bin/systemd-analyze verify pollux.service romulus.service 2>&1 | grep -E 'pollux\.service|romulus\.service' | filtre_sortie || true)
    verifie "systemd-analyze:pollux-romulus" "" "$sortie"
    verifie "StateDirectory:pollux" "StateDirectory=paresia-pollux" "$(sudo /usr/bin/systemctl show -p StateDirectory pollux.service | filtre_sortie)"
    verifie "StateDirectory:romulus" "StateDirectory=paresia-romulus" "$(sudo /usr/bin/systemctl show -p StateDirectory romulus.service | filtre_sortie)"
}

# ---------------------------------------------------------------------------
# Étape demarrage : start de Romulus puis de Pollux (jamais restart, jamais enable ici), puis
# sockets, propriétaires et droits. Un redémarrage ferme les sessions de présence (D9).
# Retour arrière : arrêt des unités (ferme toutes les sessions).
# ---------------------------------------------------------------------------
deja_conforme_demarrage() {
    local unite
    if [ "$MISE_A_JOUR" = oui ]; then
        # les unités actives avant doivent l'être ; une unité inactive avant reste inactive
        for unite in "${MAJ_ACTIVES[@]}"; do
            if ! unite_active "$unite"; then
                return 1
            fi
        done
        return 0
    fi
    unite_active romulus.service && unite_active pollux.service
}

etape_demarrage() {
    # ATTENTION : démarrer Pollux ou Romulus ; un arrêt ou un redémarrage ferme toutes les sessions de présence (D9).
    # Sous mise à jour, seules les unités actives avant sont reprises, dans l'ordre inverse de l'arrêt.
    if unite_visee romulus.service && ! unite_active romulus.service; then
        maj_avant_demarrage romulus.service
        attention "systemctl start" romulus.service
        sudo /usr/bin/systemctl start romulus.service
        maj_apres_demarrage romulus.service
    fi
    if unite_visee pollux.service && ! unite_active pollux.service; then
        maj_avant_demarrage pollux.service
        attention "systemctl start" pollux.service
        sudo /usr/bin/systemctl start pollux.service
        maj_apres_demarrage pollux.service
    fi
}

verifier_demarrage() {
    local ligne attendus=0
    local -a controles=("/etc/paresia root:root 755")
    if unite_visee romulus.service; then
        verifie "romulus.service" active "$(sudo /usr/bin/systemctl is-active romulus.service | filtre_sortie || true)"
        attendus=$((attendus + 2))
        controles+=("/run/paresia-romulus paresia-romulus:paresia-romulus 711" "/var/lib/paresia-romulus paresia-romulus:paresia-romulus 711"
            "/run/paresia-romulus/romulus.sock paresia-romulus:paresia-liaison 660"
            "/run/paresia-romulus/romulus-http.sock paresia-romulus:paresia-http 660")
    fi
    if unite_visee pollux.service; then
        verifie "pollux.service" active "$(sudo /usr/bin/systemctl is-active pollux.service | filtre_sortie || true)"
        attendus=$((attendus + 2))
        controles+=("/run/paresia-pollux paresia-pollux:paresia-pollux 711" "/var/lib/paresia-pollux paresia-pollux:paresia-pollux 711"
            "/run/paresia-pollux/pollux.sock paresia-pollux:paresia-sessions 660"
            "/run/paresia-pollux/pollux-relay.sock paresia-pollux:paresia-liaison 660")
    fi
    releve_info "status" "$(sudo /usr/bin/systemctl status romulus.service pollux.service --no-pager | filtre_sortie || true)"
    if unite_visee romulus.service; then
        releve_info "journal romulus" "$(sudo /usr/bin/journalctl -u romulus.service -n 30 --no-pager | filtre_sortie || true)"
    fi
    if unite_visee pollux.service; then
        releve_info "journal pollux" "$(sudo /usr/bin/journalctl -u pollux.service -n 30 --no-pager | filtre_sortie || true)"
    fi
    verifie "ss-xl:pollux-romulus" "$attendus" "$(ss -xl | grep -c -E '/run/paresia-(pollux|romulus)/' || true)"
    for ligne in "${controles[@]}"; do
        controle_attributs "${ligne%% *}" "${ligne#* }"
    done
    if unite_visee pollux.service; then
        verifie "nsenter:pollux:authorized_keys" "root:root 644" "$(attributs_vus_par_pollux)"
    fi
}

# attributs_vus_par_pollux : propriétaire, groupe et mode (forme « root:root 644 ») de authorized_keys dans l'espace de noms de Pollux.
attributs_vus_par_pollux() {
    local pid droits proprietaire groupe
    pid=$(systemctl show -p MainPID --value pollux.service)
    read -r droits _ proprietaire groupe _ < <(sudo /usr/bin/nsenter -t "$pid" -m -- /usr/bin/ls -l /var/lib/paresia-app/.ssh/authorized_keys | filtre_sortie)
    [ "$droits" = "-rw-r--r--" ] && printf '%s:%s 644\n' "$proprietaire" "$groupe" || printf '%s:%s %s\n' "${proprietaire:-?}" "${groupe:-?}" "${droits:-?}"
}

# ---------------------------------------------------------------------------
# Étape refus : un compte tiers ne peut pas ouvrir les sockets ; www-data n'obtient pas
# d'action sans jeton. Lecture seule.
# ---------------------------------------------------------------------------
refus_connexion() {          # COMPTE SOCKET : doit se terminer par PermissionError
    local sortie
    if sortie=$(sudo /usr/sbin/runuser -u "$1" -- /usr/bin/python3 -I -c "import socket; s=socket.socket(socket.AF_UNIX); s.connect('$2')" 2>&1); then
        ecart "connect:$1:$2" "PermissionError" "accepted"
    fi
    case $sortie in
        *PermissionError*) hook alpha_verifie "refused:$1:$2" PermissionError ;;
        *) ecart "refused:$1:$2" PermissionError "$(printf '%s' "$sortie" | tail -n 1 | filtre_sortie)" ;;
    esac
}

requete_http() {             # METHODE : statut et corps de la requête de www-data
    sudo /usr/sbin/runuser -u www-data -- /usr/bin/curl -s -w ' %{http_code}\n' --unix-socket /run/paresia-romulus/romulus-http.sock -X "$1" http://localhost/api/admin/bunker/identity/list | filtre_sortie
}

deja_conforme_refus() { return 1; }
etape_refus() { :; }
verifier_refus() {
    local reponse
    if unite_visee pollux.service; then
        refus_connexion nobody /run/paresia-pollux/pollux.sock
    fi
    if ! unite_visee romulus.service; then
        return 0
    fi
    refus_connexion nobody /run/paresia-romulus/romulus-http.sock
    if [[ $SAUTER == *" www-data "* ]]; then
        return 0
    fi
    reponse=$(requete_http POST)
    case $reponse in
        *token_missing*' 403') hook alpha_verifie "POST:no-token" "token_missing 403" ;;
        *) ecart "POST:no-token" "token_missing 403" "$reponse" ;;
    esac
    verifie "GET:method" " 405" " $(requete_http GET | awk 'END {print $NF}')"
}

# ---------------------------------------------------------------------------
# Partie « tunnel » de backend-admin : relevés, clé, client, known_hosts, unité, sockets.
# L'ordre entre machines est admin (1re passe) > relais > admin (2e passe, avec
# ADRESSE_RELAIS et EMPREINTE_HOTE_RELAIS) ; les étapes déjà conformes sont reconnues.
# ---------------------------------------------------------------------------
TUNNEL_DIR=/etc/paresia/tunnel

# tunnel_releves : relevés avant (lecture seule).
deja_conforme_tunnel_releves() { return 1; }
etape_tunnel_releves() {
    releve_info "stat:/etc/paresia" "$(attributs /etc/paresia)"
    releve_info "paresia-tunnel" "$(getent passwd paresia-tunnel | filtre_sortie || true)"
}
verifier_tunnel_releves() {
    controle_attributs /etc/paresia "root:root 755"
    releve_identifiants
    verifie "getent:paresia-tunnel:uid" "${IDENT[compte:paresia-tunnel]}" "$(getent passwd paresia-tunnel | cut -d: -f3)"
}

# tunnel_cle : paire de clés générée sur place ; la clé privée (paresia-tunnel, 0400) n'est jamais
# copiée, lue, affichée ni journalisée ; seules la clé publique et son empreinte sortent.
deja_conforme_tunnel_cle() {
    local privee pub
    if ! existe "$TUNNEL_DIR/id_ed25519" && ! existe "$TUNNEL_DIR/id_ed25519.pub"; then
        return 1
    fi
    privee=$(attributs "$TUNNEL_DIR/id_ed25519")
    pub=$(attributs "$TUNNEL_DIR/id_ed25519.pub")
    if [ "$privee" != "paresia-tunnel:paresia-tunnel 400" ] || [ "$pub" != "root:root 644" ]; then
        ecart "$TUNNEL_DIR/id_ed25519" "paresia-tunnel:paresia-tunnel 400 / root:root 644" "$privee / $pub"
    fi
    return 0
}

etape_tunnel_cle() {
    sauvegarder "$TUNNEL_DIR/id_ed25519" "$TUNNEL_DIR/id_ed25519.pub"
    sudo /usr/bin/install -d -o root -g root -m 0755 "$TUNNEL_DIR" "$TUNNEL_DIR/ssh_config.d"
    # ATTENTION : ssh-keygen écrit une clé privée ; elle ne doit être ni copiée, ni affichée, ni envoyée.
    attention ssh-keygen "$TUNNEL_DIR/id_ed25519"
    sudo /usr/bin/ssh-keygen -q -t ed25519 -N '' -C paresia-tunnel -f /etc/paresia/tunnel/id_ed25519
    sudo /usr/bin/chown paresia-tunnel:paresia-tunnel /etc/paresia/tunnel/id_ed25519
    sudo /usr/bin/chmod 0400 /etc/paresia/tunnel/id_ed25519
    sudo /usr/bin/chown root:root /etc/paresia/tunnel/id_ed25519.pub
    sudo /usr/bin/chmod 0644 /etc/paresia/tunnel/id_ed25519.pub
}

verifier_tunnel_cle() {
    local publique empreinte
    controle_attributs "$TUNNEL_DIR" "root:root 755"
    controle_attributs "$TUNNEL_DIR/id_ed25519" "paresia-tunnel:paresia-tunnel 400"
    controle_attributs "$TUNNEL_DIR/id_ed25519.pub" "root:root 644"
    publique=$(sudo /usr/bin/cat -- "$TUNNEL_DIR/id_ed25519.pub" | filtre_sortie)
    empreinte=$(sudo /usr/bin/ssh-keygen -lf "$TUNNEL_DIR/id_ed25519.pub" | awk '{print $2}' | filtre_sortie)
    msg_out install_cle_publique "cle=$publique"
    msg_out install_empreinte_cle "empreinte=$empreinte"
}

tunnel_client_conforme() {
    existe "$TUNNEL_DIR/ssh_config" && contenu_identique "$DEPOT/deploy/backend-admin/etc/paresia/tunnel/ssh_config" "$TUNNEL_DIR/ssh_config" \
        && existe "$TUNNEL_DIR/ssh_config.d/10-relais.conf" \
        && sed "s/^    HostName 192\.0\.2\.200\$/    HostName $ADRESSE_RELAIS/" -- "$DEPOT/deploy/backend-admin/etc/paresia/tunnel/ssh_config.d/10-relais.conf" \
        | sudo /usr/bin/diff -q - "$TUNNEL_DIR/ssh_config.d/10-relais.conf" > /dev/null 2>&1
}

# tunnel_client : ssh_config (couche commune) et ssh_config.d/10-relais.conf (adresse de backend-relais).
deja_conforme_tunnel_client() {
    if tunnel_client_conforme; then
        return 0
    fi
    if existe "$TUNNEL_DIR/ssh_config" || existe "$TUNNEL_DIR/ssh_config.d/10-relais.conf"; then
        if [ "$CODE_REMPLACEMENT_CONFIRME" != oui ] && [ "$MISE_A_JOUR" != oui ]; then
            refuser_difference "$TUNNEL_DIR/ssh_config"
        fi
    fi
    return 1
}

etape_tunnel_client() {
    maj_arreter_unites
    sauvegarder "$TUNNEL_DIR/ssh_config" "$TUNNEL_DIR/ssh_config.d/10-relais.conf"
    sudo /usr/bin/install -m 0644 -o root -g root "$DEPOT/deploy/backend-admin/etc/paresia/tunnel/ssh_config" /etc/paresia/tunnel/ssh_config
    sudo /usr/bin/install -m 0644 -o root -g root "$DEPOT/deploy/backend-admin/etc/paresia/tunnel/ssh_config.d/10-relais.conf" /etc/paresia/tunnel/ssh_config.d/10-relais.conf
    # ATTENTION : sed -i modifie la copie installée (adresse de backend-relais), pas celle du dépôt.
    sudo /usr/bin/sed -i "s/^    HostName 192\.0\.2\.200\$/    HostName $ADRESSE_RELAIS/" /etc/paresia/tunnel/ssh_config.d/10-relais.conf
}

verifier_tunnel_client() {
    local effectif ligne
    effectif=$(sudo /usr/bin/ssh -G -F /etc/paresia/tunnel/ssh_config paresia-relais \
        | grep -i -E '^(hostname|user|port|stricthostkeychecking|exitonforwardfailure|streamlocalbindunlink|streamlocalbindmask|serveraliveinterval|identitiesonly|batchmode|localforward) ' | filtre_sortie)
    for ligne in "hostname $ADRESSE_RELAIS" "user tunnel" "stricthostkeychecking true" "exitonforwardfailure yes" \
        "streamlocalbindunlink yes" "streamlocalbindmask 0111" "serveraliveinterval 15" "identitiesonly yes" "batchmode yes"; do
        verifie "ssh-G:${ligne% *}" "$ligne" "$(grep -x -i -F "$ligne" <<< "$effectif" || true)"
    done
    verifie "ssh-G:localforward" 2 "$(grep -c -i '^localforward ' <<< "$effectif" || true)"
}

# tunnel_known_hosts : jamais de confiance au premier usage. ssh-keyscan seul ne prouve rien :
# l'empreinte obtenue est comparée à EMPREINTE_HOTE_RELAIS, lue sur backend-relais (second canal).
known_hosts_empreinte() {    # FICHIER -> empreinte
    sudo /usr/bin/ssh-keygen -lf "$1" | awk 'NR==1 {print $2}' | filtre_sortie
}

deja_conforme_tunnel_known_hosts() {
    local actuelle
    if ! existe "$TUNNEL_DIR/known_hosts"; then
        return 1
    fi
    actuelle=$(known_hosts_empreinte "$TUNNEL_DIR/known_hosts")
    verifie "known_hosts:fingerprint" "$EMPREINTE_HOTE_RELAIS" "$actuelle"
    controle_attributs "$TUNNEL_DIR/known_hosts" "root:root 644"
}

etape_tunnel_known_hosts() {
    # ATTENTION : rm retire le fichier provisoire known_hosts.nouveau (sous /run/paresia-installation) ; rien d'autre.
    local obtenue lignes
    # Les lignes de commentaire (« # hôte:22 SSH-2.0-… », écrites par certaines versions sur la sortie standard) sont retirées.
    sudo /usr/bin/ssh-keyscan -T 5 -t ed25519 "$ADRESSE_RELAIS" | { grep -v '^#' || true; } | sudo /usr/bin/tee /run/paresia-installation/known_hosts.nouveau > /dev/null
    sudo /usr/bin/test -s /run/paresia-installation/known_hosts.nouveau
    lignes=$(sudo /usr/bin/grep -c '' /run/paresia-installation/known_hosts.nouveau || true)
    if [ "$lignes" != 1 ]; then
        sudo /usr/bin/rm /run/paresia-installation/known_hosts.nouveau
        ecart "known_hosts.nouveau:lignes" 1 "$lignes"
    fi
    obtenue=$(known_hosts_empreinte /run/paresia-installation/known_hosts.nouveau)
    if [ "$obtenue" != "$EMPREINTE_HOTE_RELAIS" ]; then
        sudo /usr/bin/rm /run/paresia-installation/known_hosts.nouveau
        arreter "$EX_CONFIG" install_err_empreinte "attendu=$EMPREINTE_HOTE_RELAIS" "releve=$obtenue"
    fi
    sauvegarder "$TUNNEL_DIR/known_hosts"
    # ATTENTION : install écrase un known_hosts existant ; l'outil le sauvegarde d'abord.
    sudo /usr/bin/install -m 0644 -o root -g root /run/paresia-installation/known_hosts.nouveau /etc/paresia/tunnel/known_hosts
    sudo /usr/bin/rm /run/paresia-installation/known_hosts.nouveau
}

verifier_tunnel_known_hosts() {
    controle_attributs "$TUNNEL_DIR/known_hosts" "root:root 644"
}

# tunnel_unite : dossiers des sockets par tmpfiles.d(5) (parent root:root 0711, romulus paresia-tunnel:paresia-romulus
# 0710, pollux paresia-tunnel:paresia-pollux 0710), puis paresia-tunnel.service vérifiée et démarrée (start, jamais
# enable, activation propre ancienne retirée sans arrêt). Les comptes et groupes existent déjà (étape identifiants_comptes). Une unité active dont un fichier
# changerait est refusée : l'arrêt du tunnel coupe Pollux et Romulus de leurs jumeaux (D8) et reste à faire par vous.
TMPFILES_SOURCE=deploy/backend-admin/etc/tmpfiles.d/paresia-tunnel.conf
TMPFILES_TUNNEL=/etc/tmpfiles.d/paresia-tunnel.conf

deja_conforme_tunnel_unite() {
    local conforme=0
    ! a_poser "$DEPOT/$TMPFILES_SOURCE" "$TMPFILES_TUNNEL" 0644 || conforme=1
    ! a_poser "$DEPOT/deploy/backend-admin/etc/systemd/system/paresia-tunnel.service" /etc/systemd/system/paresia-tunnel.service 0644 || conforme=1
    ! unite_visee paresia-tunnel.service || unite_active paresia-tunnel.service || conforme=1
    [ "$(sudo /usr/bin/systemctl is-enabled paresia-tunnel.service || true)" != enabled ] || conforme=1
    return "$conforme"
}

etape_tunnel_unite() {
    # ATTENTION : poser tmpfiles.d et l'unité écrase les anciennes (sauvegardées) ; systemd-tmpfiles --create ajuste
    # les modes et propriétaires des dossiers ; le tunnel est démarré (start) ; jamais de restart.
    local source=$DEPOT/deploy/backend-admin/etc/systemd/system/paresia-tunnel.service
    maj_arreter_unites
    if a_poser "$DEPOT/$TMPFILES_SOURCE" "$TMPFILES_TUNNEL" 0644 || a_poser "$source" /etc/systemd/system/paresia-tunnel.service 0644; then
        refuser_si_active paresia-tunnel.service
    fi
    if a_poser "$DEPOT/$TMPFILES_SOURCE" "$TMPFILES_TUNNEL" 0644; then
        sauvegarder "$TMPFILES_TUNNEL"
        sudo /usr/bin/install -D -m 0644 -o root -g root "$DEPOT/deploy/backend-admin/etc/tmpfiles.d/paresia-tunnel.conf" /etc/tmpfiles.d/paresia-tunnel.conf
    fi
    sudo /usr/bin/systemd-tmpfiles --create /etc/tmpfiles.d/paresia-tunnel.conf
    if a_poser "$source" /etc/systemd/system/paresia-tunnel.service 0644; then
        poser_fichier "$source" /etc/systemd/system/paresia-tunnel.service 0644
    fi
    sudo /usr/bin/systemctl daemon-reload
    if [ "$(sudo /usr/bin/systemctl is-enabled paresia-tunnel.service || true)" = enabled ]; then
        attention "systemctl disable" paresia-tunnel.service
        sudo /usr/bin/systemctl disable paresia-tunnel.service
    fi
    verifie "systemd-analyze:paresia-tunnel" "" "$(sudo /usr/bin/systemd-analyze verify paresia-tunnel.service 2>&1 | grep -E 'paresia-tunnel\.service' | filtre_sortie || true)"
    if unite_visee paresia-tunnel.service && ! unite_active paresia-tunnel.service; then
        maj_avant_demarrage paresia-tunnel.service
        attention "systemctl start" paresia-tunnel.service
        sudo /usr/bin/systemctl start paresia-tunnel.service
        maj_apres_demarrage paresia-tunnel.service
    fi
}

verifier_tunnel_unite() {
    local ligne active=non
    if [ "$(sudo /usr/bin/systemctl is-enabled paresia-tunnel.service || true)" = enabled ]; then
        active=oui
    fi
    verifie "paresia-tunnel:non-active" non "$active"
    if ! unite_visee paresia-tunnel.service; then
        controle_attributs "$TMPFILES_TUNNEL" "root:root 644"
        return 0
    fi
    verifie "paresia-tunnel.service" active "$(sudo /usr/bin/systemctl is-active paresia-tunnel.service | filtre_sortie || true)"
    releve_info "status" "$(sudo /usr/bin/systemctl status paresia-tunnel.service --no-pager | filtre_sortie || true)"
    releve_info "journal" "$(sudo /usr/bin/journalctl -u paresia-tunnel.service -n 30 --no-pager | filtre_sortie || true)"
    verifie "ss-xl:paresia-tunnel" 2 "$(ss -xl | grep -c paresia-tunnel || true)"
    # Type=simple ne garantit pas que les sockets soient prêtes au retour de start : leur présence est contrôlée ici.
    for ligne in "/run/paresia-tunnel root:root 711" "/run/paresia-tunnel/romulus paresia-tunnel:paresia-romulus 710" \
        "/run/paresia-tunnel/pollux paresia-tunnel:paresia-pollux 710"; do
        controle_attributs "${ligne%% *}" "${ligne#* }"
    done
    controle_attributs "$TMPFILES_TUNNEL" "root:root 644"
}

jumeaux() {                  # COMPTE SOCKET ACTION SESSION
    sudo /usr/sbin/runuser -u "$1" -- /usr/bin/python3 -I -c "import json,secrets,socket,sys; s=socket.socket(socket.AF_UNIX); s.settimeout(3); s.connect(sys.argv[1]); s.sendall(json.dumps({'proto':'jumeaux/1','id':secrets.token_hex(8),'session':int(sys.argv[3]),'action':sys.argv[2],'params':{}}).encode()+b'\n'); print(s.makefile('rb').readline().decode().strip())" "$2" "$3" "$4" 2>&1 | tail -n 1 | filtre_sortie
}

connecte() {                 # COMPTE SOCKET : « connecte » attendu
    sudo /usr/sbin/runuser -u "$1" -- /usr/bin/python3 -I -c "import socket; s=socket.socket(socket.AF_UNIX); s.settimeout(3); s.connect('$2'); print('connecte')" 2>&1 | tail -n 1 | filtre_sortie
}

refuse() {                   # COMPTE SOCKET : PermissionError attendu
    sudo /usr/sbin/runuser -u "$1" -- /usr/bin/python3 -I -c "import socket; s=socket.socket(socket.AF_UNIX); s.connect('$2')" 2>&1 | tail -n 1 | filtre_sortie
}

# tunnel_sockets : les sockets locales créées par ssh sont accessibles à Pollux et à Romulus, à eux seuls.
# Le mode réel (StreamLocalBindMask 0111, UMask=0077 de l'unité) est un relevé, jamais présumé.
deja_conforme_tunnel_sockets() { return 1; }
etape_tunnel_sockets() {
    releve_info "tunnel-sockets" "$(sudo /usr/bin/stat -c '%U:%G %a %n' /run/paresia-tunnel/romulus/remus.sock /run/paresia-tunnel/pollux/castor.sock | filtre_sortie)"
    releve_info "stat:dossiers" "$(sudo /usr/bin/stat -c '%U:%G %a %F %n' /run/paresia-tunnel /run/paresia-tunnel/romulus /run/paresia-tunnel/pollux | filtre_sortie)"
    releve_info "namei" "$(sudo /usr/bin/namei -l /run/paresia-tunnel/romulus/remus.sock /run/paresia-tunnel/pollux/castor.sock | filtre_sortie)"
}

# Membres déclarés des deux groupes (getent(1), base group ; group(5), champ liste_utilisateurs) : deux lignes, avec le
# quatrième champ vide, donc aucun membre supplémentaire ; l'appartenance primaire des démons vient des comptes.
# Un groupe manquant ou une liste de membres non vide arrête le script.
controle_groupes_tunnel() {
    local lignes ligne nom
    lignes=$(sudo /usr/bin/getent group paresia-romulus paresia-pollux | filtre_sortie)
    verifie "getent:group:lignes" 2 "$(grep -c '' <<< "$lignes")"
    for nom in paresia-romulus paresia-pollux; do
        ligne=$(grep "^$nom:" <<< "$lignes" || true)
        verifie "getent:group:$nom:membres" "" "$(cut -d: -f4 <<< "$ligne")"
    done
}
verifier_tunnel_sockets() {
    local reponse
    controle_groupes_tunnel
    if ! unite_visee paresia-tunnel.service; then
        return 0
    fi
    verifie "paresia-romulus -> remus.sock" connecte "$(connecte paresia-romulus /run/paresia-tunnel/romulus/remus.sock)"
    verifie "paresia-pollux -> castor.sock" connecte "$(connecte paresia-pollux /run/paresia-tunnel/pollux/castor.sock)"
    case $(refuse nobody /run/paresia-tunnel/pollux/castor.sock) in *PermissionError*) ;; *) ecart "refused:nobody:castor.sock" PermissionError autre ;; esac
    case $(refuse paresia-romulus /run/paresia-tunnel/pollux/castor.sock) in *PermissionError*) ;; *) ecart "refused:paresia-romulus:castor.sock" PermissionError autre ;; esac
    case $(refuse paresia-pollux /run/paresia-tunnel/romulus/remus.sock) in *PermissionError*) ;; *) ecart "refused:paresia-pollux:remus.sock" PermissionError autre ;; esac
    # Sous mise à jour, l'essai qui ouvre puis ferme le feu de la session 9001 de Castor n'est pas rejoué.
    if [ "$MISE_A_JOUR" = oui ]; then
        return 0
    fi
    # ATTENTION : cet échange ouvre puis ferme le feu de la session 9001 de Castor ; sans effet sur une session réelle.
    attention "ping-and-close" "session-9001"
    for reponse in castor/light/ping castor/light/close; do
        case $(jumeaux paresia-pollux /run/paresia-tunnel/pollux/castor.sock "$reponse" 9001) in
            *'"ok": true'* | *'"ok":true'*) hook alpha_verifie "$reponse:9001" ok ;;
            *) ecart "$reponse:9001" '"ok":true' "autre" ;;
        esac
    done
}

# ---------------------------------------------------------------------------
# Étape activation (sous --activer seulement) : systemctl enable de pollux et romulus seulement,
# après la conformité de toutes les étapes précédentes. Le tunnel est tiré par les services.
# Retour arrière : systemctl disable.
# ---------------------------------------------------------------------------
UNITES_ACTIVER="pollux.service romulus.service"
unites_activer() {
    UNITES_ACTIVER="pollux.service romulus.service"
}
etat_activation() {
    unites_activer
    # shellcheck disable=SC2086
    sudo /usr/bin/systemctl is-enabled $UNITES_ACTIVER | filtre_sortie | tr '\n' ' ' || true
}
attendu_activation() {
    printf 'enabled enabled '
}
deja_conforme_activation() {
    [ "$(etat_activation)" = "$(attendu_activation)" ]
}
etape_activation() {
    unites_activer
    # ATTENTION : systemctl enable est persistant ; n'est lancé que si tout est conforme.
    attention "systemctl enable" "$UNITES_ACTIVER"
    # shellcheck disable=SC2086
    sudo /usr/bin/systemctl enable $UNITES_ACTIVER
}
verifier_activation() {
    verifie "is-enabled $UNITES_ACTIVER" "$(attendu_activation)" "$(etat_activation)"
}

# ---------------------------------------------------------------------------
# Retour arrière : --retour-arriere --jeu <nom> --confirme. Ordre inverse de la pose :
# arrêt des unités posées, restauration de chaque fichier sauvegardé ou marqué absent (arrêt au
# premier code 5), sshd -t puis reload ssh (SESSION_SECOURS=oui), daemon-reload, dossiers vides,
# comptes et groupes créés par cette installation. Idempotent ; jamais userdel -r.
# ---------------------------------------------------------------------------
# pose_complete : tout ce que l'installation ou la mise à jour peut poser, dans l'ordre de pose (POSE).
pose_complete() {
    local nom
    POSE=("$REPERTOIRE_APP/.ssh/authorized_keys" /usr/local/lib/paresia/server /usr/local/bin/pollux-session /usr/local/lib/paresia/VERSION
        "$INSTALLE_EMPREINTES" /etc/paresia/paresia.conf /etc/paresia/paresia.conf.paresia-nouveau
        /etc/paresia/conf.d/10-backend-admin.conf /etc/paresia/conf.d/10-backend-admin.conf.paresia-nouveau "$WEB_DOSSIER" "$SSHD_APP"
        /etc/systemd/system/pollux.service /etc/systemd/system/romulus.service
        /etc/paresia/tunnel/id_ed25519 /etc/paresia/tunnel/id_ed25519.pub /etc/paresia/tunnel/ssh_config
        /etc/paresia/tunnel/ssh_config.d/10-relais.conf /etc/paresia/tunnel/known_hosts
        /etc/tmpfiles.d/paresia-tunnel.conf /etc/systemd/system/paresia-tunnel.service)
    lire_declarations
    for nom in "${DECLARATIONS_NOMS[@]}"; do
        POSE+=("$DECLARATIONS_DOSSIER/$nom.toml")
    done
}

retour_arriere() {
    local chemin pose_sshd=non indice ligne
    if [ "$PARESIA_SAUVEGARDE_STOCKAGE_ACTIF" = non ]; then
        arreter "$EX_CONFIG" install_err_retour_sans_sauvegarde
    fi
    JEU=$JEU_OPTION
    pose_complete
    local -a pose=("${POSE[@]}")
    copier_code_outil
    if maj_jeu_de_mise_a_jour; then
        maj_retour_manuel
        return 0
    fi
    if dans_jeu "$SSHD_APP"; then
        pose_sshd=oui
        exiger_session_secours
    fi
    msg install_retour_arret
    for chemin in paresia-tunnel pollux romulus; do
        if dans_jeu "/etc/systemd/system/$chemin.service"; then
            # ATTENTION : l'arrêt ferme toutes les sessions de présence (D9).
            attention "systemctl disable --now" "$chemin.service"
            sudo /usr/bin/systemctl disable --now "$chemin.service"
        fi
    done
    for ((indice = ${#pose[@]} - 1; indice >= 0; indice--)); do
        chemin=${pose[$indice]}
        if restaurer_si_pose "$chemin"; then
            hook alpha_verifie "restored" "$chemin"
        fi
    done
    if [ "$pose_sshd" = oui ]; then
        recharger_ssh
    fi
    sudo /usr/bin/systemctl daemon-reload
    for ligne in /var/lib/paresia-pollux /var/lib/paresia-romulus "$REPERTOIRE_APP/.ssh" "$REPERTOIRE_APP" /usr/local/lib/paresia/romulus/services /usr/local/lib/paresia/romulus \
        /usr/local/share/paresia /usr/local/lib/paresia /etc/paresia/tunnel/ssh_config.d \
        /etc/paresia/tunnel /etc/paresia/conf.d /etc/paresia /run/paresia-tunnel/romulus /run/paresia-tunnel/pollux \
        /run/paresia-tunnel /etc/tmpfiles.d; do
        # ATTENTION : rmdir ne retire qu'un dossier vide.
        if sudo /usr/bin/rmdir -- "$ligne" 2> /dev/null; then
            hook alpha_verifie "removed-directory" "$ligne"
        fi
    done
    if cree_par_installation membre www-data; then
        attention gpasswd www-data
        sudo /usr/bin/gpasswd -d www-data paresia-http
    fi
    supprimer_comptes_crees
    msg install_retour_fait
}

principal "$@"
