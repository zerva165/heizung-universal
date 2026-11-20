"""Leistungsmessung der nachgebildeten Klima-Steckdose: 0 W ohne Strom, 1 W Bereitschaft, 450 W bei laufender Klimaanlage."""
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    async_add_entities([KlimaLeistung(hass.data["hz_testgeraete"]["klima_wohnzimmer"])])


class KlimaLeistung(SensorEntity):
    _attr_should_poll = False
    _attr_name = "Klima Steckdose Wohnzimmer Leistung"
    _attr_unique_id = "hz_test_klima_steckdose_wohnzimmer_leistung"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "W"

    def __init__(self, klima):
        self.entity_id = "sensor.klima_steckdose_wohnzimmer_leistung"
        self._klima = klima

    @property
    def native_value(self):
        return 0.0 if not self._klima.strom else (450.0 if self._klima.laeuft else 1.0)

    async def async_added_to_hass(self):
        self._klima.beobachter.append(self.async_write_ha_state)
