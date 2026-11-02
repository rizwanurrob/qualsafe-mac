# Installing QualSafe Desktop

This page is for the person who uses the program. To set up a development checkout, see `README_QT.md`.

---

## What you need

You need **Windows 10 or 11, 64-bit**. That is the complete list.

You do **not** need Python, administrator rights, an internet connection at install time, an account, or a licence key. The installer contains everything.

**Disk space:** about 500 MB. Add about 700 MB if you later install the analysis engine. Add about 1.9 GB more for the language models.

---

## Install the program

1. Double-click **`QualSafe-Desktop-0.99.0-Setup.exe`**.

2. **Windows shows a warning.** The message is *"Windows protected your PC"*. Click **More info**. Then click **Run anyway**.

   The message appears because the installer has no code-signing certificate yet. It does not mean that the installer has a fault. To check the file before you trust it, verify the download first. See the next section.

3. Accept the licence. Choose a folder, or use the default folder. The default installs the program for you only, in your own user folder. You do not need an administrator password.

   *If you choose your own folder, keep the path short.* Windows limits the length of a file path. QualSafe keeps some files in folders that are deeply nested. The installer tells you if your folder path is too long.

4. Start QualSafe from the Start menu. Or tick the box on the last page of the installer.

### Verify the download first

Compare the fingerprint of the file with the fingerprint that we published with the release. Use this command:

```powershell
Get-FileHash "$env:USERPROFILE\Downloads\QualSafe-Desktop-0.99.0-Setup.exe" -Algorithm SHA256
```

If the two fingerprints are the same, the file is complete and unchanged. This check also finds a download that stopped before the end. Such a file fails part-way through the install.

---

## The first five minutes

The program opens on **Documents** with nothing loaded. Press **F1** to open the guide. Start with **Start here**. Walkthrough A codes a transcript that comes with the program. It takes about five minutes. It needs no other software.

Before you code your own data, go to **Data** and set **your analyst name**. QualSafe puts your name on every coding that you make. Agreement analysis uses the name to tell your coding from the coding of a colleague. If you set the name later, QualSafe does not change the name on work that you already did.

---

## Code surveys automatically

Everything above works with no extra parts. Automatic coding of the open text in surveys needs two extra parts. The **Models** screen tells you which parts are missing.

**The analysis engine.** The engine is three Python packages: PyTorch, transformers, and sentence-transformers. They are about 700 MB to 1 GB. Open the **Models** screen. Press **Install the analysis engine**. QualSafe downloads the packages one time and shows the progress. It puts them in a folder of your own, outside the program.

On Windows the folder is `%LOCALAPPDATA%\QualSafe\engine`. On Mac the folder is `~/Library/Application Support/QualSafe/engine`. So nothing inside the program changes. An update of QualSafe does not remove the engine.

If a download stops part-way, press the button again. The download then continues.

QualSafe uses the processor-only build of PyTorch on purpose. The default build is several gigabytes larger. It is useful only with an NVIDIA graphics card.

**The models.** The models are about 1.9 GB. Download them one time from the **Models** screen.

The engine and the models are the only two times that the program uses the internet. The engine comes from `pypi.org` and `download.pytorch.org`. The models come from `huggingface.co`.

Each download runs in its own separate process. The process starts only when you press its button. So the analysis itself can never reach the network. QualSafe sends none of your text in either download.

If the network of your institution blocks a download, ask the network manager about `pypi.org` and `huggingface.co`.

---

## Where your files are

| | |
|---|---|
| The program | the folder that you chose during the install |
| Your projects | the place where you saved them. A project is one `.qnw` file. |
| Run output | an `output_qt` folder next to the program |
| Analysis engine | `%LOCALAPPDATA%\QualSafe\engine` (Mac: `~/Library/Application Support/QualSafe/engine`) |
| Models | `C:\Users\<you>\.cache\huggingface` |
| Preferences | the Windows registry, under your own user account |

**The uninstaller removes the program only.** It does not remove your projects, your saved output, the analysis engine, or the downloaded models. The engine and the models use about 3 GB. To free the space, delete their folders by hand. The uninstaller tells you this before it starts.

---

## If something goes wrong

**The program does not start.** Make sure that you installed the program. Do not run the setup from inside a zip file. If the window does not appear, start the program from a terminal. In the installation folder, run `python\pythonw.exe -m qualsafe_qt`. Look for an error message.

**A document opens but you cannot code it.** The program does not code a document when it cannot map the character positions exactly. It does not guess, because your codes could then attach to the wrong words. Save the file again as plain UTF-8 text. This usually solves the problem.

**The survey screen says that the analysis engine is missing.** Press **Install the analysis engine** on the Models screen (see above). Everything except automatic coding still works.

**An install into a long folder path stopped part-way.** The cause is the Windows path limit. Uninstall the program. Install it again in a shorter path.

**Something else.** Press **F1** and read **Troubleshooting**. It covers more cases than this page.
