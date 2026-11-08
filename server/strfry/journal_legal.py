#!/usr/bin/python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Plugin writePolicy de strfry : liste noire et journal légal (bibliothèque standard seule).
# Il remplace le script shell journal-legal.sh 1.3.0 : même format de ligne, mêmes noms de fichiers.
# Version du document : 3.0.0-alpha.41 · 2026-11-06.
# Suivi des versions
#   3.0.0-alpha.40  2026-11-06  Module Python sans sous-processus, chemin rapide pour les kinds non journalisés (T040, D95).
#   3.0.0-alpha.41  2026-11-06  Liste noire conservée sur erreur d'accès, alertes de lecture et de lignes invalides (D110).
#
# Protocole (strfry, docs/plugins.md) : une ligne JSON par requête sur l'entrée standard, une ligne
# JSON de réponse par requête sur la sortie standard, écrite et vidée avant la lecture de la suivante.
# Variables d'environnement facultatives : JOURNAL_DIR, BLOCKLIST_FILE, UNJOURNALED_KINDS.
import errno
import json
import os
import re
import sys
import time

TOR_PREFIX = 'fc00:dead:beef:'
DEFAUT_JOURNAL_DIR = '/app/journal'
DEFAUT_BLOCKLIST_FILE = '/app/plugins/blocklist.txt'
DEFAUT_UNJOURNALED_KINDS = '20001 22242 23194 23195 24133 24242 27235'
MOTIF_CLE = re.compile(r'[0-9a-f]{64}')
# Caractères de contrôle que json.dumps laisse bruts avec ensure_ascii=False, plus U+2028 et U+2029
# (séparateurs de ligne, qui ne sont pas des caractères de contrôle).
MOTIF_CONTROLE = re.compile('[\u007f-\u009f  ]')
ECHEC_JOURNAL = 'ECHEC_JOURNAL'
ECHEC_LISTE_NOIRE = 'ECHEC_LISTE_NOIRE'
MSG_BANNI = 'blocked: auteur banni de ce relais'
PROTOCOLES_TOR = 'Tor, WebSocket, Nostr NIP-01'
PROTOCOLES_IP = 'TCP/IP, TLS, WebSocket, Nostr NIP-01'


class ErreurEntree(Exception):
    """Ligne inutilisable : aucune réponse n'est possible."""


def analyser_kinds(texte):
    """Ensemble des kinds entiers d'une liste séparée par des espaces ; les jetons invalides sont ignorés."""
    kinds = set()
    for jeton in texte.split():
        try:
            kinds.add(int(jeton))
        except ValueError:
            continue
    return frozenset(kinds)


class Etat:
    """Configuration du conteneur, cache de la liste noire et horloge injectable."""

    def __init__(self, journal_dir, blocklist_file, kinds_non_journalises, horloge=time.time):
        self.journal_dir = journal_dir
        self.blocklist_file = blocklist_file
        self.kinds_non_journalises = frozenset(kinds_non_journalises)
        self.horloge = horloge
        self._signature = None
        self._bannis = frozenset()
        self._lue = False
        self._en_erreur = False

    @classmethod
    def depuis_environnement(cls, env=None):
        env = os.environ if env is None else env
        return cls(env.get('JOURNAL_DIR', DEFAUT_JOURNAL_DIR),
                   env.get('BLOCKLIST_FILE', DEFAUT_BLOCKLIST_FILE),
                   analyser_kinds(env.get('UNJOURNALED_KINDS', DEFAUT_UNJOURNALED_KINDS)))

    def _erreur_acces(self, erreur):
        """Erreur d'accès : la dernière liste lue est conservée ; une alerte par épisode."""
        if not self._lue:
            self._bannis = frozenset()
            if isinstance(erreur, FileNotFoundError):
                return self._bannis
        if not self._en_erreur:
            self._en_erreur = True
            nom = errno.errorcode.get(erreur.errno, type(erreur).__name__)
            chemin = MOTIF_CONTROLE.sub(lambda m: '\\u%04x' % ord(m.group()), self.blocklist_file)
            chemin = re.sub('[\x00-\x1f]', lambda m: '\\x%02x' % ord(m.group()), chemin)
            _echec('lecture impossible', chemin + ' : ' + nom, ECHEC_LISTE_NOIRE)
        return self._bannis

    def bannis(self):
        """Clés bannies ; un seul os.stat par appel, relecture seulement si le fichier a changé."""
        try:
            st = os.stat(self.blocklist_file)
        except OSError as erreur:
            return self._erreur_acces(erreur)
        signature = (st.st_dev, st.st_ino, st.st_mtime_ns, st.st_size)
        if signature != self._signature or self._en_erreur:
            try:
                with open(self.blocklist_file, encoding='utf-8', errors='replace') as f:
                    lignes = f.read().split('\n')
            except OSError as erreur:
                return self._erreur_acces(erreur)
            cles, invalides = set(), []
            for numero, brute in enumerate(lignes, 1):
                texte = brute.strip()
                if not texte or texte.startswith('#'):
                    continue
                if MOTIF_CLE.fullmatch(texte):
                    cles.add(texte)
                else:
                    invalides.append(numero)
            self._bannis = frozenset(cles)
            self._signature = signature
            self._lue = True
            self._en_erreur = False
            if invalides:
                _echec('lignes invalides', '%d : %s' % (len(invalides), ' '.join(str(n) for n in invalides[:10])),
                       ECHEC_LISTE_NOIRE)
        return self._bannis


def _echec(code, detail='', mot=ECHEC_JOURNAL):
    texte = mot + ' ' + code + (' ' + detail if detail else '') + '\n'
    sys.stderr.buffer.write(texte.encode('utf-8', errors='backslashreplace'))
    sys.stderr.buffer.flush()


def nature(kind):
    if type(kind) is not int:
        return 'creation'
    if kind == 5:
        return 'suppression'
    if kind == 0 or kind == 3 or 10000 <= kind < 20000 or 30000 <= kind < 40000:
        return 'creation_ou_modification'
    return 'creation'


def _valeurs_etiquettes(tags, nom):
    valeurs = []
    if isinstance(tags, list):
        for etiquette in tags:
            if (isinstance(etiquette, list) and len(etiquette) > 1 and etiquette[0] == nom
                    and isinstance(etiquette[1], str)):
                valeurs.append(etiquette[1])
    return valeurs


def ligne_journal(requete):
    """Ligne de journal (sans fin de ligne) ; lève une exception si un champ est inutilisable."""
    evenement = requete['event']
    recu = requete['receivedAt']
    if type(recu) not in (int, float):
        raise TypeError('receivedAt')
    connexion = requete['sourceInfo']
    if not isinstance(connexion, str):
        raise TypeError('sourceInfo')
    auteur = evenement['pubkey']
    if not isinstance(auteur, str):
        raise TypeError('pubkey')
    kind = evenement.get('kind')
    entree = {
        't': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(int(recu))),
        'connexion': connexion,
        'protocoles': PROTOCOLES_TOR if connexion.startswith(TOR_PREFIX) else PROTOCOLES_IP,
        'contenu': evenement['id'],
        'nature': nature(kind),
        'auteur': auteur,
    }
    if type(kind) is int and kind == 5:
        tags = evenement.get('tags')
        entree['vise'] = _valeurs_etiquettes(tags, 'e')
        adressables = _valeurs_etiquettes(tags, 'a')
        if adressables:
            entree['vise_adressables'] = adressables
    texte = json.dumps(entree, separators=(',', ':'), ensure_ascii=False)
    return MOTIF_CONTROLE.sub(lambda m: '\\u%04x' % ord(m.group()), texte)


def _ajouter(chemin, donnees):
    base = os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        fd = os.open(chemin, base | os.O_CREAT | os.O_EXCL, 0o640)
        cree = True
    except FileExistsError:
        fd = os.open(chemin, base)
        cree = False
    try:
        # Fichier créé par cet appel : mode 0640 quel que soit l'umask ; un fichier préexistant garde son mode.
        if cree:
            os.fchmod(fd, 0o640)
        while donnees:
            ecrits = os.write(fd, donnees)
            donnees = donnees[ecrits:]
    finally:
        os.close(fd)


def inscrire(etat, ligne):
    """Ajoute la ligne au journal du jour (date UTC) ; un seul nouvel essai ; l'échec est signalé, jamais levé."""
    chemin = os.path.join(etat.journal_dir,
                          'journal-' + time.strftime('%Y-%m-%d', time.gmtime(etat.horloge())) + '.jsonl')
    donnees = (ligne + '\n').encode('utf-8', errors='backslashreplace')
    for essai in (1, 2):
        try:
            _ajouter(chemin, donnees)
            return
        except OSError:
            continue
    _echec('ecriture impossible dans ' + chemin + ' :', ligne)


def _reponse(identifiant, action, msg=None):
    corps = {'id': identifiant, 'action': action}
    if msg is not None:
        corps['msg'] = msg
    return json.dumps(corps, separators=(',', ':'))


def traiter(entree, etat):
    """Traite une requête (octets ou texte) ; renvoie la ligne de réponse, ou None si elle est illisible."""
    try:
        requete = json.loads(entree)
        evenement = requete['event']
        identifiant = evenement['id']
        if not isinstance(identifiant, str):
            raise ErreurEntree()
    except (ValueError, KeyError, TypeError, ErreurEntree, RecursionError):
        _echec('entree illisible')
        return None
    auteur = evenement.get('pubkey')
    if isinstance(auteur, str) and auteur in etat.bannis():
        return _reponse(identifiant, 'reject', MSG_BANNI)
    kind = evenement.get('kind')
    rapide = ((type(kind) is int and kind in etat.kinds_non_journalises)
              or requete.get('sourceType') not in ('IP4', 'IP6'))
    if not rapide:
        try:
            inscrire(etat, ligne_journal(requete))
        except Exception as erreur:
            _echec('champ inutilisable', type(erreur).__name__)
    return _reponse(identifiant, 'accept')


def main(entree=None, sortie=None, etat=None):
    entree = sys.stdin.buffer if entree is None else entree
    sortie = sys.stdout if sortie is None else sortie
    etat = Etat.depuis_environnement() if etat is None else etat
    for ligne in iter(entree.readline, b''):
        if not ligne.strip():
            continue
        reponse = traiter(ligne, etat)
        if reponse is not None:
            sortie.write(reponse + '\n')
            sortie.flush()
    return 0


if __name__ == '__main__':
    sys.exit(main())
