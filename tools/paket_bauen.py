#!/usr/bin/env python3
"""Baut das fertige Installationspaket:  custom_components/heizung_universal/  (von HACS gelesen) und die ZIP-Datei in paket/.

Quellen: integration/heizung_universal (Oberfläche), assistent/ (Einrichtungslogik), blueprints/ (die drei Blueprints).
Die Texte der Oberfläche stehen unten in TEXTE (Deutsch) und in tools/texte_en.py (Englisch) und werden als Übersetzungsdateien geschrieben.
"""
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

BASIS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from texte_en import TEXTE as TEXTE_EN  # noqa: E402

ZIEL = BASIS / "custom_components" / "heizung_universal"
VERSION = json.loads((BASIS / "integration/heizung_universal/manifest.json").read_text(encoding="utf-8"))["version"]
# Bereits veröffentlichte Fassungen: deren ZIP wird nie neu geschrieben
VERSIONEN_FREIGEGEBEN = set()

LERNEN = {
    "lernen_auswahl": {
        "title": "IR-Befehle – je Befehl wählen",
        "description": ("Raum **{raum}** · IR-Sender `{sender}` · Gerätename `{geraet}`\n\n{stand}\n\n"
                        "Die Befehle gehören nur zu diesem Raum und diesem Sender. Für jeden Befehl gilt:\n"
                        "- **nicht angekreuzt** = vorhandenen Befehl verwenden (es wird nichts gesendet und nichts angelernt)\n"
                        "- **„neu anlernen“** = Befehl mit `remote.learn_command` über diesen Sender anlernen und danach testen\n"
                        "- **„testen“** = vorhandenen Befehl mit `remote.send_command` testweise senden\n\n"
                        "Viele Klimaanlagen senden bei jedem Tastendruck den **vollständigen Zustand** (Modus, Temperatur, Lüfter). Stellen Sie dann die "
                        "Fernbedienung so ein, dass der letzte Tastendruck genau den gewünschten Zustand herstellt."),
        "data": {"befehle": "Neu anlernen", "testen": "Vorhandenen Befehl testweise senden",
                 "ueberschreiben": "Bereits vorhandene Befehle dürfen durch das Anlernen ersetzt werden"},
        "data_description": {"ueberschreiben": "Ohne dieses Häkchen wird kein vorhandener Befehl verändert."}},
    "lernen": {
        "title": "Befehl {nr} von {anzahl} anlernen",
        "description": ("**{befehl}** – {bedeutung}\n\n1. Fernbedienung vorbereiten (ein Schritt vor dem gewünschten Zustand).\n"
                        "2. Unten „Jetzt anlernen“ wählen und auf **Senden** klicken.\n"
                        "3. Sobald am IR-Sender `{sender}` die Lampe leuchtet: Fernbedienung auf den Sender richten und die Taste drücken (innerhalb von 30 Sekunden).\n\n"
                        "Verwendet wird die Home-Assistant-Aktion `remote.learn_command`."),
        "data": {"aktion": "Aktion"}},
    "lernen_test": {
        "title": "Befehl testen",
        "description": ("**{befehl}** ({bedeutung}) {herkunft}.\n\nTesten Sie den Befehl mit der Aktion `remote.send_command` über `{sender}` und prüfen Sie, "
                        "ob die Klimaanlage im Raum **{raum}** richtig reagiert – so ist sichergestellt, dass der Befehl zum richtigen Raum gehört.\n\n{status}"),
        "data": {"aktion": "Aktion"}},
}
KARTE = {
    "dashboard": {"title": "Dashboard-Karte – Dashboards",
                  "description": ("In welche Dashboards soll die Raumkarte eingefügt werden? Es können mehrere gewählt werden. Für jedes gewählte Dashboard folgen "
                                  "Ansicht, Bereich, Position und Design – die Karte wird jeweils passend zu den vorhandenen Karten gestaltet."),
                  "data": {"dashboards": "Dashboards"}},
    "ansicht": {"title": "{dashboard} – Ansicht", "description": ("In welcher Ansicht von **{dashboard}** soll die Karte stehen?\n\n"
                                                                    "★ = in dieser Ansicht stehen schon Raumkarten (vorausgewählt)."), "data": {"ansicht": "Ansicht"}},
    "platz": {"title": "{dashboard} – Bereich",
              "description": ("Aufbau der Ansicht **{ansicht}** (★ = hier stehen schon Raumkarten):\n\n{uebersicht}\n\n"
                              "Wählen Sie den Bereich, in dem die Karte stehen soll. Empfohlene Bereiche stehen oben in der Liste und sind vorausgewählt; "
                              "jeder andere Bereich ist ebenso möglich – auch Stapel, Raster und Tabdeck-Tabs."),
              "data": {"platz": "Bereich"}},
    "position": {"title": "{dashboard} – Position und Design",
                 "description": ("**{ansicht} › {platz}**\n\n{bild}\n\nVorgeschlagenes Design (aus den vorhandenen Karten erkannt): **{erkannt}**. "
                                 "Die Karte lässt sich später im Dashboard-Editor verschieben oder über „Konfigurieren“ neu platzieren."),
                 "data": {"position": "Position der Karte", "design": "Design der Karte"}},
}
FEHLER = {
    "kein_profil": "Bitte mindestens ein Heizprofil auswählen.",
    "pflichtfeld": "Bitte die erforderlichen Geräte bzw. Sensoren auswählen – oder unten „Zurück zum vorherigen Schritt“ wählen.",
    "pv_braucht_klima": "PV-Überschussheizen benötigt die Klimaautomatik dieses Raums.",
    "heizstufe_bereich": "Die Heizstufe beim PV-Heizen muss zwischen „Heizstufen von“ und „Heizstufen bis“ liegen.",
    "pv_braucht_ir": "PV-Überschussheizen braucht eine Klimaanlage mit IR-Sender (eine Steckdose kann nicht auf Heizen umschalten).",
    "zeit_gleich": "Beginn und Ende einer Heizzeit dürfen nicht gleich sein.",
    "absenk_hoeher": "Die Absenktemperatur darf nicht über der Solltemperatur liegen.",
    "kein_tag": "Bitte mindestens einen Wochentag wählen.",
    "zu_viele": "Für dieses Profil sind bereits alle Termine dieser Art belegt (höchstens 4, im Sommerprofil 2).",
    "stufen": "Die niedrigste Stufe darf nicht über der höchsten liegen.",
    "sender_nicht_bereit": "Der IR-Sender ist nicht eingeschaltet oder nicht erreichbar (Zustand: {fehler}).",
    "senden_fehlgeschlagen": "Der Befehl konnte nicht gesendet werden: {fehler}",
    "lernen_fehlgeschlagen": "Anlernen fehlgeschlagen: {fehler}",
    "ueberschreiben": "Mindestens ein gewählter Befehl ist im Sender bereits vorhanden. Zum Ersetzen bitte das Häkchen setzen – oder den Befehl abwählen.",
    "nicht_bestaetigt": "Bitte das Anlegen bestätigen.",
    "kein_dashboard": "Bitte mindestens ein Dashboard auswählen.",
    "bt_belegt": "Dieses Better Thermostat wird bereits vom Raum „{belegt}“ dieser Integration gesteuert. Bitte zuerst diesen Raum entfernen.",
    "alt_pv_laeuft": "Nicht angelegt, es wurde nichts verändert: {fehler}",
    "anlegen_fehlgeschlagen": "Anlegen fehlgeschlagen – alles bereits Angelegte wurde wieder entfernt. Ursache: {fehler}",
}
ABBRUCH = {
    "already_configured": "Für diesen Raum gibt es bereits einen Eintrag.",
    "keine_ansicht": "Dieses Dashboard hat keine Ansicht.",
    "vorschau_fehlgeschlagen": "Home Assistant konnte nicht gelesen werden: {fehler}",
    "funktionen_fertig": "Funktionen geändert:\n{liste}\n\nFehler beim Aufräumen: {fehler}",
    "aendern_fehlgeschlagen": "Funktionen nicht geändert – der vorige Stand wurde wiederhergestellt. Ursache: {fehler}",
    "nichts_geaendert": "Es wurde keine Funktion geändert – nichts zu tun.",
    "alte_karten_fertig": "Entfernt (Dashboards vorher gesichert):\n{liste}\n\nNicht entfernt: {fehler}",
    "keine_alten_karten": "In den Dashboards wurden keine Karten der alten Steuerung dieses Raums gefunden.",
    "keine_auswahl": "Keine Karte ausgewählt – nichts entfernt.",
    "geraet_fertig": "{alt} wurde durch {neu} ersetzt in:\n{liste}{hinweis}",
    "keine_klima": "Für diesen Raum ist keine Klimaautomatik eingerichtet.",
    "ir_fertig": "IR-Anlernen beendet. Angelernte Befehle: {anzahl}.{freigabe}",
    "keine_klima_ir": ("Für diesen Raum ist keine Klimaanlage über einen IR-Sender eingerichtet. Bei einer Klimaanlage an einer Schaltsteckdose ist die "
                       "Steckdose schon das Stellglied (Automation „Klima <Raum>“)."),
    "steckdose_fertig": "{stand}\n\nGeänderte Automationen:\n{liste}",
    "steckdose_fehlgeschlagen": "Die Klima-Steckdose wurde nicht geändert: {fehler}",
    "karte_fertig": "Die Raumkarte wurde neu platziert (Anzahl Dashboards: {anzahl}).",
    "alt_zurueck_fertig": "Die alte Steuerung ist wieder eingeschaltet, die neue Steuerung dieses Raums ist angehalten. Meldungen: {fehler}",
    "alt_neu_fertig": "Die neue Steuerung ist wieder aktiv, die alte Steuerung ist erneut abgeschaltet und gekennzeichnet.",
    "alt_geloescht": "Die alte Steuerung wurde gelöscht. Sicherung: {datei}. Meldungen: {fehler}",
}
TEXTE = {
    "title": "Heizung Universal",
    "config": {
        "step": {
            "user": {
                "title": "Raum einrichten – Geräte",
                "description": ("Richtet die Heizungssteuerung für einen Raum ein. Am Ende werden alle benötigten Helfer, Zeitpläne, Automationen "
                                "(aus den drei Blueprints) und die Dashboard-Karte automatisch angelegt. Bestehende Automationen werden nicht verändert."),
                "data": {"raum_name": "Raumname", "bt": "Better Thermostat des Raums", "raumfuehler": "Externer Raumtemperaturfühler (optional)",
                         "aussen": "Außentemperatur", "haus_aus": "Globaler Schalter „Heizung Aus“ (optional)"},
                "data_description": {"bt": "Das Better Thermostat regelt weiterhin selbst die Heizkörperthermostate.",
                                     "raumfuehler": "Leer lassen, um den Messwert des Better Thermostat zu verwenden."}},
            "funktionen": {
                "title": "Raum {raum} – Funktionen",
                "description": "Alle Zusatzfunktionen sind vollständig enthalten und standardmäßig ausgeschaltet. Es werden nur die Helfer angelegt, die die gewählten Funktionen brauchen.",
                "data": {"profile": "Heizprofile (zusätzlich immer vorhanden: Sommer und Aus)", "sommer_heizen": "Im Profil Sommer zeitweise heizen (sonst Frostschutz)",
                         "zeitquelle": "Heizzeiten", "fenster_modus": "Fensterüberwachung", "boost": "Heizungs-Boost",
                         "vorheizen": "Vorausschauendes Vorheizen vor Heizbeginn", "mindest": "Mindesttemperatur zu festen Uhrzeiten erreichen",
                         "zieltermin": "Zieltemperatur zu festen Uhrzeiten erreichen", "klima": "Klimaautomatik", "klima_art": "Art der Klimaanlage",
                         "pv": "PV-Überschussheizen über die Klimaanlage", "karte": "Dashboard-Karte anlegen und platzieren"}},
            "profil": {
                "title": "Profil {profil} ({nr} von {anzahl})",
                "description": ("Jedes Profil hat drei unabhängige Tagesprogramme – Montag bis Freitag, Samstag, Sonntag – mit je bis zu drei Heizphasen. "
                                "Innerhalb einer eingeschalteten Heizphase gilt die Solltemperatur, sonst die Absenktemperatur. {art}\n\n"
                                "Liegt das Ende vor dem Beginn, läuft die Heizphase über Mitternacht."),
                "data": {"soll": "Solltemperatur", "absenk": "Absenktemperatur",
                         "vh": "Vor jedem Heizbeginn vorausschauend vorheizen", "vh_temp": "Mindesttemperatur, die zum Heizbeginn erreicht sein soll"},
                "sections": {tag: {"name": "{profil} – " + name,
                                   "data": {f"heizphase_{i}_{feld}": f"Heizphase {i} – {text}" for i in (1, 2, 3)
                                            for feld, text in (("verwenden", "verwenden"), ("beginn", "Beginn"), ("ende", "Ende"))}}
                             for tag, name in (("montag_bis_freitag", "Montag bis Freitag"), ("samstag", "Samstag"), ("sonntag", "Sonntag"))}},
            "fenster": {
                "title": "Fenster",
                "description": ("Aus den Kontakten pflegt die Raumheizung den Fensterstatus dieses Raums (fällt ein Kontakt aus, bleibt der letzte "
                                "Zustand 10 Minuten erhalten, danach Freigabe und einmalige Meldung). {reaktion} Klimaanlage und PV-Heizen verwenden denselben "
                                "Fensterstatus – Kontakte tauschen später nur an einer Stelle (Automation „Heizung …“ oder „Konfigurieren → Gerät austauschen“). {herkunft}"),
                "data": {"fensterkontakte": "Fensterkontakte des Raums", "fenster_ausnahmen": "Kontakte, die Klimaanlage und PV-Heizen nicht pausieren (z. B. Balkontür)"},
                "data_description": {"fenster_ausnahmen": "Diese Kontakte pausieren nur die Heizung. Leer lassen, wenn alle Kontakte auch Klima und PV pausieren sollen."}},
            "fenster_extern": {"title": "Fenster", "description": "Der Fensterstatus des anderen Raums wird auch in Better Thermostat als Fenstersensor eingetragen.",
                               "data": {"fensterstatus_extern": "Fensterstatus-Helfer des anderen Raums"}},
            "werte": {
                "title": "Grundwerte",
                "data": {"frostschutz": "Frostschutz-Temperatur (Profil Aus, Sperren)", "aussensperre": "Nicht heizen ab Außentemperatur (0 = keine Sperre)",
                         "boost_dauer": "Boost-Dauer", "vorheizen_max": "Maximale Vorlaufzeit für Vorheizen und Termine",
                         "waermeerzeuger": "Betriebszustand des Wärmeerzeugers (optional)", "mindest_halten": "Mindesttemperatur nach dem Termin halten",
                         "zieltermin_halten": "Zieltemperatur nach dem Termin halten"},
                "data_description": {"waermeerzeuger": "Zum Beispiel der Betriebszustand des Heizkreises (Wärmepumpe oder Kessel). Im reduzierten Betrieb wird mit längerer Vorlaufzeit gerechnet."}},
            "termin": {
                "title": "Mindest- und Zieltemperatur-Termine",
                "description": ("Zur gewählten Uhrzeit soll die Temperatur erreicht sein. Dafür wird der Sollwert rechtzeitig vorher angehoben (nie abgesenkt). "
                                "Je Profil sind bis zu 4 Termine je Art möglich, auch mehrere am selben Tag. Alle Termine lassen sich später in der Blueprint ändern.\n\nBisher eingetragen:\n{liste}"),
                "data": {"art": "Art", "profil": "Gilt im Heizprofil", "tage": "Wochentage", "zeit": "Uhrzeit, zu der die Temperatur erreicht sein soll",
                         "temp": "Temperatur", "weiterer": "Danach einen weiteren Termin eintragen"}},
            "klima_sender": {
                "title": "Klimaanlage im Raum {raum} – IR-Sender",
                "description": ("Wählen Sie den IR-Sender **dieses Raums** (z. B. den Broadlink im Wohnzimmer oder den im Schlafzimmer). PV-Überschussheizen "
                                "verwendet automatisch denselben Sender.\n\n{grund}\n\nAuf der nächsten Seite liest die Integration aus, welche Befehle "
                                "die bisherige Steuerung über diesen Sender verwendet hat und welche dort bereits angelernt sind, und füllt alles vor. "
                                "Dabei wird nichts gesendet und nichts angelernt.\n\n{fehler}"),
                "data": {"klima_sender": "IR-Sender (Remote-Entität)"}},
            "klima": {
                "title": "Klimaanlage im Raum {raum} – IR-Befehle",
                "description": ("IR-Sender `{sender}`. **Erkannt:**\n{erkennung}\n\n"
                                "Die Felder sind entsprechend vorausgefüllt – normalerweise nur prüfen und weiter. {stufe} im Befehlsnamen steht für die "
                                "Temperatur (power_{stufe} → power_20), {luefter} für die Lüfterstufe. Mehrere Zusatzbefehle werden durch Komma getrennt "
                                "und nacheinander im Abstand von 1 s gesendet. Fehlende Befehle werden im nächsten Schritt mit Ihnen angelernt; "
                                "vorhandene werden nie ohne Ihre ausdrückliche Zustimmung ersetzt."),
                "data": {"ir_geraet": "Gerätename der IR-Befehle in diesem Sender", "ir_pruefen": "Befehle trotzdem einzeln prüfen (testweise senden oder neu anlernen)",
                         "befehl_kuehlen": "Befehlsname Kühlen", "befehl_zusatz": "Zusatzbefehle nach Kühlen (optional, durch Komma getrennt)", "befehl_aus": "Befehlsname Aus",
                         "stufe_min": "Niedrigste Kühltemperatur", "stufe_max": "Höchste Kühltemperatur", "luefter": "Lüfterstufe (optional)",
                         "klima_fenster": "Fensterkontakte, die die Klimaanlage pausieren (optional)",
                         "befehl_heizen": "Befehlsname Heizen (vollständiger Zustand; wird vom PV-Überschussheizen dieses Raums verwendet)", "befehl_heizen_aus": "Befehlsname Heizen aus",
                         "klima_steckdose": "Steckdose der Klimaanlage (optional)", "klima_leistung": "Leistungsmessung der Klimaanlage (optional)",
                         "laeuft_ab_w": "Klimaanlage gilt als laufend ab"},
                "data_description": {"luefter": "Zum Beispiel auto, niedrig oder hoch – nur nötig, wenn die Befehlsnamen eine Lüfterstufe enthalten.",
                                     "klima_steckdose": ("Schaltbare Messsteckdose vor der Klimaanlage. Sie bleibt dauerhaft eingeschaltet: Vor jedem IR-Befehl wird "
                                                         "sie bei Bedarf eingeschaltet, nach versehentlichem Ausschalten wieder eingeschaltet – ausgeschaltet wird sie nie."),
                                     "klima_leistung": ("Leer lassen: Es wird automatisch der Leistungssensor derselben Steckdose verwendet. Damit prüft die Steuerung, "
                                                        "ob die Klimaanlage einen Befehl ausgeführt hat – sonst einmal wiederholen, danach Meldung."),
                                     "laeuft_ab_w": "Über dem Bereitschaftsverbrauch (meist 1–3 W) und unter der Leistung des Lüfters allein.",
                                     "ir_geraet": "Unter diesem Namen speichert der Sender die Befehle dieses Raums (Parameter „device“), z. B. klima.",
                                     "befehl_zusatz": "Zum Beispiel eco_{stufe} oder eco_{stufe}, display_off – genau so, wie es die bisherige Steuerung gesendet hat.",
                                     "ir_pruefen": "Ohne Häkchen geht es direkt weiter, wenn alle Befehle vorhanden sind. Fehlende Befehle führen immer zum Anlernen.",
                                     "befehl_heizen": "Leer lassen, wenn in diesem Raum nicht über die Klimaanlage geheizt wird."}},
            **LERNEN,
            "klima_schalter": {
                "title": "Klimaanlage an einer Schaltsteckdose – {raum}",
                "description": ("Die Steckdose schaltet die Klimaanlage nur ein und aus; Temperatur und Lüfter stellt das Gerät selbst. Automatik: ein, wenn der Raum "
                                "wärmer ist als Zieltemperatur plus Einschalt-Abstand, aus, wenn er kühler ist als Ziel minus Ausschalt-Abstand "
                                "(Beispiel: Ziel 22 °C, +0,5 / −0,0 → ein über 22,5 °C, aus unter 22,0 °C). „Manuell“ in der Karte = Dauerbetrieb. "
                                "Alles ist später in der Automation „Klima {raum}“ änderbar."),
                "data": {"klima_schalter": "Schaltsteckdose der Klimaanlage", "klima_ziel_start": "Zieltemperatur (Startwert)",
                         "ein_ueber": "Einschalten, wenn wärmer als Ziel plus", "aus_unter": "Ausschalten, wenn kühler als Ziel minus",
                         "kuehl_profile": "Kühlen erlaubt in den Heizprofilen", "anwesenheit": "Nur kühlen, wenn anwesend (Person oder Schalter, optional)",
                         "abwesend_aus": "Beim Verlassen auch den Klima-Modus auf Aus stellen", "klima_fenster": "Fensterkontakte, die die Klimaanlage pausieren (optional)"},
                "data_description": {"kuehl_profile": "Standard Sommer und Aus – so kühlt die Klimaanlage nicht, während die Heizung heizt.",
                                     "abwesend_aus": "Nach der Rückkehr wird die Klimaanlage bewusst wieder eingeschaltet."}},
            "pv": {
                "title": "PV-Überschussheizen",
                "description": ("Ablauf: Start bei Überschuss und vollem Speicher, Heizkörper schließen, Klimaanlage heizt, Wärmeprüfung, "
                                "Pausen und Sicherheitsfreigabe. Alle Schwellen sind später in der Blueprint einstellbar.\n\n"
                                "**Heizbefehle:** Sie werden über den Broadlink der Klimaanlage gesendet (Gerätename `{geraet}`). Mit {stufe} im Befehlsnamen "
                                "gibt es einen Befehl je Heizstufe, z. B. `heizen_22` … `heizen_28`; beim PV-Heizen wird die gewählte Heizstufe gesendet und lässt "
                                "sich später ohne neues Anlernen wechseln. Mit „jetzt prüfen“ geht es direkt zum Anlernen der fehlenden Befehle an genau diesem "
                                "Broadlink – jeder wird danach einmal testweise gesendet.\n\n{uebernahme}\n\n{heiz_stand}\n\n{fehler}"),
                "data": {"pv_sender": "Broadlink der Klimaanlage (sendet auch die Heizbefehle)", "befehl_heizen": "Befehlsname Heizen",
                         "heiz_stufe_min": "Heizstufen von", "heiz_stufe_max": "Heizstufen bis", "pv_heizstufe": "Heizstufe beim PV-Heizen",
                         "befehl_heizen_aus": "Befehlsname Heizen aus", "heiz_anlernen": "Heizbefehle",
                         "pv_raumfuehler": "Raumtemperaturfühler", "pv_trvs": "Heizkörperthermostate des Raums (werden vor dem PV-Heizen geschlossen)",
                         "pv_ventile": "Ventilöffnungs-Sensoren (optional)", "pv_fenster": "Fenster, die PV-Heizen sperren (optional)",
                         "soc": "Batterie-Ladestand", "netz": "Netz-Einspeisung (positiv = Einspeisung)", "akku_leistung": "Batterie-Leistung (positiv = Laden)",
                         "pv_leistung": "PV-Leistung", "verbrauch": "Hausverbrauch", "zeitstempel_attribut": "Zeitstempel-Attribut der Energiedaten (optional)",
                         "start_leistung": "Start ab Einspeisung", "soc_start": "Start ab Batterie-Ladestand", "soc_halten": "Weiterheizen ab Batterie-Ladestand",
                         "pv_ziel": "PV-Zieltemperatur"}},
            **KARTE,
            "altsteuerung": {
                "title": "Alte Steuerung im Raum {raum}",
                "description": ("Für dieses Better Thermostat (und ggf. den Klima-Sender) wurde die bisherige Steuerung gefunden: **{anz_auto} Automationen**, "
                                "**{anz_skript} Skripte** und **{anz_helfer} Helfer**. Beim Anlegen werden die gewählten Automationen ausgeschaltet, die Skripte "
                                "deaktiviert und beide mit „(alt)“ im Namen gekennzeichnet; die gewählten Helfer erhalten „(alt)“ im Anzeigenamen. Gelöscht wird "
                                "nichts – über „Konfigurieren“ lässt sich alles wieder einschalten oder nach einer Testwoche endgültig löschen.\n\n"
                                "**Andere Automationen und Skripte, die alte Helfer dieses Raums verwenden** (bleiben eingeschaltet):\n{abhaengig}\n\n"
                                "**Gemeinsam mit anderen Räumen** (bleiben unverändert):\n{gemeinsam}\n\n{warnungen}"),
                "data": {"abschalten": "Ausschalten bzw. deaktivieren und „(alt)“ anhängen", "helfer": "Helfer mit „(alt)“ kennzeichnen",
                         "umstellen": "Abhängige Automationen und Skripte auf die neuen Helfer umstellen"},
                "data_description": {"umstellen": "Nur wo es einen gleichwertigen neuen Helfer gibt (gleiche Auswahlwerte). Die Originale werden gesichert."}},
            "alte_karten": {
                "title": "Alte Dashboard-Karten – {raum}",
                "description": ("Diese {anzahl} Karten gehören zur alten Steuerung dieses Raums (sie verwenden deren Skripte, Automationen oder Helfer). Nach dem "
                                "Umstieg funktionieren ihre Knöpfe nicht mehr. Angehakte Karten werden entfernt – gerade in verschachtelten Dashboards wie „Mobil“ "
                                "geht das hier einfacher als im Dashboard-Editor. Vorher wird jedes betroffene Dashboard gesichert; „Alte Steuerung wieder "
                                "einschalten“ setzt die Karten an ihre Stelle zurück. Karten, die nur das Thermostat anzeigen, und Sammelkarten mit anderen "
                                "Räumen erscheinen hier nicht."),
                "data": {"karten": "Diese alten Karten entfernen"}},
            "bestaetigen": {
                "title": "Raum {raum} anlegen",
                "description": ("Es werden angelegt:\n\n**Automationen**\n{automationen}\n\n**{anzahl} Helfer**\n{helfer}\n\n**Dashboard-Karte:** {karte}\n\n{hinweise}\n\n"
                                "Die drei Blueprints werden bei Bedarf installiert. Bestehende Automationen, Helfer und Dashboard-Karten bleiben unverändert."),
                "data": {"bestaetigt": "Ja, jetzt anlegen", "aendern": "Oder etwas ändern – zurück zu"},
                "data_description": {"aendern": "Alle bisherigen Eingaben bleiben erhalten und sind vorausgefüllt. Danach kommen Sie wieder hierher."}},
        },
        "error": FEHLER,
        "abort": ABBRUCH,
        "create_entry": {"hinweis": "Der Raum {raum} wurde angelegt und läuft.\n\n⚠ {hinweis}"},
    },
    "options": {
        "step": {
            "init": {"title": "Raum anpassen", "menu_options": {"funktionen": "Funktionen ändern (z. B. Boost, Fenster, Profile, Klima nachrüsten oder entfernen)",
                                                     "geraet": "Gerät austauschen (z. B. defekter Fensterkontakt, Thermostat, Fühler, Broadlink)",
                                                     "ir": "IR-Befehle der Klimaanlage (neu) anlernen und testen",
                                                     "steckdose": "Klima-Steckdose einrichten oder ändern (dauerhaft an, Rückmeldung über die Leistung)",
                                                     "alte_karten": "Alte Dashboard-Karten dieses Raums entfernen", "karte": "Dashboard-Karte neu platzieren (ein oder mehrere Dashboards, Design wählbar)",
                                                     "alt_zurueck": "Alte Steuerung wieder einschalten (neue Steuerung anhalten)",
                                                     "alt_neu": "Neue Steuerung wieder übernehmen (alte erneut abschalten)",
                                                     "alt_loeschen": "Alte Steuerung endgültig löschen"}},
            "alt_zurueck": {"title": "Alte Steuerung wieder einschalten",
                            "description": ("Diese alte Steuerung wird wieder eingeschaltet, Namen ohne „(alt)“, Skripte wieder freigegeben:\n{liste}\n\n"
                                            "Dazu {helfer} Helfernamen zurückgesetzt und {abhaengig} umgestellte Automationen/Skripte im Original wiederhergestellt. "
                                            "Die neue Steuerung ({neu}) wird ausgeschaltet."),
                            "data": {"bestaetigt": "Ja, alte Steuerung wieder einschalten"}},
            "alt_neu": {"title": "Neue Steuerung wieder übernehmen",
                        "description": "Die alte Steuerung wird erneut abgeschaltet und gekennzeichnet:\n{liste}\n\nDie neue Steuerung ({neu}) wird eingeschaltet.",
                        "data": {"bestaetigt": "Ja, neue Steuerung übernehmen"}},
            "alt_loeschen": {"title": "Alte Steuerung endgültig löschen",
                             "description": ("Diese Automationen und Skripte werden gelöscht:\n{liste}\n\nVorher wird alles als Datei gesichert "
                                             "(`config/heizung_universal/<raum>/`). Home Assistant kann Gelöschtes nicht wiederherstellen.\n\n"
                                             "**Helfer, die noch woanders verwendet werden** (nicht vorausgewählt):\n{verwendet}"),
                             "data": {"helfer": "Diese Helfer ebenfalls löschen", "bestaetigt": "Ja, endgültig löschen"}},
            **LERNEN, **KARTE,
        },
        "error": FEHLER,
        "abort": ABBRUCH,
    },
}

# Konfigurieren → Funktionen ändern: dieselben Schritte wie bei der Einrichtung
TEXTE["options"]["step"].update({k: TEXTE["config"]["step"][k] for k in ("profil", "fenster", "fenster_extern", "werte", "termin", "klima_sender", "klima", "klima_schalter", "pv")})
TEXTE["options"]["step"]["funktionen"] = dict(TEXTE["config"]["step"]["funktionen"], description=(
    "Neu gewählte Funktionen fragen danach nur ihre eigenen Angaben ab; abgewählte Funktionen werden mit ihren Helfern entfernt. "
    "Was Sie in den Automationen selbst geändert haben (Geräte, Zeiten, Temperaturen), bleibt erhalten. Die Raumkarten werden an ihrer Stelle erneuert. "
    "Die Art der Heizzeiten (Tagesprogramme oder Wochenzeitplan) lässt sich hier nicht umstellen."))
TEXTE["options"]["step"]["alte_karten"] = TEXTE["config"]["step"]["alte_karten"]
TEXTE["options"]["step"]["steckdose"] = {
    "title": "Klima-Steckdose – {raum}",
    "description": ("Schaltbare Messsteckdose vor der Klimaanlage. Sie bleibt **dauerhaft eingeschaltet**: Vor jedem IR-Befehl wird sie bei Bedarf "
                    "eingeschaltet (danach kurze Wartezeit zum Hochfahren), nach versehentlichem Ausschalten nach 1 Minute wieder eingeschaltet – "
                    "ausgeschaltet wird sie nie. Mit Leistungsmessung prüft die Steuerung, ob die Klimaanlage einen Befehl ausgeführt hat: sonst einmal "
                    "wiederholen, danach dauerhafte Meldung.\n\nEingetragen wird in {automationen}. **Steckdose leer lassen = entfernen.** Prüfzeiten und "
                    "„dauerhaft eingeschaltet halten“ stehen danach in diesen Automationen im Abschnitt „Stromversorgung und Rückmeldung“."),
    "data": {"klima_steckdose": "Steckdose der Klimaanlage", "klima_leistung": "Leistungsmessung der Klimaanlage", "laeuft_ab_w": "Klimaanlage gilt als laufend ab"},
    "data_description": {"klima_leistung": "Leer lassen: Es wird automatisch der Leistungssensor derselben Steckdose verwendet.",
                         "laeuft_ab_w": "Über dem Bereitschaftsverbrauch (meist 1–3 W) und unter der Leistung des Lüfters allein."}}
TEXTE["options"]["step"]["geraet"] = {"title": "{raum} – Gerät austauschen",
                                      "description": ("Welches Gerät soll ersetzt werden? Aufgeführt sind alle Geräte, die die Automationen dieses Raums "
                                                      "und sein Better Thermostat verwenden (Heizkörperthermostate, Fühler, Fensterkontakte, Steckdose, Broadlink …)."),
                                      "data": {"alt": "Altes Gerät"}}
TEXTE["options"]["step"]["geraet_neu"] = {"title": "Neues Gerät",
                                          "description": ("Ersetzt **{alt}** überall in diesem Raum (verwendet in: {verwendet}) – in den Automationen und, wenn es "
                                                          "dort eingetragen ist, im Better Thermostat (Fühler und Heizkörperthermostate; Kalibrierung und Einstellungen "
                                                          "bleiben). Ein Heizkörperthermostat einer anderen Geräte-Integration (z. B. Zigbee statt Homematic IP) tauscht "
                                                          "Better Thermostat besser selbst – das wird dann gemeldet. Wird das Better Thermostat selbst getauscht, "
                                                          "bekommt das neue denselben Fenstersensor.{andere}"),
                                          "data": {"neu": "Neues Gerät", "alle_raeume": "Auch in allen anderen Räumen ersetzen, die dieses Gerät verwenden"},
                                          "data_description": {"alle_raeume": "Zum Beispiel die Energiesensoren der PV-Anlage oder der Außenfühler, die jeder Raum verwendet."}}
TEXTE["options"]["step"]["aendern_bestaetigen"] = {
    "title": "Raum {raum} – Funktionen ändern",
    "description": ("{aenderungen}\n\nRaumkarten, die erneuert werden: {karten}\n\nVorher werden die Dashboards gesichert. Schlägt etwas fehl, "
                    "wird der vorige Stand wiederhergestellt. Nicht mehr benötigte Automationen und Helfer werden zuletzt gelöscht."),
    "data": {"bestaetigt": "Ja, jetzt ändern"}}

# Schalter „Zurück zum vorherigen Schritt“ auf allen Seiten, die ihn zeigen können
ZURUECK_TEXT = "↩ Zurück zum vorherigen Schritt"
ZURUECK_HILFE = "Einschalten und OK: Die vorherige Seite erscheint wieder mit Ihren Eingaben. Was auf dieser Seite eingegeben wurde, wird nicht übernommen."
for bereich in ("config", "options"):
    for schritt in ("funktionen", "profil", "fenster", "fenster_extern", "werte", "termin", "klima_sender", "klima", "klima_schalter", "pv", "altsteuerung", "alte_karten",
                    "dashboard", "ansicht", "platz", "position", "bestaetigen", "lernen_auswahl", "aendern_bestaetigen"):
        st = TEXTE[bereich]["step"].get(schritt)
        if st is None:
            continue
        st = TEXTE[bereich]["step"][schritt] = json.loads(json.dumps(st))  # keine gemeinsamen Objekte zwischen config und options
        st.setdefault("data", {})["zurueck"] = ZURUECK_TEXT
        st.setdefault("data_description", {})["zurueck"] = ZURUECK_HILFE


def uebersetzung_pruefen(de, en, pfad="TEXTE"):
    """Englisch muss dieselben Schlüssel und je Text dieselben {Platzhalter} haben wie Deutsch. Liefert die Abweichungen."""
    if isinstance(de, dict) and isinstance(en, dict):
        return ([f"{pfad}: Schlüssel fehlt in en: {k}" for k in de.keys() - en.keys()] + [f"{pfad}: Schlüssel nur in en: {k}" for k in en.keys() - de.keys()]
                + [f for k in de.keys() & en.keys() for f in uebersetzung_pruefen(de[k], en[k], f"{pfad}.{k}")])
    if isinstance(de, str) and isinstance(en, str):
        platz = re.compile(r"\{([a-z_0-9]+)\}")
        return [] if set(platz.findall(de)) == set(platz.findall(en)) else [f"{pfad}: Platzhalter {sorted(set(platz.findall(de)))} ≠ {sorted(set(platz.findall(en)))}"]
    return [f"{pfad}: unterschiedlicher Typ"]


def main():
    abweichungen = uebersetzung_pruefen(TEXTE, TEXTE_EN)
    if abweichungen:
        raise SystemExit("Englische Übersetzung passt nicht zu den deutschen Texten:\n" + "\n".join(abweichungen))
    if ZIEL.exists():
        shutil.rmtree(ZIEL)
    (ZIEL / "assistent" / "blueprints").mkdir(parents=True)
    (ZIEL / "translations").mkdir()
    for f in (BASIS / "integration" / "heizung_universal").glob("*"):
        if f.is_file():
            shutil.copy2(f, ZIEL / f.name)
    marke = BASIS / "integration" / "heizung_universal" / "brand"  # Logo: Home Assistant zeigt es direkt aus diesem Ordner an (ab 2026.x)
    if marke.is_dir():
        shutil.copytree(marke, ZIEL / "brand")
    (ZIEL / "assistent" / "__init__.py").write_text('"""Einrichtungslogik (identisch mit dem Kommandozeilen-Assistenten des Projekts)."""\n', encoding="utf-8")
    for n in ("ha_verbindung.py", "karte.py", "raumassistent.py", "altsteuerung.py", "irerkennung.py", "altuebernahme.py"):
        shutil.copy2(BASIS / "assistent" / n, ZIEL / "assistent" / n)
    for f in (BASIS / "blueprints/automation/ha_heizung_universal").glob("*.yaml"):
        shutil.copy2(f, ZIEL / "assistent" / "blueprints" / f.name)
    for sprache, texte in (("de", TEXTE), ("en", TEXTE_EN)):
        (ZIEL / "translations" / f"{sprache}.json").write_text(json.dumps(texte, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (BASIS / "paket").mkdir(exist_ok=True)
    zipdatei = BASIS / "paket" / f"heizung_universal_{VERSION}.zip"
    if zipdatei.exists() and VERSION in VERSIONEN_FREIGEGEBEN:  # Schutz: ausgelieferte Fassungen nie überschreiben (vorher Version erhöhen!)
        print(f"ZIP:   {zipdatei} bleibt unverändert (Version {VERSION} ist bereits ausgeliefert – für Änderungen die Version erhöhen)")
        return
    with zipfile.ZipFile(zipdatei, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(ZIEL.rglob("*")):
            if f.is_file() and "__pycache__" not in f.parts:
                z.write(f, f.relative_to(BASIS))
    print(f"Paket: {ZIEL}\nZIP:   {zipdatei} ({zipdatei.stat().st_size // 1024} KB, {sum(1 for _ in ZIEL.rglob('*') if _.is_file())} Dateien)")


if __name__ == "__main__":
    main()
