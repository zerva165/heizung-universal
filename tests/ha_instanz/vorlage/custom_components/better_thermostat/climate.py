from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature, HVACMode
from homeassistant.const import UnitOfTemperature
from homeassistant.core import callback
from homeassistant.helpers.event import async_track_state_change_event


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([TestBTKlima(entry)])


class TestBTKlima(ClimateEntity):
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.TURN_OFF | ClimateEntityFeature.TURN_ON
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_should_poll = False

    def __init__(self, entry):
        self._entry = entry
        self._attr_name = entry.data["name"]
        self._attr_unique_id = entry.entry_id
        self._attr_hvac_mode = HVACMode.HEAT
        self._attr_target_temperature = 20
        self._attr_current_temperature = 20
        self._fenster = entry.options.get("window_sensors")

    async def async_added_to_hass(self):
        if self._fenster:
            self.async_on_remove(async_track_state_change_event(self.hass, [self._fenster], self._geaendert))

    @callback
    def _geaendert(self, _event):
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self):
        z = self.hass.states.get(self._fenster) if self._fenster else None
        o = self._entry.options
        return {"window_sensor": self._fenster, "window_open": bool(z and z.state == "on"), "temperature_sensor": o.get("temperature_sensor"),
                "trvs": [t.get("trv") for t in o.get("thermostat") or []],
                "trv_kalibrierung": [(t.get("advanced") or {}).get("calibration") for t in o.get("thermostat") or []]}

    async def async_set_temperature(self, **kwargs):
        if "temperature" in kwargs:
            self._attr_target_temperature = kwargs["temperature"]
        if kwargs.get("hvac_mode"):
            self._attr_hvac_mode = kwargs["hvac_mode"]
        self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode):
        self._attr_hvac_mode = hvac_mode
        self.async_write_ha_state()
