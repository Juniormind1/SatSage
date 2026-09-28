"""Start-Log: eine Zeile je Wallet, sofort im Strom, nicht erst am Ende."""
from __future__ import annotations

import json
import threading
import time
import urllib.request

from tests.fixtures import BIP84_ZPUB
from tests.test_api import ApiTestBasis


class TestBootLog(ApiTestBasis):

    def test_zeile_kommt_bevor_das_naechste_wallet_fertig_ist(self):
        """Der Strom liefert die Ankündigung, während die Ableitung noch hängt."""
        tor = threading.Barrier(2)
        original = self.state._build_context

        def haengt(entries, **kwargs):
            tor.wait(timeout=5)
            return original(entries)

        self.state._build_context = haengt
        self.state.reload(hintergrund=True)

        url = f"http://127.0.0.1:{self.port}/api/boot-log"
        req = urllib.request.Request(url)
        req.add_header("X-Satsage-Token", self.state.token)
        req.add_header("Accept", "application/x-ndjson")
        with urllib.request.urlopen(req, timeout=15) as antwort:
            zeile = antwort.readline()
            self.assertTrue(zeile, "erste Zeile fehlt, bevor die Ableitung weiterläuft")
            obj = json.loads(zeile)
            self.assertIn("Wallet", obj["log"])
            # Die Ableitung hängt noch — die Zeile kam also nicht erst am Ende.
            self.assertFalse(self.state.context_bereit())
            tor.wait(timeout=5)
            rest = antwort.read().decode()
        self.assertIn("Wallets bereit.", rest)
        self.assertTrue(self.state.context_bereit())

    def test_jobs_tragen_die_zeilen_solange_die_vorbereitung_laeuft(self):
        self.state.boot_log.zeile("Bereite 1 Wallet vor…")
        self.state.boot_log.zeile("Leite Adressen ab…", wallet="Cold Storage")
        self.state._context_bereit.clear()
        _, koerper = self.anfrage("/api/jobs?recent_s=3")
        job = next(j for j in koerper["jobs"] if j["kind"] == "wallet_context")
        self.assertEqual(job["log"][1], "Leite Adressen ab…")
        self.assertEqual(job["log_wallets"][1], "Cold Storage")
        self.state._context_bereit.set()

    def test_config_wartet_nicht_auf_cache_waehrend_vorbereitung(self):
        self.state._context_bereit.clear()
        _, koerper = self.anfrage("/api/config")
        self.assertFalse(koerper["context_bereit"])
        self.assertGreaterEqual(len(koerper["wallets"]), 1)
        self.assertIn("name", koerper["wallets"][0])
        self.state._context_bereit.set()

    def test_cache_gelesen_traegt_den_wallet_stand(self):
        self.state.reload(hintergrund=True)
        self.assertTrue(self.state.warte_auf_context(timeout=10))
        zeilen, fertig = self.state.boot_log.stand()
        self.assertTrue(fertig)
        staende = [
            z["extra"]["wallet"] for z in zeilen
            if z.get("text") == "Cache gelesen." and (z.get("extra") or {}).get("wallet")
        ]
        self.assertGreaterEqual(len(staende), 1)
        self.assertIn("id", staende[0])
        self.assertIn("name", staende[0])

    def test_ableitung_meldet_jedes_wallet(self):
        gesehen = []
        self.state._build_context(
            [e for e in self.state.entries if e.analyse_schluessel == BIP84_ZPUB],
            on_log=lambda text, wallet="": gesehen.append((wallet, text)),
        )
        self.assertTrue(any(name and text.startswith("Leite") for name, text in gesehen))
        self.assertTrue(any(text.startswith("Adressen abgeleitet") for _name, text in gesehen))
        self.assertLess(
            [t for _n, t in gesehen].index("Leite Adressen ab…"),
            [t for _n, t in gesehen].index("Adressen abgeleitet."),
        )
