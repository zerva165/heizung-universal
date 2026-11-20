#!/usr/bin/env python3
"""Erzeugt Blueprint 4 „Klimaautomatik Steckdose“ (optional, Räume mit Klimaanlage an einer Schaltsteckdose).

Vorbild: eine einfache Steckdosen-Klimaautomatik (Steckdose ein über 22,5 °C, aus unter 22,0 °C, nur bei Anwesenheit;
beim Verlassen Steckdose und Hauptschalter aus). Die Klimaanlage selbst kennt nur ein/aus – keine Stufen, kein PV-Heizen.
Ausgabe: blueprints/automation/ha_heizung_universal/klimaautomatik_steckdose.yaml
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from yamlgen import Inp, dump  # noqa: E402
from build_raumheizung import sel_entity, sel_number, c  # noqa: E402

BASIS = Path(__file__).resolve().parent.parent
ZIELDATEI = BASIS / "blueprints" / "automation" / "ha_heizung_universal" / "klimaautomatik_steckdose.yaml"


def inputs():
    return {
        "geraete": {"name": "Raum und Klimaanlage", "icon": "mdi:power-socket-de", "input": {
            "raum_name": {"name": "Raumname", "default": "Raum", "selector": {"text": {}}},
            "raum_schluessel": {"name": "Raumkennung", "default": "raum", "description": "Wie in der Raumheizungssteuerung, z. B. `kinderzimmer`.", "selector": {"text": {}}},
            "klima_schalter": {"name": "Schaltsteckdose der Klimaanlage", "description": "Schalter (z. B. Zigbee-Steckdose), der die Klimaanlage ein- und ausschaltet.",
                               "selector": sel_entity(["switch", "input_boolean"])},
            "raumfuehler": {"name": "Raumtemperatur", "description": "Externer Raumfühler oder das Better Thermostat des Raums.",
                            "selector": {"entity": {"filter": [{"domain": ["sensor"], "device_class": ["temperature"]}, {"domain": ["climate"]}]}}},
            "fensterkontakte": {"name": "Fensterkontakte für die Klimaanlage", "default": [],
                                "description": "Kontakte, deren Öffnen die Klimaanlage pausiert.",
                                "selector": {"entity": {"multiple": True, "filter": [{"domain": ["binary_sensor"], "device_class": ["window", "door", "opening"]},
                                                                                {"domain": ["input_boolean"]}]}}},
        }},
        "automatik": {"name": "Automatik-Kühlen", "icon": "mdi:snowflake-thermometer", "collapsed": True,
                      "description": "Die Steckdose schaltet ein, wenn der Raum wärmer ist als Ziel plus Einschalt-Abstand, und aus, wenn er kühler ist als Ziel minus Ausschalt-Abstand.",
                      "input": {
            "ein_ueber": {"name": "Einschalten, wenn wärmer als Ziel plus", "default": 0.5, "selector": sel_number(0, 3, 0.1, "K")},
            "aus_unter": {"name": "Ausschalten, wenn kühler als Ziel minus", "default": 0.0, "selector": sel_number(0, 3, 0.1, "K")},
            "fenster_minuten": {"name": "Pause, wenn ein Fenster offen ist seit", "default": 3, "selector": sel_number(0, 30, 1, "min", "box")},
        }},
        "anwesenheit_abschnitt": {"name": "Anwesenheit", "icon": "mdi:home-account", "collapsed": True,
                                  "description": "Optional: Die Klimaanlage läuft nur, solange diese Person bzw. dieser Schalter „zuhause“ bzw. „an“ meldet.",
                                  "input": {
            "anwesenheit": {"name": "Anwesenheit (Person, Tracker oder Schalter, optional)", "default": [],
                            "selector": sel_entity(["person", "device_tracker", "binary_sensor", "input_boolean", "group"])},
            "abwesend_aus": {"name": "Beim Verlassen auch den Klima-Modus auf Aus stellen", "default": True,
                             "description": "Nach der Rückkehr muss die Klimaanlage bewusst wieder eingeschaltet werden.",
                             "selector": {"boolean": {}}},
        }},
        "heizung": {"name": "Zusammenarbeit mit der Raumheizung", "icon": "mdi:radiator", "collapsed": True,
                    "description": "Kühlen ist nur erlaubt, wenn die Heizung dieses Raums in einem der gewählten Profile steht oder der globale Schalter „Heizung Aus“ an ist – so heizen Heizkörper und Klimaanlage nie gegeneinander.",
                    "input": {
            "heizprofil": {"name": "Heizprofil-Auswahl der Raumheizung", "selector": sel_entity("input_select")},
            "kuehl_profile": {"name": "Kühlen erlaubt in den Heizprofilen", "default": ["Sommer", "Aus"],
                              "selector": {"select": {"multiple": True, "mode": "list", "options": ["Komfort", "Übergang", "Urlaub", "Sommer", "Aus"]}}},
            "haus_heizung_aus": {"name": "Globaler Schalter „Heizung Aus“ (optional)", "default": [], "selector": sel_entity("input_boolean")},
        }},
        "helfer": {"name": "Raum-Helfer der Klimaanlage", "icon": "mdi:tune-variant", "collapsed": True,
                   "description": "Legt der Einrichtungsassistent an. Die Dashboard-Karte bedient die Klimaanlage nur über diese Helfer.", "input": {
            "klima_modus": {"name": "Klima-Modus (input_select: Aus, Automatik Kühlen, Manuell Kühlen = Dauerbetrieb)", "selector": sel_entity("input_select")},
            "zieltemperatur": {"name": "Automatik-Zieltemperatur (input_number)", "selector": sel_entity("input_number")},
            "klima_aktiv": {"name": "Klimaanlage läuft (input_boolean, Anzeige)", "selector": sel_entity("input_boolean")},
        }},
        "erweitert": {"name": "Erweitert", "icon": "mdi:cog", "collapsed": True, "input": {
            "ausgabe_modus": {"name": "Betriebsart", "default": "produktiv", "selector": {"select": {"mode": "list", "options": [
                {"value": "produktiv", "label": "Normalbetrieb"}, {"value": "test", "label": "Testbetrieb (Entscheidung nur ins Logbuch)"}]}}},
        }},
    }


def variablen():
    v = {k: Inp(k) for k in ["raum_name", "raum_schluessel", "klima_schalter", "raumfuehler", "fensterkontakte", "ein_ueber", "aus_unter",
                             "anwesenheit", "abwesend_aus", "heizprofil", "kuehl_profile", "haus_heizung_aus", "klima_modus", "zieltemperatur",
                             "klima_aktiv", "ausgabe_modus"]}
    v["produktiv"] = "{{ ausgabe_modus == 'produktiv' }}"
    v["normal_ids"] = ["raumtemperatur", "modus", "zieltemperatur", "heizprofil", "fenster_geschlossen", "anwesenheit", "ha_start"]
    return v


def trigger():
    return [
        {"alias": "Nach dem Start von Home Assistant: Zustand prüfen", "trigger": "homeassistant", "event": "start", "id": "ha_start"},
        {"alias": "Raumtemperatur geändert", "trigger": "state", "entity_id": Inp("raumfuehler"), "id": "raumtemperatur"},
        {"alias": "Klima-Modus geändert", "trigger": "state", "entity_id": Inp("klima_modus"), "id": "modus"},
        {"alias": "Automatik-Zieltemperatur geändert", "trigger": "state", "entity_id": Inp("zieltemperatur"), "id": "zieltemperatur"},
        {"alias": "Heizprofil der Raumheizung geändert", "trigger": "state", "entity_id": Inp("heizprofil"), "id": "heizprofil"},
        {"alias": "Globaler Schalter „Heizung Aus“ geändert", "trigger": "state", "entity_id": Inp("haus_heizung_aus"), "id": "heizprofil"},
        {"alias": "Anwesenheit geändert", "trigger": "state", "entity_id": Inp("anwesenheit"), "id": "anwesenheit"},
        {"alias": "Ein Fenster ist seit der Pausenzeit offen", "trigger": "state", "entity_id": Inp("fensterkontakte"), "to": "on",
         "for": {"minutes": Inp("fenster_minuten")}, "id": "fenster_offen"},
        {"alias": "Ein Fenster wurde geschlossen", "trigger": "state", "entity_id": Inp("fensterkontakte"), "from": "on", "to": "off", "id": "fenster_geschlossen"},
        {"alias": "Steckdose geschaltet (auch von Hand oder durch Ausfall)", "trigger": "state", "entity_id": Inp("klima_schalter"), "id": "schalter"},
    ]


ENTSCHEIDUNG = r"""{%- if trigger.id == 'schalter' -%}anzeige
{%- elif anwesenheit_gesetzt and not anwesend and (aktiv_jetzt or (abwesend_aus and modus_jetzt != 'Aus')) -%}abwesend
{%- elif anwesenheit_gesetzt and not anwesend -%}keine
{%- elif modus_jetzt == 'Aus' -%}{{ 'aus' if aktiv_jetzt else 'keine' }}
{%- elif not profil_ok -%}sperre_aus
{%- elif fenster_offen -%}{{ 'fenster_pause' if aktiv_jetzt and trigger.id == 'fenster_offen' else 'keine' }}
{%- elif modus_jetzt == 'Manuell Kühlen' -%}{{ 'ein' if not aktiv_jetzt else 'keine' }}
{%- elif modus_jetzt == 'Automatik Kühlen' and raum_gueltig and raum_temp > ein_ab and not aktiv_jetzt -%}ein
{%- elif modus_jetzt == 'Automatik Kühlen' and raum_gueltig and raum_temp < aus_ab and aktiv_jetzt -%}aus
{%- else -%}keine{%- endif -%}"""


def schalten(dienst, alias):
    return {"alias": alias, "action": f"homeassistant.{dienst}", "target": {"entity_id": "{{ klima_schalter }}"}, "continue_on_error": True}


def anzeige():
    return {"alias": "Anzeige „Klimaanlage läuft“ an den tatsächlichen Steckdosen-Zustand angleichen", "if": [c(
        "Anzeige weicht ab", "{{ is_state(klima_schalter, 'on') != is_state(klima_aktiv, 'on') }}")], "then": [
        {"alias": "Anzeige setzen", "action": "{{ 'input_boolean.turn_on' if is_state(klima_schalter, 'on') else 'input_boolean.turn_off' }}",
         "target": {"entity_id": "{{ klima_aktiv }}"}}]}


def aktionen():
    a = []
    a.append({"alias": "Nach einem Neustart höchstens 2 Minuten auf gültige Werte warten", "if": [c("Neustart", "{{ trigger.id == 'ha_start' }}")], "then": [
        {"alias": "Auf Raumtemperatur und Klima-Modus warten",
         "wait_template": ("{%- set s = states(raumfuehler) if raumfuehler.startswith('sensor.') else state_attr(raumfuehler, 'current_temperature') -%}"
                           "{{ is_number(s) and states(klima_modus) not in ['unknown', 'unavailable'] and states(heizprofil) not in ['unknown', 'unavailable'] }}"),
         "timeout": {"minutes": 2}, "continue_on_timeout": True}]})
    a.append({"alias": "Erstwiederherstellung eines Helfers nach dem Neustart ist keine echte Änderung", "if": [c(
        "Trigger ohne Vorzustand", "{{ trigger.id not in ['ha_start'] and trigger.from_state is none }}")],
        "then": [{"alias": "Sicher beenden", "stop": "Erstwiederherstellung eines Helfers"}]})
    a.append({"alias": "Aktuelle Werte lesen", "variables": {
        "raum_temp": ("{%- set s = states(raumfuehler) if raumfuehler.startswith('sensor.') else state_attr(raumfuehler, 'current_temperature') -%}"
                      "{{ s | float(0) }}"),
        "raum_gueltig": ("{%- set s = states(raumfuehler) if raumfuehler.startswith('sensor.') else state_attr(raumfuehler, 'current_temperature') -%}"
                         "{{ is_number(s) }}"),
        "modus_jetzt": "{{ states(klima_modus) }}",
        "aktiv_jetzt": "{{ is_state(klima_schalter, 'on') }}",
        "fenster_offen": "{{ fensterkontakte | select('is_state', 'on') | list | count > 0 }}",
        "anwesenheit_gesetzt": "{{ anwesenheit is string and anwesenheit != '' }}",
        "anwesend": "{{ not (anwesenheit is string and anwesenheit != '') or states(anwesenheit) in ['home', 'on'] }}",
        "profil_ok": "{{ states(heizprofil) in kuehl_profile or (haus_heizung_aus is string and haus_heizung_aus != '' and is_state(haus_heizung_aus, 'on')) }}",
        "ein_ab": "{{ states(zieltemperatur) | float(22) + ein_ueber | float }}",
        "aus_ab": "{{ states(zieltemperatur) | float(22) - aus_unter | float }}",
    }})
    a.append({"alias": "Entscheidung genau einmal bestimmen", "variables": {"entscheidung": ENTSCHEIDUNG}})
    a.append({"alias": "Nichts zu tun", "condition": "template", "value_template": "{{ entscheidung != 'keine' }}"})
    a.append({"alias": "Testbetrieb: Entscheidung nur protokollieren", "if": [c("Testbetrieb (Anzeige wird trotzdem angeglichen)", "{{ not produktiv and entscheidung != 'anzeige' }}")],
              "then": [{"alias": "Geplante Aktion ins Logbuch", "action": "logbook.log", "data": {
                  "name": "{{ raum_name }} Klima (Test)",
                  "message": "Geplant: {{ entscheidung }} · Raum {{ raum_temp }} °C · Ziel {{ states(zieltemperatur) }} · Modus {{ modus_jetzt }} · Steckdose {{ states(klima_schalter) }}",
                  "entity_id": "{{ klima_aktiv }}"}},
                  {"alias": "Testlauf beenden", "stop": "Testbetrieb"}]})
    zweige = [
        {"alias": "Steckdose wurde geschaltet: Anzeige angleichen", "conditions": [c("Anzeige", "{{ entscheidung == 'anzeige' }}")],
         "sequence": [anzeige()]},
        {"alias": "Niemand mehr anwesend: Klimaanlage aus (und Klima-Modus aus, falls gewählt)", "conditions": [c("Abwesend", "{{ entscheidung == 'abwesend' }}")],
         "sequence": [
             schalten("turn_off", "Steckdose ausschalten"),
             {"alias": "Klima-Modus auf Aus, falls gewählt", "if": [c("Beim Verlassen ausschalten", "{{ abwesend_aus and modus_jetzt != 'Aus' }}")],
              "then": [{"alias": "Klima-Modus Aus", "action": "input_select.select_option", "target": {"entity_id": "{{ klima_modus }}"}, "data": {"option": "Aus"}}]},
             {"alias": "Im Logbuch festhalten", "action": "logbook.log", "data": {
                 "name": "{{ raum_name }} Klima", "message": "Niemand anwesend ({{ states(anwesenheit) }}) – Klimaanlage ausgeschaltet.", "entity_id": "{{ klima_aktiv }}"}}]},
        {"alias": "Klima-Modus Aus oder Ziel erreicht: Steckdose aus", "conditions": [c("Aus", "{{ entscheidung == 'aus' }}")],
         "sequence": [schalten("turn_off", "Steckdose ausschalten")]},
        {"alias": "Kühlen nicht erlaubt (Heizprofil): Steckdose aus und Klima-Modus auf Aus", "conditions": [c("Sperre", "{{ entscheidung == 'sperre_aus' }}")],
         "sequence": [
             schalten("turn_off", "Steckdose ausschalten"),
             {"alias": "Klima-Modus auf Aus", "action": "input_select.select_option", "target": {"entity_id": "{{ klima_modus }}"}, "data": {"option": "Aus"}},
             {"alias": "Im Logbuch festhalten", "action": "logbook.log", "data": {
                 "name": "{{ raum_name }} Klima", "message": "Kühlen im Heizprofil {{ states(heizprofil) }} nicht erlaubt – Klimaanlage aus.", "entity_id": "{{ klima_aktiv }}"}}]},
        {"alias": "Fenster offen: Klimaanlage pausieren (Modus bleibt)", "conditions": [c("Fensterpause", "{{ entscheidung == 'fenster_pause' }}")],
         "sequence": [schalten("turn_off", "Steckdose ausschalten")]},
        {"alias": "Kühlen: Steckdose ein", "conditions": [c("Ein", "{{ entscheidung == 'ein' }}")],
         "sequence": [schalten("turn_on", "Steckdose einschalten")]},
    ]
    a.append({"alias": "Entscheidung ausführen", "choose": zweige})
    return a


def blueprint():
    return {
        "blueprint": {
            "name": "Klimaautomatik Steckdose (Raum)",
            "description": "Paketversion 1.6.0 · " + (
                "Optionale Ergänzung zur „Universellen Raumheizungssteuerung“ für Klimaanlagen, die über eine Schaltsteckdose ein- und "
                "ausgeschaltet werden. Betriebsarten Aus, Automatik Kühlen (Ein- und Ausschalt-Abstand um die Zieltemperatur) und Manuell Kühlen "
                "(Dauerbetrieb). Kühlen nur in freigegebenen Heizprofilen, Fensterpause, optional nur bei Anwesenheit (beim Verlassen aus)."),
            "domain": "automation", "author": "HA-Heizung-Universal",
            "homeassistant": {"min_version": "2026.11.0"},
            "input": inputs(),
        },
        "mode": "queued", "max": 10, "max_exceeded": "warning", "trace": {"stored_traces": 20},
        "variables": variablen(), "triggers": trigger(), "conditions": [], "actions": aktionen(),
    }


if __name__ == "__main__":
    ZIELDATEI.parent.mkdir(parents=True, exist_ok=True)
    ZIELDATEI.write_text("# Klimaautomatik Steckdose – Blueprint 4 (optional)\n# Erzeugt mit tools/build_klima_steckdose.py\n" + dump(blueprint()), encoding="utf-8")
    print("geschrieben:", ZIELDATEI.relative_to(BASIS))
