"""Nachgebildeter IR-Sender: lernt Befehle je Gerät, sendet nur bekannte Befehle, kann ausfallen."""
from homeassistant.components.remote import RemoteEntity, RemoteEntityFeature
from homeassistant.exceptions import HomeAssistantError

WOHNZIMMER = {"klima": ["power_off", "heizen_24", "heizen_24_off"] + [f"power_{t}" for t in range(16, 24)] + [f"eco_{t}" for t in range(16, 24)]}


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    async_add_entities([TestSender("Broadlink Wohnzimmer", "broadlink_wohnzimmer", WOHNZIMMER), TestSender("Broadlink Schlafzimmer", "broadlink_schlafzimmer", {}),
                        TestSender("Broadlink Ersatz", "broadlink_ersatz", {})])


class TestSender(RemoteEntity):
    _attr_supported_features = RemoteEntityFeature.LEARN_COMMAND | RemoteEntityFeature.DELETE_COMMAND
    _attr_should_poll = False

    def __init__(self, name, kennung, codes):
        self._attr_name = name
        self._attr_unique_id = f"hz_test_{kennung}"
        self.entity_id = f"remote.{kennung}"
        self._attr_is_on = True
        self._codes = {g: list(b) for g, b in codes.items()}
        self._gesendet = []

    @property
    def extra_state_attributes(self):
        return {"gesendet": self._gesendet[-40:], "gelernt": self._codes}

    async def async_turn_on(self, **kwargs):
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        self._attr_is_on = False
        self.async_write_ha_state()

    async def async_send_command(self, command, **kwargs):
        if not self._attr_is_on:  # wie Broadlink: ausgeschaltet → es wird stillschweigend nichts gesendet
            return
        geraet = kwargs.get("device")
        for befehl in command:
            if befehl not in self._codes.get(geraet, []):
                raise HomeAssistantError(f"Command not found: {befehl!r} (device {geraet!r})")
            self._gesendet = self._gesendet + [befehl]
            if self.entity_id == "remote.broadlink_wohnzimmer" and "hz_testgeraete" in self.hass.data:
                self.hass.data["hz_testgeraete"]["klima_wohnzimmer"].befehl(befehl)
        self.async_write_ha_state()

    async def async_learn_command(self, **kwargs):
        if kwargs["command"][0].startswith("zeitueberschreitung"):
            raise HomeAssistantError("No infrared code received within 30.0 seconds")
        self._codes.setdefault(kwargs.get("device"), [])
        for befehl in kwargs["command"]:
            if befehl not in self._codes[kwargs.get("device")]:
                self._codes[kwargs.get("device")].append(befehl)
        self.async_write_ha_state()
