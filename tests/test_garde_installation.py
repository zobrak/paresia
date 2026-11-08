# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests du garde « installation privée » de tools/hooks/scan_secrets.py.
# Toutes les valeurs sont construites à l'exécution (aucune référence réelle ni motif en clair).
# Suivi des versions
#   0.1.18  2026-11-08  Crochet configurable, exclusions et exceptions locales.
#   3.0.0-alpha.28  2026-11-05  Première version.
#   3.0.0-alpha.28  2026-11-05  Test du fichier de motifs depuis un worktree lié.
#   3.0.0-alpha.28  2026-11-05  Noms-gabarits chef et tunnel acceptés, nom inventé refusé.
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "hooks" / "scan_secrets.py"
SPEC = importlib.util.spec_from_file_location("scan_secrets_garde", SCRIPT)
scan = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scan)

PRIVE = "zz-fictif-" + "42"
MOTIF = "zz-fictif-" + r"\d+"
REGISTRE = "interne/registre.md"
FICHE = "interne/fiche.md"


def ip(*octets):
    return ".".join(str(o) for o in octets)


def lien(partie):
    return "https://claude." + "ai/" + partie + "/x"


def garde(name, text, motifs=()):
    out = []
    scan.scan_garde(name, text, [(n, scan.re.compile(m)) for n, m in motifs], out)
    return out


def depot(tmp_path, fichiers):
    d = tmp_path / "depot"
    d.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    for nom, contenu in fichiers.items():
        chemin = d / nom
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_bytes(contenu if isinstance(contenu, bytes) else contenu.encode("utf-8"))
    subprocess.run(["git", "add", "-A"], cwd=d, check=True)
    return d


def executer(tmp_path, d, mode, motifs_texte=None, extra=()):
    env = dict(os.environ)
    env[scan.ENV_TESTS] = "1"
    if motifs_texte is None:
        env[scan.ENV_MOTIFS] = str(tmp_path / "absent.txt")
    else:
        fm = tmp_path / "motifs.txt"
        fm.write_bytes(motifs_texte if isinstance(motifs_texte, bytes) else motifs_texte.encode("utf-8"))
        env[scan.ENV_MOTIFS] = str(fm)
    return subprocess.run([sys.executable, str(SCRIPT), mode, *extra], cwd=d, env=env,
                          capture_output=True, text=True)


def lancer(tmp_path, mode, motifs_texte=None, fichiers=None, extra=()):
    return executer(tmp_path, depot(tmp_path, fichiers or {}), mode, motifs_texte, extra)


def test_motif_prive_refuse(tmp_path):
    r = lancer(tmp_path, "--staged", MOTIF + "\n", {"a.txt": f"x {PRIVE}\n"})
    assert r.returncode == 1
    assert "a.txt:1" in r.stderr


def test_motifs_commentaires_ignores(tmp_path):
    r = lancer(tmp_path, "--staged", "# commentaire\n\n   # autre\n" + MOTIF + "\n",
               {"a.txt": "# commentaire\nrien\n"})
    assert r.returncode == 0, r.stderr
    assert "invalide" not in r.stderr and "aucun motif" not in r.stderr


def test_fichier_absent_avertit_et_generique(tmp_path):
    r = lancer(tmp_path, "--staged", None, {"a.txt": "rien\n"})
    assert r.returncode == 0
    assert "avertissement" in r.stderr
    assert str(tmp_path) not in r.stderr
    autre = tmp_path / "b"
    autre.mkdir()
    r2 = lancer(autre, "--staged", None, {"a.txt": "ip " + ip(10, 1, 2, 3) + "\n"})
    assert r2.returncode == 1


def test_lien_claude_refuse():
    assert garde("a.md", lien("artifact"))
    assert garde("a.md", lien("share"))
    assert not garde("a.md", "https://claude." + "ai/")


def test_chemin_home():
    assert garde("a.md", "/home/" + "zz-fictif" + "/x")
    for gabarit in ("user", "example", "app", "utilisateur", "exemple", "paresia"):
        assert not garde("a.md", "/home/" + gabarit + "/x"), gabarit


def test_chemin_home_gabarits_relais():
    assert not garde("a.md", "/home/chef/")
    assert not garde("a.md", "/home/tunnel/.ssh")
    assert garde("a.md", "/home/" + "zz9test" + "/")


def test_chemin_home_sans_barre_finale():
    nom = "zz-fictif"
    assert garde("a.md", "voir /home/" + nom)
    assert garde("a.md", "voir /home/" + nom + ", puis")
    assert garde("a.md", "voir /home/" + nom + ".")
    assert not garde("a.md", "voir /home/user.")


def test_ipv4_rfc1918_seulement():
    for a in (ip(10, 1, 2, 3), ip(172, 16, 0, 1), ip(172, 31, 255, 1), ip(192, 168, 1, 1)):
        assert garde("a.md", "ip " + a), a
    for a in (ip(172, 15, 0, 1), ip(172, 32, 0, 1), ip(192, 0, 2, 1), ip(198, 51, 100, 7),
              ip(203, 0, 113, 9), ip(8, 8, 8, 8), ip(999, 1, 1, 1)):
        assert not garde("a.md", "ip " + a), a


def test_ipv4_fin_de_phrase():
    assert garde("a.md", "la machine est en " + ip(10, 1, 2, 3) + ".")
    assert garde("a.md", "(" + ip(192, 168, 1, 1) + ")")
    assert not garde("a.md", "version " + ip(10, 1, 2, 3) + ".4")


def test_ipv4_zeros_initiaux():
    assert garde("a.md", "ip " + ".".join(["010", "001", "002", "003"]))
    assert garde("a.md", "ip " + ".".join(["192", "168", "001", "001"]))


def test_documentation_hors_rfc1918():
    for reseau in ((192 << 24, 24), (198 << 24 | 51 << 16 | 100 << 8, 24),
                   (203 << 24 | 113 << 8, 24)):
        net = scan.ipaddress.ip_network(reseau)
        assert not any(net.overlaps(p) for p in scan.RFC1918)


def test_message_sans_valeur():
    out = garde("a.md", f"ligne {PRIVE}", [(7, MOTIF)])
    assert out == ["a.md:1 : référence à l'installation privée (motif privé n° 7)"]
    assert PRIVE not in out[0] and MOTIF not in out[0]
    adresse = ip(192, 168, 1, 1)
    out = garde("a.md", "ip " + adresse)
    assert "a.md:1" in out[0] and adresse not in out[0]


def test_motif_invalide_refuse(tmp_path):
    r = lancer(tmp_path, "--staged", "# c\n(zz-ouvert\n", {"a.txt": "rien\n"})
    assert r.returncode == 1
    assert "ligne 2" in r.stderr
    assert "zz-ouvert" not in r.stderr


def test_motif_trop_long_refuse(tmp_path):
    r = lancer(tmp_path, "--staged", "# c\n" + "a" * (scan.LONGUEUR_MOTIF_MAX + 1) + "\n",
               {"a.txt": "rien\n"})
    assert r.returncode == 1
    assert "ligne 2" in r.stderr
    assert "aaaa" not in r.stderr


def test_exclusion_registre_et_fiche():
    texte = "ip " + ip(192, 168, 1, 1)
    for nom in (REGISTRE, FICHE):
        out = []
        scan.scan_garde(nom, texte, [], out, exclusions=frozenset({REGISTRE, FICHE}))
        assert not out
        assert garde(nom, texte)
    assert garde("docs/autre.md", texte)
    assert garde("tools/hooks/scan_secrets.py", texte)
    assert garde("tests/test_garde_installation.py", texte)


def test_nom_de_fichier():
    out = garde("dossier/" + PRIVE + ".txt", "rien", [(1, MOTIF)])
    assert out and PRIVE not in out[0]


def test_nom_et_contenu_masques_a_l_affichage(tmp_path):
    r = lancer(tmp_path, "--staged", MOTIF + "\n", {PRIVE + ".txt": f"x {PRIVE}\n"})
    assert r.returncode == 1
    assert PRIVE not in r.stderr
    assert "***" in r.stderr


def test_nom_interdit_masque(tmp_path):
    r = lancer(tmp_path, "--staged", MOTIF + "\n", {PRIVE + ".key": "rien\n"})
    assert r.returncode == 1
    assert PRIVE not in r.stderr


def test_affichage_filtre():
    assert scan.sure("a\x1b[31mb\nc") == "a?[31mb?c"
    out = garde("x\x1b" + PRIVE + ".txt", "rien", [(1, MOTIF)])
    assert out and "\x1b" not in out[0]


def test_caractere_largeur_nulle():
    zw = "​"
    assert garde("a.md", "ip " + ip(10, 1, 2, 3)[:3] + zw + ip(10, 1, 2, 3)[3:])
    assert garde("a.md", "z" + zw + "z-fictif-42", [(1, MOTIF)])


def test_utf16_avec_bom(tmp_path):
    contenu = ("ip " + ip(10, 1, 2, 3) + "\n").encode("utf-16")
    r = lancer(tmp_path, "--staged", None, {"a.txt": contenu})
    assert r.returncode == 1


def test_binaire_sans_plantage(tmp_path):
    r = lancer(tmp_path, "--staged", None, {"a.bin": bytes(range(256)) + b"\xff\xfe\x00"})
    assert r.returncode == 0, r.stderr
    assert "Traceback" not in r.stderr


def test_strict(tmp_path):
    r = lancer(tmp_path, "--staged", None, {"a.txt": "rien\n"}, ("--strict",))
    assert r.returncode == 1
    sub = tmp_path / "s"
    sub.mkdir()
    r = lancer(sub, "--all", "# seulement un commentaire\n\n", {"a.txt": "rien\n"}, ("--strict",))
    assert r.returncode == 1
    sub2 = tmp_path / "t"
    sub2.mkdir()
    r = lancer(sub2, "--all", MOTIF + "\n", {"a.txt": "rien\n"}, ("--strict",))
    assert r.returncode == 0, r.stderr


def test_aucun_motif_avertit(tmp_path):
    r = lancer(tmp_path, "--staged", "# rien\n", {"a.txt": "rien\n"})
    assert r.returncode == 0
    assert "aucun motif" in r.stderr


def test_all_lit_l_index(tmp_path):
    d = depot(tmp_path, {"a.txt": f"x {PRIVE}\n", "b.txt": "propre\n"})
    (d / "a.txt").write_text("propre\n", encoding="utf-8")
    (d / "b.txt").write_text(f"x {PRIVE}\n", encoding="utf-8")
    r = executer(tmp_path, d, "--all", MOTIF + "\n")
    assert r.returncode == 1
    assert "a.txt:1" in r.stderr and "b.txt" not in r.stderr


def test_gitlink_nom_controle(tmp_path):
    d = tmp_path / "depot"
    d.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=d, check=True)
    for nom in ("sous", PRIVE):
        sub = d / nom
        sub.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=sub, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.org",
                        "commit", "-q", "--allow-empty", "-m", "x"], cwd=sub, check=True)
        subprocess.run(["git", "add", nom], cwd=d, check=True)
    for mode in ("--staged", "--all"):
        r = executer(tmp_path, d, mode, MOTIF + "\n")
        assert r.returncode == 1, mode
        assert PRIVE not in r.stderr and "sous" not in r.stderr
    sain = tmp_path / "sain"
    sain.mkdir()
    d2 = sain / "depot"
    d2.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=d2, check=True)
    sub = d2 / "sous"
    sub.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=sub, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.org",
                    "commit", "-q", "--allow-empty", "-m", "x"], cwd=sub, check=True)
    subprocess.run(["git", "add", "sous"], cwd=d2, check=True)
    for mode in ("--staged", "--all"):
        assert executer(sain, d2, mode, MOTIF + "\n").returncode == 0, mode


def test_integration_staged(tmp_path):
    sain = lancer(tmp_path, "--staged", MOTIF + "\n", {"a.txt": "bonjour\n"})
    assert sain.returncode == 0, sain.stderr
    autre = tmp_path / "autre"
    autre.mkdir()
    mauvais = lancer(autre, "--staged", MOTIF + "\n", {"a.txt": f"x {PRIVE}\n"})
    assert mauvais.returncode == 1
    assert "Commit refusé : référence à l'installation privée." in mauvais.stderr
    assert PRIVE not in mauvais.stderr and MOTIF not in mauvais.stderr


def test_variable_ignoree_sans_drapeau_tests(tmp_path):
    d = depot(tmp_path, {"a.txt": f"x {PRIVE}\n"})
    fm = tmp_path / "motifs.txt"
    fm.write_text(MOTIF + "\n", encoding="utf-8")
    env = dict(os.environ, **{scan.ENV_MOTIFS: str(fm)})
    env.pop(scan.ENV_TESTS, None)
    r = subprocess.run([sys.executable, str(SCRIPT), "--staged"], cwd=d, env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0
    assert "ignorée" in r.stderr
    r = subprocess.run([sys.executable, str(SCRIPT), "--staged", "--strict"], cwd=d, env=env,
                       capture_output=True, text=True)
    assert r.returncode == 1
    assert "motifs-prives.txt" in r.stderr


def test_crochet_pre_commit(tmp_path):
    d = depot(tmp_path, {"a.txt": "rien\n"})
    hooks = d / "tools/hooks"
    hooks.mkdir(parents=True)
    for nom in ("pre-commit", "scan_secrets.py"):
        (hooks / nom).write_bytes((SCRIPT.parent / nom).read_bytes())
    env = dict(os.environ)
    env.pop(scan.ENV_MOTIFS, None)
    env.pop(scan.ENV_TESTS, None)

    def lancer_hook():
        return subprocess.run(["sh", "tools/hooks/pre-commit"], cwd=d, env=env,
                              capture_output=True, text=True)

    r = lancer_hook()
    assert r.returncode == 1 and "motifs-prives.txt" in r.stderr
    subprocess.run(["git", "config", "paresia.gardeStricte", "false"], cwd=d, check=True)
    r = lancer_hook()
    assert r.returncode == 0 and "avertissement" in r.stderr
    (d / "a.txt").write_text("nsec1" + "q" * 58)
    subprocess.run(["git", "add", "a.txt"], cwd=d, check=True)
    assert lancer_hook().returncode == 1
    (d / "a.txt").write_text("rien")
    subprocess.run(["git", "add", "a.txt"], cwd=d, check=True)
    subprocess.run(["git", "config", "paresia.gardeStricte", "true"], cwd=d, check=True)
    r = lancer_hook()
    assert r.returncode == 1 and "motifs-prives.txt" in r.stderr
    (d / scan.FICHIER_PRIVE_DEFAUT).write_text(MOTIF + "\n")
    assert lancer_hook().returncode == 0


def test_worktree_lie_strict(tmp_path):
    d = tmp_path / "principal"
    d.mkdir()
    env = dict(os.environ)
    env.pop(scan.ENV_MOTIFS, None)
    env.pop(scan.ENV_TESTS, None)
    env.update({"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org"})

    def git(cwd, *args):
        return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True)

    assert git(d, "init", "-q").returncode == 0
    (d / scan.FICHIER_PRIVE_DEFAUT).write_text(MOTIF + "\n", encoding="utf-8")
    (d / "base.txt").write_text("base\n", encoding="utf-8")
    git(d, "add", "base.txt")
    assert git(d, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "base").returncode == 0
    lie = tmp_path / "lie"
    assert git(d, "worktree", "add", "-q", "-b", "essai", str(lie)).returncode == 0
    assert not (lie / scan.FICHIER_PRIVE_DEFAUT).exists()

    def crochet():
        return subprocess.run([sys.executable, str(SCRIPT), "--staged", "--strict"], cwd=lie,
                              env=env, capture_output=True, text=True)

    (lie / "propre.txt").write_text("rien\n", encoding="utf-8")
    git(lie, "add", "propre.txt")
    r = crochet()
    assert r.returncode == 0, r.stderr
    (lie / "sale.txt").write_text(f"x {PRIVE}\n", encoding="utf-8")
    git(lie, "add", "sale.txt")
    r = crochet()
    assert r.returncode == 1
    assert "sale.txt:1" in r.stderr
    assert "absent ou illisible" not in r.stderr


def test_exclusions_indexees(tmp_path):
    adresse = ip(10, 1, 2, 3)
    r = lancer(tmp_path, "--staged", MOTIF, {
        "tools/hooks/garde-exclusions.txt": "# commentaire\ninterne/registre.md\n",
        REGISTRE: adresse, "autre.md": adresse})
    assert r.returncode == 1
    assert "autre.md:1" in r.stderr and REGISTRE not in r.stderr


def test_configuration_motifs(tmp_path):
    d = depot(tmp_path, {"a.txt": PRIVE})
    fm = d / "motifs.txt"
    fm.write_text(MOTIF)
    env = dict(os.environ)
    env.pop(scan.ENV_TESTS, None)
    env.pop(scan.ENV_MOTIFS, None)
    for valeur in (str(fm), fm.name):
        subprocess.run(["git", "config", "paresia.motifsPrives", valeur], cwd=d, check=True)
        r = subprocess.run([sys.executable, str(SCRIPT), "--staged"], cwd=d, env=env,
                           capture_output=True, text=True)
        assert r.returncode == 1 and "a.txt:1" in r.stderr
        assert "absent" not in r.stderr


def test_crochets_sans_references_internes():
    interdit = scan.re.compile(r"paresia-v2|\.orchestration|consigne|T\d{3}|\bC4\b")
    for chemin in (SCRIPT, SCRIPT.parent / "pre-commit"):
        assert not interdit.search(chemin.read_text())


def test_fichiers_locaux_interdits(tmp_path):
    for numero, nom in enumerate((".motifs-prives.txt", "garde-exceptions.txt")):
        dossier = tmp_path / str(numero)
        dossier.mkdir()
        r = lancer(dossier, "--staged", MOTIF, {nom: "rien"})
        assert r.returncode == 1 and "fichier interdit" in r.stderr


def test_exceptions_locales(tmp_path):
    domaine = "example" + ".org"
    contact = "contact@" + domaine
    cas = [
        ({"SECURITY.md": contact}, 0),
        ({"autre.md": contact}, 1),
        ({"SECURITY.md": "autre@" + domaine}, 1),
        ({"SECURITY.md": contact + " nsec1" + "q" * 58}, 1),
        ({"SECURITY.md": contact + " " + ip(10, 1, 2, 3)}, 1),
    ]
    for numero, (fichiers, code) in enumerate(cas):
        dossier = tmp_path / str(numero)
        dossier.mkdir()
        (dossier / "garde-exceptions.txt").write_text("\ufeff# commentaire\nSECURITY.md\t" + contact + "\n")
        r = lancer(dossier, "--staged", scan.re.escape(domaine), fichiers)
        assert r.returncode == code, r.stderr
    for numero, ligne in enumerate(("contenu", "\ttexte", "SECURITY.md\t")):
        dossier = tmp_path / ("malforme" + str(numero))
        dossier.mkdir()
        (dossier / "garde-exceptions.txt").write_text(ligne)
        r = lancer(dossier, "--staged", MOTIF, {"a.txt": "rien"})
        assert r.returncode == 1 and "mal formée à la ligne 1" in r.stderr
        assert ligne not in r.stderr


def test_exceptions_absentes(tmp_path):
    d = depot(tmp_path, {"a.txt": PRIVE})
    for extra in ((), ("--strict",)):
        r = executer(tmp_path, d, "--staged", MOTIF, extra)
        assert r.returncode == 1 and "a.txt:1" in r.stderr
        assert "exception" not in r.stderr


def test_lectures_locales_bornees(tmp_path):
    chemin = tmp_path / "tools/hooks/garde-exclusions.txt"
    chemin.parent.mkdir(parents=True)
    for contenu in (b"\xff", b"a" * 65537):
        chemin.write_bytes(contenu)
        assert scan.charger_exclusions(tmp_path) == frozenset()
        (tmp_path / "garde-exceptions.txt").write_bytes(contenu)
        erreurs = []
        assert scan.charger_exceptions(tmp_path, erreurs) == {}
        assert len(erreurs) == 1 and "invalide" in erreurs[0]
    chemin.write_text("\ufeff# commentaire\na.md\n", encoding="utf-8")
    assert scan.charger_exclusions(tmp_path) == frozenset({"a.md"})
