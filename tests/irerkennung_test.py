"""IR-Befehlserkennung (assistent/irerkennung.py) mit typischen Mustern einer bestehenden Steuerung in zwei Räumen."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "assistent"))
import irerkennung as ie  # noqa: E402

FEHLER = []


def pruefe(bed, text):
    print(("   OK    " if bed else "   FEHLER ") + text)
    if not bed:
        FEHLER.append(text)


def skript(sender, geraet, *befehle, liste=False):
    seq = []
    for b in befehle:
        seq.append({"action": "remote.send_command", "target": {"entity_id": sender}, "data": {"device": geraet, "command": [b] if liste else b}})
        seq.append({"delay": {"seconds": 1}})
    return {"config": {"alias": "x", "sequence": seq}}


WZ = "remote.wohnraum_klima_ir"
sk = {f"script.wohnraum_klima_{n}": skript(WZ, "klima", f"power_{n}", f"eco_{n}") for n in range(16, 24)}
sk["script.wohnraum_klima_aus"] = skript(WZ, "klima", "power_off")
sk["script.wohnraum_klima_fenster_pause"] = skript(WZ, "klima", "power_off")
sk["script.wohnraum_pv_ir_ein"] = skript(WZ, "klima", "heizen_24")
sk["script.wohnraum_pv_ir_aus"] = skript(WZ, "klima", "heizen_24_off", liste=True)
sk["script.tv_kueche"] = skript(WZ, "tv_kueche", "power")
sk["script.vorlage"] = {"config": {"sequence": [{"action": "remote.send_command", "target": {"entity_id": WZ}, "data": {"device": "klima", "command": "power_{{ s }}"}}]}}
gel = {"klima": {*(f"power_{n}" for n in range(16, 24)), *(f"eco_{n}" for n in range(16, 24)), *(f"kuehlen_{n}" for n in range(16, 24)),
                 "power_off", "aus", "heizen_24", "heizen_24_off", "fan_auto", "swing", "turbo", "eco", "power"}, "tv_kueche": {"power"}}

pruefe(ie.sender_der_altsteuerung(sk, {}, "wohnraum") == WZ, "Sender des Raums aus den alten Klima-Skripten vorgeschlagen")
sk_y = dict(sk, **{f"script.oben_wohnraum_klima_{n}": skript("remote.oben", "klima", f"power_{n}") for n in range(16, 24)})
pruefe(ie.sender_der_altsteuerung(sk_y, {}, "wohnraum") == WZ and ie.sender_der_altsteuerung(sk_y, {}, "oben_wohnraum") == "remote.oben",
       "Wohnraum und Wohnraum oben: je der eigene Sender, obwohl „wohnraum“ in beiden Namen vorkommt")
pruefe(ie.sender_der_altsteuerung(sk, {}, "oben_wohnraum") is None, "Anderer Raum (Wohnraum oben) bekommt diesen Sender nicht vorgeschlagen")
e = ie.erkennen(ie.quellen_aus(sk, {}, WZ), gel)
pruefe((e["ir_geraet"], e["befehl_kuehlen"], e["befehl_zusatz"], e["befehl_aus"], e["stufe_min"], e["stufe_max"])
       == ("klima", "power_{stufe}", "eco_{stufe}", "power_off", 16, 23), "Wohnraum: klima · power_{stufe} → eco_{stufe} · power_off · 16–23 °C aus den alten Skripten")
pruefe((e["befehl_heizen"], e["pv_heizstufe"], e["befehl_heizen_aus"], e["heiz_stufe_min"], e["heiz_stufe_max"]) == ("heizen_{stufe}", 24, "heizen_24_off", 22, 28),
       "Wohnraum PV: heizen_{stufe} (bisher 24), Heizen aus heizen_24_off, Heizstufen 22–28")
pruefe(set(e["herkunft"].values()) == {"alt"} and "power_{stufe} → eco_{stufe}" in e["hinweise"][0], "Herkunft „alte Steuerung“ und Hinweistext")

e = ie.erkennen({}, gel)
pruefe((e["ir_geraet"], e["befehl_kuehlen"], e["befehl_zusatz"], e["befehl_aus"], e["stufe_min"], e["stufe_max"]) == ("klima", "power_{stufe}", "", "power_off", 16, 23)
       and "eco_{stufe}" in e["hinweise"][0], "Ohne alte Steuerung: aus dem Sender power_{stufe} (vor kuehlen_{stufe}), power_off; eco_{stufe} nur als Hinweis")

SZ = "remote.schlafraum_klima_ir"
sk2 = {f"script.schlafraum_klima_{n}": skript(SZ, "klima", f"power_{n}", f"eco_{n}", "display_off") for n in range(16, 24)}
sk2["script.schlafraum_klima_aus"] = skript(SZ, "klima", "power_off")
e = ie.erkennen(ie.quellen_aus(sk2, {}, SZ), None)
pruefe((e["befehl_kuehlen"], e["befehl_zusatz"], e["befehl_aus"]) == ("power_{stufe}", "eco_{stufe}, display_off", "power_off") and "befehl_heizen" not in e,
       "Schlafraum: power_{stufe} → eco_{stufe}, display_off (zwei Zusatzbefehle in Reihenfolge), Aus power_off; ohne PV-Skripte kein Heizbefehl")

teil = {"script.raum_klima_20": skript(SZ, "klima", "power_20")}
e = ie.erkennen(ie.quellen_aus(teil, {}, SZ), {"klima": {f"power_{n}" for n in range(17, 26)}})
pruefe((e["stufe_min"], e["stufe_max"]) == (17, 25), "Nur ein altes Stufen-Skript: Stufenbereich um die im Sender vorhandenen Stufen ergänzt (17–25)")
e = ie.erkennen({}, {})
pruefe("ir_geraet" not in e and e["herkunft"] == {}, "Nichts gefunden: kein Vorschlag (Einrichtung nutzt Standardnamen)")
pruefe(ie.vorlage("heizen_24_off") == ("heizen_{stufe}_off", 24) and ie.vorlage("kühlen_21") == ("kühlen_{stufe}", 21) and ie.vorlage("power") == ("power", None),
       "Befehlsmuster: Stufenzahl wird zu {stufe}")
print(f"   {'ALLE OK' if not FEHLER else str(len(FEHLER)) + ' FEHLER'}")
sys.exit(1 if FEHLER else 0)
