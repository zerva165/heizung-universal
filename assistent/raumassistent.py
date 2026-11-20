#!/usr/bin/env python3
"""Einrichtungsassistent „Universelle Raumheizungssteuerung“.

Führt Schritt für Schritt durch die Einrichtung eines Raums und legt – nach Zusammenfassung und ausdrücklicher
Bestätigung – genau die Komponenten an, die der Raum braucht:
  * Blueprints (nur falls noch nicht installiert oder veraltet – mit Rückfrage)
  * Raum-Helfer (Heizprofil, Status, Fail-safe, Boost, Vorheizen, Klima, PV – je nach Auswahl)
  * die Automation(en) aus den Blueprints (Raumheizung, optional Klimaautomatik und PV-Überschussheizen)
  * die Dashboard-Karte an der gewählten Stelle (vorher wird das Dashboard gesichert)
Bestehende Automationen, Skripte, Helfer und Geräte werden nie verändert. Jeder Lauf schreibt eine Rückbau-Datei.

Aufruf:
  python3 assistent/raumassistent.py                     Interaktiv (fragt URL und Token)
  python3 assistent/raumassistent.py --trockenlauf       Nur Plan und Dateien erzeugen, nichts in HA schreiben
  python3 assistent/raumassistent.py --antworten a.json  Antworten aus Datei (für Wiederholung/Tests)
  python3 assistent/raumassistent.py --offline s.json    Entitätsliste aus Datei statt aus HA (Tests, impliziert Trockenlauf)
  python3 assistent/raumassistent.py --rueckbau r.json   Von einem früheren Lauf angelegte Komponenten wieder entfernen
Umgebungsvariablen: HA_URL, HA_TOKEN (langlebiges Zugriffstoken aus dem HA-Profil).
"""
import argparse
import datetime as dt
import getpass
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

HIER = Path(__file__).resolve().parent
if __package__:  # als Teil der Home-Assistant-Integration
    from .ha_verbindung import HAVerbindung, HAFehler
    from .karte import raumkarte, DESIGNS
    from . import altsteuerung as al
    dump = None
    PROJEKT = HIER
    BP_ORDNER = HIER / "blueprints"
else:  # als Kommandozeilenwerkzeug im Projektordner
    sys.path.insert(0, str(HIER))
    sys.path.insert(0, str(HIER.parent / "tools"))
    from ha_verbindung import HAVerbindung, HAFehler  # noqa: E402
    from karte import raumkarte, DESIGNS  # noqa: E402
    import altsteuerung as al  # noqa: E402
    from yamlgen import dump  # noqa: E402
    PROJEKT = HIER.parent
    BP_ORDNER = PROJEKT / "blueprints" / "automation" / "ha_heizung_universal"
PAKETVERSION = "1.6.0"
PROFILNAMEN = {"komfort": "Komfort", "uebergang": "Übergang", "urlaub": "Urlaub", "sommer": "Sommer"}
TAGESPROGRAMME = [("wt", "Montag bis Freitag", ["mo", "di", "mi", "do", "fr"]), ("sa", "Samstag", ["sa"]), ("so", "Sonntag", ["so"])]
STANDARD_PHASEN = {
    "komfort": {"wt": [("06:00", "08:00"), ("16:00", "22:00")], "sa": [("08:00", "22:00")], "so": [("08:00", "22:00")]},
    "uebergang": {"wt": [("07:00", "09:00"), ("16:00", "21:00")], "sa": [("09:00", "21:00")], "so": [("09:00", "21:00")]},
    "urlaub": {"wt": [("09:00", "19:00")], "sa": [("09:00", "19:00")], "so": [("09:00", "19:00")]},
    "sommer": {"wt": [], "sa": [], "so": []},
}
WOCHENTAGE = {"mo": "monday", "di": "tuesday", "mi": "wednesday", "do": "thursday", "fr": "friday", "sa": "saturday", "so": "sunday"}


def zeitplan_bloecke(phasen):
    """Heizphasen (Tage, von, bis) → Blöcke für einen Zeitplan-Helfer (schedule). Über Mitternacht wird geteilt, Überlappungen verschmolzen."""
    tage = {t: [] for t in WOCHENTAGE}
    kurz = list(WOCHENTAGE)
    for ph in phasen:
        von, bis = ph["von"][:5] + ":00", ph["bis"][:5] + ":00"
        for t in ph["tage"]:
            if bis > von:
                tage[t].append([von, bis])
            else:
                tage[t].append([von, "24:00:00"])
                if bis != "00:00:00":
                    tage[kurz[(kurz.index(t) + 1) % 7]].append(["00:00:00", bis])
    out = {}
    for t, bl in tage.items():
        zus = []
        for von, bis in sorted(bl):
            if zus and von <= zus[-1][1]:
                zus[-1][1] = max(zus[-1][1], bis)
            else:
                zus.append([von, bis])
        out[WOCHENTAGE[t]] = [{"from": v, "to": b} for v, b in zus]
    return out
BP = {"raumheizung": "ha_heizung_universal/universelle_raumheizungssteuerung.yaml",
      "klima": "ha_heizung_universal/klimaautomatik.yaml",
      "pv": "ha_heizung_universal/pv_ueberschussheizen.yaml",
      "klima_schalter": "ha_heizung_universal/klimaautomatik_steckdose.yaml"}
TAGE = ["mo", "di", "mi", "do", "fr", "sa", "so"]
TAGNAMEN = {"mo": "Mo", "di": "Di", "mi": "Mi", "do": "Do", "fr": "Fr", "sa": "Sa", "so": "So"}


# ====================================================================== Hilfen
def slug(text):
    """Nachbildung von Home Assistants slugify (ä→a, ß→ss, Sonderzeichen→_)."""
    t = text.replace("ß", "ss")
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-zA-Z0-9]+", "_", t).strip("_").lower()
    return re.sub(r"_+", "_", t)


class Dialog:
    """Fragen im Terminal oder aus einer Antwortdatei."""

    NEU = ("zeitquelle", "mindest", "zieltermin", "termin1", "luefter", "vorheizen_max", "waermeerzeuger")

    def __init__(self, antworten=None):
        self.vorgabe = antworten or {}
        self.protokoll = {}

    def _hole(self, schluessel, frage, standard):
        if schluessel in self.vorgabe:
            wert = self.vorgabe[schluessel]
            print(f"  {frage}: {wert}  (aus Antwortdatei)")
        elif self.vorgabe and (schluessel in self.NEU or re.search(r"_(wt|sa|so)[123]_", schluessel)):
            wert = standard  # ältere Antwortdateien kennen die neueren Fragen nicht → Standardwert
        else:
            zusatz = f" [{standard}]" if standard not in (None, "") else ""
            eingabe = input(f"  {frage}{zusatz}: ").strip()
            wert = eingabe if eingabe else standard
        self.protokoll[schluessel] = wert
        return wert

    def text(self, k, frage, standard=""):
        return str(self._hole(k, frage, standard) or "")

    def zahl(self, k, frage, standard, mn=None, mx=None):
        while True:
            w = self._hole(k, frage, standard)
            try:
                z = float(str(w).replace(",", "."))
                if (mn is None or z >= mn) and (mx is None or z <= mx):
                    return int(z) if z == int(z) else z
            except ValueError:
                pass
            print(f"    Bitte eine Zahl{f' von {mn} bis {mx}' if mn is not None else ''} eingeben.")
            self.vorgabe.pop(k, None)

    def ja(self, k, frage, standard=True):
        w = self._hole(k, frage + " (j/n)", "j" if standard else "n")
        return str(w).lower() in ("j", "ja", "y", "yes", "true", "1")

    def zeit(self, k, frage, standard):
        while True:
            w = str(self._hole(k, frage, standard))
            m = re.fullmatch(r"(\d{1,2})[:.](\d{2})", w.strip())
            if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
                return f"{int(m.group(1)):02d}:{m.group(2)}:00"
            print("    Bitte Uhrzeit als HH:MM eingeben.")
            self.vorgabe.pop(k, None)

    def tage(self, k, frage, standard):
        while True:
            w = str(self._hole(k, frage, standard)).lower().replace(" ", "")
            if w in ("werktage", "mo-fr"):
                return TAGE[:5]
            if w in ("wochenende", "sa-so"):
                return TAGE[5:]
            if w in ("alle", "mo-so", "täglich", "taeglich"):
                return TAGE[:]
            teile = [t for t in re.split(r"[,;]", w) if t]
            if teile and all(t in TAGE for t in teile):
                return teile
            print("    Erlaubt: werktage, wochenende, alle oder Liste wie mo,mi,fr")
            self.vorgabe.pop(k, None)

    def auswahl(self, k, frage, eintraege, optional=False, mehrfach=False, vorschlag=None):
        """eintraege: Liste (entity_id, Anzeigename). Rückgabe: entity_id | Liste | ''."""
        if k in self.vorgabe:
            w = self.vorgabe[k]
            print(f"  {frage}: {w}  (aus Antwortdatei)")
            self.protokoll[k] = w
            return w
        filt = ""
        while True:
            treffer = [e for e in eintraege if filt in (e[0] + " " + e[1]).lower()]
            print(f"\n  {frage}" + (" (Mehrfachauswahl: Nummern mit Komma)" if mehrfach else ""))
            for i, (eid, name) in enumerate(treffer[:40], 1):
                stern = " ← Vorschlag" if vorschlag and (eid == vorschlag or (isinstance(vorschlag, list) and eid in vorschlag)) else ""
                print(f"   {i:2d}) {name}  [{eid}]{stern}")
            if len(treffer) > 40:
                print(f"   … {len(treffer) - 40} weitere – Suchtext eingeben, um einzugrenzen")
            hinweis = "Nummer(n), Suchtext" + (", 0 = keine" if optional else "") + (", Enter = Vorschlag" if vorschlag else "")
            e = input(f"  Auswahl ({hinweis}): ").strip()
            if not e and vorschlag:
                self.protokoll[k] = vorschlag
                return vorschlag
            if e == "0" and optional:
                self.protokoll[k] = [] if mehrfach else ""
                return self.protokoll[k]
            if re.fullmatch(r"[\d, ]+", e or "x"):
                nr = [int(x) for x in re.split(r"[ ,]+", e) if x]
                if all(1 <= n <= min(40, len(treffer)) for n in nr) and nr:
                    w = [treffer[n - 1][0] for n in nr]
                    w = w if mehrfach else w[0]
                    self.protokoll[k] = w
                    return w
            filt = e.lower()


# ====================================================================== Entitätsbestand
class AltPVLaeuft(HAFehler):
    """Erwartete Sperre: das alte PV-Heizen des Raums läuft gerade – es wird nichts verändert."""


class Bestand:
    def __init__(self, zustaende, register):
        self.z = {s["entity_id"]: s for s in zustaende}
        self.r = {e["entity_id"]: e for e in register}

    def name(self, eid):
        s = self.z.get(eid)
        return (s or {}).get("attributes", {}).get("friendly_name", eid)

    def liste(self, domain, device_class=None, platform=None):
        out = []
        for eid, s in sorted(self.z.items()):
            if not eid.startswith(domain + "."):
                continue
            if device_class and s.get("attributes", {}).get("device_class") not in (device_class if isinstance(device_class, list) else [device_class]):
                continue
            if platform and self.r.get(eid, {}).get("platform") != platform:
                continue
            out.append((eid, self.name(eid)))
        return out

    def existiert(self, eid):
        return eid in self.z or eid in self.r


# ====================================================================== Fragenkatalog
def frage_profil(d, vorheizen, key, name, soll, absenk, std_phasen=None):
    """Je Profil drei Tagesprogramme (Montag bis Freitag, Samstag, Sonntag) mit je bis zu drei Heizphasen."""
    print(f"\n— Profil {name} —")
    p = {"soll": d.zahl(f"{key}_soll", f"{name}: Solltemperatur °C", soll, 5, 28),
         "absenk": d.zahl(f"{key}_absenk", f"{name}: Absenktemperatur °C", absenk, 5, 25),
         "phasen": []}
    for tag, tagname, tage in TAGESPROGRAMME:
        std = STANDARD_PHASEN[key][tag]
        print(f"   {tagname}:")
        for i in (1, 2, 3):
            pre = f"{key}_{tag}{i}"
            von, bis = std[i - 1] if i <= len(std) else ("06:00", "08:00")
            if not d.ja(f"{pre}_aktiv", f"    Heizphase {i} verwenden?", i <= len(std)):
                continue
            ph = {"gruppe": tag, "nr": i, "tage": list(tage),
                  "von": d.zeit(f"{pre}_von", "      Beginn – Solltemperatur wird gesendet (HH:MM)", von),
                  "bis": d.zeit(f"{pre}_bis", "      Ende – Absenkung ab (HH:MM)", bis), "vh": False}
            if vorheizen:
                ph["vh"] = d.ja(f"{pre}_vh", "      Vor dieser Heizphase vorausschauend vorheizen?", False)
                if ph["vh"]:
                    ph["vh_temp"] = d.zahl(f"{pre}_vh_temp", "      Gewünschte Mindesttemperatur °C", max(p["soll"] - 1, 5), 5, 28)
                    ph["vh_bis"] = d.zeit(f"{pre}_vh_bis", "      Mindesttemperatur erreicht bis (HH:MM, Standard = Beginn)", ph["von"][:5])
            p["phasen"].append(ph)
    return p


def fragen(d, b):
    a = {}
    print("\n=== 1. Raum ===")
    a["raum_name"] = d.text("raum_name", "Raumname", "Büro")
    a["key"] = slug(d.text("raum_schluessel", "Raumkennung (für Helfer-IDs)", slug(a["raum_name"].replace("ü", "ue").replace("ö", "oe").replace("ä", "ae"))))
    print("\n=== 2. Geräte ===")
    a["bt"] = d.auswahl("better_thermostat", "Better Thermostat des Raums", b.liste("climate", platform="better_thermostat"))
    bat = b.z.get(a["bt"], {}).get("attributes", {}).get("batteries", "{}")
    try:
        fuehler_vorschlag = next((k for k in json.loads(bat) if k.startswith("sensor.") and "temperatur" in k), None)
    except ValueError:
        fuehler_vorschlag = None
    a["raumfuehler"] = d.auswahl("raumfuehler", "Externer Raumtemperaturfühler (0 = Wert des Better Thermostat)",
                                 b.liste("sensor", "temperature"), optional=True, vorschlag=fuehler_vorschlag)
    aussen_vorschlag = next((e for e, _ in b.liste("sensor", "temperature") if "aussen" in e), None)
    a["aussen"] = d.auswahl("aussentemperatur", "Außentemperatur", b.liste("sensor", "temperature"), vorschlag=aussen_vorschlag)

    print("\n=== 3. Fenster ===")
    modus = d.text("fenster_modus", "Fensterüberwachung: ohne / eigen / extern", "eigen")
    a["fenster_modus"] = modus if modus in ("ohne", "eigen", "extern") else "ohne"
    a["fensterkontakte"], a["fensterstatus_extern"] = [], ""
    if a["fenster_modus"] == "eigen":
        a["fensterkontakte"] = d.auswahl("fensterkontakte", "Fensterkontakte, die die Heizung pausieren",
                                         b.liste("binary_sensor", ["window", "door", "opening"]), mehrfach=True)
    elif a["fenster_modus"] == "extern":
        a["fensterstatus_extern"] = d.auswahl("fensterstatus_extern", "Fensterstatus-Helfer des anderen Raums", b.liste("input_boolean"))
    if a["fenster_modus"] != "ohne":
        r = d.text("fenster_reaktion", "Reaktion: blueprint (Automation pausiert BT) / bt (BT-Fenstersensor bereits eingerichtet)", "blueprint")
        a["fenster_reaktion"] = r if r in ("blueprint", "bt") else "blueprint"
    else:
        a["fenster_reaktion"] = "blueprint"

    print("\n=== 4. Heizprofile ===")
    print("  Standard: Die Solltemperatur wird genau zum Beginn einer Heizphase gesendet (kein Vorheizen).")
    a["vorheizen"] = d.ja("vorheizen", "Zusatzfunktion „Vorausschauendes Vorheizen“ für diesen Raum verwenden?", False)
    a["profile"] = {
        "komfort": frage_profil(d, a["vorheizen"], "komfort", "Komfort", 22, 16, [("werktage", "06:00", "08:00"), ("werktage", "16:00", "22:00"), ("wochenende", "08:00", "22:00")]),
        "uebergang": frage_profil(d, a["vorheizen"], "uebergang", "Übergang", 21, 16, [("werktage", "07:00", "09:00"), ("werktage", "16:00", "21:00"), ("wochenende", "09:00", "21:00")]),
        "urlaub": frage_profil(d, a["vorheizen"], "urlaub", "Urlaub", 17, 16, [("alle", "09:00", "19:00")]),
    }
    a["sommer_heizen"] = d.ja("sommer_heizen", "Im Profil Sommer heizen? (Standard: nein = Frostschutz)", False)
    a["profile"]["sommer"] = frage_profil(d, a["vorheizen"], "sommer", "Sommer", 19, 16, []) if a["sommer_heizen"] else {"soll": 19, "absenk": 16, "phasen": []}
    a["aktive_profile"] = ["komfort", "uebergang", "urlaub"]
    zq = d.text("zeitquelle", "Heizzeiten: phasen (in der Blueprint) / zeitplan (Zeitplan-Helfer je Profil anlegen)", "phasen")
    a["zeitquelle"] = zq if zq in ("phasen", "zeitplan") else "phasen"
    a["mindest"] = d.ja("mindest", "Zusatzfunktion „Mindesttemperatur zu festen Uhrzeiten“ verwenden?", False)
    a["zieltermin"] = d.ja("zieltermin", "Zusatzfunktion „Zieltemperatur zu festen Uhrzeiten“ verwenden?", False)
    a["termine"] = []
    while (a["mindest"] or a["zieltermin"]) and d.ja(f"termin{len(a['termine']) + 1}", "Einen Termin eintragen?", False):
        i = len(a["termine"]) + 1
        art = d.text(f"termin{i}_art", "  Art: m = Mindesttemperatur / z = Zieltemperatur", "m" if a["mindest"] else "z")
        a["termine"].append({"art": art if art in ("m", "z") else "m",
                             "profil": d.text(f"termin{i}_profil", "  Profil (komfort / uebergang / urlaub / sommer)", "komfort"),
                             "tage": d.tage(f"termin{i}_tage", "  Wochentage", "alle"),
                             "zeit": d.zeit(f"termin{i}_zeit", "  Uhrzeit (HH:MM)", "06:00"),
                             "temp": d.zahl(f"termin{i}_temp", "  Temperatur °C", 21, 5, 28)})
    a["frostschutz"] = d.zahl("frostschutz", "Frostschutz-Temperatur (Profil Aus) °C", 5, 5, 12)
    a["aussensperre"] = d.zahl("aussensperre_grenze", "Außentemperatursperre ab °C (0 = keine)", 20, 0, 30)
    a["haus_aus"] = d.auswahl("haus_heizung_aus", "Globaler Schalter „Heizung Aus“ (optional)", b.liste("input_boolean"), optional=True,
                              vorschlag=next((e for e, _ in b.liste("input_boolean") if e.endswith("haus_heizung_aus")), None))

    print("\n=== 5. Zusatzfunktionen ===")
    a["boost"] = d.ja("boost", "Boost verwenden?", True)
    a["boost_dauer"] = d.zahl("boost_dauer", "Boost-Dauer in Minuten", 120, 10, 720) if a["boost"] else 120
    a["waermeerzeuger"] = ""
    a["vorheizen_max"] = 180
    if a["vorheizen"] or a["mindest"] or a["zieltermin"]:
        a["vorheizen_max"] = d.zahl("vorheizen_max", "Maximale Vorlaufzeit in Minuten", 180, 15, 720)
        vs = next((e for e, _ in b.liste("sensor") if "heizkreis" in e and "betriebszustand" in e), None)
        a["waermeerzeuger"] = d.auswahl("waermeerzeuger", "Heizphase des Wärmeerzeugers (optional, z. B. Betriebszustand des Heizkreises)",
                                        b.liste("sensor"), optional=True, vorschlag=vs)
    a["klima"] = d.ja("klima", "Hat der Raum eine Klimaanlage (Klimaautomatik einrichten)?", False)
    if a["klima"]:
        a["klima_sender"] = d.auswahl("klima_sender", "IR-Sender der Klimaanlage", b.liste("remote"))
        a["ir_geraet"] = d.text("ir_geraet", "Gerätename der gelernten Befehle", "klima")
        a["befehl_kuehlen"] = d.text("befehl_kuehlen", "IR-Befehl Kühlen ({stufe} = Temperatur)", "power_{stufe}")
        a["befehl_zusatz"] = d.text("befehl_zusatz", "Zusatzbefehl nach Kühlen (leer = keiner)", "eco_{stufe}")
        a["befehl_aus"] = d.text("befehl_aus", "IR-Befehl Aus", "power_off")
        a["luefter"] = d.text("luefter", "Lüfterstufe für {luefter} in den Befehlsnamen (leer = keine)", "")
        a["klima_fenster"] = d.auswahl("klima_fenster", "Fensterkontakte, die die Klimaanlage pausieren (0 = keine)",
                                       b.liste("binary_sensor", ["window", "door", "opening"]), optional=True, mehrfach=True,
                                       vorschlag=a["fensterkontakte"] or None)
    a["pv"] = a["klima"] and d.ja("pv", "PV-Überschussheizen über die Klimaanlage einrichten?", False)
    if a["pv"]:
        a["pv_raumfuehler"] = a["raumfuehler"] or d.auswahl("pv_raumfuehler", "Physischer Raumtemperaturfühler (Pflicht für PV-Heizen)",
                                                             b.liste("sensor", "temperature"))
        a["pv_trvs"] = d.auswahl("pv_heizkoerper", "Heizkörperthermostate (werden vor dem PV-Heizen geschlossen)", b.liste("climate"), mehrfach=True)
        a["pv_ventile"] = d.auswahl("pv_ventile", "Ventilöffnungs-Sensoren (0 = keine)", b.liste("sensor"), optional=True, mehrfach=True)
        a["pv_fenster"] = d.auswahl("pv_fenster", "Fenster, die PV-Heizen sperren", b.liste("binary_sensor", ["window", "door", "opening"]),
                                    optional=True, mehrfach=True, vorschlag=a.get("klima_fenster") or None)
        for k, frage in [("soc", "Batterie-Ladestand"), ("netz", "Netz-Einspeisung (positiv = Einspeisung)"),
                         ("akku_leistung", "Batterie-Leistung (positiv = Laden)"), ("pv_leistung", "PV-Leistung"), ("verbrauch", "Hausverbrauch")]:
            a[k] = d.auswahl(k, frage, b.liste("sensor"))
        a["zeitstempel_attribut"] = d.text("zeitstempel_attribut", "Zeitstempel-Attribut der Energiedaten (leer = last_reported)", "")
        a["befehl_heizen"] = d.text("befehl_heizen", "IR-Befehl Heizen (Vollzustand)", "heizen_24")
        a["befehl_heizen_aus"] = d.text("befehl_heizen_aus", "IR-Befehl Heizen aus", "heizen_24_off")
        a["start_leistung"] = d.zahl("start_leistung", "Start ab Einspeisung W", 1000, 500, 3000)
        a["soc_start"] = d.zahl("soc_start", "Start ab Batterie %", 95, 50, 100)
        a["soc_halten"] = d.zahl("soc_halten", "Weiterheizen ab Batterie %", 85, 20, 100)
        a["pv_ziel"] = d.zahl("pv_ziel", "PV-Zieltemperatur °C", 24, 18, 28)
    return a


# ====================================================================== Planung
def helfer_name(a, rolle):
    return f"HZ {a['raum_name']} {rolle}"


def strom_eingaben(a):
    """Blueprint-Eingaben für Klima-Steckdose und Leistungsmessung (Klimaautomatik und PV-Heizen) – nur, was eingerichtet ist."""
    out = {}
    if a.get("klima_steckdose"):
        out["klima_steckdose"] = a["klima_steckdose"]
    if a.get("klima_leistung"):
        out["klima_leistung"] = a["klima_leistung"]
    if out and a.get("laeuft_ab_w") is not None:
        out["laeuft_ab_w"] = a["laeuft_ab_w"]
    return out


def plane(a, b, d):
    """Erzeugt die Liste der Schritte und die Konfigurationen. Prüft vorab auf Kollisionen."""
    k = a["key"]
    helfer = []  # (domain, schlüssel, create-daten, startwert-aufruf)

    def h(domain, rolle, daten, start=None):
        name = helfer_name(a, rolle)
        eid = f"{domain}.{slug(name)}"
        helfer.append({"domain": domain, "rolle": rolle, "name": name, "entity_id": eid, "daten": dict(daten, name=name), "start": start})
        return eid

    e = {}
    aktive = [x for x in ("komfort", "uebergang", "urlaub") if x in (a.get("aktive_profile") or ["komfort", "uebergang", "urlaub"])]
    optionen = [PROFILNAMEN[x] for x in aktive if x != "urlaub"] + ["Sommer"] + (["Urlaub"] if "urlaub" in aktive else []) + ["Aus"]
    e["heizprofil"] = h("input_select", "Heizprofil", {"options": optionen, "icon": "mdi:home-thermometer"},
                        ("input_select", "select_option", {"option": optionen[0]}))
    e["status"] = h("input_text", "Status", {"min": 0, "max": 255, "mode": "text", "icon": "mdi:information-outline"})
    if a["fenster_modus"] == "eigen":
        e["fensterstatus"] = h("input_boolean", "Fensterstatus", {"icon": "mdi:window-open-variant"})
        e["fenster_timer"] = h("timer", "Fensterausfall", {"duration": "00:10:00", "restore": True, "icon": "mdi:timer-alert-outline"})
        if a.get("fenster_ausnahmen") and (a["klima"] or a["pv"]):  # z. B. Balkontür: pausiert die Heizung, nicht Klimaanlage und PV-Heizen
            e["fenster_klima"] = h("input_boolean", "Fensterstatus Klima", {"icon": "mdi:window-open-variant"})
    if a["boost"]:
        e["boost_wert"] = h("input_number", "Boost", {"min": a["frostschutz"], "max": 25, "step": 0.5, "mode": "slider",
                                                      "unit_of_measurement": "°C", "icon": "mdi:fire"},
                            ("input_number", "set_value", {"value": a["frostschutz"]}))
        e["boost_timer"] = h("timer", "Boost Timer", {"duration": "%02d:%02d:00" % divmod(int(a["boost_dauer"]), 60), "restore": True, "icon": "mdi:fire"})
    vorlauf = a["vorheizen"] or a.get("mindest") or a.get("zieltermin")
    if vorlauf:
        e["vh_faktor"] = h("input_number", "Vorheizfaktor", {"min": 0.5, "max": 3, "step": 0.01, "mode": "box", "icon": "mdi:chart-bell-curve"},
                           ("input_number", "set_value", {"value": 1}))
        e["vh_merker"] = h("input_text", "Vorheizen", {"min": 0, "max": 255, "mode": "text", "icon": "mdi:clock-start"})
        e["vh_bericht"] = h("input_text", "Vorheizbericht", {"min": 0, "max": 255, "mode": "text", "icon": "mdi:clipboard-text-clock"})
    steckdose = bool(a["klima"]) and a.get("klima_art", "ir") == "schalter"
    if steckdose:  # Klimaanlage an einer Schaltsteckdose: nur ein/aus, keine Stufen, kein IR
        e["klima_modus"] = h("input_select", "Klima Modus", {"options": ["Aus", "Automatik Kühlen", "Manuell Kühlen"], "icon": "mdi:hvac"},
                             ("input_select", "select_option", {"option": "Aus"}))
        e["klima_ziel"] = h("input_number", "Klima Ziel", {"min": 16, "max": 28, "step": 0.5, "mode": "slider", "unit_of_measurement": "°C",
                                                          "icon": "mdi:air-conditioner"}, ("input_number", "set_value", {"value": a.get("klima_ziel_start", 22)}))
        e["klima_aktiv"] = h("input_boolean", "Klima Aktiv", {"icon": "mdi:air-conditioner"})
    elif a["klima"]:
        e["klima_modus"] = h("input_select", "Klima Modus", {"options": ["Aus", "Automatik Kühlen", "Manuell Kühlen"], "icon": "mdi:hvac"},
                             ("input_select", "select_option", {"option": "Aus"}))
        e["klima_ziel"] = h("input_number", "Klima Ziel", {"min": 16, "max": 23, "step": 1, "mode": "slider", "unit_of_measurement": "°C",
                                                          "icon": "mdi:air-conditioner"}, ("input_number", "set_value", {"value": 22}))
        e["klima_manuell"] = h("input_number", "Klima Manuell", {"min": 16, "max": 23, "step": 1, "mode": "box", "unit_of_measurement": "°C",
                                                                "icon": "mdi:snowflake"}, ("input_number", "set_value", {"value": 20}))
        e["klima_stufe"] = h("input_number", "Klima Letzte Stufe", {"min": 0, "max": 30, "step": 1, "mode": "box", "icon": "mdi:counter"})
        e["klima_aktiv"] = h("input_boolean", "Klima Aktiv", {"icon": "mdi:air-conditioner"})
        e["klima_vor_fenster"] = h("input_text", "Klima vor Fenster", {"min": 0, "max": 100, "mode": "text"})
        e["ir_konfig"] = h("input_text", "Klima IR", {"min": 0, "max": 255, "mode": "text", "icon": "mdi:remote"})
    if a["pv"]:
        for schl, rolle, dauer in [("t_startfrist", "PV Startfrist", 5), ("t_mangelfrist", "PV Mangelfrist", 10), ("t_wiederholung", "PV IR Wiederholung", 10),
                                   ("t_waermepruefung", "PV Waermepruefung", 40), ("t_sperre", "PV Wiederanlaufsperre", 30),
                                   ("t_freigabe", "PV Sicherheitsfreigabe", 2), ("t_schaltpause", "PV Schaltpause", 5), ("t_heizkoerper", "PV Heizkoerperfrist", 8)]:
            e[schl] = h("timer", rolle, {"duration": "00:%02d:00" % dauer, "restore": schl in ("t_sperre", "t_schaltpause", "t_heizkoerper")})
        for schl, rolle in [("f_heizfreigabe", "PV Heizfreigabe"), ("f_ir_geprueft", "PV IR geprueft"), ("f_regelung", "PV Regelung aktiv"),
                            ("f_heizbefehl", "PV Heizbefehl aktiv"), ("f_auftrag", "PV IR Auftrag offen"), ("f_fehler", "PV IR Fehler"),
                            ("f_wiederholt", "PV IR wiederholt"), ("f_vorbereitung", "PV Startvorbereitung")]:
            e[schl] = h("input_boolean", rolle, {"icon": "mdi:solar-power-variant"})
        e["pv_starttemp"] = h("input_number", "PV Starttemperatur", {"min": -20, "max": 50, "step": 0.1, "mode": "box", "unit_of_measurement": "°C"},
                              ("input_number", "set_value", {"value": 20}))
        e["pv_status"] = h("input_text", "PV Status", {"min": 0, "max": 255, "mode": "text", "icon": "mdi:solar-power-variant"})

    def phasen_inputs(key, p, n):
        if a.get("zeitquelle") == "zeitplan":
            e[f"zeitplan_{key}"] = h("schedule", f"Zeitplan {PROFILNAMEN[key]}", dict(zeitplan_bloecke(p["phasen"]), icon="mdi:calendar-clock"))
            out = {f"{key}_soll": p["soll"], f"{key}_absenk": p["absenk"], f"{key}_quelle": "zeitplan", f"{key}_zeitplan": e[f"zeitplan_{key}"]}
            if a["vorheizen"] and p.get("zp_vh"):
                out.update({f"{key}_zp_vh": True, f"{key}_zp_vh_temp": p["zp_vh_temp"]})
            return out
        out = {f"{key}_soll": p["soll"], f"{key}_absenk": p["absenk"], f"{key}_quelle": "phasen"}
        belegt = {(ph["gruppe"], ph["nr"]): ph for ph in p["phasen"]}
        for tag, _, _ in TAGESPROGRAMME:
            for i in (1, 2, 3):
                pre = f"{key}_{tag}{i}"
                ph = belegt.get((tag, i))
                if ph is None:
                    out[f"{pre}_aktiv"] = False
                    continue
                out.update({f"{pre}_aktiv": True, f"{pre}_von": ph["von"], f"{pre}_bis": ph["bis"]})
                if ph.get("vh"):
                    out.update({f"{pre}_vh": True, f"{pre}_vh_temp": ph["vh_temp"], f"{pre}_vh_bis": ph["vh_bis"]})
        return out

    rh = {"raum_name": a["raum_name"], "raum_schluessel": k, "better_thermostat": a["bt"], "aussentemperatur": a["aussen"],
          "heizprofil": e["heizprofil"], "status_text": e["status"], "frostschutz": a["frostschutz"],
          "aussensperre_aktiv": a["aussensperre"] > 0, "aussensperre_grenze": a["aussensperre"] or 20,
          "fenster_modus": a["fenster_modus"], "fenster_reaktion": a["fenster_reaktion"]}
    if a["raumfuehler"]:
        rh["raumfuehler"] = a["raumfuehler"]
    if a["haus_aus"]:
        rh["haus_heizung_aus"] = a["haus_aus"]
    for key, n in (("komfort", 6), ("uebergang", 6), ("urlaub", 6)):
        if key in aktive:
            rh.update(phasen_inputs(key, a["profile"][key], n))
    rh["sommer_heizen"] = a["sommer_heizen"]
    if a["sommer_heizen"]:
        rh.update(phasen_inputs("sommer", a["profile"]["sommer"], 3))
    if a["fenster_modus"] == "eigen":
        rh.update(fensterkontakte=a["fensterkontakte"], fensterstatus=e["fensterstatus"], fenster_timer=e["fenster_timer"])
        if e.get("fenster_klima"):
            rh.update(fenster_ausnahmen=a["fenster_ausnahmen"], fensterstatus_klima=e["fenster_klima"])
    elif a["fenster_modus"] == "extern":
        rh["fensterstatus"] = a["fensterstatus_extern"]
    if a["boost"]:
        rh.update(boost_aktiv=True, boost_wert=e["boost_wert"], boost_timer=e["boost_timer"])
    if vorlauf:
        rh.update(vorheizen_aktiv=bool(a["vorheizen"]), vorheizen_max=a["vorheizen_max"], vorheizen_faktor=e["vh_faktor"],
                  vorheizen_merker=e["vh_merker"], vorheizen_bericht=e["vh_bericht"])
        for art, schalter, halten in (("m", "mindest", "mindest_halten"), ("z", "zieltermin", "zieltermin_halten")):
            if not a.get(schalter):
                continue
            rh[f"{schalter}_aktiv"] = True
            if a.get(halten) is not None:
                rh[halten] = a[halten]
            zaehler = {}
            for tm in a.get("termine", []):
                if tm["art"] != art or (tm["profil"] not in aktive and not (tm["profil"] == "sommer" and a["sommer_heizen"])):
                    continue
                j = zaehler[tm["profil"]] = zaehler.get(tm["profil"], 0) + 1
                if j > (2 if tm["profil"] == "sommer" else 4):
                    raise ValueError(f"Zu viele {'Mindest' if art == 'm' else 'Ziel'}temperatur-Termine im Profil {PROFILNAMEN[tm['profil']]} (höchstens {2 if tm['profil'] == 'sommer' else 4}).")
                rh.update({f"{tm['profil']}_{art}{j}_aktiv": True, f"{tm['profil']}_{art}{j}_tage": tm["tage"],
                           f"{tm['profil']}_{art}{j}_zeit": tm["zeit"], f"{tm['profil']}_{art}{j}_temp": tm["temp"]})
        if a["waermeerzeuger"]:
            rh["waermeerzeuger"] = a["waermeerzeuger"]
    if a["pv"]:
        rh.update(pv_aktiv=True, pv_flags=[e["f_regelung"], e["f_heizbefehl"], e["f_auftrag"], e["f_vorbereitung"]], pv_freigabe=e["t_freigabe"])

    if a["fenster_modus"] == "eigen":
        fenster_klima = [e.get("fenster_klima") or e["fensterstatus"]]
    elif a["fenster_modus"] == "extern" and a.get("fensterstatus_extern"):
        fenster_klima = [a["fensterstatus_extern"]]
    else:
        fenster_klima = []
    automationen = [{"rolle": "raumheizung", "id": f"hz_{k}_raumheizung", "alias": f"Heizung {a['raum_name']}",
                     "description": "Erstellt mit dem Einrichtungsassistenten (Universelle Raumheizungssteuerung).",
                     "use_blueprint": {"path": BP["raumheizung"], "input": rh}}]
    if steckdose:
        ks = {"raum_name": a["raum_name"], "raum_schluessel": k, "klima_schalter": a["klima_schalter"], "raumfuehler": a["raumfuehler"] or a["bt"],
              "fensterkontakte": fenster_klima, "ein_ueber": a.get("ein_ueber", 0.5), "aus_unter": a.get("aus_unter", 0.0),
              "abwesend_aus": a.get("abwesend_aus", True), "kuehl_profile": a.get("kuehl_profile") or ["Sommer", "Aus"],
              "heizprofil": e["heizprofil"], "klima_modus": e["klima_modus"], "zieltemperatur": e["klima_ziel"], "klima_aktiv": e["klima_aktiv"]}
        if a.get("anwesenheit"):
            ks["anwesenheit"] = a["anwesenheit"]
        if a["haus_aus"]:
            ks["haus_heizung_aus"] = a["haus_aus"]
        automationen.append({"rolle": "klima", "id": f"hz_{k}_klima", "alias": f"Klima {a['raum_name']}",
                             "description": "Erstellt mit dem Einrichtungsassistenten (Klimaautomatik Steckdose).",
                             "use_blueprint": {"path": BP["klima_schalter"], "input": ks}})
    elif a["klima"]:
        kl = {"raum_name": a["raum_name"], "raum_schluessel": k, "klima_sender": a["klima_sender"], "ir_geraet": a["ir_geraet"],
              "raumfuehler": a["raumfuehler"] or a["bt"], "aussentemperatur": a["aussen"], "fensterkontakte": fenster_klima,
              "befehl_kuehlen": a["befehl_kuehlen"], "befehl_kuehlen_zusatz": a["befehl_zusatz"], "befehl_aus": a["befehl_aus"],
              "luefter": a.get("luefter", ""), "ir_konfiguration": e["ir_konfig"],
              "heizprofil": e["heizprofil"], "klima_modus": e["klima_modus"], "zieltemperatur": e["klima_ziel"], "manuelle_stufe": e["klima_manuell"],
              "letzte_stufe": e["klima_stufe"], "klima_aktiv": e["klima_aktiv"], "modus_vor_fenster": e["klima_vor_fenster"]}
        if a["haus_aus"]:
            kl["haus_heizung_aus"] = a["haus_aus"]
        for opt in ("stufe_min", "stufe_max"):
            if a.get(opt) is not None:
                kl[opt] = a[opt]
        for opt in ("befehl_heizen", "befehl_heizen_aus"):
            if a.get(opt):
                kl[opt] = a[opt]
        kl.update(strom_eingaben(a))
        if a["pv"]:
            kl.update(pv_aktiv=True, pv_heizfreigabe=e["f_heizfreigabe"], pv_heizbefehl=e["f_heizbefehl"], pv_auftrag=e["f_auftrag"],
                      pv_verantwortung=[e["f_regelung"], e["f_vorbereitung"]], pv_freigabe=e["t_freigabe"], pv_status=e["pv_status"],
                      pv_automation=f"automation.{slug('PV-Heizen ' + a['raum_name'])}")
        automationen.append({"rolle": "klima", "id": f"hz_{k}_klima", "alias": f"Klima {a['raum_name']}",
                             "description": "Erstellt mit dem Einrichtungsassistenten (Klimaautomatik).",
                             "use_blueprint": {"path": BP["klima"], "input": kl}})
    if a["pv"]:
        pv = {"raum_name": a["raum_name"], "raum_schluessel": k, "better_thermostat": a["bt"], "heizkoerper": a["pv_trvs"], "ventile": a["pv_ventile"] or [],
              "raumfuehler": a["pv_raumfuehler"], "aussentemperatur": a["aussen"],
              "fensterkontakte": fenster_klima, "ir_konfiguration": e["ir_konfig"],
              "soc": a["soc"], "netz": a["netz"], "akku_leistung": a["akku_leistung"], "pv_leistung": a["pv_leistung"], "verbrauch": a["verbrauch"],
              "zeitstempel_attribut": a["zeitstempel_attribut"], "start_leistung": a["start_leistung"], "soc_start": a["soc_start"],
              "soc_halten": a["soc_halten"], "pv_ziel": a["pv_ziel"], "heizprofil": e["heizprofil"], "heizstufe": a.get("pv_heizstufe", 24),
              "raumheizung_automation": f"automation.{slug('Heizung ' + a['raum_name'])}", "klima_automation": f"automation.{slug('Klima ' + a['raum_name'])}",
              "klima_modus": e["klima_modus"], "klima_aktiv": e["klima_aktiv"], "starttemperatur": e["pv_starttemp"], "status_text": e["pv_status"]}
        pv.update({s: e[s] for s in e if s.startswith(("t_", "f_"))})
        pv.update({k: v for k, v in strom_eingaben(a).items() if k != "steckdose_halten"})
        automationen.append({"rolle": "pv", "id": f"hz_{k}_pv", "alias": f"PV-Heizen {a['raum_name']}",
                             "description": "Erstellt mit dem Einrichtungsassistenten (PV-Überschussheizen).",
                             "use_blueprint": {"path": BP["pv"], "input": pv}})

    konflikte = [x["entity_id"] for x in helfer if b.existiert(x["entity_id"])]
    kartenhelfer = {"profile": optionen, "fenster_bt": a["fenster_modus"] != "ohne" and a.get("fenster_reaktion") == "bt", "raum_name": a["raum_name"], "status_text": e["status"], "heizprofil": e["heizprofil"],
                    "boost_wert": e.get("boost_wert"), "boost_timer": e.get("boost_timer"), "vorheizen_bericht": e.get("vh_bericht"),
                    "klima_modus": e.get("klima_modus"), "klima_ziel": e.get("klima_ziel"), "klima_manuell": e.get("klima_manuell"),
                    "pv_heizfreigabe": e.get("f_heizfreigabe"), "pv_status": e.get("pv_status"), "pv_fehler": e.get("f_fehler")}
    return {"helfer": helfer, "automationen": automationen, "kartenhelfer": kartenhelfer, "karte": raumkarte(kartenhelfer), "konflikte": konflikte, "entitaeten": e}


# ====================================================================== Dashboard-Auswahl
def dashboard_ziel(d, ha):
    if not d.ja("karte_einfuegen", "Dashboard-Karte jetzt in ein Dashboard einfügen? (sonst nur als Datei)", True):
        return None
    boards = ha.befehl("lovelace/dashboards/list")
    eintraege = [("__default__", "Übersicht (Standard-Dashboard)")] + [(x["url_path"], x.get("title") or x["url_path"]) for x in boards if x.get("mode") == "storage"]
    url = d.auswahl("dashboard", "In welchem Dashboard?", eintraege)
    url_path = None if url == "__default__" else url
    cfg = ha.befehl("lovelace/config", url_path=url_path)
    views = cfg.get("views", [])
    vi = int(d.auswahl("ansicht", "In welcher Ansicht?", [(str(i), f"{v.get('title') or v.get('path') or 'Ansicht ' + str(i)}") for i, v in enumerate(views)]))
    view = views[vi]
    if "sections" in view:
        secs = view["sections"]

        def titel(s, i):
            ueb = next((c.get("heading") for c in s.get("cards", []) if c.get("type") == "heading"), None)
            return f"Abschnitt {i + 1}" + (f" – {ueb}" if ueb else "") + f" ({len(s.get('cards', []))} Karten)"
        opts = [(str(i), titel(s, i)) for i, s in enumerate(secs)] + [("neu", "Neuen Abschnitt am Ende anlegen")]
        si = d.auswahl("abschnitt", "In welchem Abschnitt?", opts)
        if si == "neu":
            return {"url_path": url_path, "view": vi, "section": "neu", "pos": 0, "cfg": cfg}
        n = len(secs[int(si)].get("cards", []))
        pos = int(d.zahl("position", f"An welcher Position? (1 = oben … {n + 1} = unten)", n + 1, 1, n + 1)) - 1
        return {"url_path": url_path, "view": vi, "section": int(si), "pos": pos, "cfg": cfg}
    n = len(view.get("cards", []))
    print("  Hinweis: Diese Ansicht hat keine Abschnitte. Die Karte wird auf oberster Ebene eingefügt (nicht in verschachtelte Tabs).")
    pos = int(d.zahl("position", f"An welcher Position? (1 = oben … {n + 1} = unten)", n + 1, 1, n + 1)) - 1
    return {"url_path": url_path, "view": vi, "section": None, "pos": pos, "cfg": cfg}


def dashboard_plaetze(view, namen=None):
    """Alle Stellen einer Ansicht, an denen Karten stehen können: (Pfad, Beschriftung, Anzahl Karten).

    Beschriftungen sind sprechend: Tabs heißen nach ihrem Namen (ohne „Tabdeck 6“), Raster und Stapel nach der Überschrift davor
    oder nach ihrer ersten Karte."""
    plaetze = []
    art = {"vertical-stack": "Stapel", "horizontal-stack": "Reihe", "grid": "Raster", "custom:tabdeck-card": "Tab-Leiste",
           "custom:stack-in-card": "Stapel", "custom:vertical-stack-in-card": "Stapel", "custom:layout-card": "Layout"}

    def name(geschwister, i):
        k = geschwister[i]
        wort = art.get(k.get("type"), "Gruppe")
        if k.get("type") == "custom:tabdeck-card":
            return None  # die Tabs tragen den Namen
        vorher = geschwister[i - 1] if i > 0 and isinstance(geschwister[i - 1], dict) else {}
        if vorher.get("type") == "heading" and vorher.get("heading"):
            return f"{wort} „{str(vorher['heading'])[:30]}“"
        inhalt = [x for x in (k.get("cards") or []) if isinstance(x, dict)]
        return f"{wort} ab „{kartenname(inhalt[0], namen)}“" if inhalt else f"{wort} {i + 1}"

    def lauf(c, pfad, titel, tiefe):
        if not isinstance(c, dict) or tiefe > 8:
            return
        if isinstance(c.get("cards"), list) and not (c.get("type") == "custom:mod-card"):
            plaetze.append((pfad + ["cards"], " › ".join(titel) or "Oberste Ebene der Ansicht", len(c["cards"])))
            for i, k in enumerate(c["cards"]):
                if isinstance(k, dict) and (k.get("cards") is not None or k.get("tabs") is not None or (k.get("card") and k.get("type") != "custom:mod-card")):
                    teil = name(c["cards"], i)
                    lauf(k, pfad + ["cards", i], titel + ([teil] if teil else []), tiefe + 1)
        if isinstance(c.get("tabs"), list):
            for i, tab in enumerate(c["tabs"]):
                if isinstance(tab, dict) and isinstance(tab.get("card"), dict):
                    lauf(tab["card"], pfad + ["tabs", i, "card"], titel + [f"Tab „{tab.get('name') or tab.get('label') or i + 1}“"], tiefe + 1)
        if isinstance(c.get("card"), dict) and c.get("type") != "custom:mod-card":
            lauf(c["card"], pfad + ["card"], titel, tiefe + 1)

    if isinstance(view.get("sections"), list):
        for i, sec in enumerate(view["sections"]):
            ueb = next((k.get("heading") for k in sec.get("cards", []) if isinstance(k, dict) and k.get("type") == "heading"), None)
            sec.setdefault("cards", [])
            lauf(sec, ["sections", i], [f"Abschnitt {i + 1}" + (f" – {ueb}" if ueb else "")], 0)
        plaetze.append((["sections", "neu"], "Neuen Abschnitt für diese Karte anlegen", 0))
    else:
        view.setdefault("cards", [])
        lauf(view, [], [], 0)
    gesehen = {}
    for j, (pf, t, n) in enumerate(plaetze):  # gleich lautende Beschriftungen unterscheidbar machen
        gesehen[t] = gesehen.get(t, 0) + 1
        if gesehen[t] > 1:
            plaetze[j] = (pf, f"{t} ({gesehen[t]})", n)
    return plaetze


_RAUMKARTE = re.compile(r"input_text\.hz_[a-z0-9_]+_status|input_select\.[a-z0-9_]*heizprofil")
_BEHAELTER = ("grid", "vertical-stack", "horizontal-stack", "custom:tabdeck-card", "custom:layout-card")


def ist_raumkarte(c):
    """Karte, die einen Raum mit Heizung zeigt (Heizprofil-Auswahl oder Raumkarte dieser Integration) – keine Sammelkarte."""
    return isinstance(c, dict) and c.get("type") not in _BEHAELTER and bool(_RAUMKARTE.search(json.dumps(c)))


def _liste(view, pfad):
    ziel = view
    for schritt in pfad:
        ziel = ziel[schritt]
    return ziel


def raumkarten_anzahl(view, pfad):
    """Wie viele Raumkarten stehen direkt an dieser Stelle?"""
    if pfad[:2] == ["sections", "neu"]:
        return 0
    try:
        return sum(1 for k in _liste(view, pfad) if ist_raumkarte(k))
    except (KeyError, IndexError, TypeError):
        return 0


def plaetze_ordnen(view, plaetze):
    """Empfohlene Stellen zuerst: dort, wo schon Raumkarten stehen. Rückgabe: (geordnete Plätze, Indizes der empfohlenen)."""
    zahl = [raumkarten_anzahl(view, pf) for pf, _, _ in plaetze]
    beste = max(zahl, default=0)
    empf = {i for i, z in enumerate(zahl) if beste and (z == beste or z >= 2)}
    neu = next((i for i, (pf, _, _) in enumerate(plaetze) if pf[:2] == ["sections", "neu"]), None)
    if neu is not None:
        # je Raum ein eigener Abschnitt (Abschnitte-Ansicht) → „Neuen Abschnitt“ empfehlen
        abschnitte = [pf for pf, _, _ in plaetze if pf[:1] == ["sections"] and len(pf) == 3]
        einzeln = [pf for pf in abschnitte if raumkarten_anzahl(view, pf) >= 1 and len(_liste(view, pf)) <= 3]
        if len(einzeln) >= 2:
            empf.add(neu)
    reihenfolge = sorted(range(len(plaetze)), key=lambda i: (i not in empf, -(zahl[i]) if i in empf else 0, i))
    if neu is not None and neu in empf:
        reihenfolge.remove(neu)
        reihenfolge.insert(0, neu)
    return [plaetze[i] for i in reihenfolge], {j for j, i in enumerate(reihenfolge) if i in empf}


_TYPNAMEN = {"vertical-stack": "Stapel", "horizontal-stack": "Reihe", "grid": "Raster", "tabdeck-card": "Tab-Leiste", "markdown": "Text",
             "button-card": "Schaltfläche", "mushroom-chips-card": "Chips-Leiste", "glass-clock-weather-card": "Uhr und Wetter",
             "auto-entities": "Automatische Liste", "entities": "Liste", "weather-forecast": "Wetter", "picture-elements": "Bild",
             "mushroom-template-card": "Vorlagenkarte", "mod-card": "Karte", "thermostat": "Thermostat", "tile": "Kachel"}


def kartenname(c, namen=None):
    """Lesbarer Name einer vorhandenen Dashboard-Karte (für die Übersicht bei der Platzierung).

    namen: optional {entity_id: Anzeigename} – auch {Status-Helfer einer Raumkarte dieser Integration: Raumname}."""
    namen = namen or {}
    if not isinstance(c, dict):
        return "Karte"
    text = json.dumps(c, ensure_ascii=False)
    eigen = re.search(r"input_text\.hz_[a-z0-9_]+_status", text)
    if eigen and c.get("type") == "custom:mod-card":  # Raumkarte dieser Integration
        m = re.search(r'class=\\*"name\\*">([^<$]{2,40})<', text)
        raum = namen.get(eigen.group(0)) or (m.group(1).strip() if m else None)
        kopf = (c.get("card") or {}).get("cards", [{}])[0] if isinstance((c.get("card") or {}).get("cards"), list) else {}
        raum = raum or (kopf.get("name") if isinstance(kopf.get("name"), str) and "[[[" not in kopf["name"] else None)
        return f"Raumkarte {raum}" if raum else "Raumkarte"
    for k in ("name", "title", "heading", "primary"):
        v = c.get(k)
        if isinstance(v, str) and v.strip() and "[[[" not in v and "{{" not in v:
            return v.strip()[:40]
    m = re.search(r'name\\*"\s*:\s*\\*"([^"\\{}\[\]]{2,40})', text) or re.search(r'class=\\*"name\\*">([^<$]{2,40})<', text)
    if m:
        return m.group(1).strip()
    if isinstance(c.get("content"), str) and c["content"].strip():
        return c["content"].strip().splitlines()[0].lstrip("# ")[:40]
    for k in ("entity", "entity_id"):
        if isinstance(c.get(k), str):
            return namen.get(c[k]) or c[k]
    m = re.search(r'"entity"\s*:\s*"([a-z_]+\.[a-z0-9_]+)"', text)
    if m:
        return namen.get(m.group(1)) or m.group(1)
    art = str(c.get("type", "Karte")).replace("custom:", "")
    return _TYPNAMEN.get(art, art)


def platz_inhalt(view, pfad, namen=None):
    """Namen der Karten, die an dieser Stelle bereits stehen."""
    if pfad[:2] == ["sections", "neu"]:
        return [(next((k.get("heading") for k in sec.get("cards", []) if isinstance(k, dict) and k.get("type") == "heading"), None)
                 or ", ".join(kartenname(k, namen) for k in sec.get("cards", [])[:2]) or f"Abschnitt {i + 1}") for i, sec in enumerate(view.get("sections", []))]
    return [kartenname(k, namen) for k in _liste(view, pfad)]


def platz_beschriftung(view, pfad, titel, namen=None, empfohlen=False):
    stern = "★ Empfohlen · " if empfohlen else ""
    if pfad[:2] == ["sections", "neu"]:
        return stern + "Neuen Abschnitt für diese Karte anlegen (Position wählbar)"
    inhalt = platz_inhalt(view, pfad, namen)
    if not inhalt:
        return f"{stern}{titel} – noch leer"
    rk = raumkarten_anzahl(view, pfad)
    zusatz = f" ({rk} Raumkarten)" if rk >= 2 else ""
    return f"{stern}{titel}{zusatz} – enthält: " + ", ".join(inhalt[:4]) + (f" und {len(inhalt) - 4} weitere" if len(inhalt) > 4 else "")


_NUMMERN = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


def _nr(i):
    return _NUMMERN[i] if i < len(_NUMMERN) else f"({i + 1})"


def _spalten(view, pfad):
    """Spaltenzahl, wenn die Stelle ein Raster ist (Abschnitte und Stapel: 1)."""
    if pfad[:1] == ["sections"] or len(pfad) < 2 or pfad[-1] != "cards":
        return 1
    try:
        beh = _liste(view, pfad[:-1])
    except (KeyError, IndexError, TypeError):
        return 1
    if isinstance(beh, dict) and beh.get("type") == "grid":
        try:
            return max(1, int(beh.get("columns", 3)))
        except (TypeError, ValueError):
            return 3
    if isinstance(beh, dict) and beh.get("type") == "horizontal-stack":
        return max(1, len(beh.get("cards", [])) + 1)
    return 1


def positionen(view, pfad, namen=None):
    """Einfügestellen mit Nachbarn: [(Index, Beschriftung)] und ein Lageplan (Markdown).

    Raster werden als Reihen und Spalten gezeigt, Listen als Folge von Karten. Die Nummern markieren die Einfügestellen."""
    inhalt = platz_inhalt(view, pfad, namen)
    wort = "Abschnitt" if pfad[:2] == ["sections", "neu"] else "Karte"
    sp = _spalten(view, pfad) if wort == "Karte" else 1
    kurz = [x.removeprefix("Raumkarte ") for x in inhalt]
    kurz = [x if len(x) <= 20 else x[:19] + "…" for x in kurz]
    opt = []
    seite = {2: ["links", "rechts"], 3: ["links", "Mitte", "rechts"]}.get(sp)
    for i in range(len(inhalt) + 1):
        if sp > 1:
            r, s = divmod(i, sp)
            ort = f"Reihe {r + 1} · " + (seite[s] if seite else f"Spalte {s + 1}")
            text = f"{_nr(i)} {ort} – " + (f"vor „{inhalt[i]}“" if i < len(inhalt) else "ganz am Ende" + (f" (nach „{inhalt[-1]}“)" if inhalt else ""))
        elif not inhalt:
            text = f"{_nr(i)} einzige {wort} an dieser Stelle"
        elif i == 0:
            text = f"{_nr(i)} ganz oben – vor „{inhalt[0]}“"
        elif i == len(inhalt):
            text = f"{_nr(i)} ganz unten – nach „{inhalt[-1]}“"
        else:
            text = f"{_nr(i)} zwischen „{inhalt[i - 1]}“ und „{inhalt[i]}“"
        opt.append((i, text))
    if sp > 1:
        breite = max([len(x) for x in kurz] + [7])
        zeilen = []
        for r in range(len(inhalt) // sp + 1):
            zellen = []
            for s in range(sp):
                i = r * sp + s
                if i < len(inhalt):
                    zellen.append(f"{_nr(i)} {kurz[i]:<{breite}}")
                elif i == len(inhalt):
                    zellen.append(f"{_nr(i)} {'(Ende)':<{breite}}")
            if zellen:
                zeilen.append(f"Reihe {r + 1}  " + "   ".join(zellen))
        plan = "\n".join(zeilen)
        erkl = (f"Raster mit {sp} Spalten. Die Nummer steht vor der Karte, vor der die neue Karte eingefügt wird; "
                "die folgenden Karten rücken eine Stelle weiter.")
    else:
        zeilen = []
        for i in range(len(inhalt) + 1):
            zeilen.append(f"{_nr(i)} ┈┈┈┈┈┈┈┈┈┈┈┈┈┈")
            if i < len(inhalt):
                zeilen.append(f"    ▢ {inhalt[i]}")
        plan = "\n".join(zeilen)
        erkl = f"Die Nummern zeigen die möglichen Einfügestellen zwischen den vorhandenen {'Abschnitten' if wort == 'Abschnitt' else 'Karten'}."
    return opt, f"{erkl}\n\n```\n{plan}\n```"


def ansicht_uebersicht(view, plaetze, namen=None, empfohlen=()):
    """Aufbau einer Ansicht als eingerückte Liste (Markdown); empfohlene Stellen mit ★.
    Bei großen Ansichten nur die oberen zwei Ebenen (tiefer liegende Raster nur, wenn empfohlen)."""
    zeilen = []
    gross = len(plaetze) > 12
    for j, (pfad, titel, n) in enumerate(plaetze):
        if pfad[:2] == ["sections", "neu"]:
            continue
        tiefe = max(0, titel.count(" › "))
        if gross and tiefe >= 1 and j not in empfohlen:
            continue
        inhalt = platz_inhalt(view, pfad, namen)
        stern = "★ " if j in empfohlen else ""
        zeilen.append((pfad, "  " * tiefe + f"- {stern}**{titel.split(' › ')[-1]}**: " + (", ".join(inhalt[:6]) + (" …" if len(inhalt) > 6 else "") if inhalt else "*leer*")))
    zeilen.sort(key=lambda z: [str(x).zfill(4) for x in z[0]])  # in der Reihenfolge der Ansicht, auch wenn die Plätze umsortiert sind
    return "\n".join(z for _, z in zeilen) or "- *Diese Ansicht enthält noch keine Karten.*"


def design_erkennen(view, pfad):
    """Welches Kartendesign passt zu den Karten in diesem Bereich (sonst zur ganzen Ansicht)? → "mobil" | "glas" | "verlauf"."""
    def punkte(text):
        mobil = 4 * text.count("23px 22px")  # kompakter Kopf der Mobil-Raumkarten
        glas = text.count("backdrop-filter") + 2 * text.count("rgba(255,179,91,0.20)")
        verlauf = text.count("#151e2d") + text.count("rgba(30,30,30,.88)") + text.count("max-width: 390px")
        return mobil, glas, verlauf
    try:
        nah = punkte(json.dumps(_liste(view, [] if pfad[:2] == ["sections", "neu"] else pfad), ensure_ascii=False))
    except (KeyError, IndexError, TypeError):
        nah = (0, 0, 0)
    ganz = punkte(json.dumps(view, ensure_ascii=False))
    mo, g, v = nah if nah != (0, 0, 0) else ganz
    if mo and mo >= g and mo >= v:
        return "mobil"
    if ganz[0] >= 8 and not v:  # Ansicht im Mobil-Stil (mindestens zwei Mobil-Raumkarten), Bereich ohne Verlauf-Karten
        return "mobil"
    return "verlauf" if v > g else "glas"


def karte_einsetzen(view, pfad, pos, karte):
    if pfad[:2] == ["sections", "neu"]:
        abschnitte = view.setdefault("sections", [])
        abschnitte.insert(max(0, min(int(pos), len(abschnitte))) if pos is not None else len(abschnitte), {"type": "grid", "cards": [karte]})
        return
    ziel = view
    for schritt in pfad:
        ziel = ziel[schritt]
    ziel.insert(max(0, min(int(pos), len(ziel))), karte)


def karte_entfernen(cfg, merkmal):
    """Entfernt die Raumkarte(n), die den Status-Helfer des Raums verwenden. Rückgabe: Anzahl entfernter Karten."""
    anzahl = 0

    def lauf(c):
        nonlocal anzahl
        if isinstance(c, dict):
            for k, v in list(c.items()):
                if k == "cards" and isinstance(v, list):
                    behalten = [x for x in v if not (isinstance(x, dict) and x.get("type") == "custom:mod-card" and merkmal in json.dumps(x))]
                    anzahl += len(v) - len(behalten)
                    c[k] = behalten
                    v = behalten
                lauf(v)
        elif isinstance(c, list):
            for x in c:
                lauf(x)

    lauf(cfg)
    return anzahl


# ====================================================================== Ausführung
class Ausfuehrung:
    def __init__(self, ha, ordner, trocken):
        self.ha, self.ordner, self.trocken = ha, ordner, trocken
        self.rueckbau = {"erstellt": dt.datetime.now().isoformat(timespec="seconds"), "helfer": [], "automationen": [], "dashboard": None, "blueprints": []}
        self.log = []

    leise = False

    def notiere(self, text):
        if not self.leise:
            print("  ✔ " + text)
        self.log.append(text)
        self.ordner.mkdir(parents=True, exist_ok=True)
        (self.ordner / "rueckbau.json").write_text(json.dumps(self.rueckbau, ensure_ascii=False, indent=2), encoding="utf-8")

    def blueprints(self, d, rollen):
        vorhanden = {} if self.trocken else (self.ha.befehl("blueprint/list", domain="automation") or {})
        for rolle in dict.fromkeys(rollen):
            pfad = BP.get(rolle, rolle)  # Rolle oder Blueprint-Pfad
            text = (BP_ORDNER / Path(pfad).name).read_text(encoding="utf-8")
            if pfad in vorhanden and not self.trocken:
                beschreibung = ((vorhanden[pfad] or {}).get("metadata") or {}).get("description") or ""
                if f"Paketversion {PAKETVERSION} " in beschreibung:
                    self.notiere(f"Blueprint {pfad} ist bereits in Version {PAKETVERSION} installiert")
                    continue
                self.ha.befehl("blueprint/save", domain="automation", path=pfad, yaml=text, allow_override=True)
            elif not self.trocken:
                self.ha.befehl("blueprint/save", domain="automation", path=pfad, yaml=text)
            self.rueckbau["blueprints"].append(pfad)
            self.notiere(f"Blueprint {pfad} {'würde installiert' if self.trocken else 'installiert'}")

    def helfer(self, liste):
        for x in liste:
            if self.trocken:
                self.notiere(f"Helfer {x['entity_id']} würde angelegt")
                continue
            erg = self.ha.befehl(f"{x['domain']}/create", **x["daten"])
            eid = f"{x['domain']}.{erg['id']}"
            if eid != x["entity_id"]:
                raise HAFehler(f"Helfer wurde als {eid} statt {x['entity_id']} angelegt – Abbruch (Rückbau möglich).")
            self.rueckbau["helfer"].append({"domain": x["domain"], "id": erg["id"], "entity_id": eid})
            if x["start"]:
                dom, srv, daten = x["start"]
                self.ha.befehl("call_service", domain=dom, service=srv, service_data=daten, target={"entity_id": eid})
            self.notiere(f"Helfer {eid} angelegt")

    def automation(self, a):
        konf = {k: v for k, v in a.items() if k != "rolle"}
        if self.trocken:
            self.notiere(f"Automation „{a['alias']}“ würde angelegt")
            return f"automation.{slug(a['alias'])}"
        self.ha.rest("POST", f"/api/config/automation/config/{a['id']}", konf)
        self.rueckbau["automationen"].append(a["id"])
        eid = None
        for _ in range(20):
            reg = self.ha.befehl("config/entity_registry/list")
            eid = next((r["entity_id"] for r in reg if r.get("platform") == "automation" and r.get("unique_id") == a["id"]), None)
            if eid:
                break
            time.sleep(0.5)
        self.notiere(f"Automation „{a['alias']}“ angelegt ({eid})")
        return eid or f"automation.{slug(a['alias'])}"

    def karte(self, ziel, karte):
        if self.trocken or not ziel:
            self.notiere("Dashboard-Karte als Datei gespeichert (karte.yaml)")
            return
        cfg = self.ha.befehl("lovelace/config", url_path=ziel["url_path"])
        stempel = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        sicherung = self.ordner / f"dashboard_sicherung_{ziel['url_path'] or 'standard'}_{stempel}.json"
        sicherung.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
        view = cfg["views"][ziel["view"]]
        if ziel.get("pfad") is not None:
            dashboard_plaetze(view)  # legt fehlende Kartenlisten an
            karte_einsetzen(view, ziel["pfad"], ziel["pos"] if ziel["pfad"][:2] != ["sections", "neu"] or ziel.get("pos_gewaehlt") else None, karte)
        elif ziel["section"] == "neu":
            view.setdefault("sections", []).append({"type": "grid", "cards": [karte]})
        elif ziel["section"] is not None:
            view["sections"][ziel["section"]].setdefault("cards", []).insert(ziel["pos"], karte)
        else:
            view.setdefault("cards", []).insert(ziel["pos"], karte)
        self.ha.befehl("lovelace/config/save", url_path=ziel["url_path"], config=cfg)
        eintrag = {"url_path": ziel["url_path"], "sicherung": str(sicherung), "merkmal": ziel.get("merkmal"), "design": ziel.get("design", "glas")}
        self.rueckbau["dashboard"] = self.rueckbau.get("dashboard") or eintrag
        self.rueckbau.setdefault("dashboards", []).append(eintrag)
        self.notiere(f"Karte in Dashboard „{ziel['url_path'] or 'Standard'}“ eingefügt (Sicherung: {sicherung.name})")


def rueckbau(ha, datei):
    r = json.loads(Path(datei).read_text(encoding="utf-8"))
    print(f"Rückbau des Laufs vom {r['erstellt']}:")
    for aid in r["automationen"]:
        print("  Automation", aid)
    for h in r["helfer"]:
        print("  Helfer", h["entity_id"])
    if r.get("dashboard"):
        print("  Dashboard", r["dashboard"]["url_path"] or "Standard", "wird aus der Sicherung wiederhergestellt (spätere Dashboard-Änderungen gehen verloren!)")
    if input("Wirklich entfernen? Zum Bestätigen JA eingeben: ").strip() != "JA":
        print("Abgebrochen.")
        return
    for aid in r["automationen"]:
        ha.rest("DELETE", f"/api/config/automation/config/{aid}")
    for h in r["helfer"]:
        ha.befehl(f"{h['domain']}/delete", **{f"{h['domain']}_id": h["id"]})
    if r.get("dashboard"):
        cfg = json.loads(Path(r["dashboard"]["sicherung"]).read_text(encoding="utf-8"))
        ha.befehl("lovelace/config/save", url_path=r["dashboard"]["url_path"], config=cfg)
    print("Rückbau abgeschlossen. Installierte Blueprints bleiben erhalten (werden ggf. von anderen Räumen genutzt).")


def alt_geraete(a):
    """Geräte des Raums für die Suche nach der alten Steuerung: (Geräteliste, IR-Gerätename oder None, alter Fenster-Helfer oder None).

    Der alte Fenster-Helfer zählt nur, wenn der Raum wieder eigene Kontakte bekommt und kein anderes Better Thermostat ihn mitbenutzt."""
    fa = a.get("fenster_alt") or {}
    fenster = fa.get("helfer") if fa.get("helfer") and not fa.get("geteilt") and a.get("fenster_modus") == "eigen" else None
    if not a.get("klima"):
        return [a["bt"]], None, fenster
    if a.get("klima_art") == "schalter":
        return [a["bt"], a.get("klima_schalter")], None, fenster
    return [a["bt"], a.get("klima_sender")], a.get("ir_geraet"), fenster


def bt_fremdnutzung(ha, a):
    """Eingeschaltete Automationen, die das Better Thermostat des Raums bereits verwenden – ohne die eigene und ohne die alte
    Steuerung, die bei der Einrichtung abgeschaltet wird."""
    try:
        rel = ha.befehl("search/related", item_type="entity", item_id=a["bt"]) or {}
        zustand = {z["entity_id"]: z["state"] for z in ha.befehl("get_states") if z["entity_id"].startswith("automation.")}
    except HAFehler:
        return []
    abschalten = set((a.get("alt") or {}).get("abschalten") or [])
    return [x for x in rel.get("automation", []) if not x.startswith(f"automation.heizung_{slug(a['raum_name'])}")
            and x not in abschalten and zustand.get(x) != "off"]


def einrichten(ha, a, ziel, ordner, betriebsart=None):
    """Legt einen Raum vollständig an (Blueprints, Helfer, Automationen, Karte). Ohne Rückfragen; für die Integration.

    Rückgabe: {"rueckbau": …, "log": […], "betriebsart": …, "automationen": {rolle: entity_id}, "hinweise": […]}.
    Bei einem Fehler wird alles bereits Angelegte wieder entfernt und die Ausnahme weitergereicht.
    """
    b = Bestand(ha.befehl("get_states"), ha.befehl("config/entity_registry/list"))
    plan = plane(a, b, None)
    if plan["konflikte"]:
        raise HAFehler("Diese Helfer existieren bereits: " + ", ".join(plan["konflikte"]) + ". Bitte einen anderen Raumnamen wählen.")
    if betriebsart is None:
        betriebsart = "test" if bt_fremdnutzung(ha, a) else "produktiv"
    for au in plan["automationen"]:
        if au["rolle"] in ("raumheizung", "klima"):
            au["use_blueprint"]["input"]["ausgabe_modus"] = betriebsart
    alt = a.get("alt") or {}
    altdaten = al.sammeln(ha) if alt.get("abschalten") or alt.get("helfer") else None
    if altdaten:
        laeuft = al.einstufen(altdaten, *alt_geraete(a))["pv_laeuft"]
        if laeuft:
            raise AltPVLaeuft("Das alte PV-Heizen läuft gerade (" + ", ".join(laeuft) + "). Bitte erst beenden lassen, dann den Raum anlegen.")
    x = Ausfuehrung(ha, Path(ordner), False)
    x.leise = True
    altprotokoll = None
    hinweise = []  # für die Abschlussmeldung (z. B. gewählte alte Karte nicht gefunden)
    try:
        x.blueprints(None, [au["use_blueprint"]["path"] for au in plan["automationen"]])
        x.helfer(plan["helfer"])
        if altdaten:  # alte Steuerung abschalten und kennzeichnen, bevor die neue Automation startet
            altprotokoll = al.abschalten(ha, altdaten, alt.get("abschalten") or [], alt.get("helfer") or [])
            x.rueckbau["alt"] = altprotokoll
            x.notiere(f"Alte Steuerung abgeschaltet: {len(altprotokoll['automationen'])} Automationen, {len(altprotokoll['skripte'])} Skripte, "
                      f"{len(altprotokoll['helfer'])} Helfer gekennzeichnet")
        ids = {}
        for au in plan["automationen"]:
            inp = au["use_blueprint"]["input"]
            if au["rolle"] == "pv":
                inp["raumheizung_automation"] = ids["raumheizung"]
                inp["klima_automation"] = ids["klima"]
            ids[au["rolle"]] = x.automation(au)
        kl = next((au for au in plan["automationen"] if au["rolle"] == "klima"), None)
        if "pv" in ids and kl and kl["use_blueprint"]["input"].get("pv_automation") != ids["pv"]:
            kl["use_blueprint"]["input"]["pv_automation"] = ids["pv"]
            ha.rest("POST", f"/api/config/automation/config/{kl['id']}", {k: v for k, v in kl.items() if k != "rolle"})
            x.notiere("Klimaautomatik mit der PV-Automation verknüpft")
        if altprotokoll is not None and alt.get("umstellen"):
            karte_alt_neu = al.zuordnung(alt.get("helfer") or [], altdaten["zustaende"], plan["entitaeten"])
            altprotokoll["karte"] = karte_alt_neu
            altprotokoll["abhaengig"] = al.umstellen(ha, altdaten, alt.get("abhaengig") or [], karte_alt_neu)
            if altprotokoll["abhaengig"]:
                x.notiere(f"{len(altprotokoll['abhaengig'])} abhängige Automationen/Skripte auf die neuen Helfer umgestellt")
        for z in ([ziel] if isinstance(ziel, dict) else (ziel or [])):  # eine oder mehrere Platzierungen, jede im Design ihres Dashboards
            x.karte(dict(z, merkmal=plan["entitaeten"]["status"]), raumkarte(plan["kartenhelfer"], z.get("design", "glas")))
    except Exception:
        if altprotokoll is not None:
            al.wiederherstellen(ha, altprotokoll)
        x.rueckbau.pop("alt", None)
        rueckbau_ausfuehren(ha, x.rueckbau)
        raise
    if a.get("alte_karten"):  # zuletzt: gewählte alte Dashboard-Karten entfernen (Dashboards vorher gesichert)
        try:
            kandidaten = alte_karten_suchen(ha, a, a.get("alt"), {a["key"]: {"status": plan["entitaeten"]["status"], "bt": a["bt"]}})
            gewaehlt = [k for k in kandidaten if k["id"] in a["alte_karten"]]
            protokoll, fehler = alte_karten_entfernen(ha, gewaehlt, ordner)
            namen = dict(zip(a["alte_karten"], a.get("alte_karten_namen") or []))
            gefunden = {k["id"] for k in kandidaten}
            fehler += [f"„{namen.get(i) or i.split('|')[0]}“ nicht mehr gefunden – unverändert" for i in a["alte_karten"] if i not in gefunden]
            x.rueckbau["alte_karten"] = protokoll
            x.notiere(f"{len(protokoll)} alte Dashboard-Karten entfernt" + (f" ({'; '.join(fehler)})" if fehler else ""))
            if fehler:
                hinweise.append("Nicht alle gewählten alten Dashboard-Karten wurden entfernt:\n" + "\n".join(f"- {f}" for f in fehler)
                                + "\nBitte unter „Konfigurieren → Alte Dashboard-Karten entfernen“ prüfen.")
        except HAFehler as ex:
            x.notiere(f"Alte Dashboard-Karten nicht entfernt: {ex}")
            hinweise.append(f"Alte Dashboard-Karten nicht entfernt: {ex}")
    x.rueckbau["karte"] = plan["karte"]
    x.rueckbau["kartenhelfer"] = plan["kartenhelfer"]
    x.rueckbau["entitaeten"] = plan["entitaeten"]
    x.notiere("Einrichtung abgeschlossen")
    return {"rueckbau": x.rueckbau, "log": x.log, "betriebsart": betriebsart, "automationen": ids, "hinweise": hinweise}


def rueckbau_ausfuehren(ha, r):
    """Entfernt Automationen, Helfer und die Raumkarte eines Raums (ohne Rückfrage; für die Integration). Blueprints bleiben."""
    fehler = []
    for aid in r.get("automationen", []):
        try:
            ha.rest("DELETE", f"/api/config/automation/config/{aid}")
        except HAFehler as ex:
            fehler.append(str(ex))
    for h in r.get("helfer", []):
        try:
            ha.befehl(f"{h['domain']}/delete", **{f"{h['domain']}_id": h["id"]})
        except HAFehler as ex:
            fehler.append(str(ex))
    fehler += karten_entfernen(ha, r)
    return fehler


def karten_entfernen(ha, r):
    """Entfernt die Raumkarte aus allen Dashboards, in die sie eingefügt wurde. Rückgabe: Fehlertexte."""
    fehler, erledigt = [], set()
    for db in (r.get("dashboards") or ([r["dashboard"]] if r.get("dashboard") else [])):
        if not db.get("merkmal") or db["url_path"] in erledigt:
            continue
        erledigt.add(db["url_path"])
        try:
            cfg = ha.befehl("lovelace/config", url_path=db["url_path"])
            if karte_entfernen(cfg, db["merkmal"]):
                ha.befehl("lovelace/config/save", url_path=db["url_path"], config=cfg)
        except HAFehler as ex:
            fehler.append(str(ex))
    return fehler


# ====================================================================== Alte Dashboard-Karten eines Raums
_ENTITAET_RE = re.compile(r"\b([a-z_]+\.[a-z0-9_]+)\b")
_BEHAELTER_TYPEN = ("grid", "vertical-stack", "horizontal-stack", "custom:tabdeck-card", "custom:layout-card", "custom:stack-in-card",
                    "custom:vertical-stack-in-card", "custom:swipe-card")


def alte_karten_merkmale(a, alt, registry, eintraege):
    """Welche Entitäten machen eine Karte zur alten Karte dieses Raums, welche zur Sammelkarte mehrerer Räume?

    alt: Protokoll bzw. Auswahl der alten Steuerung (Automationen, Skripte, Helfer).
    eintraege: {Raumschlüssel: {"status": Status-Helfer, "bt": Thermostat}} aller Räume dieser Integration."""
    alt = alt or {}
    raum = {a["bt"]}
    for x in alt.get("automationen", []) + alt.get("skripte", []) + alt.get("helfer", []):
        raum.add(x["entity_id"] if isinstance(x, dict) else x)
    for x in alt.get("abschalten", []):
        raum.add(x)
    bts = {e["entity_id"] for e in registry if e.get("platform") == "better_thermostat" and e["entity_id"].startswith("climate.")}
    eigen = {(eintraege.get(a["key"]) or {}).get("status")} - {None}
    fremd = (bts - {a["bt"]}) | {v.get(x) for k, v in eintraege.items() if k != a["key"] for x in ("status", "bt")}
    return raum, fremd - {None, a["bt"]}, eigen


def alte_karten_finden(cfg, raum, fremd, eigen, namen=None, anzeige=()):
    """Karten eines Dashboards, die nur zur alten Steuerung dieses Raums gehören.

    Rückgabe: [(Pfad der Kartenliste, Index, Karte)]. Sammelkarten mit anderen Räumen werden nicht genommen, sondern nach innen
    durchsucht; die neuen Raumkarten dieser Integration bleiben unberührt. Karten, die nur das Thermostat zeigen (anzeige), funktionieren
    weiter und werden nicht vorgeschlagen."""
    treffer = []

    def kinder(k):
        out = list(k.get("cards") or []) if isinstance(k.get("cards"), list) else []
        if isinstance(k.get("card"), dict):
            out.append(k["card"])
        if isinstance(k.get("tabs"), list):
            out += [t["card"] for t in k["tabs"] if isinstance(t, dict) and isinstance(t.get("card"), dict)]
        return [c for c in out if isinstance(c, dict)]

    def pruefe_liste(liste, pfad):
        for i, k in enumerate(liste):
            if not isinstance(k, dict):
                continue
            text = json.dumps(k)
            refs = set(_ENTITAET_RE.findall(text))
            if refs & eigen:
                # Die neue Raumkarte selbst bleibt unberührt. Liegt sie in einem Container neben anderen Karten (Tab, Raster, Stapel –
                # z. B. Mobil › Tab „Heizung“), wird der Container weiter durchsucht, sonst würde die alte Karte daneben übersehen.
                if any(not (set(_ENTITAET_RE.findall(json.dumps(c))) & eigen) for c in kinder(k)):
                    innen(k, pfad + [i])
                continue
            r, f = refs & raum, refs & fremd
            if r and not f and (r - set(anzeige)) and k.get("type") not in ("custom:tabdeck-card",):
                treffer.append((pfad, i, k))
            elif r:
                innen(k, pfad + [i])

    def innen(k, pfad):
        if isinstance(k.get("cards"), list):
            pruefe_liste(k["cards"], pfad + ["cards"])
        if isinstance(k.get("card"), dict):
            innen(k["card"], pfad + ["card"])
        if isinstance(k.get("tabs"), list):
            for j, tab in enumerate(k["tabs"]):
                if isinstance(tab, dict) and isinstance(tab.get("card"), dict):
                    innen(tab["card"], pfad + ["tabs", j, "card"])

    for vi, view in enumerate(cfg.get("views", [])):
        if isinstance(view.get("cards"), list):
            pruefe_liste(view["cards"], ["views", vi, "cards"])
        for si, sec in enumerate(view.get("sections") or []):
            if isinstance(sec, dict) and isinstance(sec.get("cards"), list):
                pruefe_liste(sec["cards"], ["views", vi, "sections", si, "cards"])
    return treffer


def alte_karte_ort(cfg, pfad, namen=None):
    """Lesbarer Ort einer Kartenliste: Ansicht › Bereich (wie bei der Platzierung)."""
    vi = pfad[1]
    view = json.loads(json.dumps(cfg["views"][vi]))
    titel = {tuple(p): t for p, t, _ in dashboard_plaetze(view, namen)}
    ansicht = cfg["views"][vi].get("title") or cfg["views"][vi].get("path") or f"Ansicht {vi + 1}"
    bereich = titel.get(tuple(pfad[2:]), "")
    return ansicht + (f" › {bereich}" if bereich and bereich != "Oberste Ebene der Ansicht" else "")


def alte_karten_suchen(ha, a, alt, eintraege, namen=None):
    """Sucht in allen bearbeitbaren Dashboards die alten Karten dieses Raums (nur lesend).
    Rückgabe: [{id, url_path, dashboard, ort, name, pfad, index, karte}]."""
    registry = ha.befehl("config/entity_registry/list")
    raum, fremd, eigen = alte_karten_merkmale(a, alt, registry, eintraege)
    boards = [(None, "Übersicht")] + [(b["url_path"], b.get("title") or b["url_path"]) for b in ha.befehl("lovelace/dashboards/list") if b.get("mode") == "storage"]
    out = []
    for url, titel in boards:
        try:
            cfg = ha.befehl("lovelace/config", url_path=url)
        except HAFehler:
            continue
        if not isinstance(cfg, dict):
            continue
        for pfad, i, k in alte_karten_finden(cfg, raum, fremd, eigen, namen, anzeige={a["bt"]}):
            kennung = hashlib.sha1(json.dumps(k, sort_keys=True).encode()).hexdigest()[:16]  # Inhalt, nicht Position (Positionen verschieben sich)
            out.append({"id": f"{url or '-'}|{kennung}", "url_path": url, "dashboard": titel,
                        "ort": alte_karte_ort(cfg, pfad, namen), "name": kartenname(k, namen), "pfad": pfad, "index": i, "karte": k})
    return out


def _liste_aufloesen(cfg, pfad):
    ziel = cfg
    for schritt in pfad:
        ziel = ziel[schritt]
    return ziel


def alte_karten_entfernen(ha, karten, ordner):
    """Entfernt die gewählten alten Karten (je Dashboard vorher gesichert). Rückgabe: (Protokoll zum Wiederherstellen, Fehlertexte)."""
    protokoll, fehler = [], []
    ordner = Path(ordner)
    ordner.mkdir(parents=True, exist_ok=True)
    je_board = {}
    for k in karten:
        je_board.setdefault(k["url_path"], []).append(k)
    for url, liste in je_board.items():
        try:
            cfg = ha.befehl("lovelace/config", url_path=url)
            stempel = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
            sicherung = ordner / f"dashboard_sicherung_{url or 'standard'}_{stempel}_alte_karten.json"
            sicherung.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
            for k in sorted(liste, key=lambda x: (x["pfad"], x["index"]), reverse=True):
                ziel = _liste_aufloesen(cfg, k["pfad"])
                idx = k["index"] if k["index"] < len(ziel) and ziel[k["index"]] == k["karte"] else next(
                    (j for j, x in enumerate(ziel) if x == k["karte"]), None)
                if idx is None:
                    fehler.append(f"Karte „{k['name']}“ in {k['dashboard']} nicht mehr gefunden – unverändert")
                    continue
                ziel.pop(idx)
                protokoll.append({"url_path": url, "dashboard": k["dashboard"], "pfad": k["pfad"], "index": idx, "name": k["name"],
                                  "karte": k["karte"], "sicherung": str(sicherung)})
            ha.befehl("lovelace/config/save", url_path=url, config=cfg)
        except (HAFehler, KeyError, IndexError, TypeError) as ex:
            fehler.append(f"{url or 'Übersicht'}: {ex}")
    return protokoll, fehler


def alte_karten_zurueck(ha, protokoll):
    """Setzt entfernte alte Karten wieder an ihre Stelle (in umgekehrter Reihenfolge). Rückgabe: Fehlertexte."""
    fehler, je_board = [], {}
    for k in protokoll:
        je_board.setdefault(k["url_path"], []).append(k)
    for url, liste in je_board.items():
        try:
            cfg = ha.befehl("lovelace/config", url_path=url)
            for k in sorted(liste, key=lambda x: (x["pfad"], x["index"])):
                try:
                    ziel = _liste_aufloesen(cfg, k["pfad"])
                except (KeyError, IndexError, TypeError):
                    fehler.append(f"Karte „{k['name']}“: Bereich in {k['dashboard']} gibt es nicht mehr")
                    continue
                if k["karte"] not in ziel:
                    ziel.insert(min(k["index"], len(ziel)), k["karte"])
            ha.befehl("lovelace/config/save", url_path=url, config=cfg)
        except HAFehler as ex:
            fehler.append(f"{url or 'Übersicht'}: {ex}")
    return fehler


# ====================================================================== Gerät austauschen
def _ersetzen(wert, alt, neu):
    if wert == alt:
        return neu
    if isinstance(wert, list):
        return [neu if x == alt else x for x in wert]
    return wert


def geraete_im_raum(ha, automation_ids):
    """Alle Geräte (Entitäten), die die Automationen dieses Raums verwenden – ohne die eigenen Helfer. → {entity_id: [Aliasse]}"""
    out = {}
    for aid in automation_ids:
        try:
            cfg = ha.rest("GET", f"/api/config/automation/config/{aid}")
        except HAFehler:
            continue
        for wert in ((cfg.get("use_blueprint") or {}).get("input") or {}).values():
            for x in (wert if isinstance(wert, list) else [wert]):
                if (isinstance(x, str) and re.fullmatch(r"[a-z_]+\.[a-z0-9_]+", x) and not x.split(".", 1)[1].startswith("hz_")
                        and x.split(".")[0] not in ("automation", "script")):
                    out.setdefault(x, [])
                    if cfg.get("alias") not in out[x]:
                        out[x].append(cfg.get("alias"))
    return out


STROM_SCHLUESSEL = ("klima_steckdose", "klima_leistung", "laeuft_ab_w")


def strom_setzen(ha, automation_ids, a):
    """Klima-Steckdose nachträglich einrichten, ändern oder entfernen. Zuerst werden die Blueprints Klimaautomatik (und PV-Heizen, falls
    eingerichtet) bei Bedarf auf die aktuelle Paketversion gebracht – ältere Fassungen kennen die Felder nicht –, danach die Eingaben in
    den Automationen gesetzt bzw. entfernt. Rückgabe: Aliasse der geänderten Automationen."""
    vorhanden = ha.befehl("blueprint/list", domain="automation") or {}
    for rolle in ["klima"] + (["pv"] if a.get("pv") else []):
        pfad = BP[rolle]
        beschreibung = ((vorhanden.get(pfad) or {}).get("metadata") or {}).get("description") or ""
        if f"Paketversion {PAKETVERSION} " not in beschreibung:
            text = (BP_ORDNER / Path(pfad).name).read_text(encoding="utf-8")
            if pfad in vorhanden:
                ha.befehl("blueprint/save", domain="automation", path=pfad, yaml=text, allow_override=True)
            else:
                ha.befehl("blueprint/save", domain="automation", path=pfad, yaml=text)
    neu = strom_eingaben(a)
    geaendert = []
    for aid in automation_ids:
        try:
            cfg = ha.rest("GET", f"/api/config/automation/config/{aid}")
        except HAFehler:
            continue
        inp = dict((cfg.get("use_blueprint") or {}).get("input") or {})
        ziel = {k: v for k, v in inp.items() if k not in STROM_SCHLUESSEL}
        ziel.update(neu)
        if ziel != inp:
            cfg["use_blueprint"]["input"] = ziel
            ha.rest("POST", f"/api/config/automation/config/{aid}", cfg)
            geaendert.append(cfg.get("alias") or aid)
    return geaendert


def geraet_tauschen(ha, automation_ids, alt, neu):
    """Ersetzt eine Entität in allen Automationen dieses Raums (Blueprint-Eingaben). Rückgabe: Aliasse der geänderten Automationen."""
    geaendert = []
    for aid in automation_ids:
        cfg = ha.rest("GET", f"/api/config/automation/config/{aid}")
        inp = (cfg.get("use_blueprint") or {}).get("input") or {}
        neu_inp = {k: _ersetzen(v, alt, neu) for k, v in inp.items()}
        if neu_inp != inp:
            cfg["use_blueprint"]["input"] = neu_inp
            ha.rest("POST", f"/api/config/automation/config/{aid}", cfg)
            geaendert.append(cfg.get("alias"))
    return geaendert


def a_tauschen(a, alt, neu):
    """Dieselbe Ersetzung in den gespeicherten Eingaben des Raums (für spätere Änderungen)."""
    return {k: _ersetzen(v, alt, neu) for k, v in a.items()}


# ====================================================================== Funktionen nachträglich ändern
def _dreiwege(basis, aktuell, neu):
    """Blueprint-Eingaben abgleichen: Was die Funktionsänderung betrifft, kommt aus „neu“; was der Nutzer seit der Einrichtung in der
    Blueprint-Instanz selbst geändert hat (Geräte, Zeiten, Temperaturen …), bleibt erhalten. basis = Plan vor der Änderung."""
    out = {}
    for k in set(aktuell) | set(neu):
        if k in neu:
            out[k] = aktuell[k] if (k in aktuell and k in basis and neu[k] == basis[k]) else neu[k]
        elif k not in basis:
            out[k] = aktuell[k]  # vom Nutzer selbst ergänzt (z. B. Fenster-Verzögerung) oder Betriebsart
    return out


def karte_ersetzen(cfg, merkmal, erzeuge):
    """Ersetzt die Raumkarte(n) mit diesem Status-Helfer an Ort und Stelle. erzeuge(alte_karte) → neue Karte. Rückgabe: Anzahl."""
    anzahl = 0

    def lauf(c):
        nonlocal anzahl
        if isinstance(c, dict):
            for k, v in list(c.items()):
                if k == "cards" and isinstance(v, list):
                    for i, x in enumerate(v):
                        if isinstance(x, dict) and x.get("type") == "custom:mod-card" and merkmal in json.dumps(x):
                            v[i] = erzeuge(x)
                            anzahl += 1
                lauf(v)
        elif isinstance(c, list):
            for x in c:
                lauf(x)

    lauf(cfg)
    return anzahl


def karten_design(karte):
    """Design einer vorhandenen Raumkarte dieser Integration erkennen."""
    t = json.dumps(karte)
    return "mobil" if "23px 22px" in t else "verlauf" if "#151e2d" in t else "glas"


def aenderung_planen(ha, a_alt, a_neu, r):
    """Vergleicht die Pläne vor und nach der Funktionsänderung (nur lesend)."""
    b = Bestand(ha.befehl("get_states"), ha.befehl("config/entity_registry/list"))
    p_alt, p_neu = plane(a_alt, b, None), plane(a_neu, b, None)
    alt_h = {x["entity_id"]: x for x in p_alt["helfer"]}
    neu_h = {x["entity_id"]: x for x in p_neu["helfer"]}
    eigene = {h["entity_id"] for h in r.get("helfer", [])}
    helfer_neu = [x for e, x in neu_h.items() if e not in alt_h]
    alt_a = {x["rolle"]: x for x in p_alt["automationen"]}
    neu_a = {x["rolle"]: x for x in p_neu["automationen"]}
    return {
        "plan_alt": p_alt, "plan_neu": p_neu,
        "helfer_neu": helfer_neu,
        "helfer_weg": [alt_h[e] for e in alt_h if e not in neu_h and e in eigene],
        "helfer_anders": [neu_h[e] for e in neu_h if e in alt_h and e in eigene and neu_h[e]["daten"] != alt_h[e]["daten"]],
        "konflikte": [x["entity_id"] for x in helfer_neu if b.existiert(x["entity_id"]) and x["entity_id"] not in eigene],
        "autos_neu": [neu_a[k] for k in neu_a if k not in alt_a],
        "autos_weg": [alt_a[k] for k in alt_a if k not in neu_a],
        "autos_anders": [neu_a[k] for k in neu_a if k in alt_a and neu_a[k]["use_blueprint"]["path"] == alt_a[k]["use_blueprint"]["path"]
                         and neu_a[k]["use_blueprint"]["input"] != alt_a[k]["use_blueprint"]["input"]],
        "autos_ersetzt": [neu_a[k] for k in neu_a if k in alt_a and neu_a[k]["use_blueprint"]["path"] != alt_a[k]["use_blueprint"]["path"]],
        "karte_anders": p_neu["kartenhelfer"] != p_alt["kartenhelfer"],
    }


def aendern(ha, a_alt, a_neu, r, ordner, ids_alt):
    """Funktionen eines bestehenden Raums ändern, ohne ihn neu anzulegen.

    Fehlende Helfer und Automationen werden angelegt, geänderte Helfer angepasst, die Blueprint-Instanzen im Dreiwege-Abgleich
    aktualisiert (eigene Änderungen des Nutzers bleiben), die Raumkarten an Ort und Stelle erneuert; zuletzt werden nicht mehr
    benötigte Automationen und Helfer gelöscht. Schlägt vorher etwas fehl, wird der vorige Stand wiederhergestellt.
    Rückgabe: {"rueckbau": …, "automationen": {rolle: entity_id}, "fehler": […], "log": […]}."""
    pl = aenderung_planen(ha, a_alt, a_neu, r)
    if pl["konflikte"]:
        raise HAFehler("Diese Helfer existieren bereits (nicht von diesem Raum): " + ", ".join(pl["konflikte"]))
    x = Ausfuehrung(ha, Path(ordner), False)
    x.leise = True
    x.rueckbau = json.loads(json.dumps(r))
    x.rueckbau.setdefault("helfer", [])
    x.rueckbau.setdefault("automationen", [])
    uid = {h["entity_id"]: h for h in x.rueckbau["helfer"]}
    alt_daten = {h["entity_id"]: h["daten"] for h in pl["plan_alt"]["helfer"]}
    originale, autos_neu, helfer_geaendert = {}, [], []
    vorher = len(x.rueckbau["helfer"])
    ids = dict(ids_alt or {})
    try:
        if pl["autos_neu"]:
            x.blueprints(None, [au["use_blueprint"]["path"] for au in pl["autos_neu"] + pl["autos_ersetzt"]])
        x.helfer(pl["helfer_neu"])
        for h in pl["helfer_anders"]:  # z. B. Heizprofil mit neuem Profil, Boost-Dauer
            ha.befehl(f"{h['domain']}/update", **{f"{h['domain']}_id": uid[h["entity_id"]]["id"]}, **h["daten"])
            helfer_geaendert.append(h)
            x.notiere(f"Helfer {h['entity_id']} angepasst")
        alt_a = {au["rolle"]: au for au in pl["plan_alt"]["automationen"]}
        betrieb = None
        for au in pl["plan_neu"]["automationen"]:
            inp = au["use_blueprint"]["input"]
            ersetzt = au["rolle"] in alt_a and alt_a[au["rolle"]]["use_blueprint"]["path"] != au["use_blueprint"]["path"]
            if ersetzt and au["id"] in x.rueckbau["automationen"]:  # z. B. Klima von IR auf Steckdose: ganz neu schreiben, Betriebsart behalten
                cfg = ha.rest("GET", f"/api/config/automation/config/{au['id']}")
                originale[au["id"]] = json.loads(json.dumps(cfg))
                inp["ausgabe_modus"] = cfg["use_blueprint"]["input"].get("ausgabe_modus") or betrieb or "produktiv"
                ha.rest("POST", f"/api/config/automation/config/{au['id']}", {k: v for k, v in au.items() if k != "rolle"})
                x.notiere(f"Automation „{au['alias']}“ auf ein anderes Blueprint umgestellt")
                ids.setdefault(au["rolle"], f"automation.{slug(au['alias'])}")
                continue
            if au["rolle"] in alt_a and au["id"] in x.rueckbau["automationen"]:
                cfg = ha.rest("GET", f"/api/config/automation/config/{au['id']}")
                originale[au["id"]] = json.loads(json.dumps(cfg))
                if au["rolle"] == "raumheizung":
                    betrieb = cfg["use_blueprint"]["input"].get("ausgabe_modus")
                neu_inp = _dreiwege(alt_a[au["rolle"]]["use_blueprint"]["input"], cfg["use_blueprint"]["input"], inp)
                if neu_inp != cfg["use_blueprint"]["input"]:
                    cfg["use_blueprint"]["input"] = neu_inp
                    ha.rest("POST", f"/api/config/automation/config/{au['id']}", cfg)
                    x.notiere(f"Automation „{cfg.get('alias')}“ angepasst")
                ids.setdefault(au["rolle"], f"automation.{slug(au['alias'])}")
                continue
            if au["rolle"] in ("raumheizung", "klima"):
                inp["ausgabe_modus"] = betrieb or "produktiv"
            if au["rolle"] == "pv":
                inp["raumheizung_automation"] = ids.get("raumheizung", inp["raumheizung_automation"])
                inp["klima_automation"] = ids.get("klima", inp["klima_automation"])
            ids[au["rolle"]] = x.automation(au)
            autos_neu.append(au["id"])
        kl = next((au for au in pl["plan_neu"]["automationen"] if au["rolle"] == "klima"), None)
        if "pv" in ids and kl:  # Klimaautomatik mit der PV-Automation verknüpfen (wie bei der Einrichtung)
            cfg = ha.rest("GET", f"/api/config/automation/config/{kl['id']}")
            if cfg["use_blueprint"]["input"].get("pv_automation") != ids["pv"]:
                originale.setdefault(kl["id"], json.loads(json.dumps(cfg)))
                cfg["use_blueprint"]["input"]["pv_automation"] = ids["pv"]
                ha.rest("POST", f"/api/config/automation/config/{kl['id']}", cfg)
        kh = pl["plan_neu"]["kartenhelfer"]
        merkmal = pl["plan_neu"]["entitaeten"]["status"]
        erledigt = set()
        for db in x.rueckbau.get("dashboards") or ([x.rueckbau["dashboard"]] if x.rueckbau.get("dashboard") else []):
            if db.get("url_path", "-") in erledigt:
                continue
            erledigt.add(db.get("url_path", "-"))
            cfg = ha.befehl("lovelace/config", url_path=db["url_path"])
            stempel = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
            sicherung = x.ordner / f"dashboard_sicherung_{db['url_path'] or 'standard'}_{stempel}.json"
            x.ordner.mkdir(parents=True, exist_ok=True)
            sicherung.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
            if karte_ersetzen(cfg, merkmal, lambda alte: raumkarte(kh, karten_design(alte))):
                ha.befehl("lovelace/config/save", url_path=db["url_path"], config=cfg)
                x.notiere(f"Karte in Dashboard „{db['url_path'] or 'Standard'}“ erneuert (Sicherung: {sicherung.name})")
    except Exception:
        for aid, cfg in originale.items():
            try:
                ha.rest("POST", f"/api/config/automation/config/{aid}", cfg)
            except HAFehler:
                pass
        for aid in autos_neu:
            try:
                ha.rest("DELETE", f"/api/config/automation/config/{aid}")
            except HAFehler:
                pass
        for h in x.rueckbau["helfer"][vorher:]:
            try:
                ha.befehl(f"{h['domain']}/delete", **{f"{h['domain']}_id": h["id"]})
            except HAFehler:
                pass
        for h in helfer_geaendert:
            try:
                ha.befehl(f"{h['domain']}/update", **{f"{h['domain']}_id": uid[h["entity_id"]]["id"]}, **alt_daten[h["entity_id"]])
            except HAFehler:
                pass
        raise
    fehler = []
    for au in pl["autos_weg"]:  # zuletzt: nicht mehr benötigte Automationen und Helfer löschen
        try:
            ha.rest("DELETE", f"/api/config/automation/config/{au['id']}")
            x.notiere(f"Automation „{au['alias']}“ gelöscht")
        except HAFehler as ex:
            fehler.append(str(ex))
        if au["id"] in x.rueckbau["automationen"]:
            x.rueckbau["automationen"].remove(au["id"])
        ids.pop(au["rolle"], None)
    for h in pl["helfer_weg"]:
        try:
            ha.befehl(f"{h['domain']}/delete", **{f"{h['domain']}_id": uid[h["entity_id"]]["id"]})
            x.notiere(f"Helfer {h['entity_id']} gelöscht")
        except HAFehler as ex:
            fehler.append(str(ex))
        x.rueckbau["helfer"] = [y for y in x.rueckbau["helfer"] if y["entity_id"] != h["entity_id"]]
    x.rueckbau.update(kartenhelfer=pl["plan_neu"]["kartenhelfer"], entitaeten=pl["plan_neu"]["entitaeten"], karte=pl["plan_neu"]["karte"])
    x.notiere("Funktionen geändert")
    return {"rueckbau": x.rueckbau, "automationen": ids, "fehler": fehler, "log": x.log}


# ====================================================================== Hauptprogramm
def main():
    ap = argparse.ArgumentParser(description="Einrichtungsassistent Universelle Raumheizungssteuerung")
    ap.add_argument("--trockenlauf", action="store_true", help="nichts in Home Assistant schreiben")
    ap.add_argument("--antworten", help="Antworten aus JSON-Datei")
    ap.add_argument("--offline", help="Entitätsbestand aus JSON-Datei (impliziert --trockenlauf)")
    ap.add_argument("--rueckbau", help="Rückbau-Datei eines früheren Laufs")
    ap.add_argument("--ausgabe", help="Ausgabeordner", default=str(PROJEKT / "ausgabe"))
    args = ap.parse_args()

    print("Universelle Raumheizungssteuerung – Einrichtungsassistent\n")
    ha = None
    if not args.offline:
        url = os.environ.get("HA_URL") or input("Home-Assistant-Adresse (z. B. http://homeassistant.local:8123): ").strip()
        token = os.environ.get("HA_TOKEN") or getpass.getpass("Langlebiges Zugriffstoken (wird nicht gespeichert): ")
        ha = HAVerbindung(url, token)
        print("  Verbunden mit Home Assistant", ha.verbinden())
    if args.rueckbau:
        rueckbau(ha, args.rueckbau)
        return

    trocken = args.trockenlauf or bool(args.offline)
    antworten = json.loads(Path(args.antworten).read_text(encoding="utf-8")) if args.antworten else None
    d = Dialog(antworten)
    if args.offline:
        snap = json.loads(Path(args.offline).read_text(encoding="utf-8"))
        b = Bestand(snap["states"], snap.get("registry", []))
    else:
        b = Bestand(ha.befehl("get_states"), ha.befehl("config/entity_registry/list"))

    a = fragen(d, b)
    plan = plane(a, b, d)
    ordner = Path(args.ausgabe) / a["key"]
    ordner.mkdir(parents=True, exist_ok=True)

    # Sicherheitsprüfung: Steuert bereits eine andere Automation dieses Better Thermostat?
    fremd = []
    if ha:
        try:
            rel = ha.befehl("search/related", item_type="entity", item_id=a["bt"]) or {}
            fremd = [x for x in rel.get("automation", []) if not x.startswith(f"automation.heizung_{slug(a['raum_name'])}")]
        except HAFehler:
            fremd = []
    elif "bt_fremd" in (antworten or {}):
        fremd = antworten["bt_fremd"]
    betriebsart = "produktiv"
    if fremd:
        print("\n  ⚠ Das Better Thermostat wird bereits von diesen Automationen verwendet:")
        for f in fremd:
            print("     –", f, f"({b.name(f)})")
        print("    Damit es keine zwei Sollwertschreiber gibt, wird die neue Automation im TESTBETRIEB angelegt (berechnet nur, sendet nichts).")
        print("    Umschalten auf Normalbetrieb erst, nachdem Sie die alte Automation selbst deaktiviert haben (Blueprint-Abschnitt „Erweitert“).")
        betriebsart = "test"
    for au in plan["automationen"]:
        if au["rolle"] in ("raumheizung", "klima"):
            au["use_blueprint"]["input"]["ausgabe_modus"] = betriebsart
    if plan["konflikte"]:
        print("\n  ✘ Diese Helfer-IDs existieren bereits:", ", ".join(plan["konflikte"]))
        print("    Bitte eine andere Raumkennung wählen. Es wurde nichts verändert.")
        sys.exit(2)

    ziel = None if trocken else dashboard_ziel(d, ha)

    # Dateien immer schreiben (Nachvollziehbarkeit)
    (ordner / "karte.yaml").write_text("# Dashboard-Karte (Raw-Editor: als Karte einfügen)\n" + dump(plan["karte"]), encoding="utf-8")
    for au in plan["automationen"]:
        (ordner / f"automation_{au['rolle']}.yaml").write_text(dump({k: v for k, v in au.items() if k != "rolle"}), encoding="utf-8")
    (ordner / "antworten.json").write_text(json.dumps(d.protokoll, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== Zusammenfassung ===")
    print(f"  Raum: {a['raum_name']} (Kennung {a['key']}) · Better Thermostat {a['bt']}")
    print(f"  Funktionen: Fenster {a['fenster_modus']} · Boost {'ja' if a['boost'] else 'nein'} · Vorheizen {'ja' if a['vorheizen'] else 'nein'}"
          f" · Klima {'ja' if a['klima'] else 'nein'} · PV {'ja' if a['pv'] else 'nein'} · Betriebsart {betriebsart}")
    vh_liste = [f"{pn} {ph['gruppe']} Phase {ph['nr']} (mind. {ph['vh_temp']} °C bis {ph['vh_bis'][:5]})" for pn, pp in a["profile"].items()
                for ph in pp["phasen"] if ph.get("vh")]
    if a["vorheizen"]:
        print("  Vorheizen:", ", ".join(vh_liste) if vh_liste else "eingeschaltet, aber für keine Heizphase gewählt (später in der Blueprint einstellbar)")
    print(f"  Neue Helfer ({len(plan['helfer'])}):", ", ".join(x["entity_id"] for x in plan["helfer"]))
    print("  Neue Automationen:", ", ".join(x["alias"] for x in plan["automationen"]))
    print("  Karte:", f"Dashboard {ziel['url_path'] or 'Standard'}, Ansicht {ziel['view'] + 1}" if ziel else "nur Datei")
    print(f"  Dateien: {ordner}")
    if a["fenster_reaktion"] == "bt" and a["fenster_modus"] != "ohne":
        print("  Hinweis: In den Better-Thermostat-Optionen muss der Fensterstatus-Helfer als Fenstersensor eingetragen sein.")
    if trocken:
        print("\nTrockenlauf: In Home Assistant wurde nichts verändert.")
        Ausfuehrung(ha, ordner, True)
        return
    if input("\nJetzt in Home Assistant anlegen? Zum Bestätigen JA eingeben: ").strip() != "JA":
        print("Abgebrochen – nichts verändert. Die Dateien liegen im Ausgabeordner.")
        return

    x = Ausfuehrung(ha, ordner, False)
    try:
        x.blueprints(d, [au["rolle"] for au in plan["automationen"]])
        x.helfer(plan["helfer"])
        ids = {}
        for au in plan["automationen"]:
            inp = au["use_blueprint"]["input"]
            if au["rolle"] == "pv":  # tatsächliche IDs der zuvor angelegten Automationen eintragen
                inp["raumheizung_automation"] = ids["raumheizung"]
                inp["klima_automation"] = ids["klima"]
            ids[au["rolle"]] = x.automation(au)
        kl = next((au for au in plan["automationen"] if au["rolle"] == "klima"), None)
        if "pv" in ids and kl and kl["use_blueprint"]["input"].get("pv_automation") != ids["pv"]:
            kl["use_blueprint"]["input"]["pv_automation"] = ids["pv"]
            x.ha.rest("POST", f"/api/config/automation/config/{kl['id']}", {k: v for k, v in kl.items() if k != "rolle"})
            x.notiere("Klimaautomatik mit der PV-Automation verknüpft")
        x.karte(ziel, plan["karte"])
    except (HAFehler, OSError) as fehler:
        print(f"\n✘ Fehler: {fehler}\n  Bereits angelegte Komponenten stehen in {ordner / 'rueckbau.json'} – Rückbau mit --rueckbau möglich.")
        sys.exit(1)
    print(f"\nFertig. Rückbau bei Bedarf: python3 assistent/raumassistent.py --rueckbau \"{ordner / 'rueckbau.json'}\"")


if __name__ == "__main__":
    main()
