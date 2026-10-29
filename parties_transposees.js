// Export global — lecture / écriture des propriétés « parties transposées »
// (même vocabulaire que export_musescore.py : « Nom = Tonalité Clé [octave] ; ... »)
.pragma library

var TONS_FR = ["Ut", "Sib", "Mib", "Fa", "La", "Sol"];
var TONS_EN = ["C", "Bb", "Eb", "F", "A", "G"];
var CLES = ["G", "F", "C3", "C4", "C1", "G8vb", "F8vb", "G15mb", "F15mb"];
var CLES_JETON_FR = ["sol", "fa", "ut3", "ut4", "ut1", "sol8", "fa8", "sol15", "fa15"];
var CLES_JETON_EN = ["g", "f", "c3", "c4", "c1", "g8vb", "f8vb", "g15mb", "f15mb"];
var CLES_TEXTE_FR = ["sol", "fa", "ut 3", "ut 4", "ut 1", "sol 8 (8 plus bas)", "fa 8 (8 plus bas)",
                     "sol 15 (15 plus bas)", "fa 15 (15 plus bas)"];
var CLES_TEXTE_EN = ["treble", "bass", "alto", "tenor", "soprano", "treble 8vb", "bass 8vb",
                     "treble 15mb", "bass 15mb"];
// famille de clé ajoutée au nom automatique (comme FAMILLE_CLE dans export_musescore.py)
var FAMILLE_FR = ["clef de sol", "clef de fa", "clef d'ut 3", "clef d'ut 4", "clef d'ut 1",
                  "clef de sol", "clef de fa", "clef de sol", "clef de fa"];
var FAMILLE_EN = ["treble clef", "bass clef", "alto clef", "tenor clef", "soprano clef",
                  "treble clef", "bass clef", "treble clef", "bass clef"];

var ALIAS_TON = {"ut": 0, "do": 0, "c": 0, "sib": 1, "bb": 1, "b": 1, "mib": 2, "eb": 2,
                 "fa": 3, "f": 3, "la": 4, "a": 4, "sol": 5, "g": 5};
var ALIAS_CLE = {"g": 0, "sol": 0, "treble": 0, "f": 1, "fa": 1, "bass": 1,
                 "c3": 2, "ut3": 2, "c4": 3, "ut4": 3, "c1": 4, "ut1": 4,
                 "g8vb": 5, "sol8": 5, "sol8vb": 5, "f8vb": 6, "fa8": 6, "fa8vb": 6,
                 "g15mb": 7, "sol15": 7, "sol15mb": 7, "f15mb": 8, "fa15": 8, "fa15mb": 8};
var MOTS_VIDES = ["cle", "clef", "de", "d'", "en", "octave", "oct", "in"];

function simple(s) {
    return s.toLowerCase().replace(/[éèê]/g, "e").replace(/û/g, "u").replace(/♭/g, "b").trim();
}

// « Flute = Ut sol ; Sib fa +1 » -> {lignes: [{nom, ton, cle, oct}], erreur: ""}
function lire(valeur) {
    var res = [], erreur = "";
    var morceaux = (valeur || "").split(/[;|\n]+/);
    for (var i = 0; i < morceaux.length; i++) {
        var m = morceaux[i].trim();
        if (!m)
            continue;
        var nom = "";
        var eg = m.indexOf("=");
        if (eg >= 0) {
            nom = m.substring(0, eg).trim();
            m = m.substring(eg + 1).trim();
        }
        var ton = -1, cle = 0, oct = 0;
        var mots = m.replace(/,/g, " ").split(/\s+/);
        for (var j = 0; j < mots.length; j++) {
            if (!mots[j])
                continue;
            var w = simple(mots[j]);
            if (ton < 0 && ALIAS_TON.hasOwnProperty(w))
                ton = ALIAS_TON[w];
            else if (ALIAS_CLE.hasOwnProperty(w))
                cle = ALIAS_CLE[w];
            else if (/^[+-]\d$/.test(w))
                oct = parseInt(w, 10);
            else if (MOTS_VIDES.indexOf(w) < 0)
                erreur = erreur || ("« " + mots[j] + " »");
        }
        if (ton < 0) {
            erreur = erreur || ("« " + morceaux[i].trim() + " »");
            ton = 0;
        }
        res.push({nom: nom, ton: ton, cle: cle, oct: oct});
    }
    return {lignes: res, erreur: erreur};
}

// [{nom, ton, cle, oct}] -> « Flute = Ut sol ; Sib fa +1 »
function ecrire(lignes, fr) {
    var tons = fr ? TONS_FR : TONS_EN, cles = fr ? CLES_JETON_FR : CLES_JETON_EN;
    var out = [];
    for (var i = 0; i < lignes.length; i++) {
        var l = lignes[i];
        var t = tons[l.ton] + " " + cles[l.cle];
        if (l.oct)
            t += (l.oct > 0 ? " +" : " ") + l.oct;
        var nom = (l.nom || "").trim();
        out.push(nom ? nom + " = " + t : t);
    }
    return out.join(" ; ");
}

// nom final de la partie (aperçu) : nom donné, sinon instrument + tonalité + clé
function nomFinal(base, l, fr) {
    var nom = (l.nom || "").trim();
    if (nom)
        return nom;
    var mots = simple(base).split(/\s+/);
    var ton = TONS_EN[l.ton];
    var morceaux = [base];
    if (mots.indexOf(ton.toLowerCase()) < 0 && mots.indexOf(simple(TONS_FR[l.ton])) < 0)
        morceaux.push(ton);
    var fam = (fr ? FAMILLE_FR : FAMILLE_EN)[l.cle];
    if (simple(base).indexOf(simple(FAMILLE_FR[l.cle])) < 0 && simple(base).indexOf(simple(FAMILLE_EN[l.cle])) < 0)
        morceaux.push(fam);
    return morceaux.join(" ");
}

// nom invalide pour la propriété (« = » ou « ; » le couperaient)
function nomInvalide(nom) {
    return /[=;|]/.test(nom || "");
}
