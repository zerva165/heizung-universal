# Abweichungen zur privaten Ausgangsfassung

Diese öffentliche Fassung entstand aus der privaten Fassung **1.11.4**. Der Programmcode ist bewusst so nah wie möglich am
Original geblieben, damit gemeldete Fehler leicht in beide Richtungen übertragen werden können. Unterschiede betreffen fast nur
Texte (Beispiele, Kommentare), die Paketierung für HACS und die Testdaten.

**Faustregel zum Übertragen:** Änderungen in `integration/`, `assistent/` und `tools/build_*.py` lassen sich zeilengleich übernehmen –
außer an den unten genannten Textstellen. In `tools/paket_bauen.py` unterscheiden sich nur der Kopf und `main()`; ändert sich ein deutscher
Text in `TEXTE`, muss `tools/texte_en.py` mitgezogen werden (der Paketbau bricht sonst mit einer Meldung ab).

## 1. Aufbau des Repositorys

| Neu | Zweck |
|---|---|
| `custom_components/heizung_universal/` | wird von `tools/paket_bauen.py` erzeugt und von HACS installiert (im Original: `paket/custom_components/…`) |
| `tools/texte_en.py` | echte englische Oberflächentexte (im Original war `en.json` eine Kopie der deutschen Texte) |
| `README.md`, `hacs.json`, `.gitignore`, `LICENSE`, diese Datei | Veröffentlichung |

Nicht übernommen: Sicherungen, Dokumentation und Testprotokolle mit Betriebsnotizen, Bestandsaufnahmen und Dashboard-Abzüge,
Archiv der Vorgängerfassung, alte Paket-ZIPs, Logo-Quelldateien, Testausgaben sowie Tests, die nicht von `tests/alle_tests.sh` aufgerufen werden.

## 2. Programmcode und Generatoren

| Datei | Abweichung | Wirkung |
|---|---|---|
| `integration/heizung_universal/manifest.json` | `codeowners`, `documentation`, `issue_tracker` gesetzt (Repository zerva165/heizung-universal); öffentliche Version **1.0.0** (privat 1.11.4) | nur Metadaten |
| `integration/heizung_universal/config_flow.py` | 2 Docstrings: Herstellerbeispiele allgemein formuliert | keine |
| `assistent/karte.py` | Raumstil „Kinderzimmer“: Schlüsselwörter nur noch `kind` (ein Personenname entfernt) | Räume, deren Name nur einen Personennamen enthält, bekommen das Standardsymbol statt des Teddybären |
| `assistent/karte.py` | `DESIGNS`: Beschriftungen der drei Designs beschreiben das Aussehen statt auf private Dashboards zu verweisen; Kommentare/Docstring entsprechend | sichtbarer Text in der Design-Auswahl |
| `assistent/raumassistent.py` | Kommandozeilen-Frage „Wärmeerzeuger“: Beispiel ohne Herstellernamen; 2 Kommentare | sichtbarer Text nur im Kommandozeilen-Assistenten |
| `assistent/altsteuerung.py`, `altuebernahme.py`, `irerkennung.py` | Beispiele in Docstrings/Kommentaren allgemein formuliert | keine |
| `tools/build_raumheizung.py` | Beschreibung des Eingabefelds „Heizphase des Wärmeerzeugers“ ohne Herstellernamen | Blueprint-Text |
| `tools/build_klima.py` | Docstrings („Vorbild“ statt Verweis auf private Automationen) | keine |
| `tools/build_klima_steckdose.py` | Docstring; Beispiel der Raumkennung (`kinderzimmer`); Beschreibung „Beim Verlassen …“ ohne Personenbezug | Blueprint-Text |
| `tools/build_pv.py` | Docstrings; Beispiel Zeitstempel-Attribut (`last_update`); „Standardwerte = bewährte Ausgangswerte“; Blueprint-Beschreibung „statt der Zentralheizung. Ablauf: …“ | Blueprint-Text |
| `tools/blueprints_installieren.py` | Beispieladresse `http://homeassistant.local:8123` | Text der Eingabeaufforderung |
| `tools/paket_bauen.py` | Ziel `custom_components/heizung_universal/` im Repo-Stamm, ZIP weiterhin in `paket/` (gleicher Aufbau im ZIP); `VERSIONEN_FREIGEGEBEN` leer (öffentliche Zählung beginnt neu); `en.json` aus `tools/texte_en.py` mit Prüfung auf gleiche Schlüssel und Platzhalter | Paketierung |
| `tools/paket_bauen.py` (`TEXTE`) | 6 Oberflächentexte ohne Hausbezug: Fenster („Wie im Wohnzimmer“ entfernt), Wärmeerzeuger-Beispiel, Steckdosen-Beispiel und „Beim Verlassen …“, PV-Beschreibung („Ablauf: …“), „Auch in allen anderen Räumen ersetzen“-Beispiel | sichtbare deutsche Texte |

Die Versionskennung in den Blueprint-Beschreibungen („Paketversion 1.6.0“) ist unverändert – sie steuert die Aktualisierung der
Blueprints und ist unabhängig von der Versionsnummer der Integration.

## 3. Tests

| Datei | Abweichung |
|---|---|
| `tests/alle_tests.sh` | Kopfkommentar; Syntaxprüfung im neuen Paketordner `custom_components/` |
| `tests/ha_instanz/start.sh` | kopiert das Paket aus `custom_components/` |
| `tests/assistent/*.json`, `tests/mock_ha.py`, `tests/karte_js_test.js` | erfundene Entitäts-IDs und Anzeigenamen statt echter; Zeitstempel-Attribut `last_update` |
| `tests/irerkennung_test.py`, `tests/altuebernahme_test.py` | alte Steuerung in erfundenen Räumen („Wohnraum“, „Schlafraum“, „Wohnraum oben“) mit erfundenen IDs; gleiche Prüfungen |
| `tests/ha_instanz/abnahme.py`, `tests/ha_instanz/vorlage/configuration.yaml` | Fremd-Automationen der Testumgebung neutral benannt, Tab-Name im Test-Dashboard, Testtitel ohne Personen- und Hausbezug, globaler Schalter `input_boolean.heizung_aus_global`, Zeitstempel-Attribut `pv_last_update`; gleiche Prüfungen |

Alle Prüfungen und Erwartungswerte sind inhaltlich gleich geblieben; nur Namen und IDs der Testdaten unterscheiden sich.
