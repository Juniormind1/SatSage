"""
Kernschicht: liefert Daten statt Text.

Die Module hier geben Python-Objekte zurück und drucken nichts. Fortschritt
langlaufender Vorgänge läuft über Callbacks, nicht über stdout. Damit lassen
sie sich sowohl vom CLI als auch vom Web-Server (server.py) benutzen.

Regel für dieses Paket: **kein print()**. Wer Text ausgeben will, tut das in
der aufrufenden Schicht.
"""
