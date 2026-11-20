#!/usr/bin/env python3
"""Abnahmeprüfung gegen eine ECHTE lokale Home-Assistant-Instanz (Port 8124, siehe start.sh) – nicht gegen das produktive System.

Durchläuft die Einrichtungsoberfläche über dieselbe Schnittstelle wie der Browser und prüft danach, was Home Assistant
tatsächlich angelegt hat und wie sich die Automationen verhalten.
"""
import copy
import datetime as dt
import json
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASIS = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASIS / "assistent"))
from ha_verbindung import HAFehler, HAVerbindung  # noqa: E402

URL = "http://127.0.0.1:8124"
ERG = []
TAGE = ["mo", "di", "mi", "do", "fr", "sa", "so"]
ALLE = list(TAGE)


def titel(t):
    print("\n### " + t)


def pruefe(bed, text, detail=""):
    ERG.append((bool(bed), text))
    print(("   ✔ " if bed else "   ✘ ") + text + (f"   [{detail}]" if detail and not bed else ""))


def anmelden():
    def post(pfad, daten, form=False):
        req = urllib.request.Request(URL + pfad, data=(urllib.parse.urlencode(daten) if form else json.dumps(daten)).encode(),
                                     headers={"Content-Type": "application/x-www-form-urlencoded" if form else "application/json"})
        return json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
    cid = URL + "/"
    f = post("/auth/login_flow", {"client_id": cid, "handler": ["homeassistant", None], "redirect_uri": cid})
    r = post(f"/auth/login_flow/{f['flow_id']}", {"username": "test", "password": "hz-test-instanz", "client_id": cid})
    return post("/auth/token", {"grant_type": "authorization_code", "code": r["result"], "client_id": cid}, form=True)["access_token"]


GERAETE_ID = re.compile(r"\b(climate|sensor|binary_sensor|remote)\.[a-z0-9_]{2,}")


class HA(HAVerbindung):
    def befehl(self, typ, **daten):
        try:
            return super().befehl(typ, **daten)
        except (OSError, HAFehler) as ex:  # WebSocket nach längerer Pause geschlossen → neu verbinden
            if isinstance(ex, HAFehler) and "unterbrochen" not in str(ex):
                raise
            self.schliessen()
            self.verbinden()
            return super().befehl(typ, **daten)

    def zustand(self, eid):
        try:
            return self.rest("GET", f"/api/states/{eid}")
        except HAFehler:
            return None

    def s(self, eid):
        z = self.zustand(eid)
        return z["state"] if z else None

    def attr(self, eid, name):
        z = self.zustand(eid)
        return z["attributes"].get(name) if z else None

    def dienst(self, name, **daten):
        d, srv = name.split(".")
        return self.rest("POST", f"/api/services/{d}/{srv}", daten)

    def warte(self, bedingung, sekunden=25):
        ende = time.time() + sekunden
        while time.time() < ende:
            try:
                if bedingung():
                    return True
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.5)
        return False

    def ablauf(self, antworten, optionen_fuer=None):
        """Führt einen Einrichtungs- oder Anpassungsablauf aus. antworten: {Schritt: Eingabe | [Eingaben …] | Funktion(Schritt) → Eingabe}."""
        basis = "/api/config/config_entries/options/flow" if optionen_fuer else "/api/config/config_entries/flow"
        r = self.rest("POST", basis, {"handler": optionen_fuer or "heizung_universal", "show_advanced_options": False})
        verlauf, fehler = [], []
        for _ in range(120):
            if r["type"] not in ("form", "menu"):
                break
            sid = r["step_id"]
            verlauf.append(sid)
            if r.get("errors"):
                fehler.append((sid, r["errors"]))
            ant = antworten[sid]
            if isinstance(ant, list):
                ant = ant.pop(0)
            if callable(ant):
                ant = ant(r)
            if ant is None:  # Ablauf an dieser Stelle abbrechen (wie „Schließen“ im Dialog)
                self.rest("DELETE", f"{basis}/{r['flow_id']}")
                r = {"type": "abgebrochen"}
                break
            r = self.rest("POST", f"{basis}/{r['flow_id']}", ant)
        r["verlauf"], r["fehlerliste"] = verlauf, fehler
        return r

    def zeitplan(self, sid, tage):
        """Ändert die Zeiten eines Zeitplan-Helfers (wie im grafischen Editor)."""
        name = next(x["name"] for x in self.befehl("schedule/list") if x["id"] == sid)
        self.befehl("schedule/update", schedule_id=sid, name=name, **tage)

    def helfer(self, key):
        return sorted(z["entity_id"] for z in self.rest("GET", "/api/states") if z["entity_id"].split(".", 1)[1].startswith(f"hz_{key}_"))

    def auto_cfg(self, aid):
        return self.rest("GET", f"/api/config/automation/config/{aid}")

    def auto_aendern(self, aid, **neu):
        cfg = self.auto_cfg(aid)
        cfg["use_blueprint"]["input"].update(neu)
        self.rest("POST", f"/api/config/automation/config/{aid}", cfg)
        time.sleep(2)

    def eintrag(self, titel_):
        return next((e for e in self.rest("GET", "/api/config/config_entries/entry") if e["domain"] == "heizung_universal" and e["title"] == titel_), None)


def geraete(raum, aussen="sensor.aussentemperatur"):
    return {"raum_name": raum, "bt": f"climate.bt_{raum.lower()}", "raumfuehler": f"sensor.temperatur_{raum.lower()}", "aussen": aussen,
            "haus_aus": "input_boolean.heizung_aus_global"}


def funktionen(**kw):
    f = dict(profile=["komfort", "uebergang", "urlaub"], sommer_heizen=False, zeitquelle="zeitplan", fenster_modus="ohne", boost=False,
             vorheizen=False, mindest=False, zieltermin=False, klima=False, klima_art="ir", pv=False, karte=False)
    f.update(kw)
    return f


def profil(soll, absenk, *zeiten, **kw):
    """Eingabe des Profil-Schritts: drei Bereiche (wt = Montag bis Freitag, sa, so) mit je drei Heizphasen.
    zeiten: (Tage, von, bis) – wird auf die Tagesprogramme verteilt."""
    gruppen = {"wt": [], "sa": [], "so": []}
    for tage, von, bis in zeiten:
        if set(tage) & set(TAGE[:5]):
            gruppen["wt"].append((von, bis))
        if "sa" in tage:
            gruppen["sa"].append((von, bis))
        if "so" in tage:
            gruppen["so"].append((von, bis))
    p = {"soll": soll, "absenk": absenk}
    for tag, liste in gruppen.items():
        bereich = {"wt": "montag_bis_freitag", "sa": "samstag", "so": "sonntag"}[tag]
        p[bereich] = {}
        for i in (1, 2, 3):
            an = i <= len(liste)
            von, bis = liste[i - 1] if an else ("06:00:00", "08:00:00")
            p[bereich].update({f"heizphase_{i}_verwenden": an, f"heizphase_{i}_beginn": von, f"heizphase_{i}_ende": bis})
    p.update(kw)
    return p


def raum_mobil(name):
    """Raumkarte wie im Dashboard „Mobil“ (kompakter Kopf, Profile in drei Spalten) – Vorlage für die Design-Erkennung."""
    key = name.lower().replace(" ", "_")
    return {"type": "custom:mod-card", "card_mod": {"style": "ha-card {\n  border-radius: 24px !important;\n  background: linear-gradient(145deg,\n"
                                                              "    rgba(143,179,223,0.20), rgba(48,45,66,0.67)) !important;\n  backdrop-filter: blur(20px);\n}\n"},
            "card": {"type": "vertical-stack", "cards": [
                {"type": "custom:button-card", "entity": f"input_select.{key}_heizprofil", "name": name, "icon": "mdi:sofa-outline", "show_label": True,
                 "styles": {"card": [{"height": "65px"}], "grid": [{"grid-template-areas": '"i n" "i l"'}, {"grid-template-rows": "23px 22px"}]}},
                {"type": "grid", "columns": 3, "cards": [{"type": "custom:button-card", "entity": f"input_select.{key}_heizprofil", "name": "Komfort"}]}]}}


def kname(k):
    """Name einer Testkarte: Text der Markdown-Karte oder Kopfname der Mobil-Raumkarte."""
    return k.get("content") or (((k.get("card") or {}).get("cards") or [{}])[0].get("name"))


def platz(text):
    """Antwortfunktion: wählt in einem Auswahlschritt die Option, deren Beschriftung den Text enthält."""
    def wahl(schritt):
        feld = schritt["data_schema"][0]
        opt = next(o for o in feld["selector"]["select"]["options"] if text in o["label"])
        return {feld["name"]: opt["value"]}
    return wahl


def pos(index, design=None, merke=None):
    """Antwortfunktion für den Schritt „Position und Design“: Position wählen, Design = Vorschlag (erkannt) oder vorgegeben."""
    def wahl(schritt):
        if merke is not None:
            merke.append(schritt)
        vorschlag = next(f for f in schritt["data_schema"] if f["name"] == "design").get("default")
        return {"position": str(index), "design": design or vorschlag}
    return wahl


ALT_NAMEN = ["schlaf_heizung_profile", "schlaf_heizungs_boost", "schlaf_boost_ende", "schlaf_klima_automatik", "schlaf_pv_heizen", "schlaf_pv_sicherheitswache"]
ALT_AUTOS = ["alt_schlaf_heizprofil", "alt_schlaf_boost", "alt_schlaf_boost_ende", "alt_schlaf_klima", "alt_schlaf_pv", "alt_schlaf_pv_wache"]
ALT_SKRIPTE = ["schlaf_komfort_2", "schlaf_klima_20", "schlaf_pv_ir_ein"]
ALT_HELFER = ["input_select.schlaf_heizprofil", "input_number.schlaf_komforttemperatur", "input_number.schlaf_heizung_boost", "timer.schlaf_heizungs_boost_timer",
              "schedule.schlaf_komfort", "input_select.schlaf_klima_modus", "input_number.schlaf_klima_zieltemperatur", "input_boolean.schlaf_klima_aktiv",
              "input_boolean.schlaf_pv_regelung_aktiv", "input_boolean.schlaf_pv_heizfreigabe", "timer.schlaf_pv_sicherheitsfreigabe"]
ROLL_ORIGINAL = []


def _fehlt(ha, pfad):
    try:
        ha.rest("GET", pfad)
        return False
    except HAFehler:
        return True


def alte_steuerung_anlegen(ha):
    """Baut eine alte Raumsteuerung nach dem Muster des Wohnzimmers (Heizung, Boost, Klima, PV, IR-Skripte) und fremde Funktionen daneben."""
    for typ, name, extra in [
            ("input_select", "Schlaf Heizprofil", {"options": ["Komfort", "Übergang", "Sommer", "Urlaub", "Aus"]}),
            ("input_number", "Schlaf Komforttemperatur", {"min": 5, "max": 30, "step": 0.5, "mode": "slider"}),
            ("input_number", "Schlaf Heizung Boost", {"min": 5, "max": 25, "step": 0.5, "mode": "slider"}),
            ("timer", "Schlaf Heizungs Boost Timer", {"duration": "01:00:00"}), ("schedule", "Schlaf Komfort", {}),
            ("input_select", "Schlaf Klima Modus", {"options": ["Aus", "Automatik Kühlen", "Manuell Kühlen"]}),
            ("input_number", "Schlaf Klima Zieltemperatur", {"min": 16, "max": 23, "step": 1, "mode": "slider"}),
            ("input_boolean", "Schlaf Klima Aktiv", {}), ("input_boolean", "Schlaf PV Regelung aktiv", {}), ("input_boolean", "Schlaf PV Heizfreigabe", {}),
            ("timer", "Schlaf PV Sicherheitsfreigabe", {"duration": "00:02:00"}),
            ("input_boolean", "Alle ausser Haus", {}), ("input_boolean", "TV Kueche", {})]:
        ha.befehl(f"{typ}/create", name=name, **extra)
    auto = lambda aid, alias, trig, akt, bed=None: ha.rest("POST", f"/api/config/automation/config/{aid}", {  # noqa: E731
        "alias": alias, "description": "alt", "triggers": trig, "conditions": bed or [], "actions": akt, "mode": "single"})
    st = lambda e: [{"trigger": "state", "entity_id": e}]  # noqa: E731
    auto("alt_schlaf_heizprofil", "Schlaf Heizung Profile", st("input_select.schlaf_heizprofil") + st("schedule.schlaf_komfort"),
         [{"action": "climate.set_temperature", "target": {"entity_id": "climate.bt_schlaf"}, "data": {"temperature": "{{ states('input_number.schlaf_komforttemperatur') | float(20) }}"}}],
         [{"condition": "state", "entity_id": "input_boolean.heizung_aus_global", "state": "off"}])
    auto("alt_schlaf_boost", "Schlaf Heizungs Boost", st("input_number.schlaf_heizung_boost"),
         [{"action": "timer.start", "target": {"entity_id": "timer.schlaf_heizungs_boost_timer"}},
          {"action": "climate.set_temperature", "target": {"entity_id": "climate.bt_schlaf"}, "data": {"temperature": "{{ states('input_number.schlaf_heizung_boost') }}"}}])
    auto("alt_schlaf_boost_ende", "Schlaf Boost Ende", [{"trigger": "event", "event_type": "timer.finished", "event_data": {"entity_id": "timer.schlaf_heizungs_boost_timer"}}],
         [{"action": "input_number.set_value", "target": {"entity_id": "input_number.schlaf_heizung_boost"}, "data": {"value": 5}}])
    auto("alt_schlaf_klima", "Schlaf Klima Automatik", st("input_select.schlaf_klima_modus"),
         [{"action": "remote.send_command", "target": {"entity_id": "remote.broadlink_schlafzimmer"}, "data": {"device": "klima_schlaf", "command": "power_off"}},
          {"action": "input_boolean.turn_off", "target": {"entity_id": "input_boolean.schlaf_klima_aktiv"}}],
         [{"condition": "template", "value_template": "{{ states('input_number.schlaf_klima_zieltemperatur') | float(0) > 30 }}"}])
    auto("alt_schlaf_pv", "Schlaf PV Heizen", [{"trigger": "state", "entity_id": "input_boolean.schlaf_pv_heizfreigabe", "to": "on"}],
         [{"action": "input_boolean.turn_on", "target": {"entity_id": "input_boolean.schlaf_pv_regelung_aktiv"}},
          {"action": "timer.start", "target": {"entity_id": "timer.schlaf_pv_sicherheitsfreigabe"}},
          {"action": "climate.set_hvac_mode", "target": {"entity_id": "climate.bt_schlaf"}, "data": {"hvac_mode": "off"}},
          {"action": "climate.set_temperature", "target": {"entity_id": "climate.trv_schlaf"}, "data": {"temperature": 5}}],
         [{"condition": "state", "entity_id": "input_boolean.schlaf_klima_aktiv", "state": "off"}])
    auto("alt_schlaf_pv_wache", "Schlaf PV Sicherheitswache", [{"trigger": "event", "event_type": "timer.finished", "event_data": {"entity_id": "timer.schlaf_pv_sicherheitsfreigabe"}}],
         [{"action": "input_boolean.turn_off", "target": {"entity_id": "input_boolean.schlaf_pv_regelung_aktiv"}},
          {"action": "climate.set_hvac_mode", "target": {"entity_id": "climate.bt_schlaf"}, "data": {"hvac_mode": "heat"}}])
    auto("alt_tv_kueche", "TV Küche – Tagessteuerung", [{"trigger": "time", "at": "03:33:00"}],
         [{"action": "remote.send_command", "target": {"entity_id": "remote.broadlink_schlafzimmer"}, "data": {"device": "tv", "command": "power"}},
          {"action": "input_boolean.turn_on", "target": {"entity_id": "input_boolean.tv_kueche"}}])
    auto("alt_rollladen", "Rolladen Schlaf intelligent", st("input_select.schlaf_klima_modus"),
         [{"action": "persistent_notification.create", "data": {"message": "Rollladen", "notification_id": "rollo_schlaf"}}],
         [{"condition": "state", "entity_id": "input_boolean.schlaf_klima_aktiv", "state": "on"},
          {"condition": "state", "entity_id": "input_boolean.alle_ausser_haus", "state": "off"}])
    auto("alt_meldung", "Meldung Schlafzimmer", st("input_boolean.alle_ausser_haus"),
         [{"action": "persistent_notification.create", "data": {"message": "Meldung", "notification_id": "meldung_schlaf"}}])
    auto("alt_pv_assistent", "PV Benachrichtigung", [{"trigger": "event", "event_type": "pv_assistent_test"}],
         [{"action": "input_number.set_value", "target": {"entity_id": "input_number.schlaf_klima_zieltemperatur"}, "data": {"value": 20}},
          {"action": "input_select.select_option", "target": {"entity_id": "input_select.schlaf_klima_modus"}, "data": {"option": "Automatik Kühlen"}},
          {"action": "input_boolean.turn_off", "target": {"entity_id": "input_boolean.alle_ausser_haus"}}])
    skript = lambda sid, alias, folge: ha.rest("POST", f"/api/config/script/config/{sid}", {"alias": alias, "sequence": folge, "mode": "single"})  # noqa: E731
    skript("schlaf_komfort_2", "Schlaf Komfort", [{"action": "input_boolean.turn_off", "target": {"entity_id": "input_boolean.heizung_aus_global"}},
                                                  {"action": "input_select.select_option", "target": {"entity_id": "input_select.schlaf_heizprofil"}, "data": {"option": "Komfort"}},
                                                  {"action": "automation.trigger", "target": {"entity_id": "automation.schlaf_heizung_profile"}}])
    skript("schlaf_klima_20", "Schlaf Klima 20", [{"action": "remote.send_command", "target": {"entity_id": "remote.broadlink_schlafzimmer"},
                                                    "data": {"device": "klima_schlaf", "command": "power_20"}},
                                                   {"action": "input_number.set_value", "target": {"entity_id": "input_number.schlaf_klima_zieltemperatur"}, "data": {"value": 20}}])
    skript("schlaf_pv_ir_ein", "Schlaf PV IR EIN", [{"action": "remote.send_command", "target": {"entity_id": "remote.broadlink_schlafzimmer"},
                                                      "data": {"device": "klima_schlaf", "command": "heizen_24"}},
                                                     {"action": "input_boolean.turn_on", "target": {"entity_id": "input_boolean.schlaf_pv_regelung_aktiv"}}])
    skript("heizung_aus_test", "Heizung Aus (Test)", [{"action": "input_boolean.turn_on", "target": {"entity_id": "input_boolean.heizung_aus_global"}},
                                                       {"action": "input_select.select_option", "target": {"entity_id": ["input_select.schlaf_heizprofil", "input_select.hz_keller_heizprofil"]},
                                                        "data": {"option": "Aus"}},
                                                       {"action": "climate.set_temperature", "target": {"entity_id": ["climate.bt_schlaf", "climate.bt_keller"]}, "data": {"temperature": 5}}])
    cfg = ha.befehl("lovelace/config", url_path="test-ipad")
    cfg["views"][0]["sections"].append({"type": "grid", "cards": [
        {"type": "heading", "heading": "Schlafzimmer alt"},
        {"type": "custom:button-card", "name": "Schlaf alt", "entity": "input_select.schlaf_heizprofil",
         "tap_action": {"action": "perform-action", "perform_action": "script.turn_on", "target": {"entity_id": "script.schlaf_komfort_2"}}},
        {"type": "entities", "title": "Alle Thermostate", "entities": ["climate.bt_schlaf", "climate.bt_keller", "input_select.schlaf_heizprofil"]},
        {"type": "thermostat", "entity": "climate.bt_schlaf"}]})
    ha.befehl("lovelace/config/save", url_path="test-ipad", config=cfg)
    time.sleep(3)
    ROLL_ORIGINAL.append(ha.auto_cfg("alt_rollladen"))


def http_bestaetigen(ha):
    """HA 2026.11: Der Testport 8124 gilt als „vorläufige HTTP-Einstellung“ und würde nach 5 Minuten auf 8123 zurückgestellt
    (mit Neustart). Für die Testinstanz einmal bestätigen – wie der Benutzer im Dialog „Einstellungen übernehmen“."""
    try:
        ha.befehl("http/config/promote")
    except HAFehler:
        pass


def jetzt_aktiv_plan():
    """Zeitplan, der genau jetzt aktiv ist (für die Sollwertprüfung in Echtzeit)."""
    return {d: [{"from": "00:00:00", "to": "24:00:00"}] for d in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")}


def main():
    ha = HA(URL, anmelden(), timeout=90)
    version = ha.verbinden()
    print(f"Lokale Test-Instanz: Home Assistant {version} auf {URL}")
    http_bestaetigen(ha)
    log = Path(sys.argv[1]) if len(sys.argv) > 1 else None

    # ------------------------------------------------------------------ Vorbereitung: zwei Test-Dashboards
    titel("Vorbereitung")
    for url_path, name in (("test-mobil", "Mobil Test"), ("test-ipad", "iPad Test")):
        ha.befehl("lovelace/dashboards/create", url_path=url_path, title=name, mode="storage", require_admin=False, show_in_sidebar=True)
    ha.befehl("lovelace/config/save", url_path="test-mobil", config={"views": [{"title": "Start", "type": "custom:vertical-layout", "cards": [
        {"type": "markdown", "content": "Kopf"},
        {"type": "custom:tabdeck-card", "default_tab": "Heizkessel", "tabs": [
            {"name": "Heizkessel", "icon": "mdi:fire", "card": {"type": "vertical-stack", "cards": [{"type": "markdown", "content": "Heizkessel"}]}},
            {"name": "Heizung", "icon": "mdi:radiator", "card": {"type": "grid", "columns": 2, "square": False, "cards": [
                raum_mobil("Raum A"), raum_mobil("Raum B")]}}]}]}]})
    ha.befehl("lovelace/config/save", url_path="test-ipad", config={"views": [{"title": "Heizung", "type": "sections", "sections": [
        {"type": "grid", "cards": [{"type": "heading", "heading": "Räume"}, {"type": "markdown", "content": "vorhandene Karte"},
                                   {"type": "custom:mod-card", "card_mod": {"style": "ha-card {\n  max-width: 390px;\n  background: none;\n}\n"},
                                    "card": {"type": "custom:button-card", "name": "Raum im iPad-Design",
                                             "styles": {"card": [{"border-radius": "30px"}, {"background": "linear-gradient(135deg,rgba(55,145,85,.96),#151e2d)"}]}}}]}]}]})
    pruefe(ha.s("climate.bt_buero") == "heat" and ha.s("remote.broadlink_wohnzimmer") == "on", "Testgeräte vorhanden (Thermostate, Fühler, Fenster, IR-Sender)")
    eigen = (Path(__file__).resolve().parents[2] / "integration/heizung_universal/brand/icon.png").read_bytes()
    bilder = {}
    for b in ("icon.png", "dark_logo.png"):
        try:
            req = urllib.request.Request(f"{URL}/api/brands/integration/heizung_universal/{b}?placeholder=no", headers={"Authorization": f"Bearer {ha.token}"})
            bilder[b] = urllib.request.urlopen(req, timeout=15).read()
        except OSError as ex:
            bilder[b] = str(ex).encode()
    pruefe(bilder["icon.png"] == eigen and bilder["dark_logo.png"].startswith(b"\x89PNG"),
           "Logo der Integration wird von Home Assistant aus dem Ordner brand ausgeliefert (Symbol und dunkles Logo)", str(len(bilder["icon.png"])))

    # ------------------------------------------------------------------ A. Büro
    titel("A. Einfaches Büro: Heizung, Profile Komfort + Übergang, Fenster – über die Einrichtungsoberfläche")
    schritt_a = []
    r = ha.ablauf({
        "user": geraete("Büro") | {"bt": "climate.bt_buero", "raumfuehler": "sensor.temperatur_buero"},
        "funktionen": funktionen(profile=["komfort", "uebergang"], fenster_modus="eigen", karte=True),
        "profil": [profil(22, 16, (TAGE[:5], "06:00:00", "08:00:00"), (TAGE[:5], "16:00:00", "22:00:00"), (TAGE[5:], "08:00:00", "22:00:00")),
                   profil(21, 17, (ALLE, "07:00:00", "21:00:00"))],
        "fenster": {"fensterkontakte": ["binary_sensor.fenster_buero_1", "binary_sensor.fenster_buero_2"]},
        "werte": {"frostschutz": 5, "aussensperre": 20},
        "dashboard": {"dashboards": ["test-ipad"]}, "ansicht": {"ansicht": "0"}, "platz": lambda sch: schritt_a.append(sch) or platz("Abschnitt 1")(sch), "position": pos(1, merke=schritt_a),
        "bestaetigen": {"bestaetigt": True}})
    pruefe(r["type"] == "create_entry" and not r["fehlerliste"], "Ablauf ohne Fehler bis „Raum anlegen“", str(r.get("fehlerliste") or r.get("reason") or r.get("type")))
    pruefe(r["verlauf"] == ["user", "funktionen", "profil", "profil", "fenster", "werte", "dashboard", "ansicht", "platz", "position", "bestaetigen"],
           "Nur die Schritte der gewählten Funktionen erscheinen (keine Klima-, PV-, Termin-Schritte)", str(r["verlauf"]))
    hb = ha.helfer("buro")
    pruefe(hb == ["input_boolean.hz_buro_fensterstatus", "input_select.hz_buro_heizprofil", "input_text.hz_buro_status",
                  "schedule.hz_buro_zeitplan_komfort", "schedule.hz_buro_zeitplan_ubergang", "timer.hz_buro_fensterausfall"],
           "Genau die benötigten 6 Helfer angelegt (kein Boost-, Vorheiz-, Klima- oder PV-Helfer)", str(hb))
    pruefe(ha.attr("input_select.hz_buro_heizprofil", "options") == ["Komfort", "Übergang", "Sommer", "Aus"], "Heizprofil-Auswahl enthält nur die aktivierten Profile plus Sommer und Aus")
    bps = ha.befehl("blueprint/list", domain="automation")
    bp1 = bps.get("ha_heizung_universal/universelle_raumheizungssteuerung.yaml", {})
    pruefe("metadata" in bp1 and len(bp1["metadata"].get("input", {})) == 24 and all(f"profil_{p}_{t}" in bp1["metadata"]["input"] for p in ("komfort", "uebergang", "urlaub", "sommer") for t in ("wt", "sa", "so")),
           "Home Assistant hat Blueprint 1 angenommen: 24 Abschnitte, darunter je Profil „Montag bis Freitag“, „Samstag“, „Sonntag“", str(bp1)[:200])
    pruefe(ha.warte(lambda: ha.s("automation.heizung_buro") == "on"), "Automation „Heizung Büro“ läuft (Home Assistant hat Blueprint und Eingaben geprüft)", str(ha.s("automation.heizung_buro")))
    sid = "hz_buro_zeitplan_komfort"
    plan = next(x for x in ha.befehl("schedule/list") if x["id"] == sid)
    pruefe(plan["monday"] == [{"from": "06:00:00", "to": "08:00:00"}, {"from": "16:00:00", "to": "22:00:00"}] and plan["saturday"] == [{"from": "08:00:00", "to": "22:00:00"}],
           "Zeitplan-Helfer Komfort enthält die eingegebenen Wochenzeiten (grafisch änderbar)", str(plan.get("monday")))
    ha.zeitplan(sid, jetzt_aktiv_plan())
    pruefe(ha.warte(lambda: ha.attr("climate.bt_buero", "temperature") == 22), "Zeitplan aktiv → 22 °C am Better Thermostat", str(ha.attr("climate.bt_buero", "temperature")))
    ha.zeitplan(sid, {d: [] for d in jetzt_aktiv_plan()})
    pruefe(ha.warte(lambda: ha.attr("climate.bt_buero", "temperature") == 16), "Zeitplan inaktiv → 16 °C am Better Thermostat", str(ha.attr("climate.bt_buero", "temperature")))
    ha.dienst("input_select.select_option", entity_id="input_select.hz_buro_heizprofil", option="Übergang")
    ha.zeitplan("hz_buro_zeitplan_ubergang", jetzt_aktiv_plan())
    pruefe(ha.warte(lambda: ha.attr("climate.bt_buero", "temperature") == 21), "Profil Übergang mit eigenem Zeitplan → 21 °C")
    ha.dienst("input_select.select_option", entity_id="input_select.hz_buro_heizprofil", option="Komfort")
    ha.zeitplan(sid, jetzt_aktiv_plan())
    ha.warte(lambda: ha.attr("climate.bt_buero", "temperature") == 22)
    ha.auto_aendern("hz_buero_raumheizung", fenster_verzoegerung=3, fenster_nachlauf=3)
    ha.dienst("input_boolean.turn_on", entity_id="input_boolean.f_buero_1")
    pruefe(ha.warte(lambda: ha.s("input_boolean.hz_buro_fensterstatus") == "on") and ha.warte(lambda: ha.s("climate.bt_buero") == "off", 20),
           "Fenster auf → Fensterstatus an, nach der Verzögerung Heizpause (Better Thermostat aus)")
    ha.dienst("input_boolean.turn_off", entity_id="input_boolean.f_buero_1")
    pruefe(ha.warte(lambda: ha.s("climate.bt_buero") == "heat", 20), "Fenster zu → nach dem Nachlauf wird wieder geheizt")
    karten = ha.befehl("lovelace/config", url_path="test-ipad")["views"][0]["sections"][0]["cards"]
    kj = json.dumps(karten[1])
    pruefe(len(karten) == 4 and karten[1]["type"] == "custom:mod-card" and karten[2].get("content") == "vorhandene Karte" and "Raum im iPad-Design" in json.dumps(karten[3], ensure_ascii=False),
           "Karte im gewählten Dashboard, Abschnitt 1, an Position 2; vorhandene Karten unverändert")
    pl_opt = [o["label"] for o in schritt_a[0]["data_schema"][0]["selector"]["select"]["options"]]
    po = schritt_a[1]
    po_opt = [o["label"] for o in next(f for f in po["data_schema"] if f["name"] == "position")["selector"]["select"]["options"]]
    pruefe(pl_opt[0].startswith("Abschnitt 1 – Räume – enthält: Räume, vorhandene Karte, Raum im iPad-Design") and "Neuen Abschnitt" in pl_opt[-1]
           and "**Abschnitt 1 – Räume**: Räume, vorhandene Karte, Raum im iPad-Design" in schritt_a[0]["description_placeholders"]["uebersicht"],
           "Bereichsauswahl zeigt den Aufbau der Ansicht und nennt die vorhandenen Karten beim Namen", str(pl_opt))
    pruefe(po_opt[1] == "② zwischen „Räume“ und „vorhandene Karte“" and "② ┈" in po["description_placeholders"]["bild"]
           and "▢ vorhandene Karte" in po["description_placeholders"]["bild"] and "```" in po["description_placeholders"]["bild"],
           "Positionsauswahl nennt die Nachbarkarten und zeigt einen Lageplan mit nummerierten Einfügestellen", str(po_opt))
    pruefe(next(f for f in po["data_schema"] if f["name"] == "design").get("default") == "verlauf" and "max-width: 390px" in karten[1]["card_mod"]["style"]
           and karten[1]["card"]["cards"][0]["styles"]["card"][0] == {"border-radius": "30px"} and "#151e2d" in kj,
           "Design wird am Ziel erkannt: Karte im Farbverlauf-Design der vorhandenen iPad-Raumkarten angelegt (390 px, 30 px Radius, Verlauf nach Profil)")
    knoepfe = [b["name"] for b in karten[1]["card"]["cards"][1]["cards"]]
    pruefe("input_text.hz_buro_status" in kj and not GERAETE_ID.search(kj) and knoepfe == ["Komfort", "Übergang", "Sommer", "Aus"],
           "Karte verwendet nur Raum-Helfer (keine Geräte-IDs) und zeigt das nicht aktivierte Profil Urlaub nicht")
    st = ha.s("input_text.hz_buro_status")
    pruefe("bt=climate.bt_buero" in st and "p=Komfort" in st and "z=22.0" in st and "f=zu" in st, "Status für die Karte ist gefüllt", st)

    # ------------------------------------------------------------------ B. Badezimmer
    titel("B. Badezimmer: individuelle Wochenpläne, Mindesttemperatur- und Zieltemperatur-Termine")
    plz_b, pos_b = [], []
    r = ha.ablauf({
        "user": geraete("Bad"),
        "funktionen": funktionen(profile=["komfort", "urlaub"], mindest=True, zieltermin=True, karte=True),
        "profil": [profil(23, 18, (TAGE[:5], "05:30:00", "07:00:00"), (TAGE[5:], "08:00:00", "10:00:00"), (["sa"], "22:00:00", "01:00:00")),
                   profil(17, 16, (ALLE, "09:00:00", "19:00:00"))],
        "werte": {"frostschutz": 6, "aussensperre": 20, "vorheizen_max": 180, "mindest_halten": 120, "zieltermin_halten": 60},
        "termin": [{"art": "m", "profil": "komfort", "tage": ["mi"], "zeit": "04:20:00", "temp": 21, "weiterer": True},
                   {"art": "m", "profil": "komfort", "tage": ["mi"], "zeit": "15:45:00", "temp": 21.5, "weiterer": True},
                   {"art": "z", "profil": "komfort", "tage": ["sa"], "zeit": "18:30:00", "temp": 22.5, "weiterer": False}],
        "dashboard": {"dashboards": ["test-mobil"]}, "ansicht": {"ansicht": "0"},
        "platz": lambda sch: plz_b.append(sch) or platz("Tab „Heizung“")(sch), "position": pos(1, merke=pos_b),
        "bestaetigen": {"bestaetigt": True}})
    pruefe(r["type"] == "create_entry" and not r["fehlerliste"] and r["verlauf"].count("termin") == 3, "Ablauf mit drei Terminen ohne Fehler", str(r.get("fehlerliste") or r.get("type")))
    hb = ha.helfer("bad")
    pruefe(all(f"input_{x}" in hb for x in ("number.hz_bad_vorheizfaktor", "text.hz_bad_vorheizen", "text.hz_bad_vorheizbericht")) and len(hb) == 7,
           "Helfer für die Terminfunktion automatisch angelegt (7 Helfer, kein Fensterhelfer)", str(hb))
    inp = ha.auto_cfg("hz_bad_raumheizung")["use_blueprint"]["input"]
    pruefe(inp.get("mindest_aktiv") is True and inp.get("zieltermin_aktiv") is True and inp.get("vorheizen_aktiv") is False
           and (inp["komfort_m1_tage"], inp["komfort_m1_zeit"], inp["komfort_m1_temp"]) == (["mi"], "04:20:00", 21)
           and (inp["komfort_m2_zeit"], inp["komfort_m2_temp"]) == ("15:45:00", 21.5) and (inp["komfort_z1_tage"], inp["komfort_z1_zeit"], inp["komfort_z1_temp"]) == (["sa"], "18:30:00", 22.5),
           "Termine stehen in der Blueprint-Instanz: Mi 04:20 mind. 21 °C, Mi 15:45 mind. 21,5 °C, Sa 18:30 spätestens 22,5 °C")
    plan = next(x for x in ha.befehl("schedule/list") if x["id"] == "hz_bad_zeitplan_komfort")
    pruefe(plan["friday"] == [{"from": "05:30:00", "to": "07:00:00"}] and plan["saturday"] == [{"from": "08:00:00", "to": "10:00:00"}, {"from": "22:00:00", "to": "24:00:00"}]
           and plan["sunday"] == [{"from": "00:00:00", "to": "01:00:00"}, {"from": "08:00:00", "to": "10:00:00"}],
           "Zeitplan-Helfer aus den Tagesprogrammen vorbelegt, inkl. Samstag-Heizphase über Mitternacht (Sa 22:00 – So 01:00)", str(plan["saturday"]) + str(plan["sunday"]))
    pruefe(ha.warte(lambda: ha.s("automation.heizung_bad") == "on"), "Automation „Heizung Bad“ läuft")
    ha.zeitplan("hz_bad_zeitplan_komfort", {d: [] for d in jetzt_aktiv_plan()})
    ha.warte(lambda: ha.attr("climate.bt_bad", "temperature") == 18)
    bald = dt.datetime.now() + dt.timedelta(minutes=25)
    ha.auto_aendern("hz_bad_raumheizung", komfort_z1_tage=[TAGE[bald.weekday()]], komfort_z1_zeit=bald.strftime("%H:%M:00"), komfort_z1_temp=24.5)
    ok = ha.warte(lambda: ha.attr("climate.bt_bad", "temperature") == 24.5, 30)
    pruefe(ok, "Zieltemperatur-Termin in 25 Minuten (24,5 °C, Raum 19 °C): Sollwert wird sofort angehoben", str(ha.attr("climate.bt_bad", "temperature")))
    pruefe("Zieltemperatur 24.5" in (ha.s("input_text.hz_bad_vorheizbericht") or "") and f"vh=24.5@{bald.strftime('%H:%M')}" in (ha.s("input_text.hz_bad_status") or ""),
           "Bericht und Kartenstatus nennen Zieltemperatur und Uhrzeit", str(ha.s("input_text.hz_bad_vorheizbericht")))
    ha.auto_aendern("hz_bad_raumheizung", zieltermin_aktiv=False)
    pruefe(ha.warte(lambda: ha.attr("climate.bt_bad", "temperature") == 18, 30), "Zieltemperatur-Funktion in der Blueprint ausgeschaltet → zurück auf Absenkung 18 °C")
    tab = ha.befehl("lovelace/config", url_path="test-mobil")["views"][0]["cards"][1]["tabs"][1]["card"]["cards"]
    kb = tab[1]["card"]["cards"] if len(tab) == 3 and tab[1]["type"] == "custom:mod-card" else [{}, {}]
    pruefe(len(tab) == 3 and tab[1]["type"] == "custom:mod-card" and kname(tab[0]) == "Raum A" and kname(tab[2]) == "Raum B"
           and "backdrop-filter" in tab[1]["card_mod"]["style"] and kb[0].get("styles", {}).get("grid", [{}, {}, {}])[2] == {"grid-template-rows": "23px 22px"}
           and kb[0].get("name") == "Bad" and kb[1].get("columns") == 3 and "mdi:bathtub-outline" in json.dumps(kb[0]) and "rgba(174,142,225,0.20)" in tab[1]["card_mod"]["style"],
           "Tab „Heizung“ im Mobil-Dashboard (Raster mit 2 Spalten): Karte in Reihe 1 rechts – im Mobil-Design (kompakter Kopf, Profile in 3 Spalten, Tönung und Symbol für Bad)")
    pruefe(plz_b and plz_b[0]["data_schema"][0]["selector"]["select"]["options"][0]["label"].startswith("★ Empfohlen · Tab „Heizung“ (2 Raumkarten)")
           and pos_b and next(f for f in pos_b[0]["data_schema"] if f["name"] == "design").get("default") == "mobil"
           and "Reihe 1  ① Raum A" in pos_b[0]["description_placeholders"]["bild"]
           and [o["label"] for o in next(f for f in pos_b[0]["data_schema"] if f["name"] == "position")["selector"]["select"]["options"]][1] == "② Reihe 1 · rechts – vor „Raum B“",
           "Bereichsauswahl empfiehlt den Tab mit den Raumkarten (oben, vorausgewählt); Position als Lageplan mit Reihen und Spalten; Design „Mobil“ vorgeschlagen")

    # ------------------------------------------------------------------ C. Wohnzimmer
    titel("C. Wohnzimmer: Heizung, Boost, Klimaautomatik (Broadlink Wohnzimmer) und PV-Überschussheizen")
    ha.dienst("input_number.set_value", entity_id="input_number.t_wohnzimmer", value=21)
    wz_auswahl, wz_klima, wz_pv = [], [], []
    wz_codes = ha.attr("remote.broadlink_wohnzimmer", "gelernt")
    geschuetzt = ha.ablauf({"user": geraete("Wohnzimmer"), "funktionen": funktionen(profile=["komfort"], klima=True, zeitquelle="phasen"),
                            "profil": [profil(22, 16, (ALLE, "06:00:00", "22:00:00"))], "werte": {"frostschutz": 5, "aussensperre": 20},
                            "klima_sender": {"klima_sender": "remote.broadlink_wohnzimmer"},
                            "klima": {"ir_geraet": "klima", "ir_pruefen": True, "befehl_kuehlen": "power_{stufe}",
                                      "befehl_zusatz": "", "befehl_aus": "power_off", "stufe_min": 16, "stufe_max": 23, "luefter": ""},
                            "lernen_auswahl": [{"befehle": ["power_off"], "testen": [], "ueberschreiben": False}, {"befehle": [], "testen": [], "ueberschreiben": False}],
                            "bestaetigen": None})
    pruefe(("lernen_auswahl", {"base": "ueberschreiben"}) in geschuetzt["fehlerliste"] and ha.attr("remote.broadlink_wohnzimmer", "gelernt") == wz_codes
           and ha.attr("remote.broadlink_wohnzimmer", "gesendet") == [],
           "Überschreibschutz: ein vorhandener Wohnzimmer-Befehl wird ohne ausdrückliches Häkchen nicht neu angelernt; nichts gesendet, nichts verändert")
    r = ha.ablauf({
        "user": geraete("Wohnzimmer"),
        "funktionen": funktionen(fenster_modus="eigen", boost=True, klima=True, pv=True, karte=True),
        "profil": [profil(22, 16, (ALLE, "06:00:00", "22:00:00")), profil(21, 16, (ALLE, "07:00:00", "21:00:00")), profil(17, 16, (ALLE, "09:00:00", "19:00:00"))],
        "fenster": {"fensterkontakte": ["binary_sensor.fenster_wohnzimmer_1", "binary_sensor.fenster_wohnzimmer_2"]},
        "werte": {"frostschutz": 5, "aussensperre": 20, "boost_dauer": 120},
        "klima_sender": {"klima_sender": "remote.broadlink_wohnzimmer"},
        "klima": lambda sch: wz_klima.append(sch) or {"ir_geraet": "klima", "ir_pruefen": True, "befehl_kuehlen": "power_{stufe}",
                  "befehl_zusatz": "eco_{stufe}", "befehl_aus": "power_off", "stufe_min": 16, "stufe_max": 23, "luefter": "",
                  "klima_steckdose": "switch.klima_steckdose_wohnzimmer", "laeuft_ab_w": 15},
        "lernen_auswahl": [lambda sch: wz_auswahl.append(sch) or {"befehle": [], "testen": ["power_off"], "ueberschreiben": False},
                           lambda sch: wz_auswahl.append(sch) or {"befehle": next(f for f in sch["data_schema"] if f["name"] == "befehle").get("default"),
                                                                  "testen": next(f for f in sch["data_schema"] if f["name"] == "testen").get("default"),
                                                                  "ueberschreiben": False}],
        "lernen": lambda sch: {"aktion": "lernen"},
        "lernen_test": lambda sch: {"aktion": "weiter" if "gesendet" in (sch["description_placeholders"].get("status") or "") else "testen"},
        "pv": lambda sch: wz_pv.append(sch) or {"pv_sender": "remote.broadlink_wohnzimmer", "befehl_heizen": "heizen_{stufe}", "heiz_stufe_min": 23, "heiz_stufe_max": 25, "pv_heizstufe": 24,
               "befehl_heizen_aus": "heizen_24_off", "heiz_anlernen": "einzeln", "pv_trvs": ["climate.trv_wohnzimmer"], "pv_ventile": [], "soc": "sensor.energie_soc",
               "netz": "sensor.energie_netz", "akku_leistung": "sensor.energie_akku", "pv_leistung": "sensor.energie_pvl", "verbrauch": "sensor.energie_last",
               "zeitstempel_attribut": "", "start_leistung": 1000, "soc_start": 95, "soc_halten": 85, "pv_ziel": 24},
        "dashboard": {"dashboards": ["test-mobil"]}, "ansicht": {"ansicht": "0"}, "platz": platz("Tab „Heizung“"), "position": pos(0),
        "bestaetigen": {"bestaetigt": True}})
    pruefe(r["type"] == "create_entry" and not r["fehlerliste"], "Ablauf mit Klima und PV ohne Fehler", str(r.get("fehlerliste") or r.get("type")))
    vg = {f["name"]: f.get("default") for f in wz_klima[0]["data_schema"]} if wz_klima else {}
    erk = wz_klima[0]["description_placeholders"].get("erkennung", "") if wz_klima else ""
    pruefe(vg.get("ir_geraet") == "klima" and vg.get("befehl_kuehlen") == "power_{stufe}" and vg.get("befehl_aus") == "power_off"
           and (vg.get("stufe_min"), vg.get("stufe_max")) == (16, 23) and "klima_sender" not in vg and "alle vorhanden" in erk and "eco_{stufe}" in erk,
           "IR-Erkennung ohne alte Steuerung: Gerät, Kühlbefehl, Aus und Stufen 16–23 aus den im Broadlink gespeicherten Befehlen vorausgefüllt; eco_{stufe} als möglicher Zusatzbefehl genannt",
           str({k: vg.get(k) for k in ("ir_geraet", "befehl_kuehlen", "befehl_aus", "stufe_min", "stufe_max")}) + " " + erk[:200])
    pv_vg = {f["name"]: f.get("default") for f in wz_pv[0]["data_schema"]} if wz_pv else {}
    hs = wz_pv[0]["description_placeholders"].get("heiz_stand", "") if wz_pv else ""
    pruefe(pv_vg.get("befehl_heizen") == "heizen_{stufe}" and pv_vg.get("befehl_heizen_aus") == "heizen_24_off" and (pv_vg.get("heiz_stufe_min"), pv_vg.get("heiz_stufe_max")) == (22, 28)
           and pv_vg.get("pv_heizstufe") == 24 and pv_vg.get("heiz_anlernen") == "einzeln"
           and "fehlen noch:** heizen_22, heizen_23, heizen_25, heizen_26, heizen_27, heizen_28" in hs,
           "PV-Seite: heizen_{stufe} und heizen_24_off erkannt, Heizstufen 22–28 vorgeschlagen; die fehlenden heizen_22 … heizen_28 werden zum Anlernen angekündigt",
           str({k: pv_vg.get(k) for k in ("befehl_heizen", "befehl_heizen_aus", "heiz_stufe_min", "heiz_stufe_max", "heiz_anlernen")}) + " " + hs[:200])
    opts = wz_auswahl[0]["data_schema"][0]["selector"]["select"]["options"] if wz_auswahl else []
    pruefe(wz_auswahl and wz_auswahl[0]["data_schema"][0].get("default") == [] and all("bereits vorhanden" in o["label"] for o in opts) and len(opts) == 17,
           "Klima-Schritt: alle 17 Kühlbefehle des Wohnzimmers als „bereits vorhanden“ erkannt, keiner zum Anlernen vorgeschlagen", str([o["label"] for o in opts][:3]))
    hopts = {o["value"]: o["label"] for o in wz_auswahl[1]["data_schema"][0]["selector"]["select"]["options"]} if len(wz_auswahl) > 1 else {}
    pruefe(list(hopts) == ["heizen_23", "heizen_24", "heizen_25", "heizen_24_off"] and "bereits vorhanden" in hopts["heizen_24"] and "fehlt noch" in hopts["heizen_23"]
           and wz_auswahl[1]["data_schema"][0].get("default") == ["heizen_23", "heizen_25"],
           "PV-Schritt: Heizbefehle je Heizstufe (23–25 °C) am Broadlink der Klimaanlage geprüft – nur die fehlenden zum Anlernen vorgeschlagen", str(hopts))
    gel_wz = (ha.attr("remote.broadlink_wohnzimmer", "gelernt") or {}).get("klima", [])
    pruefe(ha.attr("remote.broadlink_wohnzimmer", "gesendet") == ["power_off", "heizen_23", "heizen_25", "heizen_24", "heizen_24_off"] and "heizen_23" in gel_wz and "heizen_25" in gel_wz
           and all(set(v) <= set((ha.attr("remote.broadlink_wohnzimmer", "gelernt") or {}).get(k, [])) for k, v in wz_codes.items()),
           "Fehlende Heizbefehle direkt über genau diesen Broadlink angelernt und testweise gesendet; vorhandene Befehle unverändert", str(ha.attr("remote.broadlink_wohnzimmer", "gesendet")))
    wz_codes = ha.attr("remote.broadlink_wohnzimmer", "gelernt")
    tv = next((f for f in wz_auswahl[1]["data_schema"] if f["name"] == "testen"), {}) if len(wz_auswahl) > 1 else {}
    pruefe(tv.get("default") == ["heizen_24", "heizen_24_off"] and "IR-Prüffreigabe" in wz_auswahl[1]["description_placeholders"].get("stand", "")
           and ha.warte(lambda: ha.s("input_boolean.hz_wohnzimmer_pv_ir_geprueft") == "on"),
           "IR-Prüffreigabe: vorhandene PV-Befehle (heizen_24, heizen_24_off) zum Testen vorausgewählt; nach Test und Bestätigung ist die Freigabe automatisch an",
           str(tv.get("default")) + " " + str(ha.s("input_boolean.hz_wohnzimmer_pv_ir_geprueft")))
    pruefe(all(ha.warte(lambda a=a: ha.s(a) == "on") for a in ("automation.heizung_wohnzimmer", "automation.klima_wohnzimmer", "automation.pv_heizen_wohnzimmer")),
           "Alle drei Automationen laufen (Raumheizung, Klimaautomatik, PV-Überschussheizen)")
    pv_inp = ha.auto_cfg("hz_wohnzimmer_pv")["use_blueprint"]["input"]
    pruefe("klima_sender" not in pv_inp and pv_inp.get("ir_konfiguration") == "input_text.hz_wohnzimmer_klima_ir"
           and pv_inp.get("raumheizung_automation") == "automation.heizung_wohnzimmer" and pv_inp.get("klima_automation") == "automation.klima_wohnzimmer",
           "PV-Instanz hat keinen eigenen IR-Sender, sondern die gemeinsame IR-Konfiguration; verknüpft mit Raumheizung und Klimaautomatik")
    kl_inp = ha.auto_cfg("hz_wohnzimmer_klima")["use_blueprint"]["input"]
    pruefe(all(x.get("klima_steckdose") == "switch.klima_steckdose_wohnzimmer" and x.get("klima_leistung") == "sensor.klima_steckdose_wohnzimmer_leistung"
               and x.get("laeuft_ab_w") == 15 for x in (kl_inp, pv_inp)) and "steckdose_halten" not in pv_inp,
           "Klima-Steckdose in Klimaautomatik und PV-Heizen eingetragen; Leistungsmessung derselben Steckdose automatisch ergänzt",
           str({k: kl_inp.get(k) for k in ("klima_steckdose", "klima_leistung", "laeuft_ab_w")}))
    pruefe(ha.warte(lambda: ha.s("input_text.hz_wohnzimmer_klima_ir") == "v=1|s=remote.broadlink_wohnzimmer|g=klima|h=heizen_{stufe}|ha=heizen_24_off")
           and ha.auto_cfg("hz_wohnzimmer_pv")["use_blueprint"]["input"].get("heizstufe") == 24,
           "Klimaautomatik veröffentlicht Sender und Heizbefehle für PV", str(ha.s("input_text.hz_wohnzimmer_klima_ir")))
    ha.zeitplan("hz_wohnzimmer_zeitplan_komfort", {d: [] for d in jetzt_aktiv_plan()})
    ha.warte(lambda: ha.attr("climate.bt_wohnzimmer", "temperature") == 16)
    ha.dienst("input_number.set_value", entity_id="input_number.hz_wohnzimmer_boost", value=24)
    pruefe(ha.warte(lambda: ha.attr("climate.bt_wohnzimmer", "temperature") == 24 and ha.s("timer.hz_wohnzimmer_boost_timer") == "active"),
           "Boost 24 °C: Timer läuft, Better Thermostat auf 24 °C")
    ha.dienst("timer.finish", entity_id="timer.hz_wohnzimmer_boost_timer")
    pruefe(ha.warte(lambda: ha.attr("climate.bt_wohnzimmer", "temperature") == 16), "Boost-Ende → zurück auf 16 °C")
    # PV-Überschussheizen: Startbedingungen erfüllt (Überschuss, Speicher voll, IR geprüft, Freigabe)
    # Startbestätigung für den Test von 5 auf 1 Minute; die Test-Energiesensoren melden sich nur beim Start der Instanz → zulässiges Datenalter erhöhen
    ha.auto_aendern("hz_wohnzimmer_pv", start_bestaetigung=1, max_energie_alter=1800)
    ha.dienst("input_boolean.turn_on", entity_id="input_boolean.hz_wohnzimmer_pv_ir_geprueft")
    n_pv = len(ha.attr("remote.broadlink_wohnzimmer", "gesendet") or [])  # beim Einrichten testweise gesendete Befehle nicht mitzählen
    ha.dienst("input_boolean.turn_on", entity_id="input_boolean.hz_wohnzimmer_pv_heizfreigabe")
    zu = ha.warte(lambda: ha.s("climate.bt_wohnzimmer") == "off", 120)
    pruefe(zu and "heizen_24" not in (ha.attr("remote.broadlink_wohnzimmer", "gesendet") or [])[n_pv:],
           "PV-Start: Raumheizung schließt zuerst das Better Thermostat; noch kein Heizbefehl, solange die Heizkörper nicht bestätigt geschlossen sind",
           f"Status: {ha.s('input_text.hz_wohnzimmer_pv_status')}")
    ha.dienst("climate.set_temperature", entity_id="climate.trv_wohnzimmer", temperature=5)  # Testgerät: Heizkörperthermostat folgt dem Better Thermostat
    ok = ha.warte(lambda: "heizen_24" in (ha.attr("remote.broadlink_wohnzimmer", "gesendet") or [])[n_pv:], 90)
    pruefe(ok, "PV-Überschussheizen: Heizkörper geschlossen, danach Heizbefehl „heizen_24“ über den Broadlink des Raums",
           f"Status: {ha.s('input_text.hz_wohnzimmer_pv_status')} · BT {ha.s('climate.bt_wohnzimmer')}")
    pruefe(ha.s("climate.bt_wohnzimmer") == "off", "Während PV-Heizen hält die Raumheizung das Better Thermostat geschlossen", str(ha.s("climate.bt_wohnzimmer")))
    ha.dienst("input_boolean.turn_off", entity_id="input_boolean.hz_wohnzimmer_pv_heizfreigabe")
    pruefe(ha.warte(lambda: (ha.attr("remote.broadlink_wohnzimmer", "gesendet") or [""])[-1] == "heizen_24_off", 40) and ha.warte(lambda: ha.s("climate.bt_wohnzimmer") == "heat", 60),
           "PV-Freigabe aus → „heizen_24_off“ gesendet, Raumheizung übernimmt wieder",
           f"{ha.attr('remote.broadlink_wohnzimmer', 'gesendet')} · BT {ha.s('climate.bt_wohnzimmer')} · {ha.s('input_text.hz_wohnzimmer_status')} · PV {ha.s('input_text.hz_wohnzimmer_pv_status')} · "
           + str({f: ha.s('input_boolean.hz_wohnzimmer_pv_' + f) for f in ('regelung_aktiv', 'heizbefehl_aktiv', 'ir_auftrag_offen', 'startvorbereitung')}) + f" Freigabe {ha.s('timer.hz_wohnzimmer_pv_sicherheitsfreigabe')}")
    # Klimaautomatik
    ha.dienst("input_select.select_option", entity_id="input_select.hz_wohnzimmer_heizprofil", option="Sommer")
    ha.dienst("input_number.set_value", entity_id="input_number.t_aussen", value=26)
    ha.dienst("input_number.set_value", entity_id="input_number.t_wohnzimmer", value=24.5)
    time.sleep(2)
    n = len(ha.attr("remote.broadlink_wohnzimmer", "gesendet"))
    ha.dienst("input_select.select_option", entity_id="input_select.hz_wohnzimmer_klima_modus", option="Automatik Kühlen")
    pruefe(ha.warte(lambda: ha.attr("remote.broadlink_wohnzimmer", "gesendet")[n:] == ["power_17", "eco_17"] and ha.s("input_boolean.hz_wohnzimmer_klima_aktiv") == "on"),
           "Klimaautomatik im Profil Sommer bei 24,5 °C: Kühlbefehl power_17 + Zusatzbefehl eco_17", str(ha.attr("remote.broadlink_wohnzimmer", "gesendet")[n:]))
    tab = ha.befehl("lovelace/config", url_path="test-mobil")["views"][0]["cards"][1]["tabs"][1]["card"]["cards"]
    kj = json.dumps(tab[0])
    pruefe(len(tab) == 4 and "hz_wohnzimmer_klima_modus" in kj and "hz_wohnzimmer_pv_heizfreigabe" in kj and "hz_wohnzimmer_boost" in kj and not GERAETE_ID.search(kj),
           "Karte an Position 1 im Tab „Heizung“ zeigt Boost, Klima und PV – ohne Geräte-IDs")
    kb = json.dumps(tab[2])
    pruefe("hz_bad_status" in kb and not any(x in kb for x in ("hz_bad_boost", "hz_bad_klima", "hz_bad_pv", "PV-Überschussheizen", "Klima Automatik Ziel")),
           "Bad-Karte zeigt die nicht aktivierten Funktionen (Boost, Klima, PV) nicht")

    # ------------------------------------------------------------------ D. Gästezimmer: ohne Fenster, Klima mit Anlernen (zweiter Broadlink)
    titel("D. Zimmer ohne Fensterkontakt, Klimaanlage mit neuem Anlernen über den zweiten Broadlink")
    lernfolge, gast_auswahl = [], []

    def lernen(schritt):
        return {"aktion": "ueberspringen" if schritt.get("errors") else "lernen"}

    def lerntest(schritt):
        lernfolge.append(schritt["description_placeholders"]["befehl"])
        gesendet = "gesendet" in (schritt["description_placeholders"].get("status") or "")
        return {"aktion": "weiter" if gesendet else "testen"}

    r = ha.ablauf({
        "user": geraete("Gast"),
        "funktionen": funktionen(profile=["komfort"], klima=True),
        "profil": [profil(21, 17, (ALLE, "07:00:00", "22:00:00"))],
        "werte": {"frostschutz": 5, "aussensperre": 20},
        "klima_sender": {"klima_sender": "remote.broadlink_schlafzimmer"},
        "klima": {"ir_geraet": "klima_gast", "ir_pruefen": False, "befehl_kuehlen": "kuehlen_{stufe}_{luefter}",
                  "befehl_zusatz": "", "befehl_aus": "zeitueberschreitung_aus", "stufe_min": 20, "stufe_max": 22, "luefter": "auto"},
        "lernen_auswahl": lambda s: gast_auswahl.append(s) or {"befehle": [o["value"] for o in s["data_schema"][0]["selector"]["select"]["options"]], "testen": [], "ueberschreiben": False},
        "lernen": lernen, "lernen_test": lerntest,
        "bestaetigen": {"bestaetigt": True}})
    pruefe(r["type"] == "create_entry", "Ablauf mit IR-Anlernen abgeschlossen", str(r.get("fehlerliste") or r.get("type")))
    pruefe(("lernen", {"base": "lernen_fehlgeschlagen"}) in r["fehlerliste"], "Kein IR-Signal innerhalb von 30 s: Fehler wird angezeigt, Befehl gilt nicht als gelernt")
    gel = (ha.attr("remote.broadlink_schlafzimmer", "gelernt") or {}).get("klima_gast")
    pruefe(gel == ["kuehlen_20_auto", "kuehlen_21_auto", "kuehlen_22_auto"],
           "Kühlbefehle mit remote.learn_command unter dem Gerätenamen dieses Raums gespeichert (ein Befehl je Temperatur, mit Lüfterstufe; ohne PV keine Heizbefehle)", str(gel))
    pruefe(gast_auswahl and all("fehlt noch" in o["label"] for o in gast_auswahl[0]["data_schema"][0]["selector"]["select"]["options"]),
           "Zweiter Broadlink: alle Befehle als „fehlt noch“ erkannt (keine gemeinsame Befehlssammlung mit dem Wohnzimmer)")
    pruefe(ha.attr("remote.broadlink_schlafzimmer", "gesendet") == gel and ha.attr("remote.broadlink_wohnzimmer", "gelernt") == wz_codes,
           "Jeder Befehl wurde über den gewählten Broadlink testweise gesendet; der Wohnzimmer-Broadlink blieb unberührt")
    pruefe(ha.helfer("gast") == sorted(["input_select.hz_gast_heizprofil", "input_text.hz_gast_status", "schedule.hz_gast_zeitplan_komfort", "input_select.hz_gast_klima_modus",
                                        "input_number.hz_gast_klima_ziel", "input_number.hz_gast_klima_manuell", "input_number.hz_gast_klima_letzte_stufe",
                                        "input_boolean.hz_gast_klima_aktiv", "input_text.hz_gast_klima_vor_fenster", "input_text.hz_gast_klima_ir"]) and "|g=klima_gast|" in (ha.s("input_text.hz_gast_klima_ir") or ""),
           "Ohne Fenster: kein Fensterstatus-Helfer und kein Ausfall-Timer; Klima-Helfer vorhanden", str(ha.helfer("gast")))
    ha.dienst("input_number.set_value", entity_id="input_number.t_aussen", value=8)
    ha.zeitplan("hz_gast_zeitplan_komfort", jetzt_aktiv_plan())
    pruefe(ha.warte(lambda: (ha.s("climate.bt_gast"), ha.attr("climate.bt_gast", "temperature")) == ("heat", 21)) and "f=ohne" in ha.s("input_text.hz_gast_status"),
           "Raum ohne Fenster heizt normal (keine Scheinpause): 21 °C, heat", f"{ha.s('climate.bt_gast')} {ha.attr('climate.bt_gast', 'temperature')}")
    # Kühlen über den Broadlink dieses Raums; danach: Befehl fehlt / Broadlink aus → kein vorgetäuschter Erfolg
    ha.dienst("input_number.set_value", entity_id="input_number.t_aussen", value=26)
    ha.dienst("input_select.select_option", entity_id="input_select.hz_gast_heizprofil", option="Sommer")
    ha.dienst("input_number.set_value", entity_id="input_number.t_gast", value=24.5)
    time.sleep(2)
    ha.dienst("input_select.select_option", entity_id="input_select.hz_gast_klima_modus", option="Automatik Kühlen")
    pruefe(ha.warte(lambda: ha.attr("remote.broadlink_schlafzimmer", "gesendet")[-1] == "kuehlen_20_auto" and ha.s("input_boolean.hz_gast_klima_aktiv") == "on")
           and "kuehlen_20_auto" not in ha.attr("remote.broadlink_wohnzimmer", "gesendet"),
           "Klimaautomatik Gast sendet den selbst angelernten Befehl über den eigenen Broadlink (nicht über den des Wohnzimmers)", str(ha.attr("remote.broadlink_schlafzimmer", "gesendet")))
    n = len(ha.attr("remote.broadlink_schlafzimmer", "gesendet"))
    ha.dienst("input_select.select_option", entity_id="input_select.hz_gast_klima_modus", option="Aus")
    time.sleep(6)
    pruefe(len(ha.attr("remote.broadlink_schlafzimmer", "gesendet")) == n and ha.s("input_boolean.hz_gast_klima_aktiv") == "on",
           "Benötigter Befehl „Aus“ ist nicht angelernt: nichts gesendet, „Klima aktiv“ bleibt wahrheitsgemäß an (kein vorgetäuschtes Ausschalten)",
           f"{ha.attr('remote.broadlink_schlafzimmer', 'gesendet')} {ha.s('input_boolean.hz_gast_klima_aktiv')}")
    ha.dienst("remote.learn_command", entity_id="remote.broadlink_schlafzimmer", device="klima_gast", command=["aus_gast"])
    ha.auto_aendern("hz_gast_klima", befehl_aus="aus_gast")
    ha.dienst("input_select.select_option", entity_id="input_select.hz_gast_klima_modus", option="Automatik Kühlen")
    time.sleep(3)
    ha.dienst("input_select.select_option", entity_id="input_select.hz_gast_klima_modus", option="Aus")
    pruefe(ha.warte(lambda: ha.attr("remote.broadlink_schlafzimmer", "gesendet")[-1] == "aus_gast" and ha.s("input_boolean.hz_gast_klima_aktiv") == "off"),
           "Befehl nachträglich angelernt und in der Blueprint-Instanz zugeordnet: „Aus“ wird gesendet, „Klima aktiv“ aus", str(ha.attr("remote.broadlink_schlafzimmer", "gesendet")))
    ha.dienst("remote.turn_off", entity_id="remote.broadlink_schlafzimmer")
    n = len(ha.attr("remote.broadlink_schlafzimmer", "gesendet"))
    ha.dienst("input_select.select_option", entity_id="input_select.hz_gast_klima_modus", option="Automatik Kühlen")
    time.sleep(6)
    meld = [m["notification_id"] for m in ha.befehl("persistent_notification/get")]
    pruefe(len(ha.attr("remote.broadlink_schlafzimmer", "gesendet")) == n and ha.s("input_boolean.hz_gast_klima_aktiv") == "off" and "hz_klima_ir_gast" in meld,
           "Broadlink nicht bereit: kein Befehl, „Klima aktiv“ bleibt aus, dauerhafte Meldung in Home Assistant", str(meld))
    ha.dienst("remote.turn_on", entity_id="remote.broadlink_schlafzimmer")
    ha.dienst("input_number.set_value", entity_id="input_number.t_gast", value=24.8)
    pruefe(ha.warte(lambda: ha.attr("remote.broadlink_schlafzimmer", "gesendet")[-1] == "kuehlen_20_auto" and ha.s("input_boolean.hz_gast_klima_aktiv") == "on"),
           "Broadlink wieder bereit: Kühlbefehl kuehlen_20_auto wird gesendet", str(ha.attr("remote.broadlink_schlafzimmer", "gesendet")))
    # Broadlink-Wechsel: nur in der Klimaautomatik-Instanz, danach neu anlernen über „Konfigurieren“
    ha.auto_aendern("hz_gast_klima", klima_sender="remote.broadlink_ersatz")
    pruefe(ha.warte(lambda: "s=remote.broadlink_ersatz|g=klima_gast" in (ha.s("input_text.hz_gast_klima_ir") or "")),
           "Broadlink getauscht (nur in der Klimaautomatik-Instanz): gemeinsame IR-Konfiguration nennt den neuen Sender")
    lernfolge.clear()
    r = ha.ablauf({"init": {"next_step_id": "ir"}, "lernen_auswahl": lambda s: {"befehle": ["kuehlen_20_auto", "kuehlen_21_auto"], "testen": [], "ueberschreiben": False},
                   "lernen": lernen, "lernen_test": lerntest}, optionen_fuer=ha.eintrag("Gast")["entry_id"])
    pruefe(r["type"] == "abort" and r["reason"] == "ir_fertig" and (ha.attr("remote.broadlink_ersatz", "gelernt") or {}).get("klima_gast") == ["kuehlen_20_auto", "kuehlen_21_auto"]
           and ha.attr("remote.broadlink_ersatz", "gesendet") == ["kuehlen_20_auto", "kuehlen_21_auto"],
           "„Konfigurieren → IR-Befehle neu anlernen“ liest den neuen Sender aus der Blueprint-Instanz, lernt und testet darüber", str(r.get("reason")))

    # ------------------------------------------------------------------ E. Alles deaktiviert
    titel("E. Alle Zusatzfunktionen deaktiviert; drei Tagesprogramme je Profil (Montag bis Freitag, Samstag, Sonntag) in der Blueprint")
    formular = []
    r = ha.ablauf({"user": {k: v for k, v in geraete("Keller").items() if k != "raumfuehler"},
                   "funktionen": lambda sch: formular.append(sch) or funktionen(profile=["komfort", "uebergang"], zeitquelle="phasen"),
                   "profil": [lambda sch: formular.append(sch) or profil(19, 15, (TAGE[:5], "06:00:00", "08:00:00"), (TAGE[:5], "11:30:00", "13:30:00"), (TAGE[:5], "15:30:00", "20:00:00"),
                                                                         (["sa"], "09:00:00", "12:00:00"), (["so"], "10:00:00", "11:00:00"), (["so"], "17:00:00", "21:00:00")),
                              profil(18, 14, (ALLE, "07:00:00", "09:00:00"))],
                   "werte": {"frostschutz": 5, "aussensperre": 20}, "bestaetigen": {"bestaetigt": True}})
    pruefe(r["type"] == "create_entry" and ha.helfer("keller") == ["input_select.hz_keller_heizprofil", "input_text.hz_keller_status"],
           "Nur zwei Helfer (Heizprofil, Status) – keine Zeitplan-, Fenster-, Boost-, Vorheiz-, Klima- oder PV-Helfer", str(ha.helfer("keller")))
    zq = next(f for f in formular[0]["data_schema"] if f["name"] == "zeitquelle")
    bereiche = {f["name"]: [x["name"] for x in f["schema"]] for f in formular[1]["data_schema"] if f.get("type") == "expandable"}
    pruefe(zq.get("default") == "phasen" and list(bereiche) == ["montag_bis_freitag", "samstag", "sonntag"]
           and all(v == [f"heizphase_{i}_{x}" for i in (1, 2, 3) for x in ("verwenden", "beginn", "ende")] for v in bereiche.values()),
           "Einrichtung: „Drei Tagesprogramme“ ist die Vorgabe; je Profil drei Bereiche (Mo–Fr, Sa, So) mit je drei Heizphasen (verwenden, Beginn, Ende)", str(bereiche)[:200])
    inp = ha.auto_cfg("hz_keller_raumheizung")["use_blueprint"]["input"]
    pruefe([(inp[f"komfort_wt{i}_aktiv"], inp.get(f"komfort_wt{i}_von"), inp.get(f"komfort_wt{i}_bis")) for i in (1, 2, 3)]
           == [(True, "06:00:00", "08:00:00"), (True, "11:30:00", "13:30:00"), (True, "15:30:00", "20:00:00")]
           and (inp["komfort_sa1_von"], inp["komfort_sa1_bis"], inp["komfort_sa2_aktiv"], inp["komfort_sa3_aktiv"]) == ("09:00:00", "12:00:00", False, False)
           and (inp["komfort_so1_von"], inp["komfort_so2_von"], inp["komfort_so2_bis"], inp["komfort_so3_aktiv"]) == ("10:00:00", "17:00:00", "21:00:00", False)
           and (inp["uebergang_wt1_von"], inp["uebergang_wt2_aktiv"], inp["uebergang_sa1_bis"]) == ("07:00:00", False, "09:00:00"),
           "Blueprint-Instanz: Komfort Mo–Fr 06:00–08:00, 11:30–13:30, 15:30–20:00 · Sa 09:00–12:00 · So 10:00–11:00 und 17:00–21:00; Übergang getrennt")
    ha.dienst("input_number.set_value", entity_id="input_number.t_aussen", value=8)
    heute = dt.datetime.now().weekday()
    mein = "wt" if heute < 5 else ("sa" if heute == 5 else "so")
    andere = [t for t in ("wt", "sa", "so") if t != mein]
    aus = {f"komfort_{t}{i}_aktiv": False for t in ("wt", "sa", "so") for i in (1, 2, 3)}
    ganztag = lambda t, i: {f"komfort_{t}{i}_aktiv": True, f"komfort_{t}{i}_von": "00:00:00", f"komfort_{t}{i}_bis": "23:59:00"}  # noqa: E731
    ha.auto_aendern("hz_keller_raumheizung", **(aus | ganztag(mein, 2)))
    pruefe(ha.warte(lambda: ha.attr("climate.bt_keller", "temperature") == 19), f"Heutiges Tagesprogramm ({mein}), nur Heizphase 2 aktiv → Solltemperatur 19 °C am Better Thermostat",
           str(ha.attr("climate.bt_keller", "temperature")))
    ha.auto_aendern("hz_keller_raumheizung", **(aus | ganztag(andere[0], 1) | ganztag(andere[1], 3)))
    pruefe(ha.warte(lambda: ha.attr("climate.bt_keller", "temperature") == 15),
           "Heizphasen nur in den beiden anderen Tagesprogrammen aktiv → heute Absenktemperatur 15 °C (Tagesprogramme sind unabhängig)", str(ha.attr("climate.bt_keller", "temperature")))
    ha.auto_aendern("hz_keller_raumheizung", **ganztag(mein, 3))
    ha.warte(lambda: ha.attr("climate.bt_keller", "temperature") == 19)
    ha.dienst("input_select.select_option", entity_id="input_select.hz_keller_heizprofil", option="Übergang")
    ok15 = ha.warte(lambda: ha.attr("climate.bt_keller", "temperature") in (14, 18))
    jetzt = dt.datetime.now().strftime("%H:%M")
    pruefe(ok15 and ha.attr("climate.bt_keller", "temperature") == (18 if "07:00" <= jetzt < "09:00" else 14),
           "Profil Übergang verwendet seine eigenen Tagesprogramme (07:00–09:00) und Temperaturen", str(ha.attr("climate.bt_keller", "temperature")))
    ha.dienst("input_select.select_option", entity_id="input_select.hz_keller_heizprofil", option="Komfort")
    ha.warte(lambda: ha.attr("climate.bt_keller", "temperature") == 19)
    doppelt = ha.ablauf({"user": {k: v for k, v in geraete("Keller").items() if k != "raumfuehler"}})
    pruefe(doppelt["type"] == "abort" and doppelt["reason"] == "already_configured", "Derselbe Raum kann nicht ein zweites Mal eingerichtet werden")
    belegt = ha.ablauf({"user": [geraete("Neu") | {"bt": "climate.bt_keller"}, None]})
    pruefe(("user", {"base": "bt_belegt"}) in belegt["fehlerliste"],
           "Better Thermostat, das schon ein anderer Raum dieser Integration steuert, wird bei der Einrichtung abgewiesen", str(belegt.get("fehlerliste")))
    ha.rest("POST", "/api/config/automation/config/fremd_neu", {"alias": "Fremde Steuerung Neu", "description": "",
            "triggers": [{"trigger": "state", "entity_id": "input_number.t_aussen", "to": "99"}],
            "actions": [{"action": "climate.set_temperature", "target": {"entity_id": "climate.bt_neu"}, "data": {"temperature": 25}}], "mode": "single"})
    time.sleep(2)
    alt_e = []
    testbetrieb = ha.ablauf({"user": geraete("Neu"), "funktionen": funktionen(profile=["komfort"], zeitquelle="phasen"),
                             "profil": [profil(20, 15, (ALLE, "00:00:00", "23:59:00"))], "werte": {"frostschutz": 5, "aussensperre": 20},
                             "altsteuerung": lambda sch: alt_e.append(sch) or {"abschalten": [], "helfer": [], "umstellen": False},
                             "bestaetigen": {"bestaetigt": True}})
    modus = ha.auto_cfg("hz_neu_raumheizung")["use_blueprint"]["input"].get("ausgabe_modus")
    time.sleep(4)
    pruefe(testbetrieb["type"] == "create_entry" and alt_e and modus == "test" and ha.s("automation.fremde_steuerung_neu") == "on"
           and "m=test" in (ha.s("input_text.hz_neu_status") or ""),
           "Fremde Automation am Thermostat gefunden, aber bewusst nicht abgeschaltet → neue Automation automatisch im Testbetrieb", f"{modus} {ha.s('input_text.hz_neu_status')}")
    ha.rest("DELETE", "/api/config/automation/config/fremd_neu")

    # ------------------------------------------------------------------ F. Gerätewechsel
    titel("F. Gerätewechsel im Büro: Thermostat, Raumfühler und Fensterkontakt nur in der Blueprint-Instanz")
    ha.dienst("input_number.set_value", entity_id="input_number.t_neu", value=20.4)
    vorher = ha.befehl("lovelace/config", url_path="test-ipad")
    helfer_vorher = ha.helfer("buro")
    ha.rest("DELETE", f"/api/config/config_entries/entry/{ha.eintrag('Neu')['entry_id']}")
    ha.auto_aendern("hz_buero_raumheizung", better_thermostat="climate.bt_neu", raumfuehler="sensor.temperatur_neu", fensterkontakte=["binary_sensor.fenster_neu_1"])
    pruefe(ha.warte(lambda: (ha.s("climate.bt_neu"), ha.attr("climate.bt_neu", "temperature")) == ("heat", 22)), "Neues Thermostat erhält den aktuellen Sollwert 22 °C",
           f"{ha.s('climate.bt_neu')} {ha.attr('climate.bt_neu', 'temperature')}")
    st = ha.s("input_text.hz_buro_status")
    pruefe("bt=climate.bt_neu" in st and "t=20.4" in st, "Kartenstatus nennt neues Thermostat und Wert des neuen Raumfühlers", st)
    alt_soll = ha.attr("climate.bt_buero", "temperature")
    ha.dienst("input_boolean.turn_on", entity_id="input_boolean.f_buero_1")
    time.sleep(6)
    a = ha.s("climate.bt_neu")
    ha.dienst("input_boolean.turn_off", entity_id="input_boolean.f_buero_1")
    ha.dienst("input_boolean.turn_on", entity_id="input_boolean.f_neu_1")
    pruefe(a == "heat" and ha.warte(lambda: ha.s("climate.bt_neu") == "off", 20), "Alter Fensterkontakt wirkungslos, neuer pausiert die Heizung")
    ha.dienst("input_boolean.turn_off", entity_id="input_boolean.f_neu_1")
    pruefe(ha.befehl("lovelace/config", url_path="test-ipad") == vorher and ha.helfer("buro") == helfer_vorher and ha.attr("climate.bt_buero", "temperature") == alt_soll,
           "Dashboard-Karte und Helfer unverändert; das alte Thermostat erhält keine Befehle mehr")

    # ------------------------------------------------------------------ R. Klima-Messsteckdose: dauerhaft an, Strom vor jedem IR-Befehl, Rückmeldung
    titel("R. Klima-Messsteckdose im Wohnzimmer: dauerhaft eingeschaltet, Strom vor jedem IR-Befehl, Rückmeldung über die Leistung")

    def gs():
        return ha.attr("remote.broadlink_wohnzimmer", "gesendet") or []

    def watt():
        try:
            return float(ha.s("sensor.klima_steckdose_wohnzimmer_leistung"))
        except (TypeError, ValueError):
            return -1.0

    def meld():
        return [m["notification_id"] for m in ha.befehl("persistent_notification/get")]

    def modus(m):
        ha.dienst("input_select.select_option", entity_id="input_select.hz_wohnzimmer_klima_modus", option=m)

    steckdose, mid = "switch.klima_steckdose_wohnzimmer", "hz_klima_rueckmeldung_wohnzimmer"
    # Konfigurieren → „Klima-Steckdose einrichten oder ändern“ (1.10.1): entfernen und wieder eintragen, in Klimaautomatik und PV gemeinsam
    eintrag_wz = ha.eintrag("Wohnzimmer")["entry_id"]
    menues = {}
    for name, eid_ in (("Wohnzimmer", eintrag_wz), ("Büro", ha.eintrag("Büro")["entry_id"])):
        ha.ablauf({"init": lambda sch, n=name: menues.setdefault(n, sch.get("menu_options")) and None}, optionen_fuer=eid_)
    pruefe("steckdose" in (menues.get("Wohnzimmer") or []) and "steckdose" not in (menues.get("Büro") or []),
           "Menüpunkt „Klima-Steckdose einrichten oder ändern“ nur bei Räumen mit IR-Klimaanlage", str(menues))

    def eintrag_a(titel_):  # gespeicherte Raumdaten (die REST-Liste der Einträge enthält keine Daten)
        try:
            eintr = json.loads((log.parent / ".storage" / "core.config_entries").read_text(encoding="utf-8"))["data"]["entries"]
            return next(e["data"]["a"] for e in eintr if e["domain"] == "heizung_universal" and e["title"] == titel_)
        except (OSError, StopIteration, KeyError, ValueError):
            return {}

    def strom_inp():
        return [{k: ha.auto_cfg(a_)["use_blueprint"]["input"].get(k) for k in ("klima_steckdose", "klima_leistung", "laeuft_ab_w")}
                for a_ in ("hz_wohnzimmer_klima", "hz_wohnzimmer_pv")]
    r = ha.ablauf({"init": {"next_step_id": "steckdose"}, "steckdose": {"laeuft_ab_w": 15}}, optionen_fuer=eintrag_wz)
    time.sleep(2)
    pruefe(r.get("reason") == "steckdose_fertig" and strom_inp() == [{"klima_steckdose": None, "klima_leistung": None, "laeuft_ab_w": None}] * 2
           and "entfernt" in (r.get("description_placeholders") or {}).get("stand", "") and ha.warte(lambda: eintrag_a("Wohnzimmer").get("klima_steckdose") == "", 15)
           and ha.s("automation.klima_wohnzimmer") == "on" and ha.s("automation.pv_heizen_wohnzimmer") == "on",
           "Steckdose über das Menü entfernt: aus Klimaautomatik und PV-Heizen ausgetragen, beide laufen weiter", str(strom_inp()))
    r = ha.ablauf({"init": {"next_step_id": "steckdose"}, "steckdose": {"klima_steckdose": steckdose, "laeuft_ab_w": 15}}, optionen_fuer=eintrag_wz)
    time.sleep(2)
    erwartet = {"klima_steckdose": steckdose, "klima_leistung": "sensor.klima_steckdose_wohnzimmer_leistung", "laeuft_ab_w": 15}
    pruefe(r.get("reason") == "steckdose_fertig" and strom_inp() == [erwartet] * 2 and len((r.get("description_placeholders") or {}).get("liste", "").splitlines()) == 2
           and ha.warte(lambda: eintrag_a("Wohnzimmer").get("klima_leistung") == erwartet["klima_leistung"], 15)
           and ha.s("automation.klima_wohnzimmer") == "on" and ha.s("automation.pv_heizen_wohnzimmer") == "on",
           "Steckdose über das Menü nachgerüstet: in beiden Automationen eingetragen, Leistungsmessung automatisch ergänzt",
           str(strom_inp()) + " " + str(r.get("description_placeholders")))
    ha.auto_aendern("hz_wohnzimmer_klima", vorlauf_s=5, pruef_ein_min=1, pruef_aus_min=1)
    ha.auto_aendern("hz_wohnzimmer_pv", vorlauf_s=5, pruef_aus_min=1)
    for f in ("input_boolean.f_wohnzimmer_1", "input_boolean.f_wohnzimmer_2"):
        ha.dienst("input_boolean.turn_off", entity_id=f)
    ha.dienst("input_select.select_option", entity_id="input_select.hz_wohnzimmer_heizprofil", option="Sommer")
    ha.dienst("input_number.set_value", entity_id="input_number.t_aussen", value=26)
    ha.dienst("input_number.set_value", entity_id="input_number.t_wohnzimmer", value=24.5)
    ha.dienst("switch.turn_on", entity_id=steckdose)
    modus("Aus")
    ha.warte(lambda: ha.s("input_boolean.hz_wohnzimmer_klima_aktiv") == "off", 30)
    ha.dienst("hz_testgeraete.klima_laufen", an=False)
    pruefe(ha.warte(lambda: ha.s(steckdose) == "on" and 0 < watt() < 15, 20), "Ausgangslage: Klima-Modus Aus, Steckdose an, Bereitschaft 1 W", f"{ha.s(steckdose)} {watt()} W")

    n = len(gs())
    ha.dienst("switch.turn_off", entity_id=steckdose)
    pruefe(ha.warte(lambda: ha.s(steckdose) == "on" and gs()[n:] == ["power_off"], 110),
           "Steckdose ausgeschaltet: nach 1 Minute wieder eingeschaltet, danach sicherheitshalber „Aus“ gesendet (dauerhaft eingeschaltet halten)",
           f"{ha.s(steckdose)} {gs()[n:]}")

    ha.dienst("switch.turn_off", entity_id=steckdose)
    time.sleep(1)
    n = len(gs())
    modus("Automatik Kühlen")
    ok = ha.warte(lambda: gs()[n:] == ["power_17", "eco_17"] and ha.s("input_boolean.hz_wohnzimmer_klima_aktiv") == "on", 45)
    pruefe(ok and ha.s(steckdose) == "on" and watt() >= 400,
           "Steckdose war aus: vor dem Kühlbefehl eingeschaltet, kurze Wartezeit, dann power_17 + eco_17 – die Klimaanlage läuft (450 W)",
           f"{gs()[n:]} {ha.s(steckdose)} {watt()} W")

    modus("Aus")
    ha.warte(lambda: ha.s("input_boolean.hz_wohnzimmer_klima_aktiv") == "off" and watt() < 15, 30)
    ha.dienst("hz_testgeraete.klima_taub", anzahl=2)
    n = len(gs())
    modus("Automatik Kühlen")
    ha.warte(lambda: gs()[n:] == ["power_17", "eco_17"] and ha.s("input_boolean.hz_wohnzimmer_klima_aktiv") == "on", 30)
    pruefe(watt() < 15 and ha.s("input_boolean.hz_wohnzimmer_klima_aktiv") == "on",
           "Test „Sichtverbindung gestört“: Kühlbefehl gesendet, die Klimaanlage nimmt aber nur 1 W auf", f"{watt()} W")
    pruefe(ha.warte(lambda: gs()[n:] == ["power_17", "eco_17", "power_17", "eco_17"] and watt() >= 400, 100),
           "Rückmeldung nach der Prüfzeit (1 min): Kühlbefehl einmal wiederholt – die Klimaanlage läuft (450 W)", f"{gs()[n:]} {watt()} W")
    time.sleep(65)
    pruefe(mid not in meld() and gs()[n:] == ["power_17", "eco_17", "power_17", "eco_17"],
           "Zweite Prüfung (doppelte Prüfzeit): Klimaanlage läuft – keine Meldung, kein weiterer Befehl", str(meld()))

    modus("Aus")
    ha.warte(lambda: ha.s("input_boolean.hz_wohnzimmer_klima_aktiv") == "off" and watt() < 15, 30)
    ha.dienst("hz_testgeraete.klima_taub", anzahl=99)
    n = len(gs())
    modus("Automatik Kühlen")
    ok = ha.warte(lambda: mid in meld(), 170)
    pruefe(ok and gs()[n:] == ["power_17", "eco_17", "power_17", "eco_17"] and watt() < 15,
           "Klimaanlage reagiert auch auf die Wiederholung nicht: nach der doppelten Prüfzeit dauerhafte Meldung, keine weiteren Sendeversuche",
           f"{gs()[n:]} {meld()}")
    ha.dienst("hz_testgeraete.klima_taub", anzahl=0)

    modus("Aus")
    ha.warte(lambda: ha.s("input_boolean.hz_wohnzimmer_klima_aktiv") == "off", 30)
    m0 = len(gs())
    modus("Automatik Kühlen")
    ha.warte(lambda: gs()[m0:] == ["power_17", "eco_17"] and ha.s("input_boolean.hz_wohnzimmer_klima_aktiv") == "on" and watt() >= 400, 30)
    ha.dienst("hz_testgeraete.klima_taub", anzahl=1)
    n = len(gs())
    modus("Aus")
    ha.warte(lambda: gs()[n:] == ["power_off"], 30)
    pruefe(watt() >= 400, "Test: Die Klimaanlage überhört „Aus“ und läuft mit 450 W weiter", f"{watt()} W")
    pruefe(ha.warte(lambda: gs()[n:] == ["power_off", "power_off"] and watt() < 15, 100),
           "Rückmeldung nach der Prüfzeit: „Aus“ einmal wiederholt – die Klimaanlage ist aus (1 W)", f"{gs()[n:]} {watt()} W")
    pruefe(ha.warte(lambda: mid not in meld(), 90),
           "Zweite Prüfung in Ordnung: die frühere Meldung „reagiert nicht“ wird automatisch entfernt", str(meld()))

    # PV-Heizen mit ausgeschalteter Steckdose und Rückmeldung nach HEIZEN-AUS (Wächter der Klimaautomatik dafür kurz aus, damit nichts dazwischenfunkt)
    ha.auto_aendern("hz_wohnzimmer_klima", steckdose_halten=False)
    ha.dienst("input_select.select_option", entity_id="input_select.hz_wohnzimmer_heizprofil", option="Komfort")
    ha.dienst("input_number.set_value", entity_id="input_number.t_aussen", value=8)
    ha.dienst("input_number.set_value", entity_id="input_number.t_wohnzimmer", value=21)
    for tm in ("timer.hz_wohnzimmer_pv_wiederanlaufsperre", "timer.hz_wohnzimmer_pv_schaltpause"):
        ha.dienst("timer.cancel", entity_id=tm)
    for eid, wert in (("input_number.e_soc", 97), ("input_number.e_netz", 1600), ("input_number.e_akku", 1), ("input_number.e_pvl", 3100), ("input_number.e_last", 600)):
        ha.dienst("input_number.set_value", entity_id=eid, value=wert)
    ha.dienst("input_boolean.turn_off", entity_id="input_boolean.hz_wohnzimmer_pv_ir_fehler")
    ha.dienst("input_boolean.turn_on", entity_id="input_boolean.hz_wohnzimmer_pv_ir_geprueft")
    ha.dienst("switch.turn_off", entity_id=steckdose)
    n = len(gs())
    ha.dienst("input_boolean.turn_on", entity_id="input_boolean.hz_wohnzimmer_pv_heizfreigabe")
    ha.warte(lambda: ha.s("climate.bt_wohnzimmer") == "off", 150)
    ha.dienst("climate.set_temperature", entity_id="climate.trv_wohnzimmer", temperature=5)
    ok = ha.warte(lambda: "heizen_24" in gs()[n:], 120)
    pruefe(ok and ha.s(steckdose) == "on" and ha.warte(lambda: watt() >= 400, 15),
           "PV-Heizen bei ausgeschalteter Steckdose: Steckdose vor HEIZEN eingeschaltet, dann heizen_24 – die Klimaanlage heizt (450 W)",
           f"{gs()[n:]} {ha.s(steckdose)} {watt()} W · PV {ha.s('input_text.hz_wohnzimmer_pv_status')}")
    ha.dienst("hz_testgeraete.klima_taub", anzahl=1)
    n = len(gs())
    ha.dienst("input_boolean.turn_off", entity_id="input_boolean.hz_wohnzimmer_pv_heizfreigabe")
    ha.warte(lambda: gs()[n:] == ["heizen_24_off"], 40)
    pruefe(watt() >= 400, "Test: Die Klimaanlage überhört HEIZEN-AUS und heizt weiter", f"{gs()[n:]} {watt()} W")
    pruefe(ha.warte(lambda: gs()[n:] == ["heizen_24_off", "heizen_24_off"] and watt() < 15, 100) and ha.s("input_boolean.hz_wohnzimmer_pv_ir_fehler") == "off",
           "PV-Rückmeldung nach der Prüfzeit: HEIZEN-AUS einmal wiederholt – die Klimaanlage ist aus, kein IR-Fehler",
           f"{gs()[n:]} {watt()} W · IR-Fehler {ha.s('input_boolean.hz_wohnzimmer_pv_ir_fehler')}")
    ha.auto_aendern("hz_wohnzimmer_klima", steckdose_halten=True)
    ha.dienst("hz_testgeraete.klima_taub", anzahl=0)

    # ------------------------------------------------------------------ G. Karte versetzen, Neustart
    titel("G. Karte neu platzieren, Neustart von Home Assistant")
    plz_g = []
    r = ha.ablauf({"init": {"next_step_id": "karte"}, "dashboard": {"dashboards": ["test-mobil", "test-ipad"]}, "ansicht": [{"ansicht": "0"}, {"ansicht": "0"}],
                   "platz": [lambda sch: plz_g.append(sch) or platz("Tab „Heizkessel“")(sch), platz("Neuen Abschnitt")], "position": [pos(0), pos(0)]},
                  optionen_fuer=ha.eintrag("Büro")["entry_id"])
    mob = ha.befehl("lovelace/config", url_path="test-mobil")["views"][0]["cards"][1]["tabs"]
    ipad = ha.befehl("lovelace/config", url_path="test-ipad")["views"][0]["sections"]
    mk, ik = mob[0]["card"]["cards"][0], ipad[0]["cards"][0]
    pruefe(r.get("reason") == "karte_fertig" and r["verlauf"] == ["init", "dashboard", "ansicht", "platz", "position", "ansicht", "platz", "position"],
           "„Konfigurieren → Karte neu platzieren“ mit zwei gewählten Dashboards: je Dashboard Ansicht, Bereich, Position und Design", str(r.get("verlauf")))
    labels = " | ".join(o["label"] for o in plz_g[0]["data_schema"][0]["selector"]["select"]["options"]) if plz_g else ""
    pruefe("Raumkarte Wohnzimmer" in labels and "Raumkarte Bad" in labels and "HZ " not in labels and "Status" not in labels,
           "Eigene Raumkarten heißen in der Auswahl nach ihrem Raum („Raumkarte Wohnzimmer“), nicht nach Helfern", labels[:300])
    pruefe("hz_buro_status" in json.dumps(mk) and "backdrop-filter" in mk["card_mod"]["style"] and len(mob[0]["card"]["cards"]) == 2
           and "23px 22px" in json.dumps(mk) and "mdi:desk" in json.dumps(mk),
           "Mobil-Dashboard, Tabdeck-Tab „Heizkessel“: Karte an Position 1 – auch dort im Mobil-Design (die Ansicht hat Mobil-Raumkarten)")
    pruefe(len(ipad) == 2 and "hz_buro_status" in json.dumps(ik) and "max-width: 390px" in ik["card_mod"]["style"] and len(ipad[0]["cards"]) == 1
           and len(ipad[1]["cards"]) == 3 and "hz_buro" not in json.dumps(ipad[1]),
           "iPad-Dashboard: Karte in neuem Abschnitt an erster Stelle im Farbverlauf-Design; die alte Karte ist entfernt, übrige Karten unverändert")
    ha.dienst("input_boolean.turn_on", entity_id="input_boolean.f_wohnzimmer_1")
    time.sleep(3)
    try:
        ha.dienst("homeassistant.stop")
    except Exception:  # noqa: BLE001
        pass
    ha.schliessen()
    for _ in range(40):
        if subprocess.run(["pgrep", "-f", f"hass -c {log.parent}"], capture_output=True).returncode != 0:
            break
        time.sleep(1)
    with open(log, "a") as ausgabe:
        subprocess.Popen([str(Path(sys.argv[2]) / "bin" / "hass"), "-c", str(log.parent)], stdout=ausgabe, stderr=ausgabe, start_new_session=True)
    time.sleep(10)
    ha = None
    for _ in range(60):
        try:
            ha = HA(URL, anmelden(), timeout=90)
            ha.verbinden()
            if ha.s("automation.heizung_wohnzimmer"):
                http_bestaetigen(ha)
                break
        except Exception:  # noqa: BLE001
            ha = None
        time.sleep(3)
    autos = ["automation.heizung_buro", "automation.heizung_bad", "automation.heizung_wohnzimmer", "automation.klima_wohnzimmer", "automation.pv_heizen_wohnzimmer",
             "automation.heizung_gast", "automation.klima_gast", "automation.heizung_keller"]
    pruefe(ha is not None and all(ha.warte(lambda a=a: ha.s(a) == "on", 60) for a in autos), "Nach dem Neustart laufen alle 8 Automationen wieder")
    pruefe(ha.warte(lambda: ha.s("input_boolean.hz_wohnzimmer_fensterstatus") == "on" and ha.s("climate.bt_wohnzimmer") == "off", 40),
           "Neustart bei offenem Fenster: Fensterstatus an, Heizpause besteht sofort wieder", f"{ha.s('input_boolean.hz_wohnzimmer_fensterstatus')} {ha.s('climate.bt_wohnzimmer')}")
    ha.dienst("input_boolean.turn_off", entity_id="input_boolean.f_wohnzimmer_1")
    pruefe(len([e for e in ha.rest("GET", "/api/config/config_entries/entry") if e["domain"] == "heizung_universal" and e["state"] == "loaded"]) == 5,
           "Alle fünf Raum-Einträge der Integration sind nach dem Neustart geladen")

    # ------------------------------------------------------------------ H. Raum entfernen
    titel("H. Raum Bad entfernen (Rückbau)")
    ha.rest("DELETE", f"/api/config/config_entries/entry/{ha.eintrag('Bad')['entry_id']}")
    tab = ha.befehl("lovelace/config", url_path="test-mobil")["views"][0]["cards"][1]["tabs"][1]["card"]["cards"]
    pruefe(ha.warte(lambda: ha.helfer("bad") == [] and ha.s("automation.heizung_bad") is None), "Automation und alle Helfer des Raums entfernt", str(ha.helfer("bad")))
    pruefe([kname(k) for k in tab[1:]] == ["Raum A", "Raum B"] and "hz_wohnzimmer" in json.dumps(tab[0]) and len(tab) == 3,
           "Nur die Karte dieses Raums entfernt; die übrigen Karten des Dashboards sind unverändert")
    pruefe(len([b for b in ha.befehl("blueprint/list", domain="automation") if b.startswith("ha_heizung_universal/")]) == 3
           and ha.s("automation.heizung_wohnzimmer") == "on", "Blueprints und andere Räume bleiben bestehen")

    # ------------------------------------------------------------------ J. Umstieg: alte Steuerung nach dem Muster des Wohnzimmers
    titel("J. Umstieg eines Raums mit alter Steuerung (Muster: Heizung, Boost, Klima, PV-Heizen, IR-Skripte, TV am selben Broadlink)")
    alte_steuerung_anlegen(ha)
    original = {aid: ha.auto_cfg(aid) for aid in ALT_AUTOS}
    alt_schritt, j_sender, j_klima, j_lernen, j_pv = [], [], [], [], []
    antworten = {
        "user": geraete("Schlaf"),
        "funktionen": funktionen(profile=["komfort"], zeitquelle="phasen", boost=True, klima=True, pv=True),
        "profil": [profil(22, 17, (ALLE, "00:00:00", "23:59:00"))], "werte": {"frostschutz": 5, "aussensperre": 20, "boost_dauer": 60},
        "klima_sender": lambda sch: j_sender.append(sch) or {"klima_sender": "remote.broadlink_schlafzimmer"},
        "klima": lambda sch: j_klima.append(sch) or {"ir_geraet": "klima_schlaf", "ir_pruefen": False, "befehl_kuehlen": "power_{stufe}",
                  "befehl_zusatz": "", "befehl_aus": "power_off", "stufe_min": 16, "stufe_max": 23, "luefter": ""},
        "lernen_auswahl": lambda sch: j_lernen.append(sch) or {"befehle": [], "testen": [], "ueberschreiben": False},
        "pv": lambda sch: j_pv.append(sch) or {"befehl_heizen": "heizen_24", "befehl_heizen_aus": "heizen_24_off", "heiz_stufe_min": 24, "heiz_stufe_max": 24, "pv_heizstufe": 24,
               "heiz_anlernen": "vorhanden", "pv_trvs": ["climate.trv_schlaf"], "pv_ventile": [], "soc": "sensor.energie_soc", "netz": "sensor.energie_netz",
               "akku_leistung": "sensor.energie_akku", "pv_leistung": "sensor.energie_pvl", "verbrauch": "sensor.energie_last", "zeitstempel_attribut": "",
               "start_leistung": 1000, "soc_start": 95, "soc_halten": 85, "pv_ziel": 24},
        "altsteuerung": lambda sch: alt_schritt.append(sch) or {f["name"]: f.get("default") for f in sch["data_schema"]},
        "alte_karten": lambda sch: ak_schritt.append(sch) or {"karten": [o["value"] for o in sch["data_schema"][0]["selector"]["select"]["options"]]},
    }
    ak_schritt = []

    def alte_karte():  # (Abschnitt, Index) der alten Schlafzimmer-Karte im iPad-Test-Dashboard oder None
        for si, sec in enumerate(ha.befehl("lovelace/config", url_path="test-ipad")["views"][0]["sections"]):
            for ci, c in enumerate(sec.get("cards", [])):
                if c.get("name") == "Schlaf alt":
                    return si, ci
        return None

    def ipad_text():
        return json.dumps(ha.befehl("lovelace/config", url_path="test-ipad"), ensure_ascii=False)
    ort_vorher = alte_karte()
    antw = lambda **kw: {**copy.deepcopy(antworten), **kw}  # noqa: E731  (Listen-Antworten werden je Ablauf verbraucht)
    # 1) Altes PV-Heizen läuft → Anlegen wird verweigert, nichts verändert
    ha.dienst("input_boolean.turn_on", entity_id="input_boolean.schlaf_pv_regelung_aktiv")
    ha.dienst("input_boolean.turn_on", entity_id="input_boolean.schlaf_klima_aktiv")
    r = ha.ablauf(antw(bestaetigen=[{"bestaetigt": True}, None]))
    beschr = alt_schritt[0]["description_placeholders"] if alt_schritt else {}
    pruefe(r["type"] == "abgebrochen" and ("bestaetigen", {"base": "alt_pv_laeuft"}) in r["fehlerliste"]
           and all(ha.s(f"automation.{x}") == "on" for x in ALT_NAMEN) and not ha.helfer("schlaf") and "PV-Heizen läuft gerade" in beschr.get("warnungen", ""),
           "Altes PV-Heizen läuft: Hinweis in der Auswahl, Anlegen wird verweigert, alte Steuerung unverändert, nichts angelegt", str(r.get("fehlerliste")))
    pruefe("Klimaanlage als eingeschaltet" in beschr.get("warnungen", ""), "Alte Klimasteuerung meldet die Klimaanlage an: Hinweis vor dem Umstellen")
    felder = {f["name"]: f for f in alt_schritt[0]["data_schema"]}
    erkannt = set(felder["abschalten"]["default"])
    soll = {f"automation.{x}" for x in ALT_NAMEN} | {f"script.{x}" for x in ALT_SKRIPTE}
    pruefe(erkannt == soll, "Erkannt und vorausgewählt: 6 Heizungs-, Boost-, Klima- und PV-Automationen und 3 Skripte des Raums", str(sorted(erkannt ^ soll)))
    js = {f["name"]: f.get("default") for f in j_sender[0]["data_schema"]} if j_sender else {}
    jk = {f["name"]: f.get("default") for f in j_klima[0]["data_schema"]} if j_klima else {}
    jerk = j_klima[0]["description_placeholders"].get("erkennung", "") if j_klima else ""
    pruefe(js.get("klima_sender") == "remote.broadlink_schlafzimmer" and "bisherige Klimasteuerung" in j_sender[0]["description_placeholders"].get("grund", "")
           and jk.get("ir_geraet") == "klima_schlaf" and jk.get("befehl_kuehlen") == "power_{stufe}" and jk.get("befehl_aus") == "power_off"
           and "script.schlaf_klima_20" in jerk,
           "IR-Erkennung aus alter Steuerung: Broadlink des Raums vorgeschlagen; Gerät „klima_schlaf“, power_{stufe} und power_off aus den alten Skripten/Automationen übernommen (TV am selben Sender ignoriert)",
           str(js) + " " + str({k: jk.get(k) for k in ("ir_geraet", "befehl_kuehlen", "befehl_aus")}) + " " + jerk[:200])
    jl = next((f for f in j_lernen[0]["data_schema"] if f["name"] == "befehle"), {}) if j_lernen else {}
    jpv = {f["name"]: f.get("default") for f in j_pv[0]["data_schema"]} if j_pv else {}
    pruefe("power_off" in (jl.get("default") or []) and "power_16" in (jl.get("default") or []) and jpv.get("befehl_heizen") == "heizen_{stufe}" and jpv.get("pv_heizstufe") == 24,
           "Fehlende Befehle führen automatisch zur Anlernseite (alle fehlenden vorausgewählt); PV-Heizbefehl heizen_{stufe} mit bisheriger Stufe 24 aus dem alten Skript erkannt",
           str((jl.get("default") or [])[:4]) + " " + str({k: jpv.get(k) for k in ("befehl_heizen", "pv_heizstufe")}))
    pruefe(jpv.get("pv_ventile") == ["sensor.trv_schlaf_ventil_offnungsgrad"] and jpv.get("zeitstempel_attribut") == "pv_last_update",
           "PV-Seite: Ventilsensor des Heizkörperthermostats und Zeitstempel-Attribut des Ladestand-Sensors vorausgefüllt",
           str({k: jpv.get(k) for k in ("pv_ventile", "zeitstempel_attribut")}))
    pruefe(jpv.get("pv_trvs") == ["climate.trv_schlaf"] and jpv.get("soc") == "sensor.energie_soc" and jpv.get("netz") == "sensor.energie_netz"
           and "Energiesensoren wie im Raum „Wohnzimmer“" in j_pv[0]["description_placeholders"].get("uebernahme", ""),
           "PV-Seite vorausgefüllt: Heizkörperthermostat aus der alten PV-Automation, Energiesensoren wie im bereits eingerichteten Wohnzimmer",
           str({k: jpv.get(k) for k in ("pv_trvs", "soc", "netz")}))
    pruefe(set(felder["helfer"]["default"]) == set(ALT_HELFER), "Erkannt: die 11 Helfer der alten Raumsteuerung (ohne „Alle außer Haus“, TV-Helfer, „Heizung Aus“)",
           str(sorted(set(felder["helfer"]["default"]) ^ set(ALT_HELFER))))
    pruefe("Rolladen Schlaf intelligent" in beschr.get("abhaengig", "") and "PV Benachrichtigung" in beschr.get("abhaengig", "")
           and "Heizung Aus (Test)" in beschr.get("gemeinsam", "") and "TV Küche" not in str(beschr) and "Meldung Schlafzimmer" not in str(beschr),
           "Abhängige (Rollladen, PV-Benachrichtigung) und gemeinsames „Heizung Aus“ werden gezeigt; TV-Automation am selben Broadlink und Meldung bleiben außen vor")
    # 2) PV beendet → Raum anlegen
    ha.dienst("input_boolean.turn_off", entity_id="input_boolean.schlaf_pv_regelung_aktiv")
    ha.dienst("input_boolean.turn_off", entity_id="input_boolean.schlaf_klima_aktiv")
    alt_schritt.clear()
    r = ha.ablauf(antw(bestaetigen={"bestaetigt": True}))
    pruefe(r["type"] == "create_entry", "Raum mit Heizung, Boost, Klima und PV angelegt", str(r.get("fehlerliste") or r.get("type")))
    labels = [o["label"] for o in ak_schritt[-1]["data_schema"][0]["selector"]["select"]["options"]] if ak_schritt else []
    pruefe(len(labels) == 1 and "„Schlaf alt“" in labels[0] and "iPad Test" in labels[0] and ak_schritt[-1]["data_schema"][0].get("default") == [],
           "Schritt „Alte Dashboard-Karten“: nur die alte Steuerkarte gefunden (nicht die Sammelkarte mit dem Keller, nicht die reine Thermostat-Anzeige); nichts vorausgewählt",
           str(labels))
    t = ipad_text()
    pruefe(alte_karte() is None and "Alle Thermostate" in t and '"type": "thermostat"' in t,
           "Gewählte alte Karte beim Anlegen entfernt; Sammelkarte und Thermostat-Anzeige bleiben")
    time.sleep(3)
    pruefe(all(ha.s(f"automation.{x}") == "off" and ha.auto_cfg(ALT_AUTOS[i])["alias"].endswith(" (alt)") for i, x in enumerate(ALT_NAMEN)),
           "Alte Automationen ausgeschaltet und mit „(alt)“ gekennzeichnet (Entitäts-IDs unverändert)")
    pruefe(all(ha.s(f"script.{x}") is None and ha.rest("GET", f"/api/config/script/config/{x}")["alias"].endswith(" (alt)") for x in ALT_SKRIPTE),
           "Alte Skripte deaktiviert (nicht mehr aufrufbar) und mit „(alt)“ gekennzeichnet")
    pruefe(all((ha.attr(h, "friendly_name") or "").endswith(" (alt)") for h in ALT_HELFER), "Alte Helfer tragen „(alt)“ im Namen",
           str([h for h in ALT_HELFER if not (ha.attr(h, "friendly_name") or "").endswith(" (alt)")]))
    pruefe(all(ha.s(f"automation.{x}") == "on" for x in ("tv_kuche_tagessteuerung", "rolladen_schlaf_intelligent", "meldung_schlafzimmer", "pv_benachrichtigung"))
           and ha.s("script.heizung_aus_test") == "off" and ha.attr("input_boolean.alle_ausser_haus", "friendly_name") == "Alle ausser Haus",
           "TV-Automation, Rollladen, Meldung, PV-Benachrichtigung, „Heizung Aus“ und globale Helfer bleiben an und unverändert")
    roll = json.dumps(ha.auto_cfg("alt_rollladen")); pva = json.dumps(ha.auto_cfg("alt_pv_assistent"))
    pruefe("input_select.hz_schlaf_klima_modus" in roll and "input_boolean.hz_schlaf_klima_aktiv" in roll
           and "input_select.schlaf_klima_modus" not in roll and "input_boolean.schlaf_klima_aktiv" not in roll
           and "input_number.hz_schlaf_klima_ziel" in pva and "input_boolean.alle_ausser_haus" in roll,
           "Rollladen und PV-Assistent verwenden jetzt die neuen Klima-Helfer (übrige Verweise unverändert)")
    neu_autos = ("automation.heizung_schlaf", "automation.klima_schlaf", "automation.pv_heizen_schlaf")
    inp = ha.auto_cfg("hz_schlaf_raumheizung")["use_blueprint"]["input"]
    pruefe(inp.get("ausgabe_modus") == "produktiv" and all(ha.warte(lambda a=a: ha.s(a) == "on") for a in neu_autos)
           and ha.warte(lambda: ha.attr("climate.bt_schlaf", "temperature") == 22),
           "Neue Steuerung startet sofort im Normalbetrieb und stellt das Thermostat (22 °C)", str(inp.get("ausgabe_modus")))
    eintrag = ha.eintrag("Schlaf")["entry_id"]
    # 3) Alte Steuerung wieder einschalten
    r = ha.ablauf({"init": {"next_step_id": "alt_zurueck"}, "alt_zurueck": {"bestaetigt": True}}, optionen_fuer=eintrag)
    time.sleep(4)
    pruefe(r.get("reason") == "alt_zurueck_fertig" and all(ha.auto_cfg(a) == original[a] for a in ALT_AUTOS)
           and all(ha.s(f"automation.{x}") == "on" for x in ALT_NAMEN) and all(ha.s(f"script.{x}") == "off" for x in ALT_SKRIPTE)
           and not any((ha.attr(h, "friendly_name") or "").endswith(" (alt)") for h in ALT_HELFER) and ha.auto_cfg("alt_rollladen") == ROLL_ORIGINAL[0]
           and all(ha.s(a) == "off" for a in neu_autos),
           "„Alte Steuerung wieder einschalten“: alles exakt wie vorher (Namen, Skripte, Rollladen im Original), neue Steuerung angehalten", str(r.get("reason")))
    pruefe(alte_karte() == ort_vorher, "… und die alte Dashboard-Karte steht wieder an ihrer Stelle", f"{alte_karte()} statt {ort_vorher}")
    # 4) Neue Steuerung wieder übernehmen
    r = ha.ablauf({"init": {"next_step_id": "alt_neu"}, "alt_neu": {"bestaetigt": True}}, optionen_fuer=eintrag)
    time.sleep(3)
    pruefe(r.get("reason") == "alt_neu_fertig" and all(ha.s(f"automation.{x}") == "off" for x in ALT_NAMEN) and all(ha.s(f"script.{x}") is None for x in ALT_SKRIPTE)
           and all(ha.s(a) == "on" for a in neu_autos) and "hz_schlaf_klima_modus" in json.dumps(ha.auto_cfg("alt_rollladen")),
           "„Neue Steuerung wieder übernehmen“: alte erneut abgeschaltet, Rollladen wieder umgestellt, neue Steuerung an")
    r = ha.ablauf({"init": {"next_step_id": "alte_karten"},
                   "alte_karten": lambda sch: {"karten": [o["value"] for o in sch["data_schema"][0]["selector"]["select"]["options"] if "Schlaf alt" in o["label"]]}},
                  optionen_fuer=eintrag)
    pruefe(r.get("reason") == "alte_karten_fertig" and alte_karte() is None and "Alle Thermostate" in ipad_text(),
           "„Konfigurieren → Alte Dashboard-Karten entfernen“: alte Karte entfernt, andere Karten unverändert", str(r.get("reason")))
    # 5) Raum entfernen → alte Steuerung übernimmt automatisch wieder
    ha.rest("DELETE", f"/api/config/config_entries/entry/{eintrag}")
    time.sleep(5)
    pruefe(ha.s("automation.heizung_schlaf") is None and all(ha.s(f"automation.{x}") == "on" for x in ALT_NAMEN)
           and all(ha.s(f"script.{x}") == "off" for x in ALT_SKRIPTE) and ha.auto_cfg("alt_rollladen") == ROLL_ORIGINAL[0],
           "Raum entfernt: neue Steuerung weg, alte Steuerung automatisch wieder eingeschaltet und im Original")
    pruefe(alte_karte() == ort_vorher, "… auch die alte Dashboard-Karte ist wieder da", str(alte_karte()))
    # 6) Erneut anlegen und nach der „Testwoche“ die alte Steuerung endgültig löschen
    r = ha.ablauf(antw(bestaetigen={"bestaetigt": True}, alte_karten={"karten": []}))
    eintrag = ha.eintrag("Schlaf")["entry_id"]
    pruefe(alte_karte() == ort_vorher, "Neu angelegt ohne Auswahl im Schritt „Alte Dashboard-Karten“: die alte Karte bleibt")
    loesch = []
    r2 = ha.ablauf({"init": {"next_step_id": "alt_loeschen"},
                    "alt_loeschen": lambda sch: loesch.append(sch) or {"helfer": next(f for f in sch["data_schema"] if f["name"] == "helfer").get("default"), "bestaetigt": True}},
                   optionen_fuer=eintrag)
    time.sleep(3)
    vorschlag = set(next(f for f in loesch[0]["data_schema"] if f["name"] == "helfer").get("default")) if loesch else set()
    geloescht_auto = all(_fehlt(ha, f"/api/config/automation/config/{a}") for a in ALT_AUTOS)
    geloescht_skript = all(_fehlt(ha, f"/api/config/script/config/{x}") for x in ALT_SKRIPTE)
    pruefe(r["type"] == "create_entry" and r2.get("reason") == "alt_geloescht" and geloescht_auto and geloescht_skript,
           "„Alte Steuerung endgültig löschen“: alte Automationen und Skripte gelöscht", str(r2.get("reason")))
    pruefe("input_select.schlaf_heizprofil" not in vorschlag and all(ha.s(h) is None for h in vorschlag) and ha.s("input_select.schlaf_heizprofil") is not None,
           "Helfer, die noch verwendet werden (Profil-Helfer im gemeinsamen „Heizung Aus“), werden nicht vorgeschlagen und bleiben; die übrigen sind gelöscht",
           str(sorted(vorschlag)))
    sicherungen = list((log.parent / "heizung_universal" / "schlaf").glob("altsteuerung_geloescht_*.json")) if log else []
    pruefe(sicherungen and len(json.loads(sicherungen[0].read_text())["automationen"]) == 6
           and ha.s("automation.rolladen_schlaf_intelligent") == "on" and ha.s("script.heizung_aus_test") == "off",
           "Sicherung der gelöschten Konfiguration liegt vor; Rollladen und „Heizung Aus“ bestehen weiter")

    # ------------------------------------------------------------------ K. Zurück aus der Zusammenfassung, Funktionen nachträglich ändern
    titel("K. „Etwas ändern“ in der Zusammenfassung und „Funktionen ändern“ unter Konfigurieren")
    fk, wk, bk, pk = [], [], [], []
    r = ha.ablauf({
        "user": geraete("Probe") | {"bt": "climate.trv_buero", "raumfuehler": "sensor.temperatur_buero"},
        "funktionen": [funktionen(profile=["komfort"], zeitquelle="phasen"),
                       lambda sch: fk.append(sch) or funktionen(profile=["komfort"], zeitquelle="phasen", boost=True)],
        "profil": [profil(21, 16, (ALLE, "06:00:00", "08:00:00")), lambda sch: pk.append(sch) or profil(21, 16, (ALLE, "06:00:00", "08:00:00"))],
        "werte": [{"frostschutz": 6, "aussensperre": 19}, lambda sch: wk.append(sch) or {"frostschutz": 6, "aussensperre": 19, "boost_dauer": 90}],
        "altsteuerung": lambda sch: {f["name"]: f.get("default") for f in sch["data_schema"]},
        "bestaetigen": [{"bestaetigt": False, "aendern": "funktionen"}, lambda sch: bk.append(sch) or {"bestaetigt": False, "aendern": "profil"}, None]})
    vg = lambda sch, name: next((f.get("default") for f in sch["data_schema"] if f["name"] == name), "fehlt")  # noqa: E731
    pruefe(r["type"] == "abgebrochen" and r["verlauf"] == ["user", "funktionen", "profil", "werte", "bestaetigen", "funktionen", "werte", "bestaetigen", "profil", "bestaetigen"],
           "„Etwas ändern → Funktionen“: Boost ergänzt – gefragt wird nur nach der Boost-Dauer (Profil wird nicht erneut abgefragt)", str(r.get("verlauf")))
    pruefe(fk and vg(fk[0], "profile") == ["komfort"] and vg(fk[0], "zeitquelle") == "phasen" and vg(fk[0], "boost") is False and vg(fk[0], "karte") is False
           and wk and vg(wk[0], "frostschutz") == 6 and vg(wk[0], "aussensperre") == 19 and vg(wk[0], "boost_dauer") == 120,
           "Beim Zurückgehen sind die bisherigen Eingaben vorausgefüllt (Funktionen, Grundwerte)")
    abschnitt = next((f for f in (pk[0]["data_schema"] if pk else []) if f["name"] == "montag_bis_freitag"), {})
    felder_mf = {f["name"]: f.get("default") for f in abschnitt.get("schema", [])}
    pruefe(pk and vg(pk[0], "soll") == 21 and vg(pk[0], "absenk") == 16 and felder_mf.get("heizphase_1_beginn") == "06:00:00"
           and felder_mf.get("heizphase_1_verwenden") is True and felder_mf.get("heizphase_2_verwenden") is False,
           "„Etwas ändern → Heizzeiten“: Temperaturen und Heizphasen wie eingegeben vorausgefüllt", str(felder_mf)[:200])
    pruefe(bk and "HZ Probe Boost" in bk[0]["description_placeholders"]["helfer"] and not ha.helfer("probe"),
           "Zusammenfassung zeigt danach den Boost; abgebrochen – nichts angelegt")
    # Zurück-Schalter auf jeder Seite: vorwärts, zweimal zurück (einmal mit leerem Pflichtfeld), wieder vorwärts
    z = {"user": [], "fk": [], "p": []}
    r = ha.ablauf({
        "user": lambda sch: z["user"].append(sch) or (geraete("Probe2") | {"bt": "climate.trv_buero", "raumfuehler": "sensor.temperatur_buero"}),
        "funktionen": lambda sch: z["fk"].append(sch) or funktionen(profile=["komfort", "uebergang"], zeitquelle="phasen", fenster_modus="eigen"),
        "profil": [profil(21, 16, (ALLE, "06:00:00", "08:00:00")),
                   lambda sch: z["p"].append(sch) or dict(profil(19, 15, (ALLE, "07:00:00", "09:00:00")), zurueck=True),
                   lambda sch: z["p"].append(sch) or profil(21, 16, (ALLE, "06:00:00", "08:00:00")),
                   profil(19, 15, (ALLE, "07:00:00", "09:00:00")),
                   lambda sch: z["p"].append(sch) or profil(19, 15, (ALLE, "07:00:00", "09:00:00"))],
        "fenster": [{"zurueck": True}, {"fensterkontakte": ["binary_sensor.fenster_buero_1"]}],
        "werte": {"frostschutz": 5, "aussensperre": 20},
        "altsteuerung": lambda sch: {f["name"]: f.get("default") for f in sch["data_schema"]},
        "bestaetigen": None})
    namen_von = lambda sch: [f["name"] for f in sch["data_schema"]]  # noqa: E731
    pruefe(r["type"] == "abgebrochen" and r["verlauf"] == ["user", "funktionen", "profil", "profil", "profil", "profil", "fenster", "profil", "fenster", "werte", "bestaetigen"]
           and not r["fehlerliste"],
           "Zurück-Schalter: von „Übergang“ zurück zu „Komfort“ und vom Fenster (Pflichtfeld leer) zurück zu „Übergang“, danach normal weiter", str(r.get("verlauf")))
    mf = lambda sch: {f["name"]: f.get("default") for f in next(x for x in sch["data_schema"] if x["name"] == "montag_bis_freitag")["schema"]}  # noqa: E731
    pruefe(z["user"] and "zurueck" not in namen_von(z["user"][0]) and z["fk"] and "zurueck" in namen_von(z["fk"][0])
           and len(z["p"]) == 3 and "zurueck" in namen_von(z["p"][0]),
           "Der Schalter „Zurück“ erscheint ab der zweiten Seite (nicht auf der ersten)")
    pruefe(len(z["p"]) == 3 and vg(z["p"][1], "soll") == 21 and mf(z["p"][1]).get("heizphase_1_beginn") == "06:00:00"
           and vg(z["p"][2], "soll") == 19 and mf(z["p"][2]).get("heizphase_1_beginn") == "07:00:00" and not ha.helfer("probe2"),
           "Nach „Zurück“ sind die vorherigen Eingaben vorausgefüllt (Komfort 21 °C ab 06:00, Übergang 19 °C ab 07:00); abgebrochen – nichts angelegt")
    # Funktionen ändern (Büro: Thermostat, Raumfühler und Fensterkontakt wurden in F in der Blueprint getauscht, Zeitplan in A bearbeitet)
    eintrag = ha.eintrag("Büro")["entry_id"]
    vorher_inp = ha.auto_cfg("hz_buero_raumheizung")["use_blueprint"]["input"]
    zp_vorher = next(x for x in ha.befehl("schedule/list") if x["id"] == "hz_buro_zeitplan_komfort")
    fk2, ak = [], []
    r = ha.ablauf({"init": {"next_step_id": "funktionen"},
                   "funktionen": lambda sch: fk2.append(sch) or {"profile": ["komfort", "uebergang", "urlaub"], "sommer_heizen": False, "fenster_modus": "eigen",
                                                                 "boost": True, "vorheizen": False, "mindest": False, "zieltermin": False, "klima": False, "pv": False},
                   "profil": profil(18, 14, (ALLE, "10:00:00", "12:00:00")),
                   "werte": {"frostschutz": 5, "aussensperre": 20, "boost_dauer": 45},
                   "aendern_bestaetigen": lambda sch: ak.append(sch) or {"bestaetigt": True}}, optionen_fuer=eintrag)
    time.sleep(3)
    inp = ha.auto_cfg("hz_buero_raumheizung")["use_blueprint"]["input"]
    pruefe(r.get("reason") == "funktionen_fertig" and r["verlauf"] == ["init", "funktionen", "profil", "werte", "aendern_bestaetigen"]
           and fk2 and vg(fk2[0], "profile") == ["komfort", "uebergang"] and vg(fk2[0], "fenster_modus") == "eigen"
           and vg(fk2[0], "zeitquelle") == "fehlt" and vg(fk2[0], "karte") == "fehlt",
           "„Konfigurieren → Funktionen ändern“: bisherige Funktionen vorausgewählt; gefragt wird nur nach dem neuen Profil Urlaub und der Boost-Dauer",
           str(r.get("reason")) + " " + str(r.get("verlauf")))
    pruefe(ak and "HZ Büro Boost" in ak[0]["description_placeholders"]["aenderungen"] and "Heizung Büro" in ak[0]["description_placeholders"]["aenderungen"],
           "Bestätigung listet neue Helfer und angepasste Automation")
    pruefe(ha.s("input_number.hz_buro_boost") is not None and ha.attr("timer.hz_buro_boost_timer", "duration") == "0:45:00"
           and ha.s("schedule.hz_buro_zeitplan_urlaub") is not None and "Urlaub" in (ha.attr("input_select.hz_buro_heizprofil", "options") or []),
           "Boost-Helfer (45 min), Zeitplan Urlaub angelegt; Heizprofil-Auswahl um Urlaub ergänzt", str(ha.attr("timer.hz_buro_boost_timer", "duration")))
    gleich = {k: (vorher_inp.get(k), inp.get(k)) for k in ("better_thermostat", "raumfuehler", "fensterkontakte", "fenster_verzoegerung", "fenster_nachlauf",
                                                           "komfort_soll", "komfort_zeitplan", "ausgabe_modus") if vorher_inp.get(k) != inp.get(k)}
    zp_nachher = next(x for x in ha.befehl("schedule/list") if x["id"] == "hz_buro_zeitplan_komfort")
    pruefe(inp.get("boost_aktiv") is True and inp.get("boost_timer") == "timer.hz_buro_boost_timer" and inp.get("urlaub_soll") == 18
           and inp.get("better_thermostat") == "climate.bt_neu" and not gleich and zp_vorher == zp_nachher,
           "Automation ergänzt (Boost, Urlaub) – eigene Änderungen bleiben: getauschtes Thermostat, Raumfühler, Fensterkontakt, Fenster-Verzögerung, bearbeiteter Zeitplan",
           str(gleich)[:300])
    mob = json.dumps(ha.befehl("lovelace/config", url_path="test-mobil")); ipd = json.dumps(ha.befehl("lovelace/config", url_path="test-ipad"))
    pruefe("hz_buro_boost" in mob and "hz_buro_boost" in ipd and mob.count("hz_buro_status") >= 1 and "max-width: 390px" in ipd,
           "Raumkarten an ihrer Stelle erneuert (mit Boost) – im jeweiligen Design (Mobil bzw. iPad)")
    # wieder entfernen
    r = ha.ablauf({"init": {"next_step_id": "funktionen"},
                   "funktionen": {"profile": ["komfort", "uebergang"], "sommer_heizen": False, "fenster_modus": "eigen", "boost": False,
                                  "vorheizen": False, "mindest": False, "zieltermin": False, "klima": False, "pv": False},
                   "aendern_bestaetigen": {"bestaetigt": True}}, optionen_fuer=eintrag)
    time.sleep(3)
    inp = ha.auto_cfg("hz_buero_raumheizung")["use_blueprint"]["input"]
    mob = json.dumps(ha.befehl("lovelace/config", url_path="test-mobil"))
    pruefe(r.get("reason") == "funktionen_fertig" and r["verlauf"] == ["init", "funktionen", "aendern_bestaetigen"]
           and ha.s("input_number.hz_buro_boost") is None and ha.s("timer.hz_buro_boost_timer") is None and ha.s("schedule.hz_buro_zeitplan_urlaub") is None
           and "Urlaub" not in (ha.attr("input_select.hz_buro_heizprofil", "options") or []) and "boost_aktiv" not in inp and "urlaub_soll" not in inp
           and inp.get("better_thermostat") == "climate.bt_neu" and "hz_buro_boost" not in mob and ha.s("automation.heizung_buro") == "on",
           "Boost und Urlaub wieder abgewählt: Helfer gelöscht, Automation und Karten bereinigt, Thermostat-Tausch bleibt", str(r.get("reason")))
    r = ha.ablauf({"init": {"next_step_id": "funktionen"},
                   "funktionen": {"profile": ["komfort", "uebergang"], "sommer_heizen": False, "fenster_modus": "eigen", "boost": False,
                                  "vorheizen": False, "mindest": False, "zieltermin": False, "klima": False, "pv": False}}, optionen_fuer=eintrag)
    pruefe(r.get("reason") == "nichts_geaendert", "Nichts geändert → nichts zu tun", str(r.get("reason")))

    # Klimaanlage nachrüsten und wieder entfernen (neue Automation, IR-Konfiguration; es wird nichts gesendet)
    eintrag_k = ha.eintrag("Keller")["entry_id"]
    gesendet = len(ha.attr("remote.broadlink_wohnzimmer", "gesendet") or [])
    betrieb = ha.auto_cfg("hz_keller_raumheizung")["use_blueprint"]["input"].get("ausgabe_modus")
    r = ha.ablauf({"init": {"next_step_id": "funktionen"},
                   "funktionen": lambda sch: {f["name"]: f.get("default") for f in sch["data_schema"]} | {"klima": True},
                   "klima_sender": {"klima_sender": "remote.broadlink_wohnzimmer"},
                   "klima": {"ir_geraet": "klima_keller", "ir_pruefen": False, "befehl_kuehlen": "power_{stufe}",
                             "befehl_zusatz": "", "befehl_aus": "power_off", "stufe_min": 16, "stufe_max": 23, "luefter": ""},
                   "lernen_auswahl": {"befehle": [], "testen": [], "ueberschreiben": False},
                   "aendern_bestaetigen": {"bestaetigt": True}}, optionen_fuer=eintrag_k)
    time.sleep(3)
    kl = ha.auto_cfg("hz_keller_klima") if ha.s("automation.klima_keller") else {}
    pruefe(r.get("reason") == "funktionen_fertig" and r["verlauf"] == ["init", "funktionen", "klima_sender", "klima", "lernen_auswahl", "aendern_bestaetigen"]
           and ha.s("automation.klima_keller") == "on" and ha.s("input_select.hz_keller_klima_modus") == "Aus"
           and (kl.get("use_blueprint") or {}).get("input", {}).get("ausgabe_modus") == betrieb
           and ha.warte(lambda: "s=remote.broadlink_wohnzimmer|g=klima_keller" in (ha.s("input_text.hz_keller_klima_ir") or ""))
           and len(ha.attr("remote.broadlink_wohnzimmer", "gesendet") or []) == gesendet,
           "Klimaanlage nachgerüstet: Klimaautomatik und Klima-Helfer angelegt (Betriebsart wie die Raumheizung), IR-Konfiguration gesetzt, nichts gesendet",
           str(r.get("reason")) + " " + str(r.get("verlauf")))
    r = ha.ablauf({"init": {"next_step_id": "funktionen"},
                   "funktionen": lambda sch: {f["name"]: f.get("default") for f in sch["data_schema"]} | {"klima": False},
                   "aendern_bestaetigen": {"bestaetigt": True}}, optionen_fuer=eintrag_k)
    time.sleep(3)
    pruefe(r.get("reason") == "funktionen_fertig" and ha.s("automation.klima_keller") is None and not [h for h in ha.helfer("keller") if "klima" in h]
           and ha.s("automation.heizung_keller") == "on",
           "Klimaanlage wieder entfernt: Klimaautomatik und Klima-Helfer gelöscht, Raumheizung läuft weiter", str(ha.helfer("keller")))

    # ------------------------------------------------------------------ L. Klimaanlage an einer Schaltsteckdose (Muster: Kinderzimmer)
    titel("L. Klimaanlage an einer Schaltsteckdose (Muster: ein über 22,5 °C, aus unter 22,0 °C, nur bei Anwesenheit)")
    for name in ("Steckdose Test Klima", "Anwesend Test", "Kinder Klimaanlage"):
        ha.befehl("input_boolean/create", name=name)
    ha.rest("POST", "/api/config/automation/config/alt_kinder_klima", {
        "alias": "Kinder Klima Automatik", "description": "alt", "mode": "restart",
        "triggers": [{"trigger": "state", "entity_id": "sensor.temperatur_keller"}],
        "conditions": [{"condition": "state", "entity_id": "input_boolean.kinder_klimaanlage", "state": "on"}],
        "actions": [{"action": "homeassistant.turn_on", "target": {"entity_id": "input_boolean.steckdose_test_klima"}}]})
    time.sleep(3)
    sd, an = "input_boolean.steckdose_test_klima", "input_boolean.anwesend_test"
    ha.dienst("input_boolean.turn_on", entity_id=an)
    ha.dienst("input_number.set_value", entity_id="input_number.t_keller", value=21)
    alt_l = []
    r = ha.ablauf({
        "user": geraete("Kinder") | {"bt": "climate.trv_buero", "raumfuehler": "sensor.temperatur_keller"},
        "funktionen": funktionen(profile=["komfort"], zeitquelle="phasen", klima=True, klima_art="schalter", karte=True, fenster_modus="eigen"),
        "profil": profil(21, 17, (ALLE, "06:00:00", "08:00:00")),
        "fenster": {"fensterkontakte": ["binary_sensor.fenster_neu_1"], "fenster_ausnahmen": []},
        "werte": {"frostschutz": 5, "aussensperre": 20},
        "klima_schalter": {"klima_schalter": sd, "klima_ziel_start": 22, "ein_ueber": 0.5, "aus_unter": 0, "kuehl_profile": ["Sommer", "Aus"],
                           "anwesenheit": an, "abwesend_aus": True},
        "altsteuerung": lambda sch: alt_l.append(sch) or {f["name"]: f.get("default") for f in sch["data_schema"]},
        "dashboard": {"dashboards": ["test-mobil"]}, "ansicht": {"ansicht": "0"}, "platz": platz("Tab „Heizung“"), "position": pos(0),
        "bestaetigen": {"bestaetigt": True}})
    time.sleep(3)
    kl = ha.auto_cfg("hz_kinder_klima") if ha.s("automation.klima_kinder") else {}
    vorschlag = next((f.get("default") for f in alt_l[0]["data_schema"] if f["name"] == "abschalten"), []) if alt_l else []
    pruefe(r["type"] == "create_entry" and "klima_schalter" in r["verlauf"] and "klima" not in r["verlauf"]
           and (kl.get("use_blueprint") or {}).get("path") == "ha_heizung_universal/klimaautomatik_steckdose.yaml"
           and ha.s("input_select.hz_kinder_klima_modus") == "Aus" and ha.s("input_number.hz_kinder_klima_ziel") == "22.0"
           and ha.s("input_number.hz_kinder_klima_manuell") is None and ha.s("input_text.hz_kinder_klima_ir") is None,
           "Raum mit Steckdosen-Klima angelegt: Blueprint 4, nur Klima-Modus, Ziel (22 °C) und Anzeige – keine IR-Helfer", str(r.get("verlauf")))
    pruefe(vorschlag == ["automation.kinder_klima_automatik"] and ha.s("automation.kinder_klima_automatik") == "off"
           and ha.auto_cfg("alt_kinder_klima")["alias"].endswith(" (alt)") and (ha.attr("input_boolean.kinder_klimaanlage", "friendly_name") or "").endswith("(alt)")
           and not (ha.attr(sd, "friendly_name") or "").endswith("(alt)"),
           "Alte Klimasteuerung über die Steckdose erkannt, abgeschaltet und gekennzeichnet; die Steckdose selbst bleibt unverändert", str(vorschlag))
    tab = ha.befehl("lovelace/config", url_path="test-mobil")["views"][0]["cards"][1]["tabs"][1]["card"]["cards"]
    kk = json.dumps(tab[0], ensure_ascii=False)
    pruefe("hz_kinder_klima_modus" in kk and "browser_mod" not in kk and "Manuell Kühlen" in kk and "mdi:teddy-bear" in kk,
           "Karte (Mobil): Klima-Reihe Auto / Manuell / Aus – „Manuell“ schaltet Dauerbetrieb, ohne Stufen-Auswahl")
    ha.auto_aendern("hz_kinder_klima", fenster_minuten=0)
    ha.dienst("input_select.select_option", entity_id="input_select.hz_kinder_heizprofil", option="Sommer")
    ha.dienst("input_select.select_option", entity_id="input_select.hz_kinder_klima_modus", option="Automatik Kühlen")
    ha.dienst("input_number.set_value", entity_id="input_number.t_keller", value=23)
    pruefe(ha.warte(lambda: ha.s(sd) == "on" and ha.s("input_boolean.hz_kinder_klima_aktiv") == "on"), "Automatik: 23 °C > 22,5 °C → Steckdose ein, Anzeige an", ha.s(sd))
    ha.dienst("input_number.set_value", entity_id="input_number.t_keller", value=22.2)
    time.sleep(3)
    ein_bleibt = ha.s(sd) == "on"
    ha.dienst("input_number.set_value", entity_id="input_number.t_keller", value=21.9)
    pruefe(ein_bleibt and ha.warte(lambda: ha.s(sd) == "off" and ha.s("input_boolean.hz_kinder_klima_aktiv") == "off"),
           "Hysterese: bei 22,2 °C bleibt sie an, unter 22,0 °C aus", ha.s(sd))
    ha.dienst("input_select.select_option", entity_id="input_select.hz_kinder_klima_modus", option="Manuell Kühlen")
    pruefe(ha.warte(lambda: ha.s(sd) == "on"), "Manuell = Dauerbetrieb: Steckdose ein, auch bei 21,9 °C")
    ha.dienst("input_boolean.turn_on", entity_id="input_boolean.f_neu_1")
    pruefe(ha.warte(lambda: ha.s(sd) == "off") and ha.s("input_select.hz_kinder_klima_modus") == "Manuell Kühlen", "Fenster offen → Pause (Steckdose aus, Modus bleibt)")
    ha.dienst("input_boolean.turn_off", entity_id="input_boolean.f_neu_1")
    pruefe(ha.warte(lambda: ha.s(sd) == "on"), "Fenster zu → Dauerbetrieb läuft weiter")
    ha.dienst("input_boolean.turn_off", entity_id=an)
    pruefe(ha.warte(lambda: ha.s(sd) == "off" and ha.s("input_select.hz_kinder_klima_modus") == "Aus"),
           "Niemand anwesend → Steckdose aus und Klima-Modus Aus (Klima-Modus Aus nach dem Verlassen)", f"{ha.s(sd)} {ha.s('input_select.hz_kinder_klima_modus')}")
    ha.dienst("input_boolean.turn_on", entity_id=an)
    ha.dienst("input_select.select_option", entity_id="input_select.hz_kinder_klima_modus", option="Manuell Kühlen")
    ha.warte(lambda: ha.s(sd) == "on")
    ha.dienst("input_select.select_option", entity_id="input_select.hz_kinder_heizprofil", option="Komfort")
    pruefe(ha.warte(lambda: ha.s(sd) == "off" and ha.s("input_select.hz_kinder_klima_modus") == "Aus"),
           "Heizprofil Komfort (Kühlen nicht freigegeben) → Steckdose aus, Klima-Modus Aus – Heizung und Kühlung nie gleichzeitig")
    ha.dienst("input_select.select_option", entity_id="input_select.hz_kinder_heizprofil", option="Sommer")
    ha.auto_aendern("hz_kinder_klima", ausgabe_modus="test")
    ha.dienst("input_select.select_option", entity_id="input_select.hz_kinder_klima_modus", option="Manuell Kühlen")
    time.sleep(4)
    pruefe(ha.s(sd) == "off", "Testbetrieb: Entscheidung nur im Logbuch, Steckdose bleibt aus")
    ha.auto_aendern("hz_kinder_klima", ausgabe_modus="produktiv")
    ha.dienst("input_select.select_option", entity_id="input_select.hz_kinder_klima_modus", option="Aus")
    # Funktionen ändern: von Steckdose auf IR-Sender umstellen, danach Klima ganz entfernen
    eintrag_l = ha.eintrag("Kinder")["entry_id"]
    r = ha.ablauf({"init": {"next_step_id": "funktionen"},
                   "funktionen": lambda sch: {f["name"]: f.get("default") for f in sch["data_schema"]} | {"klima_art": "ir"},
                   "klima_sender": {"klima_sender": "remote.broadlink_wohnzimmer"},
                   "klima": {"ir_geraet": "klima_kinder", "ir_pruefen": False, "befehl_kuehlen": "power_{stufe}",
                             "befehl_zusatz": "", "befehl_aus": "power_off", "stufe_min": 16, "stufe_max": 23, "luefter": ""},
                   "lernen_auswahl": {"befehle": [], "testen": [], "ueberschreiben": False},
                   "aendern_bestaetigen": {"bestaetigt": True}}, optionen_fuer=eintrag_l)
    time.sleep(3)
    kl = ha.auto_cfg("hz_kinder_klima") if ha.s("automation.klima_kinder") else {}
    pruefe(r.get("reason") == "funktionen_fertig" and (kl.get("use_blueprint") or {}).get("path") == "ha_heizung_universal/klimaautomatik.yaml"
           and ha.s("input_number.hz_kinder_klima_manuell") is not None and ha.s("automation.klima_kinder") == "on",
           "„Funktionen ändern“: Klima von Steckdose auf IR-Sender umgestellt (gleiche Automation, anderes Blueprint, IR-Helfer ergänzt)", str(r.get("reason")))
    r = ha.ablauf({"init": {"next_step_id": "funktionen"},
                   "funktionen": lambda sch: {f["name"]: f.get("default") for f in sch["data_schema"]} | {"klima": False},
                   "aendern_bestaetigen": {"bestaetigt": True}}, optionen_fuer=eintrag_l)
    time.sleep(3)
    pruefe(r.get("reason") == "funktionen_fertig" and ha.s("automation.klima_kinder") is None and not [h for h in ha.helfer("kinder") if "klima" in h]
           and "hz_kinder_klima" not in json.dumps(ha.befehl("lovelace/config", url_path="test-mobil")),
           "Klima entfernt: Automation, Klima-Helfer und Klima-Reihe der Karte weg", str(ha.helfer("kinder")))

    # ------------------------------------------------------------------ O. Fenster mit altem Fail-safe (Better Thermostat reagiert selbst)
    titel("O. Fenster: alter Fail-safe → Fensterstatus des Raums, Better Thermostat automatisch umgestellt, Gerät austauschen")
    for typ, name in (("input_boolean", "Alt Fenster Probe"), ("timer", "Alt Fensterausfall Probe"), ("input_boolean", "Steckdose Probe"), ("input_boolean", "Probe Klimaschalter")):
        ha.befehl(f"{typ}/create", name=name)
    k1, k2, k3 = "binary_sensor.fenster_schlaf_1", "binary_sensor.fenster_schlaf_2", "binary_sensor.fenster_bad_1"
    ha.rest("POST", "/api/config/automation/config/alt_failsafe_probe", {
        "alias": "Heizung Fenster Fail-safe Probe", "description": "alt", "mode": "queued",
        "triggers": [{"trigger": "state", "entity_id": [k1, k2]}],
        "actions": [{"action": "{{ 'input_boolean.turn_on' if [states('" + k1 + "'), states('" + k2 + "')] | select('eq', 'on') | list | count > 0 else 'input_boolean.turn_off' }}",
                     "target": {"entity_id": "input_boolean.alt_fenster_probe"}},
                    {"action": "timer.cancel", "target": {"entity_id": "timer.alt_fensterausfall_probe"}}]})
    ha.rest("POST", "/api/config/automation/config/alt_klima_probe", {
        "alias": "Probe Klima Automatik", "description": "alt", "mode": "single",
        "triggers": [{"trigger": "state", "entity_id": k1}], "conditions": [{"condition": "state", "entity_id": k1, "state": "off"}],
        "actions": [{"action": "input_boolean.toggle", "target": {"entity_id": "input_boolean.probe_klimaschalter"}}]})
    bt_flow = ha.rest("POST", "/api/config/config_entries/flow", {"handler": "better_thermostat"})
    ha.rest("POST", f"/api/config/config_entries/flow/{bt_flow['flow_id']}", {"name": "BT Fenstertest", "window_sensors": "input_boolean.alt_fenster_probe",
                                                                              "temperature_sensor": "sensor.temperatur_buero", "trv": "climate.trv_buero"})
    pruefe(ha.warte(lambda: ha.attr("climate.bt_fenstertest", "window_sensor") == "input_boolean.alt_fenster_probe"),
           "Vorbereitung: Better Thermostat (Testnachbau) mit dem alten Fenster-Helfer als Fenstersensor", str(ha.attr("climate.bt_fenstertest", "window_sensor")))
    # Alte Karten wie in einem typischen Mobil-Dashboard: im Tab „Heizung“ (Raster) – dorthin kommt auch die neue Karte; dazu eine iPad-Karte,
    # die zwischen Auswahl und Bestätigen verschwindet (muss gemeldet werden statt still übergangen).
    alt_karte = lambda name: {"type": "custom:mod-card", "card": {"type": "vertical-stack", "cards": [  # noqa: E731
        {"type": "custom:button-card", "name": name, "entity": "automation.heizung_fenster_fail_safe_probe", "tap_action": {"action": "toggle"}}]}}
    mob = ha.befehl("lovelace/config", url_path="test-mobil")
    mob["views"][0]["cards"][1]["tabs"][1]["card"]["cards"].insert(0, alt_karte("Fensterprobe alt"))
    ha.befehl("lovelace/config/save", url_path="test-mobil", config=mob)
    ipad = ha.befehl("lovelace/config", url_path="test-ipad")
    ipad["views"][0]["sections"].append({"type": "grid", "cards": [{"type": "heading", "heading": "Probe alt"}, alt_karte("Fensterprobe alt iPad")]})
    ha.befehl("lovelace/config/save", url_path="test-ipad", config=ipad)

    def ipad_karte_weg(_sch):
        cfg = ha.befehl("lovelace/config", url_path="test-ipad")
        cfg["views"][0]["sections"] = [x for x in cfg["views"][0]["sections"] if "Fensterprobe alt iPad" not in json.dumps(x)]
        ha.befehl("lovelace/config/save", url_path="test-ipad", config=cfg)
        return {"bestaetigt": True}

    def heiz_tab():
        return ha.befehl("lovelace/config", url_path="test-mobil")["views"][0]["cards"][1]["tabs"][1]["card"]["cards"]
    andere_vorher = [kname(k) for k in heiz_tab() if "Fensterprobe" not in json.dumps(k)]
    fo, alt_o, ak_o = [], [], []
    r = ha.ablauf({
        "user": geraete("Fensterprobe") | {"bt": "climate.bt_fenstertest", "raumfuehler": "sensor.temperatur_buero"},
        "funktionen": funktionen(profile=["komfort"], zeitquelle="phasen", fenster_modus="eigen", klima=True, klima_art="schalter", karte=True),
        "profil": profil(21, 16, (ALLE, "06:00:00", "08:00:00")),
        "fenster": lambda sch: fo.append(sch) or {f["name"]: f.get("default") for f in sch["data_schema"] if f["name"] != "zurueck"},
        "werte": {"frostschutz": 5, "aussensperre": 20},
        "klima_schalter": {"klima_schalter": "input_boolean.steckdose_probe", "klima_ziel_start": 22, "ein_ueber": 0.5, "aus_unter": 0,
                           "kuehl_profile": ["Sommer", "Aus"], "abwesend_aus": True},
        "altsteuerung": lambda sch: alt_o.append(sch) or {f["name"]: f.get("default") for f in sch["data_schema"] if f["name"] != "zurueck"},
        "dashboard": {"dashboards": ["test-mobil"]}, "ansicht": {"ansicht": "0"}, "platz": platz("Tab „Heizung“"), "position": pos(0),
        "alte_karten": lambda sch: ak_o.append(sch) or {"karten": [o["value"] for o in sch["data_schema"][0]["selector"]["select"]["options"]
                                                                   if "Fensterprobe alt" in o["label"]]},
        "bestaetigen": ipad_karte_weg})
    felder_o = {f["name"]: f.get("default") for f in fo[0]["data_schema"]} if fo else {}
    ak_labels = [o["label"] for o in ak_o[0]["data_schema"][0]["selector"]["select"]["options"]] if ak_o else []
    tab_o = heiz_tab()
    pruefe(len([x for x in ak_labels if "Fensterprobe alt" in x]) == 2 and any("Tab „Heizung“" in x for x in ak_labels),
           "Alte Karten angeboten: im Mobil-Tab „Heizung“ (dort kommt auch die neue Karte hin) und im iPad", str(ak_labels))
    pruefe(not any("Fensterprobe alt" in json.dumps(k) for k in tab_o) and any("hz_fensterprobe_status" in json.dumps(k) for k in tab_o)
           and [kname(k) for k in tab_o if "Fensterprobe" not in json.dumps(k) and "hz_fensterprobe" not in json.dumps(k)] == andere_vorher,
           "Alte Karte im selben Tab wie die neue Karte entfernt (Fall Mobil-Dashboard); neue Karte und die übrigen Raumkarten bleiben",
           str([kname(k) for k in tab_o]))
    hw = (r.get("description_placeholders") or {}).get("hinweis", "")
    pruefe(r.get("description") == "hinweis" and "nicht mehr gefunden" in hw and "Fensterprobe alt iPad" in hw and "Mobil" not in hw,
           "Gewählte Karte, die beim Anlegen nicht mehr da ist, wird in der Abschlussmeldung genannt (statt still übergangen)", hw[:200])
    pruefe(r["type"] == "create_entry" and felder_o.get("fensterkontakte") == [k1, k2] and felder_o.get("fenster_ausnahmen") == [k2]
           and "fenster_reaktion" not in felder_o,
           "Fenster-Schritt ohne Reaktionsfrage; Kontakte aus dem alten Fail-safe, Ausnahme (nicht von der alten Klimaautomatik beachtet) vorausgefüllt",
           str(felder_o))
    vorschlag = next((f.get("default") for f in alt_o[0]["data_schema"] if f["name"] == "abschalten"), []) if alt_o else []
    pruefe("automation.heizung_fenster_fail_safe_probe" in vorschlag and "automation.probe_klima_automatik" not in vorschlag,
           "Alter Fail-safe gehört zur alten Steuerung (er schreibt den Fenstersensor des Better Thermostat)", str(vorschlag))
    time.sleep(4)
    inp = ha.auto_cfg("hz_fensterprobe_raumheizung")["use_blueprint"]["input"]
    kl = ha.auto_cfg("hz_fensterprobe_klima")["use_blueprint"]["input"]
    pruefe(ha.warte(lambda: ha.attr("climate.bt_fenstertest", "window_sensor") == "input_boolean.hz_fensterprobe_fensterstatus")
           and inp.get("fenster_reaktion") == "bt" and inp.get("fenster_ausnahmen") == [k2]
           and kl.get("fensterkontakte") == ["input_boolean.hz_fensterprobe_fensterstatus_klima"]
           and ha.s("automation.heizung_fenster_fail_safe_probe") == "off",
           "Better Thermostat automatisch auf den Fensterstatus des Raums umgestellt; Klima hängt am Fensterstatus ohne Ausnahme; alter Fail-safe aus",
           f"{ha.attr('climate.bt_fenstertest', 'window_sensor')} {kl.get('fensterkontakte')}")
    ha.dienst("input_boolean.turn_on", entity_id="input_boolean.f_schlaf_1")
    ok1 = ha.warte(lambda: ha.s("input_boolean.hz_fensterprobe_fensterstatus") == "on" and ha.s("input_boolean.hz_fensterprobe_fensterstatus_klima") == "on"
                   and ha.attr("climate.bt_fenstertest", "window_open") is True)
    ha.dienst("input_boolean.turn_off", entity_id="input_boolean.f_schlaf_1")
    ha.warte(lambda: ha.s("input_boolean.hz_fensterprobe_fensterstatus") == "off")
    ha.dienst("input_boolean.turn_on", entity_id="input_boolean.f_schlaf_2")
    ok2 = ha.warte(lambda: ha.s("input_boolean.hz_fensterprobe_fensterstatus") == "on") and ha.s("input_boolean.hz_fensterprobe_fensterstatus_klima") == "off"
    ha.dienst("input_boolean.turn_off", entity_id="input_boolean.f_schlaf_2")
    pruefe(ok1 and ok2, "Fenster auf → Fensterstatus und Better Thermostat „offen“; ausgenommener Kontakt (Balkontür) pausiert nur die Heizung, nicht Klima/PV")
    eintrag_o = ha.eintrag("Fensterprobe")["entry_id"]
    gw = []
    r = ha.ablauf({"init": {"next_step_id": "geraet"},
                   "geraet": lambda sch: gw.append(sch) or {"alt": k2},
                   "geraet_neu": {"neu": k3}}, optionen_fuer=eintrag_o)
    time.sleep(3)
    inp = ha.auto_cfg("hz_fensterprobe_raumheizung")["use_blueprint"]["input"]
    werte_gw = [o["value"] for o in gw[0]["data_schema"][0]["selector"]["select"]["options"]] if gw else []
    pruefe(r.get("reason") == "geraet_fertig" and k1 in werte_gw and "climate.bt_fenstertest" in werte_gw and not any(".hz_" in w for w in werte_gw)
           and inp.get("fensterkontakte") == [k1, k3] and inp.get("fenster_ausnahmen") == [k3],
           "„Konfigurieren → Gerät austauschen“: defekter Kontakt an einer Stelle ersetzt – in Kontakten und Ausnahme", str(inp.get("fensterkontakte")))
    ha.dienst("input_boolean.turn_on", entity_id="input_boolean.f_bad_1")
    ok3 = ha.warte(lambda: ha.s("input_boolean.hz_fensterprobe_fensterstatus") == "on") and ha.s("input_boolean.hz_fensterprobe_fensterstatus_klima") == "off"
    ha.dienst("input_boolean.turn_off", entity_id="input_boolean.f_bad_1")
    pruefe(ok3, "Der neue Kontakt wirkt sofort (pausiert die Heizung, als Ausnahme nicht Klima/PV)")
    # Gerät austauschen auch im Better Thermostat: Raumfühler (BT + Raumheizung), Heizkörperthermostat gleicher Art, anderer Art → Hinweis
    gw2 = []
    r = ha.ablauf({"init": {"next_step_id": "geraet"},
                   "geraet": lambda sch: gw2.append(sch) or {"alt": "sensor.temperatur_buero"},
                   "geraet_neu": {"neu": "sensor.temperatur_bad"}}, optionen_fuer=eintrag_o)
    time.sleep(3)
    labels_gw2 = {o["value"]: o["label"] for o in gw2[0]["data_schema"][0]["selector"]["select"]["options"]} if gw2 else {}
    inp = ha.auto_cfg("hz_fensterprobe_raumheizung")["use_blueprint"]["input"]
    pruefe("Better Thermostat" in labels_gw2.get("climate.trv_buero", "") and "Better Thermostat" in labels_gw2.get("sensor.temperatur_buero", "")
           and "Heizung Fensterprobe" in labels_gw2.get("sensor.temperatur_buero", ""),
           "„Gerät austauschen“ zeigt auch die Geräte des Better Thermostat (Heizkörperthermostat, Raumfühler) mit ihrem Einsatzort",
           str({k: v for k, v in labels_gw2.items() if "trv" in k or "temperatur" in k}))
    pruefe(r.get("reason") == "geraet_fertig" and "Better Thermostat" in (r.get("description_placeholders") or {}).get("liste", "")
           and ha.warte(lambda: ha.attr("climate.bt_fenstertest", "temperature_sensor") == "sensor.temperatur_bad")
           and inp.get("raumfuehler") == "sensor.temperatur_bad"
           and ha.attr("climate.bt_fenstertest", "window_sensor") == "input_boolean.hz_fensterprobe_fensterstatus",
           "Raumfühler getauscht: in der Raumheizung und im Better Thermostat (Fenstersensor bleibt)",
           f"{ha.attr('climate.bt_fenstertest', 'temperature_sensor')} {inp.get('raumfuehler')} {(r.get('description_placeholders') or {}).get('liste')}")
    # Gerät, das alle Räume verwenden (Außenfühler): in einem Raum getauscht → in allen Räumen ersetzt, danach zurück
    def aussen_aller():  # Außenfühler in den Raumheizungen aller eingerichteten Räume
        out = {}
        for e in ha.befehl("config/entity_registry/list"):
            uid = str(e.get("unique_id") or "")
            if e.get("platform") == "automation" and uid.startswith("hz_") and uid.endswith("_raumheizung"):
                try:
                    out[uid] = ha.auto_cfg(uid)["use_blueprint"]["input"].get("aussentemperatur")
                except HAFehler:
                    pass
        return out
    gn = []
    r = ha.ablauf({"init": {"next_step_id": "geraet"}, "geraet": {"alt": "sensor.aussentemperatur"},
                   "geraet_neu": lambda sch: gn.append(sch) or {"neu": "sensor.aussentemperatur_neu", "alle_raeume": True}}, optionen_fuer=eintrag_o)
    time.sleep(3)
    nach = aussen_aller()
    pruefe(r.get("reason") == "geraet_fertig" and gn and "alle_raeume" in [f["name"] for f in gn[0]["data_schema"]]
           and "Auch verwendet in" in gn[0]["description_placeholders"].get("andere", "") and len(nach) >= 2
           and set(nach.values()) == {"sensor.aussentemperatur_neu"} and "Wohnzimmer:" in (r.get("description_placeholders") or {}).get("liste", ""),
           "Gerät, das mehrere Räume verwenden (Außenfühler): „Auch in allen anderen Räumen ersetzen“ tauscht es in jedem Raum", str(nach))
    ha.ablauf({"init": {"next_step_id": "geraet"}, "geraet": {"alt": "sensor.aussentemperatur_neu"},
               "geraet_neu": {"neu": "sensor.aussentemperatur", "alle_raeume": True}}, optionen_fuer=eintrag_o)
    time.sleep(3)
    pruefe(set(aussen_aller().values()) == {"sensor.aussentemperatur"}, "… und wieder zurück in allen Räumen")
    r = ha.ablauf({"init": {"next_step_id": "geraet"}, "geraet": {"alt": "climate.trv_buero"}, "geraet_neu": {"neu": "climate.trv_bad"}},
                  optionen_fuer=eintrag_o)
    pruefe(r.get("reason") == "geraet_fertig" and ha.warte(lambda: ha.attr("climate.bt_fenstertest", "trvs") == ["climate.trv_bad"])
           and ha.attr("climate.bt_fenstertest", "trv_kalibrierung") == ["target_temp_based"]
           and "⚠" not in (r.get("description_placeholders") or {}).get("hinweis", ""),
           "Heizkörperthermostat gleicher Art im Better Thermostat getauscht; Kalibrierung und Einstellungen bleiben",
           str(ha.attr("climate.bt_fenstertest", "trvs")))
    bt2 = ha.rest("POST", "/api/config/config_entries/flow", {"handler": "better_thermostat"})
    ha.rest("POST", f"/api/config/config_entries/flow/{bt2['flow_id']}", {"name": "BT Zweit"})
    ha.warte(lambda: ha.s("climate.bt_zweit") is not None)
    r = ha.ablauf({"init": {"next_step_id": "geraet"}, "geraet": {"alt": "climate.trv_bad"}, "geraet_neu": {"neu": "climate.bt_zweit"}},
                  optionen_fuer=eintrag_o)
    hw = (r.get("description_placeholders") or {}).get("hinweis", "")
    time.sleep(2)
    pruefe(r.get("reason") == "geraet_fertig" and "anderen Geräte-Integration" in hw and ha.attr("climate.bt_fenstertest", "trvs") == ["climate.trv_bad"],
           "Heizkörperthermostat einer anderen Geräte-Integration: im Better Thermostat nicht getauscht, deutlicher Hinweis", hw[:160])
    r = ha.ablauf({"init": {"next_step_id": "alt_zurueck"}, "alt_zurueck": {"bestaetigt": True}}, optionen_fuer=eintrag_o)
    pruefe(r.get("reason") == "alt_zurueck_fertig" and ha.warte(lambda: ha.attr("climate.bt_fenstertest", "window_sensor") == "input_boolean.alt_fenster_probe")
           and ha.s("automation.heizung_fenster_fail_safe_probe") == "on",
           "„Alte Steuerung wieder einschalten“: Better Thermostat wieder am alten Fenster-Helfer, alter Fail-safe an")
    r = ha.ablauf({"init": {"next_step_id": "alt_neu"}, "alt_neu": {"bestaetigt": True}}, optionen_fuer=eintrag_o)
    pruefe(r.get("reason") == "alt_neu_fertig" and ha.warte(lambda: ha.attr("climate.bt_fenstertest", "window_sensor") == "input_boolean.hz_fensterprobe_fensterstatus"),
           "„Neue Steuerung wieder übernehmen“: Better Thermostat wieder am Fensterstatus des Raums")
    ha.rest("DELETE", f"/api/config/config_entries/entry/{eintrag_o}")
    pruefe(ha.warte(lambda: ha.attr("climate.bt_fenstertest", "window_sensor") == "input_boolean.alt_fenster_probe"),
           "Raum gelöscht: Better Thermostat zurück am alten Fenster-Helfer", str(ha.attr("climate.bt_fenstertest", "window_sensor")))

    # ------------------------------------------------------------------ I. Protokoll
    titel("I. Protokoll von Home Assistant")
    if log and log.exists():
        zeilen = log.read_text(encoding="utf-8", errors="replace").splitlines()
        erwartet = ("Command not found", "IR-Senden fehlgeschlagen", "No infrared code received", "has not been tested by Home Assistant",
                    "automation.klima_gast]", "libturbojpeg", "FFmpeg", "ffmpeg")
        fehler = [z for z in zeilen if (" ERROR " in z or "custom_components/heizung_universal" in z or ("WARNING" in z and ("emplate" in z or "blueprint" in z.lower())))
                  and not any(e in z for e in erwartet)
                  # Testraum „Kinder“ verwendet ein Heizkörperthermostat (7–35 °C) als Thermostat: Frostschutz 5 °C wird von diesem Testgerät abgelehnt
                  and not ("heizung_kinder" in z and ("Provided temperature 5.0" in z or "Accepted range is 7 to 35" in z))]
        pruefe(not fehler, f"Keine unerwarteten Fehler, Template- oder Blueprint-Warnungen im Protokoll ({len(zeilen)} Zeilen)", " | ".join(f[:230] for f in fehler[:4]))
    ok = sum(1 for e, _ in ERG if e)
    print(f"\nAbnahme in echter Home-Assistant-Instanz: {ok}/{len(ERG)} Prüfungen bestanden")
    for e, t in ERG:
        if not e:
            print("   NICHT BESTANDEN:", t)
    sys.exit(0 if ok == len(ERG) else 1)


if __name__ == "__main__":
    main()
