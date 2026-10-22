# Data Charts: chart any spreadsheet

Data Charts turns a CSV or Excel file into a chart for a slide or a report, and
gives you the table of numbers behind it. It is built for survey and
institutional research data and works on any ordinary table. It is a screen in
the desktop app and a page in the web app, and the two draw the same chart from
the same choices.

Nothing leaves your computer, and your file is never changed. The program reads
it into memory, works on a copy, and never writes to the original.

## Five minutes with the sample

1. Open **Data Charts** and press **Try the sample survey** (an invented file of
   240 students).
2. Choose **Class year** as the field. A horizontal bar chart appears at once,
   with each bar labelled like `26% (63/240)`.
3. Under **Split by**, choose **First generation**. You now have one bar per group
   for each class year.
4. Set a **Title** and a **Footnote or source**. Pick **Large** under size.
5. **Save picture…**, choose PNG at 300 DPI, and drop it into a slide.

Every change redraws the chart straight away. There is no Generate button.

## Opening a file

* **CSV, TSV or text**: the separator (comma, semicolon, tab or pipe) and the
  text encoding are worked out for you, and the screen says what it found. A file
  saved from Excel as plain "CSV" is read correctly.
* **Excel (.xlsx, .xlsm, .xls)**: if the workbook has several sheets, a sheet
  picker appears.
* You see the first rows, the row and column counts, and for every field its
  type (categorical, numeric, date, yes/no or free text), how many answers are
  valid, how many are blank, and how many different values it has. Hover a field
  name for anything the program noticed about it.

## What counts as blank

Empty cells always count as blank. So do `NULL`, `null`, `NaN`, `None`, `N/A`,
`NA`, `(blank)` and `<null>`. You can edit that list. Blanks are **never** in the
base of a percentage unless you choose "All rows" or "A number I enter" under
**Percentages are of**. The program reports how many cells matched each word, so
if "None" is a real answer in your data you will see it and can take it off the
list.

Spaces at the start and end of an answer are ignored. If you tick "Treat repeated
spaces inside a label as one", `Very  good` and `Very good` count together. Answers
that differ only by spacing or capitals are **never merged for you**; the screen
lists them and you decide.

## Four kinds of question

**One question (single choice).** One column of answers. You get a frequency
table, a percentage table and bar, pie or donut charts. A column of numbers starts
as a histogram and a column of dates as a line chart, because that is usually
what you want; you can pick any other chart.

**Matrix / Likert.** Choose several related columns (one per statement). Each
statement becomes one bar, each response category one segment, and the base is
worked out **per statement**. Categories are put in scale order automatically for
agreement, importance, satisfaction and frequency scales, with "No opinion" style
answers last, or in an order you set. Charts: 100% stacked bars (the suggestion),
stacked counts, grouped bars, one pie or donut per statement, and a heatmap.

The **Top and bottom boxes** tab gives, for each statement, the share in the top
one, top two, bottom one and bottom two categories. A value reads `70% (7/10)`:
the percent, then how many chose those categories, then the base. The second
number is the base, not the number who chose the category. "No opinion" is not a
point on the scale, so it is never in a box; you can choose whether it stays in
the box's base.

**Select all that apply.** One column where a cell holds several answers.
Choose the separator (comma, semicolon, pipe, new line or your own). Splitting on
the separator is not safe when an answer contains it: `Relationships with
friends, family, partners, or roommates` is one answer, not four. So paste the
real list of choices, one per line (or press **Suggest choices from the data**),
and each cell is read by finding those exact phrases. Anything that does not match
a known choice is counted and reported, never charted as a fragment. The base is
the respondents who answered the question, so the percentages can add to more than
100%, and the chart says so: "Percent of respondents selecting each option;
multiple selections allowed".

**Free text.** You get the number of responses, the most common words (each word
counted once per response, common words removed) and a button to save all the
responses as a file. It is not turned into a chart of categories unless you ask.

## Refining without changing the data

* **Filters**: keep rows where a field is one of some values, above a number,
  between two numbers, contains some text, or is blank.
* **The category grid** carries five controls in one table. Untick **Include** to
  leave a category out (it also leaves the base). Type a new **Display name** to
  relabel it. Type the same text under **Combine into** on several rows to make
  one new category. Give a **Position** to set your own order. A **Colour** column
  takes a hex code such as `#BC912C`.
* **Blank answers** can be left out (the default) or shown as their own category.
* **Order**: highest to lowest, lowest to highest, alphabetical, the file's own
  order, scale order (Likert) or your Position column.
* **Percentages are of**: valid responses, all rows, or a number you type.
* **Undo, Redo and Reset chart** step back through fields, filters, relabelling,
  combining and sorting. Titles and colours are not part of Undo. Reset clears every
  choice for this file, and Undo brings them back.

A relabel that would make two categories share a name is refused with a sentence
instead of quietly merging them.

## Charts

Vertical and horizontal bars, grouped bars, stacked and 100% stacked bars, pie,
donut and heatmap for categories; histogram, box plot and scatter for numbers;
line and area for dates or ordered fields.

* **Histogram**: bins are chosen from the data or set by you. **Split by** lays
  the groups over each other on the same bins. The last bin includes its upper
  edge.
* **Box plot**: the box runs from the 25th to the 75th percentile with a line at
  the median. Whiskers reach the furthest value within 1.5 times the box height.
  Values beyond that are drawn as points and counted, never removed.
* **Scatter**: the field is the horizontal axis and the second number the vertical
  one. Only rows with both numbers are plotted, and the screen says how many were
  not. An optional line of best fit is reported with its slope, r and count.
* **Line and area**: dates are grouped into days, weeks, months, quarters or years
  (chosen from the span unless you pick). Empty periods show as zero for counts
  and as gaps for averages.

The suggestion is only a suggestion. A pie is never suggested just because a
field is categorical, and never for an ordered scale.

## Size, labels and the look

Four sizes (small to extra large) change bar thickness and text together. You can
set a title, subtitle, footnote, axis titles, legend title and position, data
labels (percent, count, valid N), decimal places, gridlines, axis limits, label
wrapping and the longest label line, and the figure shape: 16:9 PowerPoint, 4:3,
square, report, or your own width and height.

## Colours

**QualSafe default** is the default: gold for a single series, blue for the
second, silver for the lowest or neutral category, light purple for the next, a
white background and light grey gridlines. Ordered answers are coloured from low to
high (for example strongly disagree in silver, somewhat disagree in light purple,
neutral in blue, agree in gold), and where neighbouring segments share a colour a
thin white border keeps them apart.

There are also Colour-blind safe (Okabe-Ito), Grayscale and Ocean themes. **Make my
own theme** lets you type hex codes for the primary, secondary, neutral, background,
text, title and gridline colours, plus extra colours and a category order. A theme
you make is kept for next time. You can also set the colour of one category, share a
theme as a file, add one someone sent you, and **Reset to the default**.

## Getting the chart out

* **Picture**: PNG, SVG or PDF; 96, 150, 300 or 600 DPI for PNG; white or transparent
  background. A 16:9 figure at 300 DPI is 4000 by 2250 pixels. SVG and PDF stay sharp
  at any size. In the desktop app **Copy picture** puts it on the clipboard for
  PowerPoint or Word.
* **Table**: the numbers behind every chart, with optional totals, valid N and
  missing N; save as CSV or Excel, or copy and paste. A chart split by a field has
  a column for that field.
* Files are named after the chart title and made safe for Windows (forbidden
  characters removed, and shortened so the full path stays under the 260-character
  limit).

## Saving a chart to open later

**Save chart** stores the choices, not the data: the fields, filters, relabelling,
order, base, colours, labels and size, plus the names of the columns of the file it
was made for. Open it on the same kind of file and it draws the same chart. If the
new file lacks a field the chart used, that choice is cleared and the screen says
which. A chart can also be saved as a file to send to a colleague.

Saved charts and your own themes live in your user folder (`%APPDATA%\QualSafe\
chartbuilder` on Windows, `~/Library/Application Support/QualSafe/chartbuilder` on a
Mac). They survive an uninstall. A saved chart contains category labels you renamed
or excluded (for example "Very important") but no rows of your data.

## Limits worth knowing

* A scatter draws every point and warns above 5,000.
* A histogram uses equal-width bins.
* Data labels are left off dense charts (more than 15 bins or points) so they stay
  readable.
* Legacy `.xls` files need the small `xlrd` component, which the installer includes.
* The desktop preview is a picture of the exact export, so it does not show hover
  tips.
