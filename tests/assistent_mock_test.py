"""Ende-zu-Ende-Test des Einrichtungsassistenten gegen den nachgebauten HA-Server (schreibt nichts in das echte HA)."""
import json, os, subprocess, sys, shutil
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import mock_ha
BASIS = Path(__file__).resolve().parent.parent
srv = mock_ha.starten()
env = dict(os.environ, HA_URL="http://127.0.0.1:18123", HA_TOKEN="test-token")
aus = BASIS / "tests" / "assistent" / "mock_ausgabe"
shutil.rmtree(aus, ignore_errors=True)
pruef = []
def ok(bed, text):
    pruef.append((bool(bed), text)); print(("  ✔ " if bed else "  ✘ ") + text)
def lauf(antwortdatei, extra):
    a = json.load(open(antwortdatei)); a.update(extra); a.pop("bt_fremd", None)
    f = aus / ("antw_" + Path(antwortdatei).name); f.parent.mkdir(parents=True, exist_ok=True); f.write_text(json.dumps(a, ensure_ascii=False))
    r = subprocess.run([sys.executable, "-I", str(BASIS / "assistent" / "raumassistent.py"), "--antworten", str(f), "--ausgabe", str(aus)],
                       input="JA\n", text=True, capture_output=True, env=env, timeout=120)
    print(r.stdout[-1500:]); print(r.stderr[-1500:])
    return r
Z = mock_ha.ZUSTAND
print("\n### Lauf 1: Büro (Better Thermostat wird bereits verwendet → Testbetrieb), Karte in Abschnitt 1 an Position 2")
r = lauf(BASIS / "tests/assistent/antworten_buero.json", {"karte_einfuegen": "j", "dashboard": "dashboard-test", "ansicht": "0", "abschnitt": "0", "position": 2})
ok(r.returncode == 0, "Assistent ohne Fehler beendet")
ok(len(Z["blueprints"]) == 1, "nur Blueprint 1 installiert (kein Klima/PV im Büro)")
ok(len(Z["helfer"]) == 9, f"9 Helfer angelegt ({len(Z['helfer'])})")
auto = Z["automationen"].get("hz_buero_raumheizung")
ok(auto and auto["use_blueprint"]["input"]["ausgabe_modus"] == "test", "Automation im Testbetrieb angelegt (Doppelschreiber verhindert)")
bi = auto["use_blueprint"]["input"]
ok(bi.get("vorheizen_aktiv") is True and bi.get("komfort_wt1_vh") is True and bi.get("komfort_wt1_vh_temp") == 21 and bi.get("komfort_wt1_vh_bis") == "06:00:00"
   and "komfort_wt2_vh" not in bi and "uebergang_wt1_vh" not in bi and bi.get("komfort_sa1_aktiv") is True and bi.get("komfort_wt3_aktiv") is False, "Vorheizen nur für Komfort Phase 1 (mind. 21 °C bis 06:00), übrige Phasen ohne")
karten = Z["lovelace"]["dashboard-test"]["views"][0]["sections"][0]["cards"]
ok(len(karten) == 3 and karten[1]["type"] == "custom:mod-card", "Karte an Position 2 eingefügt, bestehende Karten erhalten")
ok(any(p.get("type") == "call_service" and p["service"] == "select_option" for p in Z["protokoll"]), "Startwert Heizprofil gesetzt")
rb = aus / "buero" / "rueckbau.json"
ok(rb.exists() and len(json.loads(rb.read_text())["helfer"]) == 9, "Rückbau-Datei vollständig")
print("\n### Lauf 2: Testraum mit Klima und PV (produktiv)")
r = lauf(BASIS / "tests/assistent/antworten_klima_pv.json", {"karte_einfuegen": "j", "dashboard": "dashboard-test", "ansicht": "0", "abschnitt": "neu", "bp_ueberschreiben_raumheizung": "n"})
ok(r.returncode == 0, "Assistent ohne Fehler beendet")
ok(len(Z["blueprints"]) == 3, "alle drei Blueprints installiert")
kl = Z["automationen"]["hz_testraum_klima"]["use_blueprint"]["input"]; pv = Z["automationen"]["hz_testraum_pv"]["use_blueprint"]["input"]
ok(kl["pv_automation"] == "automation.pv_heizen_testraum_klima_pv", "Klimaautomatik mit PV-Automation verknüpft")
ok(pv["raumheizung_automation"] == "automation.heizung_testraum_klima_pv" and pv["klima_automation"] == "automation.klima_testraum_klima_pv", "PV kennt Raumheizung und Klima")
ok(kl["ausgabe_modus"] == "produktiv", "kein Fremdzugriff → Normalbetrieb")
ri = Z["automationen"]["hz_testraum_raumheizung"]["use_blueprint"]["input"]
ok("vorheizen_aktiv" not in ri and not any("vorheiz" in e for e in Z["helfer"] if "testraum" in e), "ohne Vorheizen: Funktion aus, keine Vorheiz-Helfer angelegt")
ok(len(Z["lovelace"]["dashboard-test"]["views"][0]["sections"]) == 2, "Karte in neuem Abschnitt")
print("\n### Rückbau Lauf 1")
r = subprocess.run([sys.executable, "-I", str(BASIS / "assistent" / "raumassistent.py"), "--rueckbau", str(rb)], input="JA\n", text=True, capture_output=True, env=env, timeout=60)
print(r.stdout[-800:]); print(r.stderr[-800:])
ok("hz_buero_raumheizung" not in Z["automationen"], "Büro-Automation entfernt")
ok(not any(e.startswith(("input_select.hz_buro", "timer.hz_buro", "input_text.hz_buro", "input_number.hz_buro", "input_boolean.hz_buro")) for e in Z["helfer"]), "Büro-Helfer entfernt")
ok(len(Z["lovelace"]["dashboard-test"]["views"][0]["sections"][0]["cards"]) == 2, "Dashboard aus Sicherung wiederhergestellt")
ok("hz_testraum_raumheizung" in Z["automationen"], "andere Räume unberührt")
print("\n### Fehlerfall: falsches Token")
r = subprocess.run([sys.executable, "-I", str(BASIS / "assistent" / "raumassistent.py"), "--trockenlauf"], input="", text=True, capture_output=True,
                   env=dict(env, HA_TOKEN="falsch"), timeout=30)
ok(r.returncode != 0 and "Anmeldung fehlgeschlagen" in (r.stdout + r.stderr), "falsches Token wird sauber abgewiesen")
json.dump(Z["protokoll"], open(BASIS / "tests/_mock_protokoll.json", "w"), ensure_ascii=False, indent=1)
print(f"\nErgebnis: {sum(p for p, _ in pruef)}/{len(pruef)} Prüfungen bestanden")
sys.exit(0 if all(p for p, _ in pruef) else 1)
