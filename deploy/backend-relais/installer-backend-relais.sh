#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# installer-backend-relais.sh : installation complète de Castor, de Remus, de leurs comptes, du
# sudoers, de la table nftables et de la partie « tunnel » de backend-relais (D65, D80, D82, D83, D103, D114, D138).
#
# Suivi des versions
#   0.1.19  2026-11-08  Journal d’essai remis à l’appelant sous sudo.
#   0.2.0  2026-11-08  Option --mise-a-jour (versions, arrêt et reprise des seules unités de Paresia, empreintes de configuration, retour arrière automatique) ; prérequis signalés en une fois ; copie périmée sous /run/paresia-installation déplacée.
#   0.1.2  2026-11-08  Étapes produit (contrôle de l'image) et fonctions (pose des fonctions de Remus) avant sudoers (D148, D150, D167).
#   0.1.1  2026-11-07  Dossiers d'état de Castor et Remus : contrôle des directives et des droits.
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
#   REPERTOIRE_TUNNEL           --repertoire-tunnel        /var/lib/paresia-tunnel ; jamais sous /home
#   PROFIL                      --profil                   relais ; relais ou partage (code partagé avec backend-admin)
#   CODE_REMPLACEMENT_CONFIRME  --code-remplacement-confirme  non ; oui autorise le remplacement de fichiers installés différents
#   MISE_A_JOUR                 --mise-a-jour             non ; oui : met à jour une installation existante (voir « Mise à jour »)
#   PORT_ESSAI                  --port-essai               49152 ; port TCP libre de l'essai local (1024 à 65535)
#   SESSION_SECOURS             --session-secours          non ; oui : deuxième session ouverte et testée (obligatoire pour sshd)
#   PARESIA_SAUVEGARDE_STOCKAGE_ACTIF  --stockage-actif    oui ; non désactive les sauvegardes (le retour arrière échoue alors)
#   ACCES_TUNNEL_SANS_NFTABLES  --acces-tunnel-sans-nftables  non ; oui ouvre l'accès de tunnel sans la table paresia_relais
#   ADRESSE_ADMIN               --adresse-admin            aucun ; adresse IP source de backend-admin (partie tunnel)
#   CLE_PUBLIQUE_TUNNEL         --cle-publique-tunnel      aucun ; clé publique « ssh-ed25519 AAAA… » du tunnel
#   EMPREINTE_CLE_TUNNEL        --empreinte-cle-tunnel     aucun ; empreinte SHA256 de cette clé, lue sur backend-admin
# La partie tunnel exige les trois paramètres ADRESSE_ADMIN, CLE_PUBLIQUE_TUNNEL et EMPREINTE_CLE_TUNNEL (les trois ou aucun).
# Autres options : --aide, --version, --verifier (paramètres et prérequis, lecture seule), --alpha-test,
# --retour-arriere, --jeu <nom>, --confirme, --activer, --sauter <étape> (sudoers, nftables, isolation_remus,
# www-data ; liste fermée).
#
# Exécution. Aucun shell root : le script refuse de s'exécuter en root (code 77) ; il se lance sous un
# compte ordinaire doté de sudo (1.9.10 ou plus) et appelle « sudo <chemin absolu> » commande par commande,
# sans fonction qui masque le chemin ni `sudo -i`, `su` ou `sudo sh -c`.
#
# Commandes lancées par `sudo` : liste descriptive, pas un sudoers à recopier. Plusieurs entrées valent root si
# on les autorise sans arguments figés (env, python3, tee, install, sed -i, chown, runuser, find -exec, tar, cp, mv,
# visudo, systemd-run, systemctl sans unité) ; `env … python3 -P -m server.sauvegarde` et `runuser … python3 -I -c`
# ne peuvent pas être restreintes et sont propres à cette installation. Pour un sudoers,
# figez un par un l'exécutable, le compte cible et les arguments exacts.
#
# - outil de sauvegarde : /usr/bin/env PYTHONPATH=/run/paresia-installation PARESIA_SAUVEGARDE_CONFIG=… /usr/bin/python3 -P -m server.sauvegarde (jeu, releve, copier, retrouver, restaurer) ;
# - comptes : /usr/sbin/groupadd, /usr/sbin/useradd, /usr/sbin/usermod, /usr/sbin/userdel, /usr/sbin/groupdel, /usr/bin/passwd -S ;
# - fichiers : /usr/bin/install, /usr/bin/tar, /usr/bin/cp -a, /usr/bin/mv -T, /usr/bin/chown, /usr/bin/find … -exec /usr/bin/chmod, /usr/bin/chmod, /usr/bin/sed -i, /usr/bin/tee, /usr/bin/cat, /usr/bin/diff, /usr/bin/grep, /usr/bin/rmdir, /usr/bin/test, /usr/bin/stat, /usr/bin/ls, /usr/bin/sha256sum (empreintes de configuration) ;
# - produit visé par les fonctions (lecture seule, aucune action sur Docker) : /usr/bin/docker inspect --format ;
# - sudoers, réseau et clés : /usr/sbin/visudo -c -f, /usr/bin/sudo (-V, --version, -n -l -U chef, -u chef), /usr/sbin/nft (--version, list, -c -f, delete table inet paresia_relais), /usr/sbin/sshd (-t, -T -C user=…), /usr/bin/ssh-keygen -lf ;
# - services : /usr/bin/systemctl (reload ssh, daemon-reload, start, stop, status, show, enable, disable, is-active, is-enabled pour paresia-nftables, castor et remus), /usr/bin/systemd-analyze verify, /usr/bin/systemd-run --wait --pipe --collect, /usr/bin/journalctl -u <unité> -n 30 --no-pager ;
# - essais : /usr/sbin/runuser -u tunnel|nobody|chef -- /usr/bin/python3 -I -c …, /usr/sbin/runuser -u chef -g chef -G paresia-castor-etat -- /usr/bin/python3 -I -c … (lecture de l'état de Castor), /usr/bin/env -i PYTHONPATH=… /usr/sbin/runuser -u nobody -- /usr/bin/python3 -P -s -B -m server.remus.sudoers.
#
# Étapes (une fonction etape_<nom>, précédée de deja_conforme_<nom> et suivie de verifier_<nom>) :
# prerequis, [mise_a_jour_etat sous --mise-a-jour,] produit, sauvegarde, identifiants_comptes, verification_comptes, code_configuration, fonctions, sudoers, nftables,
# unites, castor, remus, refus_castor, isolation_remus, [tunnel_releves, tunnel_authorized_keys, tunnel_sshd,
# tunnel_compte avec les trois paramètres du tunnel], activation (sous --activer). La lecture de
# isolation-remus.md est un renvoi : ses décisions et ses essais sont repris par isolation_remus.
#
# Rejouable. Chaque étape lit d'abord l'état : identique à l'attendu, elle est « déjà en place » (aucune
# commande modifiante, aucune sauvegarde) ; différent, elle est refusée avant toute modification (code 78).
# Sauf sous --mise-a-jour, le script n'arrête ni ne redémarre aucune unité : un démon actif dont le code ou la
# configuration changerait doit d'abord être arrêté par l'administrateur. Seul `reload ssh` est lancé, après `sshd -t` et
# avec SESSION_SECOURS=oui. strfry, Docker, lighttpd, bunkerd et les unités de la version précédente
# ne sont jamais touchés, avec ou sans --mise-a-jour ; la table nftables paresia_relais est la seule ajoutée au pare-feu.
#
# Mise à jour (--mise-a-jour). Sur une installation existante, le script lit la version installée
# (/usr/local/lib/paresia/VERSION, forme X.Y.Z) et la version livrée (VERSION du clone), affiche « installée X, livrée Y »
# et ne remplace que ce qui diffère. Une version livrée plus ancienne, un VERSION installé illisible ou absent, ou un format
# de manifeste de sauvegarde différent entre l'outil installé et l'outil livré sont refusés (78) avant toute modification ;
# un état identique est « déjà en place ». Demander la mise à jour vaut acceptation de l'interruption des unités de Paresia :
# avant toute modification, le script annonce sur l'erreur standard les unités qui seront arrêtées (remus puis castor), l'effet
# (remise au rouge des feux de Castor ; interruption de la mise en attente de Remus) et le nom du jeu de sauvegarde. Ordre : sauvegarde complète du jeu, arrêt
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
# Sauvegarde. Avant toute modification, le jeu daté /var/backups/paresia/relais/AAAAMMJJ-HHMMSS est créé
# (son nom est affiché sur la sortie standard) et l'outil du dépôt copie chaque fichier concerné.
# Retour arrière. --retour-arriere --jeu <nom> --confirme : arrêt des unités posées, restauration dans l'ordre
# inverse de la pose, visudo -c, sshd -t puis reload ssh, suppression des seuls comptes et groupes créés par
# cette installation. Sur un jeu de mise à jour (relevé mise-a-jour) : arrêt des seules unités de la liste (remus puis
# castor), restauration (code, VERSION, configuration, sudoers, unités, empreintes, fichiers .paresia-nouveau), visudo -c,
# daemon-reload, reprise des unités actives avant, contrôle de la version ; aucun compte ni groupe n'est supprimé et l'état
# d'activation est conservé. À la fin d'une exécution, l'empreinte de la clé d'hôte est affichée sur la sortie
# standard : elle est à fournir à backend-admin, qui la compare à celle de ssh-keyscan.
#
# Prérequis, tous signalés en une fois (un seul message, sortie 69) : Debian 13, systemd, Python 3.11 ou plus, sudo
# 1.9.10 ou plus, ss (iproute2), bash et les exécutables de la liste ci-dessus (sudo, visudo, nft, runuser, sshd, ssh-keygen,
# systemctl, journalctl, systemd-analyze, systemd-run, groupadd, useradd, usermod, userdel, groupdel, install, tar, cp, mv,
# chown, chmod, find, tee, sed, diff, cat, grep, rmdir, stat, ls, test, getent, passwd, sha256sum), dont la présence est testée
# sans sudo : l'absence de sudo lui-même est donc signalée avec les autres manques.
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
# backend-relais : compte ordinaire doté de sudo, aucun shell root (D138). Chaque commande
# privilégiée porte son propre « sudo <chemin absolu> », écrit littéralement.
# ---------------------------------------------------------------------------
NOM_SCRIPT=installer-backend-relais
VERSION_SCRIPT=0.2.0
MACHINE='relais'
CONF_OUTIL=/run/paresia-installation/server/conf/paresia-relais.conf
TUNNEL_ACTIF=non
CASTOR_DEMARRE=non
ETAPES=()
TABLE_GROUPES=()
TABLE_COMPTES=()
TABLE_GROUPES_ARRIERE=()
TABLE_COMPTES_ARRIERE=()
TABLE_CONFIG=()
CONFIGURATION=''
SRC=deploy/backend-relais/etc
UNITES_RELAIS=(castor remus)
# Listes fermées de la mise à jour (jamais lues d'un fichier ni d'un paramètre) : unités dans l'ordre d'arrêt (remus puis
# castor) ; les unités de Pollux et Romulus (profil partage) ne sont jamais arrêtées par ce script.
MAJ_UNITES=(remus.service castor.service)
MAJ_POSSIBLES=(remus.service castor.service)
MAJ_HORS_LISTE=(pollux.service romulus.service)
# Fonctions de Remus déclarées par le greffon de base : fichiers sauvegardés avec la mise à jour et restaurés au retour arrière.
FONCTIONS_REMUS=/usr/local/lib/paresia/remus/fonctions
FONCTIONS_REMUS_FICHIERS=("$FONCTIONS_REMUS/strfry_arbres" "$FONCTIONS_REMUS/strfry_arbres.toml" "$FONCTIONS_REMUS/strfry_etat"
    "$FONCTIONS_REMUS/strfry_etat.toml" "$FONCTIONS_REMUS/strfry_redemarrer" "$FONCTIONS_REMUS/strfry_redemarrer.toml")

defauts_machine() {
    DEPOT="${DEPOT:-$(racine_clone)}"
    LANGUE="${LANGUE:-$(langue_defaut)}"
    DOSSIER_JOURNAL="${DOSSIER_JOURNAL:-$DOSSIER_LANCEMENT}"
    REPERTOIRE_TUNNEL="${REPERTOIRE_TUNNEL:-/var/lib/paresia-tunnel}"
    PROFIL="${PROFIL:-relais}"
    CODE_REMPLACEMENT_CONFIRME="${CODE_REMPLACEMENT_CONFIRME:-non}"
    MISE_A_JOUR="${MISE_A_JOUR:-non}"
    PORT_ESSAI="${PORT_ESSAI:-49152}"
    SESSION_SECOURS="${SESSION_SECOURS:-non}"
    PARESIA_SAUVEGARDE_STOCKAGE_ACTIF="${PARESIA_SAUVEGARDE_STOCKAGE_ACTIF:-oui}"
    ACCES_TUNNEL_SANS_NFTABLES="${ACCES_TUNNEL_SANS_NFTABLES:-non}"
    ADRESSE_ADMIN="${ADRESSE_ADMIN:-}"
    CLE_PUBLIQUE_TUNNEL="${CLE_PUBLIQUE_TUNNEL:-}"
    EMPREINTE_CLE_TUNNEL="${EMPREINTE_CLE_TUNNEL:-}"
}

option_machine() {
    case $1 in
        --repertoire-tunnel) valeur_requise "$@"; REPERTOIRE_TUNNEL=$2 ;;
        --profil) valeur_requise "$@"; PROFIL=$2 ;;
        --port-essai) valeur_requise "$@"; PORT_ESSAI=$2 ;;
        --acces-tunnel-sans-nftables) valeur_requise "$@"; ACCES_TUNNEL_SANS_NFTABLES=$2 ;;
        --adresse-admin) valeur_requise "$@"; ADRESSE_ADMIN=$2 ;;
        --cle-publique-tunnel) valeur_requise "$@"; CLE_PUBLIQUE_TUNNEL=$2 ;;
        --empreinte-cle-tunnel) valeur_requise "$@"; EMPREINTE_CLE_TUNNEL=$2 ;;
        *) return 1 ;;
    esac
}

# Valeur par défaut posée (defauts_machine), puis validation, puis usage.
valider_machine() {
    REPERTOIRE_TUNNEL=$(chemin_normalise REPERTOIRE_TUNNEL "$REPERTOIRE_TUNNEL")
    case $PROFIL in
        relais) CONFIGURATION=/etc/paresia/paresia.conf ;;
        partage) CONFIGURATION=/etc/paresia/conf.d/20-relais.conf ;;
        *) arreter "$EX_DATAERR" install_err_param_invalide "nom=PROFIL" "valeur=$PROFIL" ;;
    esac
    valider_port PORT_ESSAI "$PORT_ESSAI"
    valeur_oui_non ACCES_TUNNEL_SANS_NFTABLES "$ACCES_TUNNEL_SANS_NFTABLES"
    if [ -n "$ADRESSE_ADMIN" ] || [ -n "$CLE_PUBLIQUE_TUNNEL" ] || [ -n "$EMPREINTE_CLE_TUNNEL" ]; then
        if [ -z "$ADRESSE_ADMIN" ]; then
            arreter "$EX_USAGE" install_err_param_absent "nom=ADRESSE_ADMIN"
        fi
        if [ -z "$CLE_PUBLIQUE_TUNNEL" ]; then
            arreter "$EX_USAGE" install_err_param_absent "nom=CLE_PUBLIQUE_TUNNEL"
        fi
        if [ -z "$EMPREINTE_CLE_TUNNEL" ]; then
            arreter "$EX_USAGE" install_err_param_absent "nom=EMPREINTE_CLE_TUNNEL"
        fi
        valider_adresse ADRESSE_ADMIN "$ADRESSE_ADMIN"
        valider_cle_publique CLE_PUBLIQUE_TUNNEL "$CLE_PUBLIQUE_TUNNEL"
        valider_empreinte EMPREINTE_CLE_TUNNEL "$EMPREINTE_CLE_TUNNEL"
        TUNNEL_ACTIF=oui
    fi
}

controle_identite() {
    if [ "$(id -u)" = 0 ]; then
        arreter "$EX_NOPERM" install_err_root_interdit
    fi
}

# --- mise à jour : crochets propres à backend-relais (voir le bloc commun) ---------------------------------------------------
maj_cle_effet() {            # UNITE -> clé du catalogue qui décrit l'effet d'un arrêt
    case $1 in
        castor.service) printf '%s\n' install_maj_effet_feux ;;
        *) printf '%s\n' install_maj_effet_remus ;;
    esac
}

maj_unites_liste() {
    MAJ_UNITES=(remus.service castor.service)
}

# maj_differences : fichiers livrés dont le contenu diffère de celui qui est installé (lecture seule). La table nftables
# n'est ni rechargée ni modifiée par la mise à jour : un écart est seulement signalé.
maj_differences() {
    local u livree
    MAJ_DIFFERENCES=()
    if ! code_relais_conforme; then
        maj_ajouter code
    fi
    composer_configuration "$DEPOT/$SOURCE_CONF"
    livree=$(printf '%s\n' "$COMPOSEE" | empreinte_texte)
    if ! conf_conforme "$CONFIGURATION" "$livree"; then
        maj_ajouter configuration
    fi
    if ! etape_sautee sudoers && a_poser "$DEPOT/$SRC/sudoers.d/paresia-remus" "$SUDOERS_REMUS" 0440; then
        maj_ajouter sudoers
    fi
    for u in "${UNITES_RELAIS[@]}"; do
        if a_poser "$DEPOT/$SRC/systemd/system/$u.service" "/etc/systemd/system/$u.service" 0644; then
            maj_ajouter unites
        fi
    done
    if [ "$TUNNEL_ACTIF" = oui ] && a_poser "$DEPOT/$SRC/ssh/sshd_config.d/50-paresia-tunnel.conf" "$SSH_TUNNEL" 0644; then
        maj_ajouter sshd
    fi
    if ! etape_sautee nftables && existe "$NFT_FICHIER" && existe "$NFT_UNITE"; then
        if a_poser "$DEPOT/$SRC/nftables/paresia-relais.nft" "$NFT_FICHIER" 0644 \
            || a_poser "$DEPOT/$SRC/systemd/system/paresia-nftables.service" "$NFT_UNITE" 0644; then
            msg install_maj_nft_ecart
        fi
    fi
}

# maj_liste_sauvegarde : tout ce que la mise à jour peut remplacer ; sauvegardé en entier avant le premier arrêt.
maj_liste_sauvegarde() {
    MAJ_SAUVEGARDE=(/usr/local/lib/paresia/server /usr/local/lib/paresia/VERSION "$INSTALLE_EMPREINTES"
        "$CONFIGURATION" "$CONFIGURATION.paresia-nouveau" "$SUDOERS_REMUS" "${FONCTIONS_REMUS_FICHIERS[@]}"
        /etc/systemd/system/castor.service /etc/systemd/system/remus.service)
    if [ "$TUNNEL_ACTIF" = oui ]; then
        MAJ_SAUVEGARDE+=("$SSH_TUNNEL" "$SSH_ALLOWUSERS")
    fi
}

sshd_dans_jeu() {            # 0 si le jeu a sauvegardé ou marqué un fichier sshd de cette machine
    dans_jeu "$SSH_TUNNEL" || dans_jeu "$SSH_ALLOWUSERS"
}

# maj_apres_restauration : le sudoers restauré est contrôlé par visudo -c.
maj_apres_restauration() {
    if existe "$SUDOERS_REMUS"; then
        sudo /usr/sbin/visudo -c -f "$SUDOERS_REMUS" > /dev/null || return 1
    fi
    return 0
}

# Relevés initiaux (sans secret) enregistrés dans le jeu à sa création.
apres_creation_jeu() {
    { getent passwd paresia-castor chef tunnel || test "$?" -eq 2; } | releve comptes-avant
    { getent group paresia-castor chef tunnel paresia-castor-tunnel paresia-remus-tunnel paresia-castor-etat || test "$?" -eq 2; } | releve groupes-avant
    sudo /usr/sbin/nft list ruleset | releve nft-initial
    releves_systeme_avant
}

construire_etapes() {
    # Noms D65, numéros attribués par le système.
    TABLE_GROUPES=(paresia-castor chef tunnel paresia-castor-tunnel paresia-remus-tunnel paresia-castor-etat)
    TABLE_COMPTES=("paresia-castor /nonexistent /usr/sbin/nologin" "chef /nonexistent /usr/sbin/nologin"
        "tunnel $REPERTOIRE_TUNNEL /usr/sbin/nologin")
    TABLE_COMPTES_ARRIERE=("tunnel x x" "chef x x" "paresia-castor x x")
    TABLE_GROUPES_ARRIERE=(paresia-castor-etat paresia-remus-tunnel paresia-castor-tunnel tunnel chef paresia-castor)
    # Numéros inscrits dans la configuration installée : « section clé compte|groupe NOM » (source unique).
    TABLE_CONFIG=("castor.tunnel uid compte tunnel" "castor.tunnel gid groupe paresia-castor-tunnel"
        "castor.state uid compte chef" "castor.state gid groupe paresia-castor-etat"
        "remus.server uid compte tunnel" "remus.server gid groupe paresia-remus-tunnel"
        "remus.castor uid compte paresia-castor")
    ETAPES=(prerequis produit sauvegarde identifiants_comptes verification_comptes code_configuration fonctions sudoers nftables
        unites castor remus refus_castor isolation_remus)
    if [ "$TUNNEL_ACTIF" = oui ]; then
        ETAPES+=(tunnel_releves tunnel_authorized_keys tunnel_sshd tunnel_compte)
    fi
    if [ "$MISE_A_JOUR" = oui ]; then
        ETAPES=("${ETAPES[0]}" mise_a_jour_etat "${ETAPES[@]:1}")
    fi
    ETAPES+=(activation)
}

fin_machine() {
    local empreinte
    empreinte=$(sudo /usr/bin/ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub | awk 'NR==1 {print $2}' | filtre_sortie)
    msg_out install_empreinte_hote "empreinte=$empreinte"
    if [ "$TUNNEL_ACTIF" != oui ]; then
        msg install_suite_tunnel_relais
    fi
}

# ---------------------------------------------------------------------------
# Étape prerequis (lecture seule) : Debian 13, systemd, Python, sudo 1.9.10 ou plus (sudoers(5) :
# expressions régulières depuis la 1.9.10), nft, visudo, runuser, ss. Retour arrière : sans objet.
# ---------------------------------------------------------------------------
controle_prerequis() {
    local systeme version
    executables_requis /usr/bin/python3 /usr/bin/env /usr/bin/sudo /usr/sbin/visudo /usr/sbin/nft /usr/sbin/runuser \
        /usr/sbin/sshd /usr/bin/ssh-keygen /usr/bin/systemctl /usr/bin/journalctl /usr/bin/systemd-analyze \
        /usr/bin/systemd-run /usr/sbin/groupadd /usr/sbin/useradd /usr/sbin/usermod /usr/sbin/userdel /usr/sbin/groupdel \
        /usr/bin/install /usr/bin/tar /usr/bin/cp /usr/bin/mv /usr/bin/chown /usr/bin/chmod /usr/bin/find /usr/bin/tee \
        /usr/bin/sed /usr/bin/diff /usr/bin/cat /usr/bin/grep /usr/bin/rmdir /usr/bin/stat /usr/bin/ls /usr/bin/test \
        /usr/bin/getent /usr/bin/passwd /usr/bin/sha256sum
    if ! command -v ss > /dev/null; then
        accumuler /usr/bin/ss
    fi
    lire_systemd
    if [ -x /usr/bin/python3 ] && ! /usr/bin/python3 -I -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
        accumuler python-3.11
    fi
    # sans sudo, rien de ce qui suit ne peut être lu : son absence est déjà consignée avec les autres manques
    if [ -x /usr/bin/sudo ]; then
        if systeme=$(lire_systeme /etc/os-release); then
            if ! grep -q '^ID=debian$' <<< "$systeme" || ! grep -Eq '^VERSION_ID="?13"?$' <<< "$systeme"; then
                accumuler debian-13
            fi
        else
            accumuler os-release
        fi
        version=$(sudo /usr/bin/sudo --version | awk 'NR==1 {print $3}' | filtre_sortie)
        version=${version%%p*}
        if [ "$(printf '%s\n%s\n' "$version" 1.9.10 | sort -V | awk 'NR==1')" != 1.9.10 ]; then
            accumuler sudo-1.9.10
        fi
    fi
    controle_manques
    releve_info "nft" "$(sudo /usr/sbin/nft --version | filtre_sortie)"
}

deja_conforme_prerequis() { return 1; }
etape_prerequis() { controle_prerequis; }
verifier_prerequis() { releve_info "systemd" "$SYSTEMD_VERSION"; }

# Étape sauvegarde : copie root du code de l'outil (D114) ; le jeu est créé au premier fichier à sauvegarder.
deja_conforme_sauvegarde() { code_outil_en_place; }
etape_sauvegarde() { copier_code_outil; }
verifier_sauvegarde() { controle_attributs "$TRAVAIL" "root:root 700"; }

# ---------------------------------------------------------------------------
# Étape identifiants_comptes : refus de tout groupe ou compte non conforme (plage système de login.defs(5)),
# puis groupes avant comptes, identifiants attribués par le système (D65), tunnel de répertoire $REPERTOIRE_TUNNEL (sous /var/lib, FHS),
# /nonexistent pour les autres (useradd(8) ; adduser(8)), puis les seuls groupes supplémentaires
# de tunnel. Retour arrière : userdel puis groupdel des seuls comptes et groupes créés ici.
# ---------------------------------------------------------------------------
tunnel_dossiers_conformes() {
    dossier_etat "$REPERTOIRE_TUNNEL" "root:root 755" && dossier_etat "$REPERTOIRE_TUNNEL/.ssh" "root:root 755"
}

tunnel_groupes_ok() {
    membre tunnel paresia-castor-tunnel && membre tunnel paresia-remus-tunnel
}

deja_conforme_identifiants_comptes() {
    composer_configuration "$DEPOT/$SOURCE_CONF" essai
    if ! getent passwd tunnel > /dev/null && existe "$REPERTOIRE_TUNNEL"; then
        refuser_difference "$REPERTOIRE_TUNNEL"
    fi
    comptes_conformes && tunnel_dossiers_conformes && tunnel_groupes_ok
}

etape_identifiants_comptes() {
    creer_comptes
    # ATTENTION : install crée le répertoire de tunnel (root:root 0755) ; aucun répertoire existant n'est déplacé.
    if ! tunnel_dossiers_conformes; then
        sudo /usr/bin/install -d -o root -g root -m 0755 "$REPERTOIRE_TUNNEL" "$REPERTOIRE_TUNNEL/.ssh"
    fi
    if ! tunnel_groupes_ok; then
        # ATTENTION : usermod modifie /etc/group ; jamais -G sans -a.
        jeu_pret
        attention usermod tunnel
        sudo /usr/sbin/usermod -aG paresia-castor-tunnel,paresia-remus-tunnel tunnel
    fi
}

verifier_identifiants_comptes() { verifier_comptes; }

# ---------------------------------------------------------------------------
# Étape verification_comptes (lecture seule) : identités réelles avant sudo et réseau.
# chef n'a que son groupe primaire ; tunnel a ses deux groupes de sockets ; mots de passe verrouillés.
# ---------------------------------------------------------------------------
deja_conforme_verification_comptes() { return 1; }
etape_verification_comptes() { :; }
verifier_verification_comptes() {
    local repertoire nom
    verifie "id -nG chef" chef "$(id -nG chef)"
    verifie "id -nG tunnel" "paresia-castor-tunnel paresia-remus-tunnel tunnel" "$(id -nG tunnel | tr ' ' '\n' | sort | tr '\n' ' ' | sed 's/ $//')"
    verifie "getent group paresia-castor-tunnel" tunnel "$(getent group paresia-castor-tunnel | cut -d: -f4)"
    verifie "getent group paresia-remus-tunnel" tunnel "$(getent group paresia-remus-tunnel | cut -d: -f4)"
    repertoire=$(getent passwd tunnel | cut -d: -f6)
    repertoire=$(chemin_normalise "tunnel-home" "$repertoire")
    verifie "tunnel-home" "$REPERTOIRE_TUNNEL" "$repertoire"
    controle_attributs "$repertoire" "root:root 755"
    controle_attributs "$repertoire/.ssh" "root:root 755"
    for nom in paresia-castor chef tunnel; do
        verifie "passwd-S:$nom:locked" L "$(sudo /usr/bin/passwd -S "$nom" | awk '{print $2}' | filtre_sortie)"
        verifie "shell de $nom" /usr/sbin/nologin "$(getent passwd "$nom" | cut -d: -f7)"
    done
}

# ---------------------------------------------------------------------------
# Étape code_configuration : code root:root sans écriture des comptes de service et configuration
# du profil (relais : /etc/paresia/paresia.conf ; partage : conf.d/20-relais.conf). Un code installé
# qui diffère n'est remplacé qu'avec CODE_REMPLACEMENT_CONFIRME=oui et après l'arrêt, par vous,
# des démons qui l'utilisent. Retour arrière : restauration du code et de la configuration.
# ---------------------------------------------------------------------------
# Deux profils.
# Profil relais : machine seule, la base est /etc/paresia/paresia.conf.
# Profil partage : tout sur une machine, le code est partagé avec Pollux/Romulus (remplacé seulement s'il diffère)
# et la surcharge /etc/paresia/conf.d/20-relais.conf est ajoutée.
CODE_RELAIS=/usr/local/lib/paresia/server
SOURCE_CONF=server/conf/paresia-relais.conf
CONF_COMPOSEE=$TRAVAIL/paresia-relais.conf.composee    # livrée, numéros du système inscrits

code_relais_conforme() {
    existe "$CODE_RELAIS" && sudo /usr/bin/diff -qr --exclude=__pycache__ --exclude=conf "$DEPOT/server" "$CODE_RELAIS" > /dev/null 2>&1 \
        && contenu_identique "$DEPOT/VERSION" /usr/local/lib/paresia/VERSION \
        && [ "$(attributs /usr/local/lib/paresia/VERSION)" = "root:root 644" ]
}

deja_conforme_code_configuration() {
    local conforme=0 livree
    charger_empreintes
    if ! code_relais_conforme; then
        if existe "$CODE_RELAIS"; then
            if [ "$CODE_REMPLACEMENT_CONFIRME" != oui ] && [ "$MISE_A_JOUR" != oui ]; then
                refuser_difference "$CODE_RELAIS"
            fi
            refuser_si_active castor.service remus.service pollux.service romulus.service
        fi
        conforme=1
    fi
    dossier_etat /etc/paresia "root:root 755" || conforme=1
    dossier_etat /usr/local/lib/paresia "root:root 755" || conforme=1
    composer_configuration "$DEPOT/$SOURCE_CONF"
    if [ "$MISE_A_JOUR" = oui ]; then
        # fichier de l'administrateur : jamais écrasé (empreinte enregistrée, version livrée à côté)
        livree=$(printf '%s\n' "$COMPOSEE" | empreinte_texte)
        conf_conforme "$CONFIGURATION" "$livree" || conforme=1
    else
        ! a_poser_composee "$CONFIGURATION" 0644 || conforme=1
    fi
    return "$conforme"
}

etape_code_configuration() {
    local neuf livree
    maj_arreter_unites
    if [ -L "$CODE_RELAIS" ] || [ -L "$CONFIGURATION" ] || [ -n "$(find "$DEPOT/server" ! -type d ! -type f -print -quit)" ]; then
        arreter "$EX_CONFIG" install_err_copie_code
    fi
    jeu_pret
    neuf="$TRAVAIL/code-neuf-$JEU"
    umask 022
    sudo /usr/bin/install -d -o root -g root -m 0755 /usr/local/lib/paresia /etc/paresia /etc/paresia/conf.d
    sudo /usr/bin/install -d -o root -g root -m 0700 "$neuf"
    sudo /usr/bin/tar -C "$DEPOT" --owner=0 --group=0 --exclude='__pycache__' --exclude='server/conf' -cf - server | sudo /usr/bin/tar -C "$neuf" -xf -
    sauvegarder_arbre /usr/local/lib/paresia/server /usr/local/lib/paresia/VERSION "$CONFIGURATION"
    if ! code_relais_conforme; then
        if existe "$CODE_RELAIS"; then
            # ATTENTION : remplacement du code installé, seulement en cas de différence et après sauvegarde.
            dans_jeu "$CODE_RELAIS" || arreter "$EX_IOERR" install_err_sauvegarde
            attention "mv -T" "$CODE_RELAIS"
            sudo /usr/bin/mv -T /usr/local/lib/paresia/server "$TRAVAIL/code-retire-$JEU"
        fi
        sudo /usr/bin/cp -a "$neuf/server" /usr/local/lib/paresia/server
    fi
    # VERSION du dépôt, à côté de server/ : sans elle les démons refusent de démarrer (code 70)
    sudo /usr/bin/install -o root -g root -m 0644 "$DEPOT/VERSION" /usr/local/lib/paresia/VERSION
    # ATTENTION : chown -R change le propriétaire de tout l'arbre indiqué (code installé seulement).
    attention chown "$CODE_RELAIS"
    sudo /usr/bin/chown -R root:root /usr/local/lib/paresia/server
    sudo /usr/bin/find /usr/local/lib/paresia/server -type d -exec /usr/bin/chmod 0755 {} +
    sudo /usr/bin/find /usr/local/lib/paresia/server -type f -exec /usr/bin/chmod 0644 {} +
    composer_configuration "$DEPOT/$SOURCE_CONF"
    if [ "$MISE_A_JOUR" = oui ]; then
        ecrire_composee
        conf_appliquer "$CONFIGURATION" "$CONF_COMPOSEE"
    else
        if a_poser_composee "$CONFIGURATION" 0644; then
            # ATTENTION : install écrase la configuration existante (sauvegardée par l'outil avant).
            sudo /usr/bin/install -o root -g root -m 0644 "$CONF_COMPOSEE" "$CONFIGURATION"
        fi
        livree=$(printf '%s\n' "$COMPOSEE" | empreinte_texte)
        EMPREINTES[$CONFIGURATION]=$livree
    fi
    ecrire_empreintes
}

verifier_code_configuration() {
    local contenu
    verifie "find:/usr/local/lib/paresia:not-root-or-writable" "" \
        "$(sudo /usr/bin/find /usr/local/lib/paresia ! -user root -o -perm /022 | filtre_sortie)"
    controle_attributs /etc/paresia "root:root 755"
    controle_attributs "$CODE_RELAIS" "root:root 755"
    controle_attributs /usr/local/lib/paresia/VERSION "root:root 644"
    controle_attributs "$CONFIGURATION" "root:root 644"
    contenu=$(sudo /usr/bin/ls "$CODE_RELAIS" | filtre_sortie)
    verifie "conf-in:$CODE_RELAIS" non "$([[ $'\n'$contenu$'\n' == *$'\nconf\n'* ]] && echo oui || echo non)"
}

# ---------------------------------------------------------------------------
# Étape produit (sautable, lecture seule) : les fonctions livrées déclarent le produit auquel elles
# correspondent ([produit] de leurs manifestes : nom, source, version, empreinte facultative). Le script
# relève, par une seule commande de lecture exécutée par l'administrateur, la référence et l'identifiant
# de l'image du conteneur qui porte le nom du produit, puis compare : l'empreinte déclarée prévaut (égalité
# avec l'identifiant de l'image) ; sinon la version déclarée (exacte, ou intervalle de clauses >=, <=, >, <)
# doit se retrouver dans l'étiquette de l'image. Désaccord, conteneur absent ou référence illisible : refus
# (78) avant toute modification, avec le nom, la source et la version déclarés. Aucun conteneur ni image
# n'est créé, démarré, modifié ni supprimé. Retour arrière : sans objet.
# ---------------------------------------------------------------------------
FONCTIONS_SRC=deploy/backend-relais/usr/local/lib/paresia/remus/fonctions
FONCTIONS_DST=/usr/local/lib/paresia/remus/fonctions
PYPRODUIT='import os, re, sys, tomllib
mode, dossier = sys.argv[1], sys.argv[2]
declare = None
try:
    for fichier in sorted(os.listdir(dossier)):
        if fichier.endswith(".toml"):
            with open(os.path.join(dossier, fichier), "rb") as f:
                p = tomllib.load(f).get("produit")
            if p is not None:
                if declare is not None and declare != p:
                    sys.exit(3)
                declare = p
    nom, source, version = declare["nom"], declare["source"], declare["version"]
    if not (re.fullmatch(r"[a-z0-9][a-z0-9-]{0,31}", nom) and isinstance(source, str) and isinstance(version, str)):
        sys.exit(3)
except (OSError, ValueError, KeyError, TypeError):
    sys.exit(3)
print(nom, source[:256], version[:160], sep="\n")
if mode == "declaration":
    sys.exit(0)
lecture = sys.stdin.readline(2048).split()
if len(lecture) != 2:
    sys.exit(5)
image, identifiant = lecture
empreinte = declare.get("empreinte")
if empreinte:
    sys.exit(0 if identifiant == empreinte else 5)
etiquette = image.rsplit("/", 1)[-1].partition("@")[0]
if ":" not in etiquette:
    sys.exit(5)
etiquette = etiquette.split(":", 1)[1]
def numeros(texte):
    m = re.match(r"v?([0-9]+(?:[.][0-9]+)*)", texte)
    return tuple(int(x) for x in m.group(1).split(".")) if m else None
if "," not in version and not version.startswith((">", "<")):
    sys.exit(0 if etiquette == version or etiquette.endswith(":" + version) else 5)
valeur = numeros(etiquette)
if valeur is None:
    sys.exit(5)
for clause in version.split(","):
    m = re.fullmatch(r"(>=|<=|>|<)(.+)", clause)
    borne = numeros(m.group(2)) if m else None
    if borne is None:
        sys.exit(3)
    if not {">=": valeur >= borne, "<=": valeur <= borne, ">": valeur > borne, "<": valeur < borne}[m.group(1)]:
        sys.exit(5)
sys.exit(0)'

deja_conforme_produit() { return 1; }

etape_produit() {
    local declaration lecture='' rc=0 nom source version
    declaration=$(/usr/bin/python3 -I -P -c "$PYPRODUIT" declaration "$DEPOT/$FONCTIONS_SRC") || rc=$?
    if [ "$rc" -ne 0 ]; then
        arreter "$EX_CONFIG" install_err_produit_declaration
    fi
    { read -r nom; read -r source; read -r version; } <<< "$declaration"
    # Une seule commande de lecture : référence et identifiant de l'image du conteneur (docker inspect(1)).
    lecture=$(sudo /usr/bin/docker inspect --format '{{.Config.Image}} {{.Image}}' "$nom" 2> /dev/null) || lecture=''
    rc=0
    /usr/bin/python3 -I -P -c "$PYPRODUIT" comparer "$DEPOT/$FONCTIONS_SRC" <<< "$lecture" > /dev/null || rc=$?
    if [ "$rc" -ne 0 ]; then
        arreter "$EX_CONFIG" install_err_produit "nom=$nom" "source=$source" "version=$version"
    fi
}

verifier_produit() { :; }

# ---------------------------------------------------------------------------
# Étape fonctions (sautable) : pose du dossier des fonctions de Remus sous /usr/local/lib/paresia/remus/fonctions
# (root:root, dossiers 0755, scripts 0755, manifestes 0644, aucun lien symbolique), de façon atomique
# (copie préalable dans la zone de travail, puis mv -T), avec sauvegarde. Un dossier existant différent
# n'est remplacé qu'avec CODE_REMPLACEMENT_CONFIRME=oui ; un fichier d'un autre propriétaire ou aux droits plus
# larges est un refus (78) sans modification. Aucune unité n'est arrêtée ni redémarrée.
# Retour arrière : restauration du dossier sauvegardé (ou retrait s'il n'existait pas).
# ---------------------------------------------------------------------------
fonctions_attributs_conformes() {
    [ -z "$(sudo /usr/bin/find "$FONCTIONS_DST" ! -user root -o -perm /022 | filtre_sortie)" ] \
        && [ -z "$(sudo /usr/bin/find "$FONCTIONS_DST" -type d ! -perm 0755 | filtre_sortie)" ] \
        && [ -z "$(sudo /usr/bin/find "$FONCTIONS_DST" -type f -name '*.toml' ! -perm 0644 | filtre_sortie)" ] \
        && [ -z "$(sudo /usr/bin/find "$FONCTIONS_DST" -type f ! -name '*.toml' ! -perm 0755 | filtre_sortie)" ] \
        && [ -z "$(sudo /usr/bin/find "$FONCTIONS_DST" ! -type d ! -type f | filtre_sortie)" ]
}

fonctions_conformes() {
    existe "$FONCTIONS_DST" && sudo /usr/bin/diff -qr "$DEPOT/$FONCTIONS_SRC" "$FONCTIONS_DST" > /dev/null 2>&1 \
        && fonctions_attributs_conformes
}

deja_conforme_fonctions() {
    if fonctions_conformes; then
        return 0
    fi
    if existe "$FONCTIONS_DST"; then
        if [ -n "$(sudo /usr/bin/find "$FONCTIONS_DST" ! -user root -o -perm /022 | filtre_sortie)" ] \
            || [ "$CODE_REMPLACEMENT_CONFIRME" != oui ]; then
            refuser_difference "$FONCTIONS_DST"
        fi
    fi
    return 1
}

etape_fonctions() {
    local neuf
    if [ -L "$FONCTIONS_DST" ] || [ -n "$(find "$DEPOT/$FONCTIONS_SRC" ! -type d ! -type f -print -quit)" ]; then
        arreter "$EX_CONFIG" install_err_copie_code
    fi
    jeu_pret
    neuf="$TRAVAIL/fonctions-neuf-$JEU"
    sudo /usr/bin/install -d -o root -g root -m 0755 /usr/local/lib/paresia /usr/local/lib/paresia/remus
    sudo /usr/bin/install -d -o root -g root -m 0700 "$neuf"
    sudo /usr/bin/tar -C "$DEPOT/${FONCTIONS_SRC%/*}" --owner=0 --group=0 -cf - fonctions | sudo /usr/bin/tar -C "$neuf" -xf -
    # ATTENTION : chown -R change le propriétaire de la seule copie de travail, posée ensuite d'un bloc.
    attention chown "$neuf"
    sudo /usr/bin/chown -R root:root "$neuf/fonctions"
    sudo /usr/bin/find "$neuf/fonctions" -type d -exec /usr/bin/chmod 0755 {} +
    sudo /usr/bin/find "$neuf/fonctions" -type f -name '*.toml' -exec /usr/bin/chmod 0644 {} +
    sudo /usr/bin/find "$neuf/fonctions" -type f ! -name '*.toml' -exec /usr/bin/chmod 0755 {} +
    sauvegarder_arbre "$FONCTIONS_DST"
    if existe "$FONCTIONS_DST"; then
        # ATTENTION : remplacement du dossier installé, seulement en cas de différence et après sauvegarde.
        dans_jeu "$FONCTIONS_DST" || arreter "$EX_IOERR" install_err_sauvegarde
        attention "mv -T" "$FONCTIONS_DST"
        sudo /usr/bin/mv -T "$FONCTIONS_DST" "$TRAVAIL/fonctions-retire-$JEU"
    fi
    sudo /usr/bin/mv -T "$neuf/fonctions" "$FONCTIONS_DST"
}

verifier_fonctions() {
    controle_attributs "$FONCTIONS_DST" "root:root 755"
    verifie "fonctions:attributs" oui "$(fonctions_attributs_conformes && echo oui || echo non)"
}

# ---------------------------------------------------------------------------
# Étape sudoers (sautable) : politique de l'hôte contrôlée (env_reset, includedir, aucun Defaults
# sur l'environnement), génération sans privilège (runuser -u nobody), visudo -c avant installation,
# contrôles après installation. Aucun droit à chef tant que la table des commandes est vide.
# Retour arrière : restauration puis visudo -c du fichier restauré.
# ---------------------------------------------------------------------------
SUDOERS_REMUS=/etc/sudoers.d/paresia-remus

# controle_politique_sudo : lecture seule ; un arrêt impose une revue manuelle (/etc/sudoers n'est jamais modifié).
# Le fichier généré ne pose aucun Defaults (D80) : il repose sur env_reset (réglage par défaut, sudoers(5),
# Command environment) et sur l'inclusion de /etc/sudoers.d (directive @includedir /etc/sudoers.d). Scénario visé :
# avec env_reset désactivé ou un env_keep large, chef passerait DOCKER_HOST ou DOCKER_CONFIG au docker lancé en
# root par sudo. Le contrôle s'arrête si /etc/sudoers ne contient pas l'inclusion, si un Defaults désactive
# env_reset, mentionne env_keep, env_check, env_delete ou setenv/SETENV (seule exception : la ligne visudo du
# paquet Debian), ou si `sudo -V` mentionne DOCKER_ ou un joker seul.
# IMPORTANT : ce contrôle est nécessaire mais non suffisant. Il ne suit pas les fichiers inclus par @include ou
# @includedir imbriqués : la revue manuelle de tous les fichiers inclus n'est pas facultative et précède
# l'installation. sudo 1.9.10 ou plus : sudoers(5) (POSIX extended regular expressions depuis la 1.9.10 ;
# journal des versions NEWS.gz de sudo, « What's new in Sudo 1.9.10 »). Session de secours conseillée : une
# erreur de syntaxe peut priver de sudo, d'où visudo -c avant installation ; fichier root:root 0440.
controle_politique_sudo() {
    local rc=0 version_sudo
    sudo /usr/bin/test -f /etc/sudoers
    sudo /usr/bin/test -r /etc/sudoers
    if ! sudo /usr/bin/test -d /etc/sudoers.d || ! sudo /usr/bin/test -r /etc/sudoers.d || ! sudo /usr/bin/test -x /etc/sudoers.d; then
        arreter "$EX_CONFIG" install_err_sudo_politique "motif=sudoers.d"
    fi
    if ! sudo /usr/bin/grep -q -E '^[[:space:]]*[@#]includedir[[:space:]]+/etc/sudoers\.d[[:space:]]*$' /etc/sudoers; then
        arreter "$EX_CONFIG" install_err_sudo_politique "motif=includedir"
    fi
    # grep rend 0 (trouvé), 1 (rien) ou 2 (erreur) : seul 1 est accepté.
    sudo /usr/bin/grep -r -n -P '^(?![[:space:]]*#)(?![[:space:]]*Defaults!/usr/sbin/visudo[[:space:]]+env_keep[[:space:]]*\+=[[:space:]]*"SUDO_EDITOR EDITOR VISUAL"[[:space:]]*$).*(Defaults[:!@>]?.*(env_keep|env_check|env_delete)|!env_reset|setenv|SETENV)' /etc/sudoers /etc/sudoers.d > /dev/null || rc=$?
    if [ "$rc" -ne 1 ]; then
        arreter "$EX_CONFIG" install_err_sudo_politique "motif=Defaults"
    fi
    version_sudo=$(sudo /usr/bin/sudo -V)
    if grep -q -E 'DOCKER_|(^|[[:space:]])[*]([[:space:]]|$)' <<< "$version_sudo"; then
        arreter "$EX_CONFIG" install_err_sudo_politique "motif=env_keep"
    fi
}

# controle_sudoers_apres : contrôles après installation (sudo -l -U chef ; refus de docker).
controle_sudoers_apres() {
    local rc=0 liste defauts
    # LC_ALL=C : en-têtes de sudo -l non traduits ; une section absente ou vide est un échec.
    liste=$(sudo /usr/bin/env LC_ALL=C /usr/bin/sudo -n -l -U chef) || rc=$?
    if [ "$rc" -gt 1 ]; then
        arreter "$EX_CONFIG" install_err_sudo_politique "motif=sudo_l"
    fi
    releve_info "sudo-l-chef" "$(printf '%s\n' "$liste" | filtre_sortie)"
    defauts=$(awk '/^Matching Defaults entries for chef/ {d=1; next} d && /^[[:space:]]*$/ {d=0} d' <<< "$liste")
    if [ -z "$defauts" ] && ! grep -q "^User chef is not allowed to run [s]udo on " <<< "$liste"; then   # aucun droit : rien à contrôler
        arreter "$EX_CONFIG" install_err_sudo_politique "motif=Matching Defaults"
    fi
    # Même liste fautive que le contrôle préalable (env_reset positif toléré), plus DOCKER_.
    if grep -q -E 'env_keep|env_check|env_delete|!env_reset|setenv|SETENV|DOCKER_' <<< "$liste"; then
        arreter "$EX_CONFIG" install_err_sudo_politique "motif=chef-defaults"
    fi
    if sudo /usr/bin/sudo -u chef /usr/bin/sudo -n -- /usr/bin/docker ps > /dev/null 2>&1; then
        arreter "$EX_CONFIG" install_err_sudo_politique "motif=docker"
    fi
    # la sortie du journal n'est ni affichée ni journalisée (elle peut porter des lignes d'autres comptes) : elle est
    # capturée, le shell n'en retient que le nombre de lignes, sans tube
    local sortie_journal nombre_lignes=0
    sortie_journal=$(sudo /usr/bin/journalctl --since '10 minutes ago' _COMM=sudo --no-pager || true)
    if [ -n "$sortie_journal" ]; then
        while IFS= read -r _; do
            nombre_lignes=$((nombre_lignes + 1))
        done <<< "$sortie_journal"
    fi
    releve_info "sudo:journal" "$(formater install_nombre_lignes "nombre=$nombre_lignes")"
}

deja_conforme_sudoers() {
    ! a_poser "$DEPOT/$SRC/sudoers.d/paresia-remus" "$SUDOERS_REMUS" 0440
}

etape_sudoers() {
    local temporaire="$TRAVAIL/sudoers-genere"
    maj_arreter_unites
    controle_politique_sudo
    jeu_pret
    sudo /usr/bin/env -i PYTHONPATH=/usr/local/lib/paresia /usr/sbin/runuser -u nobody -- /usr/bin/python3 -P -s -B -m server.remus.sudoers | sudo /usr/bin/tee "$temporaire" > /dev/null
    sudo /usr/bin/diff -- "$DEPOT/$SRC/sudoers.d/paresia-remus" "$temporaire"
    sudo /usr/sbin/visudo -c -f "$temporaire" > /dev/null
    sudo /usr/bin/cat "$temporaire" | releve sudoers-genere
    # ATTENTION : installation de sudoers ; une erreur de syntaxe peut priver de sudo (visudo -c a réussi avant).
    attention install "$SUDOERS_REMUS"
    sauvegarder "$SUDOERS_REMUS"
    sudo /usr/bin/install -o root -g root -m 0440 "$temporaire" /etc/sudoers.d/paresia-remus
}

verifier_sudoers() {
    controle_attributs "$SUDOERS_REMUS" "root:root 440"
    controle_sudoers_apres
}

# ---------------------------------------------------------------------------
# Étape nftables (sautable) : une seule table inet paresia_relais, sans toucher au pare-feu de
# l'hôte ni à Docker ; essai TCP local avant toute activation permanente (celle-ci, sous --activer).
# Retour arrière : disable, stop, suppression de la seule table paresia_relais, restauration.
# ---------------------------------------------------------------------------
NFT_FICHIER=/etc/nftables/paresia-relais.nft
NFT_UNITE=/etc/systemd/system/paresia-nftables.service

table_chargee() {
    sudo /usr/sbin/nft list table inet paresia_relais > /dev/null 2>&1
}

deja_conforme_nftables() {
    local conforme=0
    if [ "$MISE_A_JOUR" = oui ] && existe "$NFT_FICHIER" && existe "$NFT_UNITE"; then
        return 0
    fi
    ! a_poser "$DEPOT/$SRC/nftables/paresia-relais.nft" "$NFT_FICHIER" 0644 || conforme=1
    ! a_poser "$DEPOT/$SRC/systemd/system/paresia-nftables.service" "$NFT_UNITE" 0644 || conforme=1
    table_chargee || conforme=1
    return "$conforme"
}

# essai_tcp_local : serveur temporaire borné sur 127.0.0.1 ; tunnel est refusé immédiatement (ConnectionRefusedError,
# code non nul), nobody réussit (code 0). Si le serveur n'écoute pas ou si nobody échoue, l'essai est invalide : corriger
# puis recommencer ; l'unité n'est pas activée. Les tables Docker et du pare-feu hôte restent inchangées (Docker et
# firewalld ne sont pas touchés) ; seule la table inet paresia_relais est ajoutée.
essai_tcp_local() {
    (
        local attente=0 pid refus
        if [ -n "$(ss -H -ltn "sport = :$PORT_ESSAI")" ]; then
            arreter "$EX_CONFIG" install_err_port_pris "port=$PORT_ESSAI"
        fi
        PORT_ESSAI="$PORT_ESSAI" /usr/bin/python3 - <<'PY' &
import os, socket
with socket.socket() as serveur:
    serveur.settimeout(30)
    serveur.bind(('127.0.0.1', int(os.environ['PORT_ESSAI'])))
    serveur.listen(1)
    connexion, _ = serveur.accept()
    connexion.close()
PY
        pid=$!
        trap 'kill "$pid" 2>/dev/null || true' EXIT
        until [ -n "$(ss -H -ltn "sport = :$PORT_ESSAI")" ]; do
            attente=$((attente + 1))
            if [ "$attente" -gt 50 ]; then
                arreter "$EX_CONFIG" install_err_essai_tcp
            fi
            sleep 0.1
        done
        if refus=$(sudo /usr/sbin/runuser -u tunnel -- /usr/bin/python3 -I -c 'import socket,sys; socket.create_connection(("127.0.0.1",int(sys.argv[1])),3).close()' "$PORT_ESSAI" 2>&1); then
            arreter "$EX_CONFIG" install_err_essai_tcp
        fi
        releve_info "refused:tunnel" "$(printf '%s' "$refus" | tail -n 1 | filtre_sortie)"
        sudo /usr/sbin/runuser -u nobody -- /usr/bin/python3 -I -c 'import socket,sys; socket.create_connection(("127.0.0.1",int(sys.argv[1])),3).close()' "$PORT_ESSAI"
        wait "$pid"
    )
}

etape_nftables() {
    local avant apres retires
    jeu_pret
    sudo /usr/sbin/nft list ruleset | releve nft-avant
    sudo /usr/bin/install -d -o root -g root -m 0755 /etc/nftables
    if a_poser "$DEPOT/$SRC/nftables/paresia-relais.nft" "$NFT_FICHIER" 0644; then
        poser_fichier "$DEPOT/$SRC/nftables/paresia-relais.nft" "$NFT_FICHIER" 0644
    fi
    if a_poser "$DEPOT/$SRC/systemd/system/paresia-nftables.service" "$NFT_UNITE" 0644; then
        if existe "$NFT_UNITE"; then
            refuser_si_active paresia-nftables.service
        fi
        poser_fichier "$DEPOT/$SRC/systemd/system/paresia-nftables.service" "$NFT_UNITE" 0644
    fi
    sudo /usr/sbin/nft -c -f /etc/nftables/paresia-relais.nft
    sudo /usr/bin/systemd-analyze verify /etc/systemd/system/paresia-nftables.service
    # ATTENTION : chargement de règles réseau ; seule notre table est vidée puis chargée, le reste du ruleset est inchangé.
    attention "nft" "paresia_relais"
    sudo /usr/bin/systemctl daemon-reload
    sudo /usr/bin/systemctl start paresia-nftables.service
    sudo /usr/sbin/nft list ruleset | releve nft-apres
    avant=$(outil_q retrouver --releve nft-avant --jeu "$JEU" | cut -f3)
    apres=$(outil_q retrouver --releve nft-apres --jeu "$JEU" | cut -f3)
    # Compteurs (« counter packets N bytes M ») neutralisés : ils changent sans qu'aucune règle change.
    retires=$(/usr/bin/diff -u <(sudo /usr/bin/cat "$avant" | sed -E 's/counter packets [0-9]+ bytes [0-9]+/counter/') <(sudo /usr/bin/cat "$apres" | sed -E 's/counter packets [0-9]+ bytes [0-9]+/counter/') | grep -c -E '^-[^-]' || true)
    verifie "ruleset:removed-lines" 0 "$retires"
    releve_info "nft:table" "$(sudo /usr/sbin/nft list table inet paresia_relais | filtre_sortie)"
    essai_tcp_local
}

verifier_nftables() {
    controle_attributs "$NFT_FICHIER" "root:root 644"
    controle_attributs "$NFT_UNITE" "root:root 644"
    if [ "$MISE_A_JOUR" = oui ]; then
        return 0
    fi
    verifie "table:inet:paresia_relais" loaded "$(table_chargee && echo loaded || echo absent)"
}

# ---------------------------------------------------------------------------
# Étape unites : castor.service et remus.service (copie, daemon-reload, vérification ; rien n'est
# démarré ici). ConfigurationDirectory=paresia::ro exige systemd 257 ou plus (sinon ::ro est retiré).
# /run/sudo doit exister (ReadWritePaths). Une unité active dont le fichier diffère est refusée.
# Retour arrière : restauration des unités, daemon-reload. Le tunnel et son essai de bout en bout relèvent de la
# partie tunnel : ne pas démarrer le tunnel avant elle.
# ---------------------------------------------------------------------------
deja_conforme_unites() {
    local u conforme=0
    if ! sudo /usr/bin/test -d /run/sudo; then
        manque "/run/sudo"
    fi
    for u in "${UNITES_RELAIS[@]}"; do
        ! a_poser "$DEPOT/$SRC/systemd/system/$u.service" "/etc/systemd/system/$u.service" 0644 || conforme=1
    done
    return "$conforme"
}

etape_unites() {
    local u
    maj_arreter_unites
    for u in "${UNITES_RELAIS[@]}"; do
        if a_poser "$DEPOT/$SRC/systemd/system/$u.service" "/etc/systemd/system/$u.service" 0644; then
            if existe "/etc/systemd/system/$u.service"; then
                refuser_si_active "$u.service"
            fi
            poser_fichier "$DEPOT/$SRC/systemd/system/$u.service" "/etc/systemd/system/$u.service" 0644
        fi
    done
    sudo /usr/bin/systemctl daemon-reload
}

verifier_unites() {
    verifie "systemd-analyze verify" "" "$(sudo /usr/bin/systemd-analyze verify castor.service remus.service 2>&1 | grep -E 'castor\.service|remus\.service' | filtre_sortie || true)"
    controle_attributs /etc/paresia "root:root 755"
    controle_attributs /usr/local/lib/paresia "root:root 755"
    verifie "StateDirectory:castor" "StateDirectory=paresia-castor" "$(sudo /usr/bin/systemctl show -p StateDirectory castor.service | filtre_sortie)"
    verifie "StateDirectory:remus" "StateDirectory=paresia-remus" "$(sudo /usr/bin/systemctl show -p StateDirectory remus.service | filtre_sortie)"
    releve_info "/run/sudo" "$(attributs /run/sudo)"
}

# ---------------------------------------------------------------------------
# Étapes castor puis remus : start (jamais enable ici, jamais restart), Castor avant Remus.
# Tout arrêt de Castor remet les feux au rouge ; l'arrêt de Remus interrompt la mise en attente.
# Retour arrière : arrêt de Remus puis de Castor.
# ---------------------------------------------------------------------------
# Résultat attendu de Remus : TimeoutStopUSec équivalent à 150 s (forme d'affichage à relever).
deja_conforme_castor() { ! unite_visee castor.service || unite_active castor.service; }
etape_castor() {
    # ATTENTION : démarrer Castor ; tout arrêt remet tous les feux au rouge.
    maj_avant_demarrage castor.service
    attention "systemctl start" castor.service
    sudo /usr/bin/systemctl start castor.service
    CASTOR_DEMARRE=oui
    maj_apres_demarrage castor.service
}
verifier_castor() {
    local ligne
    if ! unite_visee castor.service; then
        return 0
    fi
    verifie "castor.service" active "$(sudo /usr/bin/systemctl is-active castor.service | filtre_sortie || true)"
    releve_info "status" "$(sudo /usr/bin/systemctl status castor.service --no-pager | filtre_sortie || true)"
    releve_info "journal castor" "$(sudo /usr/bin/journalctl -u castor.service -n 30 --no-pager | filtre_sortie || true)"
    verifie "ss-xl:castor" 2 "$(ss -xl | grep -c '/run/paresia-castor/' || true)"
    for ligne in "/run/paresia-castor paresia-castor:paresia-castor 711" \
        "/var/lib/paresia-castor paresia-castor:paresia-castor 711" \
        "/run/paresia-castor/castor.sock paresia-castor:paresia-castor-tunnel 660" \
        "/run/paresia-castor/castor-state.sock paresia-castor:paresia-castor-etat 660" "/etc/paresia root:root 755"; do
        controle_attributs "${ligne%% *}" "${ligne#* }"
    done
}

deja_conforme_remus() { ! unite_visee remus.service || unite_active remus.service; }
etape_remus() {
    # ATTENTION : démarrer Remus ; tout arrêt interrompt la mise en attente du feu vert (KillMode=mixed).
    maj_avant_demarrage remus.service
    attention "systemctl start" remus.service
    sudo /usr/bin/systemctl start remus.service
    maj_apres_demarrage remus.service
}
verifier_remus() {
    local ligne
    if ! unite_visee remus.service; then
        return 0
    fi
    verifie "remus.service" active "$(sudo /usr/bin/systemctl is-active remus.service | filtre_sortie || true)"
    releve_info "status" "$(sudo /usr/bin/systemctl status remus.service --no-pager | filtre_sortie || true)"
    releve_info "journal remus" "$(sudo /usr/bin/journalctl -u remus.service -n 30 --no-pager | filtre_sortie || true)"
    verifie "ss-xl:remus" 1 "$(ss -xl | grep -c '/run/paresia-remus/' || true)"
    for ligne in "/run/paresia-remus chef:chef 711" "/var/lib/paresia-remus chef:chef 711" "/run/paresia-remus/remus.sock chef:paresia-remus-tunnel 660" "/etc/paresia root:root 755"; do
        controle_attributs "${ligne%% *}" "${ligne#* }"
    done
    verifie "KillMode" "KillMode=mixed" "$(sudo /usr/bin/systemctl show -p KillMode remus.service | filtre_sortie)"
    releve_info "TimeoutStopUSec" "$(sudo /usr/bin/systemctl show -p TimeoutStopUSec remus.service | filtre_sortie)"
}

# ---------------------------------------------------------------------------
# Étape refus_castor : un compte tiers ne peut ouvrir aucune des trois sockets ; essai local de
# Castor sans le tunnel (requêtes jumeaux/1 d'une ligne JSON). Les requêtes passent par la fonction
# jumeaux ; chef lit castor-state.sock avec -g chef -G paresia-castor-etat (runuser(1), options
# réservées à root, d'où sudo). L'essai ouvre puis ferme le feu de la session 1 : il n'est mené
# que si Castor vient d'être démarré par ce passage. Résultat attendu : ping ok, état green, fermeture ok, puis
# l'état de la session 1 (session_closed pendant closed_s puis red : réponse exacte à relever), puis deux refus
# (chef sur castor.sock, tunnel sur castor-state.sock) : PermissionError [Errno 13] Permission denied. Le journal de
# Castor montre, pour la session 1, light_green puis light_closed avec reason valant close.
# Source installée, runuser(1) :
#   `-g, --group` : « The primary group to be used. This option is allowed for the root user only. »
#   `-G, --supp-group` : « Specify a supplementary group. This option is available to the root user only. »
# Ces options sont appliquées par la commande privilégiée sudo.
# ---------------------------------------------------------------------------
jumeaux() {                  # COMPTE SOCKET ACTION
    local -a groupes=()
    if test "$1" = chef && test "$2" = /run/paresia-castor/castor-state.sock; then
        groupes=(-g chef -G paresia-castor-etat)
    fi
    sudo /usr/sbin/runuser -u "$1" "${groupes[@]}" -- /usr/bin/python3 -I -c "import json,secrets,socket,sys; s=socket.socket(socket.AF_UNIX); s.settimeout(3); s.connect(sys.argv[1]); s.sendall(json.dumps({'proto':'jumeaux/1','id':secrets.token_hex(8),'session':1,'action':sys.argv[2],'params':{}}).encode()+b'\n'); print(s.makefile('rb').readline().decode().strip())" "$2" "$3" 2>&1 | tail -n 1 | filtre_sortie
}

# Sous mise à jour, l'essai local qui ouvre puis ferme le feu de la session 1 n'est pas rejoué : seule sa partie en lecture
# seule (verifier_refus_castor) l'est.
deja_conforme_refus_castor() { [ "$CASTOR_DEMARRE" != oui ] || [ "$MISE_A_JOUR" = oui ]; }

etape_refus_castor() {
    local reponse
    # ATTENTION : cet essai ouvre puis ferme le feu de la session 1 de Castor ; sans effet sur une session réelle.
    attention "ping-and-close" "session-1"
    reponse=$(jumeaux tunnel /run/paresia-castor/castor.sock castor/light/ping)
    case $reponse in *'"ok": true'* | *'"ok":true'*) hook alpha_verifie "ping" ok ;; *) ecart "ping" '"ok":true' "$reponse" ;; esac
    reponse=$(jumeaux chef /run/paresia-castor/castor-state.sock castor/light/state)
    case $reponse in *green*) hook alpha_verifie "state:after-ping" green ;; *) ecart "state:after-ping" green "$reponse" ;; esac
    reponse=$(jumeaux tunnel /run/paresia-castor/castor.sock castor/light/close)
    case $reponse in *'"ok": true'* | *'"ok":true'*) hook alpha_verifie "close" ok ;; *) ecart "close" '"ok":true' "$reponse" ;; esac
    releve_info "state:after-close" "$(jumeaux chef /run/paresia-castor/castor-state.sock castor/light/state)"
    releve_info "journal castor" "$(sudo /usr/bin/journalctl -u castor.service -n 30 --no-pager | grep -E 'light_green|light_closed' | filtre_sortie || true)"
}

verifier_refus_castor() {
    local socket sortie
    for socket in /run/paresia-castor/castor.sock /run/paresia-castor/castor-state.sock /run/paresia-remus/remus.sock; do
        if { [ "$socket" = /run/paresia-remus/remus.sock ] && ! unite_visee remus.service; } \
            || { [ "$socket" != /run/paresia-remus/remus.sock ] && ! unite_visee castor.service; }; then
            continue
        fi
        sortie=$(sudo /usr/sbin/runuser -u nobody -- /usr/bin/python3 -I -c "import socket,sys; s=socket.socket(socket.AF_UNIX); s.connect(sys.argv[1])" "$socket" 2>&1 | tail -n 1 | filtre_sortie || true)
        case $sortie in *PermissionError*) hook alpha_verifie "refused:nobody:$socket" PermissionError ;; *) ecart "refused:nobody:$socket" PermissionError "$sortie" ;; esac
    done
    if ! unite_visee castor.service; then
        return 0
    fi
    case $(jumeaux chef /run/paresia-castor/castor.sock castor/light/ping) in *PermissionError*) ;; *) ecart "refused:chef:castor.sock" PermissionError autre ;; esac
    case $(jumeaux tunnel /run/paresia-castor/castor-state.sock castor/light/state) in *PermissionError*) ;; *) ecart "refused:tunnel:castor-state.sock" PermissionError autre ;; esac
}

# ---------------------------------------------------------------------------
# Étape isolation_remus (sautable) : essais réels de l'isolation de Remus (lecture seule ; la
# lecture de isolation-remus.md est un renvoi : décisions et essais repris ici). Les valeurs à
# relever (Seccomp, réponse de sudo -n -l) restent des relevés, jamais des assertions. Table des commandes
# vide : seul un refus est attendu ; l'essai positif d'une commande réelle et l'essai d'arrêt avec une opération
# en cours restent à mener lorsque la table n'est pas vide, avant toute commande de production. Correspondance
# avec les lignes « à vérifier sur la cible » de isolation-remus.md (un écart bloque ; une réponse de sudo -n -l
# autre qu'un mot de passe requis est à relever et à conserver, sans élargir l'isolation) :
#   | CapabilityBoundingSet | CapBnd du bloc de statut | 00000000200000c0 |
#   | ProtectHome | ls -A /proc/PID/root/root | vide |
#   | PrivateTmp | ls -A /proc/PID/root/tmp | vide |
#   | PrivateDevices | ls /proc/PID/root/dev | pseudo-fichiers seulement |
#   | ProtectControlGroups | essai de isolation-remus.md (lecture seule de /sys/fs/cgroup) | aucune écriture possible |
#   | ProtectProc | sudo -n -l ci-dessous | sudo atteint sa politique |
#   | RestrictAddressFamilies | journalctl -u remus.service | aucune erreur de permission |
#   | RestrictNamespaces | commande auditée, table non vide | à mener avec une table non vide |
#   | SystemCallArchitectures | Seccomp du bloc et sudo -n -l | pas de SIGSYS |
#   | SystemCallFilter | Seccomp du bloc et sudo -n -l | pas de SIGSYS |
#   | MemoryDenyWriteExecute | commande auditée, table non vide | à mener avec une table non vide ; directive absente |
#   | ReadWritePaths | sudo -V et stat de /run/sudo | aucune erreur « read-only » |
# ---------------------------------------------------------------------------
deja_conforme_isolation_remus() { return 1; }
etape_isolation_remus() { :; }
verifier_isolation_remus() {
    local pid etat
    if ! unite_visee remus.service; then
        return 0
    fi
    pid=$(systemctl show -p MainPID --value remus.service)
    etat=$(sudo /usr/bin/grep -E '^(NoNewPrivs|CapBnd|CapEff|CapAmb|Seccomp):' "/proc/$pid/status" | filtre_sortie)
    releve_info "/proc/$pid/status" "$etat"
    verifie "NoNewPrivs" "NoNewPrivs:	0" "$(grep '^NoNewPrivs:' <<< "$etat")"
    verifie "CapBnd" "CapBnd:	00000000200000c0" "$(grep '^CapBnd:' <<< "$etat")"
    verifie "CapAmb" "CapAmb:	0000000000000000" "$(grep '^CapAmb:' <<< "$etat")"
    releve_info "systemctl show remus" "$(sudo /usr/bin/systemctl show -p KillMode -p User -p CapabilityBoundingSet -p ReadWritePaths -p ReadOnlyPaths remus.service | filtre_sortie)"
    releve_info "sudo_V" "$(sudo /usr/bin/sudo -V | grep -i -E 'timestamp|version' | filtre_sortie)"
    releve_info "/run/sudo" "$(attributs /run/sudo)"
    # Un dossier à la fois : avec plusieurs arguments, ls affiche « dossier: » même pour un dossier vide.
    verifie "ls-A:proc-root-tmp" "" "$({ sudo /usr/bin/ls -A "/proc/$pid/root/root"; sudo /usr/bin/ls -A "/proc/$pid/root/tmp"; } | filtre_sortie)"
    releve_info "/proc/PID/root/dev" "$(sudo /usr/bin/ls "/proc/$pid/root/dev" | filtre_sortie)"
    releve_info "journal remus" "$(sudo /usr/bin/journalctl -u remus.service -n 50 --no-pager | filtre_sortie || true)"
    # ATTENTION : sudo -n -l en environnement transitoire ; le sudoers installé est atteint, aucune commande de production n'est lancée.
    attention "systemd-run" "sudo_n_l"
    releve_info "systemd-run_sudo_n_l" "$(sudo /usr/bin/systemd-run --wait --pipe --collect \
        -p User=chef -p Group=chef \
        -p 'SupplementaryGroups=paresia-remus-tunnel paresia-castor-etat' \
        -p LimitCORE=0 -p 'CapabilityBoundingSet=CAP_SETUID CAP_SETGID CAP_AUDIT_WRITE' \
        -p AmbientCapabilities= -p ProtectSystem=strict -p ProtectHome=yes -p PrivateTmp=yes \
        -p PrivateDevices=yes -p ProtectKernelTunables=yes -p ProtectKernelModules=yes \
        -p ProtectKernelLogs=yes -p ProtectControlGroups=yes -p ProtectClock=yes \
        -p ProtectHostname=yes -p ProtectProc=invisible -p RestrictAddressFamilies=AF_UNIX \
        -p RestrictNamespaces=yes -p RestrictRealtime=yes -p RestrictSUIDSGID=yes \
        -p LockPersonality=yes -p SystemCallArchitectures=native -p SystemCallFilter=@system-service \
        -p UMask=0077 -p ReadWritePaths=/run/sudo \
        -p 'ReadOnlyPaths=/etc/paresia /usr/local/lib/paresia' \
        /usr/bin/sudo -n -l 2>&1 | filtre_sortie || true)"
}

# ---------------------------------------------------------------------------
# Partie « tunnel » de backend-relais (seulement avec ADRESSE_ADMIN, CLE_PUBLIQUE_TUNNEL et
# EMPREINTE_CLE_TUNNEL). Tant que la table paresia_relais n'est pas chargée, l'accès du compte
# tunnel n'est ouvert que si ACCES_TUNNEL_SANS_NFTABLES=oui (OpenSSH ne peut limiter une
# redirection de socket Unix à un chemin ; seule la règle nftables ferme cette limite).
# ---------------------------------------------------------------------------
SSH_TUNNEL=/etc/ssh/sshd_config.d/50-paresia-tunnel.conf
SSH_ALLOWUSERS=/etc/ssh/sshd_config.d/40-paresia-tunnel-allowusers.conf

sshd_tunnel() {              # FILTRE : valeurs effectives pour tunnel
    sudo /usr/sbin/sshd -T -C user=tunnel,host=backend-admin.example.org,addr=192.0.2.50 | grep -i -E "$1" | filtre_sortie || true
}

ligne_authorized_keys() {
    printf 'restrict,port-forwarding,from="%s",command="/bin/false" %s\n' "$ADRESSE_ADMIN" "$CLE_PUBLIQUE_TUNNEL"
}

deja_conforme_tunnel_releves() {
    if ! table_chargee && [ "$ACCES_TUNNEL_SANS_NFTABLES" != oui ]; then
        arreter "$EX_CONFIG" install_err_acces_tunnel
    fi
    return 1
}
etape_tunnel_releves() {
    releve_info "tunnel-home" "$(sudo /usr/bin/stat -c '%U:%G %a %n' "$REPERTOIRE_TUNNEL" "$REPERTOIRE_TUNNEL/.ssh" | filtre_sortie)"
    releve_info "ls-A:.ssh" "$(sudo /usr/bin/ls -A "$REPERTOIRE_TUNNEL/.ssh" | filtre_sortie)"
    releve_info "passwd -S tunnel" "$(sudo /usr/bin/passwd -S tunnel | filtre_sortie)"
}
verifier_tunnel_releves() {
    controle_attributs "$REPERTOIRE_TUNNEL" "root:root 755"
    controle_attributs "$REPERTOIRE_TUNNEL/.ssh" "root:root 755"
}

# tunnel_authorized_keys : l'empreinte de CLE_PUBLIQUE_TUNNEL doit égaler EMPREINTE_CLE_TUNNEL,
# lue sur backend-admin par un autre canal ; écart = refus, rien n'est écrit.
deja_conforme_tunnel_authorized_keys() {
    local calculee fichier=$REPERTOIRE_TUNNEL/.ssh/authorized_keys
    calculee=$(printf '%s\n' "$CLE_PUBLIQUE_TUNNEL" | sudo /usr/bin/ssh-keygen -lf - | awk 'NR==1 {print $2}' | filtre_sortie)
    if [ "$calculee" != "$EMPREINTE_CLE_TUNNEL" ]; then
        arreter "$EX_CONFIG" install_err_empreinte "attendu=$EMPREINTE_CLE_TUNNEL" "releve=$calculee"
    fi
    if ! existe "$fichier"; then
        return 1
    fi
    if ligne_authorized_keys | sudo /usr/bin/diff -q - "$fichier" > /dev/null 2>&1 && [ "$(attributs "$fichier")" = "root:root 644" ]; then
        return 0
    fi
    if [ "$CODE_REMPLACEMENT_CONFIRME" != oui ]; then
        refuser_difference "$fichier"
    fi
    return 1
}
etape_tunnel_authorized_keys() {
    local fichier=$REPERTOIRE_TUNNEL/.ssh/authorized_keys
    releve_info "sshd-T:tunnel:keys" "$(sshd_tunnel '^(authorizedkeysfile|allowusers|allowgroups|usepam|strictmodes) ')"
    verifie "authorizedkeysfile" "authorizedkeysfile .ssh/authorized_keys .ssh/authorized_keys2" "$(sshd_tunnel '^authorizedkeysfile ')"
    sauvegarder "$fichier"
    # ATTENTION : cette écriture crée authorized_keys du compte tunnel (l'outil en consigne l'absence avant).
    ligne_authorized_keys | sudo /usr/bin/tee "$fichier" > /dev/null
    sudo /usr/bin/chown root:root "$fichier"
    sudo /usr/bin/chmod 0644 "$fichier"
}
verifier_tunnel_authorized_keys() { controle_attributs "$REPERTOIRE_TUNNEL/.ssh/authorized_keys" "root:root 644"; }

# tunnel_sshd : 50-paresia-tunnel.conf (StrictModes yes et PermitUserEnvironment no hors du bloc,
# puis Match User tunnel en dernier). Sous-étape AllowUsers : seulement si une liste existe déjà.
# Un compte ordinaire (nobody) ne doit pas changer de configuration effective, hors StrictModes et
# PermitUserEnvironment. sshd -t, puis reload ssh (jamais restart) sous SESSION_SECOURS=oui.
deja_conforme_tunnel_sshd() {
    ! a_poser "$DEPOT/$SRC/ssh/sshd_config.d/50-paresia-tunnel.conf" "$SSH_TUNNEL" 0644
}

controle_sshd_tunnel() {
    local effectif ligne
    effectif=$(sshd_tunnel '^(allowtcpforwarding|allowstreamlocalforwarding|permitlisten|permittty|x11forwarding|allowagentforwarding|passwordauthentication|authenticationmethods|strictmodes|permituserenvironment) ')
    for ligne in "allowtcpforwarding local" "allowstreamlocalforwarding local" "permitlisten none" "permittty no" \
        "x11forwarding no" "allowagentforwarding no" "passwordauthentication no" "authenticationmethods publickey" \
        "strictmodes yes" "permituserenvironment no"; do
        verifie "sshd -T tunnel : ${ligne% *}" "$ligne" "$(grep -x -i -F "$ligne" <<< "$effectif" || true)"
    done
}

etape_tunnel_sshd() {
    local utilisateurs differences permis
    exiger_session_secours
    if ! sudo /usr/bin/grep -q -i -E '^[[:space:]]*Include[[:space:]]+/etc/ssh/sshd_config\.d/\*\.conf' /etc/ssh/sshd_config; then
        manque "Include sshd_config.d"
    fi
    sudo /usr/sbin/sshd -T -C user=nobody,host=backend-admin.example.org,addr=192.0.2.50 | sudo /usr/bin/tee /run/paresia-installation/ordinaire-avant.txt > /dev/null
    poser_fichier "$DEPOT/$SRC/ssh/sshd_config.d/50-paresia-tunnel.conf" "$SSH_TUNNEL" 0644
    sshd_t_ou_restaurer "$SSH_TUNNEL"
    controle_sshd_tunnel
    sudo /usr/sbin/sshd -T -C user=nobody,host=backend-admin.example.org,addr=192.0.2.50 | sudo /usr/bin/tee /run/paresia-installation/ordinaire-apres.txt > /dev/null
    differences=$(sudo /usr/bin/diff /run/paresia-installation/ordinaire-avant.txt /run/paresia-installation/ordinaire-apres.txt | grep -E '^[<>]' | grep -v -i -E '^[<>] (strictmodes|permituserenvironment) ' | filtre_sortie || true)
    verifie "sshd-T:nobody:diff" "" "$differences"
    utilisateurs=$(sshd_tunnel '^allowusers ')
    if [ -n "$utilisateurs" ] && ! grep -q -E "(^| )tunnel(@$ADRESSE_ADMIN)?( |$)" <<< "$utilisateurs"; then
        # Sous-étape AllowUsers : un fichier complémentaire ajoute tunnel@adresse sans rien retirer.
        sauvegarder "$SSH_ALLOWUSERS"
        printf 'AllowUsers tunnel@%s\n' "$ADRESSE_ADMIN" | sudo /usr/bin/tee /etc/ssh/sshd_config.d/40-paresia-tunnel-allowusers.conf > /dev/null
        sudo /usr/bin/chmod 0644 /etc/ssh/sshd_config.d/40-paresia-tunnel-allowusers.conf
        sshd_t_ou_restaurer "$SSH_ALLOWUSERS" "$SSH_TUNNEL"
        permis=$(sshd_tunnel '^allowusers ')
        verifie "allowusers" "oui" "$([[ $permis == *"tunnel@$ADRESSE_ADMIN"* ]] && echo oui || echo non)"
    fi
    recharger_ssh
}
verifier_tunnel_sshd() { controle_sshd_tunnel; }

# tunnel_compte : le compte tunnel a le shell nologin (D63) et un mot de passe verrouillé ; ce que
# les pages de manuel ne tranchent pas (UsePAM) est relevé, la connexion réelle fait foi.
deja_conforme_tunnel_compte() { return 1; }
etape_tunnel_compte() {
    releve_info "passwd -S tunnel" "$(sudo /usr/bin/passwd -S tunnel | filtre_sortie)"
    releve_info "usepam" "$(sshd_tunnel '^usepam ')"
}
verifier_tunnel_compte() {
    verifie "shell de tunnel" /usr/sbin/nologin "$(getent passwd tunnel | cut -d: -f7)"
}

# ---------------------------------------------------------------------------
# Étape activation (sous --activer seulement) : systemctl enable de castor et remus, et de la table
# nftables si elle est en service, seulement après la conformité de toutes les étapes.
# Retour arrière : systemctl disable.
# ---------------------------------------------------------------------------
UNITES_ACTIVER="castor.service remus.service"
deja_conforme_activation() {
    [ "$(sudo /usr/bin/systemctl is-enabled castor.service remus.service | filtre_sortie | tr '\n' ' ' || true)" = "enabled enabled " ] \
        && { etape_sautee nftables || [ "$(sudo /usr/bin/systemctl is-enabled paresia-nftables.service | filtre_sortie || true)" = enabled ]; }
}
etape_activation() {
    # ATTENTION : systemctl enable modifie le démarrage de la machine ; n'est lancé que si les contrôles sont conformes.
    attention "systemctl enable" "$UNITES_ACTIVER"
    sudo /usr/bin/systemctl enable castor.service remus.service
    if ! etape_sautee nftables; then
        sudo /usr/bin/systemctl enable paresia-nftables.service
    fi
}
verifier_activation() {
    verifie "is-enabled castor remus" "enabled enabled " "$(sudo /usr/bin/systemctl is-enabled castor.service remus.service | filtre_sortie | tr '\n' ' ' || true)"
}

# ---------------------------------------------------------------------------
# Retour arrière : --retour-arriere --jeu <nom> --confirme. Ordre inverse de la pose : arrêt de
# Remus puis de Castor et de la table nftables, restauration de chaque fichier sauvegardé ou marqué
# absent (arrêt au premier code 5), visudo -c, sshd -t puis reload ssh (SESSION_SECOURS=oui),
# daemon-reload, dossiers vides, comptes et groupes créés ici. Idempotent ; jamais userdel -r.
# ---------------------------------------------------------------------------
# pose_complete : tout ce que l'installation ou la mise à jour peut poser, dans l'ordre de pose (POSE).
pose_complete() {
    POSE=(/usr/local/lib/paresia/server /usr/local/lib/paresia/VERSION "$INSTALLE_EMPREINTES"
        /etc/paresia/paresia.conf /etc/paresia/paresia.conf.paresia-nouveau
        /etc/paresia/conf.d/20-relais.conf /etc/paresia/conf.d/20-relais.conf.paresia-nouveau
        "$FONCTIONS_DST" "$SUDOERS_REMUS" "$NFT_FICHIER" "$NFT_UNITE"
        /etc/systemd/system/castor.service /etc/systemd/system/remus.service
        "$REPERTOIRE_TUNNEL/.ssh/authorized_keys" "$SSH_ALLOWUSERS" "$SSH_TUNNEL")
}

retour_arriere() {
    local chemin pose_sshd=non indice
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
    if dans_jeu "$SSH_TUNNEL" || dans_jeu "$SSH_ALLOWUSERS"; then
        pose_sshd=oui
        exiger_session_secours
    fi
    msg install_retour_arret
    if dans_jeu /etc/systemd/system/remus.service; then
        # ATTENTION : l'arrêt de Remus puis de Castor interrompt la mise en attente et remet les feux au rouge.
        attention "systemctl disable" "castor remus"
        sudo /usr/bin/systemctl disable castor.service remus.service
        sudo /usr/bin/systemctl stop remus.service castor.service
    fi
    if dans_jeu "$NFT_UNITE"; then
        # ATTENTION : arrêt et suppression de règles réseau ; seule la table paresia_relais disparaît.
        attention "systemctl stop" paresia-nftables.service
        sudo /usr/bin/systemctl disable paresia-nftables.service
        sudo /usr/bin/systemctl stop paresia-nftables.service
        if table_chargee; then
            sudo /usr/sbin/nft delete table inet paresia_relais
        fi
    fi
    for ((indice = ${#pose[@]} - 1; indice >= 0; indice--)); do
        chemin=${pose[$indice]}
        if restaurer_si_pose "$chemin"; then
            hook alpha_verifie "restored" "$chemin"
        fi
    done
    if existe "$SUDOERS_REMUS"; then
        sudo /usr/sbin/visudo -c -f "$SUDOERS_REMUS"
    fi
    if [ "$pose_sshd" = oui ]; then
        recharger_ssh
    fi
    sudo /usr/bin/systemctl daemon-reload
    for chemin in /var/lib/paresia-castor /var/lib/paresia-remus "$REPERTOIRE_TUNNEL/.ssh" "$REPERTOIRE_TUNNEL" /etc/nftables /usr/local/lib/paresia/remus /usr/local/lib/paresia /etc/paresia/conf.d /etc/paresia; do
        # ATTENTION : rmdir ne retire qu'un dossier vide.
        if sudo /usr/bin/rmdir -- "$chemin" 2> /dev/null; then
            hook alpha_verifie "removed-directory" "$chemin"
        fi
    done
    supprimer_comptes_crees
    msg install_retour_fait
}

principal "$@"
