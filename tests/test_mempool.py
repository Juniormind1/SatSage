"""
Verweise auf eine eigene mempool.space-Instanz.

Zwei Zusicherungen. Erstens: Ohne eingetragene Instanz entstehen **keine**
Verweise — ein Standardwert auf mempool.space würde jedem Klick verraten,
welche Adresse den Benutzer interessiert. Zweitens: Eine fremde Instanz wird
als solche gekennzeichnet, damit die Entscheidung bewusst fällt.
"""
import unittest

from core.config import mempool_info, normalize_mempool_url


class TestAdressPruefung(unittest.TestCase):

    def test_schraegstrich_am_ende_faellt_weg(self):
        self.assertEqual(
            normalize_mempool_url("https://mempool.lan/"), "https://mempool.lan"
        )

    def test_fehlendes_schema_wird_ergaenzt(self):
        self.assertEqual(
            normalize_mempool_url("mempool.lan"), "https://mempool.lan"
        )

    def test_http_bleibt_erhalten(self):
        """Im LAN läuft oft nur http — das darf nicht stillschweigend kippen."""
        self.assertEqual(
            normalize_mempool_url("http://192.168.0.9:8080"),
            "http://192.168.0.9:8080",
        )

    def test_pfad_bleibt_erhalten(self):
        self.assertEqual(
            normalize_mempool_url("https://example.org/mempool"),
            "https://example.org/mempool",
        )

    def test_leere_eingabe_loescht(self):
        self.assertEqual(normalize_mempool_url(""), "")
        self.assertEqual(normalize_mempool_url("   "), "")

    def test_fremdes_schema_wird_abgelehnt(self):
        for eingabe in ("ftp://mempool.lan", "javascript:alert(1)",
                        "file:///etc/passwd"):
            with self.assertRaises(ValueError, msg=eingabe):
                normalize_mempool_url(eingabe)

    def test_parameter_werden_abgelehnt(self):
        """Sonst ließe sich beliebiges an die zusammengebaute URL hängen."""
        with self.assertRaises(ValueError):
            normalize_mempool_url("https://mempool.lan/?x=1")
        with self.assertRaises(ValueError):
            normalize_mempool_url("https://mempool.lan/#frag")

    def test_adresse_ohne_host(self):
        with self.assertRaises(ValueError):
            normalize_mempool_url("https://")


class TestOhneInstanz(unittest.TestCase):
    """Der entscheidende Zustand: kein Verweis, keine stille Voreinstellung."""

    def test_nicht_konfiguriert(self):
        info = mempool_info("")
        self.assertFalse(info["configured"])
        self.assertEqual(info["url"], "")

    def test_kein_rueckfall_auf_mempool_space(self):
        info = mempool_info("")
        self.assertNotIn("mempool.space", info["url"])
        self.assertNotIn("mempool.space", info.get("host", ""))

    def test_hinweis_erklaert_die_folge(self):
        self.assertIn("verraten", mempool_info("")["hinweis"])

    def test_unbrauchbare_eingabe_gilt_als_nicht_konfiguriert(self):
        """Lieber kein Verweis als ein kaputter."""
        self.assertFalse(mempool_info("javascript:alert(1)")["configured"])


class TestEigeneInstanz(unittest.TestCase):

    def test_lan_adresse(self):
        info = mempool_info("http://192.168.0.9:8080")
        self.assertTrue(info["configured"])
        self.assertTrue(info["local"])

    def test_onion_adresse(self):
        self.assertTrue(mempool_info("http://abc123.onion")["local"])

    def test_localhost(self):
        self.assertTrue(mempool_info("http://localhost:8999")["local"])
        self.assertTrue(mempool_info("http://127.0.0.1:8999")["local"])

    def test_hostname_ohne_punkt_gilt_als_lokal(self):
        self.assertTrue(mempool_info("http://nodebox:3006")["local"])

    def test_weitere_private_bereiche(self):
        self.assertTrue(mempool_info("http://10.0.0.5")["local"])
        self.assertTrue(mempool_info("http://172.16.3.4")["local"])
        self.assertTrue(mempool_info("http://mempool.home")["local"])

    def test_hinweis_bei_eigener_instanz(self):
        hinweis = mempool_info("http://mempool.lan")["hinweis"]
        self.assertIn("deinem Netz", hinweis)
        self.assertNotIn("verrät", hinweis)

    def test_umbrel_ueber_mdns(self):
        """Typischer Umbrel-Zugriff im Heimnetz, http auf eigenem Port."""
        info = mempool_info("http://umbrel.hostname.local:3006")
        self.assertTrue(info["local"])
        self.assertEqual(info["stufe"], "lokal")
        self.assertEqual(info["url"], "http://umbrel.hostname.local:3006")

    def test_tailscale_hostname(self):
        """
        Tailscale-Adressen sehen wie öffentliche Domains aus, sind aber nur im
        eigenen Tailnet erreichbar.
        """
        info = mempool_info("http://umbrel.tail1a2b3c.ts.net:3006")
        self.assertTrue(info["local"])
        self.assertEqual(info["stufe"], "lokal")

    def test_tailscale_adressbereich(self):
        """Tailscale vergibt IPs aus 100.64.0.0/10."""
        self.assertTrue(mempool_info("http://100.101.102.103:3006")["local"])
        self.assertFalse(mempool_info("http://100.200.1.1")["local"])

    def test_sprachpfad_bleibt_erhalten(self):
        """mempool.space kennt Sprachpräfixe wie /de — die gehören in die URL."""
        self.assertEqual(
            normalize_mempool_url("http://umbrel.local:3006/de/"),
            "http://umbrel.local:3006/de",
        )

    def test_privates_netz_mit_eigenem_port(self):
        info = mempool_info("http://172.16.1.2:9000")
        self.assertTrue(info["local"])
        self.assertEqual(info["url"], "http://172.16.1.2:9000")

    def test_ipv6_loopback_und_ula(self):
        self.assertTrue(mempool_info("http://[::1]:3006")["local"])
        self.assertTrue(mempool_info("http://[fd00::1]:3006")["local"])


class TestFremdeInstanz(unittest.TestCase):

    def test_oeffentliche_domain_ist_nicht_lokal(self):
        info = mempool_info("https://mempool.space")
        self.assertTrue(info["configured"])
        self.assertFalse(info["local"])
        self.assertEqual(info["stufe"], "fremd")

    def test_eigene_domain_wird_nicht_als_fremd_behauptet(self):
        """
        Ein selbst gehosteter mempool hinter eigener Domain sieht öffentlich
        aus und ist es doch nicht. Das Programm kann das nicht wissen — also
        soll es keine Feststellung treffen, sondern nur den Hinweis geben.
        """
        info = mempool_info("https://mempool.meinedomain.de")
        self.assertEqual(info["stufe"], "oeffentlich")
        self.assertIn("eigene Instanz", info["hinweis"])

    def test_bekannter_dienst_auch_als_subdomain(self):
        self.assertEqual(
            mempool_info("https://liquid.blockstream.info")["stufe"], "fremd"
        )

    def test_172_ausserhalb_des_privaten_bereichs(self):
        """172.32.x liegt nicht mehr in 172.16.0.0/12."""
        self.assertFalse(mempool_info("http://172.32.0.1")["local"])

    def test_hinweis_benennt_das_leck(self):
        info = mempool_info("https://mempool.space")
        self.assertIn("verrät", info["hinweis"])
        self.assertIn("Transaktion oder Adresse", info["hinweis"])

    def test_host_wird_genannt(self):
        self.assertEqual(mempool_info("https://mempool.space")["host"],
                         "mempool.space")


if __name__ == "__main__":
    unittest.main()
