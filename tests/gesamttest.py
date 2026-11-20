#!/usr/bin/env python3
"""Gesamttest der drei Blueprints im Ablauf-Simulator (tests/simulator.py).
Start: .venv/bin/python tests/gesamttest.py   (Jinja2 erforderlich; zsh tests/alle_tests.sh richtet die Umgebung ein)"""
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from simulator import Automation, Sim  # noqa: E402

WT, WE = ["mo", "di", "mi", "do", "fr"], ["sa", "so"]
MO = dt.datetime(2026, 11, 9)  # Montag
ERG, SIMS = [], []
RH, KL, PV = "universelle_raumheizungssteuerung.yaml", "klimaautomatik.yaml", "pv_ueberschussheizen.yaml"
ENERGIE = ["sensor.soc", "sensor.netz", "sensor.akku", "sensor.pvl", "sensor.last"]
PV_TIMER = ["t_startfrist", "t_mangelfrist", "t_wiederholung", "t_waermepruefung", "t_sperre", "t_freigabe", "t_schaltpause", "t_heizkoerper"]
PV_FLAGS = ["f_heizfreigabe", "f_ir_geprueft", "f_regelung", "f_heizbefehl", "f_auftrag", "f_fehler", "f_wiederholt", "f_vorbereitung"]


def zeit(tag=0, h=0, m=0):
    return MO + dt.timedelta(days=tag, hours=h, minutes=m)


def titel(t):
    print("\n### " + t)


def pruefe(bed, text):
    ERG.append((bool(bed), text))
    print(("   ✔ " if bed else "   ✘ ") + text)


def bt(s):
    return s.s("climate.bt"), s.attr("climate.bt", "temperature")


def n(s, dienst):
    return sum(1 for r in s.rufe if r[2] == dienst)


def ir(s):
    return [c for _, _, c in s.ir]


def trv_modell(sim, eid, alt, neu):
    """Heizkörperthermostate folgen dem Better Thermostat (aus → 5 °C/Ventil 0 %, heizen → offen)."""
    if eid == "climate.bt" and (alt is None or alt.state != neu.state) and neu.state in ("off", "heat"):
        for t in ("climate.trv1", "climate.trv2"):
            sim.setze(t, "heat", temperature=5.0 if neu.state == "off" else 30.0)
        for v in ("sensor.v1", "sensor.v2"):
            sim.setze(v, "0" if neu.state == "off" else "100")


def raum(start, *, vorheizen=False, vh=None, fenster=True, boost=True, klima=False, pv=False, modus="produktiv", extra=None, temp=19.0,
         profil="Komfort", aussen=8.0, vor_start=None, trv=True):
    s = Sim(start)
    SIMS.append(s)
    Z = s.zustand
    Z("climate.bt", "heat", temperature=16.0, current_temperature=temp, hvac_action="idle", window_open=False)
    Z("sensor.raum", temp)
    Z("sensor.aussen", aussen)
    Z("input_select.profil", profil, options=["Komfort", "Übergang", "Sommer", "Urlaub", "Aus"])
    Z("input_text.status", "")
    Z("input_boolean.haus_aus", "off")
    ein = dict(raum_name="Testraum", raum_schluessel="test", better_thermostat="climate.bt", raumfuehler="sensor.raum",
               aussentemperatur="sensor.aussen", heizprofil="input_select.profil", status_text="input_text.status",
               haus_heizung_aus="input_boolean.haus_aus", ausgabe_modus=modus, komfort_soll=22, komfort_absenk=16,
               komfort_sa1_von="09:00:00", komfort_sa1_bis="12:00:00", komfort_so1_von="09:00:00", komfort_so1_bis="12:00:00")
    if fenster:
        Z("binary_sensor.f1", "off")
        Z("binary_sensor.f2", "off")
        Z("input_boolean.fstatus", "off")
        Z("timer.fausfall", "idle", duration="0:10:00")
        ein.update(fenster_modus="eigen", fensterkontakte=["binary_sensor.f1", "binary_sensor.f2"], fensterstatus="input_boolean.fstatus",
                   fenster_timer="timer.fausfall")
    if boost:
        Z("input_number.boost", "5.0")
        Z("timer.boost", "idle", duration="2:00:00")
        ein.update(boost_aktiv=True, boost_wert="input_number.boost", boost_timer="timer.boost")
    if vorheizen:
        Z("input_number.vh_faktor", "1.0")
        Z("input_text.vh_merker", "")
        Z("input_text.vh_bericht", "")
        ein.update(vorheizen_aktiv=True, vorheizen_faktor="input_number.vh_faktor", vorheizen_merker="input_text.vh_merker",
                   vorheizen_bericht="input_text.vh_bericht")
        if vh:
            ein.update(komfort_wt1_vh=True, komfort_wt1_vh_temp=vh[0], komfort_wt1_vh_bis=vh[1])
    kl_ein = pv_ein = None
    if klima or pv:
        Z("remote.klima", "on")
        Z("input_select.kmodus", "Aus", options=["Aus", "Automatik Kühlen", "Manuell Kühlen"])
        Z("input_number.kziel", "22.0")
        Z("input_number.kmanuell", "20.0")
        Z("input_number.kstufe", "0.0")
        Z("input_boolean.kaktiv", "off")
        Z("input_text.kvor", "")
        Z("input_text.ircfg", "")
        kl_ein = dict(raum_name="Testraum", raum_schluessel="test", klima_sender="remote.klima", raumfuehler="sensor.raum",
                      aussentemperatur="sensor.aussen", fensterkontakte=["binary_sensor.f1", "binary_sensor.f2"], heizprofil="input_select.profil",
                      haus_heizung_aus="input_boolean.haus_aus", klima_modus="input_select.kmodus", zieltemperatur="input_number.kziel",
                      manuelle_stufe="input_number.kmanuell", letzte_stufe="input_number.kstufe", klima_aktiv="input_boolean.kaktiv",
                      modus_vor_fenster="input_text.kvor", ir_konfiguration="input_text.ircfg", ausgabe_modus=modus)
    if pv:
        for t in ("climate.trv1", "climate.trv2"):
            Z(t, "heat", temperature=30.0)
        for v in ("sensor.v1", "sensor.v2"):
            Z(v, "100")
        for e, w in zip(ENERGIE, (96, 1500, 0, 3000, 800)):
            Z(e, w)
        for t in PV_TIMER:
            Z("timer.pv_" + t, "idle")
        for f in PV_FLAGS:
            Z("input_boolean.pv_" + f, "on" if f == "f_ir_geprueft" else "off")
        Z("input_number.pv_starttemp", "20.0")
        Z("input_text.pv_status", "")
        s.herzschlag += ENERGIE + ["sensor.raum", "sensor.aussen"]
        if trv:
            s.modelle.append(trv_modell)
        flags = {f: "input_boolean.pv_" + f for f in PV_FLAGS}
        timer = {t: "timer.pv_" + t for t in PV_TIMER}
        ein.update(pv_aktiv=True, pv_flags=[flags[f] for f in ("f_regelung", "f_heizbefehl", "f_auftrag", "f_vorbereitung")], pv_freigabe=timer["t_freigabe"])
        kl_ein.update(pv_aktiv=True, pv_automation="automation.pv", pv_heizfreigabe=flags["f_heizfreigabe"], pv_heizbefehl=flags["f_heizbefehl"],
                      pv_auftrag=flags["f_auftrag"], pv_verantwortung=[flags["f_regelung"], flags["f_vorbereitung"]], pv_freigabe=timer["t_freigabe"],
                      pv_status="input_text.pv_status")
        pv_ein = dict(raum_name="Testraum", raum_schluessel="test", better_thermostat="climate.bt", heizkoerper=["climate.trv1", "climate.trv2"],
                      ventile=["sensor.v1", "sensor.v2"], raumfuehler="sensor.raum", aussentemperatur="sensor.aussen",
                      fensterkontakte=["binary_sensor.f1", "binary_sensor.f2"], ir_konfiguration="input_text.ircfg", soc="sensor.soc", netz="sensor.netz",
                      akku_leistung="sensor.akku", pv_leistung="sensor.pvl", verbrauch="sensor.last", heizprofil="input_select.profil",
                      raumheizung_automation="automation.rh", klima_automation="automation.kl", klima_modus="input_select.kmodus",
                      klima_aktiv="input_boolean.kaktiv", starttemperatur="input_number.pv_starttemp", status_text="input_text.pv_status", **flags, **timer)
    ein.update(extra or {})
    if vor_start:
        vor_start(s)
    Automation(s, "automation.rh", RH, ein)
    if kl_ein:
        Automation(s, "automation.kl", KL, kl_ein)
    if pv_ein:
        Automation(s, "automation.pv", PV, pv_ein)
    s.start()
    return s


# =============================================================================== Blueprint 1
def test_zeitplan():
    titel("Raumheizung 1 – Zeitplan ohne Vorheizen (Standardverhalten)")
    s = raum(zeit(0, 3))
    pruefe(bt(s) == ("heat", 16.0), "Start Mo 03:00: Absenktemperatur 16 °C")
    k = n(s, "climate.set_temperature")
    s.weiter(bis="05:59")
    s.weiter(sekunden=30)
    pruefe(n(s, "climate.set_temperature") == k and bt(s)[1] == 16.0, "bis 05:59:30 keine einzige Sollwertänderung (kein Vorheizen)")
    s.weiter(sekunden=30)
    pruefe(bt(s) == ("heat", 22.0), "genau 06:00:00: Solltemperatur 22 °C gesendet")
    pruefe("g=Heizphase" in s.s("input_text.status") and "nx=A08:00" in s.s("input_text.status"), "Status: Heizphase bis 08:00")
    s.weiter(bis="08:00")
    pruefe(bt(s)[1] == 16.0, "08:00: Absenkung 16 °C")
    s.weiter(bis="16:00")
    pruefe(bt(s)[1] == 22.0, "16:00: zweite Heizphase 22 °C")
    s.weiter(bis="22:00")
    pruefe(bt(s)[1] == 16.0, "22:00: Absenkung")
    s.weiter(bis="06:00")
    pruefe(bt(s)[1] == 22.0 and s.jetzt.weekday() == 1, "Dienstag 06:00: wieder 22 °C")
    pruefe(n(s, "climate.set_temperature") == k + 5, "insgesamt genau 5 Sollwertbefehle in 27 Stunden (nur bei Änderung)")
    s = raum(zeit(5, 5))
    s.weiter(bis="08:59")
    pruefe(bt(s)[1] == 16.0, "Samstag: Werktagsphase 06:00 gilt nicht, 08:59 noch 16 °C")
    s.weiter(bis="09:00")
    pruefe(bt(s)[1] == 22.0, "Samstag 09:00: Wochenendphase 22 °C")
    s.weiter(bis="12:00")
    pruefe(bt(s)[1] == 16.0, "Samstag 12:00: Absenkung")
    s = raum(zeit(0, 21), extra=dict(komfort_wt2_von="22:00:00", komfort_wt2_bis="02:00:00"))
    s.weiter(bis="22:00")
    a = bt(s)[1]
    s.weiter(bis="01:00")
    b = bt(s)[1]
    s.weiter(bis="02:00")
    pruefe((a, b, bt(s)[1]) == (22.0, 22.0, 16.0), "Heizphase über Mitternacht (22:00–02:00): 22 → 22 → 16 °C")


def test_tagesprogramme():
    titel("Raumheizung 1b – Drei Tagesprogramme je Profil (Montag bis Freitag, Samstag, Sonntag) mit je bis zu drei Heizphasen")
    P = dict(komfort_wt1_von="06:00:00", komfort_wt1_bis="08:00:00", komfort_wt2_von="11:30:00", komfort_wt2_bis="13:30:00",
             komfort_wt3_aktiv=True, komfort_wt3_von="15:30:00", komfort_wt3_bis="20:00:00",
             komfort_sa1_von="09:00:00", komfort_sa1_bis="12:00:00", komfort_sa2_aktiv=True, komfort_sa2_von="18:00:00", komfort_sa2_bis="20:00:00",
             komfort_so1_von="10:00:00", komfort_so1_bis="11:00:00",
             uebergang_wt1_von="07:00:00", uebergang_wt1_bis="09:00:00", uebergang_sa1_von="10:00:00", uebergang_sa1_bis="14:00:00", uebergang_so1_aktiv=False)

    def verlauf(s, zeiten):
        werte = []
        for z in zeiten:
            s.weiter(bis=z)
            werte.append(bt(s)[1])
        return werte

    s = raum(zeit(4, 5), extra=P)
    pruefe(verlauf(s, ["06:00", "08:00", "11:30", "13:30", "15:30", "20:00"]) == [22.0, 16.0, 22.0, 16.0, 22.0, 16.0],
           "Freitag (Montag bis Freitag): 06:00–08:00, 11:30–13:30, 15:30–20:00 → jeweils 22 °C, dazwischen 16 °C")
    pruefe(verlauf(s, ["06:00", "08:59", "09:00", "11:30", "12:00", "15:30", "18:00", "20:00"]) == [16.0, 16.0, 22.0, 22.0, 16.0, 16.0, 22.0, 16.0],
           "Samstag: eigenes Programm 09:00–12:00 und 18:00–20:00; die Werktagszeiten (06:00, 11:30, 15:30) gelten nicht")
    pruefe(verlauf(s, ["09:00", "10:00", "11:00", "18:00", "20:00"]) == [16.0, 22.0, 16.0, 16.0, 16.0],
           "Sonntag: eigenes Programm 10:00–11:00, unabhängig vom Samstag (18:00 bleibt Absenkung)")
    pruefe(verlauf(s, ["06:00", "08:00"]) == [22.0, 16.0], "Montag: wieder das Programm Montag bis Freitag")
    s = raum(zeit(0, 5), extra=dict(P, komfort_wt2_aktiv=False))
    pruefe(verlauf(s, ["06:00", "08:00", "11:30", "13:30", "15:30"]) == [22.0, 16.0, 16.0, 16.0, 22.0],
           "Einzelne Heizphase ausgeschaltet (Mo–Fr Phase 2): 11:30 bleibt Absenkung, Phasen 1 und 3 unverändert")
    s = raum(zeit(5, 8), profil="Übergang", extra=P)
    pruefe(verlauf(s, ["09:00", "10:00", "14:00", "18:00"]) == [17.0, 21.0, 17.0, 17.0],
           "Profil Übergang hat eigene Tagesprogramme und eigene Temperaturen (Samstag 10:00–14:00 → 21 °C, sonst 17 °C)")
    k = n(s, "climate.set_temperature")
    s.weiter(minuten=60 * 24)
    pruefe(bt(s)[1] == 17.0 and n(s, "climate.set_temperature") == k, "Übergang Sonntag ohne aktive Heizphase: durchgehend Absenktemperatur, kein einziger Sollwertbefehl")
    s = raum(zeit(5, 21), extra=dict(komfort_sa2_aktiv=True, komfort_sa2_von="22:00:00", komfort_sa2_bis="01:00:00"))
    pruefe(verlauf(s, ["22:00", "23:59", "00:30", "01:00"]) == [22.0, 22.0, 22.0, 16.0], "Samstag-Phase über Mitternacht (22:00–01:00) endet am Sonntag um 01:00")


def test_vorheizen():
    titel("Raumheizung 2 – Vorausschauendes Vorheizen (optional)")
    s = raum(zeit(0, 3), vorheizen=True, vh=(21, "06:00:00"), temp=18.5)
    s.weiter(bis="03:10")
    pruefe(bt(s)[1] == 16.0, "Ist 18,5 °C, mind. 21 °C bis 06:00: um 03:10 noch 16 °C (Vorlauf 165 min)")
    s.weiter(bis="03:15")
    pruefe(bt(s) == ("heat", 21.0), "03:15: Mindesttemperatur 21 °C gesendet – nicht die Solltemperatur 22 °C")
    pruefe("Vorheizen seit 03:15 für 06:00 (Mindesttemperatur 21.0 °C, Vorlauf 165 min" in s.s("input_text.vh_bericht"), "Bericht nennt Beginn, Ziel und Vorlauf")
    pruefe("vh=21.0@06:00" in s.s("input_text.status") and "g=Vorheizen" in s.s("input_text.status"), "Status für die Karte: Vorheizen 21 °C bis 06:00")
    s.weiter(bis="05:30")
    s.set("sensor.raum", 21.0)
    s.weiter(bis="05:55")
    pruefe(bt(s)[1] == 21.0, "Raum erreicht 21 °C um 05:30: Mindesttemperatur wird bis zum Beginn gehalten")
    s.weiter(bis="06:00")
    pruefe(bt(s)[1] == 22.0, "06:00: reguläre Solltemperatur 22 °C")
    pruefe(s.s("input_text.vh_bericht").startswith("✔ Mindesttemperatur 21.0 °C um 06:00 erreicht (30 min früher)"), "Bericht: erreicht, 30 min früher")
    pruefe(s.s("input_text.vh_merker") == "" and s.s("input_number.vh_faktor") == "1.0", "Vorgang abgeschlossen, Korrekturfaktor unverändert")

    s = raum(zeit(0, 3), vorheizen=True, vh=(21, "06:00:00"), temp=18.5)
    s.weiter(bis="06:00")
    pruefe(bt(s)[1] == 22.0 and s.s("input_text.vh_bericht").startswith("✘ Mindesttemperatur 21.0 °C um 06:00 NICHT erreicht (Ist 18.5 °C)"),
           "Raum bleibt bei 18,5 °C: Bericht meldet ehrlich NICHT erreicht; 06:00 trotzdem 22 °C")
    pruefe(s.s("input_number.vh_faktor") == "1.2", "Korrekturfaktor lernt nach: 1,0 → 1,2")

    s = raum(zeit(0, 3), vorheizen=True, vh=(21, "06:00:00"), temp=15.0, extra=dict(vorheizen_max=60))
    s.weiter(bis="04:55")
    a = bt(s)[1]
    s.weiter(bis="05:00")
    pruefe(a == 16.0 and bt(s)[1] == 21.0 and "voraussichtlich NICHT erreichbar, benötigt 375 min" in s.s("input_text.vh_bericht"),
           "Maximale Vorlaufzeit 60 min reicht nicht: Start erst 05:00, Bericht warnt schon beim Start")

    s = raum(zeit(0, 3), vorheizen=True, vh=(21, "06:00:00"), temp=18.5)
    s.weiter(bis="04:00")
    s.set("binary_sensor.f1", "on")
    s.weiter(minuten=2)
    aus = bt(s)[0]
    s.set("binary_sensor.f1", "off")
    s.weiter(bis="06:00")
    pruefe(aus == "off", "Fenster offen während des Vorheizens: Heizpause hat Vorrang")
    pruefe("NICHT erreicht" in s.s("input_text.vh_bericht") and "Störung: Fenster – nicht gelernt" in s.s("input_text.vh_bericht")
           and s.s("input_number.vh_faktor") == "1.0", "Verfehlt wegen Fenster: gemeldet, aber nicht in den Lernfaktor übernommen")

    s = raum(zeit(0, 4), vorheizen=True, vh=(21, "05:30:00"), temp=20.5)
    s.weiter(bis="04:40")
    a = bt(s)[1]
    s.weiter(bis="04:45")
    b = bt(s)[1]
    s.weiter(bis="05:30")
    bericht = s.s("input_text.vh_bericht")
    s.weiter(bis="05:50")
    c = bt(s)[1]
    s.weiter(bis="06:00")
    pruefe((a, b) == (16.0, 21.0), "Zieluhrzeit 05:30 (vor Beginn 06:00): Start 04:45 statt 05:15")
    pruefe(bericht.startswith("✘ Mindesttemperatur 21.0 °C um 05:30 NICHT erreicht"), "Bewertung zur Zieluhrzeit 05:30")
    pruefe(c == 21.0 and bt(s)[1] == 22.0, "05:30–06:00 Mindesttemperatur gehalten, 06:00 Solltemperatur 22 °C")

    s = raum(zeit(0, 12), vorheizen=True, vh=(21, "06:00:00"), temp=18.5)
    k = n(s, "climate.set_temperature")
    s.weiter(bis="15:59")
    s.weiter(sekunden=30)
    a = n(s, "climate.set_temperature")
    s.weiter(sekunden=30)
    pruefe(a == k and bt(s)[1] == 22.0, "Vorheizen nur für Phase 1 gewählt: vor Phase 2 (16:00) keine vorzeitige Änderung, 16:00 → 22 °C")

    s = raum(zeit(0, 3), vorheizen=True, vh=(21, "06:00:00"), temp=18.5)
    s.weiter(bis="03:30")
    s.set("input_select.profil", "Aus")
    a = bt(s)[1]
    b = s.s("input_text.vh_bericht")
    s.set("input_select.profil", "Komfort")
    s.weiter(bis="03:35")
    pruefe(a == 5.0 and "abgebrochen" in b and bt(s)[1] == 21.0, "Profil Aus während des Vorheizens → Frostschutz, Vorgang abgebrochen; zurück auf Komfort → Vorheizen neu")

    def zp(sim):
        sim.zustand("schedule.k", "off", next_event=zeit(0, 6).replace(tzinfo=sim.jetzt.tzinfo))
    s = raum(zeit(0, 4), vorheizen=True, temp=19.0, vor_start=zp,
             extra=dict(komfort_quelle="zeitplan", komfort_zeitplan="schedule.k", komfort_zp_vh=True, komfort_zp_vh_temp=20.5))
    s.weiter(bis="04:10")
    a = bt(s)[1]
    s.weiter(bis="04:15")
    b = bt(s)[1]
    s.weiter(bis="06:00")
    s.set("schedule.k", "on", next_event=zeit(0, 8).replace(tzinfo=s.jetzt.tzinfo))
    pruefe((a, b, bt(s)[1]) == (16.0, 20.5, 22.0), "Zeitplan-Helfer als Zeitquelle mit Vorheizen: 16 → 20,5 (04:15) → 22 °C beim Einschalten des Zeitplans")


def test_termine():
    titel("Raumheizung 2b – Mindest- und Zieltemperatur zu festen Uhrzeiten (optional, getrennt schaltbar)")
    M = dict(vorheizen_aktiv=False, mindest_aktiv=True, komfort_m1_aktiv=True, komfort_m1_tage=["mi"], komfort_m1_zeit="04:20:00", komfort_m1_temp=21,
             komfort_m2_aktiv=True, komfort_m2_tage=["mi"], komfort_m2_zeit="15:45:00", komfort_m2_temp=21.5)
    s = raum(zeit(2, 1), vorheizen=True, temp=18.5, extra=M)
    s.weiter(bis="01:30")
    a = bt(s)[1]
    s.weiter(bis="01:35")
    pruefe(a == 16.0 and bt(s) == ("heat", 21.0), "Mittwoch 04:20 mind. 21 °C (Ist 18,5): bis 01:30 Absenkung, 01:35 Sollwert 21 °C (Vorlauf 165 min)")
    pruefe("vh=21.0@04:20" in s.s("input_text.status"), "Status für die Karte: mindestens 21 °C bis 04:20")
    s.weiter(bis="03:30")
    s.set("sensor.raum", 21.0)
    s.weiter(bis="04:20")
    pruefe(s.s("input_text.vh_bericht").startswith("✔ Mindesttemperatur 21.0 °C um 04:20 erreicht (50 min früher)"), "Bewertung 04:20: erreicht, 50 min früher")
    s.weiter(bis="05:55")
    a = bt(s)[1]
    s.weiter(bis="06:00")
    b = bt(s)[1]
    s.weiter(bis="08:00")
    pruefe(a == 21.0 and b == 22.0 and bt(s)[1] == 16.0, "Mindesttemperatur wird bis zur Heizphase gehalten; 06:00 → 22 °C; 08:00 → 16 °C (Haltezeit vorbei)")
    s.weiter(bis="14:55")
    a = bt(s)[1]
    s.weiter(bis="15:05")
    b = bt(s)[1]
    s.weiter(bis="16:00")
    pruefe(a == 16.0 and b == 21.5 and bt(s)[1] == 22.0,
           "Zweiter Termin am selben Tag (15:45 mind. 21,5 °C): Faktor nach frühem Erreichen 0,9 → Start 15:05, 16:00 Heizphase 22 °C")
    s = raum(zeit(1, 1), vorheizen=True, temp=18.5, extra=M)
    s.weiter(bis="05:55")
    pruefe(bt(s)[1] == 16.0 and n(s, "climate.set_temperature") <= 1, "Dienstag: Termin gilt nur mittwochs – keine Änderung")
    s = raum(zeit(2, 1), vorheizen=True, temp=18.5, profil="Übergang", extra=M)
    s.weiter(bis="04:25")
    pruefe(bt(s)[1] == 17.0, "Profil Übergang: Termine des Profils Komfort gelten nicht")

    Zt = dict(vorheizen_aktiv=False, zieltermin_aktiv=True, komfort_z1_aktiv=True, komfort_z1_tage=["sa"], komfort_z1_zeit="10:30:00", komfort_z1_temp=22.5,
              komfort_m1_aktiv=True, komfort_m1_tage=["sa"], komfort_m1_zeit="07:00:00", komfort_m1_temp=21)
    s = raum(zeit(5, 3), vorheizen=True, temp=21.0, extra=Zt)
    s.weiter(bis="07:05")
    pruefe(bt(s)[1] == 16.0, "Nur Zieltemperatur eingeschaltet: ein eingetragener Mindesttemperatur-Termin bleibt wirkungslos")
    s.weiter(bis="08:40")
    a = bt(s)[1]
    s.weiter(bis="08:45")
    b = bt(s)[1]
    s.weiter(bis="09:00")
    pruefe(a == 16.0 and b == 22.5 and bt(s)[1] == 22.5, "Samstag 10:30 spätestens 22,5 °C: ab 08:45 Sollwert 22,5 °C, auch in der Heizphase ab 09:00 (Soll 22)")
    s.weiter(bis="10:30")
    pruefe(s.s("input_text.vh_bericht").startswith("✘ Zieltemperatur 22.5 °C um 10:30 NICHT erreicht (Ist 21.0 °C)"), "Bewertung 10:30: ehrlich „NICHT erreicht“ (Raum blieb bei 21 °C)")
    s.weiter(bis="11:25")
    a = bt(s)[1]
    s.weiter(bis="11:30")
    b = bt(s)[1]
    s.weiter(bis="12:00")
    pruefe(a == 22.5 and b == 22.0 and bt(s)[1] == 16.0, "Zieltemperatur 60 min gehalten, 11:30 zurück auf 22 °C, 12:00 Absenkung")
    s = raum(zeit(5, 8, 50), vorheizen=True, temp=21.0, extra=Zt)
    s.set("binary_sensor.f1", "on")
    s.weiter(minuten=3)
    pruefe(bt(s)[0] == "off", "Fenster offen während eines Zieltemperatur-Termins: Heizpause hat Vorrang")
    s.set("input_select.profil", "Aus")
    pruefe(bt(s)[1] == 5.0 and "abgebrochen" in s.s("input_text.vh_bericht"), "Profil Aus: Frostschutz, Termin abgebrochen")
    s = raum(zeit(5, 3), vorheizen=False, temp=21.0, extra=dict(Zt, zieltermin_aktiv=False))
    s.weiter(bis="11:00")
    pruefe(n(s, "climate.set_temperature") == 1 and bt(s)[1] == 22.0 and not s.warnungen,
           "Beide Funktionen aus: nur 16 → 22 °C um 09:00, keine Vorheiz-Helfer nötig")


def test_fenster():
    titel("Raumheizung 3 – Fenster und 10-Minuten-Fail-safe")
    s = raum(zeit(0, 6, 30))
    pruefe(bt(s) == ("heat", 22.0), "Start in der Heizphase: 22 °C")
    s.set("binary_sensor.f1", "on")
    pruefe(s.s("input_boolean.fstatus") == "on", "Fenster auf → Fensterstatus sofort an")
    s.weiter(sekunden=30)
    a = bt(s)[0]
    s.weiter(sekunden=30)
    pruefe(a == "heat" and bt(s)[0] == "off", "Heizpause erst nach 60 s (nach 30 s noch nicht)")
    pruefe("Fensterpause" in s.s("input_text.status") and "f=offen" in s.s("input_text.status"), "Status zeigt Fenster offen und Heizpause")
    s.set("binary_sensor.f1", "off")
    s.weiter(sekunden=90)
    a = bt(s)[0]
    s.weiter(sekunden=30)
    pruefe(s.s("input_boolean.fstatus") == "off" and a == "off" and bt(s) == ("heat", 22.0), "Fenster zu → nach 120 s wird weitergeheizt (22 °C)")
    k = [r for r in s.rufe if r[2] == "climate.set_temperature" and r[4].get("hvac_mode") == "off"]
    s.set("binary_sensor.f1", "on")
    s.weiter(sekunden=30)
    s.set("binary_sensor.f1", "off")
    s.weiter(minuten=5)
    pruefe(len([r for r in s.rufe if r[2] == "climate.set_temperature" and r[4].get("hvac_mode") == "off"]) == len(k), "Kurzes Lüften unter 60 s: keine Heizpause")

    s.set("binary_sensor.f1", "on")
    s.set("binary_sensor.f2", "unavailable")
    pruefe(s.s("input_boolean.fstatus") == "on" and s.s("timer.fausfall") == "active", "Fenster 1 offen, Kontakt 2 fällt aus: Sperre bleibt, 10-min-Frist startet")
    s.set("binary_sensor.f1", "off")
    pruefe(s.s("input_boolean.fstatus") == "on", "Fenster 1 zu, Kontakt 2 weiter ausgefallen: letzter Status (offen) bleibt während der Frist erhalten")
    s.weiter(minuten=10)
    pruefe(s.s("input_boolean.fstatus") == "off" and "heizung_fensterausfall_test" in s.meldungen, "Nach 10 min: Heizung freigegeben, einmalige Meldung mit fester ID")
    pruefe("binary_sensor.f2" in s.meldungen["heizung_fensterausfall_test"]["message"], "Meldung nennt den ausgefallenen Kontakt")
    s.set("binary_sensor.f1", "on")
    pruefe(s.s("input_boolean.fstatus") == "on" and s.s("timer.fausfall") == "idle", "Reale Offenmeldung trotz Ausfall hat Vorrang (ohne neue Frist)")
    s.set("binary_sensor.f1", "off")
    pruefe(s.s("input_boolean.fstatus") == "off", "Fenster wieder zu, Frist abgelaufen → sofort frei")
    s.set("binary_sensor.f2", "off")
    pruefe("heizung_fensterausfall_test" not in s.meldungen, "Kontakt 2 erholt: Meldung automatisch entfernt")

    s.set("binary_sensor.f2", "unavailable")
    ende = s.timer["timer.fausfall"]
    s.weiter(minuten=5)
    s.set("binary_sensor.f1", "unknown")
    pruefe(s.timer["timer.fausfall"] == ende, "Zweiter Ausfall während laufender Frist verlängert die Frist nicht")
    pruefe(s.s("input_boolean.fstatus") == "off" and bt(s)[0] == "heat", "Ausfall bei geschlossenen Fenstern sperrt die Heizung nicht")
    s.weiter(minuten=5)
    pruefe(s.s("timer.fausfall") == "idle" and "heizung_fensterausfall_test" in s.meldungen, "Frist läuft nach insgesamt 10 min ab, Meldung erscheint")
    s.set("binary_sensor.f1", "off")
    s.set("binary_sensor.f2", "off")
    pruefe("heizung_fensterausfall_test" not in s.meldungen and s.s("timer.fausfall") == "idle", "Beide Kontakte gültig: Meldung weg")

    s = raum(zeit(0, 6, 30), vor_start=lambda sim: sim.zustand("binary_sensor.f2", "unavailable"))
    pruefe(s.s("timer.fausfall") == "active" and s.s("input_boolean.fstatus") == "off", "Neustart mit ausgefallenem Kontakt: Frist startet, Heizung läuft")
    s.reload()
    pruefe(len([r for r in s.rufe if r[2] == "timer.start"]) == 1, "Automations-Reload während laufender Frist startet sie nicht neu")

    def offen(sim):
        sim.zustand("binary_sensor.f1", "on")
        sim.zustand("input_boolean.fstatus", "on")
    s = raum(zeit(0, 6, 30), vor_start=offen)
    pruefe(bt(s)[0] == "off", "Neustart bei offenem Fenster: Heizpause sofort (ohne 60 s Wartezeit)")
    s.weiter(minuten=5)
    pruefe(bt(s)[0] == "off" and "Fensterpause" in s.s("input_text.status"), "… und die Pause bleibt bestehen (auch 5 min nach dem Neustart)")
    s.set("binary_sensor.f1", "off")
    s.weiter(minuten=1)
    a = bt(s)[0]
    s.weiter(minuten=2)
    pruefe(a == "off" and bt(s) == ("heat", 22.0), "… Fenster zu: nach dem Nachlauf (120 s) wird wieder geheizt")

    s = raum(zeit(0, 6, 30))
    s.setze("climate.bt", "off")
    s.set("sensor.raum", 19.2)
    pruefe(bt(s) == ("heat", 22.0), "Better Thermostat war aus anderem Grund aus (z. B. nach PV-Heizen), Fenster kurz zuvor geschlossen gemeldet: kein fälschlicher Nachlauf, es wird sofort geheizt")

    s = raum(zeit(0, 6, 30), extra=dict(fenster_reaktion="bt"))
    s.set("binary_sensor.f1", "on")
    s.weiter(minuten=2)
    a = bt(s)[0]
    s.weiter(minuten=2)
    pruefe(a == "heat" and "hz_bt_fenster_test" in s.meldungen, "Variante „Better Thermostat reagiert selbst“: Automation pausiert nicht; reagiert das BT nicht, kommt nach 3 min ein Hinweis")


def tausche(s, eid, datei, **neu):
    """Gerätewechsel: dieselbe Automation mit geänderten Eingaben (wie Bearbeiten der Blueprint-Instanz), danach Reload."""
    alt = next(a for a in s.autos if a.entity_id == eid)
    s.autos.remove(alt)
    Automation(s, eid, datei, dict(alt.eingaben, **neu))
    s.reload()


def test_geraetewechsel():
    titel("Gerätewechsel – nur die Blueprint-Instanz wird geändert, alle Helfer bleiben")
    s = raum(zeit(0, 6, 30))
    s.zustand("climate.bt_neu", "heat", temperature=7.0, current_temperature=20.0, hvac_action="idle", window_open=False)
    s.zustand("sensor.raum_neu", 20.0)
    s.zustand("binary_sensor.f_neu", "off")
    k_alt = sum(1 for r in s.rufe if "climate.bt" in r[3])
    tausche(s, "automation.rh", RH, better_thermostat="climate.bt_neu", raumfuehler="sensor.raum_neu",
            fensterkontakte=["binary_sensor.f_neu", "binary_sensor.f2"])
    pruefe((s.s("climate.bt_neu"), s.attr("climate.bt_neu", "temperature")) == ("heat", 22.0), "Neues Better Thermostat erhält sofort den aktuellen Sollwert 22 °C")
    st = s.s("input_text.status")
    pruefe("bt=climate.bt_neu" in st and "t=20.0" in st, "Status für die Karte nennt das neue Thermostat und den Wert des neuen Raumfühlers")
    s.set("binary_sensor.f1", "on")
    s.weiter(minuten=2)
    a = s.s("climate.bt_neu")
    s.set("binary_sensor.f1", "off")
    s.set("binary_sensor.f_neu", "on")
    s.weiter(minuten=2)
    pruefe(a == "heat" and s.s("climate.bt_neu") == "off" and s.s("input_boolean.fstatus") == "on",
           "Alter Fensterkontakt wirkungslos, neuer Fensterkontakt pausiert die Heizung")
    pruefe(sum(1 for r in s.rufe if "climate.bt" in r[3]) == k_alt, "Das alte Thermostat erhält keinen einzigen Befehl mehr")

    s = pv_start()
    s.zustand("remote.klima2", "on")
    pruefe("s=remote.klima|g=klima|h=heizen_24|ha=heizen_24_off" in s.s("input_text.ircfg"), "Klimaautomatik veröffentlicht Sender und Heizbefehle im gemeinsamen Helfer")
    tausche(s, "automation.kl", KL, klima_sender="remote.klima2")
    pruefe("s=remote.klima2|" in s.s("input_text.ircfg"), "Broadlink in der Klimaautomatik getauscht: gemeinsamer Helfer nennt sofort den neuen Sender")
    s.weiter(minuten=9)
    pruefe("heizen_24" in ir(s) and s.ir_sender[ir(s).index("heizen_24")] == "remote.klima2",
           "PV-Überschussheizen sendet den Heizbefehl über den neuen Broadlink – ohne Änderung an der PV-Automation")
    s.setze("remote.klima", "unavailable")
    k = len(ir(s))
    s.set("input_boolean.pv_f_heizfreigabe", "off")
    s.weiter(minuten=1)
    pruefe("heizen_24_off" in ir(s)[k:] and set(s.ir_sender[k:]) == {"remote.klima2"},
           "PV-Heizen beenden: „Heizen aus“ läuft ebenfalls über den neuen Broadlink (der alte darf fehlen)")

    s = raum(zeit(0, 14), klima=True, pv=True, profil="Sommer", aussen=25.0, temp=24.5)
    tausche(s, "automation.kl", KL, befehl_kuehlen="kuehlen_{stufe}_{luefter}", befehl_kuehlen_zusatz="", luefter="hoch", befehl_heizen="heizen_24_{luefter}")
    s.set("input_select.kmodus", "Automatik Kühlen")
    pruefe(ir(s)[-1] == "kuehlen_17_hoch" and "h=heizen_24_hoch" in s.s("input_text.ircfg"),
           "Lüfterstufe im Befehlsnamen: Kühlen sendet kuehlen_17_hoch, PV-Heizbefehl heißt heizen_24_hoch")
    s = raum(zeit(0, 14), klima=True, profil="Sommer", aussen=25.0, temp=24.5)
    tausche(s, "automation.kl", KL, befehl_kuehlen_zusatz="eco_{stufe}, display_off")
    s.set("input_select.kmodus", "Automatik Kühlen")
    pruefe(ir(s) == ["power_17", "eco_17", "display_off"] and s.s("input_boolean.kaktiv") == "on",
           "Mehrere Zusatzbefehle (Muster Schlafzimmer): power_17, eco_17, display_off nacheinander gesendet")

    titel("Broadlink nicht erreichbar oder Befehl fehlt – kein vorgetäuschter Erfolg")
    s = raum(zeit(0, 14), klima=True, profil="Sommer", aussen=25.0, temp=24.5)
    s.setze("remote.klima", "unavailable")
    s.set("input_select.kmodus", "Automatik Kühlen")
    pruefe(ir(s) == [] and s.s("input_boolean.kaktiv") == "off" and "hz_klima_ir_test" in s.meldungen,
           "Broadlink nicht erreichbar: kein Befehl, „Klima aktiv“ bleibt aus, dauerhafte Meldung")
    s.setze("remote.klima", "on")
    s.set("sensor.raum", 24.6)
    pruefe(ir(s) == ["power_17", "eco_17"] and s.s("input_boolean.kaktiv") == "on", "Broadlink wieder da: nächste Auswertung sendet den Befehl")
    s = raum(zeit(0, 14), klima=True, profil="Sommer", aussen=25.0, temp=24.5)
    s.setze("remote.klima", "off")
    s.set("input_select.kmodus", "Automatik Kühlen")
    pruefe(ir(s) == [] and s.s("input_boolean.kaktiv") == "off", "Broadlink ausgeschaltet (remote = off): ebenfalls kein Befehl und kein „aktiv“")
    s = raum(zeit(0, 14), klima=True, profil="Sommer", aussen=25.0, temp=24.5)
    s.ir_defekt = {"power_17"}
    s.set("input_select.kmodus", "Automatik Kühlen")
    pruefe(ir(s) == [] and s.s("input_boolean.kaktiv") == "off", "Benötigter IR-Befehl nicht angelernt (Fehler beim Senden): Lauf bricht ab, „Klima aktiv“ bleibt aus")
    s = pv_start()
    s.setze("remote.klima", "unavailable")
    s.weiter(minuten=12)
    pruefe("heizen_24" not in ir(s) and s.s("input_boolean.pv_f_heizbefehl") == "off" and bt(s)[0] == "heat",
           "PV-Heizen bei nicht erreichbarem Broadlink: kein Start, Heizkörper bleiben in Betrieb")


def test_boost():
    titel("Raumheizung 4 – Boost")
    s = raum(zeit(0, 9))
    s.set("input_number.boost", "24.0")
    pruefe(s.s("timer.boost") == "active" and bt(s)[1] == 24.0, "Boost 24 °C in der Absenkung: Timer läuft, 24 °C")
    s.weiter(minuten=119)
    a = bt(s)[1]
    s.weiter(minuten=1)
    pruefe(a == 24.0 and s.s("timer.boost") == "idle" and bt(s)[1] == 16.0, "Nach 2 Stunden endet der Boost → zurück auf 16 °C")
    s.set("input_number.boost", "23.0")
    s.set("input_select.profil", "Übergang")
    pruefe(s.s("timer.boost") == "idle" and bt(s)[1] == 17.0, "Profilwechsel beendet den Boost → Übergang-Absenkung 17 °C")
    s.set("input_number.boost", "21.0")
    a = s.s("timer.boost")
    s.set("input_number.boost", "5.0")
    pruefe(a == "active" and s.s("timer.boost") == "idle" and bt(s)[1] == 17.0, "Boostwert zurück auf Frostschutz beendet den Boost")
    s.set("input_select.profil", "Aus")
    s.set("input_number.boost", "22.0")
    pruefe(s.s("timer.boost") == "idle" and bt(s)[1] == 5.0, "Im Profil Aus startet kein Boost")
    s.set("input_select.profil", "Komfort")
    s.setze("input_number.boost", "24.0", _neu=True)
    s.leere()
    pruefe(s.s("timer.boost") == "idle" and bt(s)[1] == 16.0, "Wiederherstellung des Boostwerts nach Neustart startet keinen Boost")


def test_prioritaeten():
    titel("Raumheizung 5 – Prioritäten und Sperren")
    s = raum(zeit(0, 17), pv=False)
    s.zustand("input_boolean.lease_flag", "off")
    pruefe(bt(s)[1] == 22.0, "Heizphase 22 °C")
    s.set("input_number.boost", "24.0")
    s.set("sensor.aussen", 21.0)
    a = bt(s)[1]
    s.set("sensor.aussen", 10.0)
    pruefe(a == 5.0 and bt(s)[1] == 24.0, "Außensperre (> 20 °C) schlägt Boost; danach wieder Boost 24 °C")
    s.set("input_boolean.haus_aus", "on")
    pruefe(bt(s)[1] == 5.0, "Globaler Schalter „Heizung Aus“ → Frostschutz trotz Boost und Heizphase")
    s.set("input_select.profil", "Übergang")
    pruefe(s.s("input_boolean.haus_aus") == "off" and s.s("timer.boost") == "idle" and bt(s)[1] == 21.0,
           "Bewusster Profilwechsel: Schalter aus, Boost beendet, Übergang 21 °C")
    s.set("input_select.profil", "Sommer")
    a = bt(s)[1]
    s.set("input_select.profil", "Aus")
    pruefe(a == 5.0 and bt(s)[1] == 5.0, "Sommer und Aus → Frostschutz 5 °C")
    s.set("input_select.profil", "Komfort")
    s.set("climate.bt", "unavailable")
    k = n(s, "climate.set_temperature")
    s.weiter(bis="22:00")
    a = n(s, "climate.set_temperature")
    s.set("climate.bt", "heat")
    pruefe(a == k and bt(s)[1] == 16.0, "Better Thermostat nicht verfügbar: kein Befehl; bei Rückkehr sofort aktueller Sollwert (16 °C)")
    s.set("sensor.raum", "unavailable")
    pruefe("t=19.0" in s.s("input_text.status"), "Raumfühler nicht verfügbar: Temperatur des Better Thermostat wird verwendet")
    s.set("sensor.aussen", "unavailable")
    pruefe(bt(s)[1] == 16.0, "Außentemperatur nicht verfügbar: keine Außensperre, normaler Betrieb")

    s = raum(zeit(0, 17), modus="test")
    s.set("input_number.boost", "24.0")
    s.set("binary_sensor.f1", "on")
    s.weiter(minuten=3)
    pruefe(n(s, "climate.set_temperature") == 0 and s.s("timer.boost") == "idle" and bt(s) == ("heat", 16.0),
           "Testbetrieb: kein Befehl an Better Thermostat, kein Boost-Timer")
    pruefe("m=test" in s.s("input_text.status") and "z=22.0" in s.s("input_text.status"), "Testbetrieb: berechneter Sollwert steht im Status")

    s = raum(zeit(0, 16, 30), profil="Sommer", extra=dict(sommer_heizen=True, sommer_soll=19, sommer_absenk=16, sommer_wt1_aktiv=True,
                                                         sommer_wt1_von="17:00:00", sommer_wt1_bis="18:00:00"))
    a = bt(s)[1]
    s.weiter(bis="17:00")
    pruefe(a == 16.0 and bt(s)[1] == 19.0, "Sommer mit „Im Sommer heizen“: eigene Phase 17:00 → 19 °C")
    s = raum(zeit(0, 17), fenster=False, boost=False)
    pruefe(bt(s) == ("heat", 22.0) and "f=ohne" in s.s("input_text.status") and "h=heat" in s.s("input_text.status") and n(s, "timer.start") == 0,
           "Raum ohne Fenster und ohne Boost: läuft ohne diese Helfer, heizt normal (keine Scheinpause)")


# =============================================================================== Blueprint 2
def test_klima():
    titel("Klimaautomatik")
    s = raum(zeit(0, 14), klima=True, profil="Komfort", aussen=25.0, temp=24.5)
    s.set("input_select.kmodus", "Automatik Kühlen")
    pruefe(ir(s) == ["power_off"] and s.s("input_select.kmodus") == "Aus", "Heizprofil Komfort: Kühlen nicht erlaubt → Klima aus, Modus zurück auf Aus")

    s = raum(zeit(0, 14), klima=True, profil="Sommer", aussen=25.0, temp=24.5)
    pruefe(bt(s)[1] == 5.0, "Profil Sommer: Heizung auf Frostschutz")
    s.set("input_select.kmodus", "Automatik Kühlen")
    pruefe(ir(s) == ["power_17", "eco_17"] and s.s("input_number.kstufe") == "17.0" and s.s("input_boolean.kaktiv") == "on",
           "Automatik bei 24,5 °C (Ziel 22): Kühlbefehl Stufe 17 plus Zusatzbefehl")
    s.set("sensor.raum", 24.4)
    pruefe(len(ir(s)) == 2, "Kleine Temperaturänderung: kein erneutes Senden")
    s.set("sensor.raum", 23.5)
    pruefe(ir(s)[-2:] == ["power_18", "eco_18"], "23,5 °C → Stufe 18")
    s.set("sensor.raum", 22.2)
    pruefe(ir(s)[-2:] == ["power_18", "eco_18"], "22,2 °C liegt unter der Einschaltschwelle 22,5: Stufe bleibt")
    s.set("sensor.raum", 21.8)
    pruefe(ir(s)[-1] == "power_off" and s.s("input_boolean.kaktiv") == "off" and s.s("input_select.kmodus") == "Automatik Kühlen",
           "21,8 °C (Ziel − 0,2): Klima aus, Automatik bleibt gewählt")
    s.set("sensor.raum", 22.4)
    k = len(ir(s))
    s.set("sensor.raum", 22.6)
    pruefe(len(ir(s)) == k + 2 and ir(s)[-2] == "power_20", "Hysterese: erst ab 22,5 °C wieder ein (Stufe 20)")

    s.set("sensor.raum", 24.5)
    s.set("binary_sensor.f1", "on")
    s.weiter(minuten=2, sekunden=30)
    a = ir(s)[-1]
    s.weiter(sekunden=30)
    pruefe(a != "power_off" and ir(s)[-1] == "power_off" and s.s("input_text.kvor") == "Automatik Kühlen|17|22.0" and s.s("input_boolean.kaktiv") == "off",
           "Fenster 3 min offen: Klima pausiert, Modus/Stufe/Ziel gemerkt")
    s.set("binary_sensor.f1", "off")
    pruefe(ir(s)[-2:] == ["power_17", "eco_17"] and s.s("input_boolean.kaktiv") == "on" and s.s("input_text.kvor") == "",
           "Fenster zu: Automatik wiederhergestellt und sofort weitergekühlt")
    s.set("input_number.kmanuell", "19.0")
    pruefe(ir(s)[-2:] == ["power_19", "eco_19"] and s.s("input_select.kmodus") == "Manuell Kühlen", "Manuelle Stufe 19 → Befehl gesendet, Modus Manuell Kühlen")
    s.set("input_select.kmodus", "Aus")
    pruefe(ir(s)[-1] == "power_off" and s.s("input_boolean.kaktiv") == "off", "Modus Aus → Klima aus")
    s.set("input_select.kmodus", "Automatik Kühlen")
    k = len(ir(s))
    s.set("sensor.raum", "unavailable")
    s.set("sensor.raum", 25.0)
    pruefe(len(ir(s)) == k and any("nicht verfügbar" in (m or "") for _, _, m in s.logbuch), "Raumfühler nicht verfügbar: Abbruch ohne Befehl, Logbucheintrag")
    s.set("sensor.raum", 24.9)
    s.set("sensor.aussen", 15.0)
    pruefe(ir(s)[-1] == "power_off" and s.s("input_select.kmodus") == "Aus", "Außentemperatur unter 16 °C: Klima aus")
    s.set("sensor.aussen", 18.0)
    s.set("input_select.kmodus", "Automatik Kühlen")
    s.set("input_select.profil", "Komfort")
    pruefe(ir(s)[-1] == "power_off" and s.s("input_select.kmodus") == "Aus" and bt(s)[1] in (16.0, 22.0), "Wechsel auf Heizprofil Komfort: Klima aus, Heizung übernimmt")

    def an(sim):
        sim.zustand("input_boolean.kaktiv", "on")
        sim.zustand("input_number.kstufe", "18.0")
        sim.zustand("input_select.kmodus", "Automatik Kühlen", options=["Aus", "Automatik Kühlen", "Manuell Kühlen"])
    s = raum(zeit(0, 14), klima=True, profil="Sommer", aussen=25.0, temp=24.5)
    an(s)
    s.start()
    pruefe(ir(s) == ["power_18", "eco_18"], "Neustart, Klima war vorher an: einmalige Wiederherstellung mit der letzten Stufe 18")
    s = raum(zeit(0, 14), klima=True, profil="Sommer", aussen=25.0, temp=24.5)
    pruefe(ir(s) == [], "Neustart, Klima war vorher aus: kein IR-Befehl")
    s = raum(zeit(0, 14), klima=True, profil="Sommer", aussen=25.0, temp=24.5, modus="test")
    s.set("input_select.kmodus", "Automatik Kühlen")
    pruefe(ir(s) == [] and any("(Test)" in (nm or "") for _, nm, _ in s.logbuch), "Testbetrieb: Entscheidung nur im Logbuch, kein IR-Befehl")


# =============================================================================== Blueprint 3 + Zusammenspiel
def pv_start(**kw):
    """Raum mit allen drei Automationen bis zum laufenden PV-Heizen (HEIZEN gesendet)."""
    s = raum(zeit(0, 12), klima=True, pv=True, temp=21.0, aussen=10.0, **kw)
    s.set("input_boolean.pv_f_heizfreigabe", "on")
    return s


def test_pv():
    titel("PV-Überschussheizen und Zusammenspiel der drei Automationen")
    s = pv_start()
    pruefe(s.s("timer.pv_t_startfrist") == "active" and "5 Minuten bestaetigen" in s.s("input_text.pv_status") and bt(s)[0] == "heat",
           "Startbedingungen erfüllt: 5-min-Bestätigung läuft, Heizung unverändert")
    s.weiter(minuten=4, sekunden=30)
    a = ir(s)
    s.weiter(sekunden=30)
    pruefe(a == [] and bt(s)[0] == "off", "Nach 5 min: Raumheizung schließt die Heizkörper (BT aus)")
    pruefe(ir(s) == ["heizen_24"] and s.s("input_boolean.pv_f_heizbefehl") == "on" and s.s("input_boolean.pv_f_auftrag") == "off",
           "Heizkörper bestätigt geschlossen → Klimaanlage heizt (IR heizen_24)")
    pruefe(s.s("input_number.pv_starttemp") == "21.0" and s.s("timer.pv_t_waermepruefung") == "active", "Starttemperatur gemerkt, Wärmeprüfung läuft")
    s.weiter(minuten=6)
    pruefe(bt(s)[0] == "off" and s.s("timer.pv_t_freigabe") == "active", "Befristete Freigabe wird alle 30 s erneuert, Heizkörper bleiben zu")
    s.set("sensor.raum", 21.5)
    s.weiter(minuten=36)
    pruefe(ir(s) == ["heizen_24"] and s.s("input_number.pv_starttemp") == "21.5", "Wärmeprüfung nach 40 min bestanden (kein erneutes Senden), neue Referenz 21,5 °C")
    s.set("sensor.raum", 24.0)
    pruefe(ir(s)[-1] == "heizen_24_off" and s.s("input_boolean.pv_f_heizbefehl") == "off" and s.s("timer.pv_t_schaltpause") == "active" and bt(s)[0] == "off",
           "Ziel 24 °C erreicht: Klima-Pause, Heizkörper bleiben geschlossen")
    s.set("sensor.raum", 23.0)
    s.weiter(minuten=11)
    pruefe(ir(s)[-1] == "heizen_24" and ir(s).count("heizen_24") == 2, "Raum fällt auf 23 °C: nach Schaltpause und erneuter Bestätigung heizt die Klima wieder")
    s.set("sensor.netz", -500)
    s.weiter(minuten=9, sekunden=30)
    a = ir(s)[-1]
    s.weiter(minuten=1)
    pruefe(a == "heizen_24" and ir(s)[-1] == "heizen_24_off" and s.s("input_boolean.pv_f_regelung") == "off",
           "Netzbezug > 300 W wird 10 min toleriert, dann endet PV-Heizen")
    pruefe(bt(s)[0] == "heat" and s.s("timer.pv_t_sperre") == "active", "Raumheizung übernimmt sofort wieder; 30-min-Wiederanlaufsperre")

    s = pv_start()
    s.weiter(minuten=6)
    s.set("input_select.kmodus", "Automatik Kühlen")
    pruefe(ir(s)[-2:] == ["heizen_24_off", "power_off"], "Klimabedienung während PV-Heizen: zuerst PV-Rückgabe (heizen_24_off), dann der Bedienbefehl")
    pruefe(s.s("input_boolean.pv_f_heizfreigabe") == "off" and s.s("input_boolean.pv_f_regelung") == "off" and bt(s)[0] == "heat",
           "PV-Freigabe aus, Heizkörper wieder freigegeben")

    s = pv_start()
    s.weiter(minuten=6)
    s.set("automation.pv", "off")
    pruefe(ir(s)[-1] == "power_off" and s.s("input_boolean.pv_f_heizbefehl") == "off" and "hz_pv_notrueckgabe_test" in s.meldungen,
           "PV-Automation fällt aus: Klimaautomatik schaltet die Klimaanlage ab und meldet es")
    pruefe(bt(s)[0] == "heat" and s.s("input_boolean.pv_f_heizfreigabe") == "off", "Heizkörper wieder freigegeben, PV-Freigabe zurückgenommen")

    s = pv_start()
    s.weiter(minuten=6)
    s.set("automation.pv", "off")
    s.set("automation.pv", "on")
    s.autos = [a for a in s.autos if a.entity_id != "automation.kl"]
    s2 = pv_start()
    s2.weiter(minuten=6)
    s2.autos = [a for a in s2.autos if a.entity_id == "automation.rh"]
    s2.weiter(minuten=2, sekunden=30)
    pruefe(bt(s2)[0] == "heat", "PV- und Klimaautomatik hängen beide: Raumheizung öffnet die Heizkörper allein nach Ablauf der 2-min-Freigabe")

    s = raum(zeit(0, 12), klima=True, pv=True, temp=21.0, aussen=10.0)
    s.ir_defekt.add("heizen_24")
    s.set("input_boolean.pv_f_heizfreigabe", "on")
    s.weiter(minuten=6)
    pruefe("heizen_24" not in ir(s) and s.s("input_boolean.pv_f_fehler") == "on" and s.s("input_boolean.pv_f_heizfreigabe") == "off",
           "IR-Senden schlägt fehl: PV gesperrt (IR-Fehler), Freigabe aus")
    pruefe(bt(s)[0] == "heat" and "hz_pv_ir_fehler_test" in s.meldungen and s.s("input_boolean.pv_f_auftrag") == "off",
           "Heizkörper wieder freigegeben, dauerhafte Meldung, kein offener Auftrag")

    s = pv_start()
    s.weiter(minuten=6)
    s.set("binary_sensor.f1", "on")
    pruefe(ir(s)[-1] == "heizen_24_off" and s.s("input_boolean.pv_f_regelung") == "off", "Fenster auf während PV-Heizen: PV endet sofort")

    s = pv_start()
    s.weiter(minuten=6)
    s.start()
    pruefe(ir(s)[-1] == "heizen_24_off" and s.s("input_boolean.pv_f_regelung") == "off" and bt(s)[0] == "heat",
           "Neustart während PV-Heizen: Sitzung wird beendet, normale Heizung läuft")

    s = pv_start(trv=False)
    s.weiter(minuten=5)
    a = bt(s)[0]
    s.weiter(minuten=8, sekunden=30)
    pruefe(a == "off" and "heizen_24" not in ir(s) and bt(s)[0] == "heat" and s.s("timer.pv_t_sperre") == "active",
           "Heizkörper schließen nicht innerhalb von 8 min: kein Klimastart, Heizung zurückgegeben")

    s = pv_start()
    s.weiter(minuten=6)
    s.herzschlag[:] = ["sensor.raum", "sensor.aussen"]
    s.weiter(minuten=3, sekunden=30)
    pruefe(ir(s)[-1] == "heizen_24_off" and bt(s)[0] == "heat", "Energiedaten älter als 3 min: PV endet, Heizung übernimmt")

    for name, aendern, text in (("Batterie 90 %", lambda x: x.set("sensor.soc", 90), "Akku unter 95 Prozent"),
                                ("Profil Sommer", lambda x: x.set("input_select.profil", "Sommer"), "Heizprofil erlaubt kein PV-Heizen"),
                                ("IR nicht geprüft", lambda x: x.set("input_boolean.pv_f_ir_geprueft", "off"), "IR-Prueffreigabe fehlt"),
                                ("Klima kühlt (Modus nicht Aus)", lambda x: x.setze("input_select.kmodus", "Manuell Kühlen"), "Klimabedienung hat Vorrang")):
        s = raum(zeit(0, 12), klima=True, pv=True, temp=21.0, aussen=10.0)
        if name.startswith("Klima"):
            s.autos = [a for a in s.autos if a.entity_id != "automation.kl"]
        aendern(s)
        s.set("input_boolean.pv_f_heizfreigabe", "on")
        s.weiter(minuten=7)
        pruefe(ir(s) == [] and text in s.s("input_text.pv_status") and bt(s)[0] == "heat", f"Kein Start bei: {name} („{text}“)")

    s = raum(zeit(0, 12), klima=True, pv=True, temp=21.0, aussen=10.0)
    s.set("automation.kl", "off")
    s.set("input_boolean.pv_f_heizfreigabe", "on")
    s.weiter(minuten=7)
    pruefe(ir(s) == [] and "Sicherheitsautomation deaktiviert" in s.s("input_text.pv_status"), "Kein Start, wenn die Klimaautomatik ausgeschaltet ist")


if __name__ == "__main__":
    for t in (test_zeitplan, test_tagesprogramme, test_vorheizen, test_termine, test_fenster, test_boost, test_prioritaeten, test_klima, test_pv, test_geraetewechsel):
        t()
    titel("Sauberkeit der Läufe")
    warn = [w for s in SIMS for w in s.warnungen]
    abbr = [f"{a.datei}: {x}" for s in SIMS for a in s.autos for x in a.abbrueche if "IR-Senden fehlgeschlagen" not in x]
    pruefe(not warn, f"keine Template-Warnungen (undefinierte Variablen): {len(warn)}" + ("  z. B. " + warn[0] if warn else ""))
    pruefe(not abbr, f"keine unerwartet abgebrochenen Läufe: {len(abbr)}" + ("  z. B. " + abbr[0] if abbr else ""))
    laeufe = sum(a.laeufe for s in SIMS for a in s.autos)
    ok = sum(1 for e, _ in ERG if e)
    print(f"\nGesamttest: {ok}/{len(ERG)} Prüfungen bestanden · {len(SIMS)} simulierte Räume · {laeufe} Automationsläufe")
    for e, t in ERG:
        if not e:
            print("   NICHT BESTANDEN:", t)
    sys.exit(0 if ok == len(ERG) else 1)
