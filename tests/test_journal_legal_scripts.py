# Tests des scripts journal-legal-* (D22, D24) : exécution dans un dossier
# temporaire, sur une copie dont les affectations de tête sont remplacées ;
# commandes externes remplacées par des simulacres (tests/outils/journal_legal/).
# Aucun accès réseau, aucun droit root, aucune écriture hors du dossier temporaire.
# Dépendances : bibliothèque standard, pytest.
# Suivi des versions
#   3.0.0-alpha.25  2026-11-05  Première version.
#   3.0.0-alpha.27  2026-11-05  Première relecture : référence de la purge (hachage figé,
#                               variable d'environnement), arrêt de --appliquer,
#                               contrôle lsattr de --verifier, PATH de pull,
#                               procédure.
import getpass
import hashlib
import os
import re
import shlex
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
SBIN = RACINE / "deploy" / "backend-admin" / "usr" / "local" / "sbin"
PROCEDURE = RACINE / "docs" / "installation-journal-legal-acl.md"
SIMULACRE = RACINE / "tests" / "outils" / "journal_legal" / "simulacre"
SCRIPTS = ["journal-legal-pull.sh", "journal-legal-seal.sh", "journal-legal-purge.sh",
           "journal-legal-acl.sh"]
COMMANDES = ["chmod", "setfacl", "getfacl", "chattr", "lsattr", "logger", "flock", "rsync",
             "ssh", "ots", "runuser"]
GENESIS = "0" * 64
# SHA-256 de journal-legal-purge.sh : identique à la 1.1.0 aux noms génériques près.
PURGE_SHA256 = "4e9be7b557ac1679a5a6449972060178f9acc28e108dd9b1f7671fd02cd31eab"
COMPTE = "paresia-romulus"
UTILISATEUR = getpass.getuser()


class Banc:
    """Arborescence d'essai, simulacres et copie adaptée des scripts."""

    def __init__(self, base, outils_reels=False):
        self.base = base
        self.sim = base / "sim"
        self.sim.mkdir()
        self.bin = base / "bin"
        self.bin.mkdir()
        reels = {"setfacl", "getfacl", "chmod"} if outils_reels else set()
        for nom in COMMANDES:
            if nom not in reels:
                (self.bin / nom).symlink_to(SIMULACRE)
        self.remote = base / "remote"
        self.remote.mkdir()
        self.log_root = base / "var" / "log" / "paresia"
        self.journal = self.log_root / "journal-legal"
        self.seals = self.journal / "seals"
        self.journal.mkdir(parents=True)
        self.tmp = base / "tmp"
        self.tmp.mkdir()
        self.lock = base / "verrou"
        self.compte = UTILISATEUR if outils_reels else COMPTE

    def valeurs(self):
        return {
            "PATH": f"{self.bin}:/usr/bin:/bin",
            "SOURCE": "journalpull@192.0.2.200:/",
            "DESTINATION": f"{self.journal}/",
            "SSH_KEY": str(self.base / "cle-inexistante"),
            "LOCK_FILE": str(self.lock),
            "JOURNAL_DIR": str(self.journal),
            "LOG_ROOT": str(self.log_root),
            "EXPECTED_OWNER": UTILISATEUR,
            "ACL_USER": self.compte,
            "LSATTR_BIN": str(self.bin / "lsattr"),
            "OTS_BIN": str(self.bin / "ots"),
        }

    def script(self, nom):
        texte = (SBIN / nom).read_text()
        for variable, valeur in self.valeurs().items():
            texte = re.sub(rf"^{variable}=.*$", lambda _m, v=valeur: f'{variable}="{v}"',
                           texte, flags=re.M)
        copie = self.base / "copies" / nom
        copie.parent.mkdir(exist_ok=True)
        copie.write_text(texte)
        return copie

    def lancer(self, nom, *args, **env_sup):
        env = {"PATH": f"{self.bin}:/usr/bin:/bin", "SIM_DIR": str(self.sim),
               "SIM_REMOTE_DIR": str(self.remote), "TMPDIR": str(self.tmp),
               "HOME": str(self.base), "LANG": "C.UTF-8"}
        env.update({k: str(v) for k, v in env_sup.items()})
        return subprocess.run(["/bin/sh", str(self.script(nom)), *args], env=env,
                              capture_output=True, text=True, timeout=120)

    def appels(self):
        journal = self.sim / "appels.log"
        if not journal.exists():
            return []
        sortie = []
        for ligne in journal.read_text().splitlines():
            mots = shlex.split(ligne)
            if mots and mots[-1].startswith("stderr="):
                mots = mots[:-1]
            sortie.append((mots[0], mots[1:]))
        return sortie

    def reinitialiser_journal(self):
        (self.sim / "appels.log").unlink(missing_ok=True)

    def attributs(self, chemin):
        fichier = self.sim / "attrs" / str(Path(chemin).absolute()).replace("/", "%")
        return fichier.read_text() if fichier.exists() else ""

    def poser_attributs(self, chemin, valeur):
        dossier = self.sim / "attrs"
        dossier.mkdir(exist_ok=True)
        (dossier / str(Path(chemin).absolute()).replace("/", "%")).write_text(valeur)

    def acl(self, chemin):
        """Entrées getfacl simulées, sans commentaires."""
        env = {"SIM_DIR": str(self.sim)}
        res = subprocess.run([str(self.bin / "getfacl"), "--", str(chemin)], env=env,
                             capture_output=True, text=True, check=True)
        return [re.sub(r"\s*#.*$", "", ligne) for ligne in res.stdout.splitlines()
                if ligne.strip() and not ligne.startswith("#")]


@pytest.fixture
def banc(tmp_path):
    return Banc(tmp_path)


def jour(decalage):
    return (datetime.now(timezone.utc) - timedelta(days=decalage)).strftime("%Y-%m-%d")


def sha(texte):
    return hashlib.sha256(texte.encode()).hexdigest()


CONTENU = '{"event":"a"}\n'


def preparer_scellement(banc):
    """Un journal d'il y a deux jours (local et distant), la veille sans publication."""
    d1, d2 = jour(2), jour(1)
    (banc.remote / f"journal-{d1}.jsonl").write_text(CONTENU)
    local = banc.journal / f"journal-{d1}.jsonl"
    local.write_text(CONTENU)
    local.chmod(0o644)
    return d1, d2, local


def sceller(banc, **env):
    d1, d2, local = preparer_scellement(banc)
    res = banc.lancer("journal-legal-seal.sh", **env)
    assert res.returncode == 0, res.stderr
    return d1, d2, local


def verifier_ordre(appels):
    """Pour chaque chemin : chmod toujours suivi d'un setfacl ; plus aucune
    modification (chmod, setfacl) tant qu'un chattr +i/+a est posé."""
    par_chemin = {}
    for nom, args in appels:
        if nom not in ("chmod", "setfacl", "chattr"):
            continue
        chemin = args[args.index("--") + 1]
        operation = nom if nom != "chattr" else f"chattr{args[0]}"
        par_chemin.setdefault(chemin, []).append(operation)
    for chemin, ops in par_chemin.items():
        verrous = set()
        for i, op in enumerate(ops):
            if op == "chmod":
                assert i + 1 < len(ops) and ops[i + 1] == "setfacl", (chemin, ops)
            if op in ("chmod", "setfacl"):
                assert not verrous, (chemin, ops)
            if op.startswith("chattr+"):
                verrous.add(op[-1])
            if op.startswith("chattr-"):
                verrous.discard(op[-1])
    return par_chemin


# ---------------------------------------------------------------------------
#  Syntaxe, versions, livrables
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("nom", SCRIPTS)
def test_scripts_syntaxe(nom):
    assert subprocess.run(["sh", "-n", str(SBIN / nom)]).returncode == 0
    assert os.access(SBIN / nom, os.X_OK)


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck absent : contrôle statique ignoré")
@pytest.mark.parametrize("nom", SCRIPTS)
def test_scripts_shellcheck(nom):
    # SC3012 : « \< » du script de purge, hérité de 1.1.0 (livré à l'identique).
    res = subprocess.run(["shellcheck", "-e", "SC3012", str(SBIN / nom)], capture_output=True, text=True)
    assert res.returncode == 0, res.stdout


@pytest.mark.parametrize("nom,variables", [
    ("journal-legal-pull.sh", ["PATH", "SOURCE", "DESTINATION", "SSH_KEY", "LOCK_FILE", "ACL_USER", "LSATTR_BIN"]),
    ("journal-legal-seal.sh", ["PATH", "JOURNAL_DIR", "SOURCE", "SSH_KEY", "LOCK_FILE", "OTS_BIN",
                               "ACL_USER", "LSATTR_BIN"]),
    ("journal-legal-acl.sh", ["PATH", "ACL_USER", "EXPECTED_OWNER", "LOG_ROOT", "JOURNAL_DIR",
                              "LOCK_FILE", "LSATTR_BIN"]),
])
def test_variables_de_tete(nom, variables):
    texte = (SBIN / nom).read_text()
    for variable in variables:
        assert len(re.findall(rf"^{variable}=", texte, flags=re.M)) == 1, variable


def test_scripts_versions():
    attendu = {"journal-legal-pull.sh": "1.2.1", "journal-legal-seal.sh": "1.3.0",
               "journal-legal-acl.sh": "1.1.0", "journal-legal-purge.sh": "1.1.0"}
    for nom, version in attendu.items():
        entete = (SBIN / nom).read_text().split("set -eu")[0]
        assert "Suivi des versions" in entete
        premiere = re.search(r"^#\s+(\d+\.\d+\.\d+)\s", entete.split("Suivi des versions")[1], flags=re.M)
        assert premiere.group(1) == version, nom
        if nom != "journal-legal-purge.sh":
            notes = entete.split("Suivi des versions")[1]
            assert "D22" in notes and "D24" in notes, nom
            assert "première relecture" in notes.split(f"{version}")[1].split("\n#    1.")[0] or nom == "journal-legal-seal.sh", nom


def test_livrables_sans_donnees_reelles():
    interdits = ["lap" + "2", "log" + "serv", "zobr" + "ak", "10.0." + "10", "192." + "168."]
    fichiers = [SBIN / n for n in SCRIPTS] + [PROCEDURE, Path(__file__), SIMULACRE]
    for fichier in fichiers:
        texte = fichier.read_text()
        for mot in interdits:
            assert mot not in texte, (fichier.name, mot)
        for adresse in re.findall(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", texte):
            assert adresse.startswith(("192.0.2.", "198.51.100.", "203.0.113.", "127.0.0.", "0.0.0.0")) \
                or adresse in ("3.0.0.0",), (fichier.name, adresse)
    assert not list(SBIN.glob("*.bak*"))


def test_purge_inchange():
    texte = (SBIN / "journal-legal-purge.sh").read_text()
    for interdit in ("chmod", "setfacl", "touch", "mkdir", ">>"):
        assert interdit not in texte
    assert not re.search(r"(?<![0-9])>\s*[^&/\s]", texte.replace("2>/dev/null", ""))
    assert "chattr -i -- " in texte and "rm -f -- " in texte
    # Comparaison figée à la 1.1.0 (avec noms génériques) : toujours effectuée.
    assert hashlib.sha256(texte.encode()).hexdigest() == PURGE_SHA256


def test_purge_identique_a_la_reference():
    """Compare au script de référence 1.1.0 dont le chemin est fourni par la variable
    d'environnement PARESIA_TEST_PURGE_REFERENCE (aucun chemin n'est écrit ici)."""
    chemin = os.environ.get("PARESIA_TEST_PURGE_REFERENCE")
    if not chemin:
        pytest.skip("PARESIA_TEST_PURGE_REFERENCE non définie : seul le hachage figé est contrôlé")
    reference = Path(chemin)
    assert reference.is_file(), chemin
    # Seul le nom d'hôte des commentaires de l'original est rendu générique.
    attendu = reference.read_text().replace(os.environ.get("PARESIA_TEST_PURGE_NOM", "log" + "serv"),
                                            "backend-admin")
    assert (SBIN / "journal-legal-purge.sh").read_text() == attendu


# ---------------------------------------------------------------------------
#  pull
# ---------------------------------------------------------------------------
def test_pull_modes_acl(banc):
    for nom in ("journal-2026-11-01.jsonl", "journal-2026-11-02.jsonl", "journal-2026-11-0x.jsonl",
                "journal-evil.jsonl"):
        (banc.remote / nom).write_text(CONTENU)
    scelle = banc.journal / "journal-2026-10-31.jsonl"
    scelle.write_text(CONTENU)
    scelle.chmod(0o640)
    banc.poser_attributs(scelle, "i")
    res = banc.lancer("journal-legal-pull.sh")
    assert res.returncode == 0, res.stderr
    appels = banc.appels()
    par_chemin = verifier_ordre(appels)
    for nom in ("journal-2026-11-01.jsonl", "journal-2026-11-02.jsonl"):
        chemin = str(banc.journal / nom)
        assert par_chemin[chemin] == ["chmod", "setfacl"]
        assert ("chmod", ["0640", "--", chemin]) in appels
        assert any(n == "setfacl" and f"u:{COMPTE}:r" in a[1].split(",") and chemin == a[-1]
                   for n, a in appels)
        assert banc.acl(chemin) == ["user::rw-", f"user:{COMPTE}:r--", "group::r--", "mask::r--", "other::---"]
        assert oct((banc.journal / nom).stat().st_mode & 0o777) == "0o640"
    assert str(banc.journal / "journal-evil.jsonl") not in par_chemin
    assert str(banc.journal / "journal-2026-11-0x.jsonl") not in par_chemin
    assert str(scelle) not in par_chemin
    # dossier : 0700, rx et ACL par défaut
    assert par_chemin[str(banc.journal)] == ["chmod", "setfacl"]
    assert f"default:user:{COMPTE}:r--" in banc.acl(banc.journal)


def test_pull_path_fixe():
    texte = (SBIN / "journal-legal-pull.sh").read_text()
    assert re.search(r'^PATH="/usr/sbin:/usr/bin:/sbin:/bin"$', texte, flags=re.M)


def test_pull_fichier_temporaire(banc):
    (banc.remote / "journal-2026-11-01.jsonl").write_text(CONTENU)
    assert "/tmp/journal-legal-pull" not in (SBIN / "journal-legal-pull.sh").read_text()
    for echec in (False, True):
        banc.reinitialiser_journal()
        env = {"SIM_RSYNC_FAIL": "1"} if echec else {}
        res = banc.lancer("journal-legal-pull.sh", **env)
        assert res.returncode == (1 if echec else 0)
        rsync = [ligne for ligne in (banc.sim / "appels.log").read_text().splitlines() if ligne.startswith("rsync")]
        stderr = rsync[0].rsplit("stderr=", 1)[1]
        assert stderr.startswith(str(banc.tmp) + "/")
        assert stderr != "/tmp/journal-legal-pull.err"
        assert not Path(stderr).exists()
        assert list(banc.tmp.iterdir()) == []
        if echec:
            assert any(n == "logger" and any(a.startswith("ECHEC_COPIE") for a in args)
                       for n, args in banc.appels())


# ---------------------------------------------------------------------------
#  seal
# ---------------------------------------------------------------------------
def test_ordre_chmod_setfacl_chattr(banc):
    sceller(banc)
    assert banc.lancer("journal-legal-seal.sh", SIM_OTS_UPGRADE_OK="1").returncode == 0
    par_chemin = verifier_ordre(banc.appels())
    assert par_chemin  # des appels ont bien été enregistrés
    # Le simulacre refuse chmod/setfacl sur un fichier immuable ou en ajout seul :
    # un ordre inverse aurait fait échouer le scellement (code de sortie non nul ci-dessus).


def test_seal_modes_acl(banc):
    d1, d2, local = sceller(banc)
    manifest, seals = banc.journal / "MANIFEST", banc.seals
    base_rw = ["user::rw-", f"user:{COMPTE}:r--", "group::---", "mask::r--", "other::---"]
    assert banc.acl(manifest) == base_rw
    assert banc.attributs(manifest) == "a"
    assert banc.acl(local) == ["user::rw-", f"user:{COMPTE}:r--", "group::r--", "mask::r--", "other::---"]
    assert banc.attributs(local) == "i"
    assert banc.acl(seals) == ["user::rwx", f"user:{COMPTE}:r-x", "group::---", "mask::r-x", "other::---",
                               "default:user::rwx", f"default:user:{COMPTE}:r--", "default:group::---",
                               "default:mask::r--", "default:other::---"]
    for d in (d1, d2):
        txt = seals / f"{d}.txt"
        assert banc.acl(txt) == base_rw
        assert banc.attributs(txt) == "i"
        ots = seals / f"{d}.txt.ots"
        assert ots.read_text() == "PENDING\n"
        assert banc.acl(ots) == base_rw           # après stamp : chmod + setfacl
        assert banc.attributs(ots) == ""          # preuve en attente : pas immuable
    appels = banc.appels()
    chemin_manifest = str(manifest)
    ops = [(n, a[0]) for n, a in appels if a and a[-1] == chemin_manifest and n in ("setfacl", "chattr")]
    assert ops.index(("setfacl", "-m")) < ops.index(("chattr", "+a"))
    assert ("chmod", ["0600", "--", chemin_manifest]) in appels
    assert ("chmod", ["0700", "--", str(seals)]) in appels
    # Deuxième passage : ancrage ; le fichier réécrit perd son ACL, le script la repose.
    banc.reinitialiser_journal()
    res = banc.lancer("journal-legal-seal.sh", SIM_OTS_UPGRADE_OK="1")
    assert res.returncode == 0, res.stderr
    for d in (d1, d2):
        ots = seals / f"{d}.txt.ots"
        assert ots.read_text() == "ANCHORED\n"
        assert banc.acl(ots) == base_rw
        assert banc.attributs(ots) == "i"
    ops_ots = [(n, a[0]) for n, a in banc.appels() if a and a[-1] == str(seals / f"{d1}.txt.ots")
               and n in ("chmod", "setfacl", "chattr")]
    assert [n for n, _ in ops_ots] == ["chmod", "setfacl", "chattr"]
    verifier_ordre(banc.appels())


def test_seal_format_inchange(banc):
    d1, d2, _local = sceller(banc)
    taille = len(CONTENU.encode())
    chaine1 = sha(f"{GENESIS} {d1} {sha(CONTENU)} {taille}")
    chaine2 = sha(f"{chaine1} {d2} ABSENT 0")
    attendu = (f"{d1} {sha(CONTENU)} {taille} {GENESIS} {chaine1}\n"
               f"{d2} ABSENT 0 {chaine1} {chaine2}\n")
    assert (banc.journal / "MANIFEST").read_text() == attendu
    assert (banc.seals / f"{d1}.txt").read_text() == attendu.splitlines()[0]


# ---------------------------------------------------------------------------
#  --verifier
# ---------------------------------------------------------------------------
def sortie_attendue(d1, d2, etat):
    return (f"OK      {d1}  fichier et chaîne intègres ; horodatage {etat}\n"
            f"OK      {d2}  aucune publication ce jour-là ; horodatage {etat}\n"
            "RÉSULTAT : registre intègre (2 journées)\n")


def test_verifier_inchange(banc):
    d1, d2, _ = sceller(banc)
    res = banc.lancer("journal-legal-seal.sh", "--verifier")
    assert (res.returncode, res.stdout) == (0, sortie_attendue(d1, d2, "en attente"))
    assert banc.lancer("journal-legal-seal.sh", SIM_OTS_UPGRADE_OK="1").returncode == 0
    res = banc.lancer("journal-legal-seal.sh", "--verifier")
    assert (res.returncode, res.stdout) == (0, sortie_attendue(d1, d2, "ancré"))


def test_verifier_registre_vide(banc):
    res = banc.lancer("journal-legal-seal.sh", "--verifier")
    assert res.returncode == 0
    assert res.stdout.startswith("registre vide ou absent")


def test_verifier_alteration(banc):
    d1, d2, local = sceller(banc)
    local.write_text(CONTENU + "ajout\n")          # le simulacre ne rend pas le fichier réellement immuable
    res = banc.lancer("journal-legal-seal.sh", "--verifier")
    assert res.returncode == 1
    assert f"ERREUR ligne 1 ({d1}) : fichier modifié depuis le scellement" in res.stdout
    assert "RÉSULTAT : 1 erreur(s)" in res.stdout
    local.write_text(CONTENU)
    manifest = banc.journal / "MANIFEST"
    lignes = manifest.read_text().splitlines()
    champs = lignes[0].split(" ")
    champs[2] = "999"
    manifest.write_text(" ".join(champs) + "\n" + lignes[1] + "\n")
    res = banc.lancer("journal-legal-seal.sh", "--verifier")
    assert res.returncode == 1 and "ligne du registre modifiée" in res.stdout


def test_verifier_ots_lsattr(banc):
    d1, d2, _ = sceller(banc)
    ots = banc.seals / f"{d1}.txt.ots"
    assert os.access(ots, os.W_OK)                  # inscriptible : l'ancien test [ -w ] dirait « en attente »
    banc.poser_attributs(ots, "i")
    res = banc.lancer("journal-legal-seal.sh", "--verifier")
    assert f"OK      {d1}  fichier et chaîne intègres ; horodatage ancré" in res.stdout
    assert f"{d2}  aucune publication ce jour-là ; horodatage en attente" in res.stdout
    banc.poser_attributs(ots, "")
    res = banc.lancer("journal-legal-seal.sh", "--verifier")
    assert f"{d1}  fichier et chaîne intègres ; horodatage en attente" in res.stdout


@pytest.mark.skipif(os.geteuid() == 0, reason="root lit tout : l'illisibilité ne peut pas être simulée")
def test_verifier_fichier_illisible(banc):
    d1, d2, local = sceller(banc)
    local.chmod(0o000)
    res = banc.lancer("journal-legal-seal.sh", "--verifier")
    assert res.returncode == 1
    assert f"ERREUR ligne 1 ({d1}) : lecture impossible de {local} (droits ou ACL manquants)" in res.stdout
    assert "modifié" not in res.stdout and "ne correspond pas" not in res.stdout
    local.chmod(0o640)
    txt = banc.seals / f"{d1}.txt"
    txt.chmod(0o000)
    res = banc.lancer("journal-legal-seal.sh", "--verifier")
    assert res.returncode == 1 and f"lecture impossible de seals/{d1}.txt" in res.stdout
    assert "ne correspond pas" not in res.stdout
    txt.chmod(0o600)
    res = banc.lancer("journal-legal-seal.sh", "--verifier", SIM_LSATTR_FAIL=f"{d1}.txt.ots")
    assert res.returncode == 1 and f"attributs illisibles pour seals/{d1}.txt.ots" in res.stdout
    manifest = banc.journal / "MANIFEST"
    manifest.chmod(0o000)
    res = banc.lancer("journal-legal-seal.sh", "--verifier")
    assert res.returncode == 1
    assert "ERREUR lecture impossible" in res.stdout and "registre vide" not in res.stdout
    manifest.chmod(0o600)


# ---------------------------------------------------------------------------
#  Échec d'ACL
# ---------------------------------------------------------------------------
def modes_permis(appels):
    return {a[0] for n, a in appels if n == "chmod"} <= {"0600", "0640", "0700"}


def test_echec_acl_signale(banc):
    d1, d2, local = preparer_scellement(banc)
    res = banc.lancer("journal-legal-seal.sh", SIM_SETFACL_FAIL="1")
    assert res.returncode != 0
    appels = banc.appels()
    assert any(n == "logger" and a[:3] == ["-p", "user.err", "-t"] and a[3] == "journal-legal-seal"
               and a[4].startswith("ECHEC_ACL") for n, a in appels)
    assert len((banc.journal / "MANIFEST").read_text().splitlines()) == 2    # scellement terminé
    assert banc.attributs(local) == "i" and banc.attributs(banc.journal / "MANIFEST") == "a"
    assert (banc.seals / f"{d1}.txt.ots").exists()
    assert modes_permis(appels)
    # pull : copie terminée malgré l'échec
    (banc.remote / "journal-2026-11-01.jsonl").write_text(CONTENU)
    banc.reinitialiser_journal()
    res = banc.lancer("journal-legal-pull.sh", SIM_SETFACL_FAIL="1")
    assert res.returncode != 0
    assert (banc.journal / "journal-2026-11-01.jsonl").exists()
    appels = banc.appels()
    assert any(n == "logger" and "ECHEC_ACL" in " ".join(a) for n, a in appels)
    assert modes_permis(appels)
    # chmod en échec : pas de setfacl, pas d'élargissement
    assert not any(n == "chmod" and a[0] in ("0644", "0755", "0666", "0777") for n, a in appels)


# ---------------------------------------------------------------------------
#  journal-legal-acl.sh
# ---------------------------------------------------------------------------
def arbre_acl(banc):
    banc.seals.mkdir()
    for dossier in (banc.log_root, banc.journal, banc.seals):
        dossier.chmod(0o755)
    fichiers = {
        "j1": banc.journal / "journal-2026-01-01.jsonl",
        "j2": banc.journal / "journal-2026-01-02.jsonl",
        "mauvais": banc.journal / "journal-2026-01-0x.jsonl",
        "manifest": banc.journal / "MANIFEST",
        "txt": banc.seals / "2026-01-01.txt",
        "ots": banc.seals / "2026-01-01.txt.ots",
    }
    for fichier in fichiers.values():
        fichier.write_text(CONTENU)
        fichier.chmod(0o644)
    # Registre : seul le journal du 2026-01-01 est scellé (inscrit au MANIFEST).
    fichiers["manifest"].write_text(f"2026-01-01 {sha(CONTENU)} {len(CONTENU)} {GENESIS} {GENESIS}\n")
    banc.poser_attributs(fichiers["j1"], "i")
    banc.poser_attributs(fichiers["manifest"], "a")
    banc.poser_attributs(fichiers["txt"], "i")
    banc.poser_attributs(fichiers["ots"], "i")
    return fichiers


def appels_modifiants(banc):
    return [(n, a) for n, a in banc.appels() if n in ("chmod", "setfacl", "chattr")]


def test_acl_appliquer(banc):
    f = arbre_acl(banc)
    res = banc.lancer("journal-legal-acl.sh", "--appliquer")
    assert res.returncode == 0, res.stderr + res.stdout
    appels = banc.appels()
    verifier_ordre(appels)
    # fichier immuable : retrait, chmod, setfacl, rétablissement
    for cle, drapeau in (("j1", "i"), ("manifest", "a"), ("txt", "i"), ("ots", "i")):
        chemin = str(f[cle])
        ops = [(n, a[0]) for n, a in appels if a and a[-1] == chemin and n in ("chmod", "setfacl", "chattr")]
        assert ops[0] == ("chattr", f"-{drapeau}") and ops[-1] == ("chattr", f"+{drapeau}"), ops
        assert [n for n, _ in ops[1:-1]] == ["chmod", "setfacl", "setfacl"]
        assert banc.attributs(f[cle]) == drapeau
    # un seul fichier déverrouillé à la fois
    ouverts = set()
    for n, a in appels:
        if n == "chattr":
            (ouverts.add if a[0][0] == "-" else ouverts.discard)(a[-1])
            assert len(ouverts) <= 1
    assert not ouverts
    # fichier non conforme au nom : jamais touché ; journaux ordinaires traités
    assert not any(str(f["mauvais"]) in a for _n, a in appels)
    assert banc.acl(f["j2"]) == ["user::rw-", f"user:{COMPTE}:r--", "group::r--", "mask::r--", "other::---"]
    assert banc.acl(f["manifest"]) == ["user::rw-", f"user:{COMPTE}:r--", "group::---", "mask::r--", "other::---"]
    assert banc.acl(banc.log_root) == ["user::rwx", f"user:{COMPTE}:--x", "group::---", "mask::--x", "other::---"]
    assert f"default:user:{COMPTE}:r--" in banc.acl(banc.journal)
    assert f"default:user:{COMPTE}:r--" in banc.acl(banc.seals)
    # journalisation syslog de chaque élément traité
    traites = [a[-1] for n, a in appels if n == "logger" and a[-1].startswith("TRAITE")]
    assert len(traites) == 8        # 3 dossiers + 2 journaux + MANIFEST + .txt + .ots
    # idempotence : deuxième passage sans aucune modification
    banc.reinitialiser_journal()
    res = banc.lancer("journal-legal-acl.sh", "--appliquer")
    assert res.returncode == 0
    assert appels_modifiants(banc) == []
    assert "RÉSULTAT : modes et ACL appliqués" in res.stdout


def test_acl_appliquer_trap(banc):
    f = arbre_acl(banc)
    # setfacl en échec : attributs rétablis, ECHEC_ACL, code non nul, pas de repli plus large
    res = banc.lancer("journal-legal-acl.sh", "--appliquer", SIM_SETFACL_FAIL="1")
    assert res.returncode == 1
    for cle, drapeau in (("j1", "i"), ("manifest", "a"), ("txt", "i"), ("ots", "i")):
        assert banc.attributs(f[cle]) == drapeau, cle
    appels = banc.appels()
    assert any(n == "logger" and "ECHEC_ACL" in " ".join(a) for n, a in appels)
    assert modes_permis(appels)
    # interruption (TERM) pendant le traitement d'un fichier immuable : rétablissement par trap
    banc.reinitialiser_journal()
    for fichier in (banc.sim / "acl").glob("*"):
        fichier.unlink()
    res = banc.lancer("journal-legal-acl.sh", "--appliquer", SIM_SETFACL_KILL_PARENT="journal-2026-01-01.jsonl")
    assert res.returncode == 143
    assert banc.attributs(f["j1"]) == "i"
    appels = banc.appels()
    ops = [(n, a[0]) for n, a in appels if a and a[-1] == str(f["j1"]) and n == "chattr"]
    assert ops == [("chattr", "-i"), ("chattr", "+i")]


def test_acl_appliquer_arret_apres_echec_retablissement(banc):
    f = arbre_acl(banc)
    # chattr +i échoue au rétablissement : arrêt immédiat, code non nul, pas de « appliqués »
    res = banc.lancer("journal-legal-acl.sh", "--appliquer", SIM_CHATTR_FAIL="+i")
    assert res.returncode != 0
    assert "ARRÊT" in res.stderr + res.stdout
    assert "appliqués" not in res.stdout
    appels = banc.appels()
    assert any(n == "logger" and "ECHEC_ACL" in " ".join(a) and "rétablissement" in " ".join(a)
               for n, a in appels)
    traites = {a[-1] for n, a in appels if n in ("chmod", "setfacl")}
    # les éléments qui suivent le premier fichier immuable (j1) ne sont pas traités
    assert str(f["txt"]) not in traites and str(f["ots"]) not in traites
    assert str(f["manifest"]) not in traites
    # chattr +a échoue pour le MANIFEST : même comportement
    banc.reinitialiser_journal()
    for fichier in (banc.sim / "acl").glob("*"):
        fichier.unlink()
    banc.poser_attributs(f["j1"], "i")
    banc.poser_attributs(f["manifest"], "a")
    res = banc.lancer("journal-legal-acl.sh", "--appliquer", SIM_CHATTR_FAIL="+a")
    assert res.returncode != 0
    assert "ARRÊT" in res.stderr + res.stdout
    assert "appliqués" not in res.stdout
    traites = {a[-1] for n, a in banc.appels() if n in ("chmod", "setfacl")}
    assert str(f["txt"]) not in traites and str(f["ots"]) not in traites


def test_acl_verifier_attributs(banc):
    f = arbre_acl(banc)
    assert banc.lancer("journal-legal-acl.sh", "--appliquer").returncode == 0
    banc.reinitialiser_journal()
    res = banc.lancer("journal-legal-acl.sh", "--verifier")
    assert res.returncode == 0, res.stdout
    assert f"OK      attribut a présent : {f['manifest']}" in res.stdout
    assert f"OK      attribut i présent : {f['j1']}" in res.stdout
    assert f"OK      attribut i présent : {f['txt']}" in res.stdout
    assert appels_modifiants(banc) == []
    # chaque attribut manquant est une erreur (arrêt brutal entre chattr -x et +x)
    for cle, lettre in (("manifest", "a"), ("j1", "i"), ("txt", "i")):
        banc.poser_attributs(f[cle], "")
        res = banc.lancer("journal-legal-acl.sh", "--verifier")
        assert res.returncode == 1, cle
        assert f"ERREUR attribut {lettre} absent : {f[cle]}" in res.stdout
        banc.poser_attributs(f[cle], lettre)
    # un journal non inscrit au registre (j2) n'a pas besoin de « i »
    assert banc.attributs(f["j2"]) == ""
    # attributs illisibles : erreur explicite
    res = banc.lancer("journal-legal-acl.sh", "--verifier", SIM_LSATTR_FAIL=str(f["manifest"]))
    assert res.returncode == 1 and f"ERREUR attributs illisibles : {f['manifest']}" in res.stdout
    # journal inscrit au registre mais absent
    f["j1"].unlink()
    res = banc.lancer("journal-legal-acl.sh", "--verifier")
    assert res.returncode == 1 and "ERREUR journal inscrit au registre absent" in res.stdout


def test_acl_appliquer_verrou(banc):
    arbre_acl(banc)
    res = banc.lancer("journal-legal-acl.sh", "--appliquer", SIM_LOCK_HELD="1")
    assert res.returncode == 1
    assert "REFUS" in res.stderr
    assert appels_modifiants(banc) == []


def test_acl_arguments(banc):
    arbre_acl(banc)
    for args in ((), ("--autre",), ("--verifier", "extra")):
        res = banc.lancer("journal-legal-acl.sh", *args)
        assert res.returncode == 2 and "usage" in res.stderr
    assert appels_modifiants(banc) == []


def test_acl_verifier(banc):
    f = arbre_acl(banc)
    assert banc.lancer("journal-legal-acl.sh", "--appliquer").returncode == 0
    banc.reinitialiser_journal()
    res = banc.lancer("journal-legal-acl.sh", "--verifier")
    assert res.returncode == 0, res.stdout
    assert "ERREUR" not in res.stdout
    assert res.stdout.rstrip().endswith("RÉSULTAT : conforme")
    assert f"OK      droits et ACL conformes : {f['manifest']}" in res.stdout
    appels = banc.appels()
    assert appels_modifiants(banc) == []            # aucune écriture
    runuser = [a for n, a in appels if n == "runuser"]
    assert all(a[:3] == ["-u", COMPTE, "--"] for a in runuser)
    commandes = [a[3:] for a in runuser]
    assert ["test", "-x", str(banc.log_root)] in commandes
    assert ["ls", "--", str(banc.journal)] in commandes
    assert ["ls", "--", str(banc.seals)] in commandes
    assert ["head", "-n", "1", "--", str(f["j2"])] in commandes       # dernier journal à nom strict
    assert ["head", "-n", "1", "--", str(f["manifest"])] in commandes
    assert ["head", "-n", "1", "--", str(f["txt"])] in commandes
    assert ["test", "-r", str(f["ots"])] in commandes
    # échec de lecture par chemin
    for cible in (str(banc.log_root), str(banc.journal), str(banc.seals), str(f["j2"]), str(f["manifest"]),
                  str(f["txt"]), str(f["ots"])):
        res = banc.lancer("journal-legal-acl.sh", "--verifier", SIM_RUNUSER_DENY=cible)
        assert res.returncode == 1, cible
        assert f"ERREUR lecture par {COMPTE} impossible" in res.stdout and cible in res.stdout
        assert "RÉSULTAT : 1 erreur(s)" in res.stdout
    # ACL manquante, ACL en trop, mauvais propriétaire
    sim_acl = {"SIM_DIR": str(banc.sim)}
    for cle in ("manifest", "j2"):
        banc.poser_attributs(f[cle], "")        # le simulacre refuse sinon, comme le noyau
    subprocess.run([str(banc.bin / "setfacl"), "-b", "--", str(f["manifest"])], env=sim_acl, check=True)
    res = banc.lancer("journal-legal-acl.sh", "--verifier")
    assert res.returncode == 1 and f"entrée ACL manquante « user:{COMPTE}:r-- »" in res.stdout
    subprocess.run([str(banc.bin / "setfacl"), "-m", "u:autre:r", "--", str(f["j2"])], env=sim_acl, check=True)
    res = banc.lancer("journal-legal-acl.sh", "--verifier")
    assert "entrée ACL non prévue « user:autre:r-- »" in res.stdout and res.returncode == 1
    banc_script = banc.script("journal-legal-acl.sh")
    texte = banc_script.read_text().replace(f'EXPECTED_OWNER="{UTILISATEUR}"', 'EXPECTED_OWNER="autre"')
    banc_script.write_text(texte)
    env = {"PATH": f"{banc.bin}:/usr/bin:/bin", "SIM_DIR": str(banc.sim)}
    res = subprocess.run(["/bin/sh", str(banc_script), "--verifier"], env=env, capture_output=True, text=True)
    assert "ERREUR propriétaire" in res.stdout


def test_acl_avec_setfacl_reel(tmp_path):
    """Syntaxe réelle de setfacl/getfacl (si le système de fichiers de test gère les ACL)."""
    if shutil.which("setfacl") is None or shutil.which("getfacl") is None:
        pytest.skip("setfacl/getfacl absents : limite documentée, simulacres seuls")
    sonde = tmp_path / "sonde"
    sonde.write_text("x")
    if subprocess.run(["setfacl", "-m", f"u:{UTILISATEUR}:r", str(sonde)], capture_output=True).returncode != 0:
        pytest.skip("ACL non gérées par le système de fichiers de test")
    (tmp_path / "banc").mkdir()
    banc = Banc(tmp_path / "banc", outils_reels=True)
    f = arbre_acl(banc)
    res = banc.lancer("journal-legal-acl.sh", "--appliquer")
    assert res.returncode == 0, res.stdout + res.stderr
    res = banc.lancer("journal-legal-acl.sh", "--verifier")
    assert res.returncode == 0, res.stdout + res.stderr
    assert res.stdout.rstrip().endswith("RÉSULTAT : conforme")
    sortie = subprocess.run(["getfacl", "-p", str(f["j1"])], capture_output=True, text=True).stdout
    assert f"user:{UTILISATEUR}:r--" in sortie and "other::---" in sortie
    # pull et seal posent la même ACL (chmod réel puis setfacl réel)
    (banc.remote / "journal-2026-11-01.jsonl").write_text(CONTENU)
    res = banc.lancer("journal-legal-pull.sh")
    assert res.returncode == 0, res.stderr
    sortie = subprocess.run(["getfacl", "-p", str(banc.journal / "journal-2026-11-01.jsonl")],
                            capture_output=True, text=True).stdout
    assert f"user:{UTILISATEUR}:r--" in sortie and "group::r--" in sortie


# ---------------------------------------------------------------------------
#  Procédure d'installation
# ---------------------------------------------------------------------------
def test_procedure_avertissements():
    texte = PROCEDURE.read_text()
    etapes = re.findall(r"^## Étape (\d+)\b", texte, flags=re.M)
    assert etapes == [str(n) for n in range(1, 11)]
    lignes = texte.splitlines()
    blocs = 0
    i = 0
    while i < len(lignes):
        if lignes[i].startswith("```") and not lignes[i].strip() == "```":
            debut = i
            fin = i + 1
            while not lignes[fin].startswith("```"):
                fin += 1
            corps = "\n".join(lignes[debut:fin])
            if any(m in corps for m in ("journal-legal-acl.sh --appliquer", "setfacl -b",
                                        "# RESTAURATION")):
                precedent = next(l for l in reversed(lignes[:debut]) if l.strip())
                assert precedent.startswith("**Avertissement"), corps
                blocs += 1
            i = fin
        i += 1
    assert blocs >= 3
