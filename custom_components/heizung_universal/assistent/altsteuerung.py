"""Alte Steuerung eines Raums finden, abschalten und kennzeichnen, später wiederherstellen oder endgültig löschen.

Ausgangspunkt sind die Geräte des Raums (Better Thermostat, Klima-Sender). Gefunden wird, was die bisherige Heizungs-, Klima- und
PV-Steuerung dieses Raums ausmacht – und nur das:

  kern       Automationen/Skripte, die ein Gerät des Raums direkt verwenden (beim Klima-Sender nur Befehle an das Klima-Gerät)
  trabant    Automationen/Skripte, die ausschließlich mit der Raumsteuerung arbeiten (z. B. „Schlafzimmer Komfort“, Boost-Ende)
  helfer     Helfer, die Kern oder Trabanten verwenden – ohne globale Helfer anderer Räume (z. B. „Heizung Aus“-Schalter)
  abhaengig  andere Funktionen, die Raum-Helfer lesen oder schalten (Rollladen, Mittagsschlaf, PV-Assistent …) – bleiben an
  gemeinsam  Automationen/Skripte, die auch das Better Thermostat anderer Räume steuern (z. B. „Heizung Aus“) – bleiben unverändert

Abschalten: Automationen werden ausgeschaltet, Skripte deaktiviert (nicht mehr aufrufbar), beide bekommen „ (alt)“ im Namen; Helfer
bekommen „ (alt)“ im Anzeigenamen. Entitäts-IDs bleiben unverändert, damit das Wiederherstellen einfach ist. Abhängige können
auf die neuen Helfer umgestellt werden, wenn es einen gleichwertigen neuen Helfer gibt (gleiche Auswahlwerte bzw. gleicher Typ).
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

try:
    from .ha_verbindung import HAFehler
except ImportError:  # Kommandozeile / Tests
    from ha_verbindung import HAFehler  # type: ignore

HELFER = ("input_select", "input_number", "input_boolean", "input_text", "input_datetime", "input_button", "timer", "schedule", "counter")
NEUTRAL = ("sensor", "binary_sensor", "weather", "sun", "zone", "person")
ZUSATZ = " (alt)"
_ENTITAET = re.compile(r"\b([a-z_]+\.[a-z0-9_]+)\b")
_IR_GERAET = re.compile(r'"device":\s*"([^"]+)"')
_PV_LAEUFT = ("pv_regelung_aktiv", "pv_heizbefehl_aktiv", "pv_ir_auftrag_offen", "pv_startvorbereitung")


def _dom(eid):
    return eid.split(".", 1)[0]


# ---------------------------------------------------------------------------------------------------------------- Daten sammeln
def sammeln(ha):
    """Liest Registry, Zustände und die Konfiguration aller UI-Automationen und -Skripte (nur lesend)."""
    reg = ha.befehl("config/entity_registry/list")
    zustaende = ha.befehl("get_states")
    autos, skripte = {}, {}
    for e in reg:
        if e.get("platform") == "automation" and e.get("unique_id") and e["entity_id"].startswith("automation."):
            try:
                cfg = ha.rest("GET", f"/api/config/automation/config/{e['unique_id']}")
            except HAFehler:
                continue
            if isinstance(cfg, dict):
                autos[e["entity_id"]] = {"id": e["unique_id"], "config": cfg}
        elif e.get("platform") == "script" and e["entity_id"].startswith("script."):
            oid = e.get("unique_id") or e["entity_id"].split(".", 1)[1]
            try:
                cfg = ha.rest("GET", f"/api/config/script/config/{oid}")
            except HAFehler:
                continue
            if isinstance(cfg, dict):
                skripte[e["entity_id"]] = {"id": oid, "config": cfg}
    return {"registry": reg, "zustaende": {z["entity_id"]: z for z in zustaende}, "autos": autos, "skripte": skripte}


# ---------------------------------------------------------------------------------------------------------------- Einstufen
def schreibt(cfg, helfer):
    """Schaltet diese Automation den Helfer (input_boolean.turn_on/turn_off bzw. eine Vorlage dafür mit diesem Ziel)?"""
    gefunden = False

    def lauf(x):
        nonlocal gefunden
        if gefunden:
            return
        if isinstance(x, dict):
            akt = str(x.get("action") or x.get("service") or "")
            ziel = x.get("target") if isinstance(x.get("target"), dict) else {}
            ids = ziel.get("entity_id") or x.get("entity_id") or ((x.get("data") or {}).get("entity_id") if isinstance(x.get("data"), dict) else None)
            ids = ids if isinstance(ids, list) else [ids]
            if "input_boolean" in akt and helfer in ids:
                gefunden = True
                return
            for v in x.values():
                lauf(v)
        elif isinstance(x, list):
            for v in x:
                lauf(v)

    lauf(cfg)
    return gefunden


def fenster_vorlage(daten, fenster_alt):
    """Fensterkontakte und Klima/PV-Ausnahmen aus der alten Steuerung lesen (nur lesend).

    fenster_alt: Fensterstatus-Helfer, den Better Thermostat heute als Fenstersensor hat. Seine Schreiber (der alte Fail-safe) nennen die
    Kontakte des Raums (Gruppen werden in ihre Mitglieder aufgelöst). Ausnahmen = Kontakte, die die alte Klimaautomatik nicht beachtet
    (Beispiel: Klima nutzt „Fenster alle“ = links + rechts, die Balkontür nicht)."""
    zust = daten["zustaende"]

    def aufloesen(eids):
        out = []
        for x in eids:
            mitglieder = (zust.get(x) or {}).get("attributes", {}).get("entity_id")
            for y in (mitglieder if isinstance(mitglieder, list) else [x]):
                if y.startswith("binary_sensor.") and y not in out:
                    out.append(y)
        return out

    schreiber = [eid for eid, e in daten["autos"].items() if not str(e["id"]).startswith("hz_") and schreibt(e["config"], fenster_alt)]
    kontakte = aufloesen([x for eid in schreiber for x in _ENTITAET.findall(json.dumps(daten["autos"][eid]["config"])) if x.startswith("binary_sensor.")])
    klima = set()
    for eid, e in daten["autos"].items():
        if eid in schreiber or str(e["id"]).startswith("hz_") or "klima" not in (e["config"].get("alias") or "").lower():
            continue
        refs = aufloesen([x for x in _ENTITAET.findall(json.dumps(e["config"])) if x.startswith("binary_sensor.")])
        if set(refs) & set(kontakte):
            klima |= set(refs)
    ausnahmen = [k for k in kontakte if klima and k not in klima]
    return {"kontakte": kontakte, "ausnahmen": ausnahmen, "schreiber": schreiber}


def einstufen(daten, geraete, ir_geraet=None, fenster_alt=None):
    """Reine Funktion: ordnet Automationen, Skripte und Helfer der alten Steuerung zu (siehe Modulbeschreibung).

    fenster_alt: bisheriger Fensterstatus-Helfer des Better Thermostat – wer ihn schreibt (alter Fail-safe), gehört zur alten Steuerung."""
    reg = daten["registry"]
    bekannt = {e["entity_id"] for e in reg} | set(daten["zustaende"])
    bt_alle = {e["entity_id"] for e in reg if e.get("platform") == "better_thermostat" and e["entity_id"].startswith("climate.")}
    # auch die Thermostate der Räume dieser Integration gelten als Raumthermostate (falls sie nicht von Better Thermostat stammen)
    bt_alle |= {((e["config"].get("use_blueprint") or {}).get("input") or {}).get("better_thermostat") for eid, e in daten["autos"].items()
                if str(e["id"]).startswith("hz_")} - {None}
    geraete = {g for g in geraete if g}
    bt_alle |= {g for g in geraete if _dom(g) == "climate"}  # das Thermostat dieses Raums, auch wenn es (noch) nicht von Better Thermostat stammt
    sender = {g for g in geraete if _dom(g) == "remote"}
    elemente = {**{k: v for k, v in daten["autos"].items()}, **{k: v for k, v in daten["skripte"].items()}}
    verweise, ir_namen, namen = {}, {}, {}
    for eid, e in elemente.items():
        text = json.dumps(e["config"], ensure_ascii=False)
        verweise[eid] = {x for x in _ENTITAET.findall(text) if x in bekannt} - {eid}
        ir_namen[eid] = set(_IR_GERAET.findall(text))
        namen[eid] = e["config"].get("alias") or eid
    eigene = {eid for eid, e in daten["autos"].items() if str(e["id"]).startswith("hz_")}
    wer_nutzt = {}
    for item, refs in verweise.items():
        for r in refs:
            wer_nutzt.setdefault(r, set()).add(item)
    fremde_bt = bt_alle - geraete
    gemeinsam = {i for i, r in verweise.items() if r & fremde_bt} - eigene

    def fremdes_ir(i):  # verwendet den Klima-Sender, aber für ein anderes IR-Gerät (z. B. Fernseher)
        return bool(verweise[i] & sender) and bool(ir_namen[i]) and (ir_geraet or "") not in ir_namen[i]

    kern = set()
    for i, refs in verweise.items():
        if i in gemeinsam or i in eigene or not (refs & geraete) or fremdes_ir(i):
            continue
        kern.add(i)
    if fenster_alt:  # der alte Fail-safe schreibt den Fenstersensor des Better Thermostat – er wird durch die neue Raumheizung ersetzt
        kern |= {i for i, e in daten["autos"].items() if i not in eigene and i not in gemeinsam and schreibt(e["config"], fenster_alt)}
    fremde_kerne = {i for b in fremde_bt for i in wer_nutzt.get(b, set()) if len(verweise[i] & bt_alle) == 1}
    global_ = {h for i in fremde_kerne for h in verweise[i] if _dom(h) in HELFER}

    def eigener_helfer(h):  # Geräte des Raums (z. B. ein input_boolean als Klima-Schalter) sind keine Helfer der alten Steuerung
        return _dom(h) in HELFER and not h.split(".", 1)[1].startswith("hz_") and h not in global_ and h not in geraete

    raumgeraete = geraete | {r for i in kern for r in verweise[i] if _dom(r) not in HELFER + ("automation", "script") + NEUTRAL}
    helfer = {h for i in kern for h in verweise[i] if eigener_helfer(h)}
    trabanten = set()
    for _ in range(12):
        logik = kern | trabanten
        neu = set()
        for i, refs in verweise.items():
            if i in kern or i in gemeinsam or i in eigene or fremdes_ir(i):
                continue
            bezug = (refs & helfer) or (refs & logik)
            erlaubt = helfer | global_ | raumgeraete | logik | gemeinsam
            if bezug and all(r in erlaubt or _dom(r) in NEUTRAL for r in refs):
                neu.add(i)
        neue_helfer = helfer | {h for i in neu for h in verweise[i] if eigener_helfer(h)}
        if neu == trabanten and neue_helfer == helfer:
            break
        trabanten, helfer = neu, neue_helfer
    steuerung = kern | trabanten
    abhaengig = {i for h in helfer for i in wer_nutzt.get(h, set())} - steuerung - gemeinsam - eigene
    gemeinsam_raum = {i for i in gemeinsam if verweise[i] & (geraete | helfer)}
    zustand = daten["zustaende"]
    return {
        "automationen": sorted(i for i in steuerung if _dom(i) == "automation"),
        "skripte": sorted(i for i in steuerung if _dom(i) == "script"),
        "helfer": sorted(helfer),
        "abhaengig": {i: sorted(verweise[i] & helfer) for i in sorted(abhaengig)},
        "gemeinsam": sorted(gemeinsam_raum),
        "namen": {i: namen[i] for i in steuerung | abhaengig | gemeinsam_raum}
        | {h: (zustand.get(h, {}).get("attributes", {}).get("friendly_name") or h) for h in helfer},
        "pv_laeuft": sorted(h for h in helfer if _dom(h) == "input_boolean" and any(k in h for k in _PV_LAEUFT)
                            and zustand.get(h, {}).get("state") == "on"),
        "klima_an": sorted(h for h in helfer if _dom(h) == "input_boolean" and h.endswith("klima_aktiv") and zustand.get(h, {}).get("state") == "on"),
    }


def zuordnung(helfer, zustaende, neue):
    """Alte Helfer → gleichwertige neue Helfer (nur bei gleichem Typ und, bei Auswahllisten, gleichen Auswahlwerten).

    neue: plan["entitaeten"] der Einrichtung (Rollen → entity_id).
    """
    def opts(eid):
        return set(zustaende.get(eid, {}).get("attributes", {}).get("options") or [])
    profile = {"Komfort", "Übergang", "Sommer", "Urlaub", "Aus"}
    klima = {"Aus", "Automatik Kühlen", "Manuell Kühlen"}
    regeln = [  # (Rolle, Typ, Namensteil, Prüfung)
        ("heizprofil", "input_select", "heizprofil", lambda e: opts(e) == profile),
        ("klima_modus", "input_select", "klima_modus", lambda e: opts(e) == klima),
        ("boost_wert", "input_number", "boost", None), ("boost_timer", "timer", "boost", None),
        ("klima_ziel", "input_number", "klima_ziel", None), ("klima_aktiv", "input_boolean", "klima_aktiv", None),
        ("klima_stufe", "input_number", "letzte_stufe", None), ("klima_vor_fenster", "input_text", "modus_vor_fenster", None),
        # Fensterstatus: nur wenn der alte Fail-safe mit abgeschaltet wird (er steht dann in der alten Steuerung, siehe einstufen)
        ("fensterstatus", "input_boolean", "fensterstatus", None),
    ]
    out = {}
    for h in helfer:
        for rolle, typ, teil, pruefung in regeln:
            if _dom(h) == typ and teil in h and neue.get(rolle) and (pruefung is None or pruefung(h)):
                if rolle == "klima_modus" and "vor_fenster" in h:
                    continue
                out[h] = neue[rolle]
                break
    return out


# ---------------------------------------------------------------------------------------------------------------- Abschalten
def _alias_setzen(ha, art, eid_id, alias):
    cfg = ha.rest("GET", f"/api/config/{art}/config/{eid_id}")
    alt = cfg.get("alias")
    cfg["alias"] = alias
    ha.rest("POST", f"/api/config/{art}/config/{eid_id}", cfg)
    return alt


def abschalten(ha, daten, auswahl_logik, auswahl_helfer):
    """Schaltet die gewählte alte Steuerung ab und kennzeichnet sie. Rückgabe: Protokoll für das Wiederherstellen."""
    p = {"zeit": dt.datetime.now().isoformat(timespec="seconds"), "automationen": [], "skripte": [], "helfer": [], "abhaengig": []}
    zust = daten["zustaende"]
    reg = {e["entity_id"]: e for e in daten["registry"]}
    for eid in auswahl_logik:
        if eid in daten["autos"]:
            aid = daten["autos"][eid]["id"]
            war_an = zust.get(eid, {}).get("state") == "on"
            alias = daten["autos"][eid]["config"].get("alias") or eid
            neu = alias if alias.endswith(ZUSATZ) else alias + ZUSATZ
            _alias_setzen(ha, "automation", aid, neu)
            ha.befehl("call_service", domain="automation", service="turn_off", service_data={}, target={"entity_id": eid})
            p["automationen"].append({"entity_id": eid, "id": aid, "alias": alias, "war_an": war_an})
        elif eid in daten["skripte"]:
            sid = daten["skripte"][eid]["id"]
            alias = daten["skripte"][eid]["config"].get("alias") or eid
            neu = alias if alias.endswith(ZUSATZ) else alias + ZUSATZ
            _alias_setzen(ha, "script", sid, neu)
            vorher = (reg.get(eid) or {}).get("disabled_by")
            if vorher is None:
                ha.befehl("config/entity_registry/update", entity_id=eid, disabled_by="user")
            p["skripte"].append({"entity_id": eid, "id": sid, "alias": alias, "disabled_by": vorher})
    for h in auswahl_helfer:
        e = reg.get(h)
        if not e:
            continue  # YAML-Helfer ohne eindeutige ID lassen sich nicht umbenennen
        anzeige = e.get("name") or zust.get(h, {}).get("attributes", {}).get("friendly_name") or h
        if not anzeige.endswith(ZUSATZ):
            ha.befehl("config/entity_registry/update", entity_id=h, name=anzeige + ZUSATZ)
        p["helfer"].append({"entity_id": h, "name": e.get("name")})
    return p


def umstellen(ha, daten, abhaengige, karte):
    """Stellt Verweise in abhängigen Automationen/Skripten von alten auf neue Helfer um. karte: alt → neu."""
    protokoll = []
    if not karte:
        return protokoll
    muster = re.compile(r"\b(" + "|".join(re.escape(k) for k in sorted(karte, key=len, reverse=True)) + r")\b")
    for eid in abhaengige:
        art, quelle = ("automation", daten["autos"]) if eid in daten["autos"] else ("script", daten["skripte"])
        if eid not in quelle:
            continue
        oid = quelle[eid]["id"]
        cfg = ha.rest("GET", f"/api/config/{art}/config/{oid}")
        text = json.dumps(cfg, ensure_ascii=False)
        neu_text = muster.sub(lambda m: karte[m.group(1)], text)
        if neu_text == text:
            continue
        ha.rest("POST", f"/api/config/{art}/config/{oid}", json.loads(neu_text))
        protokoll.append({"entity_id": eid, "art": art, "id": oid, "config": cfg})
    return protokoll


# ---------------------------------------------------------------------------------------------------------------- Wiederherstellen
def wiederherstellen(ha, p):
    """Macht abschalten() und umstellen() rückgängig. Rückgabe: Fehlertexte (der Rest wird trotzdem versucht)."""
    fehler = []
    for d in p.get("abhaengig", []):
        try:
            ha.rest("POST", f"/api/config/{d['art']}/config/{d['id']}", d["config"])
        except HAFehler as ex:
            fehler.append(str(ex))
    for a in p.get("automationen", []):
        try:
            _alias_setzen(ha, "automation", a["id"], a["alias"])
            if a.get("war_an"):
                ha.befehl("call_service", domain="automation", service="turn_on", service_data={}, target={"entity_id": a["entity_id"]})
        except HAFehler as ex:
            fehler.append(str(ex))
    skripte_geaendert = False
    for s in p.get("skripte", []):
        try:
            _alias_setzen(ha, "script", s["id"], s["alias"])
            if s.get("disabled_by") is None:
                ha.befehl("config/entity_registry/update", entity_id=s["entity_id"], disabled_by=None)
                skripte_geaendert = True
        except HAFehler as ex:
            fehler.append(str(ex))
    if skripte_geaendert:  # wieder freigegebene Skripte erscheinen erst nach dem Neuladen
        try:
            ha.befehl("call_service", domain="script", service="reload", service_data={})
        except HAFehler as ex:
            fehler.append(str(ex))
    for h in p.get("helfer", []):
        try:
            ha.befehl("config/entity_registry/update", entity_id=h["entity_id"], name=h.get("name"))
        except HAFehler as ex:
            fehler.append(str(ex))
    return fehler


# ---------------------------------------------------------------------------------------------------------------- Endgültig löschen
def loeschen(ha, p, ordner, helfer_auswahl=None):
    """Sichert und löscht die alte Steuerung endgültig. Rückgabe: (Sicherungsdatei, Fehlertexte)."""
    sicherung = {"zeit": dt.datetime.now().isoformat(timespec="seconds"), "automationen": {}, "skripte": {}, "helfer": {}}
    fehler = []
    for a in p.get("automationen", []):
        try:
            sicherung["automationen"][a["entity_id"]] = ha.rest("GET", f"/api/config/automation/config/{a['id']}")
        except HAFehler as ex:
            fehler.append(str(ex))
    for s in p.get("skripte", []):
        try:
            sicherung["skripte"][s["entity_id"]] = ha.rest("GET", f"/api/config/script/config/{s['id']}")
        except HAFehler as ex:
            fehler.append(str(ex))
    reg = {e["entity_id"]: e for e in ha.befehl("config/entity_registry/list")}
    helfer = [h for h in p.get("helfer", []) if helfer_auswahl is None or h["entity_id"] in helfer_auswahl]
    listen = {}
    for h in helfer:
        d = _dom(h["entity_id"])
        if d not in listen:
            try:
                listen[d] = {x["id"]: x for x in ha.befehl(f"{d}/list")}
            except HAFehler:
                listen[d] = {}
        uid = (reg.get(h["entity_id"]) or {}).get("unique_id")
        sicherung["helfer"][h["entity_id"]] = listen[d].get(uid)
    ordner = Path(ordner)
    ordner.mkdir(parents=True, exist_ok=True)
    datei = ordner / f"altsteuerung_geloescht_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    datei.write_text(json.dumps(sicherung, ensure_ascii=False, indent=1), encoding="utf-8")
    for a in p.get("automationen", []):
        try:
            ha.rest("DELETE", f"/api/config/automation/config/{a['id']}")
        except HAFehler as ex:
            fehler.append(str(ex))
    for s in p.get("skripte", []):
        try:
            ha.rest("DELETE", f"/api/config/script/config/{s['id']}")
        except HAFehler as ex:
            fehler.append(str(ex))
    for h in helfer:
        d = _dom(h["entity_id"])
        uid = (reg.get(h["entity_id"]) or {}).get("unique_id")
        if uid is None or listen[d].get(uid) is None:
            continue
        try:
            ha.befehl(f"{d}/delete", **{f"{d}_id": uid})
        except HAFehler as ex:
            fehler.append(str(ex))
    return str(datei), fehler


def noch_verwendet(daten, helfer):
    """Helfer → Automationen/Skripte, die ihn (außerhalb der alten Steuerung) noch verwenden."""
    out = {}
    for eid, e in {**daten["autos"], **daten["skripte"]}.items():
        text = json.dumps(e["config"], ensure_ascii=False)
        for h in helfer:
            if re.search(r"\b" + re.escape(h) + r"\b", text):
                out.setdefault(h, []).append(e["config"].get("alias") or eid)
    return out
