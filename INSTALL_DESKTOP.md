# Installing QualSafe Desktop

For the person who will use the program. If you are setting up a development
checkout instead, see `README_QT.md`.

---

## What you need

**Windows 10 or 11, 64-bit.** That is the whole list.

You do **not** need Python, administrator rights, an internet connection at
install time, an account, or a licence key. The installer contains everything.

**Disk space:** about 500 MB. Add roughly 700 MB more if you later install the
analysis engine, and about 1.9 GB after that for the language models.

---

## Installing

1. Double-click **`QualSafe-Desktop-0.99.0-Setup.exe`**.

2. **Windows will warn you.** You will see *"Windows protected your PC"*. Click
   **More info**, then **Run anyway**.

   This appears because the installer is not yet signed with a code-signing
   certificate, not because anything is wrong with it. If you would rather
   check before trusting it, verify the download first — see below.

3. Accept the licence and choose a folder, or take the default. The default
   installs for you only, under your own user folder, so no administrator
   password is needed.

   *If you choose your own folder, keep the path short.* Windows limits how long
   a file path may be, and QualSafe stores some files in deeply nested folders.
   The installer will tell you if the folder you picked is too long.

4. Start it from the Start menu, or tick the box on the last page.

### Verifying the download first

Compare the file's fingerprint against the one published with the release:

```powershell
Get-FileHash "$env:USERPROFILE\Downloads\QualSafe-Desktop-0.99.0-Setup.exe" -Algorithm SHA256
```

If the two match, the file arrived intact and unaltered. This is also worth
doing simply to catch a truncated download, which otherwise fails part-way
through installing.

---

## The first five minutes

The program opens on **Documents** with nothing loaded. Press **F1** for the
guide and start with **Start here** — walkthrough A codes a transcript that
ships with the program, takes about five minutes, and needs nothing else
installed.

Before you code anything of your own, go to **Data** and set **your analyst
name**. It is stamped on every coding you make and it is what lets agreement
analysis tell your codings from a colleague's. Setting it afterwards does not
relabel work you have already done.

---

## Coding surveys automatically

Everything above works out of the box. Automatic coding of survey open text
needs two extra pieces, and the **Models** screen tells you which are missing.

**The analysis engine** — three Python packages (PyTorch, transformers and
sentence-transformers), roughly 700 MB to 1 GB. Open the **Models** screen and
press **Install the analysis engine**. It downloads them once, with progress
shown, into a folder of your own outside the program (Windows
`%LOCALAPPDATA%\QualSafe\engine`, Mac `~/Library/Application Support/QualSafe/engine`),
so nothing inside the program is changed and updating QualSafe does not remove
it. If a download stops part-way, press the button again and it carries on.
The processor-only build of PyTorch is used deliberately; the default is
several gigabytes larger and only useful with an NVIDIA graphics card.

**The models** — about 1.9 GB, downloaded once from the **Models** screen. The
engine and the models are the only times the program uses the internet (the
engine from `pypi.org` and `download.pytorch.org`, the models from
`huggingface.co`). Each runs in its own separate process, started only when you
press its button, so that analysis itself is never able to reach the network. No
text of yours is sent in either.

If your institution's network blocks either download, ask whoever manages it
about `pypi.org` and `huggingface.co`.

---

## Where your files live

| | |
|---|---|
| The program | the folder you chose during installation |
| Your projects | wherever you saved them — a project is one `.qnw` file |
| Run output | an `output_qt` folder beside the program |
| Analysis engine | `%LOCALAPPDATA%\QualSafe\engine` (Mac: `~/Library/Application Support/QualSafe/engine`) |
| Models | `C:\Users\<you>\.cache\huggingface` |
| Preferences | the Windows registry, under your own user account |

**Uninstalling removes the program only.** Your projects, saved output, the
analysis engine and the downloaded models are left exactly where they are (the
engine and the models take about 3 GB; delete their folders by hand to get the
space back). The uninstaller says so before it runs.

---

## If something goes wrong

**It will not start.** Check you extracted or installed rather than running the
setup from inside a zip. If the window never appears, try starting it from a
terminal — `python\pythonw.exe -m qualsafe_qt` from the installation folder —
and see whether an error is printed.

**A document opens but cannot be coded.** The program refuses to code a document
whose character positions it cannot map exactly, rather than guessing and
attaching your codes to the wrong words. Re-saving the file as plain UTF-8 text
usually resolves it.

**The survey screen says the analysis engine is missing.** Press **Install the analysis engine** on the Models screen (see above). Everything
except automatic coding still works.

**An install into a long folder path failed part-way.** Windows path limits.
Uninstall, and install again somewhere shorter.

**Something else.** Press **F1** and read **Troubleshooting**, which covers more
cases than this page.
