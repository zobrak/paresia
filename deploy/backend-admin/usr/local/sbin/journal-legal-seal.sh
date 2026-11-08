#!/bin/sh
# =============================================================================
#  journal-legal-seal.sh — scellement quotidien du journal légal ParesiA (backend-admin)
# -----------------------------------------------------------------------------
#  Usage
#    journal-legal-seal.sh               scelle toutes les journées non encore
#                                        scellées, jusqu'à la veille (UTC)
#    journal-legal-seal.sh AAAA-MM-JJ    scelle uniquement la journée indiquée
#    journal-legal-seal.sh --verifier    vérifie tout le registre (lecture seule)
#    journal-legal-seal.sh --horodater   horodatage OpenTimestamps seul
#
#  Scellement d'une journée D
#    1. dernière copie depuis backend-relais (rsync --append, sous verrou partagé avec
#       journal-legal-pull.sh) ;
#    2. contrôle que la copie de backend-admin est identique à l'original de backend-relais
#       (sommes de contrôle rsync) ; divergence → ECHEC_SCELLEMENT, rien n'est
#       scellé ni écrasé ;
#    3. empreinte SHA-256 du fichier, chaînée avec la ligne précédente du
#       registre MANIFEST :
#         chaine = sha256("<chaine_precedente> <D> <sha256_fichier> <taille>")
#       Journée sans publication : sha256_fichier = ABSENT, taille = 0 ;
#    4. fichier rendu immuable (chattr +i) ; registre en ajout seul (chattr +a).
#
#  Horodatage OpenTimestamps (après chaque passage)
#    Pour chaque journée inscrite au registre :
#      seals/<D>.txt      copie exacte de sa ligne du registre (immuable) ;
#      seals/<D>.txt.ots  preuve OpenTimestamps (seule l'empreinte part sur
#                         Internet), complétée aux passages suivants puis
#                         rendue immuable une fois ancrée dans Bitcoin.
#    Un échec d'horodatage n'empêche pas le scellement : il est retenté au
#    passage suivant. Preuve encore incomplète après 3 jours → ECHEC_HORODATAGE.
#
#  Format d'une ligne de MANIFEST
#    <D> <sha256_fichier|ABSENT> <taille> <chaine_precedente> <chaine>
#
#  Échecs signalés dans syslog par « ECHEC_SCELLEMENT » (tag journal-legal-seal).
#
#  Rattrapage (sans argument)
#    Les journées sont scellées dans l'ordre chronologique, de la journée qui
#    suit la dernière inscrite au registre jusqu'à la veille. Registre vide :
#    départ à la plus ancienne journée présente sur backend-admin. Au premier échec,
#    le script s'arrête sans passer aux journées suivantes (pas de trou dans
#    la chaîne) ; la journée sera retentée au passage suivant.
#
#  Droits et ACL (D22, D24)
#    Le compte ACL_USER (Romulus) lit le journal légal par ACL, en lecture seule,
#    sans groupe. Chaque chmod est suivi d'un setfacl (un chmod recalcule le
#    masque et neutraliserait l'ACL), puis seulement d'un éventuel chattr :
#    un fichier immuable (i) ou en ajout seul (a) n'accepte plus de
#    modification de ses métadonnées (chattr(1)), donc de son ACL.
#    Cibles : journaux 0640, MANIFEST 0600, seals/ 0700, seals/<D>.txt et
#    seals/<D>.txt.ots 0600, plus l'entrée u:ACL_USER:r (rx sur les dossiers).
#    Échec d'ACL → « ECHEC_ACL » dans syslog ; le scellement continue, le code
#    de sortie est non nul ; aucun droit n'est élargi en repli.
#    --verifier est utilisable par ACL_USER : l'état « en attente » ou
#    « ancré » d'une preuve est lu par lsattr (immuable), non par le test
#    d'écriture, qui dépend de l'identité de l'utilisateur.
#
#  Variables à adapter à l'installation (une par ligne, en début de ligne).
#
#  Suivi des versions
#    1.3.0  2026-11-05  D22/D24 : modes et ACL explicites (chmod puis
#                       setfacl avant chattr), ECHEC_ACL, --verifier sans
#                       privilège (lsattr au lieu de [ -w ], erreur explicite
#                       si un fichier est illisible), journal 0640 avant
#                       chattr +i, umask 077, adresses et noms génériques.
#                       Formats et comportements de scellement inchangés.
#    1.2.0  2026-11-03  Horodatage OpenTimestamps des lignes du registre.
#    1.1.0  2026-11-03  Rattrapage automatique des journées non scellées.
#    1.0.0  2026-11-03  Première version.
# =============================================================================
set -eu
umask 077
PATH="/usr/sbin:/usr/bin:/sbin:/bin"

JOURNAL_DIR="/var/log/paresia/journal-legal"
MANIFEST="$JOURNAL_DIR/MANIFEST"
SOURCE="journalpull@192.0.2.200:/"
SSH_KEY="/root/.ssh/journal_legal_pull"
LOCK_FILE="/run/journal-legal.lock"
LOG_TAG="journal-legal-seal"
SEALS_DIR="$JOURNAL_DIR/seals"
OTS_BIN="/opt/opentimestamps/bin/ots"
OTS_MAX_PENDING_DAYS=3
ACL_USER="paresia-romulus"
LSATTR_BIN="/usr/bin/lsattr"
GENESIS="0000000000000000000000000000000000000000000000000000000000000000"
SSH_CMD="ssh -i $SSH_KEY -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=20"

say()  { printf '%s\n' "$*"; logger -t "$LOG_TAG" "$*" 2>/dev/null || true; }
fail() { printf 'ECHEC_SCELLEMENT %s\n' "$*" >&2
         logger -p user.err -t "$LOG_TAG" "ECHEC_SCELLEMENT $*" 2>/dev/null || true
         exit 1; }

warn() { printf 'ECHEC_HORODATAGE %s\n' "$*" >&2
         logger -p user.warning -t "$LOG_TAG" "ECHEC_HORODATAGE $*" 2>/dev/null || true; }

acl_errors=0

# Signale un échec de droits/ACL sans interrompre le scellement (fermé : rien n'est élargi).
acl_fail() { printf 'ECHEC_ACL %s\n' "$*" >&2
             logger -p user.err -t "$LOG_TAG" "ECHEC_ACL $*" 2>/dev/null || true
             acl_errors=1; }

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

# Attribut immuable : 0 = posé, 1 = non posé, 2 = attributs illisibles.
immutable_state() {
    attrs=$("$LSATTR_BIN" -d -- "$1" 2>/dev/null) || return 2
    attrs=${attrs%% *}
    case $attrs in *i*) return 0 ;; *) return 1 ;; esac
}

sha256_of_text() { printf '%s' "$1" | sha256sum | cut -d' ' -f1; }

last_chain() {
    if [ -s "$MANIFEST" ]; then tail -n 1 "$MANIFEST" | cut -d' ' -f5
    else printf '%s' "$GENESIS"; fi
}

# ---------------------------------------------------------------------------
#  Vérification complète du registre (lecture seule)
# ---------------------------------------------------------------------------
verify_manifest() {
    if [ ! -x "$JOURNAL_DIR" ] || { [ -e "$MANIFEST" ] && [ ! -r "$MANIFEST" ]; }; then
        echo "ERREUR lecture impossible : $MANIFEST (droits ou ACL manquants)"
        echo "RÉSULTAT : 1 erreur(s)"
        return 1
    fi
    [ -s "$MANIFEST" ] || { echo "registre vide ou absent : $MANIFEST"; return 0; }
    expected_prev="$GENESIS"; errors=0; line_no=0
    while IFS=' ' read -r day file_hash size prev chain; do
        line_no=$((line_no + 1))
        line_errors=0
        if [ "$prev" != "$expected_prev" ]; then
            echo "ERREUR ligne $line_no ($day) : chaîne rompue (précédent attendu $expected_prev)"
            line_errors=$((line_errors + 1))
        fi
        recomputed=$(sha256_of_text "$prev $day $file_hash $size")
        if [ "$recomputed" != "$chain" ]; then
            echo "ERREUR ligne $line_no ($day) : ligne du registre modifiée (empreinte de chaîne incorrecte)"
            line_errors=$((line_errors + 1))
        fi
        journal_file="$JOURNAL_DIR/journal-$day.jsonl"
        status="aucune publication ce jour-là"
        if [ "$file_hash" != "ABSENT" ]; then
            if [ -e "$journal_file" ] && [ ! -r "$journal_file" ]; then
                echo "ERREUR ligne $line_no ($day) : lecture impossible de $journal_file (droits ou ACL manquants)"
                line_errors=$((line_errors + 1))
                status="fichier illisible"
            elif [ -e "$journal_file" ]; then
                actual=$(sha256sum "$journal_file" | cut -d' ' -f1)
                if [ "$actual" != "$file_hash" ]; then
                    echo "ERREUR ligne $line_no ($day) : fichier modifié depuis le scellement"
                    line_errors=$((line_errors + 1))
                fi
                status="fichier et chaîne intègres"
            else
                status="chaîne intègre (fichier purgé)"
            fi
        fi
        seal_copy="$SEALS_DIR/$day.txt"
        if [ -e "$seal_copy" ] && [ ! -r "$seal_copy" ]; then
            echo "ERREUR ligne $line_no ($day) : lecture impossible de seals/$day.txt (droits ou ACL manquants)"
            line_errors=$((line_errors + 1))
        elif [ -e "$seal_copy" ] && [ "$(cat "$seal_copy")" != "$day $file_hash $size $prev $chain" ]; then
            echo "ERREUR ligne $line_no ($day) : la copie horodatée seals/$day.txt ne correspond pas au registre"
            line_errors=$((line_errors + 1))
        fi
        if [ -e "$seal_copy.ots" ]; then
            ots_state=0
            immutable_state "$seal_copy.ots" || ots_state=$?
            case $ots_state in
                0) status="$status ; horodatage ancré" ;;
                1) status="$status ; horodatage en attente" ;;
                *) echo "ERREUR ligne $line_no ($day) : attributs illisibles pour seals/$day.txt.ots (droits ou ACL manquants)"
                   line_errors=$((line_errors + 1)) ;;
            esac
        fi
        [ "$line_errors" -eq 0 ] && echo "OK      $day  $status"
        errors=$((errors + line_errors))
        expected_prev="$chain"
    done < "$MANIFEST"
    if [ "$errors" -eq 0 ]; then echo "RÉSULTAT : registre intègre ($line_no journées)"; return 0
    else echo "RÉSULTAT : $errors erreur(s)"; return 1; fi
}

if [ "${1:-}" = "--verifier" ]; then
    verify_manifest
    exit $?
fi

# ---------------------------------------------------------------------------
#  Scellement d'une journée (appelé sous verrou)
# ---------------------------------------------------------------------------
seal_one_day() {
    seal_day="$1"
    file_name="journal-$seal_day.jsonl"
    journal_file="$JOURNAL_DIR/$file_name"

    if [ -s "$MANIFEST" ] && grep -q "^$seal_day " "$MANIFEST"; then
        say "$seal_day déjà scellée : rien à faire"
        return 0
    fi

    # 1. Existence sur backend-relais
    if rsync --list-only -e "$SSH_CMD" "$SOURCE$file_name" >/dev/null 2>&1; then
        exists_on_relay=1
    else
        # Distinguer « pas de fichier » d'une panne de connexion.
        rsync --list-only -e "$SSH_CMD" "$SOURCE" >/dev/null 2>&1 \
            || fail "backend-relais injoignable pour $seal_day"
        exists_on_relay=0
    fi

    if [ "$exists_on_relay" -eq 1 ]; then
        # 2. Dernière copie, puis contrôle d'identité par sommes de contrôle.
        rsync --times --append -e "$SSH_CMD" "$SOURCE$file_name" "$JOURNAL_DIR/" \
            || fail "dernière copie de $file_name impossible"
        differences=$(rsync --dry-run --checksum --itemize-changes -e "$SSH_CMD" \
                      "$SOURCE$file_name" "$JOURNAL_DIR/") \
            || fail "comparaison de $file_name impossible"
        [ -z "$differences" ] || fail "$file_name diffère entre backend-relais et backend-admin : $differences"
        file_hash=$(sha256sum "$journal_file" | cut -d' ' -f1)
        file_size=$(stat -c %s "$journal_file")
    else
        [ ! -e "$journal_file" ] || fail "$file_name existe sur backend-admin mais plus sur backend-relais"
        file_hash="ABSENT"; file_size=0
    fi

    # 3. Chaînage et inscription au registre.
    previous_chain=$(last_chain)
    chain=$(sha256_of_text "$previous_chain $seal_day $file_hash $file_size")
    if [ ! -e "$MANIFEST" ]; then
        : > "$MANIFEST"
        set_mode_acl "$MANIFEST" 0600 "u:$ACL_USER:r,g::---,o::---"
    fi
    # setfacl AVANT chattr +a : un fichier en ajout seul n'accepte plus de changement d'ACL.
    chattr +a -- "$MANIFEST" 2>/dev/null || true      # registre en ajout seul (idempotent)
    printf '%s %s %s %s %s\n' "$seal_day" "$file_hash" "$file_size" "$previous_chain" "$chain" >> "$MANIFEST"

    # 4. Immuabilité du fichier scellé.
    if [ "$file_hash" != "ABSENT" ]; then
        set_mode_acl "$journal_file" 0640 "u:$ACL_USER:r,g::r--,o::---"
        chattr +i -- "$journal_file" || fail "chattr +i impossible sur $journal_file (scellement inscrit au registre)"
    fi

    say "SCELLE $seal_day fichier=$file_hash taille=$file_size chaine=$chain"
}

day_number() { printf '%s' "$1" | tr -d '-'; }

# ---------------------------------------------------------------------------
#  Horodatage OpenTimestamps des lignes du registre (jamais bloquant)
# ---------------------------------------------------------------------------
timestamp_manifest() {
    [ -s "$MANIFEST" ] || return 0
    [ -x "$OTS_BIN" ] || { warn "client OpenTimestamps absent : $OTS_BIN"; return 0; }
    if [ ! -d "$SEALS_DIR" ]; then
        mkdir -p -- "$SEALS_DIR"
        set_mode_acl "$SEALS_DIR" 0700 \
            "u:$ACL_USER:rx,g::---,o::---,d:u::rwx,d:u:$ACL_USER:r,d:g::---,d:o::---"
    fi
    pending_limit=$(date -u -d "$OTS_MAX_PENDING_DAYS days ago" +%Y%m%d)

    while IFS= read -r manifest_line; do
        day=${manifest_line%% *}
        seal_copy="$SEALS_DIR/$day.txt"

        # Copie exacte de la ligne du registre, rendue immuable.
        if [ ! -e "$seal_copy" ]; then
            printf '%s' "$manifest_line" > "$seal_copy"
            set_mode_acl "$seal_copy" 0600 "u:$ACL_USER:r,g::---,o::---"
            chattr +i -- "$seal_copy" 2>/dev/null || true
        fi

        # Première soumission.
        if [ ! -e "$seal_copy.ots" ]; then
            if timeout 120 "$OTS_BIN" stamp "$seal_copy" </dev/null >/dev/null 2>&1; then
                set_mode_acl "$seal_copy.ots" 0600 "u:$ACL_USER:r,g::---,o::---"
                say "HORODATAGE_SOUMIS $day"
            else
                rm -f "$seal_copy.ots"
                warn "soumission impossible pour $day (nouvel essai au prochain passage)"
            fi
            continue
        fi

        # Preuve déjà ancrée (immuable) : rien à faire.
        ots_state=0
        immutable_state "$seal_copy.ots" || ots_state=$?
        [ "$ots_state" -eq 0 ] && continue

        # Preuve en attente : tentative de complétion.
        rm -f "$seal_copy.ots.bak"
        if timeout 120 "$OTS_BIN" upgrade "$seal_copy.ots" </dev/null >/dev/null 2>&1; then
            rm -f "$seal_copy.ots.bak"
            # upgrade réécrit le fichier : il peut perdre son ACL.
            set_mode_acl "$seal_copy.ots" 0600 "u:$ACL_USER:r,g::---,o::---"
            chattr +i -- "$seal_copy.ots" 2>/dev/null || true
            say "HORODATAGE_ANCRE $day"
        else
            rm -f "$seal_copy.ots.bak"
            if [ "$(day_number "$day")" -lt "$pending_limit" ]; then
                warn "preuve de $day toujours incomplète après $OTS_MAX_PENDING_DAYS jours"
            fi
        fi
    done < "$MANIFEST"
}

yesterday=$(date -u -d yesterday +%Y-%m-%d)
today_number=$(date -u +%Y%m%d)

exec 9>"$LOCK_FILE"
flock -w 120 9 || fail "verrou $LOCK_FILE indisponible"

# --- Mode « horodatage seul » -------------------------------------------------
if [ "${1:-}" = "--horodater" ]; then
    timestamp_manifest
    exit "$acl_errors"
fi

# --- Mode « une journée précise » ---------------------------------------------
if [ $# -ge 1 ]; then
    case "$1" in
        [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]) ;;
        *) fail "date invalide : $1" ;;
    esac
    [ "$(day_number "$1")" -lt "$today_number" ] || fail "$1 n'est pas encore terminée (UTC)"
    seal_one_day "$1"
    timestamp_manifest
    exit "$acl_errors"
fi

# --- Mode rattrapage : de la journée suivant la dernière scellée à la veille ---
if [ -s "$MANIFEST" ]; then
    last_day=$(tail -n 1 "$MANIFEST" | cut -d' ' -f1)
    current_day=$(date -u -d "$last_day + 1 day" +%Y-%m-%d)
else
    oldest_file=$(find "$JOURNAL_DIR" -maxdepth 1 -name 'journal-????-??-??.jsonl' -printf '%f\n' | sort | head -n 1)
    if [ -n "$oldest_file" ]; then
        current_day=${oldest_file#journal-}
        current_day=${current_day%.jsonl}
    else
        current_day="$yesterday"
    fi
fi

if [ "$(day_number "$current_day")" -gt "$(day_number "$yesterday")" ]; then
    say "rien à sceller : registre à jour jusqu'au $yesterday"
    timestamp_manifest
    exit "$acl_errors"
fi

while [ "$(day_number "$current_day")" -le "$(day_number "$yesterday")" ]; do
    seal_one_day "$current_day"          # fail() arrête tout au premier échec
    current_day=$(date -u -d "$current_day + 1 day" +%Y-%m-%d)
done

timestamp_manifest

exit "$acl_errors"
