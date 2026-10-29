//=============================================================================
//  Export global — Parties transposées / Transposed parts — MuseScore 4.7
//  Copyright (c) 2026 Thomas Boulenger — licence MIT (voir le fichier LICENSE)
//  Éditeur des propriétés de la partition qui décrivent les parties transposées
//  (Fichier > Propriétés de la partition), utilisées par « Export global ».
//=============================================================================

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import MuseScore 3.0
import "parties_transposees.js" as P

MuseScore {
    id: plugin
    version: "1.3.1"
    title: "Export global – Parties transposées"
    description: "Edit the transposed parts exported by Export global (stored in the score properties). / Modifier les parties transposées exportées par Export global (enregistrées dans les propriétés de la partition)."
    pluginType: "dialog"
    requiresScore: true
    width: 820
    height: 560

    property bool fr: String(Qt.uiLanguage || Qt.locale().name).substring(0, 2) === "fr"
    function t(f, e) { return fr ? f : e }

    property var parties: []          // {titre, instrument, cle, valeur, erreur}
    property string alerte: ""

    property alias modele: lignes
    Connections {                     // tout ajout ou retrait de ligne relance le contrôle des noms
        target: lignes
        function onCountChanged() { Qt.callLater(plugin.verifier) }
    }
    ListModel { id: lignes }          // en-têtes de partie (genre "partie") et transpositions (genre "ligne")

    // ---------------------------------------------------------------- lecture
    function nomsDesExtraits() {
        // nom de piste de l'instrument -> nom de la partie (onglet), ex. « Clarinette en Sib » -> « Clarinette »
        var res = {};
        try {
            for (var i = 0; i < curScore.excerpts.length; i++) {
                var e = curScore.excerpts[i];
                var ps = e.partScore;
                if (ps && ps.parts.length === 1 && e.title)
                    res[ps.parts[0].partName] = e.title;
            }
        } catch (err) {
            console.log("Parties transposées : extraits illisibles", err);
        }
        return res;
    }

    function charger() {
        lignes.clear();
        var extraits = nomsDesExtraits();
        var liste = [];
        for (var i = 0; i < curScore.parts.length; i++) {
            var p = curScore.parts[i];
            var instrument = p.longName || p.partName || "";
            if (!instrument)
                continue;
            if ((p.instrumentId || "").indexOf("drum.") === 0 || p.hasDrumStaff)
                continue;                                     // percussions : pas de transposition
            if (p.endTrack - p.startTrack > 4)
                continue;                                     // plusieurs portées : ignoré par l'export
            var titre = extraits[p.partName] || instrument;
            // propriété existante : nom de la partie, de l'instrument, ou « parties <nom> »
            var candidats = [titre, instrument, p.partName];
            var noms = [];
            for (var c = 0; c < candidats.length; c++)
                if (candidats[c] && noms.indexOf(candidats[c]) < 0)
                    noms.push(candidats[c]);
            var cle = "", valeur = "";
            var essais = [];
            for (c = 0; c < noms.length; c++)
                essais.push(noms[c], "parties " + noms[c], "partie " + noms[c], "parts " + noms[c]);
            for (c = 0; c < essais.length && !cle; c++) {
                var v = curScore.metaTag(essais[c]);
                if (v && String(v).trim()) {
                    cle = essais[c];
                    valeur = String(v);
                }
            }
            var lu = P.lire(valeur);
            cle = cle || titre;
            // nom de base des parties sans nom : celui de la propriété (comme export_musescore.py)
            var base = cle.replace(/^(parties?|parts?)\s*[:\-]?\s+/i, "");
            var info = {titre: titre, instrument: instrument, cle: cle, base: base, valeur: valeur,
                        erreur: lu.erreur};
            liste.push(info);
            lignes.append({genre: "partie", pidx: liste.length - 1, titre: titre,
                           info: (instrument !== titre ? instrument : "")
                                 + (lu.erreur ? (instrument !== titre ? " — " : "")
                                    + t("propriété non comprise : ", "property not understood: ") + lu.erreur : ""),
                           nom: "", ton: 0, cle: 0, oct: 0});
            for (var k = 0; k < lu.lignes.length; k++) {
                var l = lu.lignes[k];
                lignes.append({genre: "ligne", pidx: liste.length - 1, titre: "", info: "",
                               nom: l.nom, ton: l.ton, cle: l.cle, oct: l.oct});
            }
        }
        parties = liste;
        verifier();
    }

    // ---------------------------------------------------------------- édition
    function ajouter(indexEntete) {
        var i = indexEntete + 1;
        while (i < lignes.count && lignes.get(i).genre === "ligne")
            i++;
        var pidx = lignes.get(indexEntete).pidx;
        lignes.insert(i, {genre: "ligne", pidx: pidx, titre: "", info: "", nom: "", ton: 0, cle: 0, oct: 0});
        verifier();
    }

    function supprimer(i) {
        lignes.remove(i);
        Qt.callLater(verifier);       // la ligne supprimée n'existe plus : contrôle relancé après coup
    }

    function lignesDe(pidx) {
        var res = [];
        for (var i = 0; i < lignes.count; i++) {
            var l = lignes.get(i);
            if (l.genre === "ligne" && l.pidx === pidx)
                res.push({nom: l.nom, ton: l.ton, cle: l.cle, oct: l.oct});
        }
        return res;
    }

    function apercu(i) {
        var l = lignes.get(i);
        if (!l || l.genre !== "ligne" || !parties[l.pidx])
            return "";
        return "→ " + P.nomFinal(parties[l.pidx].base, l, fr);
    }

    function verifier() {
        var vus = {}, msg = "";
        for (var i = 0; i < parties.length; i++)
            vus[parties[i].titre.toLowerCase()] = parties[i].titre;
        for (i = 0; i < lignes.count && !msg; i++) {
            var l = lignes.get(i);
            if (l.genre !== "ligne")
                continue;
            if (P.nomInvalide(l.nom)) {
                msg = t("Le nom « %1 » ne doit contenir ni « = » ni « ; ».",
                        "The name \"%1\" must not contain \"=\" or \";\".").arg(l.nom);
                break;
            }
            var n = P.nomFinal(parties[l.pidx].base, l, fr);
            if (vus[n.toLowerCase()]) {
                msg = t("Deux parties s'appelleraient « %1 » : changez un des noms.",
                        "Two parts would be called \"%1\": change one of the names.").arg(n);
                break;
            }
            vus[n.toLowerCase()] = n;
        }
        alerte = msg;
    }

    // ---------------------------------------------------------------- écriture
    function enregistrer() {
        verifier();
        if (alerte)
            return;
        curScore.startCmd();
        for (var i = 0; i < parties.length; i++) {
            var p = parties[i];
            var valeur = P.ecrire(lignesDe(i), fr);
            // on ne réécrit que ce qui a changé (la mise en forme d'origine est gardée sinon)
            if (valeur !== P.ecrire(P.lire(p.valeur).lignes, fr))
                curScore.setMetaTag(p.cle, valeur);
        }
        curScore.endCmd();
        quit();
    }

    onRun: charger()

    // ---------------------------------------------------------------- interface
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 8

        Label {
            text: t("Parties transposées de « %1 »", "Transposed parts of \"%1\"").arg(curScore ? curScore.scoreName : "")
            font.bold: true
            font.pixelSize: 16
        }
        Label {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            color: "#666666"
            text: t("« + » ajoute une partie transposée à partir de cet instrument. Sans nom, la partie prend le nom de l'instrument complété par la tonalité et la clé. Octave : en plus de la transposition de la tonalité.",
                    "\"+\" adds a transposed part made from this instrument. Without a name, the part gets the instrument name followed by key and clef. Octave: on top of the key's transposition.")
        }

        RowLayout {                                   // titres des colonnes
            spacing: 6
            Item { Layout.preferredWidth: 24 }
            Label { text: t("Nom de la partie", "Part name"); font.bold: true; Layout.preferredWidth: 200 }
            Label { text: t("Tonalité", "Key"); font.bold: true; Layout.preferredWidth: 90 }
            Label { text: t("Clé", "Clef"); font.bold: true; Layout.preferredWidth: 160 }
            Label { text: "Octave"; font.bold: true; Layout.preferredWidth: 100 }
        }

        ScrollView {
            id: defil
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true

            ColumnLayout {
                width: defil.availableWidth
                spacing: 4

                Label {
                    visible: lignes.count === 0
                    text: t("Aucun instrument transposable dans cette partition.", "No instrument to transpose in this score.")
                }

                Repeater {
                    model: lignes
                    delegate: RowLayout {
                        id: rang
                        Layout.fillWidth: true
                        spacing: 6
                        property bool entete: genre === "partie"

                        // ---- en-tête : nom de la partie d'origine et bouton « + »
                        Button {
                            visible: rang.entete
                            text: "+"
                            Layout.preferredWidth: 24
                            Layout.preferredHeight: 24
                            ToolTip.visible: hovered
                            ToolTip.text: t("Ajouter une partie transposée", "Add a transposed part")
                            onClicked: plugin.ajouter(index)
                        }
                        Label {
                            visible: rang.entete
                            text: titre
                            font.bold: true
                            Layout.topMargin: 6
                        }
                        Label {
                            visible: rang.entete
                            text: info
                            color: "#888888"
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                            Layout.topMargin: 6
                        }

                        // ---- transposition
                        Item { visible: !rang.entete; Layout.preferredWidth: 24 }
                        TextField {
                            visible: !rang.entete
                            Layout.preferredWidth: 200
                            text: nom
                            placeholderText: t("(automatique)", "(automatic)")
                            onTextEdited: { lignes.setProperty(index, "nom", text); plugin.verifier() }
                        }
                        ComboBox {
                            visible: !rang.entete
                            Layout.preferredWidth: 90
                            model: fr ? P.TONS_FR : P.TONS_EN
                            currentIndex: ton
                            onActivated: { lignes.setProperty(index, "ton", currentIndex); plugin.verifier() }
                        }
                        ComboBox {
                            visible: !rang.entete
                            Layout.preferredWidth: 160
                            model: fr ? P.CLES_TEXTE_FR : P.CLES_TEXTE_EN
                            currentIndex: cle
                            onActivated: { lignes.setProperty(index, "cle", currentIndex); plugin.verifier() }
                        }
                        SpinBox {
                            visible: !rang.entete
                            Layout.preferredWidth: 100
                            from: -3
                            to: 3
                            value: oct
                            textFromValue: function(v) { return v > 0 ? "+" + v : String(v) }
                            valueFromText: function(s) { return parseInt(s, 10) || 0 }
                            onValueModified: lignes.setProperty(index, "oct", value)
                        }
                        Label {
                            visible: !rang.entete
                            text: { nom; ton; cle; return apercu(index) }
                            color: "#2a6f2a"
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                        }
                        Button {
                            visible: !rang.entete
                            text: "✕"
                            Layout.preferredWidth: 28
                            ToolTip.visible: hovered
                            ToolTip.text: t("Supprimer cette partie", "Remove this part")
                            onClicked: plugin.supprimer(index)
                        }
                    }
                }
            }
        }

        Label {
            visible: alerte !== ""
            text: alerte
            color: "#b00020"
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
        }

        RowLayout {
            Layout.alignment: Qt.AlignRight
            spacing: 8
            Button {
                text: t("Annuler", "Cancel")
                onClicked: quit()
            }
            Button {
                text: t("Enregistrer", "Save")
                enabled: alerte === ""
                highlighted: true
                onClicked: enregistrer()
            }
        }
    }
}
