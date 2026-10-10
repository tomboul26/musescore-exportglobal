# Export global — a plugin for MuseScore Studio 4

**One keyboard shortcut, and all the material for a piece is ready**: full score, parts, transposed parts for other instruments, PDF, PNG, MIDI and MP3.

Built for brass bands, concert bands and wind ensembles, where the same line often has to go to several instruments: a flute part also in B♭ for a clarinet, a sousaphone part also in treble clef for a baritone sax, and so on. These extra parts are generated at export time, **without adding any instrument to the score**.

> **Language:** the plugin follows MuseScore's interface language: French when MuseScore is in French, English otherwise. The `"langue"` setting can force `"fr"` or `"en"` (see *Settings*).

---

## Features

- **One-step export** of the full score and every part.
- **Transposed parts**: any staff of the score can produce one or more parts for other instruments, with a different key, clef or octave. They are declared in the score properties.
- **Same layout**: a transposed part keeps the layout of the part it comes from.
- **Choice of formats** with check boxes:
  - single PDF (score + parts);
  - separate PDFs;
  - PNG;
  - MIDI;
  - MP3.
- **Choice of instruments**: all, one or several, including the full score and the transposed parts.
- **Confirmation window** before export:
  - the list of planned transposed parts, with the written range of each one;
  - a warning when a part looks like it is in the wrong octave.
- **Safe re-export**: either overwrite the previous export (only the checked formats and instruments are replaced) or create a new folder, "… (2)".
- **The score is never modified.** Transposed parts are built in a temporary copy.
- **Background export.** MuseScore stays usable during the export. A window shows the progress, then a summary.
- **A one-page part** gets no page number.

---

## Installation

### 1. Python 3

The plugin relies on a Python script.

- **Windows**: install Python 3 from [python.org](https://www.python.org/downloads/), **keeping the "py launcher" option checked**.
- **macOS / Linux**: `python3` must be available. These systems have not been tested yet.

No other module is required. For the single PDF, the `pypdf` module is installed automatically the first time it is needed. If that fails, run `py -m pip install pypdf`.

### 2. Copy the plugin

Copy the **`ExportGlobal`** folder into MuseScore's plugins folder. This folder is shown in *Preferences > General > Folders > Plugins*; by default it is `Documents\MuseScore4\Plugins`. Never copy it into `C:\Program Files`.

```
Plugins\
└── ExportGlobal\
    ├── export_global.qml
    ├── export_musescore.py
    └── parties_config.json
```

### 3. Enable the plugin and choose a shortcut

1. *Plugins > Manage plugins*: click **Export global**, then **Enable**.
2. **Edit shortcut**, for example **Ctrl+Shift+X**. This shortcut only exists inside MuseScore and does not conflict with the operating system.

---

## Usage

1. Open the score. It must have been saved at least once.
2. Press the shortcut, or use *Plugins > Export global*.
3. The score is saved, then the **export window** opens:
   - **Transposed parts**: a tree of the score's instruments and the parts derived from them, with key, clef and written range.
   - **Formats to export**: single PDF (score + parts), separate PDFs, PNG, MIDI, MP3. Your choice is remembered for next time.
   - **Instruments to export**: the **Instruments…** button opens a check list. **All instruments** checks or unchecks everything. The list is grouped into *Full score*, *Parts* and *Transposed parts*.
   - **Export folder**: if an export already exists, choose to overwrite it or to create a new folder.
4. Click **Export**. You can keep working in MuseScore during the export.
5. When it is done, click **Open folder**.

### Output files

In `<title> - export\`, next to the `.mscz`:

| File | Content |
|---|---|
| `<title> - score and parts.pdf` | Full score and all parts in one PDF |
| `<title> - selected parts.pdf` | Single PDF when only some instruments are exported |
| `<title>.pdf` | Full score |
| `<title> - Trumpet.pdf` | A part of the score |
| `<title> - Flute Bb treble clef.pdf` | A transposed part |
| `<title>-1.png`, `-2.png`… | Page images, or `<title>.png` for a single page |
| `<title>.mid`, `<title>.mp3` | Audio of the full score |

When only some instruments are exported, the files of the other instruments already in the folder are kept.

---

## Declaring transposed parts

They are declared **in the score itself**, in *File > Score properties*, then **New property**:

- **Name**: the instrument name as it appears in the score, for example `Flute` or `Sousaphone`.
- **Value**: one or more parts separated by `;`, each one written as:

```
[Part name =] Key  Clef  [octave shift]
```

### Examples

| Property | Value | Resulting parts |
|---|---|---|
| `Flute` | `Bb g ; Alto sax = Eb g` | Flute Bb treble clef, Alto sax |
| `Trombone` | `Bb f ; C g +1` | Trombone Bb bass clef, Trombone C treble clef |
| `Sousaphone` | `Bass C = C f8vb ; Bass Bb = Bb g15mb ; Baritone = Eb g15mb -1` | three bass parts |

### Vocabulary

| Item | Accepted values |
|---|---|
| **Key** (first word) | `C`, `Bb`, `Eb`, `F`, `A`, `G`; French names `Ut`/`Do`, `Sib`, `Mib`, `Fa`, `La`, `Sol` also work |
| **Clef** | `g` or `treble`, `f` or `bass`, `c3` (alto), `c4` (tenor). Octave clefs: `g8vb`, `f8vb` (8 below), `g15mb`, `f15mb` (15 below). French `sol`, `fa`, `ut3`, `ut4`, `sol8`, `fa8`, `sol15`, `fa15` also work |
| **Octave** | `+1`, `+2`, `-1`… on top of the instrument's transposition |

- The first word is always the key.
- With "Name = …", the part gets exactly that name ("Alto sax = Eb g" gives "Alto sax"). Without a name, the instrument name is completed automatically with key and clef, for example "Trombone Bb treble clef". If the key or the clef is already in the name ("Bass Bb"), it is not repeated. Set `"clef_dans_nom": false` to leave the clef out of the name.
- These properties are **stored inside the `.mscz`**: they travel with the score when it is copied, sent or renamed.

### Common instruments

| Instrument | Value |
|---|---|
| Trumpet, clarinet, flugelhorn, soprano sax | `Bb g` |
| Tenor sax, bass clarinet | `Bb g +1` |
| Trombone or euphonium in treble clef | `Bb g +1` |
| B♭ bass (tuba, sousaphone) in treble clef | `Bb g +2` |
| Alto sax, E♭ alto horn | `Eb g` |
| Baritone sax, E♭ bass in treble clef | `Eb g +1` |
| French horn | `F g` |
| Trombone, euphonium, tuba in bass clef (concert pitch) | `C f` |

**Check the Written range column** in the export window. It shows the lowest and highest notes as they will be written (C4 = middle C). A warning appears when a part looks too high or too low for its clef; this usually means a `+1` or `-1` should be added or removed.

---

## Settings (optional)

The `parties_config.json` file, in the plugin folder:

| Key | Purpose | Default |
|---|---|---|
| `"langue"` | Interface language: `"auto"` (MuseScore's language), `"fr"` or `"en"` | `"auto"` |
| `"clef_dans_nom"` | `false` to leave the clef out of transposed part names ("Trumpet C" instead of "Trumpet C treble clef") | `true` |
| `"confirmation"` | `false` to export straight away, without the confirmation window | `true` |
| `"formats"` | Formats checked by default: `pdfunique`, `pdf`, `png`, `mid`, `mp3` | last used |
| `"dossier_sortie"` | Export folder name (`{titre}` = score title) | `"{titre} - export"` |
| `"musescore"` | Path to `MuseScore4.exe`, if not found automatically | (automatic) |
| `"voix"` | Default transposed parts, for scores without properties | `{}` |

If the `pyw` launcher is not found, put the path to `pythonw.exe` in `export_global.qml`, on the `property string python` line.

---

## Known limitations

- Clef changes in the middle of a piece are not copied into transposed parts.
- An instrument with several staves (piano, harp…) cannot be used as the source of a transposed part.
- Tested on Windows with MuseScore Studio 4.7. macOS and Linux have not been tested yet.

---

## Troubleshooting

| Problem | Solution |
|---|---|
| Nothing happens when pressing the shortcut | Check that Python is installed with the "py launcher" and that the plugin is enabled |
| "Score … not found" | Save the score once (*File > Save as*) |
| "No transposed part" | Check that the property name is exactly the instrument name in the score |
| "word not understood" | A property value contains an unknown word: check key, clef and octave |
| No single PDF | Install the PDF module: `py -m pip install pypdf` |

---

## License

Released under the **MIT License**: free to use, modify and redistribute, including commercially, as long as the copyright notice is kept. See the [`LICENSE`](LICENSE) file.

Copyright (c) 2026 Thomas Boulenger
