# SPDX-License-Identifier: AGPL-3.0-or-later
# Tests de deploy/backend-relais/strfry/strfry.conf (T040, D95).
# Suivi des versions
#   3.0.0-alpha.40  2026-11-06  Création (T040).
#   3.0.0-alpha.41  2026-11-06  Interdiction des arbres negentropy prédéfinis (D110).
import re
from pathlib import Path

from server.strfry import journal_legal

RACINE = Path(__file__).resolve().parent.parent
CONF = RACINE / 'deploy/backend-relais/strfry/strfry.conf'

ATTENDU = {
    'db': '/app/strfry-db/',
    'dbParams.maxreaders': 256,
    'dbParams.mapsize': 10995116277760,
    'dbParams.noReadAhead': False,
    'events.maxEventSize': 65536,
    'events.rejectEventsNewerThanSeconds': 1800,
    'events.rejectEventsOlderThanSeconds': 94608000,
    'events.rejectEphemeralEventsOlderThanSeconds': 60,
    'events.ephemeralEventsLifetimeSeconds': 300,
    'events.maxNumTags': 2000,
    'events.maxTagValSize': 1024,
    'relay.bind': '0.0.0.0',
    'relay.port': 7777,
    'relay.nofiles': 524288,
    'relay.realIpHeader': 'x-forwarded-for',
    'relay.auth.enabled': True,
    'relay.auth.serviceUrl': 'wss://relay.example.org',
    'relay.auth.restrictedReadKinds': '4',
    'relay.auth.restrictReadToInvolvedPubkey': True,
    'relay.info.name': 'Paresia',
    'relay.info.description': 'Relais Nostr du projet Paresia.',
    'relay.info.pubkey': '',
    'relay.info.self': '',
    'relay.info.contact': '',
    'relay.info.icon': '',
    'relay.info.banner': '',
    'relay.info.privacy': '',
    'relay.info.terms': '',
    'relay.info.nips': '',
    'relay.maxWebsocketPayloadSize': 131072,
    'relay.maxReqFilterSize': 200,
    'relay.autoPingSeconds': 55,
    'relay.enableTcpKeepalive': True,
    'relay.queryTimesliceBudgetMicroseconds': 10000,
    'relay.maxFilterLimit': 500,
    'relay.maxTagsPerFilter': 3,
    'relay.maxFilterLimitCount': 1000000,
    'relay.maxSubsPerConnection': 200,
    'relay.maxPendingOutboundBytes': 33554432,
    'relay.writePolicy.plugin': '/app/plugins/journal_legal.py',
    'relay.writePolicy.timeoutSeconds': 10,
    'relay.compression.enabled': True,
    'relay.compression.slidingWindow': True,
    'relay.logging.dumpInAll': False,
    'relay.logging.dumpInEvents': False,
    'relay.logging.dumpInReqs': False,
    'relay.logging.dbScanPerf': False,
    'relay.logging.invalidEvents': True,
    'relay.numThreads.ingester': 3,
    'relay.numThreads.reqWorker': 3,
    'relay.numThreads.reqMonitor': 3,
    'relay.numThreads.negentropy': 2,
    'relay.negentropy.enabled': True,
    'relay.negentropy.maxSyncEvents': 1000000,
    'relay.filterValidation.enabled': False,
    'relay.filterValidation.maxFiltersPerReq': 3,
    'relay.filterValidation.minFiltersPerReq': 1,
    'relay.filterValidation.maxKindsPerFilter': 3,
    'relay.filterValidation.allowedKinds': '',
    'relay.filterValidation.requireAuthorOrTag': False,
}


def valeur(texte):
    if texte in ('true', 'false'):
        return texte == 'true'
    if re.fullmatch(r'\d+', texte):
        return int(texte)
    m = re.fullmatch(r'"([^"]*)"', texte)
    assert m, texte
    return m.group(1)


def analyser(texte):
    """Retourne (options, options sans commentaire précédent)."""
    pile, options, sans_commentaire = [], {}, []
    precedent_commentaire = False
    for ligne in texte.split('\n'):
        brut = ligne.strip()
        if not brut:
            precedent_commentaire = False
            continue
        if brut.startswith('#'):
            precedent_commentaire = True
            continue
        m = re.fullmatch(r'(\w+) \{', brut)
        if m:
            pile.append(m.group(1))
            precedent_commentaire = False
            continue
        if brut == '}':
            pile.pop()
            precedent_commentaire = False
            continue
        m = re.fullmatch(r'(\w+) = (.+)', brut)
        assert m, ligne
        nom = '.'.join(pile + [m.group(1)])
        assert nom not in options, nom
        options[nom] = valeur(m.group(2))
        if not precedent_commentaire:
            sans_commentaire.append(nom)
        precedent_commentaire = False
        # Indentation de 4 espaces par niveau.
        assert ligne == '    ' * len(pile) + brut, ligne
    assert pile == []
    return options, sans_commentaire


def test_strfry_conf_format():
    brut = CONF.read_bytes()
    texte = brut.decode('utf-8')
    assert '\t' not in texte and '\r' not in texte and texte.endswith('\n')
    options, sans_commentaire = analyser(texte)
    assert len(ATTENDU) == 60
    assert options == ATTENDU
    assert all(type(options[k]) is type(v) for k, v in ATTENDU.items())
    assert sans_commentaire == []
    assert 'Version du document : ' in texte


def test_strfry_conf_valeurs_d95():
    o, _ = analyser(CONF.read_text(encoding='utf-8'))
    assert o['relay.auth.restrictedReadKinds'] == '4'
    assert '1059' not in o['relay.auth.restrictedReadKinds']
    assert o['relay.auth.restrictReadToInvolvedPubkey'] is True
    assert o['events.rejectEventsNewerThanSeconds'] == 1800
    assert o['relay.filterValidation.requireAuthorOrTag'] is False
    assert o['relay.filterValidation.enabled'] is False
    assert o['relay.nofiles'] == 524288
    assert o['relay.maxPendingOutboundBytes'] == 33554432
    assert re.fullmatch(r'wss://[a-z.]*example\.org', o['relay.auth.serviceUrl'])
    for champ in ('pubkey', 'self', 'contact', 'icon', 'banner', 'privacy', 'terms', 'nips'):
        assert o['relay.info.' + champ] == ''
    assert o['relay.writePolicy.plugin'] == '/app/plugins/journal_legal.py'
    assert o['relay.writePolicy.timeoutSeconds'] == 10


def test_strfry_conf_aucune_donnee_privee():
    texte = CONF.read_text(encoding='utf-8')
    assert CONF.name == CONF.name.lower()
    assert '.onion' not in texte and '@' not in texte and '/home/' not in texte
    assert not re.search('nsec' + r'1[0-9a-z]+|-----BEGIN', texte)
    for a in re.findall(r'(?<![\w.])\d{1,3}(?:\.\d{1,3}){3}(?![\w.])', texte):
        assert a == '0.0.0.0'


def test_strfry_conf_chemin_plugin_et_liste():
    o, _ = analyser(CONF.read_text(encoding='utf-8'))
    assert o['relay.writePolicy.plugin'].endswith('journal_legal.py')
    assert journal_legal.DEFAUT_UNJOURNALED_KINDS == '20001 22242 23194 23195 24133 24242 27235'


def test_strfry_conf_negentropie_sans_arbre_predefini():
    texte = CONF.read_text(encoding='utf-8')
    lignes = texte.split('\n')
    index = next(i for i, x in enumerate(lignes) if x.strip() == 'negentropy {')
    cible = next(i for i in range(index, len(lignes)) if lignes[i].strip().startswith('enabled = '))
    commentaire = []
    j = cible - 1
    while j >= 0 and lignes[j].strip().startswith('#'):
        commentaire.insert(0, lignes[j])
        j -= 1
    bloc = '\n'.join(commentaire)
    assert 'INTERDIT' in bloc and 'negentropy add' in bloc and 'negentropy build' in bloc
    options, _ = analyser(texte)
    assert options['relay.negentropy.enabled'] is True
    assert '4' in options['relay.auth.restrictedReadKinds'].split(',')
