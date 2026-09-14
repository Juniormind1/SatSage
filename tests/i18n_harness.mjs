// Harness fuer tests/test_web_i18n.py: laedt web/i18n.js in Node mit
// minimalen Browser-Stubs und gibt die von initI18n gewaehlte Sprache aus.
//
//   node tests/i18n_harness.mjs web/i18n.js <gespeichert|-> <config|-> <browser>
import fs from "node:fs";

const [, , quelle, gespeichert, configLang, navLang] = process.argv;

const store = new Map();
if (gespeichert && gespeichert !== "-") store.set("satsage-ui-lang", gespeichert);

globalThis.localStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, v),
  removeItem: (k) => store.delete(k),
};
Object.defineProperty(globalThis, "navigator", {
  value: { language: navLang, languages: [navLang] },
  configurable: true,
});
globalThis.document = {
  documentElement: { setAttribute() {}, lang: "" },
  querySelectorAll: () => [],
};
globalThis.fetch = async () => ({ ok: true, json: async () => ({}) });
globalThis.window = globalThis;
globalThis.dispatchEvent = () => true;
globalThis.CustomEvent = class { constructor(t, o) { this.type = t; Object.assign(this, o); } };

eval(fs.readFileSync(quelle, "utf8"));

const opts = configLang && configLang !== "-" ? { configLang } : {};
await window.SatSageI18n.initI18n(opts);
console.log(window.SatSageI18n.currentLang());
