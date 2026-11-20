"""Nur für die lokale Test-Instanz: nachgebildete IR-Sender (verhalten sich wie Broadlink-Remotes) und eine Klima-Messsteckdose.

Die Klimaanlage im Wohnzimmer ist nachgebildet: Sie läuft nur mit Strom (Steckdose an), reagiert auf die IR-Befehle des
Wohnzimmer-Senders (power_*/heizen_* = läuft, *_off = aus) und kann für Tests „taub“ gestellt werden (die nächsten n Befehle
werden ignoriert, wie bei verdeckter Sichtverbindung).
"""
from homeassistant.helpers.discovery import async_load_platform

DOMAIN = "hz_testgeraete"


class KlimaNachbau:
    def __init__(self):
        self.strom = True
        self.laeuft = False
        self.taub = 0
        self.beobachter = []

    def melden(self):
        for b in self.beobachter:
            b()

    def befehl(self, name):
        if not self.strom:
            return  # ohne Strom geht jeder IR-Befehl verloren
        if self.taub > 0:
            self.taub -= 1
            return
        if name.endswith("_off") or name == "power_off":
            self.laeuft = False
        elif name.startswith(("power_", "heizen_")):
            self.laeuft = True
        self.melden()

    def strom_setzen(self, an):
        self.strom = an
        if not an:
            self.laeuft = False
        self.melden()


async def async_setup(hass, config):
    hass.data[DOMAIN] = {"klima_wohnzimmer": KlimaNachbau()}

    async def taub(call):
        hass.data[DOMAIN]["klima_wohnzimmer"].taub = int(call.data.get("anzahl", 1))

    async def laufen(call):  # z. B. Fremdbedienung mit der Originalfernbedienung nachbilden
        k = hass.data[DOMAIN]["klima_wohnzimmer"]
        k.laeuft = bool(call.data.get("an", True)) and k.strom
        k.melden()

    hass.services.async_register(DOMAIN, "klima_taub", taub)
    hass.services.async_register(DOMAIN, "klima_laufen", laufen)
    for plattform in ("remote", "switch", "sensor"):
        hass.async_create_task(async_load_platform(hass, plattform, DOMAIN, {}, config))
    return True
