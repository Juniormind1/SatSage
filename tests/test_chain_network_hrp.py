"""
Adress-Netz (HRP) im Trace-Pfad und im xpub_cache — zur Laufzeit gelesen.

Regression: Fulcrum/Electrs liefern Txs als Roh-Hex, ``_parse_tx_hex``
kodierte die Output-Adressen mit ``script.address()`` immer als Mainnet
(``bc1…``). Auf regtest/testnet/signet sind die eigenen Adressen aber
``bcrt1…``/``tb1…`` — jeder Vorgänger galt als extern, der Herkunftsbaum
endete nach einer Ebene. ``core.xpub_cache`` importierte ``_CHAIN_NETWORK``
als Wert und sah ``set_chain_network()`` nie (Header-Cache-Tag blieb „main“).
"""
import json
import tempfile
import unittest
from pathlib import Path

from embit import script
from embit.bip32 import HDKey
from embit.networks import NETWORKS
from embit.script import Script
from embit.transaction import Transaction, TransactionInput, TransactionOutput

import main
from core import derivation, xpub_cache
from core.fulcrum_history import _parse_tx_hex, fetch_tx_fulcrum
from core.trace import trace_utxo

#: (NETWORK-Wert aus .env, embit-Netz, erwarteter Präfix, Header-Tag)
NETZE = (
    ("regtest", NETWORKS["regtest"], "bcrt1", "regtest"),
    ("testnet", NETWORKS["test"], "tb1", "test"),
    ("signet", NETWORKS["signet"], "tb1", "signet"),
    ("main", None, "bc1", "main"),
)

_HD = HDKey.from_seed(b"\x42" * 32)


def _spk(index: int) -> Script:
    return script.p2wpkh(_HD.derive([0, index]).key)


def _tx(prev_txid_hex: str, prev_vout: int, out_spk: Script, sats: int) -> Transaction:
    return Transaction(
        vin=[TransactionInput(bytes.fromhex(prev_txid_hex), prev_vout)],
        vout=[TransactionOutput(sats, out_spk)],
    )


class _RohClient:
    """Fulcrum/Electrs ohne verbose: nur Roh-Hex je TxID."""

    host = "test"
    server_software = "electrs-test"

    def __init__(self, raw_by_txid: dict[str, str]):
        self._raw = raw_by_txid

    def request(self, method: str, params: list | None = None):
        if method != "blockchain.transaction.get":
            raise AssertionError(f"unerwartete Methode: {method}")
        return self._raw[params[0]]


class _NetzTest(unittest.TestCase):
    def tearDown(self):
        main.set_chain_network(None)


class TestParseTxHexKodiertImNetz(_NetzTest):
    def test_output_adresse_folgt_dem_netz(self):
        spk = _spk(0)
        roh = _tx("11" * 32, 0, spk, 50_000).serialize().hex()
        for name, net, praefix, _tag in NETZE:
            with self.subTest(netz=name):
                main.set_chain_network(name)
                adresse = _parse_tx_hex(roh)["vout"][0]["scriptPubKey"]["address"]
                self.assertTrue(adresse.startswith(praefix), adresse)
                erwartet = spk.address() if net is None else spk.address(net)
                self.assertEqual(adresse, erwartet)

    def test_mainnet_unveraendert_wie_embit_default(self):
        spk = _spk(1)
        roh = _tx("22" * 32, 1, spk, 1_000).serialize().hex()
        main.set_chain_network(None)
        self.assertEqual(
            _parse_tx_hex(roh)["vout"][0]["scriptPubKey"]["address"],
            spk.address(),
        )

    def test_nicht_kodierbares_script_ohne_adresse(self):
        roh = _tx("33" * 32, 0, Script(b"\x6a\x01\x00"), 0).serialize().hex()
        main.set_chain_network("regtest")
        self.assertNotIn("address", _parse_tx_hex(roh)["vout"][0]["scriptPubKey"])


class TestTraceMehrereEbenen(_NetzTest):
    """
    Extern → eigen A → eigen B → eigen C (Ziel), alle Txs nur als Roh-Hex.

    Erwartet: zwei interne Ebenen, Anschaffung = Zeit des externen Zuflusses.
    Vor dem Fix: Vorgänger B als ``bc1…`` → extern, Tiefe 1, Datum von B.
    """

    def _kette(self):
        extern = _tx("aa" * 32, 0, script.p2wpkh(HDKey.from_seed(b"\x07" * 32).key), 1_000_000)
        t_in = _tx(extern.txid().hex(), 0, _spk(0), 900_000)
        hop1 = _tx(t_in.txid().hex(), 0, _spk(1), 800_000)
        hop2 = _tx(hop1.txid().hex(), 0, _spk(2), 700_000)
        zeiten = {}
        raw = {}
        for i, t in enumerate((extern, t_in, hop1, hop2)):
            raw[t.txid().hex()] = t.serialize().hex()
            zeiten[t.txid().hex()] = (100 + i, 1_690_000_000 + i * 86_400 * 100)
        return raw, zeiten, extern, t_in, hop1, hop2

    def _get_tx(self, raw, zeiten):
        client = _RohClient(raw)

        def get_tx(tid: str) -> dict:
            tx = fetch_tx_fulcrum(client, tid, enrich_block_info=False)
            hoehe, zeit = zeiten[tid]
            tx.update(
                blockheight=hoehe, blocktime=zeit, confirmations=10,
                status={"confirmed": True, "block_height": hoehe, "block_time": zeit},
            )
            return tx

        return get_tx

    def test_trace_folgt_eigenen_vorgaengern_in_jedem_netz(self):
        raw, zeiten, extern, t_in, _hop1, hop2 = self._kette()
        for name, _net, praefix, _tag in NETZE:
            with self.subTest(netz=name):
                main.set_chain_network(name)
                eigene = {derivation.script_address(_spk(i)) for i in range(3)}
                self.assertTrue(all(a.startswith(praefix) for a in eigene), eigene)
                ergebnis = trace_utxo(
                    self._get_tx(raw, zeiten), hop2.txid().hex(), 0, eigene,
                )
                self.assertTrue(ergebnis["found"], ergebnis.get("error"))
                self.assertTrue(ergebnis["root"]["address"].startswith(praefix))
                summary = ergebnis["summary"]
                self.assertGreaterEqual(summary["max_depth"], 3, summary)
                self.assertEqual(summary["external_count"], 1, summary)
                self.assertGreater(summary["internal_sats"], 0, summary)
                # Blatt: externer Zufluss in t_in, Zeit = Entstehung des externen Outputs.
                knoten = ergebnis["children"]
                tiefe = 0
                while knoten and knoten[0].get("type") != "external":
                    self.assertTrue(knoten[0]["address"].startswith(praefix))
                    knoten = knoten[0].get("children") or []
                    tiefe += 1
                self.assertEqual(tiefe, 2, ergebnis["children"])
                blatt = knoten[0]
                self.assertEqual(blatt["from_utxo"], f"{extern.txid().hex()}:0")
                self.assertEqual(blatt["time_ts"], zeiten[extern.txid().hex()][1])


class TestXpubCacheNetzZurLaufzeit(_NetzTest):
    def test_kein_wert_import_des_netzes(self):
        # Ein Modul-Attribut _CHAIN_NETWORK wäre die eingefrorene Kopie.
        self.assertFalse(hasattr(xpub_cache, "_CHAIN_NETWORK"))

    def test_header_tag_folgt_set_chain_network(self):
        for name, _net, _praefix, tag in NETZE:
            with self.subTest(netz=name):
                main.set_chain_network(name)
                self.assertEqual(xpub_cache._block_header_network_tag(), tag)
                with tempfile.TemporaryDirectory() as tmp:
                    pfad = xpub_cache._block_header_cache_path(130, Path(tmp))
                    self.assertEqual(pfad.name, f"{tag}-130.json")

    def test_regtest_liest_keinen_mainnet_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            main.set_chain_network(None)
            xpub_cache.save_cached_block_time(130, 1_600_000_000, root, "test")
            self.assertEqual(xpub_cache.load_cached_block_time(130, root), 1_600_000_000)
            main.set_chain_network("regtest")
            self.assertIsNone(xpub_cache.load_cached_block_time(130, root))
            xpub_cache.save_cached_block_time(130, 1_700_000_000, root, "test")
            self.assertEqual(xpub_cache.load_cached_block_time(130, root), 1_700_000_000)
            self.assertTrue((root / xpub_cache.BLOCK_HEADER_CACHE_SUBDIR / "regtest-130.json").is_file())
            main.set_chain_network(None)
            self.assertEqual(xpub_cache.load_cached_block_time(130, root), 1_600_000_000)


class TestTxCacheAltlastMitMainnetHrp(_NetzTest):
    """Vor dem Fix geschriebene Flatfiles tragen ``bc1…`` auch auf regtest."""

    def _schreibe(self, root: Path, spk: Script) -> str:
        roh = _tx("44" * 32, 0, spk, 10_000)
        tid = roh.txid().hex()
        main.set_chain_network(None)
        tx = _parse_tx_hex(roh.serialize().hex())  # Mainnet-HRP wie früher
        tx.update(blockheight=5, blocktime=1_700_000_000, confirmations=3,
                  status={"confirmed": True, "block_height": 5, "block_time": 1_700_000_000})
        pfad = xpub_cache._immutable_tx_cache_path(tid, root)
        pfad.parent.mkdir(parents=True, exist_ok=True)
        pfad.write_text(json.dumps({"txid": tid, "source": "fulcrum", "tx": tx}), encoding="utf-8")
        with xpub_cache._immutable_tx_lock:
            xpub_cache._immutable_tx_memory.pop(tid, None)
        return tid

    def test_laden_kodiert_im_aktiven_netz(self):
        spk = _spk(3)
        for name, net, praefix, _tag in NETZE:
            with self.subTest(netz=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                tid = self._schreibe(root, spk)
                main.set_chain_network(name)
                tx = xpub_cache.load_cached_tx(tid, root)
                with xpub_cache._immutable_tx_lock:
                    xpub_cache._immutable_tx_memory.pop(tid, None)
                adresse = tx["vout"][0]["scriptPubKey"]["address"]
                self.assertTrue(adresse.startswith(praefix), adresse)
                self.assertEqual(adresse, spk.address() if net is None else spk.address(net))


class TestWeitereKodierstellen(_NetzTest):
    """Alle übrigen Script→Adresse-Stellen nutzen dasselbe Netz."""

    def test_bip158_bitcoind_wallets(self):
        from core import bip158_scan, bip158_wallet, bitcoind_rpc, wallets

        spk = _spk(4)
        tx = _tx("55" * 32, 0, spk, 20_000)
        xpub = _HD.to_public().to_base58(version=NETWORKS["main"]["xpub"])
        for name, net, praefix, _tag in NETZE:
            with self.subTest(netz=name):
                main.set_chain_network(name)
                erwartet = spk.address() if net is None else spk.address(net)
                self.assertEqual(
                    bip158_wallet._embit_tx_to_dict(tx)["vout"][0]["scriptPubKey"]["address"],
                    erwartet,
                )
                self.assertEqual(
                    bitcoind_rpc._embit_tx_to_analyze_dict(tx)["vout"][0]["scriptPubKey"]["address"],
                    erwartet,
                )
                self.assertEqual(bip158_scan._ausgaben_ziele(tx)[0]["addresses"], [erwartet])
                utxo = bitcoind_rpc._unspent_to_utxo({
                    "txid": "66" * 32, "vout": 0, "amount": 0.0002,
                    "scriptPubKey": spk.data.hex(),
                })
                self.assertEqual(utxo["address"], erwartet)
                adressen = wallets._receive_addresses(xpub, "segwit", 2)
                self.assertTrue(adressen and all(a.startswith(praefix) for a in adressen), adressen)
                spks = bip158_wallet.derive_script_pubkeys_from_xpub(xpub, max_index=2, include_change=False)
                for roh, adresse in spks.items():
                    sc = Script(roh)
                    self.assertEqual(adresse, sc.address() if net is None else sc.address(net))
                segwit = [a for roh, a in spks.items() if roh[:2] == b"\x00\x14"]
                self.assertTrue(segwit and all(a.startswith(praefix) for a in segwit), segwit)


if __name__ == "__main__":
    unittest.main()
