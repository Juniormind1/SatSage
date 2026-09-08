"""
Hinweise zu Verbindungsfehlern (Befund 2 aus dem Linux-Testlauf).

Ein Protokoll-Mismatch sieht in der Ausgabe sonst aus wie ein reines
Erreichbarkeitsproblem — und das Programm fällt still auf die nächste,
schlechtere Datenquelle zurück.
"""
import unittest

import main


class TestSslHinweise(unittest.TestCase):

    def test_wrong_version_number_weist_auf_fulcrum_ssl(self):
        fehler = "[SSL: WRONG_VERSION_NUMBER] wrong version number (_ssl.c:1000)"
        hinweis = main.connection_error_hint(fehler, use_ssl=True)
        self.assertIsNotNone(hinweis)
        self.assertIn("FULCRUM_SSL=false", hinweis)

    def test_derselbe_fehler_ohne_ssl_ergibt_keinen_ssl_hinweis(self):
        """Ohne aktiviertes TLS wäre der Rat, TLS abzuschalten, unsinnig."""
        fehler = "[SSL: WRONG_VERSION_NUMBER] wrong version number"
        self.assertIsNone(main.connection_error_hint(fehler, use_ssl=False))

    def test_abbruch_ohne_tls_weist_auf_aktivierung(self):
        hinweis = main.connection_error_hint("unexpected EOF", use_ssl=False)
        self.assertIsNotNone(hinweis)
        self.assertIn("FULCRUM_SSL=true", hinweis)

    def test_selbstsigniertes_zertifikat(self):
        fehler = "certificate verify failed: self signed certificate"
        hinweis = main.connection_error_hint(fehler, use_ssl=True)
        self.assertIsNotNone(hinweis)
        self.assertIn("SATSAGE_TLS_INSECURE=1", hinweis)

    def test_geschlossener_port(self):
        hinweis = main.connection_error_hint("[Errno 111] Connection refused", True)
        self.assertIsNotNone(hinweis)
        self.assertIn("FULCRUM_PORT", hinweis)


class TestKeinHinweis(unittest.TestCase):

    def test_ohne_fehler(self):
        self.assertIsNone(main.connection_error_hint(None, use_ssl=True))
        self.assertIsNone(main.connection_error_hint("", use_ssl=True))

    def test_unbekannter_fehler_erfindet_nichts(self):
        """Lieber kein Hinweis als ein irreführender."""
        self.assertIsNone(
            main.connection_error_hint("timed out after 8s", use_ssl=True)
        )


if __name__ == "__main__":
    unittest.main()
