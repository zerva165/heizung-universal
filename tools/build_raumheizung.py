#!/usr/bin/env python3
"""Erzeugt Blueprint 1 „Universelle Raumheizungssteuerung“.

Die Blueprint enthält viele gleichartige Felder (4 Profile × 3 Tagesprogramme × bis zu 3 Heizphasen). Sie wird deshalb
aus diesem Skript erzeugt, damit Feldnamen, Trigger und Aliasse konsistent bleiben.
Ausgabe: blueprints/automation/ha_heizung_universal/universelle_raumheizungssteuerung.yaml
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from yamlgen import Inp, dump  # noqa: E402

BASIS = Path(__file__).resolve().parent.parent
ZIEL = BASIS / "blueprints" / "automation" / "ha_heizung_universal" / "universelle_raumheizungssteuerung.yaml"

TAGE = [("mo", "Montag"), ("di", "Dienstag"), ("mi", "Mittwoch"), ("do", "Donnerstag"),
        ("fr", "Freitag"), ("sa", "Samstag"), ("so", "Sonntag")]
WERKTAGE = ["mo", "di", "mi", "do", "fr"]
ALLE_TAGE = ["mo", "di", "mi", "do", "fr", "sa", "so"]
WOCHENENDE = ["sa", "so"]

# Profil: (Schlüssel, Anzeigename, Icon, Soll, Absenk, Anzahl Phasen, Standardphasen)
TAGESPROGRAMME = [("wt", "Montag bis Freitag", WERKTAGE), ("sa", "Samstag", ["sa"]), ("so", "Sonntag", ["so"])]
_STD = {"wt": [("06:00:00", "08:00:00"), ("16:00:00", "22:00:00")], "sa": [("08:00:00", "22:00:00")], "so": [("08:00:00", "22:00:00")]}
_URLAUB = {t: [("09:00:00", "19:00:00")] for t in ("wt", "sa", "so")}
# (Schlüssel, Name, Symbol, Soll, Absenk, Heizphasen je Tagesprogramm, Standard-Heizphasen je Tagesprogramm)
PROFILE = [
    ("komfort", "Komfort", "mdi:sofa", 22.0, 18.0, 3, _STD),
    ("uebergang", "Übergang", "mdi:leaf", 21.0, 17.0, 3, _STD),
    ("urlaub", "Urlaub", "mdi:palm-tree", 17.0, 16.0, 3, _URLAUB),
    ("sommer", "Sommer", "mdi:white-balance-sunny", 19.0, 16.0, 3, {"wt": [], "sa": [], "so": []}),
]


def sel_number(mn, mx, step, unit, mode="slider"):
    return {"number": {"min": mn, "max": mx, "step": step, "mode": mode, "unit_of_measurement": unit}}


def sel_entity(domain, multiple=False, device_class=None, integration=None):
    f = {"domain": domain if isinstance(domain, list) else [domain]}
    if device_class:
        f["device_class"] = device_class if isinstance(device_class, list) else [device_class]
    if integration:
        f["integration"] = integration
    return {"entity": {"filter": [f], "multiple": multiple}}


TAGE_SELECTOR = {"select": {"multiple": True, "mode": "list",
                            "options": [{"value": t, "label": n} for t, n in TAGE]}}


# ======================================================================= Inputs
def inputs():
    inp = {}
    inp["geraete"] = {
        "name": "Raum und Geräte",
        "icon": "mdi:home-thermometer",
        "description": (
            "Die Geräte dieses Raums. Bei einem Gerätetausch wird nur hier (bzw. in den Optionen des "
            "Better Thermostat) die neue Entität ausgewählt – Karte und Logik folgen automatisch."
        ),
        "input": {
            "raum_name": {"name": "Raumname", "description": "Erscheint in Meldungen, Status und auf der Dashboard-Karte.",
                          "default": "Raum", "selector": {"text": {}}},
            "raum_schluessel": {"name": "Raumkennung", "description": (
                "Kurze Kennung ohne Leer- und Sonderzeichen, z. B. `buero`. Wird nur für die festen IDs von "
                "Meldungen verwendet. Der Einrichtungsassistent füllt sie automatisch."),
                "default": "raum", "selector": {"text": {}}},
            "better_thermostat": {"name": "Better Thermostat", "description": (
                "Das Better Thermostat des Raums. Es ist das einzige Stellglied dieser Automation. Die zugehörigen "
                "Heizkörperthermostate sind in den Better-Thermostat-Optionen hinterlegt."),
                "selector": sel_entity("climate", integration="better_thermostat")},
            "raumfuehler": {"name": "Externer Raumtemperaturfühler (optional)", "description": (
                "Für Status, Karte und das optionale Vorheizen. Leer lassen = Raumtemperatur des Better Thermostat "
                "verwenden (das ist i. d. R. derselbe Fühler)."),
                "default": [], "selector": sel_entity("sensor", device_class="temperature")},
            "aussentemperatur": {"name": "Außentemperatur", "description": "Für die Außentemperatursperre.",
                                 "selector": sel_entity("sensor", device_class="temperature")},
        },
    }
    inp["helfer"] = {
        "name": "Raum-Helfer",
        "icon": "mdi:tune-variant",
        "collapsed": True,
        "description": (
            "Diese Helfer legt der Einrichtungsassistent automatisch an und trägt sie hier ein. Bei manueller "
            "Einrichtung: Heizprofil-Auswahl (input_select mit Komfort, Übergang, Sommer, Urlaub, Aus) und "
            "Status-Text (input_text, max. 255) anlegen; die übrigen nur für die jeweils aktivierte Funktion."),
        "input": {
            "heizprofil": {"name": "Heizprofil-Auswahl", "description": "input_select mit den Optionen Komfort, Übergang, Sommer, Urlaub, Aus.",
                           "selector": sel_entity("input_select")},
            "status_text": {"name": "Status-Text für die Dashboard-Karte (empfohlen)", "description": (
                "input_text (max. 255). Die Automation schreibt hier Raumtemperatur, Plan, Fensterzustand und "
                "Vorheizstatus hinein. Die Dashboard-Karte liest ausschließlich diesen Text und die Raum-Helfer – "
                "dadurch enthält sie keine Geräte-IDs."),
                "default": [], "selector": sel_entity("input_text")},
            "haus_heizung_aus": {"name": "Globaler Schalter „Heizung Aus“ (optional)", "description": (
                "input_boolean für das ganze Haus. Ist er an, verhält sich dieser Raum wie im Profil „Aus“ "
                "(Frostschutz). Ein bewusster Profilwechsel in diesem Raum schaltet ihn wieder aus."),
                "default": [], "selector": sel_entity("input_boolean")},
        },
    }
    for key, name, icon, soll, absenk, n, std in PROFILE:
        sec = {
            "name": f"Profil {name}",
            "icon": icon,
            "collapsed": True,
            "description": (
                f"Temperaturen und Heizphasen für das Profil „{name}“. Zum „Beginn“ einer Heizphase wird die Solltemperatur an das "
                f"Better Thermostat gesendet, ab „Absenkung ab“ die Absenktemperatur. Vorher oder dazwischen wird nichts verändert. "
                f"Nur wenn im Abschnitt „Vorausschauendes Vorheizen“ eingeschaltet, kann je Heizphase zusätzlich eine "
                f"Mindesttemperatur bis zum Beginn verlangt werden."),
            "input": {},
        }
        if key == "sommer":
            sec["description"] = (
                "Standard wie im Bestand: Im Sommer wird nicht geheizt (Frostschutz). Wer im Sommerprofil trotzdem "
                "zeitweise heizen möchte, aktiviert „Im Sommer heizen“ und stellt die Phasen ein.")
            sec["input"]["sommer_heizen"] = {"name": "Im Sommer heizen", "default": False, "selector": {"boolean": {}}}
            vis = {"field": "sommer_heizen", "value": True}
        else:
            vis = None

        def v(extra=None):
            conds = [c for c in (vis, extra) if c]
            if not conds:
                return {}
            return {"visible": conds[0] if len(conds) == 1 else conds}

        sec["input"][f"{key}_soll"] = {"name": "Solltemperatur", "default": soll, **v(),
                                       "selector": sel_number(5, 28, 0.5, "°C")}
        sec["input"][f"{key}_absenk"] = {"name": "Absenktemperatur", "description": "Gilt außerhalb der Heizphasen dieses Profils.",
                                         "default": absenk, **v(), "selector": sel_number(5, 25, 0.5, "°C")}
        sec["input"][f"{key}_quelle"] = {
            "name": "Zeitquelle", "default": "phasen", **v(),
            "description": "Die Tagesprogramme stehen in den drei folgenden Abschnitten dieses Profils. Alternativ einen Zeitplan-Helfer verwenden.",
            "selector": {"select": {"mode": "list", "options": [
                {"value": "phasen", "label": "Drei Tagesprogramme hier einstellen (Montag bis Freitag, Samstag, Sonntag)"},
                {"value": "zeitplan", "label": "Vorhandenen Zeitplan-Helfer (schedule) verwenden"}]}}}
        sec["input"][f"{key}_zeitplan"] = {"name": "Zeitplan-Helfer", "default": [],
                                           **v({"field": f"{key}_quelle", "value": "zeitplan"}),
                                           "description": "„an“ = Solltemperatur, „aus“ = Absenkung.",
                                           "selector": sel_entity("schedule")}
        zp = [c for c in (vis, {"field": f"{key}_quelle", "value": "zeitplan"}, {"field": "vorheizen_aktiv", "value": True}) if c]
        sec["input"][f"{key}_zp_vh"] = {"name": "Vorheizen vor jedem Zeitplan-Beginn", "default": False, "visible": zp,
                                        "selector": {"boolean": {}}}
        sec["input"][f"{key}_zp_vh_temp"] = {"name": "Mindesttemperatur bis zum Zeitplan-Beginn", "default": max(soll - 1, 5),
                                             "visible": zp + [{"field": f"{key}_zp_vh", "value": True}], "selector": sel_number(5, 28, 0.5, "°C")}
        tagesabschnitte = []
        for tag, tagname, _ in TAGESPROGRAMME:
            sichtbar = [c for c in (vis, {"field": f"{key}_quelle", "value": "phasen"}) if c]
            tsec = {"name": f"{name} – {tagname}", "icon": icon, "collapsed": True,
                    "description": (f"Tagesprogramm „{tagname}“ im Profil „{name}“: bis zu drei Heizphasen, jede einzeln ein- und ausschaltbar. "
                                    f"Innerhalb einer Heizphase gilt die Solltemperatur des Profils, außerhalb die Absenktemperatur."),
                    "visible": sichtbar[0] if len(sichtbar) == 1 else sichtbar, "input": {}}
            for i in range(1, n + 1):
                zeiten = std[tag]
                on = i <= len(zeiten)
                von, bis = zeiten[i - 1] if on else ("06:00:00", "08:00:00")
                pre = f"{key}_{tag}{i}"
                akt = {"field": f"{pre}_aktiv", "value": True}
                tsec["input"][f"{pre}_aktiv"] = {"name": f"Heizphase {i} verwenden", "default": on, "selector": {"boolean": {}}}
                tsec["input"][f"{pre}_von"] = {"name": f"Heizphase {i} – Beginn (Solltemperatur wird gesendet)", "default": von,
                                               "visible": akt, "selector": {"time": {}}}
                tsec["input"][f"{pre}_bis"] = {"name": f"Heizphase {i} – Ende (Absenkung ab)", "default": bis,
                                               "description": "Liegt die Uhrzeit vor dem Beginn, endet die Phase am Folgetag (über Mitternacht).",
                                               "visible": akt, "selector": {"time": {}}}
                vh3 = [akt, {"field": "vorheizen_aktiv", "value": True}]
                tsec["input"][f"{pre}_vh"] = {"name": f"Heizphase {i} – vorausschauend vorheizen", "default": False, "visible": vh3,
                                              "selector": {"boolean": {}}}
                tsec["input"][f"{pre}_vh_temp"] = {"name": f"Heizphase {i} – Mindesttemperatur bis zum Beginn", "default": max(soll - 1, 5),
                                                   "description": "Darf niedriger sein als die Solltemperatur. Zum Beginn wird trotzdem die reguläre Solltemperatur gesendet.",
                                                   "visible": vh3 + [{"field": f"{pre}_vh", "value": True}], "selector": sel_number(5, 28, 0.5, "°C")}
                tsec["input"][f"{pre}_vh_bis"] = {"name": f"Heizphase {i} – Mindesttemperatur erreicht bis (Uhrzeit)", "default": von,
                                                  "description": ("Standard = Beginn der Heizphase. Eine frühere Uhrzeit (am selben Tag) ist möglich; bis zum "
                                                                  "Beginn wird die Mindesttemperatur dann gehalten. Eine spätere Uhrzeit als der Beginn wird ignoriert."),
                                                  "visible": vh3 + [{"field": f"{pre}_vh", "value": True}], "selector": {"time": {}}}
            tagesabschnitte.append((f"profil_{key}_{tag}", tsec))
        for art, schalter, titel, std_temp in (("m", "mindest_aktiv", "Mindesttemperatur-Termin", max(soll - 1, 5)),
                                               ("z", "zieltermin_aktiv", "Zieltemperatur-Termin", soll)):
            for j in range(1, (2 if key == "sommer" else 4) + 1):
                tv = [c for c in (vis, {"field": schalter, "value": True}) if c]
                sec["input"][f"{key}_{art}{j}_aktiv"] = {"name": f"{titel} {j} verwenden", "default": False,
                                                         "visible": tv[0] if len(tv) == 1 else tv, "selector": {"boolean": {}}}
                tv2 = tv + [{"field": f"{key}_{art}{j}_aktiv", "value": True}]
                sec["input"][f"{key}_{art}{j}_tage"] = {"name": f"{titel} {j} – Wochentage", "default": ALLE_TAGE, "visible": tv2,
                                                        "selector": TAGE_SELECTOR}
                sec["input"][f"{key}_{art}{j}_zeit"] = {"name": f"{titel} {j} – Uhrzeit, zu der die Temperatur erreicht sein soll",
                                                        "default": "06:00:00", "visible": tv2, "selector": {"time": {}}}
                sec["input"][f"{key}_{art}{j}_temp"] = {"name": f"{titel} {j} – Temperatur", "default": std_temp, "visible": tv2,
                                                        "selector": sel_number(5, 28, 0.5, "°C")}
        inp[f"profil_{key}"] = sec
        for schluessel, tsec in tagesabschnitte:
            inp[schluessel] = tsec

    inp["aus_sperren"] = {
        "name": "Aus, Frostschutz und Sperren",
        "icon": "mdi:snowflake-alert",
        "collapsed": True,
        "input": {
            "frostschutz": {"name": "Frostschutz-Temperatur (Profil „Aus“, Sommer ohne Heizen, Sperren)", "default": 5,
                            "description": "Zugleich die Schwelle, ab der ein Boostwert als „Boost aktiv“ gilt (größer als dieser Wert).",
                            "selector": sel_number(5, 12, 0.5, "°C", "box")},
            "aussensperre_aktiv": {"name": "Außentemperatursperre", "default": True,
                                   "description": "Wie im Bestand: Bei warmer Außentemperatur gilt Frostschutz.",
                                   "selector": {"boolean": {}}},
            "aussensperre_grenze": {"name": "Sperre ab Außentemperatur (größer als)", "default": 20,
                                    "visible": {"field": "aussensperre_aktiv", "value": True},
                                    "selector": sel_number(10, 30, 0.5, "°C")},
            "ersatz_temperatur": {"name": "Ersatz-Sollwert bei ungültigem Profil", "default": 16,
                                  "description": "Nur wenn die Profilauswahl ungültig ist und das Better Thermostat keinen Sollwert über Frostschutz hat.",
                                  "selector": sel_number(5, 25, 0.5, "°C", "box")},
        },
    }
    inp["vorheizen"] = {
        "name": "Vorheizen, Mindest- und Zieltemperatur-Termine (optional, Standard: aus)",
        "icon": "mdi:clock-start",
        "collapsed": True,
        "description": (
            "Ausgeschaltet (Standard) wird die Solltemperatur genau zum Beginn der Heizphase gesendet – ohne jede vorzeitige "
            "Sollwertänderung. Eingeschaltet erscheinen in jedem Profil je Heizphase die Felder „vorausschauend vorheizen“ und "
            "„Mindesttemperatur bis zum Beginn“. Für diese Phasen sendet die Automation möglichst spät vorher die Mindesttemperatur an "
            "das Better Thermostat, damit sie zum Beginn erreicht ist; zum Beginn folgt unverändert die reguläre Solltemperatur. "
            "Der Vorlauf wird aus Temperaturdifferenz und Aufheizrate berechnet (gelernte Rate des Better Thermostat, sonst "
            "Ersatzwert) und über einen Korrekturfaktor nachgelernt. Zum Beginn wird ehrlich bewertet, ob die Mindesttemperatur "
            "erreicht wurde. Heizzeiten und Zeitprogramme des Wärmeerzeugers werden nie verändert. Fenster, Profile, Sperren und "
            "Absenkzeiten haben Vorrang."),
        "input": {
            "vorheizen_aktiv": {"name": "Vorausschauendes Vorheizen vor Heizphasen verwenden", "default": False,
                                "description": "Blendet in jedem Profil je Heizphase die Vorheiz-Felder ein.", "selector": {"boolean": {}}},
            "mindest_aktiv": {"name": "Mindesttemperatur zu festen Uhrzeiten erreichen", "default": False,
                              "description": ("Blendet in jedem Profil bis zu 4 Mindesttemperatur-Termine ein (Wochentage, Uhrzeit, Temperatur). "
                                              "Beispiel: Mittwoch 04:20 Uhr mindestens 21 °C. Der Sollwert wird dafür rechtzeitig vorher angehoben, nie abgesenkt."),
                              "selector": {"boolean": {}}},
            "mindest_halten": {"name": "Mindesttemperatur nach dem Termin halten", "default": 120,
                               "visible": {"field": "mindest_aktiv", "value": True},
                               "description": "So lange gilt die Mindesttemperatur nach der Uhrzeit weiter. Beginnt vorher eine Heizphase mit höherer Solltemperatur, gilt diese.",
                               "selector": sel_number(0, 480, 5, "min")},
            "zieltermin_aktiv": {"name": "Zieltemperatur zu festen Uhrzeiten erreichen", "default": False,
                                 "description": ("Blendet in jedem Profil bis zu 4 Zieltemperatur-Termine ein. Beispiel: Samstag 18:30 Uhr spätestens 22,5 °C. "
                                                 "Die Zieltemperatur darf auch über der Solltemperatur des Profils liegen und gilt auch innerhalb einer Heizphase."),
                                 "selector": {"boolean": {}}},
            "zieltermin_halten": {"name": "Zieltemperatur nach dem Termin halten", "default": 60,
                                  "visible": {"field": "zieltermin_aktiv", "value": True},
                                  "selector": sel_number(0, 480, 5, "min")},
            "vorheizen_max": {"name": "Maximale Vorlaufzeit", "default": 180,
                              "selector": sel_number(15, 720, 15, "min")},
            "vorheizen_puffer": {"name": "Zeitpuffer", "description": "Wird zur berechneten Vorlaufzeit addiert.", "default": 15,
                                 "selector": sel_number(0, 60, 5, "min")},
            "vorheizen_rate": {"name": "Ersatz-Aufheizrate", "description": (
                "Wird verwendet, solange das Better Thermostat noch keine plausible Aufheizrate (Attribut heating_power) gelernt hat."),
                "default": 1.0, "selector": sel_number(0.2, 4, 0.1, "K/h")},
            "vorheizen_toleranz": {"name": "Toleranz „erreicht“", "default": 0.3,
                                   "selector": sel_number(0, 1, 0.1, "K")},
            "vorheizen_lernen": {"name": "Korrekturfaktor automatisch nachlernen", "default": True,
                                 "selector": {"boolean": {}}},
            "waermeerzeuger": {"name": "Heizphase des Wärmeerzeugers (optional)", "description": (
                "Z. B. der Betriebszustand des Heizkreises (Wärmepumpe oder Kessel). Meldet er einen reduzierten Betrieb, rechnet die Vorlaufzeit mit "
                "verminderter Heizleistung, und ein dadurch verfehltes Ziel wird nicht zum Lernen verwendet."),
                "default": [], "selector": sel_entity(["sensor", "binary_sensor", "select"])},
            "waermeerzeuger_voll": {"name": "Zustände mit voller Heizleistung", "default": ["Normal", "Comfort", "on"],
                                   
                                    "selector": {"select": {"multiple": True, "custom_value": True, "mode": "dropdown",
                                                            "options": ["Normal", "Comfort", "on", "heating", "Heating"]}}},
            "waermeerzeuger_faktor": {"name": "Heizleistung im reduzierten Betrieb", "default": 40,
                                      "selector": sel_number(10, 100, 5, "%")},
            "vorheizen_faktor": {"name": "Helfer: Korrekturfaktor (input_number 0,5–3)", "default": [],
                                 "selector": sel_entity("input_number")},
            "vorheizen_merker": {"name": "Helfer: laufender Vorheizvorgang (input_text)", "default": [],
                                 "selector": sel_entity("input_text")},
            "vorheizen_bericht": {"name": "Helfer: letzter Vorheizbericht (input_text)", "default": [],
                                  "selector": sel_entity("input_text")},
        },
    }
    inp["fenster"] = {
        "name": "Fenster und Fail-safe",
        "icon": "mdi:window-open-variant",
        "collapsed": True,
        "description": (
            "Offene Fenster pausieren die Heizung. Fail-safe wie im Bestand: Fällt ein Kontakt aus (unknown/unavailable), "
            "bleibt der letzte Fensterstatus 10 Minuten erhalten; ein real offenes Fenster hat immer Vorrang; danach wird die "
            "Heizung freigegeben und einmalig gemeldet."),
        "input": {
            "fenster_modus": {"name": "Fensterüberwachung", "default": "ohne", "selector": {"select": {"mode": "list", "options": [
                {"value": "ohne", "label": "Kein Fensterkontakt in diesem Raum"},
                {"value": "eigen", "label": "Eigene Fensterkontakte mit Fail-safe überwachen"},
                {"value": "extern", "label": "Fensterstatus eines anderen Raums mitbenutzen (nur lesen)"}]}}},
            "fensterkontakte": {"name": "Fensterkontakte", "description": "Alle Kontakte, die die Heizung dieses Raums pausieren sollen.",
                                "default": [], "visible": {"field": "fenster_modus", "value": "eigen"},
                                "selector": {"entity": {"multiple": True, "filter": [{"domain": ["binary_sensor"],
                                             "device_class": ["window", "door", "opening", "garage_door"]}]}}},
            "fensterstatus": {"name": "Fensterstatus-Helfer (input_boolean)", "description": (
                "„eigen“: wird ausschließlich von dieser Automation geschrieben (vom Assistenten angelegt). "
                "„extern“: den Fensterstatus-Helfer des anderen Raums auswählen."),
                "default": [], "selector": sel_entity("input_boolean")},
            "fenster_ausnahmen": {"name": "Kontakte, die Klimaanlage und PV-Heizen nicht pausieren (z. B. Balkontür)", "default": [],
                                  "description": "Diese Kontakte pausieren nur die Heizung. Für Klimaanlage und PV-Heizen zählt der Helfer darunter.",
                                  "visible": {"field": "fenster_modus", "value": "eigen"},
                                  "selector": {"entity": {"multiple": True, "filter": [{"domain": ["binary_sensor"]}]}}},
            "fensterstatus_klima": {"name": "Fensterstatus für Klimaanlage und PV-Heizen (input_boolean, ohne die Ausnahmen)", "default": [],
                                    "description": "Wird von dieser Automation geschrieben, wenn es Ausnahmen gibt (vom Assistenten angelegt).",
                                    "visible": {"field": "fenster_modus", "value": "eigen"}, "selector": sel_entity("input_boolean")},
            "fenster_timer": {"name": "Fail-safe-Timer (timer, Wiederherstellen aktiv)", "default": [],
                              "visible": {"field": "fenster_modus", "value": "eigen"}, "selector": sel_entity("timer")},
            "fenster_frist": {"name": "Ausfallfrist", "default": 10, "visible": {"field": "fenster_modus", "value": "eigen"},
                              "selector": sel_number(1, 60, 1, "min", "box")},
            "fenster_reaktion": {"name": "Heizungsreaktion auf offenes Fenster", "default": "blueprint", "selector": {"select": {"mode": "list", "options": [
                {"value": "blueprint", "label": "Diese Automation pausiert das Better Thermostat (keine BT-Einstellung nötig)"},
                {"value": "bt", "label": "Better Thermostat reagiert selbst (Fensterstatus-Helfer ist im BT als Fenstersensor eingetragen)"}]}}},
            "fenster_verzoegerung": {"name": "Heizpause beginnt nach", "default": 60, "visible": {"field": "fenster_reaktion", "value": "blueprint"}, "selector": sel_number(0, 600, 10, "s")},
            "fenster_nachlauf": {"name": "Weiterheizen nach dem Schließen nach", "default": 120, "visible": {"field": "fenster_reaktion", "value": "blueprint"}, "selector": sel_number(0, 900, 10, "s")},
        },
    }
    inp["boost"] = {
        "name": "Boost",
        "icon": "mdi:fire",
        "collapsed": True,
        "description": "Kurzzeitig höhere Temperatur. Startet nur bei einer echten Änderung des Boostwerts in Komfort, Übergang oder Urlaub; endet nach Ablauf, bei Wert = Frostschutz oder Profilwechsel.",
        "input": {
            "boost_aktiv": {"name": "Boost verwenden", "default": False, "selector": {"boolean": {}}},
            "boost_wert": {"name": "Boost-Temperatur (input_number, z. B. 5–25 °C)", "default": [],
                           "visible": {"field": "boost_aktiv", "value": True}, "selector": sel_entity("input_number")},
            "boost_timer": {"name": "Boost-Timer (Dauer im Timer, z. B. 2:00:00)", "default": [],
                            "visible": {"field": "boost_aktiv", "value": True}, "selector": sel_entity("timer")},
        },
    }
    inp["pv"] = {
        "name": "Zusammenarbeit mit PV-Überschussheizen",
        "icon": "mdi:solar-power-variant",
        "collapsed": True,
        "description": (
            "Nur für Räume mit der Blueprint „PV-Überschussheizen“. Solange die PV-Steuerung verantwortlich ist und ihre "
            "befristete Sicherheitsfreigabe läuft, wird das Better Thermostat ausgeschaltet (Heizkörper zu). Läuft die "
            "Freigabe ab – z. B. weil die PV-Automation ausfällt –, übernimmt diese Automation automatisch wieder."),
        "input": {
            "pv_aktiv": {"name": "PV-Überschussheizen in diesem Raum", "default": False, "selector": {"boolean": {}}},
            "pv_flags": {"name": "PV-Verantwortungs-Helfer", "description": "Regelung aktiv, Heizbefehl aktiv, IR-Auftrag offen, Startvorbereitung.",
                         "default": [], "visible": {"field": "pv_aktiv", "value": True},
                         "selector": {"entity": {"multiple": True, "filter": [{"domain": ["input_boolean"]}]}}},
            "pv_freigabe": {"name": "PV-Sicherheitsfreigabe (Timer)", "default": [], "visible": {"field": "pv_aktiv", "value": True},
                            "selector": sel_entity("timer")},
        },
    }
    inp["erweitert"] = {
        "name": "Erweitert",
        "icon": "mdi:cog",
        "collapsed": True,
        "input": {
            "ausgabe_modus": {"name": "Betriebsart", "default": "produktiv", "description": (
                "„Testbetrieb“ berechnet alles und schreibt das Ergebnis nur in den Status-Text – das Better Thermostat und "
                "der Boost-Timer werden nicht angesprochen."),
                "selector": {"select": {"mode": "list", "options": [
                    {"value": "produktiv", "label": "Normalbetrieb"},
                    {"value": "test", "label": "Testbetrieb (nur berechnen und anzeigen)"}]}}},
        },
    }
    reihenfolge = ["geraete", "helfer", "vorheizen"] + [k for k in inp if k not in ("geraete", "helfer", "vorheizen")]
    return {k: inp[k] for k in reihenfolge}


# ======================================================================= Variablen
def variablen():
    v = {}
    for name in ["raum_name", "raum_schluessel", "raumfuehler", "status_text", "haus_heizung_aus",
                 "frostschutz", "aussensperre_aktiv", "aussensperre_grenze", "ersatz_temperatur",
                 "vorheizen_aktiv", "mindest_aktiv", "mindest_halten", "zieltermin_aktiv", "zieltermin_halten", "vorheizen_max", "vorheizen_puffer", "vorheizen_rate", "vorheizen_toleranz",
                 "vorheizen_lernen", "waermeerzeuger", "waermeerzeuger_voll", "waermeerzeuger_faktor",
                 "vorheizen_faktor", "vorheizen_merker", "vorheizen_bericht",
                 "fenster_modus", "fensterkontakte", "fensterstatus", "fenster_timer", "fenster_frist", "fenster_ausnahmen", "fensterstatus_klima",
                 "fenster_reaktion", "fenster_verzoegerung", "fenster_nachlauf",
                 "boost_aktiv", "boost_wert", "boost_timer", "pv_aktiv", "pv_flags", "pv_freigabe", "ausgabe_modus",
                 "sommer_heizen"]:
        v[name] = Inp(name)
    v["bt"] = Inp("better_thermostat")
    v["aussen"] = Inp("aussentemperatur")
    v["profilhelfer"] = Inp("heizprofil")
    for key, name, icon, soll, absenk, n, std in PROFILE:
        v[f"cfg_{key}"] = {
            "soll": Inp(f"{key}_soll"), "absenk": Inp(f"{key}_absenk"),
            "quelle": Inp(f"{key}_quelle"), "zeitplan": Inp(f"{key}_zeitplan"),
            "zp_vh": Inp(f"{key}_zp_vh"), "zp_vh_temp": Inp(f"{key}_zp_vh_temp"),
            "phasen": [{"an": Inp(f"{key}_{tag}{i}_aktiv"), "tage": list(tage),
                        "von": Inp(f"{key}_{tag}{i}_von"), "bis": Inp(f"{key}_{tag}{i}_bis"),
                        "vh": Inp(f"{key}_{tag}{i}_vh"), "vh_temp": Inp(f"{key}_{tag}{i}_vh_temp"),
                        "vh_bis": Inp(f"{key}_{tag}{i}_vh_bis")} for tag, _, tage in TAGESPROGRAMME for i in range(1, n + 1)],
            "termine": [{"an": Inp(f"{key}_{art}{j}_aktiv"), "art": art, "tage": Inp(f"{key}_{art}{j}_tage"),
                         "zeit": Inp(f"{key}_{art}{j}_zeit"), "temp": Inp(f"{key}_{art}{j}_temp")}
                        for art in ("m", "z") for j in range(1, (2 if key == "sommer" else 4) + 1)],
        }
    v["ist_gesetzt"] = None  # Platzhalter, wird unten ersetzt
    del v["ist_gesetzt"]
    v["produktiv"] = "{{ ausgabe_modus == 'produktiv' }}"
    v["gueltige_profile"] = ["Komfort", "Übergang", "Urlaub", "Sommer", "Aus"]
    v["tage_kurz"] = ["mo", "di", "mi", "do", "fr", "sa", "so"]
    v["hat_status"] = "{{ status_text is string and status_text != '' }}"
    v["hat_haus_aus"] = "{{ haus_heizung_aus is string and haus_heizung_aus != '' }}"
    v["boost_ok"] = "{{ boost_aktiv and boost_wert is string and boost_wert != '' and boost_timer is string and boost_timer != '' }}"
    v["fenster_eigen"] = ("{{ fenster_modus == 'eigen' and fensterkontakte | count > 0 and fensterstatus is string and fensterstatus != '' "
                          "and fenster_timer is string and fenster_timer != '' }}")
    v["hat_fensterstatus"] = "{{ fenster_modus in ['eigen', 'extern'] and fensterstatus is string and fensterstatus != '' }}"
    v["pv_ok"] = "{{ pv_aktiv and pv_flags | count > 0 and pv_freigabe is string and pv_freigabe != '' }}"
    v["vorheizen_ok"] = ("{{ (vorheizen_aktiv or mindest_aktiv or zieltermin_aktiv) and vorheizen_merker is string and vorheizen_merker != '' "
                         "and vorheizen_faktor is string and vorheizen_faktor != '' }}")
    v["meldung_fenster"] = "{{ 'heizung_fensterausfall_' ~ raum_schluessel }}"
    return v


# ======================================================================= Trigger
def trigger():
    t = [
        {"alias": "Nach dem Start von Home Assistant neu berechnen und Fensterfrist abgleichen", "trigger": "homeassistant", "event": "start", "id": "neustart"},
        {"alias": "Nach dem Neuladen der Automationen Fensterstatus abgleichen", "trigger": "event", "event_type": "automation_reloaded", "id": "reload"},
        {"alias": "Heizprofil des Raums geändert", "trigger": "state", "entity_id": Inp("heizprofil"), "to": None, "id": "profil"},
        {"alias": "Globaler Schalter „Heizung Aus“ geändert", "trigger": "state", "entity_id": Inp("haus_heizung_aus"), "to": None, "id": "neuberechnen"},
        {"alias": "Außentemperatur geändert", "trigger": "state", "entity_id": Inp("aussentemperatur"), "to": None, "id": "neuberechnen"},
        {"alias": "Raumtemperaturfühler geändert", "trigger": "state", "entity_id": Inp("raumfuehler"), "to": None, "id": "raumtemperatur"},
        {"alias": "Raumtemperatur des Better Thermostat geändert", "trigger": "state", "entity_id": Inp("better_thermostat"),
         "attribute": "current_temperature", "id": "raumtemperatur"},
        {"alias": "Heizaktivität des Better Thermostat geändert (für die Karte)", "trigger": "state", "entity_id": Inp("better_thermostat"),
         "attribute": "hvac_action", "id": "anzeige"},
        {"alias": "Better Thermostat verfügbar oder Heizmodus geändert", "trigger": "state", "entity_id": Inp("better_thermostat"),
         "to": ["heat", "off"], "id": "bt_bereit"},
    ]
    for key, name, icon, soll, absenk, n, std in PROFILE:
        t.append({"alias": f"Zeitplan-Helfer {name} geändert", "trigger": "state", "entity_id": Inp(f"{key}_zeitplan"), "to": None, "id": "zeit"})
        for tag, tagname, _ in TAGESPROGRAMME:
            for i in range(1, n + 1):
                pre = f"{key}_{tag}{i}"
                t.append({"alias": f"{name} {tagname} Heizphase {i}: Beginn (Solltemperatur)", "trigger": "time", "at": Inp(f"{pre}_von"),
                          "id": "zeit", "enabled": Inp(f"{pre}_aktiv")})
                t.append({"alias": f"{name} {tagname} Heizphase {i}: Ende (Absenkung)", "trigger": "time", "at": Inp(f"{pre}_bis"),
                          "id": "zeit", "enabled": Inp(f"{pre}_aktiv")})
                t.append({"alias": f"{name} {tagname} Heizphase {i}: Zieluhrzeit des Vorheizens (Bewertung)", "trigger": "time", "at": Inp(f"{pre}_vh_bis"),
                          "id": "vorheizen", "enabled": Inp(f"{pre}_vh")})
        for art, titel in (("m", "Mindesttemperatur-Termin"), ("z", "Zieltemperatur-Termin")):
            for j in range(1, (2 if key == "sommer" else 4) + 1):
                t.append({"alias": f"{name} {titel} {j}: Uhrzeit erreicht (Bewertung)", "trigger": "time", "at": Inp(f"{key}_{art}{j}_zeit"),
                          "id": "vorheizen", "enabled": Inp(f"{key}_{art}{j}_aktiv")})
    t += [
        {"alias": "Vorausschauendes Vorheizen: alle 5 Minuten Vorlauf prüfen", "trigger": "time_pattern", "minutes": "/5",
         "id": "vorheizen", "enabled": Inp("vorheizen_aktiv")},
        {"alias": "Mindesttemperatur-Termine: alle 5 Minuten Vorlauf prüfen", "trigger": "time_pattern", "minutes": "/5",
         "id": "vorheizen", "enabled": Inp("mindest_aktiv")},
        {"alias": "Zieltemperatur-Termine: alle 5 Minuten Vorlauf prüfen", "trigger": "time_pattern", "minutes": "/5",
         "id": "vorheizen", "enabled": Inp("zieltermin_aktiv")},
        {"alias": "Boost-Timer gestartet, beendet, abgebrochen oder wiederhergestellt", "trigger": "state", "entity_id": Inp("boost_timer"),
         "to": None, "id": "boost_timer", "enabled": Inp("boost_aktiv")},
        {"alias": "Boost-Temperatur manuell geändert", "trigger": "state", "entity_id": Inp("boost_wert"), "to": None,
         "id": "boost_wert", "enabled": Inp("boost_aktiv")},
        {"alias": "Fensterkontakt geändert", "trigger": "state", "entity_id": Inp("fensterkontakte"), "to": None, "id": "fenster_kontakt"},
        {"alias": "Fail-safe-Ausfallfrist abgelaufen", "trigger": "event", "event_type": "timer.finished",
         "event_data": {"entity_id": Inp("fenster_timer")}, "id": "fenster_ablauf"},
        {"alias": "Fensterstatus geändert", "trigger": "state", "entity_id": Inp("fensterstatus"), "to": None, "id": "fenster_status"},
        {"alias": "Fenster lange genug offen: Heizpause beginnen", "trigger": "state", "entity_id": Inp("fensterstatus"), "to": "on",
         "for": {"seconds": Inp("fenster_verzoegerung")}, "id": "fenster_status"},
        {"alias": "Fenster lange genug zu: Heizpause beenden", "trigger": "state", "entity_id": Inp("fensterstatus"), "to": "off",
         "for": {"seconds": Inp("fenster_nachlauf")}, "id": "fenster_status"},
        {"alias": "Fenster seit 3 Minuten nach der Pausenzeit offen: Reaktion des Better Thermostat prüfen", "trigger": "state",
         "entity_id": Inp("fensterstatus"), "to": "on", "for": {"minutes": 3}, "id": "fenster_bt_pruefung"},
        {"alias": "PV-Verantwortung geändert", "trigger": "state", "entity_id": Inp("pv_flags"), "to": None, "id": "pv", "enabled": Inp("pv_aktiv")},
        {"alias": "PV-Sicherheitsfreigabe geändert", "trigger": "state", "entity_id": Inp("pv_freigabe"), "to": None, "id": "pv", "enabled": Inp("pv_aktiv")},
        {"alias": "PV-Sicherheitsfreigabe abgelaufen", "trigger": "event", "event_type": "timer.finished",
         "event_data": {"entity_id": Inp("pv_freigabe")}, "id": "pv", "enabled": Inp("pv_aktiv")},
    ]
    return t


def c(alias, tpl):
    return {"alias": alias, "condition": "template", "value_template": tpl}


# ======================================================================= Aktionen
FAILSAFE = [
    {"alias": "Reale Zustände der Fensterkontakte bestimmen", "variables": {
        "offen": "{{ fensterkontakte | select('is_state', 'on') | list | count > 0 }}",
        "defekte": "{{ fensterkontakte | reject('is_state', 'on') | reject('is_state', 'off') | list }}",
        "neuer_ausfall": ("{{ trigger.id == 'fenster_kontakt' and trigger.from_state is not none and trigger.from_state.state in ['on', 'off'] "
                          "and (trigger.to_state is none or trigger.to_state.state not in ['on', 'off']) }}")}},
    {"alias": "Gültige Kontakte oder technischen Ausfall behandeln", "choose": [{
        "alias": "Alle Fensterkontakte melden gültig offen/geschlossen",
        "conditions": [c("Keine fehlenden Kontaktzustände", "{{ defekte | count == 0 }}")],
        "sequence": [
            {"alias": "Laufende Ausfallfrist nach vollständiger Erholung abbrechen",
             "if": [c("Timer hat noch eine Frist", "{{ states(fenster_timer) in ['active', 'paused'] }}")],
             "then": [{"alias": "Ausfalltimer beenden", "action": "timer.cancel", "target": {"entity_id": "{{ fenster_timer }}"}}]},
            {"alias": "Gültigen Fensterzustand übernehmen", "action": "{{ 'input_boolean.turn_on' if offen else 'input_boolean.turn_off' }}",
             "target": {"entity_id": "{{ fensterstatus }}"}},
            {"alias": "Ausfallmeldung nach Erholung entfernen", "action": "persistent_notification.dismiss",
             "data": {"notification_id": "{{ meldung_fenster }}"}},
        ]}],
     "default": [
        {"alias": "Neue Ausfallfrist beginnen, laufende Frist nicht verlängern",
         "if": [c("Erster Ausfall, Wiederanlauf oder pausierter Timer",
                  "{{ (neuer_ausfall and not is_state(fenster_timer, 'active')) or is_state(fenster_timer, 'paused') "
                  "or (trigger.id in ['neustart', 'reload'] and not is_state(fenster_timer, 'active')) }}")],
         "then": [{"alias": "Konservative Ausfallfrist starten", "action": "timer.start", "target": {"entity_id": "{{ fenster_timer }}"},
                   "data": {"duration": "{{ '%02d:%02d:00' % ((fenster_frist | int) // 60, (fenster_frist | int) % 60) }}"}}]},
        {"alias": "Reales offenes Fenster hat immer Vorrang", "choose": [
            {"alias": "Mindestens ein Kontakt meldet real offen", "conditions": [c("Gültige Offenmeldung vorhanden", "{{ offen }}")],
             "sequence": [{"alias": "Fenster-Heizsperre einschalten", "action": "input_boolean.turn_on", "target": {"entity_id": "{{ fensterstatus }}"}}]},
            {"alias": "Keine reale Offenmeldung und Ausfallfrist beendet",
             "conditions": [c("Timer ist vollständig abgelaufen", "{{ is_state(fenster_timer, 'idle') }}")],
             "sequence": [{"alias": "Heizbetrieb bei bestätigtem technischen Ausfall freigeben", "action": "input_boolean.turn_off",
                           "target": {"entity_id": "{{ fensterstatus }}"}}]}]},
        {"alias": "Einmalige Meldung bei Fristablauf, keine Warnschleife",
         "if": [c("Ablaufereignis dieser Ausfallfrist", "{{ trigger.id == 'fenster_ablauf' }}")],
         "then": [{"alias": "Beständige Warnung mit fester ID anzeigen", "action": "persistent_notification.create", "data": {
             "notification_id": "{{ meldung_fenster }}",
             "title": "Heizung: Fensterkontakt-Ausfall – {{ raum_name }}",
             "message": ("Seit mindestens {{ fenster_frist | int }} Minuten fehlt ein gültiger Fensterzustand: {{ defekte | join(', ') }}. "
                         "{% if offen %}Ein anderer Kontakt meldet weiterhin offen; die Heizsperre bleibt aktiv.{% else %}Der normale "
                         "Heizbetrieb ist wieder freigegeben. Bitte Fenster, Batterie und Funkverbindung prüfen.{% endif %} Bei gültigen "
                         "Zuständen aller Kontakte wird diese Meldung automatisch entfernt.")}}]},
     ]},
    {"alias": "Fensterstatus für Klimaanlage und PV-Heizen (ohne die Ausnahmen) nachführen", "if": [c(
        "Helfer für Klima und PV vorhanden", "{{ fensterstatus_klima is string and fensterstatus_klima != '' }}")],
     "then": [{"alias": "Offen, wenn ein nicht ausgenommener Kontakt offen ist",
               "action": "{{ 'input_boolean.turn_on' if (fensterkontakte | reject('in', fenster_ausnahmen) | select('is_state', 'on') | list | count > 0) else 'input_boolean.turn_off' }}",
               "target": {"entity_id": "{{ fensterstatus_klima }}"}}]},
]

PLAN = r"""{%- set ns = namespace(aktiv=false, naechst=none, ende=none, vh=false, vh_ziel=0, vh_T=none, tl=[]) -%}
{%- if p_cfg is not none -%}
{%- if p_cfg.quelle == 'zeitplan' -%}
{%- if p_cfg.zeitplan is string and p_cfg.zeitplan != '' -%}
{%- set ns.aktiv = is_state(p_cfg.zeitplan, 'on') -%}
{%- set ne = state_attr(p_cfg.zeitplan, 'next_event') -%}
{%- if ne is not none and ne is not string -%}{%- if ns.aktiv -%}{%- set ns.ende = ne -%}{%- else -%}{%- set ns.naechst = ne -%}{%- set ns.vh = p_cfg.zp_vh -%}{%- set ns.vh_ziel = p_cfg.zp_vh_temp -%}{%- set ns.vh_T = ne -%}{%- endif -%}{%- endif -%}
{%- endif -%}
{%- else -%}
{%- for ph in p_cfg.phasen if ph.an and ph.tage | count > 0 -%}
{%- for off in [-1, 0, 1] -%}
{%- set beginn = today_at(ph.von) + timedelta(days=off) -%}
{%- set ende = today_at(ph.bis) + timedelta(days=off) -%}
{%- if ende <= beginn -%}{%- set ende = ende + timedelta(days=1) -%}{%- endif -%}
{%- if tage_kurz[beginn.weekday()] in ph.tage -%}
{%- if beginn <= now() < ende -%}{%- set ns.aktiv = true -%}{%- if ns.ende is none or ende > ns.ende -%}{%- set ns.ende = ende -%}{%- endif -%}{%- endif -%}
{%- if now() < beginn and (ns.naechst is none or beginn < ns.naechst) -%}{%- set ns.naechst = beginn -%}{%- set ns.vh = ph.vh -%}{%- set ns.vh_ziel = ph.vh_temp -%}{%- set zt = beginn.replace(hour=ph.vh_bis[:2] | int, minute=ph.vh_bis[3:5] | int, second=0, microsecond=0) -%}{%- set ns.vh_T = zt if zt <= beginn else beginn -%}{%- endif -%}
{%- endif -%}
{%- endfor -%}
{%- endfor -%}
{%- endif -%}
{%- for tm in p_cfg.termine if tm.an and tm.tage | count > 0 and ((tm.art == 'm' and mindest_aktiv) or (tm.art == 'z' and zieltermin_aktiv)) -%}
{%- for off in [-1, 0, 1] -%}
{%- set T = today_at(tm.zeit) + timedelta(days=off) -%}
{%- set bis = T + timedelta(minutes=(mindest_halten if tm.art == 'm' else zieltermin_halten) | float(0)) -%}
{%- if tage_kurz[T.weekday()] in tm.tage and (now() < bis or now() <= T) and (T - now()).total_seconds() / 60 <= (vorheizen_max | float) + 1 -%}
{%- set ns.tl = ns.tl + [{'T': T.isoformat(), 'temp': tm.temp | float(0), 'art': tm.art, 'bis': bis.isoformat()}] -%}
{%- endif -%}
{%- endfor -%}
{%- endfor -%}
{%- endif -%}
{{ {'aktiv': ns.aktiv, 'naechst': ns.naechst.isoformat() if ns.naechst is not none else '', 'ende': ns.ende.isoformat() if ns.ende is not none else '', 'vh': ns.vh and ns.naechst is not none, 'vh_ziel': ns.vh_ziel | float(0), 'vh_T': ns.vh_T.isoformat() if ns.vh_T is not none else '', 'termine': ns.tl} }}"""

MERKER = r"""{%- set s = states(vorheizen_merker) if vorheizen_ok else '' -%}
{%- set d = namespace(T='', soll='', t0='', b='', e='', st='', a='p') -%}
{%- for teil in (s.split(';') if s not in ['unknown', 'unavailable', ''] else []) -%}
{%- set kv = teil.split('=', 1) -%}
{%- if kv | count == 2 -%}
{%- if kv[0] == 'T' -%}{%- set d.T = kv[1] -%}{%- elif kv[0] == 's' -%}{%- set d.soll = kv[1] -%}{%- elif kv[0] == 't0' -%}{%- set d.t0 = kv[1] -%}{%- elif kv[0] == 'b' -%}{%- set d.b = kv[1] -%}{%- elif kv[0] == 'e' -%}{%- set d.e = kv[1] -%}{%- elif kv[0] == 'st' -%}{%- set d.st = kv[1] -%}{%- elif kv[0] == 'a' -%}{%- set d.a = kv[1] -%}{%- endif -%}
{%- endif -%}
{%- endfor -%}
{{ {'T': d.T, 'soll': d.soll, 't0': d.t0, 'b': d.b, 'e': d.e, 'st': d.st, 'a': d.a} }}"""

VORHEIZEN = r"""{%- set r = namespace(an=false, start=false, L=0, roh=0, rate=0, grund='', ziel=0, Tz='', T='', soll=0, art='') -%}
{%- if vorheizen_ok and p_cfg is not none -%}
{%- set hp = state_attr(bt, 'heating_power') | float(0) -%}
{%- set r.rate = (hp * 60) if 0.002 <= hp <= 0.2 else vorheizen_rate | float -%}
{%- if waermeerzeuger_reduziert -%}{%- set r.rate = r.rate * (waermeerzeuger_faktor | float) / 100 -%}{%- endif -%}
{%- set k = [[states(vorheizen_faktor) | float(1), 0.5] | max, 3] | min -%}
{%- set basis = raum_temp if raum_temp is not none else p_cfg.absenk | float -%}
{%- set phase = [{'T': plan.vh_T, 'temp': plan.vh_ziel, 'art': 'p'}] if vorheizen_aktiv and not plan.aktiv and plan.naechst != '' and plan.vh and plan.vh_T != '' else [] -%}
{%- for cd in (plan.termine + phase) | sort(attribute='T') -%}
{%- set T = as_datetime(cd.T) -%}
{%- set rest = (T - now()).total_seconds() / 60 -%}
{%- set soll = cd.temp | float -%}
{%- set dT = [soll - basis, 0] | max -%}
{%- set roh = ((dT / r.rate * 60) * k + (vorheizen_puffer | float)) if dT > (vorheizen_toleranz | float) else 0 -%}
{%- set L = [roh, vorheizen_max | float] | min -%}
{%- set g = 'halten' if now() >= T else ('läuft' if merker.T == cd.T else ('Start' if rest <= (vorheizen_max | float) and L > 0 and rest <= L else '')) -%}
{%- if g != '' -%}
{%- set r.an = true -%}
{%- if soll > r.ziel -%}{%- set r.ziel = soll -%}{%- set r.Tz = cd.T -%}{%- endif -%}
{%- if now() < T and (r.T == '' or cd.T == merker.T) -%}
{%- set r.T = cd.T -%}{%- set r.soll = soll -%}{%- set r.art = cd.art -%}{%- set r.L = L -%}{%- set r.roh = roh -%}{%- set r.grund = g -%}{%- set r.start = (g == 'Start') -%}
{%- endif -%}
{%- if r.grund == '' -%}{%- set r.grund = g -%}{%- endif -%}
{%- endif -%}
{%- endfor -%}
{%- endif -%}
{{ {'an': r.an, 'start': r.start, 'L': r.L | round(0), 'begrenzt': r.roh > (vorheizen_max | float), 'bedarf': r.roh | round(0), 'rate': r.rate | round(2), 'grund': r.grund, 'ziel': r.ziel, 'Tz': r.Tz, 'T': r.T, 'soll': r.soll, 'art': r.art} }}"""

ZIEL_TPL = r"""{%- if blockiert or haus_aus or profil == 'Aus' or (profil == 'Sommer' and not sommer_heizen) -%}{{ frostschutz | float }}
{%- elif boost_laeuft -%}{{ states(boost_wert) | float }}
{%- elif p_cfg is not none -%}{%- set regulaer = (p_cfg.soll | float) if plan.aktiv else (p_cfg.absenk | float) -%}{{ ([regulaer, vorheizen.ziel | float] | max) if vorheizen.an else regulaer }}
{%- else -%}{%- set cur = state_attr(bt, 'temperature') | float(0) -%}{{ cur if cur > frostschutz | float else ersatz_temperatur | float }}
{%- endif -%}"""

GRUND = r"""{%- if blockiert -%}Außensperre{%- elif haus_aus -%}Heizung Aus (Haus){%- elif profil == 'Aus' -%}Aus
{%- elif profil == 'Sommer' and not sommer_heizen -%}Sommer{%- elif boost_laeuft -%}Boost
{%- elif p_cfg is not none -%}{{ 'Heizphase' if plan.aktiv else ('Vorheizen' if vorheizen.an else 'Absenkung') }}{%- else -%}Profil ungültig{%- endif -%}
{{- ' · Fensterpause' if fenster_pause else '' -}}{{- ' · PV-Pause' if pv_pause else '' -}}"""

STATUS = r"""{%- set f = 'ohne' if not hat_fensterstatus else ('ausfall' if fenster_defekt > 0 else ('offen' if is_state(fensterstatus, 'on') else ('zu' if is_state(fensterstatus, 'off') else 'unbekannt'))) -%}
{%- set nx = '' -%}
{%- if plan.aktiv and plan.ende != '' -%}{%- set nx = 'A' ~ as_datetime(plan.ende).strftime('%H:%M') -%}
{%- elif plan.naechst != '' -%}{%- set nx = 'S' ~ tage_kurz[as_datetime(plan.naechst).weekday()] ~ as_datetime(plan.naechst).strftime('%H:%M') -%}{%- endif -%}
{{ ('v=1|bt=' ~ bt ~ '|t=' ~ (raum_temp if raum_temp is not none else '') ~ '|a=' ~ (state_attr(bt, 'hvac_action') or '')
~ '|p=' ~ profil ~ '|z=' ~ (ziel | float) ~ '|h=' ~ hvac_ziel ~ '|g=' ~ grund ~ '|f=' ~ f ~ '|n=' ~ fenster_defekt
~ '|nx=' ~ nx ~ '|vh=' ~ (((vorheizen.ziel | float) ~ '@' ~ as_datetime(vorheizen.Tz).strftime('%H:%M')) if vorheizen.an and vorheizen.Tz != '' else '')
~ '|m=' ~ ('test' if not produktiv else ''))[:255] }}"""


def aktionen():
    a = []
    a.append({"alias": "Raumtemperatur und Fensterlage einlesen", "variables": {
        "raum_temp": ("{%- set s = states(raumfuehler) if raumfuehler is string and raumfuehler != '' else '' -%}"
                      "{%- set t = s if is_number(s) else state_attr(bt, 'current_temperature') -%}"
                      "{{ t | float if is_number(t) else none }}"),
        "fenster_defekt": "{{ (fensterkontakte | reject('is_state', 'on') | reject('is_state', 'off') | list | count) if fenster_modus == 'eigen' else 0 }}",
    }})
    a.append({"alias": "Fenster-Fail-safe ausführen (eigene Kontakte)", "if": [c(
        "Eigene Fensterüberwachung und Fenster-, Start- oder Reload-Ereignis",
        "{{ fenster_eigen and trigger.id in ['fenster_kontakt', 'fenster_ablauf', 'neustart', 'reload'] }}")], "then": FAILSAFE})
    a.append({"alias": "Better Thermostat reagiert nicht auf den Fensterstatus: einmalig melden", "if": [c(
        "BT soll selbst reagieren, Fenster offen, BT meldet aber kein offenes Fenster",
        "{{ trigger.id == 'fenster_bt_pruefung' and fenster_reaktion == 'bt' and hat_fensterstatus and is_state(fensterstatus, 'on') "
        "and state_attr(bt, 'window_open') != true }}")], "then": [{
        "alias": "Hinweis auf fehlenden Fenstersensor im Better Thermostat", "action": "persistent_notification.create", "data": {
            "notification_id": "{{ 'hz_bt_fenster_' ~ raum_schluessel }}",
            "title": "Heizung {{ raum_name }}: Better Thermostat reagiert nicht auf offenes Fenster",
            "message": ("Der Fensterstatus {{ fensterstatus }} ist seit mehreren Minuten „offen“, das Better Thermostat {{ bt }} meldet aber "
                        "kein offenes Fenster. Entweder in den Better-Thermostat-Optionen den Fensterstatus als Fenstersensor eintragen "
                        "oder in dieser Automation „Diese Automation pausiert das Better Thermostat“ wählen.")}}]})
    a.append({"alias": "Boostwert-Änderung auswerten", "if": [c(
        "Echte numerische Änderung des Boostwerts (keine Wiederherstellung)",
        "{{ boost_ok and trigger.id == 'boost_wert' and trigger.from_state is not none and trigger.to_state is not none "
        "and is_number(trigger.from_state.state) and is_number(trigger.to_state.state) and trigger.from_state.state != trigger.to_state.state }}")],
        "then": [{"alias": "Boost starten oder beenden", "choose": [{
            "alias": "Boost über Frostschutz in Komfort, Übergang oder Urlaub",
            "conditions": [c("Profil und Boostwert erlauben Boost",
                             "{{ states(boost_wert) | float(frostschutz) > frostschutz | float and states(profilhelfer) in ['Komfort', 'Übergang', 'Urlaub'] }}"),
                           c("Normalbetrieb", "{{ produktiv }}")],
            "sequence": [{"alias": "Boost-Timer mit seiner Dauer starten", "action": "timer.start", "target": {"entity_id": "{{ boost_timer }}"}}]},
            {"alias": "Boost beenden",
             "conditions": [c("Normalbetrieb", "{{ produktiv }}")],
             "sequence": [{"alias": "Boost-Timer abbrechen", "action": "timer.cancel", "target": {"entity_id": "{{ boost_timer }}"}}]}]}]})
    a.append({"alias": "Bewusster Profilwechsel: Boost beenden und globalen Aus-Schalter aufheben", "if": [c(
        "Gültiges Profil wurde tatsächlich gewechselt",
        "{{ trigger.id == 'profil' and trigger.from_state is not none and trigger.to_state is not none "
        "and trigger.from_state.state in gueltige_profile and trigger.to_state.state in gueltige_profile "
        "and trigger.from_state.state != trigger.to_state.state and produktiv }}")], "then": [
        {"alias": "Laufenden Boost dieses Raums beenden", "if": [c("Boost läuft oder ist pausiert",
                                                                    "{{ boost_ok and states(boost_timer) in ['active', 'paused'] }}")],
         "then": [{"alias": "Boost-Timer abbrechen", "action": "timer.cancel", "target": {"entity_id": "{{ boost_timer }}"}}]},
        {"alias": "Globalen Schalter „Heizung Aus“ bei Wahl eines Heizprofils ausschalten", "if": [c(
            "Heizprofil gewählt und globaler Schalter an", "{{ hat_haus_aus and trigger.to_state.state != 'Aus' and is_state(haus_heizung_aus, 'on') }}")],
         "then": [{"alias": "Globalen Schalter ausschalten", "action": "input_boolean.turn_off", "target": {"entity_id": "{{ haus_heizung_aus }}"}}]}]})
    a.append({"alias": "Profil, Zeitplan, Vorheizen und Sperren auswerten", "variables": {
        "profil": "{{ states(profilhelfer) }}",
        "p_cfg": ("{%- set m = {'Komfort': cfg_komfort, 'Übergang': cfg_uebergang, 'Urlaub': cfg_urlaub, 'Sommer': cfg_sommer} -%}"
                  "{{ m[profil] if profil in m and (profil != 'Sommer' or sommer_heizen) else none }}"),
        "haus_aus": "{{ hat_haus_aus and is_state(haus_heizung_aus, 'on') }}",
        "blockiert": "{{ aussensperre_aktiv and states(aussen) | float(0) > aussensperre_grenze | float }}",
        "boost_laeuft": ("{{ boost_ok and is_state(boost_timer, 'active') and is_number(states(boost_wert)) "
                         "and states(boost_wert) | float(0) > frostschutz | float }}"),
        "waermeerzeuger_reduziert": ("{{ waermeerzeuger is string and waermeerzeuger != '' and states(waermeerzeuger) not in ['unknown', 'unavailable'] "
                                     "and states(waermeerzeuger) not in waermeerzeuger_voll }}"),
        "plan": PLAN,
        "merker": MERKER,
    }})
    a.append({"alias": "Vorlaufzeit für das vorausschauende Vorheizen bestimmen (nur gewählte Heizphasen)", "variables": {"vorheizen": VORHEIZEN}})
    a.append({"alias": "Fensterpause und PV-Pause bestimmen", "variables": {
        "fenster_pause": ("{%- if fenster_reaktion == 'blueprint' and hat_fensterstatus -%}"
                          "{%- set alter = (now() - states[fensterstatus].last_changed).total_seconds() if states[fensterstatus] is not none else 0 -%}"
                          "{{ (is_state(fensterstatus, 'on') and (alter >= fenster_verzoegerung | float or trigger.id in ['neustart', 'reload'] or is_state(bt, 'off'))) or "
                          "(is_state(fensterstatus, 'off') and alter < fenster_nachlauf | float and is_state(bt, 'off') "
                          "and (not hat_status or 'Fensterpause' in states(status_text))) }}"
                          "{%- else -%}{{ false }}{%- endif -%}"),
        "pv_pause": "{{ pv_ok and pv_flags | select('is_state', 'on') | list | count > 0 and is_state(pv_freigabe, 'active') }}",
    }})
    a.append({"alias": "Solltemperatur, Heizmodus und Status bestimmen", "variables": {
        "ziel": ZIEL_TPL,
        "hvac_ziel": "{{ 'off' if pv_pause or fenster_pause else 'heat' }}",
        "grund": GRUND,
    }})
    a.append({"alias": "Statustext für die Dashboard-Karte bilden", "variables": {"status_neu": STATUS}})
    # --- Vorheizmerker pflegen
    a.append({"alias": "Vorausschauendes Vorheizen protokollieren und lernen", "if": [c("Vorheizfunktion vollständig eingerichtet", "{{ vorheizen_ok }}")],
              "then": [{"alias": "Vorheizvorgang starten, verfolgen oder bewerten", "choose": [
                  {"alias": "Neuer Vorheizvorgang beginnt",
                   "conditions": [c("Vorlaufzeit erreicht und noch kein Merker", "{{ vorheizen.start }}")],
                   "sequence": [
                       {"alias": "Vorheizvorgang merken", "action": "input_text.set_value", "target": {"entity_id": "{{ vorheizen_merker }}"},
                        "data": {"value": ("{{ ('T=' ~ vorheizen.T ~ ';s=' ~ (vorheizen.soll | float) ~ ';t0=' ~ (raum_temp if raum_temp is not none else '') "
                                           "~ ';b=' ~ now().isoformat() ~ ';e=;st=' ~ ('w' if waermeerzeuger_reduziert else '') ~ ';a=' ~ vorheizen.art)[:255] }}")}},
                       {"alias": "Start im Bericht festhalten", "if": [c("Berichtshelfer vorhanden", "{{ vorheizen_bericht is string and vorheizen_bericht != '' }}")],
                        "then": [{"alias": "Bericht schreiben", "action": "input_text.set_value", "target": {"entity_id": "{{ vorheizen_bericht }}"},
                                  "data": {"value": ("{{ ('Vorheizen seit ' ~ now().strftime('%H:%M') ~ ' für ' ~ as_datetime(vorheizen.T).strftime('%H:%M') "
                                                     "~ ' (' ~ ('Zieltemperatur ' if vorheizen.art == 'z' else 'Mindesttemperatur ') ~ (vorheizen.soll | float) ~ ' °C, Vorlauf ' ~ (vorheizen.L | int) ~ ' min, Rate ' ~ vorheizen.rate ~ ' K/h'"
                                                     "~ (', Wärmeerzeuger reduziert' if waermeerzeuger_reduziert else '') ~ ')'"
                                                     "~ (' – voraussichtlich NICHT erreichbar, benötigt ' ~ (vorheizen.bedarf | int) ~ ' min' if vorheizen.begrenzt else ''))[:255] }}")}}]}]},
                  {"alias": "Laufender Vorgang: Erreichen der Solltemperatur vor dem Termin festhalten",
                   "conditions": [c("Merker aktiv, Termin noch nicht erreicht, Raum warm genug, noch nicht vermerkt",
                                    "{{ merker.T != '' and merker.e == '' and now() < as_datetime(merker.T) and raum_temp is not none "
                                    "and raum_temp >= (merker.soll | float(99)) - (vorheizen_toleranz | float) }}")],
                   "sequence": [{"alias": "Zeitpunkt des Erreichens vermerken", "action": "input_text.set_value", "target": {"entity_id": "{{ vorheizen_merker }}"},
                                 "data": {"value": "{{ ('T=' ~ merker.T ~ ';s=' ~ merker.soll ~ ';t0=' ~ merker.t0 ~ ';b=' ~ merker.b ~ ';e=' ~ now().isoformat() ~ ';st=' ~ merker.st ~ ';a=' ~ merker.a)[:255] }}"}}]},
                  {"alias": "Laufender Vorgang: Störungen (Fenster, Boost, PV, reduzierter Wärmeerzeuger) vermerken",
                   "conditions": [c("Merker aktiv und neue Störung",
                                    "{{ merker.T != '' and ((fenster_pause or (hat_fensterstatus and is_state(fensterstatus, 'on'))) and 'f' not in merker.st "
                                    "or (waermeerzeuger_reduziert and 'w' not in merker.st) or (pv_pause and 'p' not in merker.st)) }}")],
                   "sequence": [{"alias": "Störung im Merker ergänzen", "action": "input_text.set_value", "target": {"entity_id": "{{ vorheizen_merker }}"},
                                 "data": {"value": ("{{ ('T=' ~ merker.T ~ ';s=' ~ merker.soll ~ ';t0=' ~ merker.t0 ~ ';b=' ~ merker.b ~ ';e=' ~ merker.e ~ ';st=' ~ merker.st "
                                                    "~ ('f' if (fenster_pause or (hat_fensterstatus and is_state(fensterstatus, 'on'))) and 'f' not in merker.st else '') "
                                                    "~ ('w' if waermeerzeuger_reduziert and 'w' not in merker.st else '') ~ ('p' if pv_pause and 'p' not in merker.st else '') ~ ';a=' ~ merker.a)[:255] }}")}}]},
                  {"alias": "Termin erreicht oder Vorgang hinfällig: ehrlich bewerten und Faktor anpassen",
                   "conditions": [c("Merker aktiv und Termin vorbei oder Profil/Plan passt nicht mehr",
                                    "{{ merker.T != '' and (now() >= as_datetime(merker.T) or vorheizen.T != merker.T) }}")],
                   "sequence": [
                       {"alias": "Ergebnis berechnen", "variables": {
                           "termin_vorbei": "{{ now() >= as_datetime(merker.T) }}",
                           "erreicht": "{{ merker.e != '' or (raum_temp is not none and raum_temp >= (merker.soll | float(99)) - (vorheizen_toleranz | float)) }}",
                           "minuten_frueh": "{{ ((as_datetime(merker.T) - as_datetime(merker.e)).total_seconds() / 60) | round(0) if merker.e != '' else 0 }}",
                           "k_alt": "{{ [[states(vorheizen_faktor) | float(1), 0.5] | max, 3] | min }}",
                           "lernbar": "{{ vorheizen_lernen and merker.st == '' }}",
                           "k_neu": ("{%- set k = [[states(vorheizen_faktor) | float(1), 0.5] | max, 3] | min -%}"
                                     "{%- set m = ((as_datetime(merker.T) - as_datetime(merker.e)).total_seconds() / 60) if merker.e != '' else 0 -%}"
                                     "{%- if not (now() >= as_datetime(merker.T)) or not (vorheizen_lernen and merker.st == '') -%}{{ k }}"
                                     "{%- elif merker.e == '' and not (raum_temp is not none and raum_temp >= (merker.soll | float(99)) - (vorheizen_toleranz | float)) -%}{{ [k * 1.2, 3] | min | round(2) }}"
                                     "{%- elif m > (vorheizen_puffer | float) + 15 -%}{{ [k * 0.9, 0.5] | max | round(2) }}"
                                     "{%- else -%}{{ k }}{%- endif -%}")}},
                       {"alias": "Korrekturfaktor speichern", "if": [c("Faktor hat sich geändert", "{{ k_neu | float != k_alt | float }}")],
                        "then": [{"alias": "Faktor setzen", "action": "input_number.set_value", "target": {"entity_id": "{{ vorheizen_faktor }}"},
                                  "data": {"value": "{{ k_neu }}"}}]},
                       {"alias": "Ehrlichen Bericht schreiben", "if": [c("Berichtshelfer vorhanden", "{{ vorheizen_bericht is string and vorheizen_bericht != '' }}")],
                        "then": [{"alias": "Ergebnis eintragen", "action": "input_text.set_value", "target": {"entity_id": "{{ vorheizen_bericht }}"},
                                  "data": {"value": ("{%- set zeit = as_datetime(merker.T).strftime('%H:%M') -%}"
                                                     "{%- set stoer = ((' Fenster' if 'f' in merker.st else '') ~ (' Wärmeerzeuger-reduziert' if 'w' in merker.st else '') ~ (' PV' if 'p' in merker.st else '')) -%}"
                                                     "{%- set wort = 'Zieltemperatur' if merker.a == 'z' else 'Mindesttemperatur' -%}"
                                                     "{%- if not termin_vorbei -%}{%- set kern = 'Vorheizen für ' ~ zeit ~ ' abgebrochen (Profil/Plan geändert)' -%}"
                                                     "{%- elif erreicht -%}{%- set kern = '✔ ' ~ wort ~ ' ' ~ merker.soll ~ ' °C um ' ~ zeit ~ ' erreicht' ~ ((' (' ~ (minuten_frueh | int) ~ ' min früher)') if merker.e != '' else '') -%}"
                                                     "{%- else -%}{%- set kern = '✘ ' ~ wort ~ ' ' ~ merker.soll ~ ' °C um ' ~ zeit ~ ' NICHT erreicht (Ist ' ~ (raum_temp if raum_temp is not none else '?') ~ ' °C)' -%}{%- endif -%}"
                                                     "{%- set zusatz = ((' · Störung:' ~ stoer ~ ' – nicht gelernt') if stoer != '' else '') ~ ((' · Faktor ' ~ k_alt ~ '→' ~ k_neu) if k_neu | float != k_alt | float else '') -%}"
                                                     "{{ (kern ~ zusatz)[:255] }}")}}]},
                       {"alias": "Merker leeren", "action": "input_text.set_value", "target": {"entity_id": "{{ vorheizen_merker }}"}, "data": {"value": ""}}]},
              ]}]})
    a.append({"alias": "Statustext für die Dashboard-Karte aktualisieren", "if": [c(
        "Statushelfer vorhanden und Inhalt geändert", "{{ hat_status and states(status_text) != status_neu }}")],
        "then": [{"alias": "Status schreiben", "action": "input_text.set_value", "target": {"entity_id": "{{ status_text }}"},
                  "data": {"value": "{{ status_neu }}"}}]})
    a.append({"alias": "Ohne verfügbares Better Thermostat nichts senden (BT-Rückkehr rechnet neu)", "condition": "template",
              "value_template": "{{ states(bt) not in ['unknown', 'unavailable'] }}"})
    a.append({"alias": "Im Testbetrieb nichts an das Better Thermostat senden", "condition": "template", "value_template": "{{ produktiv }}"})
    a.append({"alias": "Nur geänderten Sollwert oder notwendigen Heizmodus senden", "condition": "template",
              "value_template": "{{ states(bt) != hvac_ziel or state_attr(bt, 'temperature') | float(-999) != ziel | float }}"})
    a.append({"alias": "Sollwert und Heizmodus ausschließlich an das Better Thermostat übergeben", "action": "climate.set_temperature",
              "target": {"entity_id": "{{ bt }}"}, "data": {"temperature": "{{ ziel | float }}", "hvac_mode": "{{ hvac_ziel }}"}})
    return a


def blueprint():
    return {
        "blueprint": {
            "name": "Universelle Raumheizungssteuerung",
            "description": "Paketversion 1.6.0 · " + (
                "Heizungssteuerung für einen Raum mit Better Thermostat: Heizprofile Komfort, Übergang, Urlaub, Sommer und Aus mit eigenen "
                "Soll- und Absenktemperaturen und drei Tagesprogrammen je Profil (Montag bis Freitag, Samstag, Sonntag) mit je bis zu drei Heizphasen. Standardverhalten: Die "
                "Solltemperatur wird genau zum Beginn einer Heizphase gesendet, die Absenktemperatur zur Absenkzeit; Better Thermostat "
                "regelt die Heizkörper. Optional: vorausschauendes Vorheizen je Heizphase auf eine eigene Mindesttemperatur, Fensterüberwachung mit 10-Minuten-Fail-safe, Boost, Zusammenarbeit mit "
                "PV-Überschussheizen und Klimaautomatik.\n\nPro Raum wird eine eigene Automation aus dieser Blueprint erstellt. Die benötigten "
                "Helfer und die Dashboard-Karte legt der Einrichtungsassistent an (siehe Dokumentation).\n\n"
                "Vorrang (von oben nach unten): Better Thermostat nicht verfügbar → Fenster (Pause) → PV-Heizkörperpause → Außensperre → "
                "Heizung Aus / Profil Aus / Sommer → Boost → Heizphase bzw. Vorheizen → Absenkung."),
            "domain": "automation",
            "author": "HA-Heizung-Universal",
            "homeassistant": {"min_version": "2026.11.0"},
            "input": inputs(),
        },
        "mode": "queued",
        "max": 25,
        "max_exceeded": "warning",
        "trace": {"stored_traces": 20},
        "variables": variablen(),
        "triggers": trigger(),
        "conditions": [],
        "actions": aktionen(),
    }


if __name__ == "__main__":
    ZIEL.parent.mkdir(parents=True, exist_ok=True)
    kopf = ("# Universelle Raumheizungssteuerung – Blueprint 1 von 3\n"
            "# Erzeugt mit tools/build_raumheizung.py – Änderungen bitte dort vornehmen.\n")
    ZIEL.write_text(kopf + dump(blueprint()), encoding="utf-8")
    print("geschrieben:", ZIEL.relative_to(BASIS))
