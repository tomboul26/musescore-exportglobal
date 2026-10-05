#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Export global — plugin pour MuseScore Studio 4
# Copyright (c) 2026 Thomas Boulenger — licence MIT (voir le fichier LICENSE)
"""
Export global MuseScore 4 (PDF conducteur + parties, PNG, MIDI, MP3)
avec génération de parties « dérivées » transposées pour d'autres instruments.

Principe :
  1. On prend le .mscz (argument, ou le plus récemment enregistré dans DOSSIER_ARRANGEMENTS).
  2. Dans une COPIE TEMPORAIRE, chaque voix listée dans parties_config.json est dupliquée
     vers un nouvel instrument (transposition + clef), masqué dans le conducteur.
  3. MuseScore est lancé en ligne de commande (sans fenêtre) :
       - sur l'original  : PNG, MIDI, MP3 du conducteur
       - sur la copie    : PDF du conducteur, de TOUTES les parties (y compris dérivées)
                           et un PDF unique « conducteur + parties »
  4. La copie temporaire est supprimée. Le fichier d'origine n'est jamais modifié.

Aucune dépendance : Python 3.8+ suffit.
"""

import base64
import copy
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
import xml.etree.ElementTree as ET

ICI = os.path.dirname(os.path.abspath(__file__))
FICHIER_CONFIG = os.path.join(ICI, "parties_config.json")

# ---------------------------------------------------------------------------
#  Théorie : transpositions
# ---------------------------------------------------------------------------
# Intervalle ÉCRIT au-dessus du son réel (degrés diatoniques, demi-tons)
TONALITES = {
    "ut": (0, 0),
    "sib": (1, 2),    # seconde majeure  (trompette, clarinette, sax ténor -> octave 1)
    "la": (2, 3),     # tierce mineure   (clarinette en La)
    "mib": (5, 9),    # sixte majeure    (sax alto ; sax baryton/tuba Mib -> octave 1)
    "fa": (4, 7),     # quinte juste     (cor en Fa)
    "sol": (3, 5),    # quarte juste     (flûte alto en Sol)
}
ALIAS_TONALITES = {"do": "ut", "c": "ut", "bb": "sib", "b": "sib", "eb": "mib", "f": "fa",
                   "a": "la", "g": "sol"}
_FIFTHS_OF_STEP = [0, 2, 4, -1, 1, 3, 5]   # 1re, 2de M, 3ce M, 4te J, 5te J, 6te M, 7e M
_SEMIS_OF_STEP = [0, 2, 4, 5, 7, 9, 11]


def interval_en_quintes(diat, chrom):
    """Décalage sur le cycle des quintes (tpc) pour un intervalle ascendant."""
    octaves, step = divmod(diat, 7)
    alteration = chrom - (12 * octaves + _SEMIS_OF_STEP[step])
    return _FIFTHS_OF_STEP[step] + 7 * alteration


def transposer_tpc(tpc, delta):
    t = tpc + delta
    while t > 33:
        t -= 12
    while t < -1:
        t += 12
    return t


def transposer_armure(cle, delta):
    k = cle + delta
    while k > 7:
        k -= 12
    while k < -7:
        k += 12
    # éviter les armures à 7 altérations quand une équivalente plus simple existe
    if k == 7:
        k = -5
    elif k == -7:
        k = 5
    return k


# ---------------------------------------------------------------------------
#  Configuration
# ---------------------------------------------------------------------------
# Les parties dérivées sont décrites DANS la partition, via
#   Fichier > Propriétés de la partition > Nouvelle propriété
#   nom    : parties Trombone          (« parties » + nom exact de l'instrument)
#   valeur : Sib fa ; Ut sol +1        (tonalité, clé, décalage d'octave)
#            Sax alto = Mib sol        (« Nom = ... » pour imposer le nom de la partie)
# À défaut : fichier "<partition>.parties.json" à côté du .mscz, puis section
# "voix" de parties_config.json (valeurs par défaut).

CLES = {"g": "G", "sol": "G", "f": "F", "fa": "F", "c3": "C3", "ut3": "C3",
        "c4": "C4", "ut4": "C4", "c1": "C1", "ut1": "C1",
        # clés avec indication d'octave (contrebasses…) : les notes apparaissent plus haut sur la portée
        "g8vb": "G8vb", "sol8": "G8vb", "sol8vb": "G8vb",
        "f8vb": "F8vb", "fa8": "F8vb", "fa8vb": "F8vb",
        "g15mb": "G15mb", "sol15": "G15mb", "sol15mb": "G15mb",
        "f15mb": "F15mb", "fa15": "F15mb", "fa15mb": "F15mb"}
NOMS_CLES = {"G": "clef de sol", "F": "clef de fa", "C3": "clef d'ut 3", "C4": "clef d'ut 4",
             "C1": "clef d'ut 1", "G8vb": "clef de sol 8", "F8vb": "clef de fa 8",
             "G15mb": "clef de sol 15", "F15mb": "clef de fa 15"}
# famille de clef pour le nom des fichiers (« Basse Bb clef de sol »)
FAMILLE_CLE = {"G": "clef de sol", "G8vb": "clef de sol", "G15mb": "clef de sol",
               "F": "clef de fa", "F8vb": "clef de fa", "F15mb": "clef de fa",
               "C1": "clef d'ut 1", "C3": "clef d'ut 3", "C4": "clef d'ut 4"}
TON_EN = {"ut": "C", "sib": "Bb", "mib": "Eb", "fa": "F", "la": "A", "sol": "G"}


def nom_complet(base, ton, cle):
    """« Basse » + Sib + sol15 -> « Basse Bb clef de sol »."""
    suffixe = "%s %s" % (TON_EN[ton], FAMILLE_CLE.get(cle, cle))
    if suffixe.lower() in base.lower():
        return base
    mots = [sans_accent(m) for m in base.split()]
    if TON_EN[ton].lower() in mots or ton in mots:      # « Basse Bb » : la tonalité est déjà dans le nom
        suffixe = FAMILLE_CLE.get(cle, cle)
        if suffixe.lower() in base.lower():
            return base
    return "%s %s" % (base, suffixe)
# décalage visuel (en demi-tons) introduit par les clés à indication d'octave, et clé de base
DECALAGE_CLE = {"G8vb": (12, "G"), "F8vb": (12, "F"), "G15mb": (24, "G"), "F15mb": (24, "F")}


def sans_accent(s):
    return (s.lower().replace("é", "e").replace("è", "e").replace("û", "u")
            .replace("♭", "b").strip())


def analyser_propriete(instrument, valeur):
    """'Sib fa ; Ut sol +1 ; Sax alto = Mib sol' -> liste de dérivées."""
    resultat = []
    for morceau in re.split(r"[;|\n]+", valeur):
        morceau = morceau.strip()
        if not morceau:
            continue
        nom = None
        if "=" in morceau:
            nom, morceau = [x.strip() for x in morceau.split("=", 1)]
        ton, cle, octave = None, "G", 0
        for mot in morceau.replace(",", " ").split():
            m = sans_accent(mot)
            if ton is None and ALIAS_TONALITES.get(m, m) in TONALITES:   # 1er mot = tonalité
                ton = ALIAS_TONALITES.get(m, m)
            elif m in CLES:                          # ensuite « sol », « fa »… = clé
                cle = CLES[m]
            elif re.fullmatch(r"[+-]\d", m):
                octave = int(m)
            elif m in ("cle", "clef", "de", "d'", "en", "octave", "oct"):
                pass
            else:
                raise SystemExit("Propriété « parties %s » : mot non compris « %s »" % (instrument, mot))
        if not ton:
            raise SystemExit("Propriété « parties %s » : tonalité manquante dans « %s »" % (instrument, morceau))
        nom = nom_complet(nom or instrument, ton, cle)
        resultat.append({"nom": nom, "tonalite": ton, "octave": octave, "clef": cle})
    return resultat


ERREURS_PROPRIETES = []


def lire_proprietes_partition(chemin_mscz):
    """Propriétés de la partition nommées « parties <instrument> » ou simplement « <instrument> »."""
    voix = {}
    with zipfile.ZipFile(chemin_mscz) as z:
        racine = ET.fromstring(z.read(fichier_principal(z)))
    score = racine.find("Score")
    instruments = set()
    for p in score.findall("Part"):
        instruments.update(n.lower() for n in noms_possibles(p))
    for mt in score.findall("metaTag"):
        nom = (mt.get("name") or "").strip()
        valeur = (mt.text or "").strip()
        if not valeur:
            continue
        m = re.match(r"(?i)parties?\s*[:\-]?\s+(.+)$", nom)
        if m:
            instrument = m.group(1).strip()
        elif nom.lower() in instruments:
            instrument = nom
        else:
            continue
        try:
            voix[instrument] = analyser_propriete(instrument, valeur)
        except SystemExit as e:
            ERREURS_PROPRIETES.append(str(e))
    return voix


def charger_config(chemin_partition):
    with open(FICHIER_CONFIG, encoding="utf-8") as f:
        cfg = json.load(f)
    if cfg.get("formats_v", 1) < 2:        # ancien réglage : « pdf » voulait dire « tout en PDF »
        cfg["formats"] = ["pdfunique" if x == "pdf" else x for x in cfg.get("formats", [])]
    voix = lire_proprietes_partition(chemin_partition)
    if voix:
        cfg["voix"] = voix
        cfg["source_voix"] = "propriétés de la partition"
        return cfg
    perso = os.path.splitext(chemin_partition)[0] + ".parties.json"
    if os.path.isfile(perso):
        with open(perso, encoding="utf-8") as f:
            cfg["voix"] = json.load(f).get("voix", {})
        cfg["source_voix"] = os.path.basename(perso)
        return cfg
    cfg["source_voix"] = "parties_config.json (valeurs par défaut)"
    return cfg


def trouver_musescore(cfg):
    if cfg.get("musescore") and os.path.isfile(cfg["musescore"]):
        return cfg["musescore"]
    candidats = []
    systeme = platform.system()
    if systeme == "Windows":
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
            candidats += [os.path.join(base, "MuseScore 4", "bin", "MuseScore4.exe"),
                          os.path.join(base, "MuseScore Studio 4", "bin", "MuseScore4.exe")]
    elif systeme == "Darwin":
        candidats += ["/Applications/MuseScore 4.app/Contents/MacOS/mscore",
                      "/Applications/MuseScore Studio 4.app/Contents/MacOS/mscore"]
    for nom in ("mscore4portable", "musescore4", "mscore4", "mscore", "musescore"):
        w = shutil.which(nom)
        if w:
            candidats.append(w)
    for c in candidats:
        if os.path.isfile(c):
            return c
    raise SystemExit("MuseScore introuvable : indiquez son chemin dans parties_config.json (clé \"musescore\").")


def fichiers_recents_musescore():
    """Liste des fichiers récents tenue par MuseScore 4 (recent_files.json)."""
    systeme = platform.system()
    if systeme == "Windows":
        base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "MuseScore", "MuseScore4")
    elif systeme == "Darwin":
        base = os.path.expanduser("~/Library/Application Support/MuseScore/MuseScore4")
    else:
        base = os.path.expanduser("~/.local/share/MuseScore/MuseScore4")
    chemin = os.path.join(base, "recent_files.json")
    try:
        with open(chemin, encoding="utf-8") as f:
            liste = json.load(f)
    except Exception:
        return []
    return [x["path"] if isinstance(x, dict) else x for x in liste]


def trouver_partition(cfg, args):
    """Argument = chemin d'un .mscz, ou --nom <nom de la partition> (envoyé par le plugin)."""
    if len(args) >= 2 and args[0] == "--nom":
        nom = args[1]
        candidats = [p for p in fichiers_recents_musescore()
                     if os.path.splitext(os.path.basename(p))[0] == nom
                     and p.lower().endswith(".mscz") and os.path.isfile(p)]
        dossier = os.path.expanduser(cfg.get("dossier_arrangements", ""))
        if os.path.isdir(dossier):
            for racine, dirs, fichiers in os.walk(dossier):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                if nom + ".mscz" in fichiers:
                    candidats.append(os.path.join(racine, nom + ".mscz"))
        if not candidats:
            raise SystemExit("Partition « %s.mscz » introuvable.\nEnregistrez-la au moins une fois "
                             "(Fichier > Enregistrer sous) puis relancez." % nom)
        # le fichier qui vient d'être enregistré est le plus récent
        return max(candidats, key=os.path.getmtime)
    if args:
        return os.path.abspath(args[0])
    raise SystemExit("Aucune partition indiquée.")


def attendre_fin_enregistrement(chemin, maxi=15):
    """Le plugin déclenche l'enregistrement juste avant : attendre que le fichier soit stable."""
    prec = None
    for _ in range(maxi * 2):
        try:
            etat = (os.path.getmtime(chemin), os.path.getsize(chemin))
            if etat == prec:
                zipfile.ZipFile(chemin).close()
                return
            prec = etat
        except (OSError, zipfile.BadZipFile):
            prec = None
        time.sleep(0.5)


def fichier_principal(z):
    try:
        cont = ET.fromstring(z.read("META-INF/container.xml"))
        for rf in cont.iter("rootfile"):
            if rf.get("full-path", "").endswith(".mscx"):
                return rf.get("full-path")
    except Exception:
        pass
    return [n for n in z.namelist() if n.endswith(".mscx") and "/" not in n][0]


# ---------------------------------------------------------------------------
#  Fabrication des parties dérivées dans le XML
# ---------------------------------------------------------------------------
# Éléments « système » ou de mise en page à ne pas dupliquer sur les portées dérivées
A_SUPPRIMER = {"VBox", "HBox", "TBox", "FBox", "Clef", "Marker", "Jump", "Tempo",
               "RehearsalMark", "SystemText", "LayoutBreak", "InstrumentChange",
               "eid", "linkedTo"}
SPANNERS_SYSTEME = {"Volta"}


def nettoyer(elem):
    for enfant in list(elem):
        if enfant.tag in A_SUPPRIMER or (enfant.tag == "Spanner" and enfant.get("type") in SPANNERS_SYSTEME):
            elem.remove(enfant)
        else:
            nettoyer(enfant)


def set_tag(parent, tag, texte, apres=None):
    el = parent.find(tag)
    if el is None:
        el = ET.Element(tag)
        idx = len(parent)
        if apres is not None and parent.find(apres) is not None:
            idx = list(parent).index(parent.find(apres)) + 1
        parent.insert(idx, el)
    el.text = str(texte)
    return el


def noms_possibles(part):
    noms = [part.findtext("trackName"), part.findtext("Instrument/longName"),
            part.findtext("Instrument/trackName")]
    return [n.strip() for n in noms if n and n.strip()]


def nom_instrument(part):
    return (part.findtext("Instrument/longName") or part.findtext("trackName") or "?").strip()


def creer_parties_derivees(score, voix_cfg, journal):
    parts = score.findall("Part")
    staves = score.findall("Staff")
    # correspondance part -> liste des numéros de portées (1..n)
    num = 1
    portees_de = {}
    for p in parts:
        n = len(p.findall("Staff"))
        portees_de[p] = list(range(num, num + n))
        num += n
    staff_par_id = {int(s.get("id")): s for s in staves}
    prochain_staff = max(staff_par_id) + 1
    prochain_part = max(int(p.get("id")) for p in parts) + 1
    dernier_staff = staves[-1]

    nouvelles_parts, nouveaux_staffs, controles = [], [], []
    noms_cfg = {k.strip().lower(): v for k, v in voix_cfg.items()}

    for p in parts:
        nom = nom_instrument(p)
        derivees = None
        for cle in noms_possibles(p):
            derivees = derivees or noms_cfg.get(cle.lower())
        if not derivees:
            continue
        if len(portees_de[p]) != 1:
            journal.append("  ! « %s » a plusieurs portées : ignoré." % nom)
            continue
        source = staff_par_id[portees_de[p][0]]
        for d in derivees:
            ton = d.get("tonalite", "ut").lower().replace("♭", "b").replace("é", "e")
            if ton not in TONALITES:
                raise SystemExit("Tonalité inconnue « %s » (possibles : %s)" % (d.get("tonalite"), ", ".join(TONALITES)))
            diat, chrom = TONALITES[ton]
            octv = int(d.get("octave", 0))
            diat += 7 * octv
            chrom += 12 * octv
            delta = interval_en_quintes(diat, chrom)
            clef = d.get("clef", "G")
            nom_partie = d["nom"]

            # ---- <Part> ----
            np_ = copy.deepcopy(p)
            np_.set("id", str(prochain_part))
            prochain_part += 1
            for st in np_.findall("Staff"):
                for t in ("eid", "linkedTo", "bracket", "barLineSpan", "defaultClef",
                          "defaultConcertClef", "defaultTransposingClef"):
                    for x in st.findall(t):
                        st.remove(x)
                st.append(ET.Element("defaultClef"))
                st.find("defaultClef").text = clef
            for x in np_.findall("show"):
                np_.remove(x)
            show = ET.Element("show")
            show.text = "0"                       # masquée dans le conducteur
            np_.insert(list(np_).index(np_.find("Staff")) + 1, show)
            set_tag(np_, "trackName", nom_partie)
            inst = np_.find("Instrument")
            for t in ("clef", "concertClef", "transposingClef", "transposeDiatonic", "transposeChromatic"):
                for x in inst.findall(t):
                    inst.remove(x)
            set_tag(inst, "longName", nom_partie)
            set_tag(inst, "shortName", d.get("abrege", nom_partie))
            set_tag(inst, "trackName", nom_partie)
            ancre = "instrumentId" if inst.find("instrumentId") is not None else "trackName"
            if chrom:
                set_tag(inst, "transposeChromatic", -chrom, apres=ancre)
                set_tag(inst, "transposeDiatonic", -diat, apres=ancre)
            set_tag(inst, "clef", clef, apres=ancre)
            for ch in inst.findall("Channel"):
                for t in ("midiPort", "midiChannel"):
                    for x in ch.findall(t):
                        ch.remove(x)
            nouvelles_parts.append(np_)

            # ---- <Staff> : copie du contenu musical ----
            ns = copy.deepcopy(source)
            ns.set("id", str(prochain_staff))
            prochain_staff += 1
            nettoyer(ns)
            nb_notes = 0
            for note in ns.iter("Note"):
                for x in note.findall("tpc2"):
                    note.remove(x)
                tpc = note.find("tpc")
                if tpc is not None and delta:
                    t2 = ET.Element("tpc2")
                    t2.text = str(transposer_tpc(int(tpc.text), delta))
                    note.insert(list(note).index(tpc) + 1, t2)
                nb_notes += 1
            for ks in ns.iter("KeySig"):
                for x in ks.findall("actualKey"):
                    ks.remove(x)
                ck = ks.find("concertKey")
                if ck is not None and delta:
                    ak = ET.Element("actualKey")
                    ak.text = str(transposer_armure(int(ck.text), delta))
                    ks.insert(list(ks).index(ck) + 1, ak)
            nouveaux_staffs.append(ns)
            controles.append((ns, chrom, delta))
            journal.append("  + %-28s depuis « %s » (%s, octave %+d, clef %s) – %d notes"
                           % (nom_partie, nom, d.get("tonalite"), octv, clef, nb_notes))

    # insertion : nouvelles <Part> après la dernière <Part>, nouveaux <Staff> à la fin
    pos = list(score).index(parts[-1]) + 1
    for i, np_ in enumerate(nouvelles_parts):
        score.insert(pos + i, np_)
    pos = list(score).index(dernier_staff) + 1
    for i, ns in enumerate(nouveaux_staffs):
        score.insert(pos + i, ns)

    verifier(controles)
    return len(nouvelles_parts)


NOMS_TPC = "FCGDAEB"


def tpc_vers_classe(tpc):
    """tpc (14 = do) -> classe de hauteur 0..11"""
    nat = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
    i = tpc + 1                      # -1 = Fbb
    lettre = NOMS_TPC[i % 7]
    alt = i // 7 - 2
    return (nat[lettre] + alt) % 12


def verifier(controles):
    """Contrôle de cohérence : la note écrite (tpc2) correspond bien à hauteur + transposition."""
    for ns, chrom, delta in controles:
        for note in ns.iter("Note"):
            pitch = int(note.findtext("pitch"))
            tpc = int(note.findtext("tpc"))
            ecrit = int(note.findtext("tpc2")) if note.find("tpc2") is not None else tpc
            if tpc_vers_classe(tpc) != pitch % 12 or tpc_vers_classe(ecrit) != (pitch + chrom) % 12:
                raise SystemExit("Incohérence de transposition détectée (hauteur %d) – export annulé." % pitch)


def fabriquer_copie(chemin_mscz, dossier_tmp, voix_cfg, journal):
    copie = os.path.join(dossier_tmp, "partition_derivee.mscz")
    with zipfile.ZipFile(chemin_mscz) as zin:
        noms = zin.namelist()
        principal = fichier_principal(zin)
        racine = ET.fromstring(zin.read(principal))
        score = racine.find("Score")
        n = creer_parties_derivees(score, voix_cfg, journal)
        donnees = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(racine, encoding="utf-8")
        with zipfile.ZipFile(copie, "w", zipfile.ZIP_DEFLATED) as zout:
            for nom in noms:
                if nom == principal:
                    zout.writestr(nom, donnees)
                else:
                    zout.writestr(zin.getinfo(nom), zin.read(nom))
    return copie, n


# ---------------------------------------------------------------------------
#  Appels à MuseScore
# ---------------------------------------------------------------------------
def lancer(mscore, args, journal, quoi="MuseScore"):
    env = dict(os.environ)
    kw = {}
    if platform.system() == "Linux":
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
    if platform.system() == "Windows":
        kw["creationflags"] = 0x08000000      # CREATE_NO_WINDOW
    r = subprocess.run([mscore] + args, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kw)
    if r.returncode != 0:
        code = r.returncode & 0xFFFFFFFF
        cause = " (plantage de MuseScore)" if code >= 0xC0000000 else ""
        journal.append("  ! %s : échec, code 0x%08X%s" % (quoi, code, cause))
        err = [l for l in r.stderr.decode("utf-8", "replace").strip().splitlines()
               if "ERROR" in l or "error" in l][-3:]
        journal.extend("    " + l[-160:] for l in err)
    return r.returncode == 0


def nom_fichier(s):
    return re.sub(r'[\\/:*?"<>|]+', "_", s).strip()


EXTENSIONS_EXPORT = (".pdf", ".png", ".mid", ".mp3")


def dossier_sortie(chemin, cfg):
    titre = os.path.splitext(os.path.basename(chemin))[0]
    return os.path.join(os.path.dirname(chemin), cfg.get("dossier_sortie", "{titre} - export").format(titre=titre))


def dossier_libre(sortie):
    """« X - export » existe -> « X - export (2) », « (3) »…"""
    n = 2
    while os.path.exists("%s (%d)" % (sortie, n)):
        n += 1
    return "%s (%d)" % (sortie, n)


NOM_PDF_UNIQUE = "{titre} - conducteur et parties.pdf"
NOM_PDF_CHOIX = "{titre} - parties choisies.pdf"      # PDF unique d'une sélection partielle
CONDUCTEUR = "Conducteur"


def cle_nom(n):
    return re.sub(r"\s+", " ", (n or "").replace("♭", "b").strip().lower())


def choisi(cfg, nom):
    """Instrument coché ? (pas de sélection = tout est exporté)"""
    sel = cfg.get("selection")
    return sel is None or cle_nom(nom) in sel


def noms_parties_partition(chemin):
    """Noms des parties tels que MuseScore les exportera (parties enregistrées, sinon une par instrument)."""
    noms = []
    with zipfile.ZipFile(chemin) as z:
        try:
            cont = ET.fromstring(z.read("META-INF/container.xml"))
            chemins = [rf.get("full-path") for rf in cont.iter("rootfile")
                       if rf.get("full-path", "").startswith("Excerpts/") and rf.get("full-path").endswith(".mscx")]
        except Exception:
            chemins = []
        if not chemins:
            chemins = sorted(n for n in z.namelist() if n.startswith("Excerpts/") and n.endswith(".mscx"))
        for c in chemins:
            try:
                sc = ET.fromstring(z.read(c)).find("Score")
            except Exception:
                continue
            nom = (sc.findtext("name") or "").strip()
            if not nom:
                for mt in sc.findall("metaTag"):
                    if mt.get("name") == "partName" and (mt.text or "").strip():
                        nom = mt.text.strip()
            if nom:
                noms.append(nom)
        if not noms:
            score = ET.fromstring(z.read(fichier_principal(z))).find("Score")
            for p in score.findall("Part"):
                if p.findtext("show") != "0":
                    noms.append((p.findtext("trackName") or nom_instrument(p)).strip())
    return noms


def vider_export(sortie, titre, formats, selection=None):
    """Écraser = retirer les anciens fichiers de ce morceau, UNIQUEMENT pour les formats cochés
    (évite les parties périmées sans toucher aux autres formats) et, si seuls certains
    instruments sont choisis, UNIQUEMENT pour ces instruments."""
    if not os.path.isdir(sortie):
        return 0
    unique = NOM_PDF_UNIQUE.format(titre=titre) if selection is None else NOM_PDF_CHOIX.format(titre=titre)

    def instrument_du_fichier(f):
        base = re.sub(r"(-\d+)?\.(pdf|png)$", "", f, flags=re.I)
        if base == titre:
            return CONDUCTEUR
        if base.startswith(titre + " - "):
            return base[len(titre) + 3:]
        return None

    def concerne(f):
        if not f.startswith(titre):
            return False
        bas = f.lower()
        if f == unique:
            return "pdfunique" in formats
        if f in (NOM_PDF_UNIQUE.format(titre=titre), NOM_PDF_CHOIX.format(titre=titre)):
            return False
        if selection is not None and bas.endswith((".pdf", ".png")):
            ins = instrument_du_fichier(f)
            if ins is None or cle_nom(ins) not in {cle_nom(nom_fichier(x)) for x in selection}:
                return False
        if bas.endswith(".pdf"):
            return "pdf" in formats
        if bas.endswith(".png"):
            return "png" in formats
        if bas.endswith(".mid"):
            return "mid" in formats and f == titre + ".mid"
        if bas.endswith(".mp3"):
            return "mp3" in formats and f == titre + ".mp3"
        return False

    n = 0
    for f in os.listdir(sortie):
        if concerne(f):
            try:
                os.remove(os.path.join(sortie, f))
                n += 1
            except OSError:
                pass
    return n


def transposer_partie(src_mscz, dst_mscz, d):
    """Fabrique une partie transposée à partir de la PARTIE SOURCE déjà extraite par MuseScore :
    même mise en page (sauts, espacements, format, style), seuls instrument, clef et notes changent."""
    diat, chrom = TONALITES[d["tonalite"]]
    diat += 7 * d.get("octave", 0)
    chrom += 12 * d.get("octave", 0)
    delta = interval_en_quintes(diat, chrom)
    clef = d["clef"]
    with zipfile.ZipFile(src_mscz) as zin:
        principal = fichier_principal(zin)
        racine = ET.fromstring(zin.read(principal))
        score = racine.find("Score")
        parts = score.findall("Part")
        if len(parts) != 1 or len(parts[0].findall("Staff")) != 1:
            raise SystemExit("partie source à plusieurs portées")
        part = parts[0]
        # liens vers le conducteur : inutiles dans une partie autonome
        for parent in racine.iter():
            for x in parent.findall("linkedTo"):
                parent.remove(x)
        # ---- instrument ----
        st = part.find("Staff")
        for t in ("defaultClef", "defaultConcertClef", "defaultTransposingClef"):
            for x in st.findall(t):
                st.remove(x)
        dc = ET.SubElement(st, "defaultClef")
        dc.text = clef
        set_tag(part, "trackName", d["nom"])
        inst = part.find("Instrument")
        src_d = int(inst.findtext("transposeDiatonic") or 0)
        src_c = int(inst.findtext("transposeChromatic") or 0)
        delta_source = interval_en_quintes(-src_d, -src_c) if src_c else 0
        for t in ("clef", "concertClef", "transposingClef", "transposeDiatonic", "transposeChromatic"):
            for x in inst.findall(t):
                inst.remove(x)
        set_tag(inst, "longName", d["nom"])
        set_tag(inst, "shortName", d.get("abrege", d["nom"]))
        set_tag(inst, "trackName", d["nom"])
        ancre = "instrumentId" if inst.find("instrumentId") is not None else "trackName"
        if chrom:
            set_tag(inst, "transposeChromatic", -chrom, apres=ancre)
            set_tag(inst, "transposeDiatonic", -diat, apres=ancre)
        set_tag(inst, "clef", clef, apres=ancre)
        # ---- titre de la partie ----
        for mt in score.findall("metaTag"):
            if mt.get("name") == "partName":
                mt.text = d["nom"]
        for txt in score.iter("Text"):
            if txt.findtext("style") == "instrument_excerpt" and txt.find("text") is not None:
                txt.find("text").text = d["nom"]
        # ---- musique ----
        controles = []
        for staff in score.findall("Staff"):
            premiere = True
            for mesure in staff.iter("Measure"):
                for voix in mesure.findall("voice"):
                    for c in list(voix.findall("Clef")):
                        if premiere and c.findtext("isHeader") == "1":
                            for t in ("concertClefType", "transposingClefType"):
                                set_tag(c, t, clef)
                        else:
                            voix.remove(c)          # changements de clef en cours de morceau
                premiere = False
            # sens des hampes : celui de la partie source (choisi pour SA clef) n'a plus de sens
            # après changement de clef / d'octave -> MuseScore le recalcule (ligne du milieu,
            # même sens pour toute une ligature). On le garde seulement s'il y a plusieurs voix.
            for mesure in staff.iter("Measure"):
                voix_pleines = [v for v in mesure.findall("voice") if v.find("Chord") is not None]
                if len(voix_pleines) > 1:
                    continue
                for v in voix_pleines:
                    for el in v.iter():
                        if el.tag in ("Chord", "Beam"):
                            for sd in el.findall("StemDirection"):
                                el.remove(sd)
            for note in staff.iter("Note"):
                for x in note.findall("tpc2"):
                    note.remove(x)
                tpc = note.find("tpc")
                if tpc is not None and delta:
                    t2 = ET.Element("tpc2")
                    t2.text = str(transposer_tpc(int(tpc.text), delta))
                    note.insert(list(note).index(tpc) + 1, t2)
            for ks in staff.iter("KeySig"):
                for x in ks.findall("actualKey"):
                    ks.remove(x)
                ck = ks.find("concertKey")
                if ck is not None and delta:
                    ak = ET.Element("actualKey")
                    ak.text = str(transposer_armure(int(ck.text), delta))
                    ks.insert(list(ks).index(ck) + 1, ak)
            # accords chiffrés : stockés à la hauteur ÉCRITE de la portée -> on les décale aussi
            delta_harm = delta - delta_source
            if delta_harm:
                for h in staff.iter("Harmony"):
                    for info in [h] + h.findall("harmonyInfo"):
                        for t in ("root", "bass"):
                            el = info.find(t)
                            if el is not None and el.text and el.text.strip().lstrip("-").isdigit():
                                el.text = str(transposer_tpc(int(el.text), delta_harm))
            controles.append((staff, chrom, delta))
        verifier(controles)
        donnees = b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(racine, encoding="utf-8")
        with zipfile.ZipFile(dst_mscz, "w", zipfile.ZIP_DEFLATED) as zout:
            for nom in zin.namelist():
                if nom == principal:
                    zout.writestr(nom, donnees)
                elif not nom.startswith("Thumbnails/"):
                    zout.writestr(zin.getinfo(nom), zin.read(nom))


def noms_instrument_partie(mscz):
    with zipfile.ZipFile(mscz) as z:
        score = ET.fromstring(z.read(fichier_principal(z))).find("Score")
    noms = []
    for p in score.findall("Part"):
        noms += noms_possibles(p)
    return [n.lower() for n in noms]


def fusionner_pdf(fichiers, sortie_pdf, journal):
    """PDF unique conducteur + parties (module pypdf, installé automatiquement si besoin)."""
    try:
        from pypdf import PdfWriter
    except ImportError:
        kw = {"creationflags": 0x08000000} if platform.system() == "Windows" else {}
        subprocess.run([sys.executable, "-m", "pip", "install", "--user", "-q", "pypdf"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
        try:
            import site
            import importlib
            sys.path.append(site.getusersitepackages())
            importlib.invalidate_caches()
            from pypdf import PdfWriter
        except Exception:
            journal.append("  ! PDF « conducteur et parties » non créé : module pypdf absent "
                           "(commande : py -m pip install pypdf)")
            return False
    w = PdfWriter()
    for f in fichiers:
        if os.path.isfile(f):
            w.append(f)
    with open(sortie_pdf, "wb") as out:
        w.write(out)
    return True


def ranger_pages(fichiers_png, cible_sans_ext):
    """x-1.png, x-2.png -> « cible-1.png »… ; une seule page -> « cible.png »."""
    fichiers_png = sorted(fichiers_png, key=lambda f: int(re.search(r"-(\d+)\.png$", f).group(1))
                          if re.search(r"-(\d+)\.png$", f) else 0)
    if len(fichiers_png) == 1:
        shutil.move(fichiers_png[0], cible_sans_ext + ".png")
        return 1
    for f in fichiers_png:
        m = re.search(r"-(\d+)\.png$", f)
        shutil.move(f, "%s-%s.png" % (cible_sans_ext, m.group(1) if m else "1"))
    return len(fichiers_png)


def exporter(chemin, cfg, etape=lambda texte: None, sortie=None):
    t0 = time.time()
    journal = ["Partition : " + chemin]
    mscore = trouver_musescore(cfg)
    titre = os.path.splitext(os.path.basename(chemin))[0]
    sortie = sortie or dossier_sortie(chemin, cfg)
    formats = [f.lower() for f in cfg.get("formats", ["pdfunique", "png", "mid", "mp3"])]
    selection = cfg.get("selection")
    if selection is not None:
        journal.append("Instruments choisis : " + ", ".join(cfg.get("selection_noms", [])))
    if os.path.isdir(sortie) and cfg.get("ecraser", True):
        n = vider_export(sortie, titre, formats, selection)
        if n:
            journal.append("Anciens fichiers remplacés (formats cochés seulement) : %d" % n)
    os.makedirs(sortie, exist_ok=True)
    avec_pdf = "pdf" in formats or "pdfunique" in formats
    base = os.path.join(sortie, titre)

    with tempfile.TemporaryDirectory(prefix="mscore_export_") as tmp:
        local = os.path.join(tmp, "conducteur.mscz")      # copie locale : MuseScore ne lit pas sur V:
        shutil.copy2(chemin, local)

        # 1. MIDI / MP3 du conducteur (un appel par format : un plantage n'emporte pas les autres)
        ok = []
        for fmt in [f for f in formats if f in ("mid", "mp3")]:
            etape("Conducteur : export %s" % fmt.upper())
            cible = os.path.join(tmp, "out_" + fmt)
            os.makedirs(cible, exist_ok=True)
            if lancer(mscore, ["-o", os.path.join(cible, "x." + fmt), local], journal, "export " + fmt.upper()):
                produits = os.listdir(cible)
                for nomf in produits:
                    shutil.move(os.path.join(cible, nomf), base + nomf[1:])
                if produits:
                    ok.append(fmt.upper())
                else:
                    journal.append("  ! export %s : aucun fichier produit" % fmt.upper())
        if ok:
            journal.append("Conducteur : " + ", ".join(ok))

        if not avec_pdf and "png" not in formats:
            journal.append("Terminé en %.0f s → %s" % (time.time() - t0, sortie))
            return sortie, journal

        # 2. Extraction de toutes les parties, chacune avec SA mise en page
        etape("Extraction des parties")
        parts_json = os.path.join(tmp, "parties.json")
        parties = []        # (nom, fichier mscz, dérivée ?)
        if lancer(mscore, [local, "--score-parts", "-o", parts_json], journal, "extraction des parties") \
                and os.path.isfile(parts_json):
            with open(parts_json, encoding="utf-8") as f:
                data = json.load(f)
            for i, (nom, b64) in enumerate(zip(data.get("parts", []), data.get("partsBin", []))):
                fp = os.path.join(tmp, "partie_%02d.mscz" % i)
                with open(fp, "wb") as f:
                    f.write(base64.b64decode(b64))
                parties.append((nom, fp, False))

        # 3. Parties transposées, fabriquées depuis la partie source (même mise en page)
        etape("Fabrication des parties transposées")
        journal.append("Parties transposées (d'après %s) :" % cfg.get("source_voix", "?"))
        voix = {k.strip().lower(): v for k, v in cfg.get("voix", {}).items()}
        resultat, n, deja = [], 0, set()
        for nom, fp, _ in parties:
            if choisi(cfg, nom):
                resultat.append((nom, fp, False))
            specs = None
            for cle in [nom.lower()] + noms_instrument_partie(fp):
                if cle in voix and cle not in deja:
                    specs = voix[cle]
                    deja.add(cle)
                    break
            for d in specs or []:
                if not choisi(cfg, d["nom"]):
                    continue
                dst = os.path.join(tmp, "derivee_%02d.mscz" % n)
                n += 1
                try:
                    transposer_partie(fp, dst, d)
                    resultat.append((d["nom"], dst, True))
                    journal.append("  + %-34s ← %s (même mise en page)" % (d["nom"], nom))
                except SystemExit as e:
                    journal.append("  ! %s : %s" % (d["nom"], e))
        parties = resultat
        if n == 0 and selection is None:
            journal.append("  aucune (pas de propriété « <instrument> » dans cette partition,\n"
                           "  ou nom d'instrument différent de celui de la partition)")
        elif n == 0:
            journal.append("  aucune parmi les instruments choisis")

        # 4. PDF et PNG du conducteur et de toutes les parties : un seul appel à MuseScore
        exts = [x for x in ("pdf", "png") if (avec_pdf if x == "pdf" else x in formats)]
        quoi = " + ".join(x.upper() for x in exts)
        etape("%s de %s%d partie(s)" % (quoi, "conducteur et " if choisi(cfg, CONDUCTEUR) else "", len(parties)))
        dout = os.path.join(tmp, "out")
        os.makedirs(dout, exist_ok=True)
        avec_conducteur = choisi(cfg, CONDUCTEUR)
        sources = ([("conducteur", local)] if avec_conducteur else []) + \
                  [("p%02d" % i, fp) for i, (_, fp, _) in enumerate(parties)]
        if not sources:
            journal.append("Aucun instrument choisi pour les PDF / PNG")
            journal.append("Terminé en %.0f s → %s" % (time.time() - t0, sortie))
            return sortie, journal
        job = [{"in": src, "out": [os.path.join(dout, cle + "." + x) for x in exts]}
               for cle, src in sources]
        fjob = os.path.join(tmp, "job.json")
        with open(fjob, "w", encoding="utf-8") as f:
            json.dump(job, f, ensure_ascii=False)
        lancer(mscore, ["-j", fjob], journal, "export " + quoi)

        cibles = {"conducteur": base}
        for i, (nom, _, _) in enumerate(parties):
            cibles["p%02d" % i] = "%s - %s" % (base, nom_fichier(nom))
        nb_pdf, nb_png, pdfs_ordre, manquants = 0, 0, [], []
        for cle, _ in sources:
            if avec_pdf:
                f = os.path.join(dout, cle + ".pdf")
                if os.path.isfile(f):
                    if "pdf" in formats:            # PDF séparés demandés : on les range
                        shutil.move(f, cibles[cle] + ".pdf")
                        f = cibles[cle] + ".pdf"
                    pdfs_ordre.append(f)
                    nb_pdf += 1
                else:
                    manquants.append(os.path.basename(cibles[cle]))
            if "png" in formats:
                pages = [os.path.join(dout, x) for x in os.listdir(dout)
                         if re.fullmatch(re.escape(cle) + r"(-\d+)?\.png", x)]
                if pages:
                    nb_png += ranger_pages(pages, cibles[cle])
                else:
                    manquants.append(os.path.basename(cibles[cle]) + " (PNG)")
        nb_p = nb_pdf - (1 if avec_conducteur and nb_pdf else 0)
        quoi_pdf = ("conducteur + %d parties" if avec_conducteur else "%d parties") % max(0, nb_p)
        if "pdfunique" in formats and pdfs_ordre:
            modele = NOM_PDF_UNIQUE if selection is None else NOM_PDF_CHOIX
            unique = os.path.join(sortie, modele.format(titre=titre))
            if fusionner_pdf(pdfs_ordre, unique, journal):
                journal.append("PDF unique : %s → %s" % (quoi_pdf, os.path.basename(unique)))
        if "pdf" in formats:
            journal.append("PDF séparés : " + quoi_pdf)
        if "png" in formats:
            journal.append("PNG : %d image(s)" % nb_png)
        for m in manquants:
            journal.append("  ! non produit : " + m)

    journal.append("Terminé en %.0f s → %s" % (time.time() - t0, sortie))
    return sortie, journal


NOTES_FR = {"C": "do", "D": "ré", "E": "mi", "F": "fa", "G": "sol", "A": "la", "B": "si"}
ALT_FR = {-2: "bb", -1: "b", 0: "", 1: "#", 2: "x"}
# zone lisible (hauteur écrite MIDI) par clé : environ 4-5 lignes supplémentaires max
ZONE_LISIBLE = {"G": (53, 88), "F": (33, 67), "C3": (43, 78), "C4": (40, 74), "C1": (50, 84)}


def nom_note(pitch, tpc):
    i = tpc + 1
    lettre = "FCGDAEB"[i % 7]
    alt = i // 7 - 2
    octave_fr = (pitch - alt) // 12 - 2          # convention française : do3 = do central
    return "%s%s%d" % (NOTES_FR[lettre], ALT_FR.get(alt, "?"), octave_fr)


def tessiture(score, part, d):
    """Tessiture écrite (min, max) de la partie dérivée, + alerte éventuelle."""
    num = 1
    for p in score.findall("Part"):
        if p is part:
            break
        num += len(p.findall("Staff"))
    staff = [s for s in score.findall("Staff") if s.get("id") == str(num)]
    notes = [(int(n.findtext("pitch")), int(n.findtext("tpc"))) for n in staff[0].iter("Note")] if staff else []
    if not notes:
        return "", None
    diat, chrom = TONALITES[d["tonalite"]]
    diat += 7 * d.get("octave", 0)
    chrom += 12 * d.get("octave", 0)
    delta = interval_en_quintes(diat, chrom)
    bas, haut = min(notes), max(notes)
    # position VUE sur la portée : hauteur écrite + décalage de la clé à octave éventuelle
    vu, cle_base = DECALAGE_CLE.get(d["clef"], (0, d["clef"]))
    texte = "%s → %s" % (nom_note(bas[0] + chrom + vu, transposer_tpc(bas[1], delta)),
                         nom_note(haut[0] + chrom + vu, transposer_tpc(haut[1], delta)))
    lo, hi = ZONE_LISIBLE.get(cle_base, (0, 127))
    alerte = None
    if haut[0] + chrom + vu > hi:
        alerte = "« %s » : écrit très aigu pour la %s (%s) — octave trop haute ?" % (
            d["nom"], NOMS_CLES.get(d["clef"], d["clef"]), texte)
    elif bas[0] + chrom + vu < lo:
        alerte = "« %s » : écrit très grave pour la %s (%s) — octave trop basse ?" % (
            d["nom"], NOMS_CLES.get(d["clef"], d["clef"]), texte)
    return texte, alerte


ALERTES_TESSITURE = []


def plan_export(chemin, cfg):
    """Ce qui va être fait, pour la fenêtre de confirmation."""
    with zipfile.ZipFile(chemin) as z:
        score = ET.fromstring(z.read(fichier_principal(z))).find("Score")
    voix = {k.strip().lower(): (k, v) for k, v in cfg.get("voix", {}).items()}
    utilisees = set()
    lignes = []
    for p in score.findall("Part"):
        nom = nom_instrument(p)
        trouve = None
        for cle in noms_possibles(p):
            if cle.lower() in voix:
                trouve = cle.lower()
                break
        if p.findtext("show") == "0":
            nom += "  (masqué)"
        if trouve:
            utilisees.add(trouve)
            for d in voix[trouve][1]:
                d = dict(d)
                d["tessiture"], alerte = tessiture(score, p, d)
                if alerte:
                    ALERTES_TESSITURE.append(alerte)
                lignes.append((nom, d))
        else:
            lignes.append((nom, None))
    orphelines = [voix[k][0] for k in voix if k not in utilisees]
    return lignes, orphelines


def decrire(d):
    t = TON_EN[d["tonalite"]]
    txt = "%s, %s" % (t, NOMS_CLES.get(d["clef"], d["clef"]))
    if d.get("octave"):
        txt += ", %+d octave" % d["octave"]
    return txt


def nb_etapes(cfg):
    formats = [f.lower() for f in cfg.get("formats", [])]
    n = len([f for f in formats if f in ("mid", "mp3")])
    if "pdf" in formats or "pdfunique" in formats or "png" in formats:
        n += 3
    return n


def memoriser_formats(formats):
    """Garde les formats cochés pour la prochaine fois (dans parties_config.json)."""
    try:
        with open(FICHIER_CONFIG, encoding="utf-8") as f:
            c = json.load(f)
        if c.get("formats") != formats or c.get("formats_v") != 2:
            c["formats"] = formats
            c["formats_v"] = 2
            with open(FICHIER_CONFIG, "w", encoding="utf-8") as f:
                json.dump(c, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def ouvrir_dossier(sortie):
    if platform.system() == "Windows":
        os.startfile(sortie)
    elif platform.system() == "Darwin":
        subprocess.run(["open", sortie])


def fenetre(chemin, cfg):
    """Fenêtre unique : confirmation, puis progression animée, puis résultat.
    Renvoie False si tkinter est indisponible (le script passe alors en mode simple)."""
    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception:
        return False
    import threading
    import queue

    lignes, orphelines = plan_export(chemin, cfg)
    titre = os.path.splitext(os.path.basename(chemin))[0]
    sortie = os.path.join(os.path.dirname(chemin), cfg.get("dossier_sortie", "{titre} - export").format(titre=titre))
    nb = sum(1 for _, d in lignes if d)

    w = tk.Tk()
    w.title("Export global — " + titre)
    w.attributes("-topmost", True)
    w.minsize(920, 420)
    racine = ttk.Frame(w, padding=14)
    racine.pack(fill="both", expand=True)
    ttk.Label(racine, text=titre, font=("Segoe UI", 13, "bold")).pack(anchor="w")
    ttk.Label(racine, text=chemin, foreground="#666").pack(anchor="w", pady=(0, 10))
    corps = ttk.Frame(racine)
    corps.pack(fill="both", expand=True)
    boutons = ttk.Frame(racine)
    boutons.pack(anchor="e", pady=(10, 0))

    def vider():
        for x in list(corps.winfo_children()) + list(boutons.winfo_children()):
            x.destroy()

    # instruments proposés : conducteur, parties de la partition, parties transposées
    instruments = [CONDUCTEUR]
    try:
        originaux = noms_parties_partition(chemin)
    except Exception:
        originaux = []
    derivees = [d["nom"] for _, d in lignes if d]
    for n in originaux + derivees:
        if cle_nom(n) not in {cle_nom(x) for x in instruments}:
            instruments.append(n)
    choix_instr = {n: tk.BooleanVar(value=True) for n in instruments}
    resume_instr = tk.StringVar()

    def maj_resume():
        coches = [n for n in instruments if choix_instr[n].get()]
        if len(coches) == len(instruments):
            resume_instr.set("Tous les instruments (%d)" % len(instruments))
        elif not coches:
            resume_instr.set("Aucun instrument")
        else:
            txt = ", ".join(coches)
            if len(txt) > 90:
                txt = txt[:87] + "…"
            resume_instr.set("%d sur %d : %s" % (len(coches), len(instruments), txt))
        maj_bouton()

    def fenetre_instruments():
        top = tk.Toplevel(w)
        top.title("Instruments à exporter")
        top.transient(w)
        top.attributes("-topmost", True)
        top.resizable(False, True)
        cadre_h = ttk.Frame(top, padding=(14, 12, 14, 4))
        cadre_h.pack(fill="x")
        tous = tk.BooleanVar(value=all(v.get() for v in choix_instr.values()))

        def basculer_tous():
            for v in choix_instr.values():
                v.set(tous.get())
            maj_resume()

        def maj_tous():
            tous.set(all(v.get() for v in choix_instr.values()))
            maj_resume()

        ttk.Checkbutton(cadre_h, text="Tous les instruments", variable=tous,
                        command=basculer_tous).pack(anchor="w")
        ttk.Separator(top).pack(fill="x", padx=14, pady=4)
        # liste défilante
        zone = ttk.Frame(top, padding=(14, 0, 4, 0))
        zone.pack(fill="both", expand=True)
        toile = tk.Canvas(zone, highlightthickness=0, width=380,
                          height=min(460, 26 * (len(instruments) + 3)))
        barre_d = ttk.Scrollbar(zone, orient="vertical", command=toile.yview)
        liste = ttk.Frame(toile)
        liste.bind("<Configure>", lambda e: toile.configure(scrollregion=toile.bbox("all")))
        toile.create_window((0, 0), window=liste, anchor="nw")
        toile.configure(yscrollcommand=barre_d.set)
        toile.pack(side="left", fill="both", expand=True)
        if 26 * (len(instruments) + 3) > 460:
            barre_d.pack(side="right", fill="y")
            toile.bind_all("<MouseWheel>", lambda e: toile.yview_scroll(int(-e.delta / 120), "units"))

        def groupe(titre_g, noms):
            if not noms:
                return
            ttk.Label(liste, text=titre_g, foreground="#666").pack(anchor="w", pady=(6, 0))
            for n in noms:
                ttk.Checkbutton(liste, text=n, variable=choix_instr[n], command=maj_tous).pack(anchor="w", padx=(12, 0))

        groupe("Conducteur", [CONDUCTEUR])
        groupe("Parties", [n for n in instruments[1:] if n not in derivees])
        groupe("Parties transposées", [n for n in instruments[1:] if n in derivees])

        bas = ttk.Frame(top, padding=(14, 8, 14, 12))
        bas.pack(fill="x")

        def fermer():
            toile.unbind_all("<MouseWheel>")
            top.destroy()

        ttk.Button(bas, text="OK", command=fermer).pack(side="right")
        top.bind("<Return>", lambda *_: fermer())
        top.bind("<Escape>", lambda *_: fermer())
        top.protocol("WM_DELETE_WINDOW", fermer)
        top.update_idletasks()                      # centrée sur la fenêtre principale
        x = w.winfo_rootx() + max(0, (w.winfo_width() - top.winfo_reqwidth()) // 2)
        y = w.winfo_rooty() + max(0, (w.winfo_height() - top.winfo_reqheight()) // 3)
        top.geometry("+%d+%d" % (x, y))
        top.grab_set()
        top.focus_force()

    cible = {}
    choix_formats = {}
    choix_dossier = tk.StringVar(value="ecraser" if cfg.get("ecraser", True) else "nouveau")
    etat_bouton = {}

    def maj_bouton():
        if "b" in etat_bouton:
            formats = [c for c, v in choix_formats.items() if v.get()]
            un_instr = any(v.get() for v in choix_instr.values())
            ok = bool(formats) and (un_instr or any(f in ("mid", "mp3") for f in formats))
            etat_bouton["b"].state(["!disabled"] if ok else ["disabled"])

    # ---------------- 1. confirmation ----------------
    def page_confirmation():
        ttk.Label(corps, text="Parties transposées (d'après %s)" % cfg.get("source_voix", "?"),
                  font=("Segoe UI", 10, "bold")).pack(anchor="w")
        arbre = ttk.Treeview(corps, columns=("partie", "regle", "tess"), show="tree headings",
                             height=min(20, len({n for n, _ in lignes}) + nb))
        for col, txt, larg in (("#0", "Instrument de la partition", 200), ("partie", "Partie générée", 300),
                               ("regle", "Transposition", 240), ("tess", "Tessiture lue", 150)):
            arbre.heading(col, text=txt)
            arbre.column(col, width=larg)
        noeuds = {}
        for nom, d in lignes:
            if nom not in noeuds:
                noeuds[nom] = arbre.insert("", "end", text=nom, open=True,
                                           values=("" if d else "— (partie normale uniquement)", "", ""))
            if d:
                arbre.insert(noeuds[nom], "end", text="", values=(d["nom"], decrire(d), d.get("tessiture", "")))
        arbre.pack(fill="both", expand=True, pady=(2, 8))

        alertes = list(ERREURS_PROPRIETES) + list(ALERTES_TESSITURE)
        for o in orphelines:
            alertes.append("Propriété « %s » : aucun instrument de ce nom dans la partition." % o)
        if nb == 0 and not alertes:
            alertes.append("Aucune partie transposée : ajoutez des propriétés « <instrument> » "
                           "(Fichier > Propriétés de la partition).")
        for a in alertes:
            ttk.Label(corps, text="⚠ " + a, foreground="#b45309", wraplength=880, justify="left").pack(anchor="w")
        ttk.Label(corps, text="Tessiture lue = position des notes sur la portée, notation française (do3 = do central).",
                  foreground="#666").pack(anchor="w", pady=(6, 0))
        # --- formats ---
        cadre = ttk.LabelFrame(corps, text=" Formats à exporter ", padding=(10, 4))
        cadre.pack(fill="x", pady=(10, 0))
        actuels = [x.lower() for x in cfg.get("formats", ["pdfunique", "png", "mid", "mp3"])]
        for code, texte in (("pdfunique", "PDF unique (conducteur + parties)"), ("pdf", "PDF séparés"),
                            ("png", "PNG"), ("mid", "MIDI"), ("mp3", "Audio MP3")):
            v = tk.BooleanVar(value=code in actuels)
            choix_formats[code] = v
            ttk.Checkbutton(cadre, text=texte, variable=v, command=maj_bouton).pack(side="left", padx=(0, 18))

        # --- instruments ---
        cadre_i = ttk.LabelFrame(corps, text=" Instruments à exporter ", padding=(10, 4))
        cadre_i.pack(fill="x", pady=(8, 0))
        ttk.Button(cadre_i, text="Instruments…", command=fenetre_instruments).pack(side="left")
        ttk.Label(cadre_i, textvariable=resume_instr, foreground="#444").pack(side="left", padx=(12, 0))
        maj_resume()

        # --- dossier ---
        cadre2 = ttk.LabelFrame(corps, text=" Dossier d'export ", padding=(10, 4))
        cadre2.pack(fill="x", pady=(8, 0))
        if os.path.isdir(sortie):
            ttk.Label(cadre2, text="« %s » existe déjà :" % os.path.basename(sortie)).pack(anchor="w")
            ttk.Radiobutton(cadre2, text="Écraser l'export précédent (seuls les formats cochés sont remplacés)",
                            variable=choix_dossier, value="ecraser").pack(anchor="w")
            ttk.Radiobutton(cadre2, text="Garder l'ancien et créer « %s »" % os.path.basename(dossier_libre(sortie)),
                            variable=choix_dossier, value="nouveau").pack(anchor="w")
        else:
            ttk.Label(cadre2, text=sortie, foreground="#444").pack(anchor="w")

        ttk.Button(boutons, text="Annuler", command=w.destroy).pack(side="right")
        b = ttk.Button(boutons, text="Exporter", command=page_progression)
        etat_bouton["b"] = b
        b.pack(side="right", padx=(0, 8))
        b.focus_set()
        w.bind("<Return>", lambda *_: page_progression())
        w.bind("<Escape>", lambda *_: w.destroy())

    # ---------------- 2. progression ----------------
    def page_progression():
        if choix_formats:
            formats = [c for c, v in choix_formats.items() if v.get()]
            if not formats:
                return
            cfg["formats"] = formats
            memoriser_formats(formats)
        coches = [n for n in instruments if choix_instr[n].get()]
        if len(coches) == len(instruments):
            cfg["selection"] = None
        else:
            if not coches and not any(f in ("mid", "mp3") for f in cfg.get("formats", [])):
                return
            cfg["selection"] = {cle_nom(n) for n in coches}
            cfg["selection_noms"] = coches
        cible["dossier"] = sortie
        if os.path.isdir(sortie):
            if choix_dossier.get() == "nouveau":
                cible["dossier"] = dossier_libre(sortie)
                cfg["ecraser"] = False
            else:
                cfg["ecraser"] = True
        w.unbind("<Return>")
        w.unbind("<Escape>")
        w.protocol("WM_DELETE_WINDOW", lambda: None)      # pas de fermeture pendant l'export
        vider()
        total = max(1, nb_etapes(cfg))
        ligne = ttk.Frame(corps)
        ligne.pack(fill="x", pady=(20, 6))
        roue = ttk.Label(ligne, text="◐", font=("Segoe UI Symbol", 22), foreground="#2563eb")
        roue.pack(side="left", padx=(0, 12))
        bloc = ttk.Frame(ligne)
        bloc.pack(side="left", fill="x", expand=True)
        lib = ttk.Label(bloc, text="Préparation…", font=("Segoe UI", 11, "bold"))
        lib.pack(anchor="w")
        info = ttk.Label(bloc, text="", foreground="#666")
        info.pack(anchor="w")
        barre = ttk.Progressbar(corps, maximum=total, mode="determinate")
        barre.pack(fill="x", pady=(8, 4))
        anim = ttk.Progressbar(corps, mode="indeterminate")
        anim.pack(fill="x")
        anim.start(12)
        ttk.Label(corps, text="MuseScore travaille en arrière-plan ; vous pouvez continuer à utiliser la partition.",
                  foreground="#666").pack(anchor="w", pady=(10, 0))

        file = queue.Queue()
        etat = {"n": 0, "t0": time.time(), "i": 0}

        def travail():
            try:
                res = exporter(chemin, cfg, etape=lambda t: file.put(("etape", t)), sortie=cible["dossier"])
                file.put(("fin", res))
            except SystemExit as e:
                file.put(("fin", (sortie, ["  ! " + str(e)])))
            except Exception:
                import traceback
                file.put(("fin", (sortie, ["  ! Erreur inattendue :"] + traceback.format_exc().splitlines()[-6:])))

        threading.Thread(target=travail, daemon=True).start()

        def boucle():
            try:
                while True:
                    genre, val = file.get_nowait()
                    if genre == "etape":
                        etat["n"] += 1
                        barre["value"] = etat["n"] - 1
                        lib["text"] = val + "…"
                    else:
                        anim.stop()
                        page_resultat(*val)
                        return
            except queue.Empty:
                pass
            etat["i"] += 1
            roue["text"] = "◐◓◑◒"[etat["i"] % 4]
            ecoule = int(time.time() - etat["t0"])
            info["text"] = "Étape %d / %d   ·   %d:%02d écoulées" % (max(1, etat["n"]), total, ecoule // 60, ecoule % 60)
            w.after(150, boucle)

        boucle()

    # ---------------- 3. résultat ----------------
    def page_resultat(dossier, journal):
        vider()
        w.protocol("WM_DELETE_WINDOW", w.destroy)
        erreur = any(l.lstrip().startswith("!") for l in journal)
        if erreur:
            ttk.Label(corps, text="⚠ Export terminé avec des erreurs", font=("Segoe UI", 12, "bold"),
                      foreground="#b45309").pack(anchor="w", pady=(4, 6))
        else:
            ttk.Label(corps, text="✔ Export terminé", font=("Segoe UI", 12, "bold"),
                      foreground="#15803d").pack(anchor="w", pady=(4, 6))
        zone = tk.Text(corps, height=min(22, len(journal) + 1), width=110, wrap="word",
                       font=("Consolas", 9), relief="flat", background="#f6f6f6")
        zone.insert("1.0", "\n".join(journal))
        for i, l in enumerate(journal, start=1):
            if l.lstrip().startswith("!"):
                zone.tag_add("err", "%d.0" % i, "%d.end" % i)
        zone.tag_config("err", foreground="#b91c1c")
        zone.configure(state="disabled")
        zone.pack(fill="both", expand=True)

        ttk.Button(boutons, text="Fermer", command=w.destroy).pack(side="right")
        b = ttk.Button(boutons, text="Ouvrir le dossier", command=lambda: (ouvrir_dossier(dossier), w.destroy()))
        b.pack(side="right", padx=(0, 8))
        b.focus_set()
        w.bind("<Return>", lambda *_: (ouvrir_dossier(dossier), w.destroy()))
        w.bind("<Escape>", lambda *_: w.destroy())
        w.lift()

    if cfg.get("confirmation", True):
        page_confirmation()
    else:
        page_progression()
    w.after(50, lambda: (w.lift(), w.focus_force()))
    w.mainloop()
    return True


def notifier(titre, message, erreur=False):
    try:
        if platform.system() == "Windows":
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, message, titre, 0x10 if erreur else 0x40)
        elif platform.system() == "Darwin":
            court = message.splitlines()[-1].replace('"', "'")
            subprocess.run(["osascript", "-e", 'display notification "%s" with title "%s"' % (court, titre)])
    except Exception:
        pass


def main():
    try:
        cfg = json.load(open(FICHIER_CONFIG, encoding="utf-8"))
        chemin = trouver_partition(cfg, sys.argv[1:])
        attendre_fin_enregistrement(chemin)
        cfg = charger_config(chemin)
        if fenetre(chemin, cfg):
            return
        # mode simple (tkinter absent)
        sortie, journal = exporter(chemin, cfg)
        texte = "\n".join(journal)
        print(texte)
        erreur = any(l.lstrip().startswith("!") for l in journal)
        notifier("Export MuseScore" + (" – avec erreurs" if erreur else ""), texte, erreur)
        if cfg.get("ouvrir_dossier", True) and not erreur:
            ouvrir_dossier(sortie)
    except SystemExit as e:
        print(e)
        notifier("Export MuseScore – erreur", str(e), True)
        sys.exit(1)
    except Exception:
        import traceback
        notifier("Export MuseScore – erreur inattendue", traceback.format_exc(), True)
        sys.exit(2)


if __name__ == "__main__":
    main()
