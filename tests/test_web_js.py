"""
Statische Prüfung der Oberflächen-Dateien.

Anlass: Eine doppelte `const`-Deklaration im selben Gültigkeitsbereich hat die
gesamte app.js unparsebar gemacht — die Web-Oberfläche zeigte nur noch eine
leere Seite. Die Python-Testsuite war grün, weil sie über JavaScript nichts
weiß.

Das Projekt hat bewusst keine JS-Werkzeugkette (kein npm, kein Bundler). Diese
Datei ersetzt keinen Linter, fängt aber die Fehlerklassen ab, die die ganze
Oberfläche lahmlegen und beim Lesen leicht übersehen werden.
"""
import re
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"


def ohne_texte_und_kommentare(quelle: str) -> str:
    """
    Ersetzt Zeichenketten- und Kommentarinhalte durch Leerzeichen.

    Zeilenumbrüche bleiben erhalten, damit Zeilennummern stimmen. Innerhalb
    von Vorlagenliteralen bleibt der Code in ``${…}`` stehen — dort stehen
    echte Ausdrücke, die mitgeprüft werden sollen.
    """
    ergebnis = []
    i = 0
    laenge = len(quelle)
    template_tiefe = []  # offene ${ innerhalb von Vorlagenliteralen

    while i < laenge:
        zeichen = quelle[i]
        folge = quelle[i:i + 2]

        if folge == "//":
            while i < laenge and quelle[i] != "\n":
                ergebnis.append(" ")
                i += 1
            continue
        if folge == "/*":
            while i < laenge and quelle[i:i + 2] != "*/":
                ergebnis.append("\n" if quelle[i] == "\n" else " ")
                i += 1
            ergebnis.append("  ")
            i += 2
            continue
        if zeichen in ("'", '"'):
            ende = zeichen
            ergebnis.append(" ")
            i += 1
            while i < laenge and quelle[i] != ende:
                if quelle[i] == "\\":
                    ergebnis.append(" ")
                    i += 1
                ergebnis.append("\n" if quelle[i] == "\n" else " ")
                i += 1
            ergebnis.append(" ")
            i += 1
            continue
        if zeichen == "`":
            ergebnis.append(" ")
            i += 1
            while i < laenge:
                if quelle[i] == "\\":
                    ergebnis.append("  ")
                    i += 2
                    continue
                if quelle[i] == "`":
                    break
                if quelle[i:i + 2] == "${":
                    # Ausdruck übernehmen — er zählt für die Klammerbilanz.
                    ergebnis.append("  ")
                    i += 2
                    tiefe = 1
                    while i < laenge and tiefe:
                        if quelle[i] == "{":
                            tiefe += 1
                        elif quelle[i] == "}":
                            tiefe -= 1
                            if tiefe == 0:
                                ergebnis.append(" ")
                                i += 1
                                break
                        ergebnis.append(quelle[i])
                        i += 1
                    continue
                ergebnis.append("\n" if quelle[i] == "\n" else " ")
                i += 1
            ergebnis.append(" ")
            i += 1
            continue

        ergebnis.append(zeichen)
        i += 1

    return "".join(ergebnis)


_DEKLARATION = re.compile(r"\b(?:const|let)\s+(\[[^\]]*\]|\{[^}]*\}|[A-Za-z_$][\w$]*)")
_NAME = re.compile(r"[A-Za-z_$][\w$]*")


def _namen(rohteil: str) -> list[str]:
    """Namen einer Deklaration — auch bei Destrukturierung."""
    if rohteil.startswith(("[", "{")):
        # Bei { a: b } zählt der zweite Name; Standardwerte werden ignoriert.
        inhalt = rohteil[1:-1]
        namen = []
        for stueck in inhalt.split(","):
            stueck = stueck.split("=")[0]
            treffer = _NAME.findall(stueck)
            if treffer:
                namen.append(treffer[-1])
        return namen
    return [rohteil]


def doppelte_deklarationen(quelle: str) -> list[tuple[int, str]]:
    """
    Findet `const`/`let`, die im selben Block zweimal denselben Namen anlegen.

    Genau dieser Fehler macht die Datei unparsebar, und zwar vollständig — die
    Oberfläche zeigt dann gar nichts mehr.

    ``for (const x of …) { … }`` bindet *x* an die Schleife, nicht an die
    umgebende Funktion — zwei solche Schleifen mit gleichem Namen sind legal.
    """
    sauber = ohne_texte_und_kommentare(quelle)
    stapel = [set()]
    funde = []
    zeile = 1
    for_header: set[str] | None = None
    for_paren = 0

    i = 0
    while i < len(sauber):
        zeichen = sauber[i]
        if zeichen == "\n":
            zeile += 1
        elif for_header is not None and for_paren > 0:
            if zeichen == "(":
                for_paren += 1
            elif zeichen == ")":
                for_paren -= 1
            else:
                treffer = _DEKLARATION.match(sauber, i)
                if treffer:
                    for name in _namen(treffer.group(1).strip()):
                        if name in for_header:
                            funde.append((zeile, name))
                        for_header.add(name)
                    i = treffer.end()
                    zeile += sauber.count("\n", treffer.start(), treffer.end())
                    continue
        elif zeichen == "{":
            neu: set[str] = set()
            if for_header is not None:
                neu.update(for_header)
                for_header = None
            stapel.append(neu)
        elif zeichen == "}":
            if len(stapel) > 1:
                stapel.pop()
        elif zeichen == ";" and for_header is not None and for_paren == 0:
            for_header = None
        else:
            if (
                sauber.startswith("for", i)
                and (i == 0 or not (sauber[i - 1].isalnum() or sauber[i - 1] in "_$"))
            ):
                j = i + 3
                while j < len(sauber) and sauber[j] in " \t\n\r":
                    if sauber[j] == "\n":
                        zeile += 1
                    j += 1
                if j < len(sauber) and sauber[j] == "(":
                    for_header = set()
                    for_paren = 1
                    i = j + 1
                    continue
            treffer = _DEKLARATION.match(sauber, i)
            if treffer:
                for name in _namen(treffer.group(1).strip()):
                    if name in stapel[-1]:
                        funde.append((zeile, name))
                    stapel[-1].add(name)
                i = treffer.end()
                zeile += sauber.count("\n", treffer.start(), treffer.end())
                continue
        i += 1

    return funde


class TestAppJs(unittest.TestCase):

    def setUp(self):
        self.quelle = (WEB / "app.js").read_text(encoding="utf-8")

    def test_keine_doppelten_deklarationen(self):
        """
        Der Fehler, der die Oberfläche schon einmal komplett lahmgelegt hat:
        zweimal `const text` in derselben Funktion.
        """
        funde = doppelte_deklarationen(self.quelle)
        self.assertEqual(
            funde, [],
            "Doppelte Deklaration(en) — die Datei ist dann nicht parsebar: "
            + ", ".join(f"Zeile {z}: {n}" for z, n in funde),
        )

    def test_klammern_sind_ausgeglichen(self):
        sauber = ohne_texte_und_kommentare(self.quelle)
        for auf, zu, name in (("{", "}", "geschweift"), ("(", ")", "rund"),
                              ("[", "]", "eckig")):
            self.assertEqual(
                sauber.count(auf), sauber.count(zu),
                f"{name}e Klammern unausgeglichen",
            )

    def test_verwendete_element_kennungen_gibt_es_im_html(self):
        """
        `$("#tippfehler")` liefert null und wirft beim ersten Zugriff — auch
        das legt die Ansicht lahm, nur später und schwerer auffindbar.
        """
        html = (WEB / "index.html").read_text(encoding="utf-8")
        vorhanden = set(re.findall(r'id="([^"]+)"', html))
        benutzt = set(re.findall(r'\$\("#([A-Za-z0-9_-]+)"\)', self.quelle))
        fehlend = sorted(benutzt - vorhanden)
        self.assertEqual(fehlend, [], f"Nicht im HTML: {fehlend}")

    def test_keine_verwaisten_ansichten(self):
        """Jede Ansicht in ANSICHTEN braucht ihren Abschnitt im HTML."""
        html = (WEB / "index.html").read_text(encoding="utf-8")
        treffer = re.search(r"const ANSICHTEN = \[([^\]]+)\]", self.quelle)
        self.assertIsNotNone(treffer)
        for name in re.findall(r'"([^"]+)"', treffer.group(1)):
            self.assertIn(f'id="ansicht-{name}"', html, f"Ansicht {name} fehlt")


class TestPrueferSelbst(unittest.TestCase):
    """Der Prüfer muss den Fehler finden — und darf nicht überall Alarm schlagen."""

    def test_findet_doppelte_deklaration(self):
        quelle = """
        function f() {
          const [a, text] = g();
          const text = h();
        }
        """
        self.assertTrue(doppelte_deklarationen(quelle))

    def test_for_of_bindungen_sind_pro_schleife_erlaubt(self):
        quelle = """
        function f() {
          for (const w of a) { use(w); }
          for (const w of b) { use(w); }
        }
        """
        self.assertEqual(doppelte_deklarationen(quelle), [])

    def test_gleicher_name_in_getrennten_bloecken_ist_erlaubt(self):
        quelle = """
        function f() { const x = 1; }
        function g() { const x = 2; }
        """
        self.assertEqual(doppelte_deklarationen(quelle), [])

    def test_gleicher_name_in_verschachteltem_block_ist_erlaubt(self):
        quelle = """
        function f() {
          const x = 1;
          if (x) { const x = 2; }
        }
        """
        self.assertEqual(doppelte_deklarationen(quelle), [])

    def test_namen_in_zeichenketten_zaehlen_nicht(self):
        quelle = 'function f() { const x = 1; const y = "const x = 2"; }'
        self.assertEqual(doppelte_deklarationen(quelle), [])

    def test_namen_in_kommentaren_zaehlen_nicht(self):
        quelle = "function f() { const x = 1; /* const x = 2 */ }"
        self.assertEqual(doppelte_deklarationen(quelle), [])

    def test_vorlagenliteral_stoert_die_klammerbilanz_nicht(self):
        quelle = 'const a = `Text ${ {b: 1}.b } mehr`; const c = 2;'
        sauber = ohne_texte_und_kommentare(quelle)
        self.assertEqual(sauber.count("{"), sauber.count("}"))
        self.assertEqual(doppelte_deklarationen(quelle), [])


if __name__ == "__main__":
    unittest.main()
