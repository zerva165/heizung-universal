"""Erkennt die IR-Befehle einer Klimaanlage aus der bisherigen Steuerung und aus dem IR-Sender (nur lesend).

Quellen, in dieser Reihenfolge:
1. Alte Skripte und Automationen, die über genau diesen Sender `remote.send_command` ausführen
   (z. B. script.<raum>_klima_20 → power_20, 1 s, eco_20). Daraus ergeben sich Befehlsmuster, Reihenfolge und Stufen.
2. Die im Sender gespeicherten Befehle (Broadlink: .storage/broadlink_remote_<id>_codes), falls die alte Steuerung nichts liefert.

Ergebnis ist ein Vorschlag für die Einrichtungsseite; gesendet oder angelernt wird hier nichts.
"""
from __future__ import annotations

import re
from collections import Counter

_ZAHL = re.compile(r"(?<!\d)(1[6-9]|2\d|3[0-2])(?!\d)")  # Temperaturstufe im Befehlsnamen (16 … 32)
_HEIZ = re.compile(r"heiz|heat|warm", re.I)
_AUS = re.compile(r"(^|[_\-\s])(off|aus)($|[_\-\s])|power_?off", re.I)
_KUEHL_BEVORZUGT = ("power_{stufe}", "kuehlen_{stufe}", "kühlen_{stufe}", "cool_{stufe}", "cooling_{stufe}")
_AUS_BEVORZUGT = ("power_off", "aus", "off", "klima_aus", "ac_off")
HEIZ_STUFEN = (22, 28)  # Standardbereich des PV-Heizens


def vorlage(befehl):
    """('power_20') → ('power_{stufe}', 20); ohne genau eine Stufenzahl → (befehl, None)."""
    treffer = _ZAHL.findall(befehl)
    if len(treffer) != 1:
        return befehl, None
    return _ZAHL.sub("{stufe}", befehl, count=1), int(treffer[0])


def sendungen(cfg, sender):
    """Gesendete IR-Befehle (Gerät, Befehl) einer Skript- oder Automationskonfiguration an diesen Sender, in Ablaufreihenfolge."""
    erg = []

    def ziele(x):
        ids = []
        for quelle in (x.get("target"), x.get("data"), x):
            if isinstance(quelle, dict):
                wert = quelle.get("entity_id")
                ids += wert if isinstance(wert, list) else ([wert] if wert else [])
        return ids

    def lauf(x):
        if isinstance(x, dict):
            akt = str(x.get("action") or x.get("service") or "")
            if akt == "remote.send_command" and sender in ziele(x):
                daten = x.get("data") if isinstance(x.get("data"), dict) else {}
                geraet = str(daten.get("device") or "")
                befehle = daten.get("command")
                for b in befehle if isinstance(befehle, list) else [befehle]:
                    if isinstance(b, str) and b.strip() and "{{" not in b and "{%" not in b and not b.startswith("b64:"):
                        erg.append((geraet, b.strip()))
                return
            for v in x.values():
                lauf(v)
        elif isinstance(x, list):
            for v in x:
                lauf(v)

    lauf(cfg)
    return erg


def _art(folge):
    """Was eine alte Quelle tut: kuehlen | heizen | heizen_aus | aus | None."""
    erster = folge[0][1]
    _, zahl = vorlage(erster)
    if _HEIZ.search(erster):
        return "heizen_aus" if _AUS.search(erster) else ("heizen" if zahl is not None else None)
    if zahl is not None:
        return "kuehlen"
    if len(folge) == 1 and _AUS.search(erster) and "display" not in erster.lower():
        return "aus"
    return None


def _haeufigste(zaehler, bevorzugt=()):
    if not zaehler:
        return None
    for b in bevorzugt:
        if b in zaehler:
            return b
    return zaehler.most_common(1)[0][0]


def erkennen(quellen, gelernt):
    """quellen: {Skript-/Automations-ID: [(Gerät, Befehl), …]} · gelernt: {Gerät: {Befehl, …}} oder None (nicht lesbar).

    Liefert ein dict mit ir_geraet, befehl_kuehlen, befehl_zusatz, befehl_aus, stufe_min, stufe_max, befehl_heizen,
    befehl_heizen_aus, pv_heizstufe, heiz_stufe_min, heiz_stufe_max sowie herkunft (Feld → Quelle) und hinweise (Texte)."""
    gelernt = gelernt or {}
    quellen = {k: v for k, v in quellen.items() if v}
    erg, herkunft, hinweise = {}, {}, []

    # --- Gerät: das Gerät, über das die alte Steuerung die Klimaanlage bedient hat (sonst „klima“ bzw. das mit den meisten Befehlen)
    geraete = Counter(g for folge in quellen.values() for g, _ in folge if g)
    klima_geraete = Counter(folge[0][0] for folge in quellen.values() if _art(folge) in ("kuehlen", "aus", "heizen", "heizen_aus") and folge[0][0])
    if klima_geraete:
        erg["ir_geraet"], herkunft["ir_geraet"] = klima_geraete.most_common(1)[0][0], "alt"
    elif geraete:
        erg["ir_geraet"], herkunft["ir_geraet"] = geraete.most_common(1)[0][0], "alt"
    elif gelernt:
        kandidaten = {g: b for g, b in gelernt.items() if any(vorlage(x)[1] is not None for x in b)} or gelernt
        erg["ir_geraet"] = "klima" if "klima" in kandidaten else max(kandidaten, key=lambda g: len(kandidaten[g]))
        herkunft["ir_geraet"] = "sender"
    geraet = erg.get("ir_geraet")
    im_sender = set(gelernt.get(geraet, ())) if geraet else set()
    eigene = {k: v for k, v in quellen.items() if v[0][0] == geraet}

    # --- Kühlen: häufigste Befehlsfolge der alten Stufen-Skripte (erster Befehl = Kühlen, weitere = Zusatzbefehle in Reihenfolge)
    folgen, stufen_je_folge, belege = Counter(), {}, {}
    for name, folge in eigene.items():
        if _art(folge) != "kuehlen":
            continue
        muster = tuple(vorlage(b)[0] for _, b in folge)
        folgen[muster] += 1
        stufen_je_folge.setdefault(muster, set()).add(vorlage(folge[0][1])[1])
        belege.setdefault(muster, []).append(name)
    if folgen:
        muster = folgen.most_common(1)[0][0]
        # Stufen der alten Skripte, ergänzt um Stufen, für die alle Befehle der Folge im Sender gespeichert sind
        mit_stufe = [m for m in muster if "{stufe}" in m]
        im_sender_komplett = {z for z in range(16, 33) if all(m.replace("{stufe}", str(z)) in im_sender for m in mit_stufe)} if im_sender else set()
        stufen = sorted(stufen_je_folge[muster] | im_sender_komplett)
        erg.update(befehl_kuehlen=muster[0], befehl_zusatz=", ".join(muster[1:]), stufe_min=stufen[0], stufe_max=stufen[-1])
        for k in ("befehl_kuehlen", "befehl_zusatz", "stufe_min", "stufe_max"):
            herkunft[k] = "alt"
        hinweise.append(f"Kühlen wie bisher in {len(belege[muster])} alten Skripten/Automationen ({_kurz(belege[muster])}): "
                        + " → ".join(muster) + f", Stufen {stufen[0]}–{stufen[-1]} °C.")
    elif im_sender:
        muster_im_sender = Counter(vorlage(b)[0] for b in im_sender if vorlage(b)[1] is not None and not _HEIZ.search(b) and not _AUS.search(b))
        kuehl = _haeufigste(muster_im_sender, _KUEHL_BEVORZUGT)
        if kuehl:
            stufen = sorted(vorlage(b)[1] for b in im_sender if vorlage(b)[0] == kuehl)
            erg.update(befehl_kuehlen=kuehl, befehl_zusatz="", stufe_min=stufen[0], stufe_max=stufen[-1])
            for k in ("befehl_kuehlen", "befehl_zusatz", "stufe_min", "stufe_max"):
                herkunft[k] = "sender"
            andere = sorted(m for m in muster_im_sender if m != kuehl)
            hinweise.append(f"Keine alte Steuerung gefunden – Kühlbefehl aus dem Sender gewählt: {kuehl}, Stufen {stufen[0]}–{stufen[-1]} °C."
                            + (f" Ebenfalls gespeichert: {', '.join(andere)} – falls die Fernbedienung einen davon nach dem Kühlbefehl "
                               "braucht, als Zusatzbefehl eintragen." if andere else ""))

    # --- Aus
    aus = Counter(folge[0][1] for folge in eigene.values() if _art(folge) == "aus")
    if aus:
        erg["befehl_aus"], herkunft["befehl_aus"] = _haeufigste(aus, _AUS_BEVORZUGT), "alt"
    elif im_sender:
        kand = Counter(b for b in im_sender if _AUS.search(b) and not _HEIZ.search(b) and "display" not in b.lower())
        if kand:
            erg["befehl_aus"], herkunft["befehl_aus"] = _haeufigste(kand, _AUS_BEVORZUGT), "sender"

    # --- Heizen (PV-Überschussheizen): Muster mit {stufe}, bisherige Heizstufe, Heizen-Aus als fester Befehl
    heiz = Counter()
    heiz_stufen = Counter()
    for folge in eigene.values():
        if _art(folge) == "heizen":
            m, z = vorlage(folge[0][1])
            heiz[m] += 1
            heiz_stufen[z] += 1
    if heiz:
        erg["befehl_heizen"], herkunft["befehl_heizen"] = heiz.most_common(1)[0][0], "alt"
        erg["pv_heizstufe"], herkunft["pv_heizstufe"] = heiz_stufen.most_common(1)[0][0], "alt"
    elif im_sender:
        kand = Counter(vorlage(b)[0] for b in im_sender if _HEIZ.search(b) and not _AUS.search(b) and vorlage(b)[1] is not None)
        if kand:
            erg["befehl_heizen"], herkunft["befehl_heizen"] = kand.most_common(1)[0][0], "sender"
            stufen = sorted(vorlage(b)[1] for b in im_sender if vorlage(b)[0] == erg["befehl_heizen"])
            erg["pv_heizstufe"] = 24 if 24 in stufen else stufen[len(stufen) // 2]
    heiz_aus = Counter(folge[0][1] for folge in eigene.values() if _art(folge) == "heizen_aus")
    if heiz_aus:
        erg["befehl_heizen_aus"], herkunft["befehl_heizen_aus"] = heiz_aus.most_common(1)[0][0], "alt"
    elif im_sender:
        kand = Counter(b for b in im_sender if _HEIZ.search(b) and _AUS.search(b))
        if kand:
            erg["befehl_heizen_aus"], herkunft["befehl_heizen_aus"] = kand.most_common(1)[0][0], "sender"
    if "befehl_heizen" in erg:
        stufe = int(erg.get("pv_heizstufe", 24))
        erg["heiz_stufe_min"], erg["heiz_stufe_max"] = min(HEIZ_STUFEN[0], stufe), max(HEIZ_STUFEN[1], stufe)
        vorhanden = sorted(z for b in im_sender if (z := vorlage(b)[1]) is not None and vorlage(b)[0] == erg["befehl_heizen"])
        hinweise.append(f"Heizen: {erg['befehl_heizen']}" + (f" (im Sender bisher: {', '.join(map(str, vorhanden))} °C)" if vorhanden else "")
                        + (f", Heizen aus: {erg['befehl_heizen_aus']}" if erg.get("befehl_heizen_aus") else "") + ".")
    erg["herkunft"], erg["hinweise"] = herkunft, hinweise
    return erg


def _kurz(namen):
    namen = sorted(namen)
    return ", ".join(namen) if len(namen) <= 3 else f"{namen[0]} … {namen[-1]}"


def sender_der_altsteuerung(skripte, autos, raum_key, raum_name=""):
    """IR-Sender, den alte Skripte/Automationen dieses Raums für die Klimaanlage verwenden (z. B. <raum>_klima_* → remote.…)."""
    stichworte = {raum_key.lower()} | ({raum_name.lower().replace(" ", "_")} if raum_name else set())
    vorne, irgendwo = Counter(), Counter()  # Namen, die mit dem Raum beginnen, haben Vorrang (bad_klima_20 vor gast_bad_klima_20)
    for eid, eintrag in list(skripte.items()) + list(autos.items()):
        name = eid.split(".", 1)[1].lower()
        if not any(s and s in name for s in stichworte) or not any(w in name for w in ("klima", "pv_", "aircon")):
            continue
        ziel_zaehler = vorne if any(s and name.startswith(s + "_") for s in stichworte) else irgendwo
        for ziel in _send_ziele(eintrag.get("config") or {}):
            ziel_zaehler[ziel] += 1
    zaehler = vorne or irgendwo
    return zaehler.most_common(1)[0][0] if zaehler else None


def _send_ziele(cfg):
    ziele = []

    def lauf(x):
        if isinstance(x, dict):
            if str(x.get("action") or x.get("service") or "") == "remote.send_command":
                for quelle in (x.get("target"), x.get("data"), x):
                    if isinstance(quelle, dict) and quelle.get("entity_id"):
                        w = quelle["entity_id"]
                        ziele.extend(e for e in (w if isinstance(w, list) else [w]) if isinstance(e, str) and e.startswith("remote."))
                return
            for v in x.values():
                lauf(v)
        elif isinstance(x, list):
            for v in x:
                lauf(v)

    lauf(cfg)
    return ziele


def quellen_aus(skripte, autos, sender):
    """{Skript-/Automations-ID: [(Gerät, Befehl), …]} aller alten Konfigurationen, die über diesen Sender senden."""
    out = {}
    for eid, eintrag in list(skripte.items()) + list(autos.items()):
        folge = sendungen(eintrag.get("config") or {}, sender)
        if folge:
            out[eid] = folge
    return out
