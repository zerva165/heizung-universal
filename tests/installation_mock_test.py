"""Prüft das Installationsskript gegen den nachgebauten HA-Server: es darf ausschließlich die drei Blueprints speichern."""
import os, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import mock_ha
BASIS = Path(__file__).resolve().parent.parent
mock_ha.starten()
Z = mock_ha.ZUSTAND
env = dict(os.environ, HA_URL="http://127.0.0.1:18123", HA_TOKEN="test-token")
pruef = []
def ok(bed, text):
    pruef.append(bool(bed)); print(("  ✔ " if bed else "  ✘ ") + text)
def lauf(*args, eingabe=""):
    return subprocess.run([sys.executable, "-I", str(BASIS / "tools" / "blueprints_installieren.py"), *args], input=eingabe, text=True,
                          capture_output=True, env=env, timeout=60)
def typen(ab=0):
    return [p.get("type") for p in Z["protokoll"][ab:]]
ZIEL = {"ha_heizung_universal/" + n for n in ("universelle_raumheizungssteuerung.yaml", "klimaautomatik.yaml", "pv_ueberschussheizen.yaml")}
vorher = {k: (len(v) if hasattr(v, "__len__") else v) for k, v in Z.items() if k not in ("protokoll", "blueprints")}

r = lauf()
ok(r.returncode == 0 and not Z["blueprints"] and set(typen()) <= {"blueprint/list"}, "Ohne --installieren: nur gelesen, nichts geschrieben")
n = len(Z["protokoll"])
r = lauf("--installieren", eingabe="nein\n")
ok(r.returncode == 1 and not Z["blueprints"], "Ohne die Eingabe JA: nichts geschrieben")
n = len(Z["protokoll"])
r = lauf("--installieren", eingabe="JA\n")
ok(r.returncode == 0 and set(Z["blueprints"]) == ZIEL, "Mit JA: genau die drei Blueprints unter ha_heizung_universal/ gespeichert")
ok(sorted(typen(n)) == ["blueprint/list", "blueprint/list", "blueprint/save", "blueprint/save", "blueprint/save"],
   "Verwendete Befehle: nur blueprint/list und 3 × blueprint/save")
groessen = {p: (BASIS / "blueprints/automation" / p).read_text(encoding="utf-8") for p in ZIEL}
ok(all(Z["blueprints"][p] == len(groessen[p]) for p in ZIEL), "Dateiinhalt vollständig übertragen (Länge identisch)")
r = lauf("--installieren", eingabe="JA\n")
ok(r.returncode == 1 and "bereits installiert" in r.stdout, "Zweiter Lauf ohne --ueberschreiben: verweigert")
r = lauf("--installieren", "--ueberschreiben", eingabe="JA\n")
ok(r.returncode == 0 and set(Z["blueprints"]) == ZIEL, "Mit --ueberschreiben: ersetzt, weiterhin genau drei")
nachher = {k: (len(v) if hasattr(v, "__len__") else v) for k, v in Z.items() if k not in ("protokoll", "blueprints")}
ok(vorher == nachher and not Z.get("automationen") and not Z.get("helfer"), "Keine Automation, kein Helfer, kein Dashboard verändert")
ok(not any(t.endswith("/create") or t in ("call_service", "lovelace/config/save") for t in typen()), "Kein Anlege-, Dienst- oder Dashboard-Befehl gesendet")
r = lauf("--entfernen", eingabe="JA\n")
ok(r.returncode == 0 and not Z["blueprints"], "--entfernen: genau diese drei Dateien wieder gelöscht")
env["HA_TOKEN"] = "falsch"
r = lauf("--installieren", eingabe="JA\n")
ok(r.returncode == 2, "Falsches Token: Abbruch ohne Schreiben")
print(f"Ergebnis: {sum(pruef)}/{len(pruef)} Prüfungen bestanden")
sys.exit(0 if all(pruef) else 1)
