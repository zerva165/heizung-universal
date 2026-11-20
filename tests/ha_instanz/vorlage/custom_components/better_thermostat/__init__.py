"""Kleiner Nachbau von Better Thermostat für die Abnahme: Fenstersensor steht wie beim Original in den Optionen (window_sensors)."""
from homeassistant.const import Platform


async def async_setup_entry(hass, entry):
    await hass.config_entries.async_forward_entry_setups(entry, [Platform.CLIMATE])
    return True


async def async_unload_entry(hass, entry):
    return await hass.config_entries.async_unload_platforms(entry, [Platform.CLIMATE])
