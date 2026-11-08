#!/bin/sh
# =============================================================================
#  journal-legal-acl.sh — modes et ACL du journal légal ParesiA (backend-admin)
# -----------------------------------------------------------------------------
#  Usage
#    journal-legal-acl.sh --verifier   contrôle (lecture seule) des modes et ACL
#                                      et lecture effective par ACL_USER
#    journal-legal-acl.sh --appliquer  pose les modes et ACL sur l'existant
#
#  Cibles (D22) — compte ACL_USER, lecture seule, par ACL, sans groupe :
#    LOG_ROOT                   root 0700  u:ACL_USER:x
#    JOURNAL_DIR                root 0700  u:ACL_USER:rx   défaut : u:ACL_USER:r
#    journal-AAAA-MM-JJ.jsonl   root 0640  u:ACL_USER:r
#    MANIFEST                   root 0600  u:ACL_USER:r
#    seals/                     root 0700  u:ACL_USER:rx   défaut : u:ACL_USER:r
#    seals/<D>.txt, .txt.ots    root 0600  u:ACL_USER:r
#  Avec une ACL nommée, le groupe affiché par ls/stat est le MASQUE : le
#  contrôle lit donc les entrées de getfacl, jamais seulement les bits de stat.
#
#  --appliquer (état initial de l'installation)
#    Pour chaque élément : chmod PUIS setfacl (D24). Un fichier scellé
#    (immuable, i) ou en ajout seul (a) refuse tout changement de métadonnées :
#    l'attribut est retiré, mode et ACL posés, puis l'attribut rétabli — UN
#    fichier à la fois, rétablissement garanti par trap, même en cas
#    d'interruption. Un élément déjà conforme n'est pas touché. Aucun contenu
#    n'est modifié. Refus si journal-legal-pull ou -seal tourne (verrou).
#    Idempotent. Chaque élément traité est tracé dans syslog.
#  Un rétablissement de +i ou +a qui échoue arrête tout (« ARRÊT », code 1).
#  --verifier contrôle aussi les attributs : MANIFEST « a », journaux listés au
#  MANIFEST et seals/*.txt « i » (après un arrêt brutal, relancer --appliquer
#  puis --verifier).
#  Échec d'ACL → « ECHEC_ACL » (syslog, tag journal-legal-acl) ; aucun droit
#  n'est élargi en repli ; code de sortie non nul.
#
#  Variables à adapter à l'installation (une par ligne, en début de ligne).
#
#  Suivi des versions
#    1.1.0  2026-11-05  D22/D24, première relecture : --appliquer s'arrête (« ARRÊT », code non
#                       nul) dès qu'un rétablissement de +i/+a échoue ; --verifier
#                       contrôle aussi les attributs (MANIFEST a ; journaux
#                       scellés et seals/*.txt i) par lsattr.
#    1.0.0  2026-11-05  D22/D24 : première version.
# =============================================================================
set -eu
umask 077
PATH="/usr/sbin:/usr/bin:/sbin:/bin"

ACL_USER="paresia-romulus"
EXPECTED_OWNER="root"
LOG_ROOT="/var/log/paresia"
JOURNAL_DIR="/var/log/paresia/journal-legal"
MANIFEST="$JOURNAL_DIR/MANIFEST"
SEALS_DIR="$JOURNAL_DIR/seals"
LOCK_FILE="/run/journal-legal.lock"
LOG_TAG="journal-legal-acl"
LSATTR_BIN="/usr/bin/lsattr"

# Famille d'un élément -> mode, spécification setfacl, lignes getfacl attendues.
# Familles : root-dir, journal-dir, file640, file600.
mode_of() {
    case $1 in
        root-dir|journal-dir) printf '0700' ;;
        file640) printf '0640' ;;
        *) printf '0600' ;;
    esac
}

acl_spec_of() {
    case $1 in
        root-dir) printf 'u:%s:x,g::---,o::---' "$ACL_USER" ;;
        journal-dir) printf 'u:%s:rx,g::---,o::---,d:u::rwx,d:u:%s:r,d:g::---,d:o::---' "$ACL_USER" "$ACL_USER" ;;
        file640) printf 'u:%s:r,g::r--,o::---' "$ACL_USER" ;;
        *) printf 'u:%s:r,g::---,o::---' "$ACL_USER" ;;
    esac
}

# Lignes getfacl attendues (une par ligne), selon la famille.
expected_entries_of() {
    case $1 in
        root-dir) printf 'user::rwx\nuser:%s:--x\ngroup::---\nmask::--x\nother::---\n' "$ACL_USER" ;;
        journal-dir) printf 'user::rwx\nuser:%s:r-x\ngroup::---\nmask::r-x\nother::---\ndefault:user::rwx\ndefault:user:%s:r--\ndefault:group::---\ndefault:other::---\n' "$ACL_USER" "$ACL_USER" ;;
        file640) printf 'user::rw-\nuser:%s:r--\ngroup::r--\nmask::r--\nother::---\n' "$ACL_USER" ;;
        *) printf 'user::rw-\nuser:%s:r--\ngroup::---\nmask::r--\nother::---\n' "$ACL_USER" ;;
    esac
}

say() { printf '%s\n' "$*"; logger -t "$LOG_TAG" "$*" 2>/dev/null || true; }

acl_fail() {
    printf 'ECHEC_ACL %s\n' "$*" >&2
    logger -p user.err -t "$LOG_TAG" "ECHEC_ACL $*" 2>/dev/null || true
}

# Liste des éléments à traiter : « famille<TAB>chemin », un par ligne.
# Seuls les noms stricts et les fichiers ordinaires (jamais de lien) sont retenus.
list_targets() {
    printf 'root-dir\t%s\n' "$LOG_ROOT"
    printf 'journal-dir\t%s\n' "$JOURNAL_DIR"
    for f in "$JOURNAL_DIR"/journal-*.jsonl; do
        [ -e "$f" ] || [ -L "$f" ] || continue
        case ${f##*/} in
            journal-[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].jsonl) ;;
            *) continue ;;
        esac
        [ -L "$f" ] && continue
        [ -f "$f" ] && printf 'file640\t%s\n' "$f"
    done
    [ -f "$MANIFEST" ] && [ ! -L "$MANIFEST" ] && printf 'file600\t%s\n' "$MANIFEST"
    if [ -d "$SEALS_DIR" ] && [ ! -L "$SEALS_DIR" ]; then
        printf 'journal-dir\t%s\n' "$SEALS_DIR"
        for f in "$SEALS_DIR"/*.txt "$SEALS_DIR"/*.txt.ots; do
            [ -e "$f" ] || [ -L "$f" ] || continue
            case ${f##*/} in
                [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].txt|[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].txt.ots) ;;
                *) continue ;;
            esac
            [ -L "$f" ] && continue
            [ -f "$f" ] && printf 'file600\t%s\n' "$f"
        done
    fi
    return 0
}

# Entrées getfacl normalisées (sans commentaire ni espaces de fin).
normalized_acl() {
    getfacl --absolute-names --omit-header -- "$1" 2>/dev/null \
        | sed -e 's/[[:space:]]*#.*$//' -e 's/[[:space:]]*$//' -e '/^$/d'
}

# Contrôle de conformité d'un élément ; messages « ERREUR … » sur la sortie
# standard, un par défaut. Code 0 si conforme.
#   $1 famille  $2 chemin
check_target() {
    ct_family=$1; ct_path=$2; ct_errors=0
    if [ ! -e "$ct_path" ]; then
        echo "ERREUR absent : $ct_path"
        return 1
    fi
    ct_owner=$(stat -c %U -- "$ct_path" 2>/dev/null) || ct_owner="?"
    if [ "$ct_owner" != "$EXPECTED_OWNER" ]; then
        echo "ERREUR propriétaire $ct_owner au lieu de $EXPECTED_OWNER : $ct_path"
        ct_errors=$((ct_errors + 1))
    fi
    ct_acl=$(normalized_acl "$ct_path") || ct_acl=""
    if [ -z "$ct_acl" ]; then
        echo "ERREUR ACL illisible : $ct_path"
        return 1
    fi
    ct_expected=$(expected_entries_of "$ct_family")
    # Entrées attendues absentes.
    while IFS= read -r wanted; do
        printf '%s\n' "$ct_acl" | grep -Fxq -- "$wanted" \
            || { echo "ERREUR entrée ACL manquante « $wanted » : $ct_path"; ct_errors=$((ct_errors + 1)); }
    done <<EOT
$ct_expected
EOT
    # Entrées en trop : toute entrée nommée ou par défaut non attendue.
    while IFS= read -r found; do
        [ -n "$found" ] || continue
        case $found in
            mask::*|default:mask::*) continue ;;                 # recalculés par setfacl
            user::*|group::*|other::*) continue ;;               # contrôlés par les entrées attendues
        esac
        printf '%s\n' "$ct_expected" | grep -Fxq -- "$found" \
            || { echo "ERREUR entrée ACL non prévue « $found » : $ct_path"; ct_errors=$((ct_errors + 1)); }
    done <<EOT
$ct_acl
EOT
    [ "$ct_errors" -eq 0 ]
}

# Exécute une commande en tant que ACL_USER (lecture effective).
as_user() { runuser -u "$ACL_USER" -- "$@" >/dev/null 2>&1; }

# ---------------------------------------------------------------------------
#  --verifier : aucune écriture
# ---------------------------------------------------------------------------
read_test() {
    # $1 description  $2... commande lancée sous ACL_USER
    rt_label=$1; shift
    if as_user "$@"; then
        echo "OK      lecture par $ACL_USER : $rt_label"
        return 0
    fi
    echo "ERREUR lecture par $ACL_USER impossible : $rt_label"
    return 1
}

last_match() { # dernier élément existant d'une liste de chemins (ordre alphabétique)
    lm_last=""
    for lm_f in "$@"; do [ -e "$lm_f" ] && lm_last=$lm_f; done
    printf '%s' "$lm_last"
}

# Contrôle des attributs (lsattr) : $1 chemin, $2 lettre attendue (i ou a).
check_attr() {
    ca_path=$1; ca_letter=$2
    if ! ca_out=$("$LSATTR_BIN" -d -- "$ca_path" 2>/dev/null); then
        echo "ERREUR attributs illisibles : $ca_path"
        return 1
    fi
    ca_out=${ca_out%% *}
    case $ca_out in
        *"$ca_letter"*) echo "OK      attribut $ca_letter présent : $ca_path"; return 0 ;;
    esac
    echo "ERREUR attribut $ca_letter absent : $ca_path"
    return 1
}

# Attributs attendus : MANIFEST « a », journaux inscrits au MANIFEST et
# seals/*.txt « i ». Retourne le nombre d'erreurs sur la sortie d'état.
check_attributes() {
    cas_errors=0
    if [ -f "$MANIFEST" ] && [ ! -L "$MANIFEST" ]; then
        check_attr "$MANIFEST" a || cas_errors=$((cas_errors + 1))
        while IFS=' ' read -r cas_day cas_hash _; do
            [ -n "$cas_day" ] || continue
            [ "$cas_hash" != "ABSENT" ] || continue
            case $cas_day in
                [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]) ;;
                *) echo "ERREUR ligne de registre invalide : $MANIFEST"; cas_errors=$((cas_errors + 1)); continue ;;
            esac
            cas_file="$JOURNAL_DIR/journal-$cas_day.jsonl"
            if [ -f "$cas_file" ] && [ ! -L "$cas_file" ]; then
                check_attr "$cas_file" i || cas_errors=$((cas_errors + 1))
            else
                echo "ERREUR journal inscrit au registre absent : $cas_file"
                cas_errors=$((cas_errors + 1))
            fi
        done < "$MANIFEST"
    fi
    if [ -d "$SEALS_DIR" ] && [ ! -L "$SEALS_DIR" ]; then
        for cas_f in "$SEALS_DIR"/*.txt; do
            [ -e "$cas_f" ] || continue
            case ${cas_f##*/} in
                [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].txt) ;;
                *) continue ;;
            esac
            [ -L "$cas_f" ] && continue
            check_attr "$cas_f" i || cas_errors=$((cas_errors + 1))
        done
    fi
    return "$cas_errors"
}

verifier_main() {
    errors=0
    # 1. Entrées ACL.
    targets=$(list_targets)
    while IFS="$(printf '\t')" read -r family path; do
        [ -n "$path" ] || continue
        if msgs=$(check_target "$family" "$path"); then
            echo "OK      droits et ACL conformes : $path"
        else
            printf '%s\n' "$msgs"
            errors=$((errors + 1))
        fi
    done <<EOT
$targets
EOT
    [ -e "$MANIFEST" ] || echo "OK      MANIFEST absent (pas encore créé) : $MANIFEST"
    [ -d "$SEALS_DIR" ] || echo "OK      seals/ absent (pas encore créé) : $SEALS_DIR"
    # 1 bis. Attributs i et a (lsattr). Le
    # code de retour de check_attributes est le nombre d'erreurs.
    attr_msgs=$(check_attributes) && attr_n=0 || attr_n=$?
    [ -z "$attr_msgs" ] || printf '%s\n' "$attr_msgs"
    errors=$((errors + attr_n))
    # 2. Lecture effective par ACL_USER.
    read_test "traversée de $LOG_ROOT" test -x "$LOG_ROOT" || errors=$((errors + 1))
    read_test "liste de $JOURNAL_DIR" ls -- "$JOURNAL_DIR" || errors=$((errors + 1))
    [ ! -d "$SEALS_DIR" ] || read_test "liste de $SEALS_DIR" ls -- "$SEALS_DIR" || errors=$((errors + 1))
    last_journal=$(last_match "$JOURNAL_DIR"/journal-[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].jsonl)
    if [ -n "$last_journal" ]; then
        read_test "première ligne de $last_journal" head -n 1 -- "$last_journal" || errors=$((errors + 1))
    else
        echo "OK      aucun journal présent (lecture d'un journal non testée)"
    fi
    if [ -e "$MANIFEST" ]; then
        read_test "première ligne de $MANIFEST" head -n 1 -- "$MANIFEST" || errors=$((errors + 1))
    fi
    last_seal=$(last_match "$SEALS_DIR"/[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].txt)
    if [ -n "$last_seal" ]; then
        read_test "première ligne de $last_seal" head -n 1 -- "$last_seal" || errors=$((errors + 1))
    fi
    last_ots=$(last_match "$SEALS_DIR"/[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].txt.ots)
    if [ -n "$last_ots" ]; then
        read_test "lecture de $last_ots" test -r "$last_ots" || errors=$((errors + 1))
    fi
    if [ "$errors" -eq 0 ]; then
        echo "RÉSULTAT : conforme"
        return 0
    fi
    echo "RÉSULTAT : $errors erreur(s)"
    return 1
}

# ---------------------------------------------------------------------------
#  --appliquer : un fichier à la fois, rétablissement des attributs par trap
# ---------------------------------------------------------------------------
restore_path=""
restore_i=0
restore_a=0

restore_attrs() {
    [ -n "$restore_path" ] || return 0
    ra_path=$restore_path
    if [ "$restore_i" -eq 1 ]; then
        chattr +i -- "$ra_path" || { acl_fail "rétablissement de +i IMPOSSIBLE sur $ra_path : à faire à la main"; restore_failed=1; }
    fi
    if [ "$restore_a" -eq 1 ]; then
        chattr +a -- "$ra_path" || { acl_fail "rétablissement de +a IMPOSSIBLE sur $ra_path : à faire à la main"; restore_failed=1; }
    fi
    restore_path=""; restore_i=0; restore_a=0
    [ "$restore_failed" -eq 0 ]
}

restore_failed=0
# shellcheck disable=SC2317  # appelée par trap
on_exit() {
    restore_attrs || true
    if [ "$restore_failed" -ne 0 ]; then exit 1; fi
}

# Attributs d'un chemin : positionne cur_i et cur_a (0/1) ; échec si illisibles.
read_attrs() {
    ra_out=$("$LSATTR_BIN" -d -- "$1" 2>/dev/null) || return 1
    ra_out=${ra_out%% *}
    cur_i=0; cur_a=0
    case $ra_out in *i*) cur_i=1 ;; esac
    case $ra_out in *a*) cur_a=1 ;; esac
    return 0
}

apply_one() {
    ao_family=$1; ao_path=$2
    if check_target "$ao_family" "$ao_path" >/dev/null 2>&1; then
        say "INCHANGE $ao_path (déjà conforme)"
        return 0
    fi
    read_attrs "$ao_path" || { acl_fail "attributs illisibles : $ao_path (élément ignoré)"; return 1; }
    ao_status=0
    # On note ce qu'il faudra rétablir AVANT de retirer quoi que ce soit.
    restore_path=$ao_path; restore_i=$cur_i; restore_a=$cur_a
    if [ "$cur_i" -eq 1 ]; then
        chattr -i -- "$ao_path" || { acl_fail "retrait de +i impossible sur $ao_path"; restore_attrs || true; return 1; }
    fi
    if [ "$cur_a" -eq 1 ]; then
        chattr -a -- "$ao_path" || { acl_fail "retrait de +a impossible sur $ao_path"; restore_attrs || true; return 1; }
    fi
    if chmod "$(mode_of "$ao_family")" -- "$ao_path"; then
        if ! setfacl -b -- "$ao_path" 2>/dev/null; then ao_status=1; fi
        if [ "$ao_status" -eq 0 ] && ! setfacl -m "$(acl_spec_of "$ao_family")" -- "$ao_path"; then
            ao_status=1
        fi
        [ "$ao_status" -eq 0 ] || acl_fail "setfacl impossible sur $ao_path (compte $ACL_USER)"
    else
        ao_status=1
        acl_fail "chmod impossible sur $ao_path"
    fi
    restore_attrs || true
    if [ "$ao_status" -eq 0 ]; then say "TRAITE $ao_path"; fi
    return "$ao_status"
}

appliquer_main() {
    exec 9>"$LOCK_FILE"
    if ! flock -n 9; then
        printf 'REFUS : journal-legal-pull ou journal-legal-seal est en cours (verrou %s)\n' "$LOCK_FILE" >&2
        return 1
    fi
    trap 'exit 130' INT
    trap 'exit 143' HUP TERM
    trap on_exit EXIT
    failures=0
    targets=$(list_targets)
    while IFS="$(printf '\t')" read -r family path; do
        [ -n "$path" ] || continue
        apply_one "$family" "$path" || failures=$((failures + 1))
        if [ "$restore_failed" -ne 0 ]; then
            echo "ARRÊT : rétablissement d'attribut impossible sur $path ; aucun autre fichier n'est traité" >&2
            return 1
        fi
    done <<EOT
$targets
EOT
    if [ "$failures" -eq 0 ]; then
        echo "RÉSULTAT : modes et ACL appliqués"
        return 0
    fi
    echo "RÉSULTAT : $failures élément(s) en échec"
    return 1
}

case ${1:-} in
    --verifier)  [ $# -eq 1 ] || { echo "usage : $0 --verifier | --appliquer" >&2; exit 2; }
                 if verifier_main; then exit 0; else exit 1; fi ;;
    --appliquer) [ $# -eq 1 ] || { echo "usage : $0 --verifier | --appliquer" >&2; exit 2; }
                 if appliquer_main; then exit 0; else exit 1; fi ;;
    *) echo "usage : $0 --verifier | --appliquer" >&2; exit 2 ;;
esac
