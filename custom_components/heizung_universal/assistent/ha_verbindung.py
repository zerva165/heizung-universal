"""Minimale Home-Assistant-Anbindung (nur Python-Standardbibliothek).

WebSocket-API (Helfer, Blueprints, Dashboards, Entitätsregister) und REST-API (Automationen),
dieselben Schnittstellen, die auch die Home-Assistant-Oberfläche verwendet.
"""
import base64
import json
import os
import socket
import ssl
import struct
import urllib.error
import urllib.parse
import urllib.request


class HAFehler(Exception):
    pass


class HAVerbindung:
    def __init__(self, url, token, timeout=30, ssl_pruefen=True):
        self.ssl_pruefen = ssl_pruefen  # False nur für die Verbindung der Integration zu ihrem eigenen Home Assistant (127.0.0.1)
        self.url = url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self._sock = None
        self._id = 0

    # ------------------------------------------------------------- WebSocket
    def verbinden(self):
        u = urllib.parse.urlparse(self.url)
        sicher = u.scheme == "https"
        port = u.port or (443 if sicher else 80)
        roh = socket.create_connection((u.hostname, port), timeout=self.timeout)
        self._sock = self._kontext().wrap_socket(roh, server_hostname=u.hostname) if sicher else roh
        key = base64.b64encode(os.urandom(16)).decode()
        anfrage = (f"GET /api/websocket HTTP/1.1\r\nHost: {u.hostname}:{port}\r\nUpgrade: websocket\r\n"
                   f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        self._sock.sendall(anfrage.encode())
        kopf = b""
        while b"\r\n\r\n" not in kopf:
            teil = self._sock.recv(1)
            if not teil:
                raise HAFehler("Verbindung beim Handshake geschlossen")
            kopf += teil
        if b" 101 " not in kopf.split(b"\r\n", 1)[0]:
            raise HAFehler("WebSocket-Handshake abgelehnt: " + kopf.split(b"\r\n", 1)[0].decode(errors="replace"))
        msg = self._empfangen()
        if msg.get("type") != "auth_required":
            raise HAFehler(f"Unerwartete Begrüßung: {msg}")
        self._senden({"type": "auth", "access_token": self.token})
        msg = self._empfangen()
        if msg.get("type") != "auth_ok":
            raise HAFehler("Anmeldung fehlgeschlagen – Token prüfen.")
        return msg.get("ha_version")

    def _kontext(self):
        k = ssl.create_default_context()
        if not self.ssl_pruefen:
            k.check_hostname = False
            k.verify_mode = ssl.CERT_NONE
        return k

    def schliessen(self):
        if self._sock:
            try:
                self._sock.close()
            finally:
                self._sock = None

    def _senden(self, obj):
        daten = json.dumps(obj).encode()
        kopf = bytearray([0x81])
        n = len(daten)
        if n < 126:
            kopf.append(0x80 | n)
        elif n < 65536:
            kopf.append(0x80 | 126)
            kopf += struct.pack("!H", n)
        else:
            kopf.append(0x80 | 127)
            kopf += struct.pack("!Q", n)
        maske = os.urandom(4)
        kopf += maske
        self._sock.sendall(bytes(kopf) + bytes(b ^ maske[i % 4] for i, b in enumerate(daten)))

    def _lesen(self, n):
        puffer = b""
        while len(puffer) < n:
            teil = self._sock.recv(n - len(puffer))
            if not teil:
                raise HAFehler("Verbindung unterbrochen")
            puffer += teil
        return puffer

    def _empfangen(self):
        nutzlast = b""
        while True:
            b1, b2 = self._lesen(2)
            fin, opcode = b1 & 0x80, b1 & 0x0F
            n = b2 & 0x7F
            if n == 126:
                n = struct.unpack("!H", self._lesen(2))[0]
            elif n == 127:
                n = struct.unpack("!Q", self._lesen(8))[0]
            maske = self._lesen(4) if b2 & 0x80 else None
            teil = self._lesen(n)
            if maske:
                teil = bytes(b ^ maske[i % 4] for i, b in enumerate(teil))
            if opcode == 0x9:  # ping -> pong
                self._sock.sendall(bytes([0x8A, 0x80]) + os.urandom(4))
                continue
            if opcode == 0x8:
                raise HAFehler("Server hat die Verbindung geschlossen")
            nutzlast += teil
            if fin:
                return json.loads(nutzlast.decode())

    def befehl(self, typ, **daten):
        self._id += 1
        mid = self._id
        self._senden({"id": mid, "type": typ, **daten})
        while True:
            msg = self._empfangen()
            if msg.get("id") == mid and msg.get("type") == "result":
                if not msg.get("success"):
                    raise HAFehler(f"{typ}: {msg.get('error', {}).get('message', msg)}")
                return msg.get("result")

    # ------------------------------------------------------------- REST
    def rest(self, methode, pfad, daten=None):
        req = urllib.request.Request(self.url + pfad, method=methode,
                                     data=None if daten is None else json.dumps(daten).encode(),
                                     headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=self._kontext() if self.url.startswith("https") else None) as r:
                inhalt = r.read().decode()
                return json.loads(inhalt) if inhalt else None
        except urllib.error.HTTPError as e:
            raise HAFehler(f"REST {methode} {pfad}: {e.code} {e.read().decode(errors='replace')[:300]}")
