#!/usr/bin/env python3
"""Kopiert AUSSCHLIESSLICH die drei Blueprint-Dateien nach Home Assistant.

Ziel in Home Assistant:  config/blueprints/automation/ha_heizung_universal/
    universelle_raumheizungssteuerung.yaml
    klimaautomatik.yaml
    pv_ueberschussheizen.yaml

Das Skript legt KEINE Automationen, Helfer, Skripte oder Dashboard-Karten an und
ändert nichts Bestehendes. Es verwendet nur zwei Befehle von Home Assistant:
    blueprint/list   (lesen)
    blueprint/save   (eine Blueprint-Datei speichern; HA prüft sie vorher)

Aufruf:
    python3 tools/blueprints_installieren.py                 nur prüfen, schreibt nichts
    python3 tools/blueprints_installieren.py --installieren  kopiert nach Rückfrage (Eingabe JA)
    python3 tools/blueprints_installieren.py --installieren --ueberschreiben
                                                             ersetzt bereits installierte Fassungen dieser drei Dateien
    python3 tools/blueprints_installieren.py --entfernen     löscht genau diese drei Dateien wieder (Eingabe JA)

Umgebungsvariablen: HA_URL, HA_TOKEN (langlebiges Zugriffstoken aus dem HA-Profil; wird nicht gespeichert).
"""
import argparse
import getpass
import hashlib
import os
import re
import sys
from pathlib import Path

BASIS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASIS / "assistent"))
from ha_verbindung import HAFehler, HAVerbindung  # noqa: E402

ORDNER = "ha_heizung_universal"
DATEIEN = ["universelle_raumheizungssteuerung.yaml", "klimaautomatik.yaml", "pv_ueberschussheizen.yaml"]
QUELLE = BASIS / "blueprints" / "automation" / ORDNER


def main():
    ap = argparse.ArgumentParser(description="Installiert nur die drei Heizungs-Blueprints.")
    ap.add_argument("--installieren", action="store_true", help="Dateien nach Rückfrage kopieren")
    ap.add_argument("--ueberschreiben", action="store_true", help="vorhandene Fassungen dieser drei Dateien ersetzen")
    ap.add_argument("--entfernen", action="store_true", help="genau diese drei Dateien wieder löschen")
    args = ap.parse_args()

    texte = {}
    print("Lokale Dateien:")
    for name in DATEIEN:
        datei = QUELLE / name
        if not datei.is_file():
            sys.exit(f"  FEHLT: {datei}")
        text = datei.read_text(encoding="utf-8")
        if not re.search(r"^blueprint:\s*$", text, re.M) or not re.search(r"^  domain: [\"']?automation[\"']?\s*$", text, re.M):
            sys.exit(f"  {name} ist keine Automations-Blueprint – Abbruch.")
        texte[name] = text
        print(f"  {name:45s} {len(text.encode('utf-8')):>7d} Bytes  sha256 {hashlib.sha256(text.encode('utf-8')).hexdigest()[:12]}")

    url = os.environ.get("HA_URL") or input("Home-Assistant-Adresse (z. B. http://homeassistant.local:8123): ").strip()
    token = os.environ.get("HA_TOKEN") or getpass.getpass("Langlebiges Zugriffstoken (wird nicht gespeichert): ")
    ha = HAVerbindung(url, token)
    try:
        version = ha.verbinden()
        print(f"\nVerbunden mit Home Assistant {version}")
        vorhanden = ha.befehl("blueprint/list", domain="automation") or {}
        print(f"Installierte Automations-Blueprints: {len(vorhanden)}")
        belegt = [n for n in DATEIEN if f"{ORDNER}/{n}" in vorhanden]
        for name in DATEIEN:
            print(f"  blueprints/automation/{ORDNER}/{name}: {'bereits vorhanden' if name in belegt else 'frei'}")

        if args.entfernen:
            if not belegt:
                print("\nNichts zu entfernen.")
                return 0
            if input(f"\n{len(belegt)} Blueprint-Datei(en) löschen? Zum Bestätigen JA eingeben: ").strip() != "JA":
                print("Abgebrochen – nichts gelöscht.")
                return 1
            for name in belegt:
                ha.befehl("blueprint/delete", domain="automation", path=f"{ORDNER}/{name}")
                print(f"  gelöscht: {ORDNER}/{name}")
            return 0

        if not args.installieren:
            print("\nNur geprüft – es wurde nichts geschrieben. Zum Kopieren: --installieren")
            return 0
        if belegt and not args.ueberschreiben:
            print("\nMindestens eine Datei ist bereits installiert. Zum Ersetzen zusätzlich --ueberschreiben angeben. Nichts geschrieben.")
            return 1
        print("\nEs werden NUR diese drei Blueprint-Dateien kopiert. Keine Automation, kein Helfer, kein Skript, keine Karte.")
        if input("Zum Kopieren JA eingeben: ").strip() != "JA":
            print("Abgebrochen – nichts geschrieben.")
            return 1
        for name in DATEIEN:
            pfad = f"{ORDNER}/{name}"
            if name in belegt:
                ha.befehl("blueprint/save", domain="automation", path=pfad, yaml=texte[name], allow_override=True)
            else:
                ha.befehl("blueprint/save", domain="automation", path=pfad, yaml=texte[name])
            print(f"  gespeichert: blueprints/automation/{pfad}")
        nachher = ha.befehl("blueprint/list", domain="automation") or {}
        print("\nKontrolle:")
        fehler = 0
        for name in DATEIEN:
            eintrag = nachher.get(f"{ORDNER}/{name}")
            if not isinstance(eintrag, dict) or "error" in eintrag:
                fehler += 1
                print(f"  ✘ {name}: {eintrag}")
            else:
                meta = eintrag.get("metadata") or {}
                print(f"  ✔ {meta.get('name', name)}  ({len(meta.get('input') or {})} Abschnitte/Felder auf oberster Ebene)")
        print("\nFertig. In Home Assistant: Einstellungen → Automationen & Szenen → Blueprints." if not fehler
              else "\nHome Assistant meldet Fehler – siehe oben.")
        return 1 if fehler else 0
    except HAFehler as e:
        print(f"\nFEHLER: {e}\nEs wurde nichts weiter geschrieben.")
        return 2
    finally:
        ha.schliessen()


if __name__ == "__main__":
    sys.exit(main())
