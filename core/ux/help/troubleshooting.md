# When something goes wrong

**My file will not open.**
Save the file from Excel as a plain CSV. Then try again. If accents or apostrophes look wrong, the file has a different kind of CSV. Save it again as a plain CSV. Older .xls files can fail to open. Save them as .xlsx or CSV. If a workbook has several sheets, QualSafe asks which sheet to use.

**The analysis is slow.**
The first run loads the models. This takes a minute or more. Press **Quick preview** first. It tries 50 answers and shows what to expect. Written-codebook coding shows an estimate before it starts. On a typical laptop, it takes about three minutes to start. Then it takes a few seconds for each code on each answer. Close other programs to make it faster.

**Too many answers need review.**
On the **Code** step, open **More options**. Then open **Check suggestions**. Two limits decide how many answers QualSafe marks. Lower the limits to check fewer answers. Also read a few of the answers that QualSafe did not mark.

**A theme has no agreement figure.**
Too few answers use that theme, so a figure has no meaning. Code more answers with that theme. Or read the theme as a note and not as a result.

**Agreement says it needs two coders.**
Agreement uses only answers that two coders both coded. Code a sample yourself (see **How do I check the computer's coding against mine?**). Or ask a second person for their coding.

**It says an extra component is needed.**
You install the analysis engine separately. Open **Settings**, then **Models**, then press **Install the analysis engine**. The written codebook also needs a one-time download. **Settings**, then **Models**, shows what is on your computer and what each part costs. One modelling method needs another small component. Your copy can lack it. Choose a different method and continue.

**The privacy check asks me every time.**
This is on purpose. You confirm the check each time you load a file. QualSafe never remembers that you confirmed it.

**I cannot find my work.**
On **Home**, each activity has **Continue**. A project is a file that you saved. It ends in .qnw. The **File** menu opens it. QualSafe writes each survey run to an output folder next to the program. Each run has its own folder.

**A run stopped part-way.**
The folder for that run has a file named run_config.json. It records exactly what you asked for. QualSafe writes nothing to your project until a run finishes. Run it again.

**A PDF imported with no text.**
The PDF is probably a scan. A scan is a picture of a page with no text in it. First run the PDF through text recognition (OCR).

**Coding is switched off for one document.**
QualSafe could not match the characters of the document to the reader with confidence. QualSafe does not attach codes in this case. It could put them on the wrong passage. Please report the document.

**Drafting a framework cell does nothing.**
Drafting needs a local language model. The model must be running. The model is optional. Everything else works without it.

**The text is too small.**
Open **View**, then **Appearance**. Set the text size for the whole program there. You can also drag the dividers between the panels.

**QualSafe would not install or start.**
The install guide that came with QualSafe (INSTALL_DESKTOP.md) tells you how to install QualSafe and check the download. It also tells you what to do if something blocks the installer.

**Something else.**
The status bar shows the last message. The run folder holds the settings of the run. Both help when you ask for help.
