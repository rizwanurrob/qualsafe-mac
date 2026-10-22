# QualSafe Desktop on macOS

> **Status: written, not yet built on a Mac.** The build script, the launcher and
> the tests of their logic exist; a Mac has not yet produced or opened the app.
> The first run of `.github/workflows/mac.yml` (or `packaging/build_mac.py` on a
> Mac) is that test, and §6 is the checklist for it. Until then treat everything
> here as a design that has been checked on paper.

## 1. What you need

| | |
|---|---|
| **macOS** | **13 (Ventura) or newer.** Qt 6.11 ships one macOS build, and it is tagged for macOS 13. On 12 the app will not open. |
| **Mac** | Apple Silicon (M1 or later) or Intel. There are two separate downloads; use the one that matches `Apple menu → About This Mac`. |
| **Disk** | About 0.5 GB for the app. About 700 MB more for the analysis engine, and about 1.9 GB after that for the language models. |
| **Python** | None. The app carries its own. |

**A 2017 MacBook** can run this only if it is on macOS 13. Macs of that age stop
at Ventura, so check `About This Mac` first: on Monterey (12) it will not open.

## 2. Installing

1. Open the `.dmg` (`QualSafe-Desktop-<version>-macOS-arm64.dmg` for Apple
   Silicon, `…-x86_64.dmg` for Intel).
2. Drag **QualSafe** onto **Applications**.
3. Open it from Applications.

**The first time, macOS will refuse.** This build is not notarised (that needs a
paid Apple Developer membership), so Gatekeeper says it cannot verify the app.
That is the equivalent of the Windows SmartScreen warning, and the same trade: it
says the developer is unregistered, not that the app is unsafe. To open it once:

* **macOS 13 and 14:** in Applications, **right-click → Open → Open**.
* **macOS 15 and later:** try to open it, dismiss the message, then
  **System Settings → Privacy & Security**, scroll to the message about
  QualSafe, and press **Open Anyway**.
* Or, from Terminal, remove the download flag and open normally:

```bash
xattr -dr com.apple.quarantine /Applications/QualSafe.app
```

You do this once per install. Notarising the app removes it; see §5.

## 3. What is stored where

Nothing of yours is inside the app, so dragging it to the Trash loses nothing.

| | Location |
|---|---|
| Your projects (`.qnw`) | wherever you saved them |
| Sample projects, settings | `~/.qualsafe/` |
| The language models | `~/.cache/huggingface/hub/` |

To remove the program, drag `QualSafe.app` to the Trash. Delete the folders above
too if you also want your data and the ~1.9 GB of models gone.

## 4. Models and the analysis engine

Same as Windows: reading, coding, the codebook, analysis, search and query work
straight away. Automatic survey coding needs the analysis engine and the models.

Models are downloaded from the **Models** tab, once. The engine (torch and
friends) is not in the download. To add it, in Terminal:

```bash
/Applications/QualSafe.app/Contents/Resources/python/bin/python3 -m pip install "torch>=2.2,<3.0" "transformers>=4.40,<5.0" "sentence-transformers>=2.7,<4.0"
```

* **Intel Macs:** PyTorch stopped publishing Intel macOS builds after version
  2.2.2, so that is what pip installs. It is enough for this app's coding models,
  but it is an old torch and the Intel build is the less-supported of the two.
* **Apple Silicon on macOS 13:** the newest torch needs macOS 14. pip will choose
  an older one that fits; nothing for you to do.
* This writes into the app, which is signed. That is untested on a Mac and is one
  of the things §6 checks. If the app refuses to open afterwards, re-download it.

## 5. Building it yourself

On a Mac, from the project folder:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-light.txt -r requirements-qt.txt
.venv/bin/python packaging/build_mac.py
```

Build each architecture on a Mac of that architecture: the script refuses
otherwise, because pip would fetch the wrong wheels. The result is
`build/QualSafe-Desktop-<version>-macOS-<arch>.dmg`. Add `--engine` to bundle
torch (several GB; on Apple Silicon this needs macOS 14 or newer).

Without a GitHub remote this is the only route. With one, `mac.yml` builds both
architectures on GitHub's Macs and launches each result.

**Signing.** By default the build is signed *ad-hoc*: Apple Silicon will not run
unsigned code at all, so it needs a signature, but an ad-hoc one names no
developer. To remove the first-launch warning you need an Apple Developer ID
(US$99 a year) and notarisation:

```bash
export QUALSAFE_SIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)"
xcrun notarytool store-credentials qualsafe-notary      # once
export QUALSAFE_NOTARY_PROFILE=qualsafe-notary
python packaging/build_mac.py
```

That path is written but has never been run.

## 6. First run on a real Mac — what to check

Everything above was written on a Windows machine. In rough order of how likely
each is to be wrong:

1. **`build_mac.py` finishes.** Failure here is most likely `check_qt_links`
   (a Qt framework was pruned that something still needs — the message names the
   entry to remove) or `codesign` objecting to a symlink in the bundle.
2. **The menu bar says "QualSafe", not "python3".** The launcher runs a
   symlink named `QualSafe` to the interpreter for this. If it says python3, the
   fix is a small compiled launcher.
3. **The Dock icon is the QualSafe mark**, not a Python rocket.
4. **`Cmd+Z` undoes a coding; `Shift+Cmd+Z` redoes it**, and the Help text says
   so (⌘Z, ⇧⌘Z) rather than Ctrl.
5. **The drag-to-select reader.** This is the reason the desktop app exists. Qt's
   text selection is native and should behave the same, but it has never been
   used on macOS: select a passage, code it, undo it.
6. **`Cmd+Q`, About and the application menu** sit where a Mac user expects.
7. **Open a `.qnw` written on Windows.** The file format is identical; this is
   worth ten seconds.
8. **Installing the engine into the signed app** (§4) and running a survey.
   On Intel, this is also the first time torch 2.2.2 runs under the transformers
   this app pins.

Report what fails; each of these is a specific, fixable thing.

## 7. Known limits

* **No file association.** Double-clicking a `.qnw` does not open it in QualSafe;
  use **File → Open**. Declaring the association without the code to handle it
  would promise something that fails.
* **Not notarised** unless you do §5's signing steps.
* **Intel torch is frozen at 2.2.2**, permanently: PyTorch no longer builds it.
  GitHub's Intel runners end in August 2027, so the Intel *build* may need
  another home after that.
* **No universal build.** Two downloads, deliberately: one universal app would
  contain two copies of every library and be twice the size.
