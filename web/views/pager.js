/**
 * Seitenleiste für lange Listen (ISSUES P2 · Umfangreiche Wallets).
 *
 * `(1–10)` `(11–20)` … `(241–247)` — der letzte Bereich endet exakt am
 * letzten Eintrag, bei vielen Seiten mit „…“ dazwischen. Dazu die Auswahl
 * 10/20/50/100; die Größe merkt sich jede Ansicht in localStorage.
 *
 * Nachladen: Eine Seitenquelle holt beim Server doppelt so viele Einträge,
 * wie eine Seite zeigt („20 aufbauen, 10 zeigen“), und lädt den nächsten
 * Block im Hintergrund vor, während die aktuelle Seite aus dem Speicher
 * gezeichnet wird. Kein Baum steckt darin — nur Listen-Meta.
 */

const PAGER_GROESSEN = [10, 20, 50, 100];
const PAGER_SPEICHER = "satsage.seitengroesse.";
/** Hochgezählt bei Sprachwechsel / fertigem Scan: alle Seitenquellen leeren. */
let _pagerGeneration = 0;

function pagerGroesse(ansicht) {
  let n = 0;
  try {
    n = Number(localStorage.getItem(PAGER_SPEICHER + ansicht));
  } catch (_) { /* privat / gesperrt */ }
  return PAGER_GROESSEN.includes(n) ? n : PAGER_GROESSEN[0];
}

function setzePagerGroesse(ansicht, n) {
  if (!PAGER_GROESSEN.includes(Number(n))) return;
  try {
    localStorage.setItem(PAGER_SPEICHER + ansicht, String(n));
  } catch (_) { /* ignorieren */ }
}

function pagerCachesVerwerfen() {
  _pagerGeneration += 1;
}

/**
 * Bereiche für die Knöpfe: erste, letzte und die Nachbarn der aktuellen
 * Seite; Lücken werden zu "…".
 */
function pagerBereiche(total, groesse, offset) {
  const n = Math.max(0, Number(total) || 0);
  const g = Math.max(1, Number(groesse) || PAGER_GROESSEN[0]);
  const seiten = Math.ceil(n / g);
  const aktuell = Math.min(Math.max(0, Math.floor((Number(offset) || 0) / g)), Math.max(0, seiten - 1));
  const zeigen = new Set([0, seiten - 1]);
  for (let i = aktuell - 2; i <= aktuell + 2; i += 1) {
    if (i >= 0 && i < seiten) zeigen.add(i);
  }
  const liste = [];
  let vorige = -1;
  for (let i = 0; i < seiten; i += 1) {
    if (!zeigen.has(i)) continue;
    if (vorige >= 0 && i - vorige > 1) liste.push("…");
    liste.push({
      von: i * g + 1,
      bis: Math.min(n, (i + 1) * g),
      offset: i * g,
      aktiv: i === aktuell,
    });
    vorige = i;
  }
  return liste;
}

/**
 * Leiste unter einer Liste. Unsichtbar, solange alles auf die kleinste
 * Seitengröße passt.
 */
function zeichnePager({ total, offset, groesse, ansicht, onSeite, onGroesse }) {
  const leiste = document.createElement("div");
  leiste.className = "pager";
  leiste.dataset.ansicht = ansicht || "";
  const n = Number(total) || 0;
  leiste.hidden = n <= PAGER_GROESSEN[0];

  const knoepfe = document.createElement("span");
  knoepfe.className = "pager-seiten";
  for (const bereich of pagerBereiche(n, groesse, offset)) {
    if (bereich === "…") {
      const luecke = document.createElement("span");
      luecke.className = "pager-luecke zart";
      luecke.textContent = "…";
      knoepfe.append(luecke);
      continue;
    }
    const knopf = document.createElement("button");
    knopf.type = "button";
    knopf.className = "knopf knopf-klein pager-seite";
    knopf.textContent = `(${bereich.von}–${bereich.bis})`;
    knopf.title = t("pager.pageTitle", { von: bereich.von, bis: bereich.bis, total: n });
    if (bereich.aktiv) {
      knopf.classList.add("aktiv");
      knopf.setAttribute("aria-current", "page");
    }
    knopf.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (!bereich.aktiv && typeof onSeite === "function") onSeite(bereich.offset);
    });
    knoepfe.append(knopf);
  }

  const wahl = document.createElement("label");
  wahl.className = "pager-groesse feld-inline";
  const text = document.createElement("span");
  text.textContent = t("pager.perPage");
  const sel = document.createElement("select");
  sel.className = "knopf knopf-klein";
  sel.setAttribute("aria-label", t("pager.perPage"));
  for (const g of PAGER_GROESSEN) {
    const opt = document.createElement("option");
    opt.value = String(g);
    opt.textContent = String(g);
    sel.append(opt);
  }
  sel.value = String(groesse);
  sel.addEventListener("change", (e) => {
    e.stopPropagation();
    const neu = Number(sel.value);
    setzePagerGroesse(ansicht, neu);
    if (typeof onGroesse === "function") onGroesse(neu);
  });
  wahl.append(text, sel);
  leiste.append(knoepfe, wahl);
  return leiste;
}

/**
 * Seitenquelle: *laden(offset, limit)* fragt den Server, *auszug(antwort)*
 * liefert `{ items, total }`. Gehalten werden höchstens drei Blöcke.
 * *vorab*: Antwort, die den ersten Block (ab 0, doppelte Seitengröße) schon
 * enthält — etwa aus der ersten Gesamtanfrage.
 */
function neueSeitenQuelle({ laden, auszug, groesse, vorab = null }) {
  const g = Math.max(1, Number(groesse) || PAGER_GROESSEN[0]);
  const bloecke = new Map();
  let generation = _pagerGeneration;
  if (vorab) {
    bloecke.set(0, Promise.resolve({ start: 0, antwort: vorab, ...auszug(vorab) }));
  }

  const block = (start) => {
    if (!bloecke.has(start)) {
      const p = Promise.resolve(laden(start, 2 * g)).then((antwort) => ({
        start, antwort, ...auszug(antwort),
      }));
      // Fehlgeschlagen: beim nächsten Versuch neu fragen.
      p.catch(() => bloecke.delete(start));
      bloecke.set(start, p);
      while (bloecke.size > 3) bloecke.delete(bloecke.keys().next().value);
    }
    return bloecke.get(start);
  };

  return {
    groesse: g,
    async seite(offset) {
      if (generation !== _pagerGeneration) {
        bloecke.clear();
        generation = _pagerGeneration;
      }
      const o = Math.max(0, Number(offset) || 0);
      const start = bloecke.has(o - g) ? o - g : o;
      const b = await block(start);
      const items = b.items.slice(o - b.start, o - b.start + g);
      // Nächste Seite vorladen, falls der Block sie nicht schon enthält.
      const naechste = o + g;
      if (naechste < b.total && naechste >= b.start + 2 * g) {
        block(naechste).catch(() => {});
      } else if (naechste + g < b.total && !bloecke.has(naechste + g)) {
        block(naechste + g).catch(() => {});
      }
      return { antwort: b.antwort, items, total: b.total, art: b.art, offset: o };
    },
  };
}

window.addEventListener("satsage:lang", () => pagerCachesVerwerfen());
