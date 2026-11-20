"""Nachgebauter Home-Assistant-Server (WebSocket + REST) für Tests des Einrichtungsassistenten.
Speichert alles im Arbeitsspeicher und protokolliert jede Anfrage nach tests/_mock_protokoll.json."""
import base64
import hashlib
import json
import socket
import struct
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "assistent"))
from raumassistent import slug  # noqa: E402

TOKEN = "test-token"
SNAP = json.loads((Path(__file__).parent / "assistent" / "bestand_snapshot.json").read_text(encoding="utf-8"))
ZUSTAND = {"states": list(SNAP["states"]), "registry": list(SNAP["registry"]), "helfer": {}, "automationen": {}, "blueprints": {},
           "lovelace": {"dashboard-test": {"views": [{"title": "Heizung", "path": "heizung", "sections": [
               {"type": "grid", "cards": [{"type": "heading", "heading": "Räume"}, {"type": "markdown", "content": "Bestehende Karte"}]}]}]}},
           "protokoll": []}


def ws_frame(text):
    d = text.encode()
    k = bytearray([0x81])
    k += bytes([len(d)]) if len(d) < 126 else (bytes([126]) + struct.pack("!H", len(d)) if len(d) < 65536 else bytes([127]) + struct.pack("!Q", len(d)))
    return bytes(k) + d


def ws_lesen(c):
    def r(n):
        b = b""
        while len(b) < n:
            t = c.recv(n - len(b))
            if not t:
                raise ConnectionError
            b += t
        return b
    b1, b2 = r(2)
    n = b2 & 0x7F
    if n == 126:
        n = struct.unpack("!H", r(2))[0]
    elif n == 127:
        n = struct.unpack("!Q", r(8))[0]
    m = r(4)
    return json.loads(bytes(x ^ m[i % 4] for i, x in enumerate(r(n))).decode())


def befehl(msg):
    t = msg["type"]
    ZUSTAND["protokoll"].append({k: v for k, v in msg.items() if k not in ("yaml",)})
    if t == "get_states":
        return ZUSTAND["states"]
    if t == "config/entity_registry/list":
        return ZUSTAND["registry"]
    if t == "search/related":
        return {"automation": ["automation.buero_heizprofil_alt"]} if msg["item_id"] == "climate.buero_bt" else {}
    if t == "blueprint/list":
        return {p: {"metadata": {}} for p in ZUSTAND["blueprints"]}
    if t == "blueprint/save":
        if msg["path"] in ZUSTAND["blueprints"] and not msg.get("allow_override"):
            raise ValueError("exists")
        assert "blueprint:" in msg["yaml"]
        ZUSTAND["blueprints"][msg["path"]] = len(msg["yaml"])
        return {}
    if t == "blueprint/delete":
        ZUSTAND["blueprints"].pop(msg["path"])
        return {}
    dom = t.split("/")[0]
    if t.endswith("/create"):
        hid = slug(msg["name"])
        eid = f"{dom}.{hid}"
        if any(s["entity_id"] == eid for s in ZUSTAND["states"]):
            hid += "_2"
            eid = f"{dom}.{hid}"
        ZUSTAND["helfer"][eid] = msg
        ZUSTAND["states"].append({"entity_id": eid, "state": "unknown", "attributes": {"friendly_name": msg["name"]}})
        return {"id": hid, **{k: v for k, v in msg.items() if k not in ("id", "type")}}
    if t.endswith("/delete"):
        eid = f"{dom}.{msg[dom + '_id']}"
        ZUSTAND["helfer"].pop(eid)
        ZUSTAND["states"] = [s for s in ZUSTAND["states"] if s["entity_id"] != eid]
        return None
    if t == "call_service":
        return {}
    if t == "lovelace/dashboards/list":
        return [{"url_path": u, "title": u, "mode": "storage"} for u in ZUSTAND["lovelace"]]
    if t == "lovelace/config":
        return json.loads(json.dumps(ZUSTAND["lovelace"][msg["url_path"]]))
    if t == "lovelace/config/save":
        ZUSTAND["lovelace"][msg["url_path"]] = msg["config"]
        return None
    raise ValueError("unbekannt: " + t)


def http(c, kopf, rumpf):
    zeile = kopf.split("\r\n")[0]
    meth, pfad, _ = zeile.split(" ")
    if "Bearer " + TOKEN not in kopf:
        c.sendall(b"HTTP/1.1 401 Unauthorized\r\nContent-Length: 0\r\n\r\n")
        return
    aid = pfad.rsplit("/", 1)[-1]
    if meth == "POST":
        cfg = json.loads(rumpf)
        assert cfg["use_blueprint"]["path"] in ZUSTAND["blueprints"], "Blueprint fehlt"
        ZUSTAND["automationen"][aid] = cfg
        eid = "automation." + slug(cfg["alias"])
        if not any(r.get("unique_id") == aid for r in ZUSTAND["registry"]):
            ZUSTAND["registry"].append({"entity_id": eid, "platform": "automation", "unique_id": aid})
            ZUSTAND["states"].append({"entity_id": eid, "state": "on", "attributes": {"friendly_name": cfg["alias"]}})
    elif meth == "DELETE":
        ZUSTAND["automationen"].pop(aid)
        ZUSTAND["registry"] = [r for r in ZUSTAND["registry"] if r.get("unique_id") != aid]
    ZUSTAND["protokoll"].append({"rest": meth, "pfad": pfad})
    body = b'{"result":"ok"}'
    c.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)


def verbindung(c):
    daten = b""
    while b"\r\n\r\n" not in daten:
        daten += c.recv(4096)
    kopf, _, rest = daten.partition(b"\r\n\r\n")
    kopf = kopf.decode()
    if "Upgrade: websocket" in kopf:
        key = next(z.split(": ", 1)[1] for z in kopf.split("\r\n") if z.lower().startswith("sec-websocket-key"))
        acc = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
        c.sendall(f"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: {acc}\r\n\r\n".encode())
        c.sendall(ws_frame(json.dumps({"type": "auth_required", "ha_version": "2026.11.0-mock"})))
        auth = ws_lesen(c)
        if auth.get("access_token") != TOKEN:
            c.sendall(ws_frame(json.dumps({"type": "auth_invalid"})))
            return
        c.sendall(ws_frame(json.dumps({"type": "auth_ok", "ha_version": "2026.11.0-mock"})))
        try:
            while True:
                msg = ws_lesen(c)
                try:
                    antwort = {"id": msg["id"], "type": "result", "success": True, "result": befehl(msg)}
                except Exception as e:  # noqa: BLE001
                    antwort = {"id": msg["id"], "type": "result", "success": False, "error": {"message": str(e)}}
                c.sendall(ws_frame(json.dumps(antwort)))
        except ConnectionError:
            pass
    else:
        laenge = int(next((z.split(": ", 1)[1] for z in kopf.split("\r\n") if z.lower().startswith("content-length")), "0"))
        while len(rest) < laenge:
            rest += c.recv(4096)
        http(c, kopf, rest.decode())
    c.close()


def starten(port=18123):
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", port))
    s.listen(5)

    def schleife():
        while True:
            c, _ = s.accept()
            threading.Thread(target=verbindung, args=(c,), daemon=True).start()
    threading.Thread(target=schleife, daemon=True).start()
    return s


if __name__ == "__main__":
    starten()
    print("Mock-HA läuft auf http://127.0.0.1:18123 – Strg+C beendet.")
    threading.Event().wait()
