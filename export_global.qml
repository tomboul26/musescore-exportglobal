//=============================================================================
//  Export global — MuseScore 4.7
//  Copyright (c) 2026 Thomas Boulenger — licence MIT (voir le fichier LICENSE)
//  Enregistre la partition puis lance export_musescore.py (même dossier),
//  qui produit conducteur, parties (y compris parties transposées), PNG, MIDI, MP3.
//  Raccourci : Plugins > Gérer les plugins > Export global > Modifier le raccourci
//=============================================================================

import QtQuick
import MuseScore 3.0

MuseScore {
    version: "1.0"
    title: "Export global"
    description: "Enregistre puis exporte conducteur, toutes les parties (y compris les parties transposées définies dans les propriétés de la partition), PNG, MIDI et MP3."
    requiresScore: true

    // Lanceur Python : "pyw" (lanceur installé avec Python de python.org).
    // Si besoin, mettre le chemin complet, ex. "C:/Users/Moi/AppData/Local/Programs/Python/Python313/pythonw.exe"
    property string python: "pyw"

    QProcess { id: proc }

    function dossierDuPlugin() {
        var u = Qt.resolvedUrl(".").toString();
        if (Qt.platform.os === "windows")
            u = u.replace(/^file:\/\/\//, "");
        else
            u = u.replace(/^file:\/\//, "");
        return decodeURIComponent(u).replace(/\/$/, "");
    }

    onRun: {
        var nom = curScore.scoreName;
        // 1. enregistrer (Python attend que le fichier soit stable avant de le lire)
        cmd("file-save");

        // 2. lancer le script en tâche détachée : MuseScore reste utilisable pendant l'export
        var script = dossierDuPlugin() + "/export_musescore.py";
        if (Qt.platform.os === "windows") {
            var args = ["/c", "start", "", python];
            if (python === "pyw" || python === "py")
                args.push("-3");
            proc.startWithArgs("cmd.exe", args.concat([script, "--nom", nom]));
        } else {
            proc.startWithArgs("/bin/sh", ["-c", "nohup python3 \"$0\" --nom \"$1\" >/dev/null 2>&1 &", script, nom]);
        }
        proc.waitForFinished(10000);
    }
}
