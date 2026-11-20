"""Nachgebildete schaltbare Messsteckdose vor der Wohnzimmer-Klimaanlage."""
from homeassistant.components.switch import SwitchEntity


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    async_add_entities([KlimaSteckdose(hass.data["hz_testgeraete"]["klima_wohnzimmer"])])


class KlimaSteckdose(SwitchEntity):
    _attr_should_poll = False
    _attr_name = "Klima Steckdose Wohnzimmer"
    _attr_unique_id = "hz_test_klima_steckdose_wohnzimmer"

    def __init__(self, klima):
        self.entity_id = "switch.klima_steckdose_wohnzimmer"
        self._klima = klima

    @property
    def is_on(self):
        return self._klima.strom

    async def async_added_to_hass(self):
        self._klima.beobachter.append(self.async_write_ha_state)

    async def async_turn_on(self, **kwargs):
        self._klima.strom_setzen(True)

    async def async_turn_off(self, **kwargs):
        self._klima.strom_setzen(False)
