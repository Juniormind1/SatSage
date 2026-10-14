"""Ka-Ching je neuem UTXO, walletweise und walletübergreifend."""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

from tests.test_wallet_mempool_js import _funktion

WALLETS = (
    Path(__file__).resolve().parent.parent / "web" / "views" / "wallets.js"
).read_text(encoding="utf-8")

_STUB = r"""
const Zustand = { walletId: "offen", scanKaChing: [], scanFundKeys: null };
let pending = null;
const gespielt = [];
const EmpfangPuls = {
  flashIncoming(walletId, sats, opts) {
    gespielt.push({ walletId, sats, halte: Boolean(opts && opts.halteDanach) });
    pending = opts && opts.onDone;
  },
};
function naechster() {
  const cb = pending;
  pending = null;
  if (cb) cb();
}
"""

_FUNKTIONEN = [
    "function merkeScanFundJob(",
    "function spieleScanFunde(",
    "function pumpeScanKaChing(",
]


def _node(skript: str) -> dict:
    teile = [_STUB] + [_funktion(WALLETS, kopf) for kopf in _FUNKTIONEN]
    code = (
        "\n".join(teile)
        + "\n(() => {\n"
        + skript
        + "\n})();"
    )
    aus = subprocess.run(
        ["node", "-e", code], capture_output=True, text=True, timeout=30,
    )
    if aus.returncode != 0:
        raise AssertionError(aus.stderr[-2000:] or aus.stdout[-2000:])
    return json.loads(aus.stdout)


@unittest.skipUnless(shutil.which("node"), "node fehlt")
class TestScanKaChing(unittest.TestCase):
    def test_jeder_utxo_nacheinander_auch_fremdes_wallet(self):
        erg = _node(r"""
          const job = {
            id: "scan-1",
            result: { entdeckt: [
              { key: "aa:0", value_sats: 10, wallet_id: "anderes" },
              { key: "bb:1", value_sats: 20, wallet_id: "offen" },
              { key: "cc:0", value_sats: 30, wallet_id: "drittes" },
            ] },
          };
          spieleScanFunde(job);
          const nachErstem = gespielt.length;
          naechster();
          naechster();
          const nachAllen = gespielt.map((e) => e.sats);
          const halten = gespielt.map((e) => e.halte);
          spieleScanFunde(job);
          const nachWiederholung = gespielt.length;
          spieleScanFunde({
            id: "scan-2",
            result: { entdeckt: [{ key: "aa:0", value_sats: 10, wallet_id: "anderes" }] },
          });
          naechster();
          console.log(JSON.stringify({
            nachErstem, nachAllen, halten, nachWiederholung,
            zweiterJob: gespielt.length,
          }));
        """)
        self.assertEqual(erg["nachErstem"], 1)
        self.assertEqual(erg["nachAllen"], [10, 20, 30])
        self.assertEqual(erg["halten"], [True, True, False])
        self.assertEqual(erg["nachWiederholung"], 3)
        self.assertEqual(erg["zweiterJob"], 4)
