#!/bin/sh
# =============================================================================
#  journal-legal-pull.sh — copie du journal légal ParesiA de backend-relais vers backend-admin
# -----------------------------------------------------------------------------
#  Lancé chaque minute par journal-legal-pull.timer.
#  - Clé SSH dédiée, bridée côté backend-relais (rrsync -ro, from=192.0.2.50).
#  - --append : seules les nouvelles lignes sont ajoutées ; une modification
#    ou une troncature d'anciennes lignes sur backend-relais n'est pas propagée.
#  - Pas de --delete : la purge de backend-admin est indépendante de celle de
#    backend-relais.
#  - Verrou partagé avec journal-legal-seal.sh : si le scellement est en
#    cours, cette copie est sautée (la suivante a lieu une minute plus tard).
#  - Droits (D22, D24) : après chaque copie réussie, chaque journal non scellé
#    reçoit le mode 0640 puis l'ACL de lecture du compte ACL_USER
#    (chmod PUIS setfacl : un chmod recalcule le masque). Un fichier immuable
#    (scellé) n'est pas retouché. Le dossier garde mode 0700 et ACL par défaut.
#  Échec de copie → « ECHEC_COPIE » dans syslog (tag journal-legal-pull).
#  Échec de droits/ACL → « ECHEC_ACL » dans syslog ; la copie n'est pas
#  interrompue, le code de sortie est non nul, aucun droit n'est élargi.
#
#  Variables à adapter à l'installation (une par ligne, en début de ligne).
#
#  Suivi des versions
#    1.2.1  2026-11-05  D22/D24, première relecture : PATH fixe.
#    1.2.0  2026-11-05  D22/D24 : mode 0640 et ACL de lecture de ACL_USER
#                       après chaque copie ; ECHEC_ACL ; fichier d'erreur de
#                       rsync par mktemp (0600) supprimé par trap ; umask 077 ;
#                       adresses et noms génériques.
#    1.1.0  2026-11-03  Verrou partagé avec le scellement quotidien.
#    1.0.0  2026-11-03  Première version.
# =============================================================================
set -eu
umask 077
PATH="/usr/sbin:/usr/bin:/sbin:/bin"

SOURCE="journalpull@192.0.2.200:/"
DESTINATION="/var/log/paresia/journal-legal/"
SSH_KEY="/root/.ssh/journal_legal_pull"
LOCK_FILE="/run/journal-legal.lock"
LOG_TAG="journal-legal-pull"
ACL_USER="paresia-romulus"
LSATTR_BIN="/usr/bin/lsattr"

acl_errors=0

# Signale un échec de droits/ACL sans interrompre la copie (fermé : rien n'est élargi).
acl_fail() {
    printf 'ECHEC_ACL %s\n' "$*" >&2
    logger -p user.err -t "$LOG_TAG" "ECHEC_ACL $*" 2>/dev/null || true
    acl_errors=1
}

# Fichier immuable ? (0 = oui, 1 = non ou attributs illisibles)
is_immutable() {
    attrs=$("$LSATTR_BIN" -d -- "$1" 2>/dev/null) || return 1
    attrs=${attrs%% *}
    case $attrs in *i*) return 0 ;; *) return 1 ;; esac
}

# chmod PUIS setfacl sur un chemin ; jamais de chmod après le setfacl.
#   $1 chemin  $2 mode  $3 spécification setfacl
set_mode_acl() {
    if ! chmod "$2" -- "$1"; then
        acl_fail "chmod $2 impossible sur $1"
        return 0
    fi
    if ! setfacl -m "$3" -- "$1"; then
        acl_fail "setfacl impossible sur $1 (compte $ACL_USER)"
    fi
    return 0
}

exec 9>"$LOCK_FILE"
flock -n 9 || exit 0

err_file=$(mktemp) || exit 1
trap 'rm -f -- "$err_file"' EXIT
trap 'exit 1' HUP INT TERM

if ! rsync --recursive --times --append --include='journal-*.jsonl' --exclude='*' \
        --timeout=50 \
        -e "ssh -i $SSH_KEY -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=20" \
        "$SOURCE" "$DESTINATION" 2>"$err_file"; then
    logger -p user.err -t "$LOG_TAG" "ECHEC_COPIE : $(tr '\n' ' ' < "$err_file")"
    exit 1
fi

# Dossier : 0700, lecture/traversée et ACL par défaut pour ACL_USER.
set_mode_acl "${DESTINATION%/}" 0700 \
    "u:$ACL_USER:rx,g::---,o::---,d:u::rwx,d:u:$ACL_USER:r,d:g::---,d:o::---"

# Journaux : seuls les noms stricts journal-AAAA-MM-JJ.jsonl (fichiers ordinaires).
for journal_file in "$DESTINATION"journal-*.jsonl; do
    [ -e "$journal_file" ] || continue
    case ${journal_file##*/} in
        journal-[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].jsonl) ;;
        *) continue ;;
    esac
    [ -L "$journal_file" ] && continue
    [ -f "$journal_file" ] || continue
    is_immutable "$journal_file" && continue       # scellé : on ne le retouche pas
    set_mode_acl "$journal_file" 0640 "u:$ACL_USER:r,g::r--,o::---"
done

exit "$acl_errors"
