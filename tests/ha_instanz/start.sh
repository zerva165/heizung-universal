#!/bin/zsh
# Startet eine frische lokale Home-Assistant-Testinstanz (Port 8124) mit dem aktuellen Paket. Aufruf: start.sh <HA-venv> <Arbeitsordner>
set -e
HIER="${0:A:h}"; VENV="$1"; ARBEIT="$2"
[[ -n "$VENV" && -n "$ARBEIT" ]] || { echo "Aufruf: start.sh <venv mit homeassistant> <Arbeitsordner>"; exit 2; }
pkill -f "hass -c $ARBEIT" 2>/dev/null || true
for i in $(seq 1 30); do pgrep -f "hass -c $ARBEIT" > /dev/null || break; python3 -c "import time; time.sleep(1)"; done
pkill -9 -f "hass -c $ARBEIT" 2>/dev/null || true
python3 -c "import time; time.sleep(1)"
rm -rf "$ARBEIT"; mkdir -p "$ARBEIT/.storage"
cp -R "$HIER/vorlage/." "$ARBEIT/"
python3 -I "$HIER/../../tools/paket_bauen.py" > /dev/null
cp -R "$HIER/../../custom_components/heizung_universal" "$ARBEIT/custom_components/"
echo '{"version":4,"minor_version":1,"key":"onboarding","data":{"done":["user","core_config","analytics","integration"]}}' > "$ARBEIT/.storage/onboarding"
"$VENV/bin/hass" --script auth -c "$ARBEIT" add test hz-test-instanz > /dev/null
nohup "$VENV/bin/hass" -c "$ARBEIT" > "$ARBEIT/hass.log" 2>&1 &
echo "gestartet (PID $!) – Protokoll: $ARBEIT/hass.log"
