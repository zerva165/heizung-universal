#!/bin/zsh
# Frische Test-Instanz starten, warten bis sie bereit ist, Abnahme ausführen. Aufruf: lauf.sh <HA-venv> <Arbeitsordner>
HIER="${0:A:h}"
zsh "$HIER/start.sh" "$1" "$2" || exit 2
for i in $(seq 1 90); do
  [[ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8124/manifest.json)" == "200" ]] && break
  python3 -c "import time; time.sleep(2)"
done
python3 -c "import time; time.sleep(12)"
python3 -I "$HIER/abnahme.py" "$2/hass.log" "$1"
