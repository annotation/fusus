"""Book workflow
"""

import sys
import os
import collections

import cv2

from tf.core.timestamp import Timestamp

from .parameters import Config
from .lib import (
    imageFileList,
    imageFileListSub,
    pagesRep,
    select,
    showImage,
    splitext,
)
from .clean import reborder
from .page import Page
from .ocr import OCR, showConf, getProofColor


class Book:
    def __init__(self, **params):
        """Engine for book conversion.

        Parameters
        ----------
        params: dict, optional
            Any number of customizable settings from `fusus.parameters.SETTINGS`.

            They will be in effect when running the workflow, until
            a `Book.configure` action will modify them.
        """

        tm = Timestamp()
        self.tm = tm
        self.C = Config(tm, **params)
        self._applySettings()
        self.OCR = OCR(self)

    def _applySettings(self):
        """After a settings update, recompute derived settings."""

        C = self.C
        whit = C.whiteGRS
        markParams = C.markParams
        tm = self.tm
        error = tm.error

        self.marks = {}
        marks = self.marks
        offsetBand = {band: offset for (band, offset) in C.offsetBand.items()}
        self.offsetBand = offsetBand

        files = imageFileListSub(C.marksDir)

        seq = 0

        for (band, images) in files.items():
            for f in images:
                tweakDict = {}
                bare = splitext(f)[0]
                parts = bare.rsplit("(", 1)
                if len(parts) > 1:
                    bare = parts[0]
                    tweaks = parts[1][0:-1].split(",")
                    for tweak in tweaks:
                        if "=" not in tweak:
                            error(f"Malformed image parameter for {bare}: {tweak}")
                            continue
                        (k, v) = tweak.split("=", 1)
                        if k not in markParams:
                            error(f"Unknown image parameter for {bare}: {k} in {k}={v}")
                            continue
                        try:
                            tweakDict[k] = int(v) if k == "bw" else float(v)
                        except Exception:
                            error(f"Unknown image parameter for {bare}: {v} in {k}={v}")

                full = f"{C.marksDir}/{band}/{f}"
                image = cv2.imread(full)
                gray = reborder(
                    cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), 4, whit, crop=True
                )

                seq += 1
                marks.setdefault(band, {})[bare] = dict(gray=gray, seq=seq)
                dest = marks[band][bare]
                for (k, kLong) in markParams.items():
                    dest[kLong] = tweakDict.get(k, getattr(C, kLong))

        self.allPages = imageFileList(C.inDir)
        self.allPagesDesc = pagesRep(self.allPages)
        self.allPagesList = pagesRep(self.allPages, asList=True)

    def configure(self, reset=False, **params):
        """Updates current settings based on new values.

        The signature is the same as `fusus.parameters.Config.configure`.
        """

        self.C.configure(reset=reset, **params)
        self._applySettings()

    def showSettings(self, params=None):
        """Display settings.

        Parameters
        ----------
        params: dict, optional
            Any number of customizable settings from `fusus.parameters.SETTINGS`.

            The current values of given parameters will be displayed.
            The values that you give each of the `params` here is not used,
            only their names. It is recommended to pass `None` as values:

            `B.showSettings(blurX=None, blurY=None)`
        """
        self.C.show(params=params)

    def availableBands(self):
        """Display the characteristics of all defined *bands*."""

        tm = self.tm
        info = tm.info

        info("Available bands and their offsets", tm=False)
        for (band, offset) in sorted(self.offsetBand.items()):
            bandRep = f"«{band}»"
            info(
                f"\t{bandRep:<10}: top={offset[0]:>4}, bottom={offset[1]:>4}", tm=False
            )

    def availableMarks(self, band=None, mark=None):
        """Display the characteristics of defined *marks*.

        Parameters
        ----------
        band: string, optional `None`
            Show only marks in this band. If `None`, show marks in all bands.
        mark: string, optional `None`
            Show only marks in with this name. If `None`, show marks with any name.
        """

        C = self.C
        grey = C.greyGRS
        tm = self.tm
        info = tm.info
        marks = self.marks

        info("Marks and their settings", tm=False)
        for (bnd, markItems) in sorted(marks.items()):
            if band is not None and band != bnd:
                continue
            bandRep = f"[{bnd}]"
            info(f"\tband {bandRep}", tm=False)
            for (mrk, markInfo) in sorted(markItems.items()):
                if mark is not None and mark != mrk:
                    continue
                markRep = f"«{mrk}»"
                seq = markInfo["seq"]
                acc = markInfo["accuracy"]
                bw = markInfo["connectBorder"]
                r = markInfo["connectRatio"]
                info(
                    f"\t\t{seq:>3}: {markRep:<20} acc={acc}, bw={bw}, r={r}",
                    tm=False,
                )
                markImage = reborder(markInfo["gray"], 2, grey)
                showImage(markImage)

    def availablePages(self):
        """Display the amount and page numbers of all pages."""

        tm = self.tm
        info = tm.info

        allPages = self.allPages
        pagesDesc = self.allPagesDesc

        info(f"{len(allPages)} pages: {pagesDesc}")

    def _doPage(
        self,
        f,
        batch=False,
        boxed=True,
        quiet=False,
        doOcr=True,
        uptoLayout=False,
        **kwargs,
    ):
        """Process a single page.

        Executes all processing steps for a single page.

        Parameters
        ----------
        f: string
            The file name of the scanned page with extension, without directory
        batch: boolean, optional `False`
            Whether to run in batch mode.
            In batch mode everything is geared to the final output.
            Less intermediate results are computed and stored.
            Less feedback happens on the console.
        boxed: boolean, optional `True`
            If in batch mode, produce also images that display the cleaned marks
            in boxes.
        quiet: boolean, optional `False`
            Whether to suppress warnings and the display of stroke separators.
        doOcr: boolean, optional `True`
            Whether to perform OCR processing
        uptoLayout: boolean, optional `False`
            Whether to stop after doing layout

        Returns
        -------
        A `fusus.page.Page` object, which is the handle for further
        inspection of what has happened during processing.
        """

        tm = self.tm
        info = tm.info
        indent = tm.indent
        if quiet:
            tm.silentOn(deep=True)
        else:
            tm.silentOff()

        # baseLevel = 1 if batch else 0
        baseLevel = 1
        subLevel = baseLevel + 1
        indent(level=baseLevel, reset=True)

        bare = splitext(f)[0]

        if not batch:
            info(f"Processing {bare}")

        page = Page(self, f, batch=batch, boxed=boxed, **kwargs)
        if batch or not page.empty:
            if not batch:
                indent(level=subLevel, reset=True)
                info("normalizing")
            page.doNormalize()
            if page.empty:
                return page

            if not batch:
                info("layout")
            page.doLayout()
            if not uptoLayout:
                if not batch:
                    info("cleaning")
                page.cleaning(showKept=not batch or boxed)
                if not page.empty and doOcr:
                    if not batch:
                        info("ocr")
                    page.ocring()

        tm.silentOff()

        return page

    def process(
        self,
        pages=None,
        batch=True,
        quiet=True,
        boxed=False,
        doOcr=True,
        uptoLayout=False,
        **kwargs,
    ):
        """Process directory of images.

        Executes all processing steps for all images.

        Parameters
        ----------
        pages: string | int, optional `None`
            Specification of pages to do. If absent or `None`: all pages.
            If an int, do only that page.
            Otherwise it must be a comma separated string of (ranges of) page numbers.
            Half ranges are also allowed: `-10` (from beginning up to and including `10`)
            and `10-` (from 10 till end).
            E.g. `1` and `5-7` and `2-5,8-10`, and `-10,15-20,30-`.
            No spaces allowed.
        batch: boolean, optional `True`
            Whether to run in batch mode.
            In batch mode everything is geared to the final output.
            Less intermediate results are computed and stored.
            Less feedback happens on the console.
        boxed: boolean, optional `False`
            If in batch mode, produce also images that display the cleaned marks
            in boxes.
        quiet: boolean, optional `True`
            Whether to suppress warnings and the display of stroke separators.
        doOcr: boolean, optional `True`
            Whether to perform OCR processing
        uptoLayout: boolean, optional `False`
            Whether to stop after doing layout

        Returns
        -------
        A `fusus.page.Page` object for the last page processed,
        which is the handle for further
        inspection of what has happened during processing.
        """

        tm = self.tm
        info = tm.info
        indent = tm.indent

        allPages = self.allPages

        tm.silentOff()

        indent(reset=True)

        C = self.C
        interDir = C.interDir
        outDir = C.outDir
        cleanDir = C.cleanDir
        proofDir = C.proofDir
        textDir = C.textDir

        for d in (interDir, outDir, cleanDir, proofDir, textDir):
            if not os.path.exists(d):
                os.makedirs(d, exist_ok=True)

        imageFiles = select(allPages, pages)
        pagesDesc = pagesRep(imageFiles)
        info(f"Batch of {len(imageFiles)} pages: {pagesDesc}")

        info("Start batch processing images")
        page = None

        for (i, imFile) in enumerate(sorted(imageFiles)):
            indent(level=1, reset=True)
            msg = f"{i + 1:>5} {imFile:<40}"
            info(f"{msg}\r", nl=False)
            page = self._doPage(
                imFile,
                batch=batch,
                boxed=boxed,
                quiet=quiet,
                doOcr=doOcr,
                uptoLayout=uptoLayout,
                **kwargs,
            )
            if not page.empty:
                page.write(stage="normalized,clean", perBlock=False)
                if uptoLayout:
                    info(f"{msg}")
                else:
                    if not batch:
                        page.write(stage="markData")
                    if boxed:
                        page.write(stage="boxed")
                    info(f"{msg}")
        indent(level=0)
        info("all done")

        return page  # the last page processed

    def stageDir(self, stage):
        C = self.C
        (stageType, stageColor, stageExt, stageDir, stagePart) = C.stages[stage]
        trail = stage if stagePart is None else "" if not stagePart else stagePart
        trail = "" if not trail else f"-{trail}"
        return (getattr(C, stageDir or "interDir"), trail, stageExt)

    def measureQuality(self, pages=None, showStats=True, updateProofs=False):
        """Measure the reported quality of the ocr processing.

        pages: string | int, optional `None`
            Specification of pages to do. If absent or `None`: all pages.
            If an int, do only that page.
            Otherwise it must be a comma separated string of (ranges of) page numbers.
            Half ranges are also allowed: `-10` (from beginning up to and including `10`)
            and `10-` (from 10 till end).
            E.g. `1` and `5-7` and `2-5,8-10`, and `-10,15-20,30-`.
            No spaces allowed.

        showStats: boolean, optional `True`
            Compute and show quality statistics

        updateProofs: boolean, optional `False`
            If true, regenerate all proofing pages.
            This is desriable if you have tweaked the coloring of OCR results
            depending on the confidence.
            The OCR itself does not have to be performed again for this.
        """

        tm = self.tm
        info = tm.info
        indent = tm.indent

        allPages = self.allPages

        imageFiles = select(allPages, pages)
        pagesDesc = pagesRep(imageFiles)
        info(f"Batch of {len(imageFiles)} pages: {pagesDesc}")

        info("Start measuring ocr quality of these images")
        if updateProofs:
            info("  end regenrating proof files")

        page = None

        results = dict(char=[], word=[])
        resultsChar = collections.defaultdict(list)

        for (i, imFile) in enumerate(sorted(imageFiles)):
            indent(level=1, reset=True)
            msg = f"{i + 1:>5} {imFile:<40}"
            info(f"{msg}\r", nl=False)
            page = Page(self, imFile, minimal=True)
            page.read(stage=("normalized,line," if updateProofs else "") + "word,char")
            if page.empty:
                continue

            if updateProofs:
                page.proofing()

            if not showStats:
                continue

            stages = page.stages
            pg = page.bare
            pageRep = f"p{pg}"

            for stage in ("word", "char"):
                proofStage = f"proof{stage}"
                thisPageRep = f"""<a href="{page.stagePath(proofStage)}">p{pg}</a>"""
                isCharStage = stage == "char"

                n = 0
                totC = 0
                (minC, maxC) = (100, 0)

                for fields in stages[stage]:
                    conf = int(fields[-2])
                    totC += conf
                    if conf < minC:
                        minC = conf
                    if conf > maxC:
                        maxC = conf
                    n += 1
                    if isCharStage:
                        c = fields[-1]
                        resultsChar[c].append((pageRep, conf))
                if n > 0:
                    results[stage].append((thisPageRep, n, minC, maxC, totC, ""))

        if not showStats:
            indent(level=0)
            info("all done")
            return

        for stage in ("word", "char"):
            stageResults = results[stage]
            if not len(stageResults):
                continue
            grandN = sum(r[1] for r in stageResults)
            grandMin = min(r[2] for r in stageResults)
            grandMax = max(r[3] for r in stageResults)
            grandTot = sum(r[4] for r in stageResults)

            toShow = [
                ("overall", grandN, grandMin, grandMax, grandTot, "")
            ] + stageResults

            info(f"{stage}-confidences of OCR results for {len(stageResults)} pages")
            showConf(stage, toShow)

        info(f"by-char-confidences of OCR results for {len(resultsChar)} characters")
        resultsCollected = []
        (sDir, sTrail, sExt) = self.stageDir("proofchar")
        for c in sorted(resultsChar):
            occs = sorted(resultsChar[c], key=lambda x: x[1])
            worstExamples = " ".join(
                f"""\
<a
    style="background-color: {getProofColor(x[1])};"
    href="{sDir}/{x[0][1:]}{sTrail}.{sExt}"
>{x[0]}</a>\
"""
                for x in occs[0:20]
            )
            nOccs = len(occs)
            minC = min(r[1] for r in occs)
            maxC = max(r[1] for r in occs)
            totC = sum(r[1] for r in occs)
            resultsCollected.append((f"⌊{c}⌋", nOccs, minC, maxC, totC, worstExamples))
        showConf(stage, resultsCollected, label="worst results")

        indent(level=0)
        info("all done")

    def plainText(self, pages=None):
        """Get the plain text from the ocr output in one file

        pages: string | int, optional `None`
            Specification of pages to do. If absent or `None`: all pages.
            If an int, do only that page.
            Otherwise it must be a comma separated string of (ranges of) page numbers.
            Half ranges are also allowed: `-10` (from beginning up to and including `10`)
            and `10-` (from 10 till end).
            E.g. `1` and `5-7` and `2-5,8-10`, and `-10,15-20,30-`.
            No spaces allowed.

        The output is written to the `text` subdirectory.
        """

        tm = self.tm
        info = tm.info
        indent = tm.indent

        C = self.C
        textDir = C.textDir
        if not os.path.exists(textDir):
            os.makedirs(textDir, exist_ok=True)

        allPages = self.allPages

        imageFiles = select(allPages, pages)
        pagesDesc = pagesRep(imageFiles)
        info(f"Batch of {len(imageFiles)} pages: {pagesDesc}")

        info("Start producing plain text of these pages")

        page = None

        path = f"{textDir}/{pagesDesc}.html"

        doc = """\
<html>
  <head>
  <meta charset="utf-8"/>
<style>
body {
  font-size: x-large;
  text-align: right;
  direction: rtl;
}
div.page {
  text-align: right;
}
div.stripe {
  display: flex;
  flex-flow: row nowrap;
}
div.c, div.cl, div.cr {
  text-align: right;
}
h3 {
  text-align: right;
}
span.ln {
  font-style: italic;
  font-size: small;
  vertical-align: super;
  text-align: right;
}
</style>
  </head>
«body»
</body>
</html>
"""
        body = []

        for (i, imFile) in enumerate(sorted(imageFiles)):
            pageMaterial = []
            indent(level=1, reset=True)
            msg = f"{i + 1:>5} {imFile:<40}"
            info(f"{msg}\r", nl=False)
            page = Page(self, imFile, minimal=True)
            page.read(stage="word")
            pg = page.bare.lstrip("0")
            if pg == "":
                pg = "0"
            pg = int(pg)
            pageRep = f"p{pg:>03}"
            pageMaterial.append(f"""<div page="{pageRep}"><h3>{pg}</h3>""")

            if page.empty:
                pageMaterial.append("""</div>""")
                body.append("\n".join(pageMaterial))
                continue

            stages = page.stages
            stage = "word"

            (prevStripe, prevColumn, prevLine) = (None, None, None)
            stripeMaterial = []
            columnMaterial = []
            lineMaterial = []

            for fields in stages[stage]:
                (stripe, column, line) = fields[0:3]
                if stripe != prevStripe:
                    if prevStripe is not None:
                        stripeMaterial.append("</div>")
                        pageMaterial.append("\n".join(stripeMaterial))
                        stripeMaterial = []
                    stripeMaterial.append(f"""<div class="stripe" stripe="{stripe}">""")
                    prevColumn = None
                if column != prevColumn:
                    if prevColumn is not None:
                        columnMaterial.append("</div>")
                        stripeMaterial.append("\n".join(columnMaterial))
                        columnMaterial = []
                    columnMaterial.append(f"""<div class="c{column}">""")
                    prevLine = None
                if line != prevLine:
                    if prevLine is not None:
                        lineMaterial.append("</div>")
                        columnMaterial.append(" ".join(lineMaterial))
                        lineMaterial = []
                    lineMaterial.append(
                        f"""<div line="{line}"><span class="ln">{line}</span>"""
                    )
                (prevStripe, prevColumn, prevLine) = (stripe, column, line)

                word = fields[-1]
                lineMaterial.append(word)

            columnMaterial.append(" ".join(lineMaterial))
            stripeMaterial.append("\n".join(columnMaterial))
            pageMaterial.append("\n".join(stripeMaterial))
            pageMaterial.append("</div>")
            body.append("\n".join(pageMaterial))

        indent(level=0)
        with open(path, "w") as f:
            f.write(doc.replace("«body»", "\n".join(body)))
        info(f"written to {path}")


def main():
    """Process a whole book with default settings.

    Go to the book directory and say

    ```
    python3 -m fusus.book [pages]
    ```

    where `pages` is an optional string specifying ranges
    of pages as in `Book.process`
    """

    pages = None
    if len(sys.argv) > 1:
        pages = sys.argv[1]
    B = Book()
    B.process(pages=pages)


if __name__ == "__main__":
    main()
