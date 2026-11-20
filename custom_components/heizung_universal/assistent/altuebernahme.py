"""Geräte für das PV-Überschussheizen aus der alten Steuerung vorschlagen (nur lesend, nur Entitäten).

Aus der alten PV-Automation des Raums: Heizkörperthermostate, Ventilöffnungs-Sensoren, Raumfühler, Energiesensoren (z. B. Wechselrichter, Speicher) und das
Zeitstempel-Attribut der Energiesensoren. Die Energiesensoren gelten für das ganze Haus und kommen notfalls aus der PV-Automation eines
anderen Raums. Schwellen, Zeiten und Funktionen werden NICHT übernommen – die stellt der Nutzer selbst ein.

Die Geräte landen danach wie bei Handeingabe in den Blueprint-Eingaben; „Gerät austauschen“ ersetzt sie dort.
"""
from __future__ import annotations

import json
import re

_ENT = re.compile(r"\b((?:sensor|climate|binary_sensor|input_number|timer|schedule|input_boolean|remote|switch)\.[a-z0-9_]+)\b")
ENERGIE = ("soc", "akku_leistung", "netz", "pv_leistung", "verbrauch")


def _text(cfg):
    return json.dumps(cfg, ensure_ascii=False)


def _entitaeten(cfg):
    """Entitäten einer Konfiguration in Reihenfolge – ohne Dienstnamen wie climate.set_temperature."""
    dienste = set()

    def lauf(x):
        if isinstance(x, dict):
            for k in ("action", "service"):
                if isinstance(x.get(k), str):
                    dienste.add(x[k])
            for v in x.values():
                lauf(v)
        elif isinstance(x, list):
            for v in x:
                lauf(v)

    lauf(cfg)
    return [e for e in dict.fromkeys(_ENT.findall(_text(cfg))) if e not in dienste and not re.search(r"\.(set|turn|start|cancel|toggle|send|select)_", e)]


def raum_automationen(autos, raum_key, bt=None):
    """Alte (nicht eigene) Automationen dieses Raums: Name beginnt mit dem Raum oder sie verwenden das Better Thermostat."""
    out = {}
    for eid, e in autos.items():
        name = eid.split(".", 1)[1]
        if name.startswith("hz_") or "use_blueprint" in (e.get("config") or {}):
            continue
        if name.startswith(raum_key + "_") or (bt and bt in _text(e.get("config") or {})):
            out[eid] = e
    return out


def _art(eid, zustand):
    """Rolle eines Energiesensors nach Name/Einheit: soc | akku_leistung | netz | pv_leistung | verbrauch | None."""
    n = eid.split(".", 1)[1]
    einheit = ((zustand or {}).get("attributes") or {}).get("unit_of_measurement")
    if any(w in n for w in ("charge_level", "state_of_charge", "ladestand", "battery_level", "_soc", "soc_")) or (einheit == "%" and any(w in n for w in ("batter", "akku"))):
        return "soc"
    if any(w in n for w in ("batter", "akku")) and any(w in n for w in ("power", "leistung", "charge_discharge")):
        return "akku_leistung"
    if any(w in n for w in ("grid", "netz", "einspeis", "export")):
        return "netz"
    if any(w in n for w in ("inverter_power", "pv_power", "pv_leistung", "solar", "dc_total", "photovolt")):
        return "pv_leistung"
    if any(w in n for w in ("consumption", "verbrauch", "hauslast", "load")):
        return "verbrauch"
    return None


def _energie(txt, zustaende):
    out = {}
    for eid in dict.fromkeys(_ENT.findall(txt)):
        if eid.startswith("sensor."):
            art = _art(eid, zustaende.get(eid))
            if art and art not in out:
                out[art] = eid
    return out


def pv_geraete(autos, zustaende, raum_key, bt=None, aussen=None):
    """Vorschlag für die PV-Seite aus der alten PV-Automation des Raums (Energiesensoren notfalls aus einer anderen PV-Automation)."""
    eigene = raum_automationen(autos, raum_key, bt)
    kandidaten = [(eid, e) for eid, e in eigene.items() if re.search(r"(^|_)pv(_|$)", eid.split(".", 1)[1])]
    kandidaten.sort(key=lambda x: -len(_entitaeten(x[1].get("config") or {})))
    out = {"quelle": {}}
    if kandidaten:
        eid, e = kandidaten[0]
        txt = _text(e.get("config") or {})
        ents = _entitaeten(e.get("config") or {})
        trvs = [x for x in ents if x.startswith("climate.") and x != bt]
        if trvs:
            out["pv_trvs"] = trvs
        ventile = [x for x in ents if x.startswith("sensor.") and any(w in x for w in ("ventil", "valve"))]
        if ventile:
            out["pv_ventile"] = ventile
        fuehler = [x for x in ents if x.startswith("sensor.") and x != aussen and "aussen" not in x and "outdoor" not in x
                   and ((((zustaende.get(x) or {}).get("attributes") or {}).get("device_class") == "temperature") or x.endswith("_temperatur") or x.endswith("_temperature"))]
        if fuehler:
            out["pv_raumfuehler"] = fuehler[0]
        out.update(_energie(txt, zustaende))
        attr = [m for m in re.findall(r"state_attr\(\s*'sensor\.[a-z0-9_]+'\s*,\s*'([a-z0-9_]+)'\s*\)", txt) if any(w in m for w in ("update", "zeit", "time", "stamp"))]
        if attr:
            out["zeitstempel_attribut"] = attr[0]
        out["quelle"]["pv"] = eid
    if not all(k in out for k in ENERGIE):  # Energiesensoren gelten für das ganze Haus: notfalls aus der PV-Automation eines anderen Raums
        andere = [(eid, e) for eid, e in autos.items() if re.search(r"(^|_)pv(_|$)", eid.split(".", 1)[1])
                  and not eid.split(".", 1)[1].startswith("hz_") and "use_blueprint" not in (e.get("config") or {})]  # eigene Räume: siehe Einrichtung
        andere.sort(key=lambda x: -len(_energie(_text(x[1].get("config") or {}), zustaende)))
        if andere:
            txt_a = _text(andere[0][1].get("config") or {})
            for k, v in _energie(txt_a, zustaende).items():
                if k not in out:
                    out[k] = v
                    out["quelle"].setdefault("energie", andere[0][0])
            attr = [m for m in re.findall(r"state_attr\(\s*'sensor\.[a-z0-9_]+'\s*,\s*'([a-z0-9_]+)'\s*\)", txt_a) if any(w in m for w in ("update", "zeit", "time", "stamp"))]
            if attr and "zeitstempel_attribut" not in out:
                out["zeitstempel_attribut"] = attr[0]
    return out
