import collections
import re
import pprint as pp

from itertools import chain
from unicodedata import name as uname

from IPython.display import display, HTML, Image

import fitz

from tf.core.helpers import setFromSpec
from .parameters import SOURCE_DIR

PP = pp.PrettyPrinter(indent=2)


def pprint(x):
    PP.pprint(x)


NAME = "Lakhnawi"
SOURCE = f"{SOURCE_DIR}/{NAME}/{NAME.lower()}.pdf"
FONT = f"{SOURCE_DIR}/{NAME}/Font report {NAME}.pdf"
DEST = f"{SOURCE_DIR}/{NAME}/{NAME.lower()}.txt"

CSS = """
<style>
.r {
    font-family: normal, sans-serif;
    font-size: 24pt;
    direction: rtl;
}
p {
    text-align: left;
    direction: ltr;
}
p.r {
    text-align: right;
    direction: rtl;
}
.l {
    font-family: normal, sans-serif;
    font-size: 16pt;
    direction: ltr;
    unicode-bidi: isolate-override;
}
.c {
    font-family: monospace;
    font-size: 12pt;
    direction: ltr;
}
.p {
    font-family: monospace;
    font-size: 12pt;
    font-weight: bold;
    background-color: yellow;
    direction: ltr;
}
td {
    text-align: left ! important;
}
</style>
"""

PUA_RANGES = (("e000", "f8ff"),)

SEMITIC_RANGES = (
    ("0600", "06ff"),
    ("0750", "077f"),
    ("08a0", "08ff"),
    ("206c", "206d"),
    ("fb50", "fdfd"),
    ("fe70", "fefc"),
    ("0591", "05f4"),
    ("206a", "206f"),
    ("fb1d", "fb4f"),
)

NO_SPACING_RANGES = (("064b", "0652"),)

BRACKET_RANGES = (
    ("0028", "0029"),  # parentheses
    ("003c", "003c"),  # less than
    ("003e", "003e"),  # greater than
    ("005b", "005b"),  # left  sq bracket
    ("005d", "005d"),  # right sq bracket
    ("007b", "007b"),  # left  brace
    ("007d", "007d"),  # right brace
    ("00ab", "00ab"),  # left  guillemet double
    ("00bb", "00bb"),  # right guillemet double
    ("2018", "201d"),  # qutation marks directed
    ("2039", "203a"),  # guillemets single
    ("2045", "2046"),  # sqare brackets with quill
    ("204c", "204d"),  # bullets directed
)

DIRECTION_RANGES = (
    ("202a", "202e"),  # control writing direction
    ("2066", "2069"),  # control writing direction
)

NEUTRAL_DIRECTION_RANGES = (
    ("0020", "0020"),
    ("2000", "2017"),
    ("201e", "2029"),
    ("202f", "2038"),
    ("203b", "2044"),
    ("204a", "2044"),
    ("2056", "2064"),
    ("201e", "206f"),
)

REPLACE_DEF = """
0627+e815 => 0623+064e : ALIF-HAMZA + FATA
e80e+e807 => fefc      : LAM + ALEF LIGATURE
e821      => 0640      : TATWEEL (short)
0640+e82b => 0670+640  : TATWEEL + SUPERSCRIPT ALEF
e825      => 064e      : FATHA (high)
e826      => 064f      : DAMMA (high)
e827      => 0651      : SHADDA (high)
e828      => 0652      : SUKUN (high)
e830      => 064e+0651 : FATHA+SHADDA LIG => non-isolated, separate chars
e831      => 064f+0651 : DAMMA+SHADDA LIG => non-isolated, separate chars
e845      => 0655+0650 : HAMZA+KASRA (low)
e8e8      => 064e      : FATHA (mid)
e864      => 0650      : KASRA (low)
e8df      => 0650      : KASRA (low)
e8e9      => 064f      : DAMMA
e8eb      => 0652      : SUKUN
fc60      => 064e+0651 : SHADDA+FATHA LIG => non-isolated, separate chars
"""


def uName(c):
    try:
        un = uname(c)
    except Exception:
        un = "NO NAME"
    return un


def getSetFromRanges(rngs):
    result = set()
    for (b, e) in rngs:
        for c in range(int(b, base=16), int(e, base=16) + 1):
            result.add(c)
    return result


REPLACE_RE = re.compile(r"""^([0-9a-z+]+)\s*=>\s*([0-9a-z+]*)\s*:\s*(.*)$""", re.I)


def getDictFromDef(defs):
    result = {}
    for line in defs.strip().split("\n"):
        match = REPLACE_RE.match(line)
        if not match:
            print(f"MALFORMED REPLACE DEF: {line}")
            continue
        (vals, repls, comment) = match.group(1, 2, 3)
        vals = vals.split("+")
        repls = [int(repl, base=16) for repl in repls.split("+")] if repls else []
        if len(vals) == 1:
            result.setdefault(int(vals[0], base=16), {})[None] = repls
        elif len(vals) == 2:
            result.setdefault(int(vals[0], base=16), {})[int(vals[1], base=16)] = repls
        else:
            print(f"MORE THAN 2 SOURCE CHARS IN REPLACE DEF: {line}")
            continue
    return result


U_LINE_RE = re.compile(r"""^U\+([0-9a-f]{4})([0-9a-f ]*)$""", re.I)
HEX_RE = re.compile(r"""^[0-9a-f]{4}$""", re.I)
PUA_RE = re.compile(r"""⌊([^⌋]*)⌋""")


def showString(x):
    display(HTML(f"""<p><span class="r"> {x} </span></p>"""))
    for c in x:

        display(
            HTML(
                f"""<p><span class="r">{c}</span>&nbsp;&nbsp;"""
                f"""<span class="c">{ord(c):>04x} {uName(c)}</span></p>"""
            )
        )


class Lakhnawi:
    def __init__(self):
        self.getCharConfig()
        self.doc = fitz.open(SOURCE)
        self.text = {}
        self.lines = {}

    def setStyle(self):
        display(HTML(CSS))

    def getCharConfig(self):
        self.puas = getSetFromRanges(PUA_RANGES)
        self.semis = getSetFromRanges(SEMITIC_RANGES)
        self.neutrals = getSetFromRanges(NEUTRAL_DIRECTION_RANGES)
        self.nospacings = getSetFromRanges(NO_SPACING_RANGES)
        self.replace = getDictFromDef(REPLACE_DEF)
        self.rls = self.puas | self.semis
        self.getCharInfo()

    def getCharInfo(self):
        self.doubles = {}
        self.privates = set()
        doubles = self.doubles
        privates = self.privates
        puas = self.puas

        doc = fitz.open(FONT)

        for page in doc:
            textPage = page.getTextPage()
            data = textPage.extractText()

            for (ln, line) in enumerate(data.split("\n")):
                if line.startswith("U+"):
                    match = U_LINE_RE.match(line)
                    if not match:
                        continue
                    (main, rest) = match.group(1, 2)
                    main = main.lower()
                    nMain = int(main, base=16)
                    if nMain in puas:
                        privates.add(nMain)
                        continue
                    if nMain == 0:
                        continue
                    second = None
                    rest = rest.replace(" ", "")
                    if rest:
                        if HEX_RE.match(rest):
                            second = rest.lower()
                    if second:
                        nSecond = int(second, base=16)
                        if nSecond > nMain:
                            doubles[nMain] = nSecond
                        else:
                            doubles[nSecond] = nMain

    def parsePageNums(self, pageNumSpec):
        doc = self.doc
        pageNums = (
            list(range(1, len(doc) + 1))
            if not pageNumSpec
            else [pageNumSpec]
            if type(pageNumSpec) is int
            else setFromSpec(pageNumSpec)
            if type(pageNumSpec) is str
            else list(pageNumSpec)
        )
        return [i for i in sorted(pageNums) if 0 < i <= len(doc)]

    def drawPages(self, pageNumSpec):
        doc = self.doc

        for pageNum in self.parsePageNums(pageNumSpec):
            page = doc[pageNum - 1]

            pix = page.getPixmap(matrix=fitz.Matrix(4, 4), alpha=False)
            display(Image(data=pix.getPNGData(), format="png"))

    def getPages(self, pageNumSpec, refreshConfig=False):
        if refreshConfig:
            self.getCharConfig()

        for pageNum in self.parsePageNums(pageNumSpec):
            self.pageNum = pageNum
            doc = self.doc
            page = doc[pageNum - 1]

            textPage = page.getTextPage()
            data = textPage.extractRAWDICT()
            self.collectPage(data)

    def plainPages(self, pageNumSpec):
        for pageNum in self.parsePageNums(pageNumSpec):
            lines = self.text.get(pageNum, [])

            for (i, line) in enumerate(lines):
                print(self.plainLine(line))

    def htmlPages(self, pageNumSpec):
        for pageNum in self.parsePageNums(pageNumSpec):
            lines = self.text.get(pageNum, [])

            html = []

            for (i, line) in enumerate(lines):
                html.append(f"""<p class="r">{self.htmlLine(line)}</p>\n""")
            display(HTML("".join(html)))

    def showInfo(self, pageNumSpec, onlyPuas=False, long=False):
        pageNums = self.parsePageNums(pageNumSpec)
        puas = self.puas
        rls = self.rls
        text = self.text

        charsOut = collections.defaultdict(collections.Counter)

        texts = {pageNum: text[pageNum] for pageNum in pageNums if pageNum in text}

        for (pageNum, pageText) in texts.items():
            for line in pageText:
                for span in line:
                    thesePuas = PUA_RE.findall(span[1])
                    for pua in thesePuas:
                        charsOut[chr(int(pua, base=16))][pageNum] += 1
                    if not onlyPuas:
                        rest = PUA_RE.sub("", span[1])
                        for c in rest:
                            charsOut[c][pageNum] += 1

        totalChars = len(charsOut)
        totalPages = len(set(chain.from_iterable(charsOut.values())))
        totalOccs = sum(sum(pns.values()) for pns in charsOut.values())

        charRep = "character" + ("" if totalChars == 1 else "s")
        occRep = "occurence" + ("" if totalOccs == 1 else "s")
        pageRep = "page" + ("" if totalPages == 1 else "s")

        label = "private use " if onlyPuas else ""

        html = []
        html.append(
            f"""
<p><b>{totalChars} {label}{charRep} in {totalOccs} {occRep}
on {totalPages} {pageRep}</b></p>
<table>
"""
        )
        for c in sorted(charsOut):
            xc = ord(c)
            ccode = f"""<span class="{"p" if xc in puas else "c"}">{xc:>04x}</span>"""
            crep = (
                ""
                if xc in puas
                else f"""<span class="{"r" if xc in rls else "l"}">{c}"""
            )
            cname = "" if xc in puas else f"""<span class="c">{uName(c)}</span>"""

            pageNums = charsOut[c]
            nPageNums = len(pageNums)
            pageRep = "page" + ("" if nPageNums == 1 else "s")
            thistotal = sum(pageNums.values())
            html.append(
                f"""
<tr>
    <td>{ccode}</td>
    <td>{crep}</td>
    <td>{cname}</td>
    <td><b>{thistotal}</b> on <i>{nPageNums}</i> {pageRep}</td>
</tr>
"""
            )
            if long:
                for pn in sorted(pageNums):
                    occs = pageNums[pn]
                    html.append(
                        f"""
<tr>
    <td></td>
    <td><i>page {pn:>3}</i>: <b>{occs:>3}</b></td>
</tr>
"""
                    )
        html.append("</table>")
        display(HTML("".join(html)))

    def collectPage(self, data):
        doubles = self.doubles
        puas = self.puas
        pageNum = self.pageNum

        chars = []
        prevChar = None
        prevFont = None
        prevSize = None

        def addChar():
            box = tuple(int(round(x * 10)) for x in prevChar["bbox"])
            c = prevChar["c"]
            uc = ord(c)
            un = uName(c)
            chars.append(
                (
                    *box,
                    prevFont,
                    prevSize,
                    f"{uc:>04x}",
                    "PRIVATE" if uc in puas else un,
                    c,
                )
            )

        def collectChars(data, font, size):
            nonlocal prevChar
            nonlocal prevFont
            nonlocal prevSize

            if type(data) is list:
                for elem in data:
                    collectChars(elem, font, size)

            elif type(data) is dict:
                if "font" in data:
                    font = data["font"]
                if "size" in data:
                    size = data["size"]
                if "c" in data:
                    c = data["c"]
                    uc = ord(c)
                    skip = False
                    if c == " ":
                        skip = True

                    if prevChar is not None:
                        pc = prevChar["c"]
                        puc = ord(pc)
                        if puc in doubles and doubles[puc] == uc:
                            skip = True
                        if uc in doubles and doubles[uc] == puc:
                            prevChar = data
                            skip = True

                    if not skip:
                        if prevChar is not None:
                            addChar()
                        prevChar = data
                        prevFont = font
                        prevSize = size

                for (k, v) in data.items():
                    if type(v) in {list, dict}:
                        collectChars(v, font, size)

        collectChars(data, None, None)
        if prevChar is not None:
            addChar()

        clusterKeyCharV = clusterVert(chars)
        lines = {}
        for char in sorted(chars, key=lambda c: (clusterKeyCharV(c), -keyCharH(c))):
            k = clusterKeyCharV(char)
            lines.setdefault(k, []).append(char)

        self.lines[pageNum] = tuple(lines.values())
        self.text[pageNum] = tuple(self.trimLine(line) for line in lines.values())

    def trimLine(self, chars):
        replace = self.replace
        puas = self.puas
        nospacings = self.nospacings
        neutrals = self.neutrals
        rls = self.rls

        stageOne = []

        for char in chars:
            char = list(char)
            c = char[-1]
            uc = ord(c)

            if stageOne:
                prevChar = stageOne[-1]
                pc = prevChar[-1]
                if len(pc) == 1:
                    puc = ord(prevChar[-1])
                    if puc in replace:
                        repls = replace[puc]
                        if uc in repls:
                            ucs = repls[uc]
                            if len(ucs) == 0:
                                stageOne[-1][-1] = ""
                                char[-1] = ""
                                stageOne.append(char)
                                continue

                            (puc, *ucs) = ucs
                            stageOne[-1][-1] = chr(puc)
                            char[-1] = "".join(chr(u) for u in ucs)
                            stageOne.append(char)
                            continue

            if uc in replace:
                repls = replace[uc]
                if None in repls:
                    repls = repls[None]
                    if len(repls) == 0:
                        char[-1] = ""
                        stageOne.append(char)
                        continue

                    char[-1] = "".join(chr(u) for u in repls)
                    stageOne.append(char)
                    continue

            stageOne.append(char)

        stageTwo = []
        prevLeft = None
        prevDir = "r"
        chars = []

        def addChars():
            if chars:
                charsRep = "".join(chars if prevDir == "r" else reversed(chars))
                stageTwo.append((prevDir, charsRep))

        for char in stageOne:
            left = int(round(char[0]))
            right = int(round(char[2]))

            if prevLeft is not None:
                if prevLeft - right >= 25:
                    chars.append(" ")

            c = char[-1]
            if c == "":
                prevLeft = left
                continue

            uc = ord(c[-1])

            if uc not in nospacings:
                prevLeft = left

            thisDir = prevDir if uc in neutrals else "r" if uc in rls else "l"

            if prevDir != thisDir:
                addChars()
                chars = []
                prevDir = thisDir

            rep = c
            for d in c:
                ud = ord(d)
                if ud in puas:
                    rep = f"""⌊{ud:>04x}⌋"""
            chars.append(rep)

        addChars()

        return stageTwo

    def plainLine(self, spans):
        return "".join("".join(span[1]) for span in spans)

    def htmlLine(self, spans):
        result = []

        for (textDir, string) in spans:
            rep = string.replace("⌊", """<span class="p">""").replace("⌋", "</span>")
            result.append(f"""<span class="{textDir}">{rep}</span>""")

        return "".join(result)


def keyCharV(char):
    return int(round((char[3] + char[1]) / 2))


def keyCharH(char):
    return char[2]


def clusterVert(data):
    keys = collections.Counter()
    for char in data:
        k = keyCharV(char)
        keys[k] += 1

    peaks = sorted(keys)
    if len(peaks) > 1:
        nDistances = len(peaks) - 1
        avPeakDist = int(
            round(sum(peaks[i + 1] - peaks[i] for i in range(nDistances)) / nDistances)
        )

        peakThreshold = int(round(avPeakDist / 3))
        clusteredPeaks = {}
        for (k, n) in sorted(keys.items(), key=lambda x: (-x[1], x[0])):
            added = False
            for kc in clusteredPeaks:
                if abs(k - kc) <= peakThreshold:
                    clusteredPeaks[kc].add(k)
                    added = True
                    break
            if not added:
                clusteredPeaks[k] = {k}
    toCluster = {}
    for (kc, ks) in clusteredPeaks.items():
        for k in ks:
            toCluster[k] = kc

    def clusterKeyCharV(char):
        k = keyCharV(char)
        return toCluster[k]

    if False:
        print("PEAKS")
        for k in peaks:
            print(f"{k:>4} : {keys[k]:>4}")
        print("CLUSTERED_PEAKS")
        for kc in sorted(clusteredPeaks):
            peak = ", ".join(f"{k:>4}" for k in sorted(clusteredPeaks[kc]))
            print(f"{peak} : {sum(keys[k] for k in clusteredPeaks[kc]):>4}")

    return clusterKeyCharV
