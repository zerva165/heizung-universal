"""Heizung Universal: Einrichtungsoberfläche für die drei Heizungs-Blueprints (ein Eintrag je Raum).

Die Regelung selbst läuft vollständig in den Blueprint-Automationen. Diese Integration legt beim Einrichten eines Raums
Blueprints, Helfer, Zeitpläne, Automationen und die Dashboard-Karte an und entfernt sie wieder, wenn der Raum gelöscht wird.
"""
import logging

from .const import DOMAIN  # noqa: F401

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry):
    return True


async def async_unload_entry(hass, entry):
    return True


async def async_remove_entry(hass, entry):
    """Raum gelöscht: Automationen, Helfer und Karte dieses Raums entfernen; eine abgeschaltete alte Steuerung wird wieder
    eingeschaltet (sofern sie nicht schon endgültig gelöscht wurde). Die Blueprints bleiben installiert."""
    from .assistent import raumassistent as ra
    from .verbindung import mit_verbindung

    r = entry.data.get("rueckbau")
    if not r:
        return
    alt = r.get("alt")
    alt_zurueck = bool(alt) and entry.data.get("alt_status", "neu_aktiv") == "neu_aktiv"

    def entfernen(ha):
        fehler = []
        if alt_zurueck:  # Raum wird entfernt → die alte Steuerung übernimmt wieder
            from .assistent import altsteuerung as al
            fehler += al.wiederherstellen(ha, alt)
            fehler += ra.alte_karten_zurueck(ha, r.get("alte_karten") or [])
        return fehler + ra.rueckbau_ausfuehren(ha, r)

    try:
        fehler = await mit_verbindung(hass, entfernen)
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Rückbau des Raums %s fehlgeschlagen", entry.title)
        return
    bf = entry.data.get("bt_fenster") or {}
    if bf.get("bt"):
        from .config_flow import bt_fenster_setzen
        zurueck = bf.get("alt") if bf.get("alt") and hass.states.get(bf["alt"]) is not None else None
        try:
            await bt_fenster_setzen(hass, bf["bt"], zurueck)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Fenstersensor von Better Thermostat nach dem Entfernen von %s nicht zurückgestellt", entry.title)
    for f in fehler:
        _LOGGER.warning("Rückbau %s: %s", entry.title, f)
