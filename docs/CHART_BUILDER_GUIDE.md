# Data Charts: chart any spreadsheet

Data Charts turns a CSV or Excel file into a chart for a slide or a report. It also gives you the table of numbers behind the chart. It is for survey data and institutional research data. It works on any ordinary table. It is a screen in the desktop app and a page in the web app. Both apps draw the same chart from the same choices.

Nothing leaves your computer. The program never changes your file. It reads the file into memory and works on a copy. It never writes to the original file.

## Five minutes with the sample

1. Open **Data Charts**. Press **Try the sample survey**. The sample is an invented file of 240 students.
2. Choose **Class year** as the field. A horizontal bar chart shows at once. Each bar has a label like this: `26% (63/240)`.
3. Under **Split by**, choose **First generation**. Now each class year has one bar for each group.
4. Set a **Title** and a **Footnote or source**. Under size, pick **Large**.
5. Press **Save picture…**. Choose PNG at 300 DPI. Put the picture in a slide.

Each change draws the chart again at once. There is no Generate button.

## Open a file

* **CSV, TSV, or text:** The program finds the separator (comma, semicolon, tab, or pipe) and the text encoding. The screen says what it found. The program reads a file that you saved from Excel as plain "CSV" correctly.
* **Excel (.xlsx, .xlsm, .xls):** If the workbook has several sheets, a sheet picker shows.
* The screen shows the first rows and the number of rows and columns. For each field it shows the type (categorical, numeric, date, yes/no, or free text). It shows how many answers are valid, how many are blank, and how many different values there are. Hover over the name of a field to see what the program noticed about it.

## What counts as blank

An empty cell is always blank. These values are also blank: `NULL`, `null`, `NaN`, `None`, `N/A`, `NA`, `(blank)`, and `<null>`. You can edit this list. A blank is **never** in the base of a percentage. The exceptions are the choices "All rows" and "A number I enter" under **Percentages are of**.

The program reports how many cells matched each word. If "None" is a real answer in your data, you see it. Then you can take it off the list.

The program ignores spaces at the start and at the end of an answer. You can tick "Treat repeated spaces inside a label as one". Then `Very  good` and `Very good` count together. The program **never merges** answers that differ only by spacing or capitals. The screen lists them and you decide.

## Four kinds of question

**One question (single choice).** One column of answers. The result is a frequency table, a percentage table, and bar, pie, or donut charts.

A column of numbers starts as a histogram. A column of dates starts as a line chart. This is usually what you want. You can pick any other chart.

**Matrix / Likert.** Choose several related columns, one for each statement. Each statement is one bar. Each response category is one segment. The program works out the base **for each statement**. The program puts the categories in scale order for scales of agreement, importance, satisfaction, and frequency. Answers like "No opinion" go last. You can also set your own order.

The charts are 100% stacked bars (the suggestion), stacked counts, grouped bars, one pie or donut for each statement, and a heatmap.

The **Top and bottom boxes** tab shows four shares for each statement. They are the top one, the top two, the bottom one, and the bottom two categories. A value reads `70% (7/10)`. The first number is the percent. The second number is how many people chose those categories. The third number is the base.

The second number is not the base. "No opinion" is not a point on the scale, so it is never in a box. You can choose if it stays in the base of the box.

**Select all that apply.** One column where a cell holds several answers. Choose the separator (comma, semicolon, pipe, new line, or your own).

Do not split on the separator when an answer contains it. `Relationships with friends, family, partners, or roommates` is one answer. It is not four answers. So paste the real list of choices, one choice on each line. Or press **Suggest choices from the data**.

The program then reads each cell and looks for those exact phrases. The program counts and reports each part that does not match a known choice. It never shows such a part as a fragment in a chart.

The base is the respondents who answered the question. So the percentages can add up to more than 100%. The chart says this: "Percent of respondents selecting each option; multiple selections allowed".

**Free text.** The result shows the number of responses and the most common words. The program counts each word one time for each response. It removes common words. You also get a button to save all the responses as a file. The program does not make a chart of categories unless you ask.

## Refine the chart without changing the data

* **Filters:** Keep the rows where a field is one of some values. Or keep the rows where it is above a number, between two numbers, or blank. Or keep the rows where it contains some text.
* **The category grid:** It has five controls in one table. Clear **Include** to leave a category out. The category then leaves the base too. Type a new **Display name** to rename a category. Type the same text under **Combine into** on several rows to make one new category. Give a **Position** to set your own order. The **Colour** column takes a hex code. An example is `#BC912C`.
* **Blank answers:** You can leave them out (the default). Or you can show them as their own category.
* **Order:** highest to lowest, lowest to highest, alphabetical, the order of the file, scale order (Likert), or your Position column.
* **Percentages are of:** valid responses, all rows, or a number that you type.
* **Undo, Redo, and Reset chart:** They step back through fields, filters, renaming, combining, and sorting. Titles and colours are not part of Undo. Reset clears every choice for this file. Undo brings the choices back.

The program refuses a rename that gives two categories the same name. It shows a sentence. It does not merge them without telling you.

## Charts

For categories, you can make vertical bars, horizontal bars, grouped bars, stacked bars, 100% stacked bars, pie, donut, and heatmap. For numbers, you can make a histogram, a box plot, and a scatter chart. For dates or ordered fields, you can make a line chart and an area chart.

* **Histogram:** The program chooses the bins from the data, or you set them. **Split by** puts the groups over each other on the same bins. The last bin includes its upper edge.
* **Box plot:** The box goes from the 25th percentile to the 75th percentile. A line shows the median. Whiskers reach the furthest value that is within 1.5 times the height of the box. The program draws values beyond that as points. It counts them. It never removes them.
* **Scatter:** The field is the horizontal axis. The second number is the vertical axis. The program plots only the rows that have both numbers. The screen says how many rows it did not plot. You can add a line of best fit. The program reports its slope, r, and count.
* **Line and area:** The program groups dates into days, weeks, months, quarters, or years. It chooses the group from the time span, unless you pick one. Empty periods show as zero for counts. They show as gaps for averages.

The suggested chart is only a suggestion. The program never suggests a pie only because a field is categorical. It never suggests a pie for an ordered scale.

## Size, labels, and appearance

There are four sizes (small to extra large). They change the thickness of the bars and the size of the text together. You can set these items:

* a title, a subtitle, a footnote, axis titles, and the title and position of the legend
* data labels (percent, count, valid N) and decimal places
* gridlines, axis limits, label wrapping, and the longest label line
* the shape of the figure: 16:9 PowerPoint, 4:3, square, report, or your own width and height

## Colours

The default is **QualSafe default**. Gold is for a single series. Blue is for the second series. Silver is for the lowest category or a neutral category. Light purple is for the next category. The background is white. The gridlines are light grey.

The program colours ordered answers from low to high. For example, strongly disagree is silver, somewhat disagree is light purple, neutral is blue, and agree is gold. A thin white border separates neighbouring segments that have the same colour.

There are also the themes Colour-blind safe (Okabe-Ito), Grayscale, and Ocean. Use **Make my own theme** to type hex codes for the primary, secondary, neutral, background, text, title, and gridline colours. You can also add extra colours and a category order. The program keeps a theme that you make for next time.

You can also set the colour of one category. You can share a theme as a file. You can add a theme that someone sent you. Press **Reset to the default** to go back to the default.

## Get the chart out

* **Picture:** PNG, SVG, or PDF. For PNG, choose 96, 150, 300, or 600 DPI. The background is white or transparent. A 16:9 figure at 300 DPI is 4000 by 2250 pixels. SVG and PDF stay sharp at any size. In the desktop app, **Copy picture** puts the picture on the clipboard. Then you can paste it into PowerPoint or Word.
* **Table:** The numbers behind each chart. You can add totals, valid N, and missing N. Save the table as CSV or Excel, or copy and paste it. If you split a chart by a field, the table has a column for that field.
* The program names the files after the title of the chart. It makes the names safe for Windows. It removes forbidden characters. It makes the names shorter, so the full path stays under the limit of 260 characters.

## Save a chart to open later

**Save chart** stores your choices. It does not store the data. It stores the fields, filters, renaming, order, base, colours, labels, and size. It also stores the names of the columns of the file that you made the chart for.

Open the chart on the same kind of file. It draws the same chart. If the new file does not have a field that the chart used, the program clears that choice. The screen says which choice. You can also save a chart as a file to send to a colleague.

The program keeps saved charts and your own themes in your user folder. On Windows the folder is `%APPDATA%\QualSafe\chartbuilder`. On a Mac the folder is `~/Library/Application Support/QualSafe/chartbuilder`. They stay after an uninstall. A saved chart contains the category labels that you renamed or excluded (for example "Very important"). It contains no rows of your data.

## Limits

* A scatter chart draws every point. It gives a warning above 5,000 points.
* A histogram uses bins of equal width.
* The program leaves data labels off dense charts (more than 15 bins or points). Then the chart stays easy to read.
* Old `.xls` files need the small `xlrd` component. The installer includes it.
* The desktop preview is a picture of the exact export. So it does not show hover tips.
