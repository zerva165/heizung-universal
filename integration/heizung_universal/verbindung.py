"""Verbindung der Integration zu ihrem eigenen Home Assistant über die offiziellen WebSocket- und REST-Schnittstellen.

Die Einrichtung verwendet damit genau die Befehle, die auch die Oberfläche von Home Assistant benutzt
(Helfer anlegen, Blueprint speichern, Automation speichern, Dashboard speichern). Home Assistant prüft jede Eingabe selbst.
Dafür wird kurzzeitig ein Systembenutzer angelegt und nach dem Vorgang wieder entfernt.
"""
from homeassistant.auth.const import GROUP_ID_ADMIN

from .assistent.ha_verbindung import HAFehler, HAVerbindung


async def mit_verbindung(hass, funktion):
    benutzer = await hass.auth.async_create_system_user("Heizung Universal – Einrichtung", group_ids=[GROUP_ID_ADMIN])
    try:
        erneuerung = await hass.auth.async_create_refresh_token(benutzer)
        token = hass.auth.async_create_access_token(erneuerung)
        api = hass.config.api
        schema = "https" if api.use_ssl else "http"
        adressen = [f"{schema}://127.0.0.1:{api.port}"] + ([f"{schema}://{api.local_ip}:{api.port}"] if api.local_ip not in ("127.0.0.1", "0.0.0.0") else [])

        def lauf():
            letzter = None
            for url in adressen:
                ha = HAVerbindung(url, token, timeout=60, ssl_pruefen=False)
                try:
                    ha.verbinden()
                except (OSError, HAFehler) as ex:
                    letzter = ex
                    continue
                try:
                    return funktion(ha)
                finally:
                    ha.schliessen()
            raise HAFehler(f"Keine Verbindung zum eigenen Home Assistant: {letzter}")

        return await hass.async_add_executor_job(lauf)
    finally:
        await hass.auth.async_remove_user(benutzer)
