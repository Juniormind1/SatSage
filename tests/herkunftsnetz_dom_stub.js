// Minimaler DOM-Ersatz für tests/test_herkunftsnetz_js.py (kein jsdom im Projekt).
const CSS = { escape: (wert) => String(wert).replace(/[^a-zA-Z0-9_-]/g, "\\$&") };
class El {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.children = []; this.parent = null; this.className = "";
    this.dataset = {}; this.style = {}; this.attrs = {}; this.hidden = false;
    this._text = ""; this.handlers = {};
    const el = this;
    this.classList = {
      _l() { return el.className.split(/\s+/).filter(Boolean); },
      contains(c) { return this._l().includes(c); },
      add(...cs) { const l = this._l(); for (const c of cs) if (!l.includes(c)) l.push(c); el.className = l.join(" "); },
      remove(...cs) { el.className = this._l().filter((c) => !cs.includes(c)).join(" "); },
      toggle(c, an) { const soll = an === undefined ? !this.contains(c) : Boolean(an); if (soll) this.add(c); else this.remove(c); return soll; },
    };
  }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(""); }
  setAttribute(k, v) { this.attrs[k] = String(v); if (k === "class") this.className = String(v); }
  getAttribute(k) { return k === "class" ? this.className : (this.attrs[k] ?? null); }
  removeAttribute(k) { delete this.attrs[k]; }
  append(...kinder) { for (const k of kinder) { if (k.parent) k.remove(); k.parent = this; this.children.push(k); } }
  replaceChildren(...kinder) { for (const k of this.children) k.parent = null; this.children = []; this.append(...kinder); }
  remove() { if (this.parent) { this.parent.children = this.parent.children.filter((c) => c !== this); this.parent = null; } }
  addEventListener(typ, fn) { (this.handlers[typ] ||= []).push(fn); }
  fire(typ, ev = {}) {
    const e = { target: this, preventDefault() {}, stopPropagation() { this.gestoppt = true; }, ...ev };
    let el = this;
    while (el && !e.gestoppt) { for (const fn of el.handlers[typ] || []) fn(e); el = el.parent; }
    return e;
  }
  matches(sel) { return sel.split(",").some((s) => passt(this, s.trim())); }
  closest(sel) { let el = this; while (el) { if (el.matches && el.matches(sel)) return el; el = el.parent; } return null; }
  querySelectorAll(sel) {
    const aus = [];
    const lauf = (el) => { for (const k of el.children) { if (k.matches(sel)) aus.push(k); lauf(k); } };
    lauf(this); return aus;
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}
function passt(el, s) {
  let rest = s;
  const nicht = [];
  rest = rest.replace(/:not\(\.([\w-]+)\)/g, (_, c) => { nicht.push(c); return ""; });
  const attr = [];
  const attrGleich = [];
  rest = rest.replace(/\[data-([\w-]+)="([^"]*)"\]/g, (_, a, v) => {
    attrGleich.push([a, v.replace(/\\(.)/g, "$1")]);
    return "";
  });
  rest = rest.replace(/\[data-([\w-]+)\]/g, (_, a) => { attr.push(a); return ""; });
  const klassen = (rest.match(/\.([\w-]+)/g) || []).map((c) => c.slice(1));
  if (!klassen.every((c) => el.classList.contains(c))) return false;
  if (nicht.some((c) => el.classList.contains(c))) return false;
  const camel = (a) => a.replace(/-(\w)/g, (_, b) => b.toUpperCase());
  if (!attr.every((a) => el.dataset[camel(a)] !== undefined)) return false;
  return attrGleich.every(([a, v]) => String(el.dataset[camel(a)] ?? "") === v);
}
const ids = {};
const document = {
  handlers: {},
  createElement: (t) => new El(t),
  createElementNS: (_ns, t) => new El(t),
  querySelector: (sel) => ids[sel.replace(/^#/, "")] || null,
  addEventListener(typ, fn) { (this.handlers[typ] ||= []).push(fn); },
  fire(typ, ev) { for (const fn of this.handlers[typ] || []) fn(ev); },
};
function mitId(id, el) { ids[id] = el; el.id = id; return el; }
