# SPDX-License-Identifier: AGPL-3.0-or-later
# Suivi des versions
#   0.1.18  2026-11-08  Vérification des références dans les fichiers livrés.
import re
from pathlib import Path

from server.remus.sudoers import ENTETE

INTERDIT = re.compile(r"\bT\d{3,4}\b|\bC\d{2}\b|\bcycle(?: de correction)? \d\b|\blot \d|(?i:coordinateur|ex[ée]cutant|codex|\.orchestration|\bfiche\b|chef de lot|documentaliste|relecteur|auditeur)")


def test_livrables_sans_references_internes():
    erreurs = []
    for chemin in (Path(__file__).resolve().parents[1] / "deploy").rglob("*"):
        if not chemin.is_file() or "__pycache__" in chemin.parts:
            continue
        try:
            texte = chemin.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if "\0" in texte:
            continue
        for numero, ligne in enumerate(texte.splitlines(), 1):
            if INTERDIT.search(ligne):
                erreurs.append(f"{chemin}:{numero}")
    assert not erreurs, "\n".join(erreurs)
    assert not INTERDIT.search(ENTETE)
