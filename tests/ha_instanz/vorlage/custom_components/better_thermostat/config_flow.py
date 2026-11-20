import voluptuous as vol
from homeassistant import config_entries


class TestBT(config_entries.ConfigFlow, domain="better_thermostat"):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            # Speicherformat wie Better Thermostat 2.0: alles in den Optionen, Heizkörperthermostate als Liste mit Integration, Modell, Kalibrierung
            trvs = [x for x in (user_input.get("trv") or "").split(",") if x]
            return self.async_create_entry(title=user_input["name"], data={"name": user_input["name"]}, options={
                "window_sensors": user_input.get("window_sensors") or None, "window_off_delay": 30,
                "temperature_sensor": user_input.get("temperature_sensor") or None,
                "thermostat": [{"trv": t, "integration": "generic_thermostat", "model": "generic", "adapter": None,
                                "advanced": {"calibration": "target_temp_based", "child_lock": False}} for t in trvs]})
        return self.async_show_form(step_id="user", data_schema=vol.Schema({vol.Required("name"): str, vol.Optional("window_sensors"): str,
                                                                            vol.Optional("temperature_sensor"): str, vol.Optional("trv"): str}))
