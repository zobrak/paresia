#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# =============================================================================
#  scan_secrets.py — refuse tout secret et toute référence à l'installation privée
# -----------------------------------------------------------------------------
#  Usage : scan_secrets.py [--staged | --all] [--strict]
#    --staged   (défaut ; crochet pre-commit) contenu indexé complet des fichiers
#               ajoutés ou modifiés (git show :0:<fichier>), pas l'arbre de travail
#    --all      tout le dépôt suivi par Git, contenu indexé (CI)
#    --strict   échoue si le fichier de motifs privés est absent, illisible ou ne
#               charge aucun motif (sans cette option : simple avertissement)
#    --help     cette aide
#
#  Secrets : motifs nsec1, ncryptsec1, clé privée PEM/OpenSSH, jetons GitHub ou OpenAI, et
#  fichiers interdits (secrets/, *.key, *.pem, .env). N'affiche jamais le secret trouvé.
#  Exception : vecteurs de test publiés (BIP-340, NIP-49…) dans tests/vecteurs/, ligne par
#  ligne, marqués « scan-secrets: vecteur-public » sur la même ligne.
#
#  Garde « installation privée » : refuse toute référence à l'installation
#  de l'utilisateur. Motifs génériques inscrits ici (liens artifact/share du service de
#  l'assistant, chemins de répertoires personnels hors noms-gabarits, adresses IPv4
#  RFC 1918) ; motifs privés lus dans le fichier .motifs-prives.txt à la racine principale, ou le chemin de la clé Git paresia.motifsPrives
#  (valable aussi depuis un worktree lié ; hors dépôt ; une expression rationnelle Python par ligne, « # » pour un commentaire, UTF-8).
#  Les motifs privés doivent rester simples (pas de répétitions imbriquées : risque de
#  blocage par backtracking) ; longueur maximale 256 caractères par motif.
#  Variable d'environnement PARESIA_MOTIFS_PRIVES : chemin de remplacement du fichier,
#  honorée seulement si PARESIA_GARDE_TESTS=1 est aussi défini (tests) ; sinon ignorée avec
#  avertissement. Le crochet pre-commit appelle --strict par défaut, sauf si la clé Git paresia.gardeStricte vaut false.
#  Le texte, les noms de fichiers et les motifs sont normalisés (NFKC, caractères de
#  catégorie Cf retirés, UTF-16 décodé s'il porte un BOM) avant recherche. Les noms de
#  fichiers sont contrôlés aussi. Les messages donnent fichier:ligne et un libellé ou un
#  numéro de motif, jamais la valeur, le motif ni un extrait ; les parties de nom de
#  fichier qui correspondent sont masquées. Les caractères de contrôle sont filtrés.
#  Messages en français dans le script (outil de développement, hors affichage du produit).
#
#  Suivi des versions
#    0.1.18  2026-11-08  Fichier de motifs et exclusions configurables, aucun chemin interne ; exceptions locales par fichier.
#    3.0.0-alpha.28  2026-11-05  Noms-gabarits chef et tunnel (comptes du backend-relais, D47).
#    3.0.0-alpha.28  2026-11-05  Fichier de motifs cherché dans l'arbre de travail principal (worktree lié).
#    3.0.0-alpha.28  2026-11-05  Garde « installation privée » : motifs génériques, fichier local de motifs privés.
#    3.0.0-alpha.28  2026-11-05  Contenu indexé (:0:) dans les deux modes ; listes de fichiers en -z.
#    3.0.0-alpha.28  2026-11-05  Option --strict ; avertissement si aucun motif ; motifs limités à 256 caractères.
#    3.0.0-alpha.28  2026-11-05  Normalisation NFKC, retrait des caractères Cf, décodage UTF-16 avec BOM.
#    3.0.0-alpha.28  2026-11-05  Noms de fichiers masqués dans tous les messages ; gitlinks contrôlés par leur nom.
#    3.0.0-alpha.28  2026-11-05  PARESIA_MOTIFS_PRIVES honorée seulement avec PARESIA_GARDE_TESTS=1 ; aide à la création du fichier.
#    3.0.0-alpha.2   2026-11-05  Exception pour les vecteurs de test publiés, dans tests/vecteurs/ seulement.
#    3.0.0-alpha.1   2026-11-05  Première version.
# =============================================================================
import ipaddress
import os
import re
import subprocess
import sys
import unicodedata

PATTERNS = {
    "nsec": re.compile(r"nsec1[02-9ac-hj-np-z]{20,}"),
    "ncryptsec": re.compile(r"ncryptsec1[02-9ac-hj-np-z]{20,}"),
    "clé privée": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "jeton GitHub": re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    "clé OpenAI": re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
}
FORBIDDEN = re.compile(r"(^|/)(secrets/|\.env($|\.)|[^/]*\.(key|pem)$|\.motifs-prives\.txt$|garde-exceptions\.txt$)")
SELF = "tools/hooks/scan_secrets.py"
VECTOR_DIR = "tests/vecteurs/"
VECTOR_MARK = "scan-secrets: vecteur-public"

# Noms tolérés après /home/ (gabarits, « app » : compte générique du projet) : liste unique.
HOME_GABARITS = frozenset({"utilisateur", "user", "example", "exemple", "paresia", "app", "chef", "tunnel"})
RE_LIEN = re.compile(r"claude\.ai/(artifact|share)/")
RE_HOME = re.compile(r"/home/([A-Za-z0-9._-]+)(?![A-Za-z0-9._-])")
RE_IPV4 = re.compile(r"(?<!\d)(?<!\d\.)\d{1,4}(?:\.\d{1,4}){3}(?!\d|\.\d)")
# RFC 1918, construits en nombres (aucune adresse littérale).
RFC1918 = (
    ipaddress.ip_network((10 << 24, 8)),
    ipaddress.ip_network(((172 << 24) | (16 << 16), 12)),
    ipaddress.ip_network(((192 << 24) | (168 << 16), 16)),
)
FICHIER_PRIVE_DEFAUT = ".motifs-prives.txt"
ENV_MOTIFS = "PARESIA_MOTIFS_PRIVES"
ENV_TESTS = "PARESIA_GARDE_TESTS"
LONGUEUR_MOTIF_MAX = 256
AIDE_CREATION = ("Créer .motifs-prives.txt ou configurer paresia.motifsPrives à la racine de l'arbre de travail principal du dépôt (hors dépôt, ignoré par Git) : "
                 "une expression rationnelle Python par ligne, « # » pour un commentaire, "
                 "au moins un motif.")
ENTETE_GARDE = "Commit refusé : référence à l'installation privée."
AIDE = "Usage : scan_secrets.py [--staged | --all] [--strict] [--help]"


def git(*args):
    sortie = subprocess.run(["git", *args], capture_output=True, check=True).stdout
    return sortie.decode("utf-8", errors="surrogateescape")


def racine_principale():
    """Racine de l'arbre de travail principal (git-rev-parse(1), --git-common-dir avec
    --path-format=absolute, vérifié avec Git 2.47.3) ; repli sur --show-toplevel."""
    try:
        commun = git("rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    except subprocess.CalledProcessError:
        commun = ""
    if commun and os.path.basename(commun) == ".git":
        return os.path.dirname(commun)
    return git("rev-parse", "--show-toplevel").strip()


def liste_z(*args):
    return [n for n in git(*args, "-z").split("\0") if n]


def sure(text):
    """Filtre les caractères de contrôle avant tout affichage."""
    return "".join("?" if unicodedata.category(c).startswith("C") else c for c in str(text))


def nettoyer(text):
    """NFKC et retrait des caractères de catégorie Cf (largeur nulle, etc.)."""
    text = unicodedata.normalize("NFKC", text)
    return "".join(c for c in text if unicodedata.category(c) != "Cf")


def decoder(brut):
    if brut.startswith((b"\xff\xfe", b"\xfe\xff")):
        return brut.decode("utf-16", errors="replace")
    return brut.decode("utf-8", errors="replace")


def ipv4_privee(texte):
    try:
        octets = [int(p) for p in texte.split(".")]
        if len(octets) != 4 or any(o > 255 for o in octets):
            return False
        adresse = ipaddress.IPv4Address(bytes(octets))
    except ValueError:
        return False
    return any(adresse in reseau for reseau in RFC1918)


def libelles_generiques(texte):
    """Libellés des motifs génériques présents dans texte (sans les valeurs)."""
    trouves = []
    if RE_LIEN.search(texte):
        trouves.append("lien claude.ai")
    if any(m.group(1).rstrip(".").lower() not in HOME_GABARITS for m in RE_HOME.finditer(texte)):
        trouves.append("chemin /home")
    if any(ipv4_privee(m.group(0)) for m in RE_IPV4.finditer(texte)):
        trouves.append("adresse IPv4 privée")
    return trouves


def chemin_motifs(racine):
    if os.environ.get(ENV_MOTIFS) and os.environ.get(ENV_TESTS) == "1":
        return os.path.join(racine, os.environ[ENV_MOTIFS])
    try:
        valeur = git("config", "--get", "paresia.motifsPrives").strip()
    except (OSError, subprocess.CalledProcessError):
        valeur = ""
    return os.path.join(racine, valeur or FICHIER_PRIVE_DEFAUT)


def charger_exclusions(racine):
    try:
        lignes = lire_local(os.path.join(racine, "tools/hooks/garde-exclusions.txt"))
    except (OSError, UnicodeDecodeError, ValueError):
        return frozenset()
    return frozenset(ligne for ligne in lignes if ligne and not ligne.startswith("#"))


def lire_local(chemin):
    with open(chemin, "rb") as fichier:
        brut = fichier.read(65537)
    if len(brut) > 65536:
        raise ValueError("fichier trop long")
    return brut.decode("utf-8-sig").splitlines()


def charger_exceptions(dossier, erreurs):
    try:
        lignes = lire_local(os.path.join(dossier, "garde-exceptions.txt"))
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeDecodeError, ValueError):
        erreurs.append("erreur : fichier d'exceptions de garde illisible ou invalide.")
        return {}
    exceptions = {}
    for numero, ligne in enumerate(lignes, 1):
        if not ligne or ligne.startswith("#"):
            continue
        chemin, separateur, texte = ligne.partition("\t")
        if not separateur or not chemin or not texte:
            erreurs.append(f"erreur : exception de garde mal formée à la ligne {numero} du fichier d'exceptions.")
            continue
        exceptions.setdefault(chemin, []).append(texte)
    return {chemin: tuple(textes) for chemin, textes in exceptions.items()}


def charger_motifs_prives(racine, avertissements, erreurs, strict=False):
    chemin = chemin_motifs(racine)
    if os.environ.get(ENV_MOTIFS) and os.environ.get(ENV_TESTS) != "1":
        avertissements.append(f"avertissement : {ENV_MOTIFS} ignorée (réservée aux tests, "
                              f"{ENV_TESTS}=1 requis).")
    sortie = erreurs if strict else avertissements
    try:
        with open(chemin, encoding="utf-8-sig") as f:
            lignes = f.read().splitlines()
    except (OSError, UnicodeDecodeError):
        sortie.append(("erreur" if strict else "avertissement")
                      + " : fichier de motifs privés absent ou illisible, motifs privés non appliqués.")
        return []
    motifs = []
    for numero, ligne in enumerate(lignes, 1):
        if not ligne.strip() or ligne.lstrip().startswith("#"):
            continue
        if len(ligne) > LONGUEUR_MOTIF_MAX:
            erreurs.append(f"erreur : motif privé trop long à la ligne {numero} du fichier de motifs "
                           f"(maximum {LONGUEUR_MOTIF_MAX} caractères).")
            continue
        try:
            motifs.append((numero, re.compile(nettoyer(ligne))))
        except re.error:
            erreurs.append(f"erreur : motif privé invalide à la ligne {numero} du fichier de motifs.")
    if not motifs:
        sortie.append(("erreur" if strict else "avertissement")
                      + " : aucun motif privé chargé, motifs privés non appliqués.")
    return motifs


def masquer_nom(name, motifs=()):
    """Nom de fichier affichable : les parties qui correspondent à un motif sont masquées."""
    name = nettoyer(name)
    for _, motif in motifs:
        name = motif.sub("***", name)
    name = RE_LIEN.sub("***", name)
    name = RE_HOME.sub(
        lambda m: m.group(0) if m.group(1).rstrip(".").lower() in HOME_GABARITS else "***", name)
    return RE_IPV4.sub(lambda m: "***" if ipv4_privee(m.group(0)) else m.group(0), name)


def scan_garde(name, text, motifs, findings, exclusions=frozenset(), exceptions=()):
    """Garde installation : nom du fichier, puis contenu ligne par ligne."""
    if name in exclusions:
        return
    affiche = sure(masquer_nom(name, motifs))
    cibles = [("nom de fichier", nettoyer(name), nettoyer(name))]
    for n, ligne in enumerate(text.splitlines(), 1):
        privee = ligne
        for exception in exceptions:
            privee = privee.replace(exception, " ")
        cibles.append((str(n), nettoyer(ligne), nettoyer(privee)))
    for etiquette, ligne, privee in cibles:
        for libelle in libelles_generiques(ligne):
            findings.append(f"{affiche}:{etiquette} : référence à l'installation privée "
                            f"(motif générique {libelle})")
        for n, motif in motifs:
            if motif.search(privee):
                findings.append(f"{affiche}:{etiquette} : référence à l'installation privée "
                                f"(motif privé n° {n})")


def scan_text(name, text, findings, display=None):
    vectors_allowed = name.startswith(VECTOR_DIR)
    affiche = sure(name if display is None else display)
    for number, line in enumerate(nettoyer(text).splitlines(), 1):
        if vectors_allowed and VECTOR_MARK in line:
            continue
        for label, pattern in PATTERNS.items():
            if pattern.search(line):
                findings.append(f"{affiche}:{number} : motif « {label} »")


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if "--help" in args or "-h" in args:
        print(AIDE)
        return 0
    inconnus = [a for a in args if a not in ("--staged", "--all", "--strict")]
    if inconnus or ("--staged" in args and "--all" in args):
        print(sure(AIDE), file=sys.stderr)
        return 2
    strict = "--strict" in args
    tout = "--all" in args
    findings, garde, avertissements, erreurs = [], [], [], []
    racine = racine_principale()
    motifs = charger_motifs_prives(racine, avertissements, erreurs, strict)
    exclusions = charger_exclusions(git("rev-parse", "--show-toplevel").strip())
    exceptions = charger_exceptions(os.path.dirname(chemin_motifs(racine)), erreurs)
    if tout:
        files = liste_z("ls-files")
    else:
        files = liste_z("diff", "--cached", "--name-only", "--diff-filter=ACMR")
    gitlinks = set()
    for entree in git("ls-files", "-s", "-z").split("\0"):
        if entree.startswith("160000 ") and "\t" in entree:
            gitlinks.add(entree.split("\t", 1)[1])
    for name in files:
        affiche = sure(masquer_nom(name, motifs))
        if FORBIDDEN.search(name):
            findings.append(f"{affiche} : fichier interdit dans le dépôt")
            continue
        if name in gitlinks:
            scan_garde(name, "", motifs, garde, exclusions, exceptions.get(name, ()))
            continue
        try:
            brut = subprocess.run(["git", "show", f":0:{name}"], capture_output=True, check=True).stdout
        except subprocess.CalledProcessError:
            findings.append(f"{affiche} : lecture du contenu indexé impossible")
            continue
        text = decoder(brut)
        scan_garde(name, text, motifs, garde, exclusions, exceptions.get(name, ()))
        if name != SELF:
            scan_text(name, text, findings, affiche)
    for item in avertissements + erreurs:
        print(item, file=sys.stderr)
    if strict and any(e.startswith("erreur : fichier de motifs") or e.startswith("erreur : aucun motif")
                      for e in erreurs):
        print(AIDE_CREATION, file=sys.stderr)
    if findings:
        print("Commit refusé : secret ou fichier interdit détecté.", file=sys.stderr)
        for item in findings:
            print("  " + item, file=sys.stderr)
    if garde:
        print(ENTETE_GARDE, file=sys.stderr)
        for item in garde:
            print("  " + item, file=sys.stderr)
    return 1 if (findings or garde or erreurs) else 0


if __name__ == "__main__":
    sys.exit(main())
