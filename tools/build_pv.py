#!/usr/bin/env python3
"""Erzeugt Blueprint 3 „PV-Überschussheizen“ (optional, setzt Klimaautomatik im selben Raum voraus).

Vorbild: eine gewachsene PV-Heizsteuerung (Automation „PV heizen“, Sicherheitswache für Neustart und Freigabe,
Skripte „IR ein“ / „IR aus“ / „PV beenden“). Alle Schwellen und Fristen sind Eingaben mit bewährten Standardwerten.
Ausgabe: blueprints/automation/ha_heizung_universal/pv_ueberschussheizen.yaml
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from yamlgen import Inp, dump  # noqa: E402
from build_raumheizung import sel_entity, sel_number, c  # noqa: E402

BASIS = Path(__file__).resolve().parent.parent
ZIELDATEI = BASIS / "blueprints" / "automation" / "ha_heizung_universal" / "pv_ueberschussheizen.yaml"

TIMER = [("t_startfrist", "Startbestätigung", "start_bestaetigung", 5),
         ("t_mangelfrist", "Energiemangel-Toleranz", "mangel_minuten", 10),
         ("t_wiederholung", "IR-Wiederholung", "wiederholung_minuten", 10),
         ("t_waermepruefung", "Wärmeprüfung", "pruef_minuten", 40),
         ("t_sperre", "Wiederanlaufsperre", "sperre_minuten", 30),
         ("t_freigabe", "Sicherheitsfreigabe (Lease)", "freigabe_minuten", 2),
         ("t_schaltpause", "Schaltpause nach AUS", "schaltpause_minuten", 5),
         ("t_heizkoerper", "Heizkörper-Schließfrist", "heizkoerper_minuten", 8)]
FLAGS = [("f_heizfreigabe", "PV-Heizfreigabe (Schalter für den Benutzer)"),
         ("f_ir_geprueft", "IR-Befehle vor Ort geprüft (Freigabe nach Test)"),
         ("f_regelung", "Regelung aktiv (PV verantwortlich)"),
         ("f_heizbefehl", "Heizbefehl aktiv"),
         ("f_auftrag", "IR-Auftrag offen"),
         ("f_fehler", "IR-Fehler (quittierungspflichtig)"),
         ("f_wiederholt", "IR wiederholt"),
         ("f_vorbereitung", "Startvorbereitung")]


def dauer(m):
    return "{{ '%02d:%02d:00' % ((" + m + " | int) // 60, (" + m + " | int) % 60) }}"


def inputs():
    helfer = {k: {"name": n, "selector": sel_entity("timer")} for k, n, _, _ in TIMER}
    helfer.update({k: {"name": n, "selector": sel_entity("input_boolean")} for k, n in FLAGS})
    helfer["starttemperatur"] = {"name": "Starttemperatur für die Wärmeprüfung (input_number −20…50)", "selector": sel_entity("input_number")}
    helfer["status_text"] = {"name": "PV-Status-Text (input_text)", "selector": sel_entity("input_text")}
    return {
        "geraete": {"name": "Raum und Geräte", "icon": "mdi:home-lightning-bolt", "input": {
            "raum_name": {"name": "Raumname", "default": "Raum", "selector": {"text": {}}},
            "raum_schluessel": {"name": "Raumkennung", "default": "raum", "selector": {"text": {}}},
            "better_thermostat": {"name": "Better Thermostat des Raums", "selector": sel_entity("climate", integration="better_thermostat")},
            "heizkoerper": {"name": "Heizkörperthermostate", "description": "Alle Heizkörperthermostate des Raums. Vor dem PV-Heizen müssen alle auf Frostschutz (≤ 5 °C) stehen.",
                            "selector": {"entity": {"multiple": True, "filter": [{"domain": ["climate"]}]}}},
            "ventile": {"name": "Ventilöffnungs-Sensoren (optional)", "default": [], "description": "Wenn vorhanden: alle müssen 0 % melden, bevor die Klimaanlage heizt.",
                        "selector": {"entity": {"multiple": True, "filter": [{"domain": ["sensor"]}]}}},
            "raumfuehler": {"name": "Raumtemperaturfühler", "description": "Physischer Fühler (sein Meldezeitpunkt wird auf Aktualität geprüft).",
                            "selector": sel_entity("sensor", device_class="temperature")},
            "aussentemperatur": {"name": "Außentemperatur", "selector": sel_entity("sensor", device_class="temperature")},
            "fensterkontakte": {"name": "Fenster, die PV-Heizen sperren", "default": [],
                                "description": "Vom Assistenten: der Fensterstatus des Raums (ohne die dort eingetragenen Ausnahmen).",
                                "selector": {"entity": {"multiple": True, "filter": [{"domain": ["binary_sensor"], "device_class": ["window", "door", "opening"]},
                                                                                    {"domain": ["input_boolean"]}]}}},
            "ir_konfiguration": {"name": "Gemeinsame IR-Konfiguration der Klimaautomatik (input_text)",
                                 "description": ("Derselbe Helfer wie in der Klimaautomatik dieses Raums. Von dort kommen IR-Sender, Gerätename und die "
                                                 "Heizbefehle – hier wird kein eigener Sender gewählt, damit es nur eine Broadlink-Zuordnung je Raum gibt."),
                                 "selector": sel_entity("input_text")},
            "heizstufe": {"name": "Heizstufe der Klimaanlage beim PV-Heizen", "default": 24,
                          "description": ("Ersetzt `{stufe}` im Heizbefehl der Klimaautomatik (z. B. `heizen_{stufe}` → `heizen_24`). Für jede hier gewählte "
                                          "Stufe muss der Befehl im Sender angelernt sein. Ohne `{stufe}` im Befehlsnamen wirkt diese Einstellung nicht."),
                          "selector": sel_number(16, 30, 1, "°C", "box")},
        }},
        "strom": {"name": "Stromversorgung und Rückmeldung (optional)", "icon": "mdi:power-socket-de", "collapsed": True,
                  "description": ("Dieselbe Messsteckdose wie in der Klimaautomatik. Vor jedem IR-Befehl wird sie bei Bedarf eingeschaltet (nie ausgeschaltet). "
                                  "Mit Leistungsmessung entscheidet die IR-Wiederholung nach der Leistung statt nach dem Temperaturanstieg; reagiert die "
                                  "Klimaanlage auch auf die Wiederholung nicht, wird PV mit IR-Fehler beendet. Läuft sie nach HEIZEN-AUS weiter, wird AUS "
                                  "einmal wiederholt."),
                  "input": {
            "klima_steckdose": {"name": "Steckdose der Klimaanlage (optional)", "default": [], "selector": sel_entity("switch")},
            "vorlauf_s": {"name": "Wartezeit nach dem Einschalten der Steckdose", "default": 30, "selector": sel_number(5, 120, 5, "s", "box")},
            "klima_leistung": {"name": "Leistungsmessung der Klimaanlage (optional)", "default": [], "selector": sel_entity("sensor", device_class="power")},
            "laeuft_ab_w": {"name": "Klimaanlage gilt als laufend ab", "default": 15, "selector": sel_number(2, 500, 1, "W", "box")},
            "pruef_aus_min": {"name": "Rückmeldung nach HEIZEN-AUS prüfen nach", "default": 10, "selector": sel_number(1, 60, 1, "min", "box")},
        }},
        "energie": {"name": "Energiedaten", "icon": "mdi:solar-power", "collapsed": True, "input": {
            "soc": {"name": "Batterie-Ladestand (%)", "selector": sel_entity("sensor")},
            "netz": {"name": "Netz-Einspeisung (W, positiv = Einspeisung, negativ = Bezug)", "selector": sel_entity("sensor")},
            "akku_leistung": {"name": "Batterie-Leistung (W, positiv = Laden, negativ = Entladen)", "selector": sel_entity("sensor")},
            "pv_leistung": {"name": "PV-Leistung (W)", "selector": sel_entity("sensor")},
            "verbrauch": {"name": "Hausverbrauch (W)", "selector": sel_entity("sensor")},
            "zeitstempel_attribut": {"name": "Attribut mit Zeitpunkt der letzten Aktualisierung (optional)", "default": "",
                                     "description": "Z. B. `last_update`. Leer = Meldezeitpunkt (last_reported) der Sensoren verwenden.", "selector": {"text": {}}},
            "max_energie_alter": {"name": "Energiedaten höchstens so alt", "default": 180, "selector": sel_number(30, 1800, 10, "s")},
            "max_raum_alter": {"name": "Raumfühler höchstens so alt", "default": 120, "selector": sel_number(10, 720, 10, "min")},
            "max_aussen_alter": {"name": "Außentemperatur höchstens so alt", "default": 180, "selector": sel_number(10, 1440, 10, "min")},
        }},
        "schwellen": {"name": "Start- und Stoppschwellen", "icon": "mdi:tune", "collapsed": True,
                      "description": "Standardwerte = bewährte Ausgangswerte.", "input": {
            "start_leistung": {"name": "Start: Einspeisung mindestens", "default": 1000, "selector": sel_number(500, 3000, 50, "W")},
            "soc_start": {"name": "Start: Batterie mindestens", "default": 95, "selector": sel_number(50, 100, 1, "%")},
            "soc_halten": {"name": "Weiterheizen: Batterie mindestens", "default": 85, "selector": sel_number(20, 100, 1, "%")},
            "akku_entladung_max": {"name": "Start: Batterie-Entladung höchstens", "default": 100, "selector": sel_number(0, 2000, 10, "W")},
            "aussen_start": {"name": "Start: Außentemperatur unter", "default": 18, "selector": sel_number(-10, 30, 0.5, "°C")},
            "aussen_ende": {"name": "Ende: Außentemperatur ab", "default": 19, "selector": sel_number(-10, 30, 0.5, "°C")},
            "netzbezug_max": {"name": "Ende: Netzbezug über (länger als Toleranz)", "default": 300, "selector": sel_number(0, 3000, 50, "W")},
            "pv_ziel": {"name": "Zieltemperatur PV-Heizen (Klima aus ab)", "default": 24, "selector": sel_number(18, 28, 0.5, "°C")},
            "einschalt_abstand": {"name": "Wieder einschalten ab Ziel minus", "default": 0.7, "selector": sel_number(0.1, 3, 0.1, "K")},
            "anstieg_min": {"name": "Wärmeprüfung: Mindestanstieg", "default": 0.2, "selector": sel_number(0.1, 1, 0.1, "K")},
        }},
        "fristen": {"name": "Fristen", "icon": "mdi:timer-cog", "collapsed": True, "input": {
            m: {"name": n, "default": d, "selector": sel_number(1, 120, 1, "min", "box")} for _, n, m, d in TIMER}},
        "kopplung": {"name": "Zusammenarbeit mit Raumheizung und Klimaautomatik", "icon": "mdi:link-variant", "collapsed": True, "input": {
            "heizprofil": {"name": "Heizprofil-Auswahl der Raumheizung", "selector": sel_entity("input_select")},
            "pv_profile": {"name": "PV-Heizen erlaubt in den Profilen", "default": ["Komfort", "Übergang", "Urlaub"],
                           "selector": {"select": {"multiple": True, "mode": "list", "options": ["Komfort", "Übergang", "Urlaub", "Sommer", "Aus"]}}},
            "raumheizung_automation": {"name": "Raumheizungssteuerung-Automation dieses Raums", "description": "Muss eingeschaltet sein (übernimmt die Heizkörper).",
                                       "selector": sel_entity("automation")},
            "klima_automation": {"name": "Klimaautomatik-Automation dieses Raums", "description": "Muss eingeschaltet sein (Notrückgabe bei Ausfall).",
                                 "selector": sel_entity("automation")},
            "klima_modus": {"name": "Klima-Modus der Klimaautomatik", "selector": sel_entity("input_select")},
            "klima_aktiv": {"name": "Kühlbefehl aktiv der Klimaautomatik", "selector": sel_entity("input_boolean")},
        }},
        "helfer": {"name": "PV-Helfer", "icon": "mdi:tune-variant", "collapsed": True,
                   "description": "Legt der Einrichtungsassistent an (8 Timer, 8 Schalter, 1 Zahl, 1 Text).", "input": helfer},
    }


X = r"""{%- set ns = namespace(trv_zu=true, ventile_zu=true, alter_max=-999999, alter_min=999999) -%}
{%- for t in heizkoerper -%}{%- if not (states(t) in ['heat', 'off'] and is_number(state_attr(t, 'temperature')) and state_attr(t, 'temperature') | float(99) <= 5) -%}{%- set ns.trv_zu = false -%}{%- endif -%}{%- endfor -%}
{%- for v in ventile -%}{%- if not (is_number(states(v)) and states(v) | float(99) == 0) -%}{%- set ns.ventile_zu = false -%}{%- endif -%}{%- endfor -%}
{%- for e in [soc, netz, akku_leistung, pv_leistung, verbrauch] -%}
{%- set ts = (state_attr(e, zeitstempel_attribut) if zeitstempel_attribut | trim != '' else (states[e].last_reported if states[e] is not none else none)) -%}
{%- set alt = (as_timestamp(now()) - as_timestamp(ts, 0)) -%}
{%- set ns.alter_max = [ns.alter_max, alt] | max -%}{%- set ns.alter_min = [ns.alter_min, alt] | min -%}
{%- endfor -%}
{{ dict(preparing=is_state(f_vorbereitung, 'on'), radiator_deadline=states(t_heizkoerper),
 radiators_closed=(is_state(bt, 'off') and heizkoerper | count > 0 and ns.trv_zu and ns.ventile_zu),
 soc=(states(soc) | float(none)), grid=(states(netz) | float(none)), battery=(states(akku_leistung) | float(none)),
 pv=(states(pv_leistung) | float(none)), load=(states(verbrauch) | float(none)), outdoor=(states(aussen) | float(none)),
 room=(states(raumfuehler) | float(none)), target=(pv_ziel | float), profile=states(heizprofil),
 room_age=(as_timestamp(now()) - as_timestamp(states[raumfuehler].last_reported, 0) if states[raumfuehler] is not none else 999999),
 outdoor_age=(as_timestamp(now()) - as_timestamp(states[aussen].last_reported, 0) if states[aussen] is not none else 999999),
 energy_age=ns.alter_max, energy_min_age=ns.alter_min,
 armed=is_state(f_heizfreigabe, 'on'), ir_ready=is_state(f_ir_geprueft, 'on'), owner=is_state(f_regelung, 'on'),
 sent=is_state(f_heizbefehl, 'on'), pending=is_state(f_auftrag, 'on'), fault=is_state(f_fehler, 'on'), retried=is_state(f_wiederholt, 'on'),
 main_on=(this.state == 'on' if this is defined and this.state is defined else true),
 watch_on=is_state(klima_automation, 'on'), profile_on=is_state(raumheizung_automation, 'on'),
 bt_ready=(states(bt) in ['heat', 'off']), remote_ready=(is_state(klima_sender, 'on') and befehl_heizen != '' and befehl_heizen_aus != ''
   and (not steckdose_ok or states(klima_steckdose) in ['on', 'off'])),
 leistung_ok=(leistung_ok and is_number(states(klima_leistung))), laeuft=(leistung_ok and states(klima_leistung) | float(0) >= laeuft_ab_w | float),
 leistung=(states(klima_leistung) if leistung_ok else ''),
 windows_closed=(fensterkontakte | reject('is_state', 'off') | list | count == 0),
 cooling_clear=(is_state(klima_modus, 'Aus') and is_state(klima_aktiv, 'off')),
 start_w=(start_leistung | float), rise=(anstieg_min | float), baseline=(states(starttemperatur) | float(none)),
 wiederanlaufsperre=states(t_sperre), sicherheitsfreigabe=states(t_freigabe), schaltpause=states(t_schaltpause),
 waermepruefung=states(t_waermepruefung), ir_wiederholung=states(t_wiederholung),
 event=(trigger.event.data.entity_id if trigger is defined and trigger.platform == 'event' else ''),
 boot=(trigger is defined and trigger.id == 'boot'),
 helpers_ok=([t_startfrist, t_mangelfrist, t_wiederholung, t_waermepruefung, t_sperre, t_freigabe, t_schaltpause, t_heizkoerper,
   f_heizfreigabe, f_ir_geprueft, f_regelung, f_heizbefehl, f_auftrag, f_fehler, f_wiederholt, f_vorbereitung, starttemperatur, status_text]
   | select('is_state', ['unknown', 'unavailable']) | list | count == 0)) }}"""

D = r"""{%- set ns = namespace(reason='', op='wait', ir_fault=false) -%}
{%- if x.boot -%}{%- set ns.reason = 'Neustart: normale Heizung wiederherstellen' -%}
{%- elif not x.armed -%}{%- set ns.reason = 'PV-Heizfreigabe ausgeschaltet' -%}
{%- elif not x.ir_ready -%}{%- set ns.reason = 'IR-Prueffreigabe fehlt' -%}
{%- elif x.fault -%}{%- set ns.reason = 'IR-Sendefehler: manuell pruefen und quittieren' -%}
{%- elif not x.main_on or not x.watch_on or not x.profile_on -%}{%- set ns.reason = 'Regelung oder Sicherheitsautomation deaktiviert' -%}
{%- elif not x.helpers_ok -%}{%- set ns.reason = 'PV-Helfer nicht verfuegbar' -%}
{%- elif x.profile not in pv_profile -%}{%- set ns.reason = 'Heizprofil erlaubt kein PV-Heizen' -%}
{%- elif not x.cooling_clear -%}{%- set ns.reason = 'Kuehlbetrieb oder manuelle Klimabedienung hat Vorrang' -%}
{%- elif not x.windows_closed -%}{%- set ns.reason = 'Fenster offen oder unbekannt' -%}
{%- elif not x.bt_ready or not x.remote_ready -%}{%- set ns.reason = 'BT oder IR-Sender nicht verfuegbar' -%}
{%- elif x.soc is none or x.grid is none or x.battery is none or x.pv is none or x.load is none or x.outdoor is none or x.room is none or x.target is none -%}{%- set ns.reason = 'Pflichtmesswert ist nicht numerisch' -%}
{%- elif not (0 <= x.soc <= 100 and -100000 < x.grid < 100000 and -100000 < x.battery < 100000 and 0 <= x.pv < 100000 and 0 <= x.load < 100000 and -40 <= x.outdoor <= 60 and -10 <= x.room <= 50 and 5 < x.target <= 30) -%}{%- set ns.reason = 'Messwert unplausibel oder Raumziel ausserhalb des Bereichs' -%}
{%- elif x.baseline is none -%}{%- set ns.reason = 'Einstellwert nicht numerisch' -%}
{%- elif not (-60 <= x.energy_min_age and x.energy_age <= max_energie_alter | float) -%}{%- set ns.reason = 'Energiedaten fehlen oder sind zu alt' -%}
{%- elif not (-60 <= x.room_age <= (max_raum_alter | float) * 60) -%}{%- set ns.reason = 'Raumfuehler meldet zu lange nicht' -%}
{%- elif not (-60 <= x.outdoor_age <= (max_aussen_alter | float) * 60) -%}{%- set ns.reason = 'Aussentemperatur meldet zu lange nicht' -%}
{%- elif x.owner and x.soc < soc_halten | float -%}{%- set ns.reason = 'Akku unter ' ~ (soc_halten | int) ~ ' Prozent' -%}
{%- elif x.owner and x.outdoor >= aussen_ende | float -%}{%- set ns.reason = 'Aussentemperatur mindestens ' ~ aussen_ende ~ ' Grad' -%}
{%- elif x.owner and x.sicherheitsfreigabe != 'active' -%}{%- set ns.reason = 'Befristete Heizkoerperfreigabe abgelaufen' -%}
{%- endif -%}
{%- set safe = ns.reason == '' -%}
{%- set poor = safe and ((x.grid < -(netzbezug_max | float)) if x.owner else (x.grid < x.start_w or x.battery < -(akku_entladung_max | float) or x.pv <= 0)) -%}
{%- if ns.reason -%}{%- set ns.op = 'stop' if x.owner or x.sent or x.pending or x.preparing else 'blocked' -%}
{%- elif x.pending -%}{%- set ns.op = 'stop' -%}{%- set ns.reason = 'Unvollstaendiger IR-Auftrag: sichere Rueckgabe' -%}
{%- elif x.owner and poor and x.event == t_mangelfrist -%}{%- set ns.op = 'stop' -%}{%- set ns.reason = 'Netzbezug ueber ' ~ (netzbezug_max | int) ~ ' W seit ' ~ (mangel_minuten | int) ~ ' Minuten' -%}
{%- elif x.preparing and not x.owner -%}{%- set ns.op = 'stop' -%}{%- set ns.reason = 'Verwaiste Startvorbereitung' -%}
{%- elif x.preparing and x.radiator_deadline != 'active' -%}{%- set ns.op = 'stop' -%}{%- set ns.reason = 'Heizkoerper nach ' ~ (heizkoerper_minuten | int) ~ ' Minuten nicht sicher geschlossen' -%}
{%- elif x.owner and x.sent and not x.radiators_closed -%}{%- set ns.op = 'stop' -%}{%- set ns.reason = 'Heizkoerper nicht mehr geschlossen: Klima beenden' -%}
{%- elif x.preparing and x.room >= x.target -%}{%- set ns.op = 'stop' -%}{%- set ns.reason = 'Raumziel bereits waehrend Startvorbereitung erreicht' -%}
{%- elif x.preparing and x.radiators_closed -%}{%- set ns.op = 'start_heat' -%}{%- set ns.reason = 'Heizkoerper bei Frostschutz und Ventile geschlossen' -%}
{%- elif x.preparing -%}{%- set ns.op = 'wait_radiators' -%}{%- set ns.reason = 'Warte auf Heizkoerper: Frostschutz und Ventile 0 Prozent' -%}
{%- elif x.owner and x.sent and x.room >= x.target -%}{%- set ns.op = 'cycle_off' -%}{%- set ns.reason = 'PV-Ziel ' ~ x.target ~ ' Grad erreicht: Klima-Pause' -%}
{%- elif x.owner and x.sent and x.waermepruefung == 'idle' -%}
{%- if x.room < x.baseline + x.rise - 0.00001 -%}{%- set ns.op = 'stop' -%}{%- set ns.reason = 'Kein ausreichender Temperaturanstieg in ' ~ (pruef_minuten | int) ~ ' Minuten' -%}
{%- else -%}{%- set ns.op = 'proof_reset' -%}{%- set ns.reason = 'Temperaturanstieg erkannt; naechstes Prueffenster' -%}{%- endif -%}
{%- elif x.owner and x.sent and x.retried and x.leistung_ok and x.event == t_wiederholung and not x.laeuft -%}{%- set ns.op = 'stop' -%}{%- set ns.ir_fault = true -%}{%- set ns.reason = 'Klimaanlage reagiert auch auf die IR-Wiederholung nicht (' ~ x.leistung ~ ' W)' -%}
{%- elif x.owner and x.sent and not x.retried and x.leistung_ok and x.event == t_wiederholung and not x.laeuft and not poor -%}{%- set ns.op = 'retry' -%}{%- set ns.reason = 'Einmalige IR-Wiederholung: Klimaanlage nimmt nur ' ~ x.leistung ~ ' W auf' -%}
{%- elif x.owner and x.sent and not x.retried and x.ir_wiederholung == 'idle' and not x.leistung_ok and x.room < x.baseline + x.rise - 0.00001 and not poor -%}{%- set ns.op = 'retry' -%}{%- set ns.reason = 'Einmalige IR-Wiederholung wegen fehlendem Temperaturanstieg' -%}
{%- elif x.owner and x.sent -%}{%- set ns.op = 'active' -%}{%- set ns.reason = 'PV heizt angefordert' -%}
{%- elif x.wiederanlaufsperre != 'idle' -%}{%- set ns.reason = (sperre_minuten | int) ~ '-Minuten-Wiederanlaufsperre' -%}
{%- elif not x.owner and x.soc < soc_start | float -%}{%- set ns.reason = 'Akku unter ' ~ (soc_start | int) ~ ' Prozent' -%}
{%- elif not x.owner and x.outdoor >= aussen_start | float -%}{%- set ns.reason = 'Aussentemperatur nicht unter ' ~ aussen_start ~ ' Grad' -%}
{%- elif poor -%}{%- set ns.reason = 'Nicht genug Netzeinspeisung oder Akkuentladung' -%}
{%- elif x.room > x.target - (einschalt_abstand | float) + 0.00001 -%}{%- set ns.reason = 'PV-Pause: Raum ueber Einschaltgrenze ' ~ (x.target - (einschalt_abstand | float)) ~ ' Grad' -%}
{%- elif x.schaltpause != 'idle' -%}{%- set ns.reason = (schaltpause_minuten | int) ~ '-Minuten-Schaltpause nach AUS' -%}
{%- elif x.event == t_startfrist -%}{%- set ns.op = 'prepare_heat' -%}{%- set ns.reason = 'Startbedingungen erfuellt: zuerst Heizkoerper schliessen' -%}
{%- else -%}{%- set ns.op = 'qualify' -%}{%- set ns.reason = 'Startbedingungen: ' ~ (start_bestaetigung | int) ~ ' Minuten bestaetigen' -%}
{%- endif -%}
{{ dict(op=ns.op, reason=ns.reason, safe=safe, poor=poor, lease=safe and x.owner and ns.op != 'stop', ir_fault=ns.ir_fault) }}"""


def status(tpl):
    return {"alias": "Sichtbaren PV-Status aktualisieren", "action": "input_text.set_value", "target": {"entity_id": "{{ status_text }}"},
            "data": {"value": "{{ (" + tpl + ")[:255] }}"}}


def t_start(alias, tvar, minuten=None):
    a = {"alias": alias, "action": "timer.start", "target": {"entity_id": "{{ " + tvar + " }}"}}
    if minuten:
        a["data"] = {"duration": dauer(minuten)}
    return a


def t_cancel(alias, tvar):
    return {"alias": alias, "action": "timer.cancel", "target": {"entity_id": "{{ " + tvar + " }}"}, "continue_on_error": True}


def flag(alias, fvar, an):
    return {"alias": alias, "action": "input_boolean.turn_on" if an else "input_boolean.turn_off", "target": {"entity_id": "{{ " + fvar + " }}"}}


def ir(alias, befehl):
    return {"alias": alias, "action": "remote.send_command", "target": {"entity_id": "{{ klima_sender }}"},
            "data": {"device": "{{ ir_geraet }}", "command": "{{ " + befehl + " }}"}}


def strom_sichern():
    """Vor einem IR-Befehl: Steckdose bei Bedarf einschalten. Meldet sie nicht „an“, endet die innere Sequenz (Auftrag bleibt offen → Fehlerrückgabe)."""
    return {"alias": "Stromversorgung der Klimaanlage sicherstellen", "if": [c(
        "Steckdose eingerichtet und nicht eingeschaltet", "{{ steckdose_ok and not is_state(klima_steckdose, 'on') }}")], "then": [
        {"alias": "Steckdose einschalten", "action": "switch.turn_on", "target": {"entity_id": "{{ klima_steckdose }}"}, "continue_on_error": True},
        {"alias": "Höchstens 20 s warten, bis die Steckdose „an“ meldet", "wait_template": "{{ is_state(klima_steckdose, 'on') }}", "timeout": {"seconds": 20}},
        {"alias": "Nur weiter, wenn die Steckdose eingeschaltet ist", "condition": "template", "value_template": "{{ is_state(klima_steckdose, 'on') }}"},
        {"alias": "Klimaanlage nach dem Einschalten hochfahren lassen", "delay": {"seconds": "{{ vorlauf_s | int }}"}}]}


def ir_ein():
    """Entspricht dem Skript „IR ein“: Auftrag offen → Heizkörper prüfen → senden → Heizbefehl → Auftrag zu.
    Schlägt etwas fehl, bricht die innere Sequenz ab; der Auftrag bleibt offen und wird danach als Fehler zurückgegeben."""
    return {"alias": "HEIZEN-Befehl als abgesicherter Auftrag senden", "continue_on_error": True, "sequence": [
        flag("IR-Auftrag als offen markieren", "f_auftrag", True),
        {"alias": "Nur senden, wenn alle Heizkörper sicher geschlossen sind", "condition": "template",
         "value_template": ("{%- set ns = namespace(zu=true) -%}{%- for t in heizkoerper -%}{%- if not (states(t) in ['heat', 'off'] and is_number(state_attr(t, 'temperature')) "
                            "and state_attr(t, 'temperature') | float(99) <= 5) -%}{%- set ns.zu = false -%}{%- endif -%}{%- endfor -%}"
                            "{%- for v in ventile -%}{%- if not (is_number(states(v)) and states(v) | float(99) == 0) -%}{%- set ns.zu = false -%}{%- endif -%}{%- endfor -%}"
                            "{{ is_state(bt, 'off') and heizkoerper | count > 0 and ns.zu }}")},
        strom_sichern(),
        ir("Gelernten Vollzustand HEIZEN senden", "befehl_heizen"),
        flag("Heizbefehl als aktiv markieren", "f_heizbefehl", True),
        flag("IR-Auftrag schließen", "f_auftrag", False)]}


def ir_aus():
    return {"alias": "HEIZEN-AUS-Befehl senden", "continue_on_error": True, "sequence": [
        strom_sichern(),
        ir("Gelernten AUS-Zustand senden", "befehl_heizen_aus"),
        flag("Heizbefehl zurücknehmen", "f_heizbefehl", False),
        flag("IR-Auftrag schließen", "f_auftrag", False)]}


def beenden():
    """Entspricht dem Skript „PV beenden“ (ohne automation.trigger – die Raumheizung reagiert selbst auf die Helfer)."""
    return [
        {"alias": "Bisherige PV-Verantwortung merken", "variables": {
            "hat_pv": "{{ is_state(f_regelung, 'on') or is_state(f_heizbefehl, 'on') or is_state(f_auftrag, 'on') or is_state(f_vorbereitung, 'on') }}"}},
        {"alias": "Klimaanlage nur bei eigener Heizanforderung ausschalten", "if": [c(
            "Eigener Heizbefehl oder offener Auftrag", "{{ is_state(f_heizbefehl, 'on') or is_state(f_auftrag, 'on') }}")], "then": [ir_aus()]},
        flag("Startvorbereitung beenden", "f_vorbereitung", False),
        t_cancel("Heizkörperfrist abbrechen", "t_heizkoerper"),
        flag("PV-Verantwortung abgeben", "f_regelung", False),
        t_cancel("Sicherheitsfreigabe abbrechen (Heizkörper werden sofort freigegeben)", "t_freigabe"),
        {"alias": "Fehlgeschlagene Sendung sperrt weitere Versuche", "if": [c(
            "Sendefehler oder Befehl nicht sicher zurückgenommen",
            "{{ rueckgabe_fehler | default(false) or is_state(f_heizbefehl, 'on') or is_state(f_auftrag, 'on') }}")], "then": [
            flag("IR-Fehler setzen", "f_fehler", True),
            flag("PV-Heizfreigabe ausschalten", "f_heizfreigabe", False),
            {"alias": "IR-Fehler dauerhaft melden", "action": "persistent_notification.create", "data": {
                "notification_id": "{{ 'hz_pv_ir_fehler_' ~ raum_schluessel }}", "title": "{{ raum_name }} PV: IR-Senden fehlgeschlagen",
                "message": ("PV gesperrt, normale Heizung freigegeben. Klimazustand vor Ort prüfen und ggf. mit der Originalfernbedienung ausschalten. "
                            "Danach „IR-Fehler“ ausschalten und die PV-Heizfreigabe erneut einschalten.")}},
            status("'IR-Sendefehler: PV gesperrt, Klimazustand vor Ort pruefen'")]},
        {"alias": "Restliche PV-Merker zurücksetzen", "action": "input_boolean.turn_off",
         "target": {"entity_id": "{{ [f_heizbefehl, f_auftrag, f_wiederholt] }}"}, "continue_on_error": True},
        t_cancel("Startfrist abbrechen", "t_startfrist"),
        t_cancel("Mangelfrist abbrechen", "t_mangelfrist"),
        t_cancel("IR-Wiederholung abbrechen", "t_wiederholung"),
        t_cancel("Wärmeprüfung abbrechen", "t_waermepruefung"),
        {"alias": "Nach beendetem PV-Betrieb erneute Versuche begrenzen", "if": [c("PV war verantwortlich", "{{ hat_pv }}")], "then": [
            t_start("Wiederanlaufsperre starten", "t_sperre", "sperre_minuten"),
            t_start("Schaltpause starten", "t_schaltpause", "schaltpause_minuten")]},
        {"alias": "Rückgabegrund anzeigen, Fehlerhinweis hat Vorrang", "if": [c("Kein IR-Fehler", "{{ not is_state(f_fehler, 'on') }}")],
         "then": [status("rueckgabe_grund | default('PV beendet: normale Heizung uebernimmt')")]},
    ]


def trigger():
    return [
        {"alias": "Energie-, Raum- oder Schutzdaten geändert", "trigger": "state", "entity_id": Inp("soc"), "id": "daten"},
        {"alias": "Netzleistung geändert", "trigger": "state", "entity_id": Inp("netz"), "id": "daten"},
        {"alias": "Batterieleistung geändert", "trigger": "state", "entity_id": Inp("akku_leistung"), "id": "daten"},
        {"alias": "PV-Leistung geändert", "trigger": "state", "entity_id": Inp("pv_leistung"), "id": "daten"},
        {"alias": "Hausverbrauch geändert", "trigger": "state", "entity_id": Inp("verbrauch"), "id": "daten"},
        {"alias": "Raum- oder Außentemperatur geändert", "trigger": "state", "entity_id": Inp("raumfuehler"), "id": "daten"},
        {"alias": "Außentemperatur geändert", "trigger": "state", "entity_id": Inp("aussentemperatur"), "id": "daten"},
        {"alias": "Better Thermostat geändert", "trigger": "state", "entity_id": Inp("better_thermostat"), "id": "daten"},
        {"alias": "Heizkörperthermostat geändert", "trigger": "state", "entity_id": Inp("heizkoerper"), "id": "daten"},
        {"alias": "Ventilöffnung geändert", "trigger": "state", "entity_id": Inp("ventile"), "id": "daten"},
        {"alias": "Fenster geändert", "trigger": "state", "entity_id": Inp("fensterkontakte"), "id": "daten"},
        {"alias": "Heizprofil oder Klimabedienung geändert", "trigger": "state", "entity_id": Inp("heizprofil"), "id": "daten"},
        {"alias": "Klima-Modus geändert", "trigger": "state", "entity_id": Inp("klima_modus"), "id": "daten"},
        {"alias": "Kühlbefehl der Klimaautomatik geändert", "trigger": "state", "entity_id": Inp("klima_aktiv"), "id": "daten"},
        {"alias": "PV-Heizfreigabe geändert", "trigger": "state", "entity_id": Inp("f_heizfreigabe"), "id": "daten"},
        {"alias": "IR-Prüffreigabe geändert", "trigger": "state", "entity_id": Inp("f_ir_geprueft"), "id": "daten"},
        {"alias": "IR-Fehler quittiert oder gesetzt", "trigger": "state", "entity_id": Inp("f_fehler"), "id": "daten"},
        {"alias": "Startvorbereitung geändert", "trigger": "state", "entity_id": Inp("f_vorbereitung"), "id": "daten"},
        {"alias": "Raumheizung oder Klimaautomatik ein-/ausgeschaltet", "trigger": "state", "entity_id": Inp("raumheizung_automation"), "id": "daten"},
        {"alias": "Klimaautomatik ein-/ausgeschaltet", "trigger": "state", "entity_id": Inp("klima_automation"), "id": "daten"},
        *[{"alias": f"Frist abgelaufen: {n}", "trigger": "event", "event_type": "timer.finished", "event_data": {"entity_id": Inp(k)}, "id": "timer"}
          for k, n, _, _ in TIMER],
        {"alias": "Alle 30 s: stillstehende Daten prüfen und befristete Freigabe erneuern", "trigger": "time_pattern", "seconds": "/30", "id": "sicherheit"},
        {"alias": "Nach dem Neustart PV nicht blind fortsetzen", "trigger": "homeassistant", "event": "start", "id": "boot"},
        {"alias": "Rückmeldung: Heizbefehl seit der Prüfzeit zurückgenommen", "trigger": "state", "entity_id": Inp("f_heizbefehl"), "to": "off",
         "for": {"minutes": Inp("pruef_aus_min")}, "id": "aus_pruefung"},
        {"alias": "Rückmeldung: Heizbefehl seit der doppelten Prüfzeit zurückgenommen (nach der Wiederholung)", "trigger": "state", "entity_id": Inp("f_heizbefehl"), "to": "off",
         "for": "{{ '%02d:%02d:00' % ((pruef_aus_tv | int * 2) // 60, (pruef_aus_tv | int * 2) % 60) }}", "id": "aus_pruefung2"},
    ]


def aus_pruefung():
    """Läuft die Klimaanlage nach HEIZEN-AUS (Pause oder Ende) weiter: nach der Prüfzeit AUS einmal wiederholen, nach der doppelten Prüfzeit
    IR-Fehler setzen. Kein Warten im Lauf – die 30-s-Sicherheitsprüfung der PV-Sitzung bleibt ungestört."""
    meldung = "{{ 'hz_pv_rueckmeldung_' ~ raum_schluessel }}"
    return {"alias": "Rückmeldung nach HEIZEN-AUS prüfen (eigener Lauf, danach Ende)", "if": [c(
        "Prüfzeit nach HEIZEN-AUS abgelaufen", "{{ trigger.id in ['aus_pruefung', 'aus_pruefung2'] }}")], "then": [
        {"alias": "Nur wenn die Klimaanlage trotz AUS weiterläuft und niemand anderes sie nutzt", "if": [c(
            "Leistung über der Laufschwelle, kein Heiz- oder Kühlauftrag",
            "{{ leistung_ok and is_number(states(klima_leistung)) and states(klima_leistung) | float >= laeuft_ab_w | float "
            "and is_state(f_heizbefehl, 'off') and is_state(f_auftrag, 'off') and is_state(klima_modus, 'Aus') and is_state(klima_aktiv, 'off') "
            "and not is_state(f_fehler, 'on') }}")], "then": [
            {"alias": "Erste Prüfung: wiederholen – zweite Prüfung: IR-Fehler", "if": [c("Erste Prüfung", "{{ trigger.id == 'aus_pruefung' }}")], "then": [
                {"alias": "Im Logbuch festhalten", "action": "logbook.log", "data": {
                    "name": "{{ raum_name }} PV",
                    "message": "Klimaanlage nimmt {{ pruef_aus_min | int }} min nach HEIZEN-AUS noch {{ states(klima_leistung) }} W auf – AUS wird einmal wiederholt.",
                    "entity_id": "{{ f_heizbefehl }}"}},
                {"alias": "HEIZEN-AUS erneut senden", "continue_on_error": True, "sequence": [
                    strom_sichern(), ir("Gelernten AUS-Zustand erneut senden", "befehl_heizen_aus")]}],
             "else": [
                flag("IR-Fehler setzen (PV gesperrt bis zur Quittierung)", "f_fehler", True),
                {"alias": "Dauerhafte Meldung", "action": "persistent_notification.create", "data": {
                    "notification_id": meldung, "title": "{{ raum_name }} PV: Klimaanlage läuft nach HEIZEN-AUS weiter",
                    "message": ("HEIZEN-AUS wurde zweimal gesendet, die Klimaanlage nimmt aber weiter {{ states(klima_leistung) }} W auf. PV-Heizen ist gesperrt. "
                                "Bitte vor Ort prüfen und notfalls mit der Originalfernbedienung ausschalten, danach „IR-Fehler“ ausschalten.")}},
                status("'IR-Fehler: Klimaanlage laeuft nach HEIZEN-AUS weiter, vor Ort pruefen'")]}]},
        {"alias": "Rückmeldungsprüfung beendet", "stop": "Rückmeldung nach HEIZEN-AUS geprüft"}]}


def aktionen():
    a = [
        aus_pruefung(),
        {"alias": "Aktuelle Eingangsdaten lesen", "variables": {"x": X}},
        {"alias": "Regelungsschritt entscheiden", "variables": {"d": D}},
        {"alias": "Bei freigegebener Sitzung die befristete Heizkörperpause verlängern", "if": [c("Sitzung sicher und PV verantwortlich", "{{ d.lease }}")],
         "then": [t_start("Sicherheitsfreigabe neu starten", "t_freigabe", "freigabe_minuten")]},
        {"alias": "Energiemangel während PV begrenzt tolerieren", "if": [c("PV verantwortlich und sicher", "{{ x.owner and d.safe and d.op != 'stop' }}")], "then": [
            {"alias": "Mangelfrist starten oder abbrechen", "if": [c("Zu wenig Energie", "{{ d.poor }}")],
             "then": [{"alias": "Laufende Frist nicht verlängern", "if": [c("Mangelfrist läuft noch nicht", "{{ is_state(t_mangelfrist, 'idle') }}")],
                       "then": [t_start("Mangelfrist starten", "t_mangelfrist", "mangel_minuten")]}],
             "else": [{"alias": "Energie erholt", "if": [c("Mangelfrist läuft", "{{ not is_state(t_mangelfrist, 'idle') }}")],
                       "then": [t_cancel("Mangelfrist abbrechen", "t_mangelfrist")]}]}]},
        {"alias": "Unterbrochene Startbedingungen setzen die Bestätigung zurück", "if": [c(
            "Keine Qualifikation mehr und Startfrist läuft", "{{ d.op not in ['qualify', 'start_heat', 'prepare_heat'] and not is_state(t_startfrist, 'idle') }}")],
         "then": [t_cancel("Startfrist abbrechen", "t_startfrist")]},
        {"alias": "Genau den aktuellen Regelungsschritt ausführen", "choose": [
            {"alias": "Heizkörper vor dem Klimastart schließen", "conditions": [c("Startvorbereitung", "{{ d.op == 'prepare_heat' }}")], "sequence": [
                t_start("Heizkörperfrist starten", "t_heizkoerper", "heizkoerper_minuten"),
                t_start("Sicherheitsfreigabe starten", "t_freigabe", "freigabe_minuten"),
                flag("Startvorbereitung markieren", "f_vorbereitung", True),
                flag("PV übernimmt die Verantwortung (Raumheizung schließt die Heizkörper)", "f_regelung", True),
                status("'PV: Heizkoerper schliessen; Klima wartet auf Frostschutz und Ventile 0%'")]},
            {"alias": "Heizanforderung nach bestätigtem Start senden", "conditions": [c("Heizkörper geschlossen", "{{ d.op == 'start_heat' }}")], "sequence": [
                ir_ein(),
                {"alias": "Nur bei erfolgreichem Senden fortsetzen", "if": [c("Heizbefehl gesetzt und Auftrag geschlossen",
                                                                             "{{ is_state(f_heizbefehl, 'on') and is_state(f_auftrag, 'off') }}")], "then": [
                    flag("Startvorbereitung beenden", "f_vorbereitung", False),
                    t_cancel("Heizkörperfrist abbrechen", "t_heizkoerper"),
                    {"alias": "Starttemperatur für die Wärmeprüfung merken", "action": "input_number.set_value", "target": {"entity_id": "{{ starttemperatur }}"},
                     "data": {"value": "{{ states(raumfuehler) | float }}"}},
                    flag("Wiederholungsmerker löschen", "f_wiederholt", False),
                    t_start("IR-Wiederholungsfrist starten", "t_wiederholung", "wiederholung_minuten"),
                    t_start("Wärmeprüfung starten", "t_waermepruefung", "pruef_minuten"),
                    t_start("Sicherheitsfreigabe starten", "t_freigabe", "freigabe_minuten"),
                    flag("PV-Verantwortung bestätigen", "f_regelung", True),
                    status("'PV: HEIZEN angefordert; Heizwirkung wird geprueft'")]}]},
            {"alias": "Startbestätigung beginnen oder weiterlaufen lassen", "conditions": [c("Qualifikation", "{{ d.op == 'qualify' }}")], "sequence": [
                {"alias": "Nur eine laufende Startfrist", "if": [c("Startfrist läuft noch nicht", "{{ is_state(t_startfrist, 'idle') }}")],
                 "then": [t_start("Startfrist starten", "t_startfrist", "start_bestaetigung")]},
                status("d.reason")]},
            {"alias": "Zieltemperatur erreicht: Klimaanlage pausieren", "conditions": [c("Obere Schwelle", "{{ d.op == 'cycle_off' }}")], "sequence": [
                ir_aus(),
                {"alias": "Nur bei erfolgreichem AUS die Pause einleiten", "if": [c("Heizbefehl zurückgenommen", "{{ is_state(f_heizbefehl, 'off') }}")], "then": [
                    t_start("Schaltpause starten", "t_schaltpause", "schaltpause_minuten"),
                    t_cancel("IR-Wiederholung abbrechen", "t_wiederholung"),
                    t_cancel("Wärmeprüfung abbrechen", "t_waermepruefung"),
                    status("'PV-Regelung: Temperaturpause bis Einschaltgrenze'")]}]},
            {"alias": "Höchstens eine IR-Wiederholung je Heizzyklus", "conditions": [c("Wiederholung", "{{ d.op == 'retry' }}")], "sequence": [
                flag("Wiederholung vermerken", "f_wiederholt", True), ir_ein(),
                {"alias": "Status bei erfolgreicher Wiederholung", "if": [c("Auftrag geschlossen", "{{ is_state(f_auftrag, 'off') }}")], "then": [
                    t_start("IR-Wiederholungsfrist neu starten (danach Rückmeldung über die Leistung prüfen)", "t_wiederholung", "wiederholung_minuten"),
                    status("d.reason")]}]},
            {"alias": "Temperaturwirkung vorhanden: neues Prüffenster", "conditions": [c("Prüfung bestanden", "{{ d.op == 'proof_reset' }}")], "sequence": [
                {"alias": "Neue Temperaturreferenz merken", "action": "input_number.set_value", "target": {"entity_id": "{{ starttemperatur }}"}, "data": {"value": "{{ x.room }}"}},
                t_start("Wärmeprüfung neu starten", "t_waermepruefung", "pruef_minuten"),
                flag("Wiederholungsmerker setzen", "f_wiederholt", True),
                status("d.reason")]}],
         "default": [status("('PV: ' if x.owner else 'Blockiert: ') ~ d.reason ~ ('; Energiemangelfrist laeuft' if x.owner and d.poor else '')")]},
        {"alias": "Sichere Rückgabe bei Stopp oder fehlgeschlagenem Senden", "if": [c(
            "Stopp entschieden oder IR-Schritt fehlgeschlagen",
            "{{ d.op == 'stop' or (d.op == 'start_heat' and not (is_state(f_heizbefehl, 'on') and is_state(f_auftrag, 'off'))) "
            "or (d.op == 'retry' and is_state(f_auftrag, 'on')) or (d.op == 'cycle_off' and is_state(f_heizbefehl, 'on')) }}")], "then": [
            {"alias": "Grund und Fehlerstatus der Rückgabe bestimmen", "variables": {
                "rueckgabe_grund": ("{{ d.reason if d.op == 'stop' else ('IR-EIN fehlgeschlagen' if d.op == 'start_heat' else "
                                    "('IR-Wiederholung fehlgeschlagen' if d.op == 'retry' else 'IR-AUS fehlgeschlagen')) }}"),
                "rueckgabe_fehler": "{{ (x.pending or d.ir_fault) if d.op == 'stop' else true }}"}},
            *beenden()]},
    ]
    return a


def variablen():
    names = ["raum_name", "raum_schluessel", "heizkoerper", "ventile", "raumfuehler", "fensterkontakte", "ir_konfiguration", "soc", "netz", "akku_leistung", "pv_leistung", "verbrauch", "zeitstempel_attribut",
             "max_energie_alter", "max_raum_alter", "max_aussen_alter", "start_leistung", "soc_start", "soc_halten", "akku_entladung_max",
             "aussen_start", "aussen_ende", "netzbezug_max", "pv_ziel", "einschalt_abstand", "anstieg_min", "heizprofil", "pv_profile",
             "raumheizung_automation", "klima_automation", "klima_modus", "klima_aktiv", "starttemperatur", "status_text", "heizstufe",
             "klima_steckdose", "vorlauf_s", "klima_leistung", "laeuft_ab_w", "pruef_aus_min"]
    names += [m for _, _, m, _ in TIMER] + [k for k, _, _, _ in TIMER] + [k for k, _ in FLAGS]
    v = {n: Inp(n) for n in names}
    v["bt"] = Inp("better_thermostat")
    v["aussen"] = Inp("aussentemperatur")
    v["steckdose_ok"] = "{{ klima_steckdose is string and klima_steckdose != '' }}"
    v["leistung_ok"] = "{{ klima_leistung is string and klima_leistung != '' }}"
    # Sender und Heizbefehle kommen ausschließlich aus der IR-Konfiguration der Klimaautomatik (eine Broadlink-Zuordnung je Raum)
    v["ir_cfg"] = ("{%- set d = namespace(s='', g='', h='', ha='') -%}"
                   "{%- for teil in (states(ir_konfiguration) if ir_konfiguration is string and ir_konfiguration != '' else '').split('|') -%}"
                   "{%- set kv = teil.split('=', 1) -%}{%- if kv | count == 2 -%}"
                   "{%- if kv[0] == 's' -%}{%- set d.s = kv[1] -%}{%- elif kv[0] == 'g' -%}{%- set d.g = kv[1] -%}"
                   "{%- elif kv[0] == 'h' -%}{%- set d.h = kv[1] -%}{%- elif kv[0] == 'ha' -%}{%- set d.ha = kv[1] -%}{%- endif -%}"
                   "{%- endif -%}{%- endfor -%}{{ {'s': d.s, 'g': d.g, 'h': d.h, 'ha': d.ha} }}")
    v["klima_sender"] = "{{ ir_cfg.s }}"
    v["ir_geraet"] = "{{ ir_cfg.g }}"
    v["befehl_heizen"] = "{{ ir_cfg.h | replace('{stufe}', (heizstufe | int) | string) }}"
    v["befehl_heizen_aus"] = "{{ ir_cfg.ha | replace('{stufe}', (heizstufe | int) | string) }}"
    return v


def blueprint():
    return {
        "blueprint": {
            "name": "PV-Überschussheizen (Raum)",
            "description": "Paketversion 1.6.0 · " + (
                "Optionale Ergänzung für Räume mit Klimaanlage: Bei PV-Überschuss und voller Batterie heizt die Klimaanlage (IR-Vollzustand) "
                "statt der Zentralheizung. Ablauf: Startbedingungen 5 min bestätigen → Heizkörper über die "
                "Raumheizungssteuerung schließen und Ventile prüfen → Klimaanlage heizen → Wärmeprüfung mit einer IR-Wiederholung → "
                "Temperaturpause → Ende bei Energiemangel, Kälte/Wärme, Fenster, Profil oder Fehler. Sicherheitsprinzip: Die "
                "Heizkörperpause gilt nur, solange diese Automation ihre befristete Freigabe alle 30 s erneuert. Fällt sie aus, übernimmt "
                "die Raumheizung automatisch, und die Klimaautomatik schaltet die Klimaanlage ab.\n\nVoraussetzungen im selben Raum: "
                "„Universelle Raumheizungssteuerung“ (mit PV-Zusammenarbeit) und „Klimaautomatik“ (mit PV-Zusammenarbeit).\n\nOptional mit schaltbarer Messsteckdose: Strom vor jedem IR-Befehl gesichert, IR-Wiederholung nach der Leistung statt nach dem Temperaturanstieg, Rückmeldung nach HEIZEN-AUS."),
            "domain": "automation", "author": "HA-Heizung-Universal",
            "homeassistant": {"min_version": "2026.11.0"},
            "input": inputs(),
        },
        "mode": "queued", "max": 20, "max_exceeded": "warning", "trace": {"stored_traces": 20},
        "trigger_variables": {"pruef_aus_tv": Inp("pruef_aus_min")},
        "variables": variablen(), "triggers": trigger(), "conditions": [
            {"alias": "Nur Ablauf-Ereignisse der eigenen Timer auswerten", "condition": "template",
             "value_template": "{{ trigger.id != 'timer' or trigger.event.data.entity_id in [t_startfrist, t_mangelfrist, t_wiederholung, t_waermepruefung, t_sperre, t_freigabe, t_schaltpause, t_heizkoerper] }}"}],
        "actions": aktionen(),
    }


if __name__ == "__main__":
    ZIELDATEI.parent.mkdir(parents=True, exist_ok=True)
    ZIELDATEI.write_text("# PV-Überschussheizen – Blueprint 3 von 3 (optional)\n# Erzeugt mit tools/build_pv.py\n" + dump(blueprint()), encoding="utf-8")
    print("geschrieben:", ZIELDATEI.relative_to(BASIS))
