# When something goes wrong

**My file will not open.**
Save it from Excel as a plain CSV and try again. If accents or apostrophes look wrong, the file was probably saved as a different kind of CSV; save it again as plain CSV. Older .xls files may not open: save them as .xlsx or CSV. If a workbook has several sheets, you are asked which one.

**The analysis is slow.**
The first run loads the models, which takes a minute or more. Press **Quick preview** first. It tries 50 answers and tells you what to expect. Written-codebook coding shows an estimate before it starts: roughly three minutes to begin, then a few seconds for each code on each answer, on a typical laptop. Closing other programs helps.

**Too many answers need review.**
On the **Code** step, open **More options**, then **Check suggestions**. The two limits decide how many answers are marked. Lower them to check fewer answers, but read a few of the answers left unmarked too.

**A theme has no agreement figure.**
It was used on too few answers for a figure to mean anything. Code more answers with that theme, or read it as a note, not a result.

**Agreement says it needs two coders.**
Agreement is only defined on answers two coders both coded. Code a sample yourself (see **How do I check the computer's coding against mine?**), or bring in a second person's coding.

**It says an extra component is needed.**
The analysis engine is installed separately (**Settings**, then **Models**, then **Install the analysis engine**), and the written codebook also needs a one-time download. **Settings**, then **Models**, shows what is on your computer and what each part costs. One modelling method needs another small component that may be missing from your copy; choose a different method and carry on.

**The privacy check asks me every time.**
That is on purpose. You confirm it each time you load a file, and QualSafe never remembers that you did.

**I cannot find my work.**
On **Home**, each activity has **Continue**. Projects are files you saved, ending in .qnw; the **File** menu opens them. Survey runs are written to an output folder next to the program, one folder for each run.

**A run stopped part-way.**
The folder for that run holds a file called run_config.json that records exactly what was asked for. Nothing is written to your project until a run finishes. Run it again.

**A PDF imported with no text.**
It is probably a scan: a picture of a page with no text in it. Run it through text recognition (OCR) first.

**Coding is switched off for one document.**
Its characters could not be matched to the reader reliably, so QualSafe will not attach codes rather than risk putting them on the wrong passage. Please report the document.

**Drafting a framework cell does nothing.**
Drafting needs a local language model to be running. It is optional; everything else works without it.

**The text is too small.**
**View**, then **Appearance** sets the text size for the whole program. You can also drag the dividers between panels.

**QualSafe would not install or start.**
The install guide that came with QualSafe (INSTALL_DESKTOP.md) covers installing, checking the download, and what to do if the installer is blocked.

**Something else.**
The status bar shows the last message and the run folder holds its settings. Both help when you ask for help.
