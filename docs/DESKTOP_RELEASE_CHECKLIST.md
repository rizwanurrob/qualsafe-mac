# Release checklist — QualSafe Desktop

What automated tests cannot check. The suite proves the code behaves; this page
exists for the things that only fail in front of a person — a blank icon, a
dialog that blocks forever, a file that says it was written and was not.

Every item here has failed at least once. None of them was caught by the tests.

Work through it on the **built installer**, not on a development checkout.

---

## 1. Build

- [ ] `python packaging/build_payload.py --keep-download` completes, and its
      own verification step prints `payload ok: <version>` with eight screens.
- [ ] `iscc packaging/qualsafe.iss /DAppVersion=<version>` compiles with no
      errors.
- [ ] The payload root contains only the expected entries — the build fails on
      anything else, but confirm the failure is not being skipped.
- [ ] The version in the installer filename matches `qualsafe_qt/version.py`.

## 2. Install, on a machine that has never had this program

The only way to find what the installer forgot. Ideally a machine that has
never had Python or a Hugging Face cache either.

- [ ] SHA-256 of the transferred file matches the one published.
- [ ] SmartScreen warning appears and **More info → Run anyway** proceeds.
      (Until signing exists this is expected; verify it is *possible*, since a
      user who cannot get past it cannot use the program at all.)
- [ ] Installs with **no** administrator prompt.
- [ ] Installing into a deliberately long folder path is refused with a
      readable message rather than failing part-way.
- [ ] Start Menu shortcut exists and launches.
- [ ] **No console window** appears behind the application, ever.

## 3. Identity — look at the screen

- [ ] The **taskbar** shows the QualSafe icon, not Python's, not a blank.
- [ ] **Alt+Tab** shows it.
- [ ] Right-click the taskbar button → **Pin to taskbar** works, and the pinned
      icon launches the program.
- [ ] **Help → About** reports the desktop version, and the engine version
      beside it.

## 4. Use it

- [ ] Walkthrough **A** end to end. Drag-select coding applies to the passage
      you actually selected — check one against the text.
- [ ] Margin stripes are legible where two codes overlap.
- [ ] **Ctrl+Z** and **Ctrl+Y**.
- [ ] Walkthrough **B**, if the engine is installed. The window stays usable
      while the run works — switch to Documents and read during it.
- [ ] **Both themes.** Switch in **View → Appearance…** and code a passage in
      each. Light mode has historically been the one that was verified late.

## 5. Reports

- [ ] Every report on the **Reports** screen writes a file that opens.
- [ ] The **methods appendix** says something sensible when no agreement is
      computable — a single-coder project must produce a statement, not an
      empty table.
- [ ] **The redaction claims are true.** With the quote options off, search each
      output for a distinctive phrase from your source text. It must not be
      there. This is the claim the screen makes in writing.

## 6. Data and erasure

- [ ] **Back up now** produces a listed backup; restoring returns the earlier
      state.
- [ ] Erasing a participant requires typing `ERASE`.
- [ ] After an erasure, the response is gone from the project **and** from the
      file's bytes — `strings project.qnw` (or any hex viewer) must not find it.
      This failed silently once and is the most consequential item on this page.
- [ ] With backup purging left on, `project_backups/` is gone afterwards.

## 7. Uninstall

- [ ] Uninstalling removes the program folder.
- [ ] A `.qnw` project saved elsewhere **survives**.
- [ ] Saved run output **survives**.
- [ ] The model cache **survives**.
- [ ] The Add/Remove Programs entry is gone.
- [ ] An unattended uninstall (`unins000.exe /VERYSILENT /SUPPRESSMSGBOXES`)
      completes rather than hanging on an invisible dialog.

## 7b. Data Charts (not covered by any automated test)

The tests draw charts offscreen with no fonts, so these need eyes on a real machine.

- [ ] Open **Data Charts**, press **Try the sample survey**, choose `Class year`: the chart
      appears with readable labels (fonts render, nothing is boxes or clipped).
- [ ] A Likert matrix, a select-all question, a histogram, a box plot and a line chart each
      draw and look right at 16:9.
- [ ] **Open a CSV or Excel file…** on a real file from Excel (plain "CSV", not "CSV UTF-8"):
      curly apostrophes read correctly. Also a workbook with several sheets, and an old
      `.xls` (this path has only been tested for its error message).
- [ ] **Copy picture**, then paste into PowerPoint and Word: the image arrives at the
      right size, on a white or transparent background as chosen.
- [ ] **Save picture…** as PNG (150 and 300 DPI), SVG and PDF: each opens, and the SVG is
      still sharp when scaled up.
- [ ] Make a colour theme with a typo in a hex code: the OK button stays off and the
      message names the colour. Save a good one, close the app, reopen: it is still there.
- [ ] **Save chart**, close the app, reopen, open a file with the same columns and press
      **Open**: the same chart. Open it on a file missing a column: the screen names it.
- [ ] The installer size is recorded (0.99.8 measured 122.9 MB, up from 103.6 MB, with `vl-convert`;
      0.99.9 measured 122.9 MB / 128,921,350 bytes, unchanged; 0.99.10 measured
      123.0 MB / 128,945,417 bytes).
- [ ] On a Mac: the same list, plus that `vl-convert` and `xlrd` installed for the Mac's chip.

## 8. Paperwork

- [ ] `CHANGELOG_DESKTOP.md` describes this version.
- [ ] `CITATION.cff` has a real family name; its `version`
      and `date-released` are this release (the version is checked by a test).
- [ ] `INSTALL_DESKTOP.md` still matches what the installer does.
- [ ] Publish the installer's SHA-256 next to the download.
- [ ] `THIRD_PARTY_NOTICES` covers PySide6 (LGPL v3), and the model licences if
      models are bundled.

---

## Only when signing exists

- [ ] Both `SignTool` lines uncommented in `packaging/qualsafe.iss`, including
      `SignedUninstaller` — the uninstaller is what a user runs later, when
      they trust the program least.
- [ ] `Get-AuthenticodeSignature` on the installer reports **Valid**.
- [ ] Downloading it no longer triggers SmartScreen.

---

## Recording the result

Note the date, the version, the machine, and anything that failed — including
anything you fixed on the spot. A checklist with no record of ever having been
run is indistinguishable from one that was skipped.
