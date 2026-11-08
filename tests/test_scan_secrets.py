# Tests de tools/hooks/scan_secrets.py (exception des vecteurs de test publiés).
# Suivi des versions
#   3.0.0-alpha.28  2026-11-05  Version alignée ; le garde est testé dans test_garde_installation.py.
#   3.0.0-alpha.2  2026-11-05  Première version.
import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "scan_secrets", Path(__file__).resolve().parents[1] / "tools" / "hooks" / "scan_secrets.py")
scan = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scan)

# Motif construit à l'exécution : aucun secret, même factice, n'est écrit dans ce fichier.
FAKE = "nsec1" + "q" * 58


def findings(name, text):
    out = []
    scan.scan_text(name, text, out)
    return out


def test_motif_refuse_hors_vecteurs():
    assert findings("src/a.py", f"x = '{FAKE}'")


def test_marque_ignoree_hors_dossier_vecteurs():
    assert findings("src/a.py", f"x = '{FAKE}'  # {scan.VECTOR_MARK}")


def test_vecteur_marque_accepte():
    assert not findings("tests/vecteurs/bip340.py", f"x = '{FAKE}'  # {scan.VECTOR_MARK}")


def test_vecteur_non_marque_refuse():
    assert findings("tests/vecteurs/bip340.py", f"x = '{FAKE}'")
