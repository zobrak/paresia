#!/bin/sh
# =============================================================================
#  journal-legal-purge.sh — purge de la copie du journal légal ParesiA (backend-admin)
# -----------------------------------------------------------------------------
#  Supprime les fichiers journal-AAAA-MM-JJ.jsonl dont la date (dans le NOM)
#  est antérieure de plus de 365 jours à aujourd'hui (UTC). Une journée D est
#  donc supprimée à D + 366 jours, ce qui garantit à chaque ligne au moins un
#  an de conservation. Chaque suppression est tracée dans syslog.
#  Les fichiers scellés sont immuables (chattr +i) : le verrou est retiré juste
#  avant la suppression. Le registre MANIFEST (empreintes seules) est conservé.
#
#  Suivi des versions
#    1.1.0  2026-11-03  Retrait du verrou chattr +i avant suppression.
#    1.0.0  2026-11-03  Première version (copie de backend-admin).
# =============================================================================
set -eu

JOURNAL_DIR="/var/log/paresia/journal-legal"
RETENTION_DAYS=365
LOG_TAG="journal-legal-purge"

cutoff_date=$(date -u -d "${RETENTION_DAYS} days ago" +%Y-%m-%d)

for journal_file in "$JOURNAL_DIR"/journal-????-??-??.jsonl; do
    [ -e "$journal_file" ] || continue          # aucun fichier : rien à faire
    file_date=${journal_file##*/journal-}
    file_date=${file_date%.jsonl}
    # Comparaison lexicographique valable pour des dates AAAA-MM-JJ.
    if [ "$file_date" \< "$cutoff_date" ]; then
        chattr -i -- "$journal_file" 2>/dev/null || true
        rm -f -- "$journal_file"
        logger -t "$LOG_TAG" "supprime $journal_file (date $file_date < $cutoff_date)"
    fi
done
