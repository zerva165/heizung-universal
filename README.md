# Heizung Universal

Room-by-room heating control for Home Assistant, set up entirely through the UI.
Raumweise Heizungssteuerung für Home Assistant, vollständig über die Oberfläche eingerichtet.

[English](#english) · [Deutsch](#deutsch) · [Screenshots / Bilder](#screenshots--bilder)

---

## Screenshots / Bilder

![Room card in three designs / Raumkarte in drei Designs](docs/bilder/dashboard.png)

<sub>Screenshots from a local test instance with example devices; the integration's UI shown in German. · Bilder aus einer lokalen Test-Instanz mit Beispielgeräten.</sub>

<details>
<summary><b>Dashboard card designs / Kartendesigns</b></summary>

<table>
<tr><td align="center" valign="top"><a href="docs/bilder/karte_mobil.png"><img src="docs/bilder/karte_mobil.png" width="260" alt="Mobil kompakt"></a><br><sub>Mobil kompakt</sub></td><td align="center" valign="top"><a href="docs/bilder/karte_glas.png"><img src="docs/bilder/karte_glas.png" width="260" alt="Liquid-Glass"></a><br><sub>Liquid-Glass</sub></td><td align="center" valign="top"><a href="docs/bilder/karte_verlauf.png"><img src="docs/bilder/karte_verlauf.png" width="260" alt="Farbverlauf"></a><br><sub>Farbverlauf</sub></td></tr>
</table>

</details>

<details>
<summary><b>Setup wizard / Einrichtungsassistent</b> (13 steps / Schritte)</summary>

<table>
<tr><td align="center" valign="top"><a href="docs/bilder/einrichtung_01_geraete.png"><img src="docs/bilder/einrichtung_01_geraete.png" width="260" alt="1 · Devices / Geräte"></a><br><sub>1 · Devices / Geräte</sub></td><td align="center" valign="top"><a href="docs/bilder/einrichtung_02_funktionen.png"><img src="docs/bilder/einrichtung_02_funktionen.png" width="260" alt="2 · Functions / Funktionen"></a><br><sub>2 · Functions / Funktionen</sub></td><td align="center" valign="top"><a href="docs/bilder/einrichtung_03_profil.png"><img src="docs/bilder/einrichtung_03_profil.png" width="260" alt="3 · Heating profile / Heizprofil"></a><br><sub>3 · Heating profile / Heizprofil</sub></td></tr>
<tr><td align="center" valign="top"><a href="docs/bilder/einrichtung_04_fenster.png"><img src="docs/bilder/einrichtung_04_fenster.png" width="260" alt="4 · Windows / Fenster"></a><br><sub>4 · Windows / Fenster</sub></td><td align="center" valign="top"><a href="docs/bilder/einrichtung_05_ir_sender.png"><img src="docs/bilder/einrichtung_05_ir_sender.png" width="260" alt="5 · IR transmitter / IR-Sender"></a><br><sub>5 · IR transmitter / IR-Sender</sub></td><td align="center" valign="top"><a href="docs/bilder/einrichtung_06_ir_befehle.png"><img src="docs/bilder/einrichtung_06_ir_befehle.png" width="260" alt="6 · Detected IR commands / Erkannte IR-Befehle"></a><br><sub>6 · Detected IR commands / Erkannte IR-Befehle</sub></td></tr>
<tr><td align="center" valign="top"><a href="docs/bilder/einrichtung_07_ir_auswahl.png"><img src="docs/bilder/einrichtung_07_ir_auswahl.png" width="260" alt="7 · Learn or test / Anlernen oder testen"></a><br><sub>7 · Learn or test / Anlernen oder testen</sub></td><td align="center" valign="top"><a href="docs/bilder/einrichtung_08_ir_anlernen.png"><img src="docs/bilder/einrichtung_08_ir_anlernen.png" width="260" alt="8 · Learn a command / Befehl anlernen"></a><br><sub>8 · Learn a command / Befehl anlernen</sub></td><td align="center" valign="top"><a href="docs/bilder/einrichtung_09_ir_testen.png"><img src="docs/bilder/einrichtung_09_ir_testen.png" width="260" alt="9 · Test a command / Befehl testen"></a><br><sub>9 · Test a command / Befehl testen</sub></td></tr>
<tr><td align="center" valign="top"><a href="docs/bilder/einrichtung_10_pv.png"><img src="docs/bilder/einrichtung_10_pv.png" width="260" alt="10 · PV surplus heating / PV-Überschussheizen"></a><br><sub>10 · PV surplus heating / PV-Überschussheizen</sub></td><td align="center" valign="top"><a href="docs/bilder/einrichtung_11_dashboard_bereich.png"><img src="docs/bilder/einrichtung_11_dashboard_bereich.png" width="260" alt="11 · Dashboard section / Bereich"></a><br><sub>11 · Dashboard section / Bereich</sub></td><td align="center" valign="top"><a href="docs/bilder/einrichtung_12_position_design.png"><img src="docs/bilder/einrichtung_12_position_design.png" width="260" alt="12 · Position & design"></a><br><sub>12 · Position & design</sub></td></tr>
<tr><td align="center" valign="top"><a href="docs/bilder/einrichtung_13_zusammenfassung.png"><img src="docs/bilder/einrichtung_13_zusammenfassung.png" width="260" alt="13 · Summary / Zusammenfassung"></a><br><sub>13 · Summary / Zusammenfassung</sub></td></tr>
</table>

</details>

<details>
<summary><b>After setup: configure, replace devices / Nach der Einrichtung: Konfigurieren, Gerät austauschen</b></summary>

<table>
<tr><td align="center" valign="top"><a href="docs/bilder/integration.png"><img src="docs/bilder/integration.png" width="260" alt="One entry per room / Ein Eintrag je Raum"></a><br><sub>One entry per room / Ein Eintrag je Raum</sub></td><td align="center" valign="top"><a href="docs/bilder/konfigurieren_menue.png"><img src="docs/bilder/konfigurieren_menue.png" width="260" alt="Configure / Konfigurieren"></a><br><sub>Configure / Konfigurieren</sub></td><td align="center" valign="top"><a href="docs/bilder/geraet_austauschen.png"><img src="docs/bilder/geraet_austauschen.png" width="260" alt="Replace a device / Gerät austauschen"></a><br><sub>Replace a device / Gerät austauschen</sub></td></tr>
<tr><td align="center" valign="top"><a href="docs/bilder/geraet_neu.png"><img src="docs/bilder/geraet_neu.png" width="260" alt="New device / Neues Gerät"></a><br><sub>New device / Neues Gerät</sub></td><td align="center" valign="top"><a href="docs/bilder/automationen.png"><img src="docs/bilder/automationen.png" width="260" alt="Created automations / Angelegte Automationen"></a><br><sub>Created automations / Angelegte Automationen</sub></td></tr>
</table>

</details>

---

## English

> **Language note:** The setup dialogs are available in English and German. Everything the integration *creates*
> in your Home Assistant – helpers, automations, blueprint texts and the dashboard card – is in **German**
> (e.g. the heating profiles are called *Komfort*, *Übergang*, *Urlaub*, *Sommer* and *Aus*).
> Some dynamic hints inside the dialogs are German as well.

### What it does

One config entry per room. The setup wizard asks for the room's devices and the functions you want and then creates
everything automatically: helpers, schedules, automations (from the bundled blueprints) and a dashboard card.
The actual control runs in normal Home Assistant automations that you can inspect and adjust at any time.
Removing the config entry removes exactly what was created for that room.

- **Heating profiles** *Komfort*, *Übergang*, *Urlaub* plus *Sommer* and *Aus*, each with target and setback temperature
- **Heating times** either as three day schedules per profile (Monday–Friday, Saturday, Sunday, up to three heating periods each)
  or as a graphical weekly schedule (schedule helper)
- **Window monitoring** with a 10-minute fail-safe for unavailable contacts, or reuse of another room's window status;
  optionally entered in Better Thermostat as window sensor
- **Boost**, **frost protection**, **outdoor temperature lock**, optional **global "heating off" switch**
- **Predictive pre-heating** with a self-learning correction factor, optionally taking the heat source's operating state into account
- **Minimum / target temperature appointments** (temperature reached at a fixed time)
- **Air conditioning via IR** (e.g. Broadlink): the existing commands are detected automatically from your previous scripts and from the
  transmitter's stored codes; missing commands can be learned and tested directly in the wizard
- **Air conditioner on a switchable smart plug** (on/off only, e.g. portable units), optionally only when someone is present
- **PV surplus heating** via the air conditioner (start on surplus with a full battery, radiators closed in the meantime,
  heat check, pauses, safety release that hands control back to the radiators if anything fails)
- **Optional smart plug with power metering** in front of the air conditioner as power supply and command feedback
- **Replace a device** (thermostat, sensor, window contact, transmitter …) in one step – also in all other rooms that use it
- **Take over an existing heating control**: the previous automations/scripts/helpers of the room are detected, switched off and
  marked "(alt)" – nothing is deleted; you can switch back at any time or delete the old control after a test period
- **Dashboard card** in three designs, placed into the dashboard, view and section you choose; previous room cards can be removed

### Requirements

| | |
|---|---|
| Home Assistant | **2026.11** (tested with 2026.11.0) |
| [Better Thermostat](https://github.com/KartoffelToby/better_thermostat) | one Better Thermostat entity per room (required) |
| Frontend cards (HACS) | [button-card](https://github.com/custom-cards/button-card), [Mushroom](https://github.com/piitaya/lovelace-mushroom), [card-mod](https://github.com/thomasloven/lovelace-card-mod) (provides `custom:mod-card`) – needed for the dashboard card |
| Optional | IR transmitter with `remote.learn_command` / `remote.send_command` (e.g. Broadlink) for air conditioning and PV heating |
| Optional | switchable smart plug (with power metering for command feedback) |
| Optional | PV system sensors: battery state of charge, grid export, battery power, PV power, house consumption |

### Installation

**HACS (custom repository)**

1. HACS → ⋮ → *Custom repositories* → add `https://github.com/zerva165/heizung-universal`, category *Integration*.
2. Install **Heizung Universal** and restart Home Assistant.
3. *Settings → Devices & services → Add integration → Heizung Universal* – one entry per room.

**Manual**

Copy `custom_components/heizung_universal/` into your Home Assistant `config/custom_components/` folder and restart.

### Please note

- **Temporary admin system user:** to create helpers, blueprints, automations and dashboards, the integration uses Home Assistant's own
  WebSocket/REST API – the same commands the UI uses, so Home Assistant validates every input itself. For the duration of each
  operation it creates a **system user in the administrators group** with a short-lived token and **removes it again** afterwards.
  The connection goes to your own instance only (`127.0.0.1` or the configured local IP).
- Existing automations, helpers and dashboard cards are not changed unless you explicitly choose to take over a previous control
  or remove previous cards. Affected dashboards are backed up before cards are renewed or removed; deleted old automations are
  backed up to `config/heizung_universal/<room>/`.
- Please test a new room for a few days before relying on it, especially PV heating and air conditioning.

### Development

```
integration/heizung_universal/   UI (config flow) – source
assistent/                       setup logic (also usable as a command-line wizard)
tools/build_*.py                 generate the blueprints in blueprints/automation/ha_heizung_universal/
tools/paket_bauen.py             builds custom_components/heizung_universal/ (with translations) and a ZIP in paket/
tools/texte_en.py                English UI texts (German texts: TEXTE in tools/paket_bauen.py)
tests/alle_tests.sh              all local tests
```

`custom_components/` is **generated** – change the sources and run `tools/paket_bauen.py` (or the tests).

```bash
python3 -m venv tests/.venv && tests/.venv/bin/pip install jinja2
```

```bash
zsh tests/alle_tests.sh
```

Optional acceptance test in a real, local throw-away Home Assistant instance (port 8124, about 6 minutes;
needs a venv with `pip install homeassistant==2026.11.0`):

```bash
zsh tests/ha_instanz/lauf.sh <venv-with-homeassistant> <empty-work-folder>
```

### Reporting problems

Please open an [issue](https://github.com/zerva165/heizung-universal/issues) with your Home Assistant version, the integration version,
what you did and the relevant log lines (*Settings → System → Logs*, filter `heizung_universal`). Please remove personal data
(names, addresses, entity IDs you consider private) before posting.

### License

[MIT](LICENSE)

---

## Deutsch

### Was die Integration macht

Ein Konfigurationseintrag je Raum. Der Einrichtungsassistent fragt die Geräte des Raums und die gewünschten Funktionen ab und legt
danach alles automatisch an: Helfer, Zeitpläne, Automationen (aus den mitgelieferten Blueprints) und eine Dashboard-Karte.
Die eigentliche Regelung läuft in normalen Home-Assistant-Automationen, die jederzeit einsehbar und änderbar sind.
Wird der Eintrag gelöscht, wird genau das wieder entfernt, was für diesen Raum angelegt wurde.

- **Heizprofile** Komfort, Übergang, Urlaub sowie Sommer und Aus, jeweils mit Soll- und Absenktemperatur
- **Heizzeiten** als drei Tagesprogramme je Profil (Montag bis Freitag, Samstag, Sonntag, je bis zu drei Heizphasen)
  oder als grafischer Wochenzeitplan (Zeitplan-Helfer)
- **Fensterüberwachung** mit 10-Minuten-Fail-safe bei ausgefallenen Kontakten oder Mitverwendung des Fensterstatus eines anderen Raums;
  auf Wunsch auch als Fenstersensor in Better Thermostat eingetragen
- **Boost**, **Frostschutz**, **Außentemperatursperre**, optional **globaler Schalter „Heizung Aus“**
- **Vorausschauendes Vorheizen** mit selbstlernendem Korrekturfaktor, optional abhängig vom Betriebszustand des Wärmeerzeugers
- **Mindest- und Zieltemperatur-Termine** (Temperatur zu einer festen Uhrzeit erreicht)
- **Klimaanlage über IR** (z. B. Broadlink): Vorhandene Befehle werden automatisch aus der bisherigen Steuerung und aus dem Speicher
  des Senders erkannt; fehlende Befehle lassen sich direkt im Assistenten anlernen und testen
- **Klimaanlage an einer Schaltsteckdose** (nur ein/aus, z. B. mobiles Klimagerät), auf Wunsch nur bei Anwesenheit
- **PV-Überschussheizen** über die Klimaanlage (Start bei Überschuss und vollem Speicher, Heizkörper währenddessen geschlossen,
  Wärmeprüfung, Pausen, Sicherheitsfreigabe – fällt etwas aus, übernehmen automatisch wieder die Heizkörper)
- **Optionale Messsteckdose** vor der Klimaanlage für Stromversorgung und Rückmeldung, ob ein Befehl ausgeführt wurde
- **Gerät austauschen** (Thermostat, Fühler, Fensterkontakt, Sender …) in einem Schritt – auf Wunsch in allen Räumen, die es verwenden
- **Bestehende Heizungssteuerung übernehmen**: Die bisherigen Automationen, Skripte und Helfer des Raums werden erkannt, abgeschaltet und
  mit „(alt)“ gekennzeichnet – gelöscht wird nichts; zurückschalten ist jederzeit möglich, endgültiges Löschen nach einer Testphase
- **Dashboard-Karte** in drei Designs, eingefügt in Dashboard, Ansicht und Bereich nach Wahl; alte Raumkarten lassen sich entfernen

### Voraussetzungen

| | |
|---|---|
| Home Assistant | **2026.11** (getestet mit 2026.11.0) |
| [Better Thermostat](https://github.com/KartoffelToby/better_thermostat) | je Raum eine Better-Thermostat-Entität (Pflicht) |
| Frontend-Karten (HACS) | [button-card](https://github.com/custom-cards/button-card), [Mushroom](https://github.com/piitaya/lovelace-mushroom), [card-mod](https://github.com/thomasloven/lovelace-card-mod) (stellt `custom:mod-card` bereit) – für die Dashboard-Karte |
| Optional | IR-Sender mit `remote.learn_command` / `remote.send_command` (z. B. Broadlink) für Klimaanlage und PV-Heizen |
| Optional | schaltbare Steckdose (mit Leistungsmessung für die Rückmeldung) |
| Optional | Sensoren der PV-Anlage: Batterie-Ladestand, Netz-Einspeisung, Batterie-Leistung, PV-Leistung, Hausverbrauch |

### Installation

**HACS (benutzerdefiniertes Repository)**

1. HACS → ⋮ → *Benutzerdefinierte Repositories* → `https://github.com/zerva165/heizung-universal` mit Kategorie *Integration* hinzufügen.
2. **Heizung Universal** installieren und Home Assistant neu starten.
3. *Einstellungen → Geräte & Dienste → Integration hinzufügen → Heizung Universal* – ein Eintrag je Raum.

**Manuell**

Den Ordner `custom_components/heizung_universal/` nach `config/custom_components/` kopieren und Home Assistant neu starten.

### Bitte beachten

- **Kurzzeitiger Admin-Systembenutzer:** Um Helfer, Blueprints, Automationen und Dashboards anzulegen, verwendet die Integration die
  WebSocket- und REST-Schnittstelle von Home Assistant – dieselben Befehle wie die Oberfläche, sodass Home Assistant jede Eingabe selbst prüft.
  Für die Dauer jedes Vorgangs legt sie dafür einen **Systembenutzer in der Gruppe Administratoren** mit kurzlebigem Token an und
  **entfernt ihn danach wieder**. Verbunden wird ausschließlich mit der eigenen Instanz (`127.0.0.1` bzw. die eingestellte lokale IP).
- Bestehende Automationen, Helfer und Dashboard-Karten werden nicht verändert, außer Sie wählen ausdrücklich die Übernahme einer alten
  Steuerung oder das Entfernen alter Karten. Betroffene Dashboards werden gesichert, bevor Karten erneuert oder entfernt werden;
  gelöschte alte Automationen werden nach `config/heizung_universal/<raum>/` gesichert.
- Einen neuen Raum bitte einige Tage beobachten, bevor Sie sich darauf verlassen – besonders PV-Heizen und Klimaanlage.

### Entwicklung

Aufbau siehe englischer Teil. `custom_components/` wird **erzeugt** – Änderungen in den Quellen vornehmen und `tools/paket_bauen.py`
(oder die Tests) ausführen. Alle lokalen Tests: `zsh tests/alle_tests.sh` (braucht Jinja2, siehe oben). Optionale Abnahme in einer
echten lokalen Wegwerf-Instanz: `zsh tests/ha_instanz/lauf.sh <venv mit homeassistant> <leerer Arbeitsordner>`.

### Fehler melden

Bitte ein [Issue](https://github.com/zerva165/heizung-universal/issues) mit Home-Assistant-Version, Version der Integration, Ablauf und den
passenden Protokollzeilen (*Einstellungen → System → Protokolle*, Filter `heizung_universal`) anlegen. Persönliche Daten (Namen, Adressen,
Entitäts-IDs, die Sie als privat ansehen) bitte vorher entfernen.

### Lizenz

[MIT](LICENSE)
