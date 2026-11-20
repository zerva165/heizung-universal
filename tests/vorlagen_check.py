#!/usr/bin/env python3
"""Übersetzt JEDE Jinja-Vorlage der drei Blueprints (Syntaxprüfung).

Findet Klammer- und Blockfehler auch in Zweigen, die im Betrieb selten laufen
(z. B. die Bewertung des Vorheizens zur Zieluhrzeit). Benötigt Jinja2.
"""
import sys
from pathlib import Path

import jinja2

sys.path.insert(0, str(Path(__file__).parent))
from simulator import lade_blueprint  # noqa: E402

ORDNER = Path(__file__).resolve().parent.parent / "blueprints/automation/ha_heizung_universal"
env = jinja2.Environment()
for name in ["is_state", "state_attr", "states", "now", "as_datetime", "as_timestamp", "today_at"]:
    env.globals[name] = lambda *a, **k: None
for name in ["float", "int", "is_number", "is_state", "regex_replace", "regex_findall", "as_datetime",
             "as_timestamp", "from_json", "to_json", "timestamp_custom", "contains", "slugify", "bool"]:
    env.filters.setdefault(name, lambda *a, **k: None)
for name in ["is_state", "match", "search", "contains", "is_number"]:
    env.tests.setdefault(name, lambda *a, **k: False)

fehler = 0
for datei in sorted(ORDNER.glob("*.yaml")):
    bp = lade_blueprint(datei)
    anzahl = 0

    def lauf(o, pfad):
        global fehler, anzahl
        if isinstance(o, dict):
            for k, v in o.items():
                lauf(v, f"{pfad}/{k}")
        elif isinstance(o, list):
            for i, v in enumerate(o):
                lauf(v, f"{pfad}[{i}]")
        elif isinstance(o, str) and ("{{" in o or "{%" in o):
            anzahl += 1
            try:
                env.from_string(o)
            except jinja2.TemplateError as e:
                fehler += 1
                print(f"  ✘ {datei.name} {pfad}: {e}\n      {o[:160]}")

    for teil in ["variables", "trigger_variables", "triggers", "trigger", "conditions", "condition", "actions", "action"]:
        if teil in bp:
            lauf(bp[teil], teil)
    print(f"  {'✔' if not fehler else '·'} {datei.name}: {anzahl} Vorlagen übersetzt")
print("Vorlagen-Syntax:", "OK" if not fehler else f"{fehler} FEHLER")
sys.exit(1 if fehler else 0)
