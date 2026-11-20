#!/bin/zsh
# Alle lokalen Prüfungen (kein Schreibzugriff auf Home Assistant). Abnahme in einer echten lokalen HA-Testinstanz: siehe Ende dieser Datei
set -e
cd "${0:A:h}/.."
export LANG=en_US.UTF-8
echo "1) Blueprints neu erzeugen"; for b in raumheizung klima pv klima_steckdose; do python3 -I tools/build_$b.py | sed 's/^/   /'; done
echo "2) YAML-Syntax und Eingabefelder"; ruby tests/yaml_check.rb blueprints/automation/ha_heizung_universal/*.yaml | sed 's/^/   /'
echo "3) Aliasse für alle Trigger, Bedingungen und Aktionen"; ruby tests/alias_check.rb blueprints/automation/ha_heizung_universal/*.yaml | sed 's/^/   /'
echo "4) Assistent – Trockenlauf (Büro, Vollausbau)"
rm -rf tests/assistent/ausgabe
for f in buero klima_pv; do python3 -I assistent/raumassistent.py --offline tests/assistent/bestand_snapshot.json --antworten tests/assistent/antworten_$f.json --ausgabe tests/assistent/ausgabe > /dev/null && echo "   OK  $f"; done
echo "5) Erzeugte Instanzen gegen Blueprints"; ruby tests/instanz_check.rb tests/assistent/ausgabe/*/automation_*.yaml
echo "6) Dashboard-Karten (JavaScript)"
for r in buero testraum; do ruby -rjson -rpsych -e "File.write('tests/_karte_$r.json', JSON.generate(Psych.safe_load(File.read('tests/assistent/ausgabe/$r/karte.yaml', encoding:'UTF-8'))))"; done
python3 -I -c "
import sys, json; sys.path.insert(0, 'assistent'); sys.path.insert(0, 'tools')
import raumassistent as ra
h = {'profile': ['Komfort', 'Übergang', 'Sommer', 'Urlaub', 'Aus'], 'raum_name': 'Testraum', 'status_text': 'input_text.hz_testraum_status', 'heizprofil': 'input_select.hz_testraum_heizprofil',
     'boost_wert': 'input_number.hz_testraum_boost', 'boost_timer': 'timer.hz_testraum_boost_timer', 'vorheizen_bericht': 'input_text.hz_testraum_vorheizbericht',
     'klima_modus': 'input_select.hz_testraum_klima_modus', 'klima_ziel': 'input_number.hz_testraum_klima_ziel', 'klima_manuell': 'input_number.hz_testraum_klima_manuell',
     'pv_heizfreigabe': 'input_boolean.hz_testraum_pv_heizfreigabe', 'pv_status': 'input_text.hz_testraum_pv_status', 'pv_fehler': 'input_boolean.hz_testraum_pv_ir_fehler'}
json.dump(ra.raumkarte(h, 'verlauf'), open('tests/_karte_verlauf.json', 'w'), ensure_ascii=False)
json.dump(ra.raumkarte(dict(h, raum_name='Schlafzimmer'), 'mobil'), open('tests/_karte_mobil.json', 'w'), ensure_ascii=False)
json.dump(ra.raumkarte(dict(h, raum_name='Büro', fenster_bt=True), 'mobil'), open('tests/_karte_mobil_fensterbt.json', 'w'), ensure_ascii=False)"
node tests/karte_js_test.js tests/_karte_buero.json tests/_karte_testraum.json tests/_karte_verlauf.json tests/_karte_mobil.json tests/_karte_mobil_fensterbt.json | tail -1 | sed 's/^/   /'
echo "7) Assistent gegen nachgebauten HA-Server (Anlegen, Dashboard, Rückbau)"
python3 tests/assistent_mock_test.py | tail -1 | sed 's/^/   /'
echo "7b) Installationsskript: speichert ausschließlich die drei Blueprints"
python3 tests/installation_mock_test.py | tail -1 | sed 's/^/   /'
rm -f tests/_*.json
rm -rf tests/assistent/mock_ausgabe
# Schritte 8 und 9 brauchen Jinja2 (einmalig: python3 -m venv tests/.venv && tests/.venv/bin/pip install jinja2)
PY=""
for kandidat in tests/.venv/bin/python python3; do
  if "$kandidat" -c "import jinja2" 2>/dev/null; then PY="$kandidat"; break; fi
done
if [[ -z "$PY" ]]; then
  echo "8) und 9) ÜBERSPRUNGEN: Jinja2 fehlt (python3 -m venv tests/.venv && tests/.venv/bin/pip install jinja2)"; exit 1
fi
echo "8) Syntax aller Vorlagen der drei Blueprints"; "$PY" tests/vorlagen_check.py | sed 's/^/   /'
echo "9) Gesamttest im Simulator (Zeitplan, Vorheizen, Fenster, Boost, Prioritäten, Klima, PV)"
"$PY" tests/gesamttest.py > tests/gesamttest_ausgabe.txt 2>&1 || { grep -v "✔" tests/gesamttest_ausgabe.txt | sed 's/^/   /'; exit 1; }
tail -1 tests/gesamttest_ausgabe.txt | sed 's/^/   /'
echo "9b) IR-Befehlserkennung (alte Steuerung, Broadlink-Speicher)"; python3 -I tests/irerkennung_test.py | tail -1
echo "9c) Übernahme aus der alten Steuerung (Heizprogramme, Funktionen, PV-Geräte)"; python3 -I tests/altuebernahme_test.py | tail -1
echo "10) Installationspaket bauen und Integration übersetzen"
python3 -I tools/paket_bauen.py | sed 's/^/   /'
python3 -I -m py_compile custom_components/heizung_universal/*.py custom_components/heizung_universal/assistent/*.py && echo "   Python-Syntax der Integration: OK"
echo "Abnahme in einer echten lokalen Home-Assistant-Instanz (dauert ca. 6 Minuten, braucht ein venv mit homeassistant):"
echo "   zsh tests/ha_instanz/lauf.sh <venv> <leerer Arbeitsordner>"
