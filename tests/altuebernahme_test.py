"""PV-Geräte aus der alten Steuerung (assistent/altuebernahme.py) mit dem Aufbau einer typischen gewachsenen Raumsteuerung."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "assistent"))
import altuebernahme as au  # noqa: E402

FEHLER = []


def pruefe(bed, text):
    print(("   OK    " if bed else "   FEHLER ") + text)
    if not bed:
        FEHLER.append(text)


BT = "climate.wohnraum_bt"
WT = [{"from": "04:30:00", "to": "08:00:00"}, {"from": "11:30:00", "to": "13:30:00"}, {"from": "15:30:00", "to": "22:00:00"}]
plaene = [{"id": "wohnraum_komfort", "monday": WT, "tuesday": WT, "wednesday": WT, "thursday": WT, "friday": WT,
           "saturday": [{"from": "08:30:00", "to": "13:00:00"}, {"from": "16:30:00", "to": "23:00:00"}], "sunday": [{"from": "08:30:00", "to": "24:00:00"}]},
          {"id": "wohnraum_ubergang", "monday": WT, "tuesday": WT[:1], "wednesday": WT, "thursday": WT, "friday": WT, "saturday": [], "sunday": []},
          {"id": "wohnraum_urlaub", **{t: [{"from": "09:00:00", "to": "19:00:00"}] for t in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")}}]
registry = [{"entity_id": f"schedule.{p['id']}", "unique_id": p["id"], "platform": "schedule"} for p in plaene]
profil_auto = {"config": {"alias": "Wohnraum Heizung Profile", "actions": [{"variables": {"profilwerte": {
    "Komfort": {"helper": "input_number.wohnraum_komforttemperatur", "schedule": "schedule.wohnraum_komfort", "absenkung": 18},
    "Übergang": {"helper": "input_number.wohnraum_ubergangstemperatur", "schedule": "schedule.wohnraum_ubergang", "absenkung": 17},
    "Urlaub": {"helper": "input_number.wohnraum_urlaubstemperatur", "schedule": "schedule.wohnraum_urlaub", "absenkung": 16}}}},
    {"action": "climate.set_temperature", "target": {"entity_id": BT}}]}}
E = "sensor.pv_anlage_"
pv_auto = {"config": {"alias": "Wohnraum PV Heizen", "variables": {"x": (
    "{{ dict(soc=states('" + E + "battery_energy_charge_level'), grid=states('" + E + "inverter_power_grid_export'), battery=states('" + E
    + "battery_power_charge_discharge'), pv=states('" + E + "inverter_power_dc_total'), load=states('" + E + "site_data_power_consumption_total'), "
    "t=states('sensor.wohnraum_raumfuehler_temperatur'), a=states('sensor.aussentemperatur_mittel'), "
    "v1=states('sensor.wohnraum_trv_links_ventil_offnungsgrad'), start=states('input_number.wohnraum_pv_startleistung'), "
    "alter=state_attr('" + E + "battery_energy_charge_level','pv_last_update')) }}{% if x.soc<80 %}stop{% endif %}")},
    "actions": [{"action": "climate.set_hvac_mode", "target": {"entity_id": BT}},
                {"action": "climate.set_temperature", "target": {"entity_id": ["climate.wohnraum_trv_links", "climate.wohnraum_trv_rechts"]}},
                {"action": "remote.send_command", "target": {"entity_id": "remote.wohnraum_klima_ir"}}]}}
autos = {"automation.wohnraum_heizung_profile": profil_auto, "automation.wohnraum_pv_heizen": pv_auto,
         "automation.wohnraum_pv_sicherheitswache": {"config": {"actions": [{"action": "climate.set_hvac_mode", "target": {"entity_id": BT}}]}},
         "automation.wohnraum_heizungs_boost": {"config": {"actions": [{"action": "timer.start", "target": {"entity_id": "timer.wohnraum_heizungs_boost_timer"}}]}},
         "automation.wohnraum_boost_ende": {"config": {"actions": []}},
         "automation.wohnraum_klima_automatik": {"config": {"actions": [{"action": "script.turn_on", "target": {"entity_id": "script.wohnraum_klima_20"}}]}},
         "automation.hz_buero_raumheizung": {"config": {"use_blueprint": {"input": {"better_thermostat": BT}}}},
         "automation.oben_wohnraum_pv_test": {"config": {"actions": []}}}
zust = {"input_number.wohnraum_komforttemperatur": {"state": "22.5"}, "input_number.wohnraum_ubergangstemperatur": {"state": "21.0"},
        "input_number.wohnraum_urlaubstemperatur": {"state": "15.0"}, "input_number.wohnraum_pv_startleistung": {"state": "1000.0"},
        "timer.wohnraum_heizungs_boost_timer": {"state": "idle", "attributes": {"duration": "2:00:00"}},
        "sensor.wohnraum_raumfuehler_temperatur": {"state": "21.3", "attributes": {"device_class": "temperature"}},
        "sensor.aussentemperatur_mittel": {"state": "5", "attributes": {"device_class": "temperature"}}}
p = au.pv_geraete(autos, zust, "wohnraum", BT, "sensor.aussentemperatur_mittel")
pruefe(p.get("pv_trvs") == ["climate.wohnraum_trv_links", "climate.wohnraum_trv_rechts"]
       and p.get("pv_ventile") == ["sensor.wohnraum_trv_links_ventil_offnungsgrad"]
       and p.get("pv_raumfuehler") == "sensor.wohnraum_raumfuehler_temperatur", "PV: Heizkörperthermostate (ohne Better Thermostat), Ventilsensor, Raumfühler (nicht der Außenfühler)")
pruefe((p.get("soc"), p.get("netz"), p.get("akku_leistung"), p.get("pv_leistung"), p.get("verbrauch")) == (
    E + "battery_energy_charge_level", E + "inverter_power_grid_export", E + "battery_power_charge_discharge", E + "inverter_power_dc_total", E + "site_data_power_consumption_total"),
    "PV: alle fünf Energiesensoren ihrer Rolle zugeordnet")
pruefe(p.get("zeitstempel_attribut") == "pv_last_update" and "start_leistung" not in p and "soc_halten" not in p,
       "PV: Zeitstempel-Attribut pv_last_update; Schwellen werden nicht übernommen (bleiben Eingabe)")
p2 = au.pv_geraete(autos, zust, "schlafraum", "climate.schlafraum_bt")
pruefe(p2.get("soc") == E + "battery_energy_charge_level" and "pv_trvs" not in p2 and p2["quelle"].get("energie") == "automation.wohnraum_pv_heizen"
       and p2.get("zeitstempel_attribut") == "pv_last_update",
       "Raum ohne eigene alte PV: keine fremden Thermostate, aber Energiesensoren und Zeitstempel-Attribut aus der Wohnraum-PV")
print({k: p.get(k) for k in ("pv_trvs", "pv_ventile", "pv_raumfuehler")}) if FEHLER else None
print(f"   {'ALLE OK' if not FEHLER else str(len(FEHLER)) + ' FEHLER'}")
sys.exit(1 if FEHLER else 0)
