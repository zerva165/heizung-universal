#!/usr/bin/env python3
"""Erzeugt Blueprint 2 „Klimaautomatik“ (optional, nur Räume mit Klimaanlage).

Vorbild: eine gewachsene IR-Klimasteuerung (Automation + Skript je Kühlstufe + Skript „PV-Vorrang“).
Ausgabe: blueprints/automation/ha_heizung_universal/klimaautomatik.yaml
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from yamlgen import Inp, dump  # noqa: E402
from build_raumheizung import sel_entity, sel_number, c  # noqa: E402

BASIS = Path(__file__).resolve().parent.parent
ZIELDATEI = BASIS / "blueprints" / "automation" / "ha_heizung_universal" / "klimaautomatik.yaml"


def inputs():
    return {
        "geraete": {"name": "Raum und Klimaanlage", "icon": "mdi:air-conditioner", "input": {
            "raum_name": {"name": "Raumname", "default": "Raum", "selector": {"text": {}}},
            "raum_schluessel": {"name": "Raumkennung", "default": "raum", "description": "Wie in der Raumheizungssteuerung, z. B. `wohnzimmer`.", "selector": {"text": {}}},
            "klima_sender": {"name": "IR-Sender der Klimaanlage", "description": "Remote-Entität (z. B. Broadlink), die die gelernten Klimabefehle sendet.",
                             "selector": sel_entity("remote")},
            "ir_geraet": {"name": "Gerätename der gelernten Befehle", "default": "klima",
                          "description": "Der beim Anlernen verwendete Gerätename (Parameter „device“ von remote.send_command).", "selector": {"text": {}}},
            "raumfuehler": {"name": "Raumtemperatur", "description": "Externer Raumfühler oder das Better Thermostat des Raums.",
                            "selector": {"entity": {"filter": [{"domain": ["sensor"], "device_class": ["temperature"]}, {"domain": ["climate"]}]}}},
            "aussentemperatur": {"name": "Außentemperatur", "selector": sel_entity("sensor", device_class="temperature")},
            "fensterkontakte": {"name": "Fensterkontakte für die Klimaanlage", "default": [],
                                "description": "Kontakte, deren Öffnen die Klimaanlage pausiert (können andere sein als bei der Heizung).",
                                "selector": {"entity": {"multiple": True, "filter": [{"domain": ["binary_sensor"], "device_class": ["window", "door", "opening"]},
                                                                                {"domain": ["input_boolean"]}]}}},
        }},
        "befehle": {"name": "IR-Befehle", "icon": "mdi:remote", "collapsed": True,
                    "description": ("Namen der gelernten Befehle. `{stufe}` wird durch die Temperaturstufe (z. B. 20) ersetzt, `{luefter}` durch die "
                                    "Lüfterstufe. Viele Klimaanlagen senden vollständige Zustände (Modus + Temperatur + Lüfter in einem Befehl) – "
                                    "dann je Temperatur einen Befehl anlernen, z. B. `power_20`. Der IR-Sender wird nur in dieser Automation gewählt; "
                                    "das PV-Überschussheizen verwendet denselben Sender und die hier eingetragenen Heizbefehle."), "input": {
            "befehl_kuehlen": {"name": "Kühlen mit Stufe", "default": "power_{stufe}", "selector": {"text": {}}},
            "befehl_kuehlen_zusatz": {"name": "Zusatzbefehle nach dem Kühlbefehl (optional)", "default": "eco_{stufe}",
                                      "description": ("Werden nacheinander im Abstand von 1 s nach dem Kühlbefehl gesendet. Mehrere durch Komma trennen, "
                                                      "z. B. `eco_{stufe}, display_off`. Leer lassen, wenn nicht benötigt."), "selector": {"text": {}}},
            "befehl_aus": {"name": "Ausschalten", "default": "power_off", "selector": {"text": {}}},
            "luefter": {"name": "Lüfterstufe (optional)", "default": "",
                        "description": "Wird für `{luefter}` in den Befehlsnamen eingesetzt, z. B. `auto`, `niedrig`, `hoch`. Leer lassen, wenn die Befehle keine Lüfterstufe enthalten.",
                        "selector": {"text": {}}},
            "befehl_heizen": {"name": "Heizen (vollständiger Zustand, z. B. Heizen 24 °C)", "default": "heizen_24",
                              "description": "Wird nur vom PV-Überschussheizen dieses Raums verwendet. `{stufe}` wird durch dessen Heizstufe ersetzt (z. B. `heizen_{stufe}`).",
                              "selector": {"text": {}}},
            "befehl_heizen_aus": {"name": "Heizen aus", "default": "heizen_24_off",
                                  "description": "Wird nur vom PV-Überschussheizen dieses Raums verwendet.", "selector": {"text": {}}},
            "ir_konfiguration": {"name": "Gemeinsame IR-Konfiguration (input_text, optional)", "default": [],
                                 "description": ("Hier veröffentlicht die Klimaautomatik Sender, Gerätename und Heizbefehle. Das PV-Überschussheizen liest sie "
                                                 "von dort. Bei einem Wechsel des IR-Senders genügt deshalb die Änderung in dieser Automation."),
                                 "selector": sel_entity("input_text")},
            "stufe_min": {"name": "Niedrigste Stufe", "default": 16, "selector": sel_number(16, 30, 1, "°C", "box")},
            "stufe_max": {"name": "Höchste Stufe", "default": 23, "selector": sel_number(16, 30, 1, "°C", "box")},
        }},
        "strom": {"name": "Stromversorgung und Rückmeldung (optional)", "icon": "mdi:power-socket-de", "collapsed": True,
                  "description": ("Für eine schaltbare Messsteckdose vor der Klimaanlage. Die Steckdose bleibt dauerhaft eingeschaltet: Vor jedem IR-Befehl "
                                  "wird sie bei Bedarf eingeschaltet (danach kurze Wartezeit zum Hochfahren), nach versehentlichem Ausschalten wieder "
                                  "eingeschaltet. Ausgeschaltet wird sie von dieser Automation nie. Mit Leistungsmessung prüft die Automation, ob die "
                                  "Klimaanlage einen Befehl wirklich ausgeführt hat, wiederholt ihn sonst einmal und meldet sich, wenn auch das nicht wirkt."),
                  "input": {
            "klima_steckdose": {"name": "Steckdose der Klimaanlage (optional)", "default": [], "selector": sel_entity("switch")},
            "steckdose_halten": {"name": "Steckdose dauerhaft eingeschaltet halten", "default": True,
                                 "description": "Wird die Steckdose ausgeschaltet, schaltet die Automation sie nach 1 Minute wieder ein und stellt den Klimazustand wieder her.",
                                 "selector": {"boolean": {}}},
            "vorlauf_s": {"name": "Wartezeit nach dem Einschalten der Steckdose", "default": 30,
                          "description": "So lange braucht die Klimaanlage nach dem Einschalten, bis sie IR-Befehle annimmt.", "selector": sel_number(5, 120, 5, "s", "box")},
            "klima_leistung": {"name": "Leistungsmessung der Klimaanlage (optional)", "default": [],
                               "description": "Meist der Leistungssensor derselben Messsteckdose.", "selector": sel_entity("sensor", device_class="power")},
            "laeuft_ab_w": {"name": "Klimaanlage gilt als laufend ab", "default": 15,
                            "description": "Deutlich über dem Bereitschaftsverbrauch (meist 1–3 W) und unter der Leistung des Lüfters allein.",
                            "selector": sel_number(2, 500, 1, "W", "box")},
            "pruef_ein_min": {"name": "Rückmeldung nach dem Einschalten prüfen nach", "default": 3, "selector": sel_number(1, 30, 1, "min", "box")},
            "pruef_aus_min": {"name": "Rückmeldung nach dem Ausschalten prüfen nach", "default": 10,
                              "description": "Großzügig wählen: Viele Klimaanlagen trocknen nach dem Ausschalten noch einige Minuten mit dem Lüfter.",
                              "selector": sel_number(1, 60, 1, "min", "box")},
        }},
        "automatik": {"name": "Automatik-Kühlen", "icon": "mdi:snowflake-thermometer", "collapsed": True, "input": {
            "ein_ueber": {"name": "Einschalten ab Ziel plus", "default": 0.5, "selector": sel_number(0, 3, 0.1, "K")},
            "aus_unter": {"name": "Ausschalten ab Ziel minus", "default": 0.2, "selector": sel_number(0, 3, 0.1, "K")},
            "aussen_min": {"name": "Kühlen erst ab Außentemperatur", "default": 16, "selector": sel_number(0, 30, 0.5, "°C")},
            "fenster_minuten": {"name": "Pause, wenn ein Fenster offen ist seit", "default": 3, "selector": sel_number(0, 30, 1, "min", "box")},
            "stufe_sehr_warm_ab": {"name": "Raum wärmer als … → Stufe", "default": 24, "selector": sel_number(18, 35, 0.5, "°C", "box")},
            "stufe_sehr_warm": {"name": "… dann Stufe", "default": 17, "selector": sel_number(16, 30, 1, "°C", "box")},
            "stufe_warm_ab": {"name": "Raum wärmer als … → Stufe", "default": 23, "selector": sel_number(18, 35, 0.5, "°C", "box")},
            "stufe_warm": {"name": "… dann Stufe", "default": 18, "selector": sel_number(16, 30, 1, "°C", "box")},
            "stufe_mild_ab": {"name": "Raum mindestens … → Stufe", "default": 22, "selector": sel_number(18, 35, 0.5, "°C", "box")},
            "stufe_mild": {"name": "… dann Stufe (sonst: Zieltemperatur)", "default": 20, "selector": sel_number(16, 30, 1, "°C", "box")},
        }},
        "heizung": {"name": "Zusammenarbeit mit der Raumheizung", "icon": "mdi:radiator", "collapsed": True,
                    "description": "Kühlen ist nur erlaubt, wenn die Heizung dieses Raums in einem der gewählten Profile steht (wie im Bestand: Sommer oder Aus) oder der globale Schalter „Heizung Aus“ an ist.", "input": {
            "heizprofil": {"name": "Heizprofil-Auswahl der Raumheizung", "selector": sel_entity("input_select")},
            "kuehl_profile": {"name": "Kühlen erlaubt in den Heizprofilen", "default": ["Sommer", "Aus"],
                              "selector": {"select": {"multiple": True, "mode": "list", "options": ["Komfort", "Übergang", "Urlaub", "Sommer", "Aus"]}}},
            "haus_heizung_aus": {"name": "Globaler Schalter „Heizung Aus“ (optional)", "default": [], "selector": sel_entity("input_boolean")},
        }},
        "helfer": {"name": "Raum-Helfer der Klimaanlage", "icon": "mdi:tune-variant", "collapsed": True,
                   "description": "Legt der Einrichtungsassistent an. Die Dashboard-Karte bedient die Klimaanlage nur über diese Helfer.", "input": {
            "klima_modus": {"name": "Klima-Modus (input_select: Aus, Automatik Kühlen, Manuell Kühlen)", "selector": sel_entity("input_select")},
            "zieltemperatur": {"name": "Automatik-Zieltemperatur (input_number)", "selector": sel_entity("input_number")},
            "manuelle_stufe": {"name": "Manuelle Stufe (input_number)", "description": "Eine Änderung schaltet auf „Manuell Kühlen“ und sendet diese Stufe.",
                               "default": [], "selector": sel_entity("input_number")},
            "letzte_stufe": {"name": "Zuletzt gesendete Stufe (input_number)", "selector": sel_entity("input_number")},
            "klima_aktiv": {"name": "Kühlbefehl aktiv (input_boolean)", "selector": sel_entity("input_boolean")},
            "modus_vor_fenster": {"name": "Speicher „Modus vor Fenster“ (input_text)", "selector": sel_entity("input_text")},
        }},
        "pv": {"name": "Zusammenarbeit mit PV-Überschussheizen", "icon": "mdi:solar-power-variant", "collapsed": True,
               "description": (
                   "Nur wenn in diesem Raum die Blueprint „PV-Überschussheizen“ läuft. Jede Klimabedienung beendet zuerst eine laufende "
                   "PV-Heizsitzung (Vorrang der Bedienung). Fällt die PV-Automation aus, während die Klimaanlage für PV heizt, schaltet "
                   "diese Automation die Klimaanlage nach spätestens 2 Minuten sicher ab (Notrückgabe)."), "input": {
            "pv_aktiv": {"name": "PV-Überschussheizen in diesem Raum", "default": False, "selector": {"boolean": {}}},
            "pv_automation": {"name": "PV-Überschussheizen-Automation dieses Raums", "default": [], "visible": {"field": "pv_aktiv", "value": True},
                              "selector": sel_entity("automation")},
            "pv_heizfreigabe": {"name": "PV-Heizfreigabe (input_boolean)", "default": [], "visible": {"field": "pv_aktiv", "value": True},
                                "selector": sel_entity("input_boolean")},
            "pv_heizbefehl": {"name": "PV: Heizbefehl aktiv (input_boolean)", "default": [], "visible": {"field": "pv_aktiv", "value": True},
                              "selector": sel_entity("input_boolean")},
            "pv_auftrag": {"name": "PV: IR-Auftrag offen (input_boolean)", "default": [], "visible": {"field": "pv_aktiv", "value": True},
                           "selector": sel_entity("input_boolean")},
            "pv_verantwortung": {"name": "PV: weitere Verantwortungs-Helfer (Regelung aktiv, Startvorbereitung)", "default": [],
                                 "visible": {"field": "pv_aktiv", "value": True},
                                 "selector": {"entity": {"multiple": True, "filter": [{"domain": ["input_boolean"]}]}}},
            "pv_freigabe": {"name": "PV-Sicherheitsfreigabe (Timer)", "default": [], "visible": {"field": "pv_aktiv", "value": True},
                            "selector": sel_entity("timer")},
            "pv_status": {"name": "PV-Status-Text (input_text)", "default": [], "visible": {"field": "pv_aktiv", "value": True},
                          "selector": sel_entity("input_text")},
        }},
        "erweitert": {"name": "Erweitert", "icon": "mdi:cog", "collapsed": True, "input": {
            "ausgabe_modus": {"name": "Betriebsart", "default": "produktiv", "selector": {"select": {"mode": "list", "options": [
                {"value": "produktiv", "label": "Normalbetrieb"}, {"value": "test", "label": "Testbetrieb (Entscheidung nur ins Logbuch)"}]}}},
        }},
    }


def variablen():
    v = {k: Inp(k) for k in ["raum_name", "raum_schluessel", "klima_sender", "ir_geraet", "raumfuehler", "fensterkontakte",
                             "befehl_kuehlen", "befehl_kuehlen_zusatz", "befehl_aus", "luefter", "befehl_heizen", "befehl_heizen_aus",
                             "ir_konfiguration", "stufe_min", "stufe_max",
                             "ein_ueber", "aus_unter", "aussen_min", "stufe_sehr_warm_ab", "stufe_sehr_warm", "stufe_warm_ab",
                             "stufe_warm", "stufe_mild_ab", "stufe_mild", "heizprofil", "kuehl_profile", "haus_heizung_aus",
                             "klima_modus", "zieltemperatur", "manuelle_stufe", "letzte_stufe", "klima_aktiv", "modus_vor_fenster",
                             "pv_aktiv", "pv_automation", "pv_heizfreigabe", "pv_heizbefehl", "pv_auftrag", "pv_verantwortung",
                             "pv_freigabe", "pv_status", "ausgabe_modus",
                             "klima_steckdose", "steckdose_halten", "vorlauf_s", "klima_leistung", "laeuft_ab_w", "pruef_ein_min", "pruef_aus_min"]}
    v["aussen"] = Inp("aussentemperatur")
    v["steckdose_ok"] = "{{ klima_steckdose is string and klima_steckdose != '' }}"
    v["leistung_ok"] = "{{ klima_leistung is string and klima_leistung != '' }}"
    v["produktiv"] = "{{ ausgabe_modus == 'produktiv' }}"
    v["gesetzt"] = None
    del v["gesetzt"]
    v["pv_ok"] = ("{{ pv_aktiv and pv_heizbefehl is string and pv_heizbefehl != '' and pv_auftrag is string and pv_auftrag != '' "
                  "and pv_freigabe is string and pv_freigabe != '' }}")
    v["ir_cfg_text"] = ("{{ ('v=1|s=' ~ klima_sender ~ '|g=' ~ ir_geraet ~ '|h=' ~ (befehl_heizen | replace('{luefter}', luefter)) "
                        "~ '|ha=' ~ (befehl_heizen_aus | replace('{luefter}', luefter)))[:255] }}")
    v["normal_ids"] = ["raumtemperatur", "aussentemperatur", "modus", "zieltemperatur", "klima_aktiv", "heizprofil"]
    return v


def trigger():
    return [
        {"alias": "Nach dem Start von Home Assistant: vorherigen Klimazustand sicher wiederherstellen", "trigger": "homeassistant", "event": "start", "id": "ha_start"},
        {"alias": "Nach dem Neuladen der Automationen: IR-Konfiguration veröffentlichen", "trigger": "event", "event_type": "automation_reloaded", "id": "reload"},
        {"alias": "Raumtemperatur geändert", "trigger": "state", "entity_id": Inp("raumfuehler"), "id": "raumtemperatur"},
        {"alias": "Außentemperatur geändert", "trigger": "state", "entity_id": Inp("aussentemperatur"), "id": "aussentemperatur"},
        {"alias": "Klima-Modus geändert", "trigger": "state", "entity_id": Inp("klima_modus"), "id": "modus"},
        {"alias": "Automatik-Zieltemperatur geändert", "trigger": "state", "entity_id": Inp("zieltemperatur"), "id": "zieltemperatur"},
        {"alias": "Manuelle Stufe gewählt", "trigger": "state", "entity_id": Inp("manuelle_stufe"), "to": None, "id": "manuell"},
        {"alias": "Kühlbefehl-Helfer geändert", "trigger": "state", "entity_id": Inp("klima_aktiv"), "id": "klima_aktiv"},
        {"alias": "Heizprofil der Raumheizung geändert", "trigger": "state", "entity_id": Inp("heizprofil"), "id": "heizprofil"},
        {"alias": "Globaler Schalter „Heizung Aus“ geändert", "trigger": "state", "entity_id": Inp("haus_heizung_aus"), "id": "heizprofil"},
        {"alias": "Ein Fenster ist seit der Pausenzeit offen", "trigger": "state", "entity_id": Inp("fensterkontakte"), "to": "on",
         "for": {"minutes": Inp("fenster_minuten")}, "id": "fenster_offen"},
        {"alias": "Ein Fenster wurde geschlossen", "trigger": "state", "entity_id": Inp("fensterkontakte"), "from": "on", "to": "off", "id": "fenster_geschlossen"},
        {"alias": "PV-Notrückgabe: minütliche Sicherheitsprüfung", "trigger": "time_pattern", "minutes": "/1", "id": "pv_pruefung", "enabled": Inp("pv_aktiv")},
        {"alias": "PV-Notrückgabe: PV-Automation ausgeschaltet", "trigger": "state", "entity_id": Inp("pv_automation"), "to": "off", "id": "pv_pruefung", "enabled": Inp("pv_aktiv")},
        {"alias": "Steckdose der Klimaanlage seit 1 Minute aus", "trigger": "state", "entity_id": Inp("klima_steckdose"), "to": "off",
         "for": {"minutes": 1}, "id": "steckdose_aus"},
        {"alias": "Rückmeldung: Kühlbefehl seit der Prüfzeit aktiv", "trigger": "state", "entity_id": Inp("klima_aktiv"), "to": "on",
         "for": {"minutes": Inp("pruef_ein_min")}, "id": "pruef_ein"},
        {"alias": "Rückmeldung: Kühlbefehl seit der doppelten Prüfzeit aktiv (nach der Wiederholung)", "trigger": "state", "entity_id": Inp("klima_aktiv"), "to": "on",
         "for": DOPPELT.format("pruef_ein_tv"), "id": "pruef_ein2"},
        {"alias": "Rückmeldung: Klimaanlage seit der Prüfzeit ausgeschaltet", "trigger": "state", "entity_id": Inp("klima_aktiv"), "to": "off",
         "for": {"minutes": Inp("pruef_aus_min")}, "id": "pruef_aus"},
        {"alias": "Rückmeldung: Klimaanlage seit der doppelten Prüfzeit ausgeschaltet (nach der Wiederholung)", "trigger": "state", "entity_id": Inp("klima_aktiv"), "to": "off",
         "for": DOPPELT.format("pruef_aus_tv"), "id": "pruef_aus2"},
    ]


# Doppelte Prüfzeit als Trigger-Vorlage (Trigger-Variablen sind dort verfügbar)
DOPPELT = "{{{{ '%02d:%02d:00' % (({0} | int * 2) // 60, ({0} | int * 2) % 60) }}}}"


def strom_sichern():
    """Stromversorgung vor einem IR-Befehl sicherstellen: Steckdose einschalten, Bestätigung abwarten, Klimaanlage hochfahren lassen."""
    return {"alias": "Stromversorgung der Klimaanlage sicherstellen", "if": [c(
        "Steckdose eingerichtet und nicht eingeschaltet", "{{ steckdose_ok and not is_state(klima_steckdose, 'on') }}")], "then": [
        {"alias": "Steckdose einschalten", "action": "switch.turn_on", "target": {"entity_id": "{{ klima_steckdose }}"}, "continue_on_error": True},
        {"alias": "Höchstens 20 s warten, bis die Steckdose „an“ meldet", "wait_template": "{{ is_state(klima_steckdose, 'on') }}", "timeout": {"seconds": 20}},
        {"alias": "Steckdose meldet nicht „an“?", "if": [c("Steckdose nicht eingeschaltet", "{{ not is_state(klima_steckdose, 'on') }}")], "then": [
            {"alias": "Dauerhafte Meldung: Klimabefehl nicht gesendet", "action": "persistent_notification.create", "data": {
                "notification_id": "{{ 'hz_klima_ir_' ~ raum_schluessel }}", "title": "Klima {{ raum_name }}: IR-Befehl nicht gesendet",
                "message": ("Die Steckdose {{ klima_steckdose }} der Klimaanlage lässt sich nicht einschalten (Zustand: {{ states(klima_steckdose) }}). "
                            "Der Klimabefehl wurde NICHT gesendet; der Zustand der Klimaanlage wurde nicht verändert.")}},
            {"alias": "Im Logbuch festhalten", "action": "logbook.log", "data": {
                "name": "{{ raum_name }} Klima", "message": "Steckdose lässt sich nicht einschalten – Befehl nicht gesendet.", "entity_id": "{{ klima_aktiv }}"}},
            {"alias": "Lauf mit Fehler beenden", "stop": "Steckdose der Klimaanlage nicht eingeschaltet", "error": True}]},
        {"alias": "Im Logbuch festhalten", "action": "logbook.log", "data": {
            "name": "{{ raum_name }} Klima", "message": "Steckdose der Klimaanlage war aus – eingeschaltet, {{ vorlauf_s | int }} s Wartezeit vor dem IR-Befehl.",
            "entity_id": "{{ klima_aktiv }}"}},
        {"alias": "Klimaanlage nach dem Einschalten hochfahren lassen", "delay": {"seconds": "{{ vorlauf_s | int }}"}}]}


def ir_roh(alias, befehl_tpl):
    return {"alias": alias, "action": "remote.send_command", "target": {"entity_id": "{{ klima_sender }}"},
            "data": {"device": "{{ ir_geraet }}", "command": befehl_tpl}}


def ir_senden(alias, befehl_tpl):
    """Sendet nur, wenn der IR-Sender eingeschaltet und erreichbar ist. Sonst: Meldung und Abbruch – kein vorgetäuschter Erfolg."""
    return {"alias": alias + " (nur bei erreichbarem IR-Sender)", "sequence": [
        strom_sichern(),
        {"alias": "IR-Sender prüfen", "if": [c("IR-Sender nicht eingeschaltet oder nicht erreichbar", "{{ not is_state(klima_sender, 'on') }}")],
         "then": [
             {"alias": "Dauerhafte Meldung: Klimabefehl nicht gesendet", "action": "persistent_notification.create", "data": {
                 "notification_id": "{{ 'hz_klima_ir_' ~ raum_schluessel }}", "title": "Klima {{ raum_name }}: IR-Befehl nicht gesendet",
                 "message": ("Der IR-Sender {{ klima_sender }} ist nicht erreichbar oder ausgeschaltet (Zustand: {{ states(klima_sender) }}). "
                             "Der Klimabefehl wurde NICHT gesendet; der Zustand der Klimaanlage wurde nicht verändert.")}},
             {"alias": "Im Logbuch festhalten", "action": "logbook.log", "data": {
                 "name": "{{ raum_name }} Klima", "message": "IR-Sender nicht erreichbar – Befehl nicht gesendet.", "entity_id": "{{ klima_aktiv }}"}},
             {"alias": "Lauf mit Fehler beenden", "stop": "IR-Senden fehlgeschlagen: Sender nicht erreichbar", "error": True}]},
        ir_roh(alias, befehl_tpl)]}


def stufe_senden(stufe_tpl):
    """Entspricht einem Skript <raum>_klima_<stufe>: PV-Vorrang, Kühlbefehl, 1 s, Zusatzbefehl, letzte Stufe merken."""
    return [
        {"alias": "Bedienung hat Vorrang: laufendes PV-Heizen zuerst beenden", "if": [c(
            "PV-Heizen in diesem Raum freigegeben oder aktiv",
            "{{ pv_ok and (is_state(pv_heizfreigabe, 'on') or is_state(pv_heizbefehl, 'on') or is_state(pv_auftrag, 'on') "
            "or pv_verantwortung | select('is_state', 'on') | list | count > 0) }}")], "then": [
            {"alias": "PV-Heizfreigabe ausschalten (die PV-Automation beendet daraufhin ihre Sitzung)", "action": "input_boolean.turn_off",
             "target": {"entity_id": "{{ pv_heizfreigabe }}"}},
            {"alias": "Höchstens 30 s auf die Rückgabe durch die PV-Automation warten",
             "wait_template": "{{ is_state(pv_heizbefehl, 'off') and is_state(pv_auftrag, 'off') and pv_verantwortung | select('is_state', 'on') | list | count == 0 }}",
             "timeout": {"seconds": 30}}]},
        ir_senden("Kühlbefehl mit Stufe senden", "{{ befehl_kuehlen | replace('{stufe}', (" + stufe_tpl + ") | string) | replace('{luefter}', luefter) }}"),
        {"alias": "Zusatzbefehle nacheinander senden, falls eingerichtet (mehrere durch Komma getrennt, z. B. eco_{stufe}, display_off)",
         "repeat": {"for_each": "{{ (befehl_kuehlen_zusatz | string).split(',') | map('trim') | reject('eq', '') | list }}", "sequence": [
             {"alias": "1 s Abstand zwischen IR-Befehlen", "delay": {"seconds": 1}},
             ir_senden("Zusatzbefehl mit Stufe senden", "{{ repeat.item | replace('{stufe}', (" + stufe_tpl + ") | string) | replace('{luefter}', luefter) }}")]}},
        {"alias": "Gesendete Stufe merken", "action": "input_number.set_value", "target": {"entity_id": "{{ letzte_stufe }}"},
         "data": {"value": "{{ " + stufe_tpl + " }}"}},
    ]


def aus_senden():
    return [
        {"alias": "Bedienung hat Vorrang: laufendes PV-Heizen zuerst beenden", "if": [c(
            "PV-Heizen in diesem Raum freigegeben oder aktiv",
            "{{ pv_ok and (is_state(pv_heizfreigabe, 'on') or is_state(pv_heizbefehl, 'on') or is_state(pv_auftrag, 'on')) }}")], "then": [
            {"alias": "PV-Heizfreigabe ausschalten", "action": "input_boolean.turn_off", "target": {"entity_id": "{{ pv_heizfreigabe }}"}},
            {"alias": "Höchstens 30 s auf die PV-Rückgabe warten",
             "wait_template": "{{ is_state(pv_heizbefehl, 'off') and is_state(pv_auftrag, 'off') }}", "timeout": {"seconds": 30}}]},
        ir_senden("Klimaanlage per IR ausschalten", "{{ befehl_aus | replace('{luefter}', luefter) }}"),
    ]


ENTSCHEIDUNG = r"""{%- set normal = trigger.id in normal_ids and trigger.from_state is not none -%}
{%- if trigger.id == 'ha_start' -%}neustart
{%- elif trigger.id == 'pv_pruefung' -%}{{ 'pv_rueckgabe' if pv_notfall else 'keine' }}
{%- elif trigger.id == 'steckdose_aus' -%}{{ 'steckdose_ein' if steckdose_ok and steckdose_halten and is_state(klima_steckdose, 'off') else 'keine' }}
{%- elif trigger.id in ['pruef_ein', 'pruef_ein2'] -%}
{%- if not (leistung_gueltig and aktiv_jetzt and stufe_jetzt > 0 and not pv_belegt) -%}keine
{%- elif laeuft -%}{{ 'rueckmeldung_ok' if trigger.id == 'pruef_ein2' else 'keine' }}
{%- else -%}{{ 'nachsenden_ein' if trigger.id == 'pruef_ein' else 'fehler_ein' }}{%- endif -%}
{%- elif trigger.id in ['pruef_aus', 'pruef_aus2'] -%}
{%- if not (leistung_gueltig and not aktiv_jetzt and not pv_belegt) -%}keine
{%- elif not laeuft -%}{{ 'rueckmeldung_ok' if trigger.id == 'pruef_aus2' else 'keine' }}
{%- else -%}{{ 'nachsenden_aus' if trigger.id == 'pruef_aus' else 'fehler_aus' }}{%- endif -%}
{%- elif trigger.id == 'fenster_offen' and modus_jetzt != 'Aus' -%}fenster_pause
{%- elif trigger.id == 'fenster_geschlossen' and not fenster_offen and kuehl_profil_ok and aussen_temp >= aussen_min | float and gespeicherter_modus == 'Automatik Kühlen' -%}fenster_wiederherstellen
{%- elif trigger.id == 'modus' and normal and modus_jetzt == 'Aus' and (aktiv_jetzt or stufe_jetzt > 0) -%}aus
{%- elif normal and not fenster_offen and not klima_erlaubt and modus_jetzt != 'Aus' -%}sperre_aus
{%- elif trigger.id == 'manuell' and trigger.from_state is not none and is_number(trigger.to_state.state) and klima_erlaubt -%}manuell
{%- elif normal and klima_erlaubt and modus_jetzt == 'Automatik Kühlen' and raum_temp >= ein_ab and (not aktiv_jetzt or stufe_jetzt != (auto_stufe | int)) -%}kuehlen_ein
{%- elif normal and klima_erlaubt and modus_jetzt == 'Automatik Kühlen' and aktiv_jetzt and raum_temp <= aus_ab -%}kuehlen_aus
{%- else -%}keine{%- endif -%}"""


def aktionen():
    a = []
    a.append({"alias": "Gemeinsame IR-Konfiguration für das PV-Überschussheizen veröffentlichen", "if": [c(
        "Helfer vorhanden und Inhalt geändert",
        "{{ ir_konfiguration is string and ir_konfiguration != '' and states(ir_konfiguration) != ir_cfg_text }}")],
        "then": [{"alias": "IR-Konfiguration schreiben", "action": "input_text.set_value", "target": {"entity_id": "{{ ir_konfiguration }}"},
                  "data": {"value": "{{ ir_cfg_text }}"}}]})
    a.append({"alias": "Aktuelle Werte lesen", "variables": {
        "raum_temp": ("{%- set s = states(raumfuehler) if raumfuehler.startswith('sensor.') else state_attr(raumfuehler, 'current_temperature') -%}"
                      "{{ s | float(0) }}"),
        "raum_gueltig": ("{%- set s = states(raumfuehler) if raumfuehler.startswith('sensor.') else state_attr(raumfuehler, 'current_temperature') -%}"
                         "{{ is_number(s) }}"),
        "aussen_temp": "{{ states(aussen) | float(0) }}",
        "klima_ziel": "{{ states(zieltemperatur) | float(22) }}",
        "stufe_jetzt": "{{ states(letzte_stufe) | int(0) }}",
        "modus_jetzt": "{{ states(klima_modus) }}",
        "aktiv_jetzt": "{{ is_state(klima_aktiv, 'on') }}",
        "fenster_offen": "{{ fensterkontakte | select('is_state', 'on') | list | count > 0 }}",
        "haus_aus": "{{ haus_heizung_aus is string and haus_heizung_aus != '' and is_state(haus_heizung_aus, 'on') }}",
        "kuehl_profil_ok": "{{ states(heizprofil) in kuehl_profile or (haus_heizung_aus is string and haus_heizung_aus != '' and is_state(haus_heizung_aus, 'on')) }}",
        "gespeicherter_modus": "{% set s = states(modus_vor_fenster) %}{{ s.split('|')[0] if '|' in s else '' }}",
        "gespeichertes_ziel": "{% set s = states(modus_vor_fenster) %}{{ s.split('|')[2] | float(22) if '|' in s else states(zieltemperatur) | float(22) }}",
        "klima_erlaubt": ("{{ (states(heizprofil) in kuehl_profile or (haus_heizung_aus is string and haus_heizung_aus != '' and is_state(haus_heizung_aus, 'on'))) "
                          "and not (fensterkontakte | select('is_state', 'on') | list | count > 0) and states(aussen) | float(0) >= aussen_min | float }}"),
        "ein_ab": "{{ states(zieltemperatur) | float(22) + ein_ueber | float }}",
        "aus_ab": "{{ states(zieltemperatur) | float(22) - aus_unter | float }}",
        "auto_stufe": ("{%- set t = raum_temp | float -%}{%- set z = states(zieltemperatur) | float(22) -%}"
                       "{%- set s = (stufe_sehr_warm if t > stufe_sehr_warm_ab | float else (stufe_warm if t > stufe_warm_ab | float else (stufe_mild if t >= stufe_mild_ab | float else z))) | int -%}"
                       "{{ [[s, stufe_min | int] | max, stufe_max | int] | min }}"),
        "leistung_gueltig": "{{ leistung_ok and is_number(states(klima_leistung)) }}",
        "laeuft": "{{ leistung_ok and states(klima_leistung) | float(0) >= laeuft_ab_w | float }}",
        "pv_belegt": ("{{ pv_ok and (is_state(pv_heizbefehl, 'on') or is_state(pv_auftrag, 'on') "
                      "or pv_verantwortung | select('is_state', 'on') | list | count > 0) }}"),
        "pv_notfall": ("{{ pv_ok and (is_state(pv_heizbefehl, 'on') or is_state(pv_auftrag, 'on')) and ("
                       "(pv_automation is string and pv_automation != '' and is_state(pv_automation, 'off')) or "
                       "(is_state(pv_freigabe, 'idle') and states[pv_freigabe] is not none and (now() - states[pv_freigabe].last_changed).total_seconds() >= 90)) }}"),
    }})
    a.append({"alias": "Sicherheitsabbruch bei ungültigen Pflichtsensoren (außer Neustart und PV-Prüfung)", "if": [c(
        "Raum- oder Außentemperatur ungültig",
        "{{ trigger.id not in ['ha_start', 'pv_pruefung', 'steckdose_aus', 'pruef_ein', 'pruef_ein2', 'pruef_aus', 'pruef_aus2'] "
        "and (not raum_gueltig or states(aussen) in ['unknown', 'unavailable', '']) }}")],
        "then": [{"alias": "Abbruch im Logbuch festhalten", "action": "logbook.log", "data": {
            "name": "{{ raum_name }} Klima", "message": "Abgebrochen: Raum- oder Außentemperatur ist nicht verfügbar. Keine Moduswechsel, keine Einschaltung.",
            "entity_id": "{{ klima_aktiv }}"}},
                 {"alias": "Sicher beenden", "stop": "Pflichtsensoren ungültig"}]})
    a.append({"alias": "Erstwiederherstellung eines Helfers nach dem Neustart ist keine echte Änderung", "if": [c(
        "Trigger ohne Vorzustand", "{{ trigger.id not in ['ha_start', 'pv_pruefung'] and trigger.from_state is none }}")],
        "then": [{"alias": "Sicher beenden", "stop": "Erstwiederherstellung eines Helfers"}]})
    a.append({"alias": "Entscheidung genau einmal bestimmen (Reihenfolge wie im Bestand)", "variables": {"entscheidung": ENTSCHEIDUNG}})
    a.append({"alias": "Nichts zu tun", "condition": "template", "value_template": "{{ entscheidung != 'keine' }}"})
    a.append({"alias": "Testbetrieb: Entscheidung nur protokollieren", "if": [c("Testbetrieb und kein Neustartfall", "{{ not produktiv and entscheidung != 'neustart' }}")],
              "then": [{"alias": "Geplante Aktion ins Logbuch", "action": "logbook.log", "data": {
                  "name": "{{ raum_name }} Klima (Test)",
                  "message": "Geplant: {{ entscheidung }} · Raum {{ raum_temp }} °C · Ziel {{ klima_ziel }} · Stufe {{ auto_stufe }} · Modus {{ modus_jetzt }}",
                  "entity_id": "{{ klima_aktiv }}"}},
                  {"alias": "Testlauf beenden", "stop": "Testbetrieb"}]})
    zweige = []
    zweige.append({"alias": "Neustart: nur wiederherstellen, wenn die Klimaanlage vorher aktiv war", "conditions": [c("Neustart", "{{ entscheidung == 'neustart' }}")],
                   "sequence": [
        {"alias": "Steckdose nach dem Neustart einschalten, falls sie aus ist (dauerhaft eingeschaltet halten)", "if": [c(
            "Steckdose eingerichtet, halten gewünscht und aus", "{{ steckdose_ok and steckdose_halten and is_state(klima_steckdose, 'off') and produktiv }}")],
         "then": [{"alias": "Steckdose einschalten", "action": "switch.turn_on", "target": {"entity_id": "{{ klima_steckdose }}"}, "continue_on_error": True}]},
        {"alias": "Höchstens 2:30 min auf gültige Pflichtdaten warten",
         "wait_template": ("{%- set s = states(raumfuehler) if raumfuehler.startswith('sensor.') else state_attr(raumfuehler, 'current_temperature') -%}"
                           "{{ is_number(s) and states(aussen) not in ['unknown', 'unavailable', ''] "
                           "and fensterkontakte | reject('is_state', 'on') | reject('is_state', 'off') | list | count == 0 "
                           "and states(heizprofil) not in ['unknown', 'unavailable'] and states(klima_modus) not in ['unknown', 'unavailable'] "
                           "and states(klima_aktiv) not in ['unknown', 'unavailable'] and states(zieltemperatur) not in ['unknown', 'unavailable'] }}"),
         "timeout": {"minutes": 2, "seconds": 30}, "continue_on_timeout": True},
        {"alias": "Wurden gültige Daten erreicht?", "if": [c("Warten erfolgreich", "{{ wait.completed }}")], "then": [
            {"alias": "Zustand vor dem Neustart auswerten", "choose": [
                {"alias": "Klimaanlage war vorher aus", "conditions": [c("Kühlbefehl-Helfer aus", "{{ is_state(klima_aktiv, 'off') }}")],
                 "sequence": [{"alias": "Kein IR-Befehl – im Logbuch vermerken", "action": "logbook.log", "data": {
                     "name": "{{ raum_name }} Klima Neustart", "message": "Klimaanlage war vor dem Neustart aus. Kein IR-Befehl.", "entity_id": "{{ klima_aktiv }}"}}]},
                {"alias": "Klimaanlage war vorher an", "conditions": [c("Kühlbefehl-Helfer an", "{{ is_state(klima_aktiv, 'on') }}")],
                 "sequence": [
                     {"alias": "Frische Werte nach dem Neustart", "variables": {
                         "r_raum": "{%- set s = states(raumfuehler) if raumfuehler.startswith('sensor.') else state_attr(raumfuehler, 'current_temperature') -%}{{ s | float(0) }}",
                         "r_erlaubt": ("{{ (states(heizprofil) in kuehl_profile or (haus_heizung_aus is string and haus_heizung_aus != '' and is_state(haus_heizung_aus, 'on'))) "
                                       "and not (fensterkontakte | select('is_state', 'on') | list | count > 0) and states(aussen) | float(0) >= aussen_min | float }}"),
                         "r_stufe": ("{%- set l = states(letzte_stufe) | int(0) -%}{%- set t = states(raumfuehler) | float(0) if raumfuehler.startswith('sensor.') else state_attr(raumfuehler, 'current_temperature') | float(0) -%}"
                                     "{{ l if l > 0 else (17 if t > 24 else 18 if t > 23 else 20 if t >= 22 else 21) }}")}},
                     {"alias": "Wiederherstellen oder blockieren", "choose": [{
                         "alias": "Sicherheitsbedingungen erlauben die Wiederherstellung", "conditions": [c("Kühlen erlaubt", "{{ r_erlaubt }}")],
                         "sequence": [
                             {"alias": "Testbetrieb oder Normalbetrieb", "if": [c("Normalbetrieb", "{{ produktiv }}")],
                              "then": stufe_senden("r_stufe | int") + [
                                  {"alias": "Wiederherstellung im Logbuch", "action": "logbook.log", "data": {
                                      "name": "{{ raum_name }} Klima Neustart", "message": "Klimaanlage war aktiv – mit Stufe {{ r_stufe }} °C wiederhergestellt.",
                                      "entity_id": "{{ klima_aktiv }}"}}],
                              "else": [{"alias": "Testbetrieb: nur protokollieren", "action": "logbook.log", "data": {
                                  "name": "{{ raum_name }} Klima (Test)", "message": "Geplant: Neustart-Wiederherstellung mit Stufe {{ r_stufe }}", "entity_id": "{{ klima_aktiv }}"}}]}]}],
                      "default": [{"alias": "Blockierte Wiederherstellung im Logbuch", "action": "logbook.log", "data": {
                          "name": "{{ raum_name }} Klima Neustart",
                          "message": "Wiederherstellung blockiert (Profil {{ states(heizprofil) }}, Außen {{ states(aussen) }} °C, Fenster/Erlaubnis nicht erfüllt).",
                          "entity_id": "{{ klima_aktiv }}"}}]}]}]}],
            "else": [{"alias": "Zeitüberschreitung im Logbuch", "action": "logbook.log", "data": {
                "name": "{{ raum_name }} Klima Neustart", "message": "Sensordaten nach 2,5 Minuten nicht gültig – kein Einschaltbefehl.", "entity_id": "{{ klima_aktiv }}"}}]}]})
    zweige.append({"alias": "Fenster offen: Zustand merken und Klimaanlage pausieren", "conditions": [c("Fensterpause", "{{ entscheidung == 'fenster_pause' }}")],
                   "sequence": [
        {"alias": "Modus, Stufe und Ziel merken", "action": "input_text.set_value", "target": {"entity_id": "{{ modus_vor_fenster }}"},
         "data": {"value": "{{ modus_jetzt }}|{{ stufe_jetzt }}|{{ klima_ziel }}"}},
        *aus_senden(),
        {"alias": "Kühlbefehl als inaktiv markieren", "action": "input_boolean.turn_off", "target": {"entity_id": "{{ klima_aktiv }}"}},
        {"alias": "Letzte Stufe zurücksetzen", "action": "input_number.set_value", "target": {"entity_id": "{{ letzte_stufe }}"}, "data": {"value": 0}}]})
    zweige.append({"alias": "Fenster geschlossen: Automatik wiederherstellen", "conditions": [c("Wiederherstellung", "{{ entscheidung == 'fenster_wiederherstellen' }}")],
                   "sequence": [
        {"alias": "Gemerktes Ziel setzen", "action": "input_number.set_value", "target": {"entity_id": "{{ zieltemperatur }}"}, "data": {"value": "{{ gespeichertes_ziel }}"}},
        {"alias": "Automatik Kühlen wählen", "action": "input_select.select_option", "target": {"entity_id": "{{ klima_modus }}"}, "data": {"option": "Automatik Kühlen"}},
        {"alias": "Kühlbefehl inaktiv", "action": "input_boolean.turn_off", "target": {"entity_id": "{{ klima_aktiv }}"}},
        {"alias": "Letzte Stufe zurücksetzen", "action": "input_number.set_value", "target": {"entity_id": "{{ letzte_stufe }}"}, "data": {"value": 0}},
        {"alias": "Merker leeren", "action": "input_text.set_value", "target": {"entity_id": "{{ modus_vor_fenster }}"}, "data": {"value": ""}},
        {"alias": "2 s warten", "delay": {"seconds": 2}},
        {"alias": "Sofort weiterkühlen, wenn der Raum zu warm ist", "if": [c("Raum über Einschaltschwelle", "{{ raum_temp >= gespeichertes_ziel + ein_ueber | float }}")],
         "then": stufe_senden("auto_stufe | int") + [
             {"alias": "Kühlbefehl aktiv", "action": "input_boolean.turn_on", "target": {"entity_id": "{{ klima_aktiv }}"}}]}]})
    zweige.append({"alias": "Klima-Modus auf Aus gestellt: Klimaanlage ausschalten", "conditions": [c("Aus", "{{ entscheidung == 'aus' }}")],
                   "sequence": [*aus_senden(),
        {"alias": "Letzte Stufe zurücksetzen", "action": "input_number.set_value", "target": {"entity_id": "{{ letzte_stufe }}"}, "data": {"value": 0}},
        {"alias": "Kühlbefehl inaktiv", "action": "input_boolean.turn_off", "target": {"entity_id": "{{ klima_aktiv }}"}},
        {"alias": "Fenstermerker leeren", "action": "input_text.set_value", "target": {"entity_id": "{{ modus_vor_fenster }}"}, "data": {"value": ""}}]})
    zweige.append({"alias": "Kühlen nicht mehr erlaubt (Heizprofil, Außentemperatur): ausschalten", "conditions": [c("Sperre", "{{ entscheidung == 'sperre_aus' }}")],
                   "sequence": [
        {"alias": "Fenstermerker leeren", "action": "input_text.set_value", "target": {"entity_id": "{{ modus_vor_fenster }}"}, "data": {"value": ""}},
        *aus_senden(),
        {"alias": "1 s warten", "delay": {"seconds": 1}},
        {"alias": "Letzte Stufe zurücksetzen", "action": "input_number.set_value", "target": {"entity_id": "{{ letzte_stufe }}"}, "data": {"value": 0}},
        {"alias": "Klima-Modus auf Aus", "action": "input_select.select_option", "target": {"entity_id": "{{ klima_modus }}"}, "data": {"option": "Aus"}},
        {"alias": "Kühlbefehl inaktiv", "action": "input_boolean.turn_off", "target": {"entity_id": "{{ klima_aktiv }}"}}]})
    zweige.append({"alias": "Manuelle Stufe senden", "conditions": [c("Manuell", "{{ entscheidung == 'manuell' }}")],
                   "sequence": [
        {"alias": "Gewählte Stufe bestimmen", "variables": {"m_stufe": "{{ [[states(manuelle_stufe) | int(20), stufe_min | int] | max, stufe_max | int] | min }}"}},
        *stufe_senden("m_stufe | int"),
        {"alias": "Modus Manuell Kühlen setzen", "action": "input_select.select_option", "target": {"entity_id": "{{ klima_modus }}"}, "data": {"option": "Manuell Kühlen"}},
        {"alias": "Kühlbefehl aktiv", "action": "input_boolean.turn_on", "target": {"entity_id": "{{ klima_aktiv }}"}}]})
    zweige.append({"alias": "Automatik: Kühlen einschalten oder Stufe anpassen", "conditions": [c("Kühlen ein", "{{ entscheidung == 'kuehlen_ein' }}")],
                   "sequence": [*stufe_senden("auto_stufe | int"),
        {"alias": "2 s warten", "delay": {"seconds": 2}},
        {"alias": "Kühlbefehl aktiv", "action": "input_boolean.turn_on", "target": {"entity_id": "{{ klima_aktiv }}"}}]})
    zweige.append({"alias": "Automatik: Ziel erreicht, ausschalten", "conditions": [c("Kühlen aus", "{{ entscheidung == 'kuehlen_aus' }}")],
                   "sequence": [*aus_senden(),
        {"alias": "2 s warten", "delay": {"seconds": 2}},
        {"alias": "Kühlbefehl inaktiv", "action": "input_boolean.turn_off", "target": {"entity_id": "{{ klima_aktiv }}"}},
        {"alias": "Letzte Stufe zurücksetzen", "action": "input_number.set_value", "target": {"entity_id": "{{ letzte_stufe }}"}, "data": {"value": 0}}]})
    zweige.append({"alias": "PV-Notrückgabe: PV-Automation ausgefallen, Klimaanlage sicher ausschalten", "conditions": [c("PV-Notfall", "{{ entscheidung == 'pv_rueckgabe' }}")],
                   "sequence": [
        ir_roh("Klimaanlage per IR ausschalten", "{{ befehl_aus | replace('{luefter}', luefter) }}") | {"continue_on_error": True},
        {"alias": "PV-Heizbefehl zurücknehmen", "action": "input_boolean.turn_off", "target": {"entity_id": "{{ [pv_heizbefehl, pv_auftrag] + pv_verantwortung }}"}},
        {"alias": "PV-Heizfreigabe ausschalten (muss bewusst wieder eingeschaltet werden)", "action": "input_boolean.turn_off", "target": {"entity_id": "{{ pv_heizfreigabe }}"}},
        {"alias": "PV-Status aktualisieren", "if": [c("PV-Status-Helfer vorhanden", "{{ pv_status is string and pv_status != '' }}")],
         "then": [{"alias": "Status schreiben", "action": "input_text.set_value", "target": {"entity_id": "{{ pv_status }}"},
                   "data": {"value": "Notrückgabe durch Klimaautomatik: PV-Automation ausgefallen, Klima aus"}}]},
        {"alias": "Beständige Meldung", "action": "persistent_notification.create", "data": {
            "notification_id": "{{ 'hz_pv_notrueckgabe_' ~ raum_schluessel }}",
            "title": "{{ raum_name }}: PV-Heizen durch Notrückgabe beendet",
            "message": ("Die PV-Überschussheizen-Automation war ausgeschaltet oder hat ihre Sicherheitsfreigabe nicht erneuert, während die "
                        "Klimaanlage für PV heizte. Die Klimaanlage wurde ausgeschaltet und die PV-Heizfreigabe zurückgenommen. "
                        "Die Heizkörper übernimmt die Raumheizungssteuerung automatisch.")}}]})
    meldung_id = "{{ 'hz_klima_rueckmeldung_' ~ raum_schluessel }}"
    zweige.append({"alias": "Steckdose war ausgeschaltet: wieder einschalten und Klimazustand herstellen", "conditions": [c("Steckdose wieder einschalten", "{{ entscheidung == 'steckdose_ein' }}")],
                   "sequence": [
        {"alias": "Im Logbuch festhalten", "action": "logbook.log", "data": {
            "name": "{{ raum_name }} Klima", "message": "Steckdose der Klimaanlage war seit 1 Minute aus – wird wieder eingeschaltet (dauerhaft eingeschaltet halten).",
            "entity_id": "{{ klima_aktiv }}"}},
        {"alias": "Klimazustand nach dem Wiedereinschalten herstellen", "choose": [
            {"alias": "PV-Heizen ist verantwortlich: nur Strom herstellen", "conditions": [c("PV belegt", "{{ pv_belegt }}")],
             "sequence": [strom_sichern()]},
            {"alias": "Kühlen war aktiv: zuletzt gesendete Stufe erneut senden", "conditions": [c("Kühlbefehl aktiv mit Stufe", "{{ aktiv_jetzt and stufe_jetzt > 0 }}")],
             "sequence": stufe_senden("stufe_jetzt | int")}],
         "default": [ir_senden("Sicherheitshalber Aus senden (manche Klimaanlagen laufen nach Stromrückkehr von selbst weiter)",
                               "{{ befehl_aus | replace('{luefter}', luefter) }}")]}]})
    zweige.append({"alias": "Rückmeldung: Klimaanlage läuft nach dem Einschaltbefehl nicht – einmal wiederholen", "conditions": [c("Nachsenden Ein", "{{ entscheidung == 'nachsenden_ein' }}")],
                   "sequence": [
        {"alias": "Im Logbuch festhalten", "action": "logbook.log", "data": {
            "name": "{{ raum_name }} Klima",
            "message": "Klimaanlage läuft {{ pruef_ein_min | int }} min nach dem Einschaltbefehl nicht ({{ states(klima_leistung) }} W) – Stufe {{ stufe_jetzt }} wird einmal wiederholt.",
            "entity_id": "{{ klima_aktiv }}"}},
        *stufe_senden("stufe_jetzt | int")]})
    zweige.append({"alias": "Rückmeldung: Klimaanlage läuft auch nach der Wiederholung nicht – melden", "conditions": [c("Fehler Ein", "{{ entscheidung == 'fehler_ein' }}")],
                   "sequence": [
        {"alias": "Dauerhafte Meldung: Klimaanlage reagiert nicht", "action": "persistent_notification.create", "data": {
            "notification_id": meldung_id, "title": "Klima {{ raum_name }}: Klimaanlage reagiert nicht",
            "message": ("Der Einschaltbefehl (Stufe {{ stufe_jetzt }}) wurde zweimal gesendet, die Klimaanlage nimmt aber nur {{ states(klima_leistung) }} W auf "
                        "(läuft ab {{ laeuft_ab_w | int }} W). Bitte vor Ort prüfen: Sichtverbindung zum IR-Sender, Strom, Fehleranzeige am Gerät.")}},
        {"alias": "Im Logbuch festhalten", "action": "logbook.log", "data": {
            "name": "{{ raum_name }} Klima", "message": "Klimaanlage reagiert auch auf die Wiederholung nicht ({{ states(klima_leistung) }} W).", "entity_id": "{{ klima_aktiv }}"}}]})
    zweige.append({"alias": "Rückmeldung: Klimaanlage läuft nach dem Ausschaltbefehl weiter – einmal wiederholen", "conditions": [c("Nachsenden Aus", "{{ entscheidung == 'nachsenden_aus' }}")],
                   "sequence": [
        {"alias": "Im Logbuch festhalten", "action": "logbook.log", "data": {
            "name": "{{ raum_name }} Klima",
            "message": "Klimaanlage nimmt {{ pruef_aus_min | int }} min nach dem Ausschalten noch {{ states(klima_leistung) }} W auf – Aus wird einmal wiederholt.",
            "entity_id": "{{ klima_aktiv }}"}},
        *aus_senden()]})
    zweige.append({"alias": "Rückmeldung: Klimaanlage läuft auch nach der Wiederholung weiter – melden", "conditions": [c("Fehler Aus", "{{ entscheidung == 'fehler_aus' }}")],
                   "sequence": [
        {"alias": "Dauerhafte Meldung: Klimaanlage lässt sich nicht ausschalten", "action": "persistent_notification.create", "data": {
            "notification_id": meldung_id, "title": "Klima {{ raum_name }}: Klimaanlage läuft weiter",
            "message": ("Der Ausschaltbefehl wurde zweimal gesendet, die Klimaanlage nimmt aber weiter {{ states(klima_leistung) }} W auf. "
                        "Bitte vor Ort prüfen und notfalls mit der Originalfernbedienung ausschalten.")}},
        {"alias": "Im Logbuch festhalten", "action": "logbook.log", "data": {
            "name": "{{ raum_name }} Klima", "message": "Klimaanlage läuft auch nach der Wiederholung weiter ({{ states(klima_leistung) }} W).", "entity_id": "{{ klima_aktiv }}"}}]})
    zweige.append({"alias": "Rückmeldung in Ordnung: eine frühere Meldung entfernen", "conditions": [c("Rückmeldung ok", "{{ entscheidung == 'rueckmeldung_ok' }}")],
                   "sequence": [{"alias": "Rückmelde-Meldung entfernen (falls vorhanden)", "action": "persistent_notification.dismiss", "data": {"notification_id": meldung_id}}]})
    a.append({"alias": "Entscheidung ausführen", "choose": zweige})
    return a


def blueprint():
    return {
        "blueprint": {
            "name": "Klimaautomatik (Raum)",
            "description": "Paketversion 1.6.0 · " + (
                "Optionale Ergänzung zur „Universellen Raumheizungssteuerung“ für Räume mit Klimaanlage (IR-Steuerung, z. B. Broadlink). "
                "Betriebsarten Aus, Automatik Kühlen (Hysterese und Stufentabelle) und Manuell Kühlen. Kühlen nur, wenn die Raumheizung in "
                "einem freigegebenen Profil steht (Standard Sommer/Aus), alle Fenster zu sind und es draußen warm genug ist. Fensterpause mit "
                "Wiederherstellung, Schutz bei ungültigen Sensoren, sichere Wiederherstellung nach Neustarts. Arbeitet mit "
                "„PV-Überschussheizen“ zusammen: Bedienung hat Vorrang, Notrückgabe bei Ausfall der PV-Automation. Optional mit schaltbarer "
                "Messsteckdose: Steckdose bleibt dauerhaft eingeschaltet (vor jedem Befehl gesichert), Rückmeldung über die Leistung mit "
                "einmaliger Wiederholung und Meldung."),
            "domain": "automation", "author": "HA-Heizung-Universal",
            "homeassistant": {"min_version": "2026.11.0"},
            "input": inputs(),
        },
        "mode": "queued", "max": 10, "max_exceeded": "warning", "trace": {"stored_traces": 20},
        "trigger_variables": {"pruef_ein_tv": Inp("pruef_ein_min"), "pruef_aus_tv": Inp("pruef_aus_min")},
        "variables": variablen(), "triggers": trigger(), "conditions": [], "actions": aktionen(),
    }


if __name__ == "__main__":
    ZIELDATEI.parent.mkdir(parents=True, exist_ok=True)
    ZIELDATEI.write_text("# Klimaautomatik – Blueprint 2 von 3 (optional)\n# Erzeugt mit tools/build_klima.py\n" + dump(blueprint()), encoding="utf-8")
    print("geschrieben:", ZIELDATEI.relative_to(BASIS))
