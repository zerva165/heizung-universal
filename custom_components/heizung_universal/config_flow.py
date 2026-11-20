"""Einrichtungsoberfläche „Heizung Universal“: ein Eintrag je Raum.

Einstellungen → Geräte & Dienste → Integration hinzufügen → „Heizung Universal“.
Der Ablauf fragt Geräte und Funktionen ab, legt danach Blueprints, Helfer, Zeitpläne, Automationen und die
Dashboard-Karte an. Entfernen des Eintrags baut genau diese Bestandteile wieder ab.
"""
from __future__ import annotations

import copy
import functools
import sys
from types import SimpleNamespace
import json
import logging

try:  # Home Assistant 2026.11 verwendet probatio, ältere Versionen voluptuous (gleiche Schreibweise)
    import probatio as vol
except ImportError:  # pragma: no cover
    import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector as sel
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .assistent import raumassistent as ra
from .assistent import altsteuerung as al
from .assistent import irerkennung as ie
from .assistent import altuebernahme as au
from .verbindung import mit_verbindung

_LOGGER = logging.getLogger(__name__)

TAGE = [("mo", "Montag"), ("di", "Dienstag"), ("mi", "Mittwoch"), ("do", "Donnerstag"), ("fr", "Freitag"), ("sa", "Samstag"), ("so", "Sonntag")]
WERKTAGE, WOCHENENDE, ALLE = ["mo", "di", "mi", "do", "fr"], ["sa", "so"], [t for t, _ in TAGE]
TAGESPROGRAMME = ra.TAGESPROGRAMME  # (Schlüssel, Name, Wochentage): Montag bis Freitag, Samstag, Sonntag
BEREICH = {"wt": "montag_bis_freitag", "sa": "samstag", "so": "sonntag"}  # Feldnamen der drei Bereiche im Profil-Schritt
STANDARD = {"komfort": (22, 16), "uebergang": (21, 16), "urlaub": (17, 16), "sommer": (19, 16)}  # Soll, Absenk
FENSTERKLASSEN = ["window", "door", "opening", "garage_door"]
KLAMMERN = {"stufe": "{stufe}", "luefter": "{luefter}"}


def _wahl(optionen, mehrfach=False):
    return sel.SelectSelector(sel.SelectSelectorConfig(
        options=[sel.SelectOptionDict(value=str(v), label=str(text)) for v, text in optionen], multiple=mehrfach,
        mode=sel.SelectSelectorMode.LIST if mehrfach or len(optionen) <= 4 else sel.SelectSelectorMode.DROPDOWN))


def _zahl(mn, mx, schritt, einheit=None):
    return sel.NumberSelector(sel.NumberSelectorConfig(min=mn, max=mx, step=schritt, unit_of_measurement=einheit, mode=sel.NumberSelectorMode.BOX))


def _ent(domain, klasse=None, mehrfach=False):
    cfg = {"domain": domain, "multiple": mehrfach}
    if klasse:
        cfg["device_class"] = klasse
    return sel.EntitySelector(sel.EntitySelectorConfig(**cfg))


_JA = sel.BooleanSelector()
_ZEIT = sel.TimeSelector()
_TEXT = sel.TextSelector()


async def gespeicherte_befehle(hass, entity_id):
    """Alle im IR-Sender gespeicherten Befehlsnamen je Gerät: {Gerät: {Befehl, …}} (nur lesend). None = nicht feststellbar."""
    zustand = hass.states.get(entity_id)
    if zustand is not None and isinstance(zustand.attributes.get("gelernt"), dict):
        return {g: set(b) for g, b in zustand.attributes["gelernt"].items()}
    eintrag = er.async_get(hass).async_get(entity_id)
    if eintrag is not None and eintrag.platform == "broadlink" and eintrag.unique_id:
        daten = await Store(hass, 1, f"broadlink_remote_{eintrag.unique_id}_codes").async_load()
        return {g: set(b) for g, b in (daten or {}).items() if isinstance(b, dict)}
    return None


async def bekannte_befehle(hass, entity_id, geraet):
    """Bereits im IR-Sender gespeicherte Befehlsnamen dieses Geräts (nur lesend). None = nicht feststellbar."""
    alle = await gespeicherte_befehle(hass, entity_id)
    return None if alle is None else set(alle.get(geraet, set()))


def zusatzbefehle(text):
    """„eco_{stufe}, display_off“ → ["eco_{stufe}", "display_off"] (Reihenfolge wie gesendet)."""
    return [t.strip() for t in str(text or "").split(",") if t.strip()]


def kurzliste(namen, hoechstens=10):
    namen = list(namen)
    return ", ".join(namen) if len(namen) <= hoechstens else ", ".join(namen[:hoechstens]) + f" … (+{len(namen) - hoechstens})"


def befehlsliste(a):
    """Alle IR-Befehle, die die Konfiguration dieses Raums benötigt: (Name, Anleitung)."""
    lf = a.get("luefter") or ""
    zus = f", Lüfter „{lf}“" if lf else ""

    def name(vorlage, stufe=None):
        return vorlage.replace("{stufe}", str(stufe if stufe is not None else "")).replace("{luefter}", lf)

    liste, gesehen = [], set()

    def dazu(n, text):
        if n and n not in gesehen:
            gesehen.add(n)
            liste.append((n, text))

    dazu(name(a["befehl_aus"]), "Klimaanlage AUS")
    for st in range(int(a["stufe_min"]), int(a["stufe_max"]) + 1):
        dazu(name(a["befehl_kuehlen"], st), f"KÜHLEN, {st} °C{zus}")
        for z in zusatzbefehle(a.get("befehl_zusatz")):
            dazu(name(z, st), f"Zusatzbefehl nach Kühlen {st} °C")
    for n, t in heizbefehle(a):
        dazu(n, t)
    return liste


def heizbefehle(a):
    """Heizbefehle für das PV-Überschussheizen: (Name, Anleitung). Mit {stufe} im Namen ein Befehl je Heizstufe."""
    if not a.get("pv"):
        return []
    lf = a.get("luefter") or ""
    zus = f", Lüfter „{lf}“" if lf else ""
    stufen = range(int(a.get("heiz_stufe_min", 24)), int(a.get("heiz_stufe_max", 24)) + 1)
    liste = []
    for vorlage, text in ((a.get("befehl_heizen"), "HEIZEN {st} °C (vollständiger Zustand für das PV-Überschussheizen)" + zus),
                          (a.get("befehl_heizen_aus"), "HEIZEN AUS{nach}")):
        if not vorlage:
            continue
        for st in (stufen if "{stufe}" in vorlage else [None]):
            n = vorlage.replace("{stufe}", str(st) if st is not None else "").replace("{luefter}", lf)
            if n and n not in [x for x, _ in liste]:
                liste.append((n, text.format(st=st if st is not None else a.get("pv_heizstufe", 24), nach=f" (nach Heizen {st} °C)" if st else "")))
    return liste


def bt_eintrag(hass, bt):
    """Konfigurationseintrag von Better Thermostat zu dieser Klima-Entität (oder None, z. B. bei anderen Thermostaten)."""
    reg = er.async_get(hass).async_get(bt) if bt else None
    if reg is None or not reg.config_entry_id:
        return None
    eintrag = hass.config_entries.async_get_entry(reg.config_entry_id)
    return eintrag if eintrag is not None and eintrag.domain == "better_thermostat" else None


def bt_fenster_lesen(hass, bt):
    eintrag = bt_eintrag(hass, bt)
    if eintrag is None:
        return None
    return eintrag.options.get("window_sensors", eintrag.data.get("window_sensors"))


async def bt_fenster_setzen(hass, bt, sensor):
    """Trägt den Fensterstatus-Helfer als Fenstersensor in Better Thermostat ein (Optionen, danach neu laden). Rückgabe: bisheriger Wert.
    Die Verzögerungen und alle anderen Einstellungen von Better Thermostat bleiben unverändert."""
    eintrag = bt_eintrag(hass, bt)
    if eintrag is None:
        return None
    vorher = eintrag.options.get("window_sensors", eintrag.data.get("window_sensors"))
    if vorher != sensor:
        if "window_sensors" in eintrag.options or "window_sensors" not in eintrag.data:
            hass.config_entries.async_update_entry(eintrag, options={**eintrag.options, "window_sensors": sensor})
        else:
            hass.config_entries.async_update_entry(eintrag, data={**eintrag.data, "window_sensors": sensor})
        await hass.config_entries.async_reload(eintrag.entry_id)
    return vorher


BT_FUEHLER = ("temperature_sensor", "humidity_sensor", "outdoor_sensor", "door_sensors", "cooler", "weather")


def _bt_optionen(eintrag):
    """Better Thermostat 2.0 speichert alles in den Optionen; ältere Einträge (und der Testnachbau) teils in den Daten."""
    return {**eintrag.data, **eintrag.options}


def bt_geraete(hass, bt):
    """Geräte, die das Better Thermostat selbst verwendet: Heizkörperthermostate und Fühler (ohne Fenster-Helfer). → [entity_id]"""
    eintrag = bt_eintrag(hass, bt)
    if eintrag is None:
        return []
    o = _bt_optionen(eintrag)
    out = [t["trv"] for t in (o.get("thermostat") or []) if isinstance(t, dict) and isinstance(t.get("trv"), str)]
    for k in BT_FUEHLER:
        v = o.get(k)
        out += [x for x in (v if isinstance(v, list) else [v]) if isinstance(x, str) and "." in x and x not in out]
    return out


def _plattform(hass, eid):
    reg = er.async_get(hass).async_get(eid)
    return reg.platform if reg else None


_VENTIL = ("ventil", "valve", "offnungsgrad", "öffnungsgrad")


def ventile_zu_trvs(hass, trvs):
    """Ventilöffnungs-Sensoren derselben Geräte wie die Heizkörperthermostate. → (aktive, deaktivierte) Entitäten."""
    reg = er.async_get(hass)
    aktiv, aus = [], []
    for trv in trvs or []:
        e = reg.async_get(trv)
        if e and e.device_id:
            for x in er.async_entries_for_device(reg, e.device_id, include_disabled_entities=True):
                name = f"{x.entity_id} {x.original_name or ''} {x.name or ''}".lower()
                if x.domain == "sensor" and any(w in name for w in _VENTIL):
                    (aus if x.disabled_by else aktiv).append(x.entity_id)
        else:  # ohne Gerät: übliche Namensmuster
            objekt = trv.split(".", 1)[1]
            for eid in (f"sensor.{objekt}_ventil_offnungsgrad", f"sensor.{objekt}_valve_position", f"sensor.{objekt}_ventil"):
                if hass.states.get(eid) is not None:
                    aktiv.append(eid)
                    break
    return list(dict.fromkeys(aktiv)), list(dict.fromkeys(aus))


def zeitstempel_attribut(hass, sensor):
    """Attribut eines Energiesensors mit dem Zeitpunkt der letzten echten Daten (z. B. ein Attribut …_last_update) oder ""."""
    st = hass.states.get(sensor) if sensor else None
    for k in (st.attributes if st else {}):
        if any(w in k.lower() for w in ("last_update", "timestamp", "zeitstempel")):
            return k
    return ""


def leistung_zur_steckdose(hass, schalter):
    """Leistungssensor (W) desselben Geräts wie die Steckdose der Klimaanlage – Vorschlag für die Rückmeldung. Leer, wenn keiner da ist."""
    reg = er.async_get(hass)
    e = reg.async_get(schalter) if schalter else None
    if not e or not e.device_id:  # ohne Gerät: übliche Namensmuster derselben Steckdose
        objekt = schalter.split(".", 1)[1] if schalter else ""
        for eid in (f"sensor.{objekt}_leistung", f"sensor.{objekt}_power"):
            st = hass.states.get(eid) if objekt else None
            if st and (st.attributes.get("device_class") == "power" or st.attributes.get("unit_of_measurement") == "W"):
                return eid
        return ""
    kandidaten = []
    for x in er.async_entries_for_device(reg, e.device_id):
        if x.domain != "sensor" or x.disabled_by:
            continue
        st = hass.states.get(x.entity_id)
        klasse = x.device_class or x.original_device_class or (st.attributes.get("device_class") if st else None)
        if klasse == "power":
            einheit = (st.attributes.get("unit_of_measurement") if st else None) or x.unit_of_measurement
            kandidaten.append((einheit != "W", "device" in x.entity_id, x.entity_id))  # W vor kW, Messwert vor Eigenverbrauch
    return sorted(kandidaten)[0][2] if kandidaten else ""


async def _bt_modell(hass, eintrag, eid, vorher):
    """Modell eines Heizkörperthermostats so, wie Better Thermostat es selbst bestimmt; sonst das bisherige behalten."""
    hilfen = sys.modules.get("custom_components.better_thermostat.utils.helpers")  # schon von BT geladen – kein Import im Event-Loop
    try:
        return await hilfen.get_device_model(SimpleNamespace(hass=hass, device_name=eintrag.title), eid, configured_model=vorher)
    except Exception:  # noqa: BLE001 – andere BT-Version oder Testnachbau
        reg = er.async_get(hass).async_get(eid)
        dev = dr.async_get(hass).async_get(reg.device_id) if reg and reg.device_id else None
        return (dev.model_id or dev.model) if dev and (dev.model_id or dev.model) else vorher


async def bt_geraet_tauschen(hass, bt, alt, neu):
    """Tauscht ein Gerät auch in den Einstellungen des Better Thermostat (Fühler, Heizkörperthermostate) und lädt es neu.

    Heizkörperthermostate werden nur getauscht, wenn das neue zur selben Geräte-Integration gehört (z. B. Homematic IP → Homematic IP):
    Dann bleiben Kalibrierung und Ventilsteuerung gültig. Bei einer anderen Integration richtet Better Thermostat diese neu ein –
    dann bleibt es unverändert und der Hinweis sagt das. Rückgabe: (geändert, Hinweis oder None)."""
    eintrag = bt_eintrag(hass, bt)
    if eintrag is None or alt == bt:
        return False, None
    teile = {"options": copy.deepcopy(dict(eintrag.options)), "data": copy.deepcopy(dict(eintrag.data))}
    geaendert, hinweis, betroffen = False, None, set()
    for k in BT_FUEHLER:
        teil = "options" if k in teile["options"] else "data"
        if k in teile[teil] and ra._ersetzen(teile[teil][k], alt, neu) != teile[teil][k]:  # noqa: SLF001
            teile[teil][k] = ra._ersetzen(teile[teil][k], alt, neu)  # noqa: SLF001
            geaendert = True
            betroffen.add(teil)
    teil = "options" if "thermostat" in teile["options"] else "data"
    for i, t in enumerate(teile[teil].get("thermostat") or []):
        if not (isinstance(t, dict) and t.get("trv") == alt):
            continue
        p_alt, p_neu = t.get("integration") or _plattform(hass, alt), _plattform(hass, neu)
        if p_neu and p_neu == p_alt:
            teile[teil]["thermostat"][i] = dict(t, trv=neu, model=await _bt_modell(hass, eintrag, neu, t.get("model")))
            geaendert = True
            betroffen.add(teil)
        else:
            hinweis = (f"Im Better Thermostat ist {alt} nicht getauscht: {neu} gehört zu einer anderen Geräte-Integration "
                       f"({p_neu or 'unbekannt'} statt {p_alt or 'unbekannt'}). Better Thermostat richtet dafür Kalibrierung und Ventilsteuerung "
                       "neu ein – bitte dort unter „Konfigurieren“ das Heizkörperthermostat tauschen.")
    if geaendert:
        hass.config_entries.async_update_entry(eintrag, **{t: teile[t] for t in betroffen})
        await hass.config_entries.async_reload(eintrag.entry_id)
    return geaendert, hinweis


def fenster_ziel(a, entitaeten):
    """Welcher Helfer soll Fenstersensor von Better Thermostat sein? (eigene Kontakte → Fensterstatus des Raums, extern → der andere Raum)"""
    if a.get("fenster_modus") == "eigen":
        return (entitaeten or {}).get("fensterstatus")
    if a.get("fenster_modus") == "extern":
        return a.get("fensterstatus_extern") or None
    return None


# Seiten mit dem Schalter „Zurück zum vorherigen Schritt“ (Anlern-Seiten haben eigene Knöpfe und senden Befehle – dorthin geht es nicht zurück)
ZURUECK_SCHRITTE = {"funktionen", "profil", "fenster", "fenster_extern", "werte", "termin", "klima_sender", "klima", "klima_schalter", "pv", "altsteuerung",
                    "alte_karten", "dashboard", "ansicht", "platz", "position", "bestaetigen", "lernen_auswahl", "aendern_bestaetigen"}


def mit_zurueck(fn):
    """Merkt sich jede abgeschickte Seite und bietet auf der nächsten den Schalter „Zurück“. Zurück zeigt die vorherige Seite mit den
    bisherigen Eingaben (die Schritte füllen ihre Felder aus self.a vor). Eingaben der Seite, von der man zurückgeht, werden verworfen."""
    name = fn.__name__[len("async_step_"):]

    @functools.wraps(fn)
    async def huelle(self, user_input=None):
        if user_input is not None and user_input.get("zurueck"):
            return await self._zurueck(name)
        stand = None
        if user_input is not None:
            user_input = {k: v for k, v in user_input.items() if k != "zurueck"}
            stand = self._nav_stand(name)
        erg = await fn(self, user_input)
        if stand is not None and not (erg.get("type") == "form" and erg.get("step_id") == name and erg.get("errors")):
            self._verlauf_liste().append(stand)
        return self._zurueck_feld(erg)
    return huelle


class Schritte:
    """Gemeinsame Schritte von Ersteinrichtung und späterer Anpassung: IR-Anlernen und Kartenplatzierung."""

    _NAV = ("_ablauf", "_pi", "_profile", "_dbs", "ziele", "_db", "_dbname", "_cfg", "_vi", "_plaetze", "_empf", "_pi2", "_lern_nur")

    def _verlauf_liste(self):
        if not hasattr(self, "_verlauf_nav"):
            self._verlauf_nav = []
        return self._verlauf_nav

    def _nav_stand(self, name):
        stand = {k: (list(v) if isinstance(v, list) else v) for k in self._NAV if (v := getattr(self, k, None)) is not None or True}
        stand["termine"] = json.loads(json.dumps((getattr(self, "a", None) or {}).get("termine", [])))
        return name, stand

    async def _zurueck(self, aktuell):
        verlauf = self._verlauf_liste()
        if not verlauf:
            return await getattr(self, f"async_step_{aktuell}")()
        name, stand = verlauf.pop()
        for k in self._NAV:
            setattr(self, k, list(stand[k]) if isinstance(stand[k], list) else stand[k])
        if getattr(self, "a", None) is not None:
            self.a["termine"] = stand["termine"]
        if name == "funktionen":
            self._nur_neues = False  # beim Weitergehen alle Seiten wieder zeigen (vorausgefüllt)
        return await getattr(self, f"async_step_{name}")()

    def _zurueck_feld(self, erg):
        if (isinstance(erg, dict) and erg.get("type") == "form" and erg.get("step_id") in ZURUECK_SCHRITTE and self._verlauf_liste()
                and erg.get("data_schema") is not None and "zurueck" not in [str(k) for k in erg["data_schema"].schema]):
            erg["data_schema"] = erg["data_schema"].extend({vol.Optional("zurueck", default=False): _JA})
        return erg

    # ------------------------------------------------------------------ IR-Anlernen
    @mit_zurueck
    async def async_step_lernen_auswahl(self, user_input=None):
        fehler = {}
        alle = befehlsliste(self.a)
        nur = getattr(self, "_lern_nur", None)  # Klima-Schritt: nur Kühlbefehle · PV-Schritt: nur Heizbefehle · Konfigurieren: alle
        if nur is not None:
            alle = [(n, t) for n, t in alle if n in nur]
        vorhanden = await bekannte_befehle(self.hass, self.a["klima_sender"], self.a["ir_geraet"])
        if user_input is not None:
            lernen, testen = user_input.get("befehle") or [], user_input.get("testen") or []
            wuerde_ersetzen = sorted(n for n in lernen if vorhanden is not None and n in vorhanden)
            if wuerde_ersetzen and not user_input.get("ueberschreiben"):
                fehler["base"] = "ueberschreiben"
            else:
                # (Name, Bedeutung, "lernen" | "testen"): zuerst anlernen (mit Test), dann vorhandene Befehle nur testen
                self._lern = [(n, t, "lernen") for n, t in alle if n in lernen] + [(n, t, "testen") for n, t in alle if n in testen and n not in lernen]
                self._li = 0
                self._gelernt = []
                return await self._lern_start() if self._lern else await self._nach_lernen()

        def text(n, t):
            return f"{n} – {t}" + ("" if vorhanden is None else (" · bereits vorhanden" if n in vorhanden else " · fehlt noch"))

        fehlend = [n for n, _ in alle if vorhanden is not None and n not in vorhanden]
        stand = ("Der Sender kann nicht nach gespeicherten Befehlen gefragt werden – bitte selbst auswählen." if vorhanden is None
                 else f"Im Sender unter „{self.a['ir_geraet']}“ gespeichert: {len(vorhanden)} Befehle. Vorgeschlagen zum Anlernen sind nur die fehlenden.")
        # PV-Heizen sendet „Heizen“ in der eingestellten Heizstufe und „Heizen aus“: einmal testen = IR-Prüffreigabe wird danach gesetzt
        a = self.a
        stufe, lf = str(int(a.get("pv_heizstufe", 24))), a.get("luefter") or ""
        pv_noetig = [n for n in dict.fromkeys((a.get(k) or "").replace("{stufe}", stufe).replace("{luefter}", lf) for k in ("befehl_heizen", "befehl_heizen_aus"))
                     if a.get("pv") and n and n in {x for x, _ in alle}]
        test_vorschlag = [n for n in pv_noetig if vorhanden is not None and n in vorhanden]
        if pv_noetig:
            stand += (f" Für die IR-Prüffreigabe des PV-Heizens werden {' und '.join(pv_noetig)} einmal testweise gesendet und von Ihnen bestätigt"
                      " („Befehl ist richtig“) – danach darf PV-Heizen starten.")
        return self.async_show_form(step_id="lernen_auswahl", errors=fehler, data_schema=vol.Schema({
            vol.Optional("befehle", default=fehlend): _wahl([(n, text(n, t)) for n, t in alle], mehrfach=True),
            vol.Optional("testen", default=test_vorschlag): _wahl([(n, text(n, t)) for n, t in alle], mehrfach=True),
            vol.Required("ueberschreiben", default=False): _JA}),
            description_placeholders={"sender": self.a["klima_sender"], "geraet": self.a["ir_geraet"], "raum": self.a["raum_name"], "stand": stand})

    async def _lern_start(self):
        self._test = ""
        return await (self.async_step_lernen() if self._lern[self._li][2] == "lernen" else self.async_step_lernen_test())

    async def async_step_lernen(self, user_input=None):
        fehler, meldung = {}, ""
        name, text, _ = self._lern[self._li]
        if user_input is not None:
            if user_input["aktion"] == "beenden":
                return await self._nach_lernen()
            if user_input["aktion"] == "ueberspringen":
                return await self._lern_weiter()
            try:
                await self.hass.services.async_call("remote", "learn_command", {
                    "entity_id": self.a["klima_sender"], "device": self.a["ir_geraet"], "command": [name],
                    "command_type": "ir", "timeout": 30}, blocking=True)
            except Exception as ex:  # noqa: BLE001 – jede Ursache wird dem Nutzer angezeigt
                fehler["base"] = "lernen_fehlgeschlagen"
                meldung = str(ex)
            else:
                self._gelernt.append(name)
                self._test = ""
                return await self.async_step_lernen_test()
        return self.async_show_form(step_id="lernen", errors=fehler, data_schema=vol.Schema({
            vol.Required("aktion", default="lernen"): _wahl([("lernen", "Jetzt anlernen (danach innerhalb von 30 Sekunden die Taste drücken)"),
                                                             ("ueberspringen", "Diesen Befehl überspringen"),
                                                             ("beenden", "Anlernen beenden")])}),
            description_placeholders={"befehl": name, "bedeutung": text, "nr": str(self._li + 1), "anzahl": str(len(self._lern)),
                                      "sender": self.a["klima_sender"], "fehler": meldung})

    async def async_step_lernen_test(self, user_input=None):
        fehler, meldung = {}, ""
        name, text, art = self._lern[self._li]
        if user_input is not None:
            if user_input["aktion"] == "weiter":
                if self._test:  # erst gesendet, dann „Befehl ist richtig“ → gilt als vor Ort geprüft
                    if not hasattr(self, "_bestaetigt"):
                        self._bestaetigt = set()
                    self._bestaetigt.add(name)
                return await self._lern_weiter()
            if user_input["aktion"] == "wiederholen":
                return await self.async_step_lernen()
            try:
                if self.hass.states.get(self.a["klima_sender"]) is None or self.hass.states.get(self.a["klima_sender"]).state != "on":
                    raise RuntimeError("Der IR-Sender ist nicht eingeschaltet oder nicht erreichbar.")
                await self.hass.services.async_call("remote", "send_command", {
                    "entity_id": self.a["klima_sender"], "device": self.a["ir_geraet"], "command": [name]}, blocking=True)
                self._test = "Der Befehl wurde gesendet. Hat die Klimaanlage in diesem Raum richtig reagiert? Wenn nicht: „Erneut anlernen“."
            except Exception as ex:  # noqa: BLE001
                fehler["base"] = "senden_fehlgeschlagen"
                meldung = str(ex)
        return self.async_show_form(step_id="lernen_test", errors=fehler, data_schema=vol.Schema({
            vol.Required("aktion", default="testen" if not self._test else "weiter"): _wahl([
                ("testen", "Befehl jetzt über diesen IR-Sender testweise senden"), ("weiter", "Befehl ist richtig – weiter"),
                ("wiederholen", "Neu anlernen (ersetzt den gespeicherten Befehl dieses Namens)")])}),
            description_placeholders={"befehl": name, "bedeutung": text, "herkunft": "wurde soeben angelernt" if name in self._gelernt else "ist bereits im Sender gespeichert", "sender": self.a["klima_sender"], "raum": self.a["raum_name"],
                                      "status": self._test, "fehler": meldung})

    def _pv_ir_bestaetigt(self):
        """Wurden die Befehle, die das PV-Heizen sendet (Heizen in der eingestellten Heizstufe, Heizen aus), getestet und bestätigt?"""
        a = self.a
        if not a.get("pv"):
            return False
        stufe, lf = str(int(a.get("pv_heizstufe", 24))), a.get("luefter") or ""
        noetig = {(a.get(k) or "").replace("{stufe}", stufe).replace("{luefter}", lf) for k in ("befehl_heizen", "befehl_heizen_aus")} - {""}
        return bool(noetig) and noetig <= getattr(self, "_bestaetigt", set())

    async def _ir_freigabe_setzen(self, entitaeten):
        """Setzt die IR-Prüffreigabe des PV-Heizens, wenn die PV-Befehle in diesem Ablauf getestet und bestätigt wurden. → True, wenn gesetzt."""
        eid = (entitaeten or {}).get("f_ir_geprueft")
        if not eid or not self._pv_ir_bestaetigt():
            return False
        try:
            await self.hass.services.async_call("input_boolean", "turn_on", {"entity_id": eid}, blocking=True)
        except Exception:  # noqa: BLE001 – dann bleibt sie aus; die Karte zeigt den Hinweis
            _LOGGER.exception("IR-Prüffreigabe %s nicht gesetzt", eid)
            return False
        return True

    async def _lern_weiter(self):
        self._li += 1
        if self._li < len(self._lern):
            return await self._lern_start()
        return await self._nach_lernen()

    # ------------------------------------------------------------------ Dashboard-Karte platzieren (ein oder mehrere Dashboards)
    @mit_zurueck
    async def async_step_dashboard(self, user_input=None):
        fehler = {}
        boards = await mit_verbindung(self.hass, lambda ha: ha.befehl("lovelace/dashboards/list"))
        namen = {"__standard__": "Übersicht (Standard-Dashboard)"} | {x["url_path"]: x.get("title") or x["url_path"] for x in boards if x.get("mode") == "storage"}
        if user_input is not None:
            if not user_input.get("dashboards"):
                fehler["base"] = "kein_dashboard"
            else:
                self._dbs = [(d, namen.get(d, d)) for d in namen if d in user_input["dashboards"]]
                self._db_auswahl = list(user_input["dashboards"])
                self.ziele = []
                # Anzeigenamen für die Übersicht: Entitäten und Raumkarten dieser Integration
                self._namen = {z.entity_id: z.name for z in self.hass.states.async_all() if z.name}
                self._namen.update({((e.data.get("rueckbau") or {}).get("entitaeten") or {}).get("status"): e.title
                                    for e in self.hass.config_entries.async_entries(DOMAIN)
                                    if ((e.data.get("rueckbau") or {}).get("entitaeten") or {}).get("status")})
                return await self._naechstes_dashboard()
        return self.async_show_form(step_id="dashboard", errors=fehler, data_schema=vol.Schema({
            vol.Required("dashboards", default=[d for d in getattr(self, "_db_auswahl", []) if d in namen]): _wahl(list(namen.items()), mehrfach=True)}))

    async def _naechstes_dashboard(self):
        if not self._dbs:
            return await self._nach_platz()
        kennung, self._dbname = self._dbs.pop(0)
        self._db = None if kennung == "__standard__" else kennung
        self._cfg = await mit_verbindung(self.hass, lambda ha: ha.befehl("lovelace/config", url_path=self._db))
        return await self.async_step_ansicht()

    def _ansichtsname(self, i):
        v = self._cfg["views"][i]
        return v.get("title") or v.get("path") or f"Ansicht {i + 1}"

    @mit_zurueck
    async def async_step_ansicht(self, user_input=None):
        views = self._cfg.get("views", [])
        namen = getattr(self, "_namen", {})
        if user_input is not None:
            self._vi = int(user_input["ansicht"])
            self._plaetze, self._empf = ra.plaetze_ordnen(views[self._vi], ra.dashboard_plaetze(views[self._vi], namen))
            return await self.async_step_platz()
        if not views:
            return await self._naechstes_dashboard()
        zahlen = []
        for v in views:
            pl = ra.dashboard_plaetze(json.loads(json.dumps(v)))
            zahlen.append((sum(n for pf, _, n in pl if pf[:2] != ["sections", "neu"]), sum(ra.raumkarten_anzahl(v, pf) for pf, _, _ in pl)))
        beste = max(range(len(views)), key=lambda i: (zahlen[i][1], -i))

        def text(i):
            karten, raum = zahlen[i]
            return (f"★ {self._ansichtsname(i)} ({karten} Karten, davon {raum} Raumkarten)" if raum
                    else f"{self._ansichtsname(i)} ({karten} Karten)")

        return self.async_show_form(step_id="ansicht", data_schema=vol.Schema({vol.Required("ansicht", default=str(beste if zahlen[beste][1] else 0)): _wahl(
            [(i, text(i)) for i in range(len(views))])}), description_placeholders={"dashboard": self._dbname})

    @mit_zurueck
    async def async_step_platz(self, user_input=None):
        view = self._cfg["views"][self._vi]
        if user_input is not None:
            self._pi2 = int(user_input["platz"])
            return await self.async_step_position()
        namen, empf = getattr(self, "_namen", {}), getattr(self, "_empf", set())
        return self.async_show_form(step_id="platz", data_schema=vol.Schema({vol.Required("platz", default="0"): _wahl(
            [(i, ra.platz_beschriftung(view, pfad, titel, namen, i in empf)) for i, (pfad, titel, _) in enumerate(self._plaetze)])}),
            description_placeholders={"dashboard": self._dbname, "ansicht": self._ansichtsname(self._vi),
                                      "uebersicht": ra.ansicht_uebersicht(view, self._plaetze, namen, empf)})

    @mit_zurueck
    async def async_step_position(self, user_input=None):
        view = self._cfg["views"][self._vi]
        pfad, titel, _ = self._plaetze[self._pi2]
        optionen, bild = ra.positionen(view, pfad, getattr(self, "_namen", {}))
        erkannt = ra.design_erkennen(view, pfad)
        if user_input is not None:
            self.ziele.append({"url_path": self._db, "view": self._vi, "pfad": pfad, "pos": int(user_input["position"]), "pos_gewaehlt": True,
                               "section": None, "design": user_input["design"], "name": f"{self._dbname} › {self._ansichtsname(self._vi)}"})
            return await self._naechstes_dashboard()
        return self.async_show_form(step_id="position", data_schema=vol.Schema({
            vol.Required("position", default=str(optionen[-1][0])): _wahl(optionen),
            vol.Required("design", default=erkannt): _wahl(list(ra.DESIGNS.items()))}),
            description_placeholders={"dashboard": self._dbname, "ansicht": self._ansichtsname(self._vi),
                                      "platz": "Neuer Abschnitt" if pfad[:2] == ["sections", "neu"] else titel, "bild": bild,
                                      "erkannt": ra.DESIGNS[erkannt]})


class Raumschritte(Schritte):
    """Schritte, die Ersteinrichtung und „Funktionen ändern“ gemeinsam nutzen. Jeder Schritt zeigt die bisherigen Eingaben als Vorgabe.

    self._modus: "neu" (Ersteinrichtung, endet mit der Zusammenfassung) oder "anpassen" (Konfigurieren → Funktionen ändern)."""

    _modus = "neu"

    async def _weiter(self):
        return await getattr(self, f"async_step_{self._ablauf.pop(0)}")()

    def _alle_profile(self):
        a = self.a
        return list(a.get("aktive_profile") or []) + (["sommer"] if a.get("sommer_heizen") else [])

    # ------------------------------------------------------------------ 2. Funktionen
    @mit_zurueck
    async def async_step_funktionen(self, user_input=None):
        fehler = {}
        a = self.a
        anpassen = self._modus == "anpassen"
        if user_input is not None:
            if not user_input["profile"]:
                fehler["base"] = "kein_profil"
            elif user_input["pv"] and not user_input["klima"]:
                fehler["base"] = "pv_braucht_klima"
            elif user_input["pv"] and user_input.get("klima_art", "ir") != "ir":
                fehler["base"] = "pv_braucht_ir"
            else:
                vorher = dict(a)
                a.update(aktive_profile=[p for p in ("komfort", "uebergang", "urlaub") if p in user_input["profile"]],
                         sommer_heizen=user_input["sommer_heizen"], zeitquelle=user_input.get("zeitquelle", a.get("zeitquelle", "phasen")),
                         fenster_modus=user_input["fenster_modus"], boost=user_input["boost"], vorheizen=user_input["vorheizen"],
                         mindest=user_input["mindest"], zieltermin=user_input["zieltermin"], klima=user_input["klima"], pv=user_input["pv"],
                         klima_art=user_input.get("klima_art", a.get("klima_art", "ir")))
                if a["fenster_modus"] != vorher.get("fenster_modus"):
                    a.update(fensterkontakte=[], fensterstatus_extern="", fenster_reaktion="blueprint")
                for k, v in (("fensterkontakte", []), ("fensterstatus_extern", ""), ("fenster_reaktion", "blueprint"), ("boost_dauer", 120),
                             ("waermeerzeuger", ""), ("vorheizen_max", 180), ("frostschutz", 5), ("aussensperre", 20)):
                    a.setdefault(k, v)
                a.setdefault("profile", {})
                for p, (soll, absenk) in STANDARD.items():
                    a["profile"].setdefault(p, {"soll": soll, "absenk": absenk, "phasen": []})
                a["termine"] = [t for t in a.get("termine", []) if (t["art"] == "m" and a["mindest"]) or (t["art"] == "z" and a["zieltermin"])]
                if not anpassen:
                    self._karte = user_input["karte"]
                    if not self._karte:
                        self.ziele = []
                vorlauf_alt = vorher.get("vorheizen") or vorher.get("mindest") or vorher.get("zieltermin")
                vorlauf_neu = a["vorheizen"] or a["mindest"] or a["zieltermin"]
                # nur die Schritte, deren Angaben noch fehlen (bei der Ersteinrichtung alle)
                voll = not anpassen and not getattr(self, "_nur_neues", False)  # Ersteinrichtung oder „Zurück“: alle Seiten (vorausgefüllt)
                self._nur_neues = False
                self._profile = [p for p in self._alle_profile() if voll or not a["profile"][p].get("erfasst")]
                self._pi = 0
                fenster = []
                if a["fenster_modus"] == "eigen" and (voll or a["fenster_modus"] != vorher.get("fenster_modus") or not a["fensterkontakte"]):
                    fenster = ["fenster"]
                elif a["fenster_modus"] == "extern" and (voll or a["fenster_modus"] != vorher.get("fenster_modus") or not a["fensterstatus_extern"]):
                    fenster = ["fenster_extern"]
                werte = voll or not a.get("werte_erfasst") or (a["boost"] and not vorher.get("boost")) or (vorlauf_neu and not vorlauf_alt)
                termin = any(schalter and not any(t["art"] == art for t in a["termine"]) for art, schalter in (("m", a["mindest"]), ("z", a["zieltermin"])))
                self._ablauf = ((["profil"] if self._profile else []) + fenster + (["werte"] if werte else []) + (["termin"] if termin else [])
                                + (["klima_sender"] if a["klima"] and a["klima_art"] == "ir" and (voll or not a.get("klima_sender")) else [])
                                + (["klima_schalter"] if a["klima"] and a["klima_art"] == "schalter" and (voll or not a.get("klima_schalter")) else [])
                                + (["pv"] if a["pv"] and (voll or not a.get("pv_trvs")) else []))
                if anpassen:
                    self._ablauf.append("aendern_bestaetigen")
                else:
                    if voll or not a.get("alt_geprueft") or (a["klima"] and (not vorher.get("klima") or a["klima_art"] != vorher.get("klima_art", "ir"))):
                        self._ablauf.append("altsteuerung")
                    if self._karte and (voll or not self.ziele):
                        self._ablauf.append("dashboard")
                    if voll or not a.get("alte_karten_geprueft"):
                        self._ablauf.append("alte_karten")
                    self._ablauf.append("bestaetigen")
                return await self._weiter()
        felder = {
            vol.Required("profile", default=a.get("aktive_profile") or ["komfort", "uebergang", "urlaub"]): _wahl(
                [("komfort", "Komfort"), ("uebergang", "Übergang"), ("urlaub", "Urlaub")], mehrfach=True),
            vol.Required("sommer_heizen", default=a.get("sommer_heizen", False)): _JA}
        if not anpassen:  # die Zeitquelle lässt sich nachträglich nicht umstellen (Zeiten stehen dann in der Blueprint bzw. im Zeitplan)
            felder[vol.Required("zeitquelle", default=a.get("zeitquelle", "phasen"))] = _wahl([
                ("phasen", "Drei Tagesprogramme je Profil: Montag bis Freitag, Samstag, Sonntag – je bis zu drei Heizphasen"),
                ("zeitplan", "Grafischer Wochenzeitplan je Profil (Zeitplan-Helfer; jeder Wochentag einzeln, vorbelegt aus den Tagesprogrammen)")])
        felder.update({
            vol.Required("fenster_modus", default=a.get("fenster_modus", "eigen")): _wahl([
                ("eigen", "Fensterkontakte dieses Raums mit 10-Minuten-Fail-safe"),
                ("extern", "Vorhandenen Fensterstatus-Helfer eines anderen Raums mitverwenden"), ("ohne", "Keine Fensterüberwachung")]),
            vol.Required("boost", default=a.get("boost", False)): _JA,
            vol.Required("vorheizen", default=a.get("vorheizen", False)): _JA,
            vol.Required("mindest", default=a.get("mindest", False)): _JA,
            vol.Required("zieltermin", default=a.get("zieltermin", False)): _JA,
            vol.Required("klima", default=a.get("klima", False)): _JA,
            vol.Required("klima_art", default=a.get("klima_art", "ir")): _wahl([
                ("ir", "Klimaanlage über IR-Sender (z. B. Broadlink): Stufen, Manuell, PV-Heizen möglich"),
                ("schalter", "Klimaanlage an einer Schaltsteckdose: nur ein/aus (z. B. mobiles Klimagerät)")]),
            vol.Required("pv", default=a.get("pv", False)): _JA})
        if not anpassen:
            felder[vol.Required("karte", default=getattr(self, "_karte", True))] = _JA
        return self.async_show_form(step_id="funktionen", errors=fehler, data_schema=vol.Schema(felder),
                                    description_placeholders={"raum": self.a["raum_name"]})

    # ------------------------------------------------------------------ 3. Profile
    @mit_zurueck
    async def async_step_profil(self, user_input=None):
        fehler = {}
        key = self._profile[self._pi]
        a = self.a
        bisher = a["profile"].get(key) or {}
        erfasst = bool(bisher.get("erfasst"))
        soll, absenk = (bisher["soll"], bisher["absenk"]) if erfasst else STANDARD[key]

        def vorgabe(tag, i):
            std = ra.STANDARD_PHASEN[key][tag]
            von, bis = std[i - 1] if i <= len(std) else ("06:00", "08:00")
            if erfasst:
                ph = next((x for x in bisher.get("phasen", []) if x["gruppe"] == tag and x["nr"] == i), None)
                return (True, ph["von"], ph["bis"]) if ph else (False, von + ":00", bis + ":00")
            return i <= len(std), von + ":00", bis + ":00"

        if user_input is not None:
            phasen = []
            for tag, _, tage in TAGESPROGRAMME:
                teil = user_input.get(BEREICH[tag])
                for i in (1, 2, 3):
                    an, von, bis = vorgabe(tag, i) if teil is None else (teil.get(f"heizphase_{i}_verwenden", False), teil.get(f"heizphase_{i}_beginn", "06:00:00"),
                                                                         teil.get(f"heizphase_{i}_ende", "08:00:00"))
                    if not an:
                        continue
                    if von[:5] == bis[:5]:
                        fehler["base"] = "zeit_gleich"
                    ph = {"gruppe": tag, "nr": i, "tage": list(tage), "von": von, "bis": bis, "vh": False}
                    if a["vorheizen"] and user_input.get("vh") and a["zeitquelle"] == "phasen":
                        ph.update(vh=True, vh_temp=user_input["vh_temp"], vh_bis=von)
                    phasen.append(ph)
            if user_input["absenk"] > user_input["soll"]:
                fehler["base"] = "absenk_hoeher"
            if not fehler:
                a["profile"][key] = {"soll": user_input["soll"], "absenk": user_input["absenk"], "phasen": phasen, "erfasst": True,
                                     "zp_vh": bool(a["vorheizen"] and user_input.get("vh")), "zp_vh_temp": user_input.get("vh_temp", soll - 1)}
                self._pi += 1
                if self._pi < len(self._profile):
                    return await self.async_step_profil()
                return await self._weiter()
        felder = {vol.Required("soll", default=soll): _zahl(5, 28, 0.5, "°C"), vol.Required("absenk", default=absenk): _zahl(5, 25, 0.5, "°C")}
        for tag, _, _ in TAGESPROGRAMME:
            teil = {}
            for i in (1, 2, 3):
                an, von, bis = vorgabe(tag, i)
                teil[vol.Required(f"heizphase_{i}_verwenden", default=an)] = _JA
                teil[vol.Required(f"heizphase_{i}_beginn", default=von)] = _ZEIT
                teil[vol.Required(f"heizphase_{i}_ende", default=bis)] = _ZEIT
            # Komfort und Übergang: Tagesbereiche aufgeklappt; Urlaub und Sommer: eingeklappt (vorbelegt)
            felder[vol.Required(BEREICH[tag])] = section(vol.Schema(teil), {"collapsed": key in ("urlaub", "sommer")})
        if a["vorheizen"]:
            felder[vol.Required("vh", default=bool(bisher.get("zp_vh")) if erfasst else False)] = _JA
            felder[vol.Required("vh_temp", default=bisher.get("zp_vh_temp", max(soll - 1, 5)) if erfasst else max(soll - 1, 5))] = _zahl(5, 28, 0.5, "°C")
        return self.async_show_form(step_id="profil", errors=fehler, data_schema=vol.Schema(felder), description_placeholders={
            "profil": ra.PROFILNAMEN[key], "nr": str(self._pi + 1), "anzahl": str(len(self._profile)),
            "art": ("Die Tagesprogramme werden in die Blueprint eingetragen und sind dort jederzeit änderbar (Abschnitte „"
                    + ra.PROFILNAMEN[key] + " – Montag bis Freitag“, „… – Samstag“, „… – Sonntag“)." if a["zeitquelle"] == "phasen"
                    else "Aus den Tagesprogrammen wird ein Zeitplan-Helfer angelegt, den Sie danach grafisch ändern können (Einstellungen → Geräte & Dienste → Helfer).")})

    # ------------------------------------------------------------------ 4. Fenster
    async def _fenster_vorbereiten(self):
        """Wie regelt der Raum die Fenster heute? Better Thermostat mit Fenstersensor → so bleibt es (Fensterstatus-Helfer des Raums);
        Kontakte und Klima/PV-Ausnahmen werden aus dem alten Fail-safe und der alten Klimaautomatik vorausgefüllt."""
        a = self.a
        if a.get("fenster_geprueft"):
            return
        a["fenster_geprueft"] = True
        alt = bt_fenster_lesen(self.hass, a["bt"])
        if not (isinstance(alt, str) and alt.startswith("input_boolean.")):
            return
        geteilt = any(e.options.get("window_sensors", e.data.get("window_sensors")) == alt for e in self.hass.config_entries.async_entries("better_thermostat")
                      if e.entry_id != getattr(bt_eintrag(self.hass, a["bt"]), "entry_id", None))
        a["fenster_alt"] = {"helfer": alt, "geteilt": geteilt}
        if a.get("fensterkontakte"):
            return
        try:
            v = await mit_verbindung(self.hass, lambda ha: al.fenster_vorlage(al.sammeln(ha), alt))
        except Exception:  # noqa: BLE001 – ohne Vorbelegung weiter
            return
        a["fensterkontakte"], a["fenster_ausnahmen"] = v["kontakte"], v["ausnahmen"]

    @mit_zurueck
    async def async_step_fenster(self, user_input=None):
        a = self.a
        if user_input is not None and user_input.get("fensterkontakte"):
            a.update(fensterkontakte=user_input["fensterkontakte"],
                     fenster_ausnahmen=[x for x in (user_input.get("fenster_ausnahmen") or []) if x in user_input["fensterkontakte"]],
                     fenster_reaktion="bt" if bt_eintrag(self.hass, a["bt"]) else "blueprint")
            return await self._weiter()
        await self._fenster_vorbereiten()
        kontakte = {"default": a["fensterkontakte"]} if a.get("fensterkontakte") else {}
        felder = {vol.Optional("fensterkontakte", **kontakte): _ent("binary_sensor", FENSTERKLASSEN, mehrfach=True)}
        if a.get("klima") or a.get("pv"):
            felder[vol.Optional("fenster_ausnahmen", default=a.get("fenster_ausnahmen") or [])] = _ent("binary_sensor", mehrfach=True)
        herkunft = ("Vorausgefüllt aus der bisherigen Steuerung (" + (a.get("fenster_alt") or {}).get("helfer", "") + ")."
                    if (a.get("fenster_alt") or {}).get("helfer") and a.get("fensterkontakte") else "")
        return self.async_show_form(step_id="fenster", errors={"base": "pflichtfeld"} if user_input is not None else {}, data_schema=vol.Schema(felder),
                                    description_placeholders={"herkunft": herkunft,
                                                              "reaktion": ("Better Thermostat pausiert sich selbst – der Fensterstatus dieses Raums wird dort "
                                                                           "automatisch als Fenstersensor eingetragen." if bt_eintrag(self.hass, a["bt"])
                                                                           else "Diese Automation pausiert das Thermostat.")})

    @mit_zurueck
    async def async_step_fenster_extern(self, user_input=None):
        a = self.a
        if user_input is not None and user_input.get("fensterstatus_extern"):
            a.update(fensterstatus_extern=user_input["fensterstatus_extern"], fenster_reaktion="bt" if bt_eintrag(self.hass, a["bt"]) else "blueprint")
            return await self._weiter()
        await self._fenster_vorbereiten()
        status = {"default": a["fensterstatus_extern"]} if a.get("fensterstatus_extern") else {}
        return self.async_show_form(step_id="fenster_extern", errors={"base": "pflichtfeld"} if user_input is not None else {}, data_schema=vol.Schema({
            vol.Optional("fensterstatus_extern", **status): _ent("input_boolean")}))

    # ------------------------------------------------------------------ 5. Werte
    @mit_zurueck
    async def async_step_werte(self, user_input=None):
        a = self.a
        vorlauf = a["vorheizen"] or a["mindest"] or a["zieltermin"]
        if user_input is not None:
            a.update({k: v for k, v in user_input.items() if k != "waermeerzeuger"})
            a["waermeerzeuger"] = user_input.get("waermeerzeuger") or ""
            a["werte_erfasst"] = True
            return await self._weiter()
        felder = {vol.Required("frostschutz", default=a.get("frostschutz", 5)): _zahl(5, 12, 0.5, "°C"),
                  vol.Required("aussensperre", default=a.get("aussensperre", 20)): _zahl(0, 30, 0.5, "°C")}
        if a["boost"]:
            felder[vol.Required("boost_dauer", default=a.get("boost_dauer", 120))] = _zahl(10, 720, 5, "min")
        if vorlauf:
            felder[vol.Required("vorheizen_max", default=a.get("vorheizen_max", 180))] = _zahl(15, 720, 5, "min")
            felder[vol.Optional("waermeerzeuger", description={"suggested_value": a.get("waermeerzeuger") or None})] = _ent(["sensor", "binary_sensor", "select"])
        if a["mindest"]:
            felder[vol.Required("mindest_halten", default=a.get("mindest_halten", 120))] = _zahl(0, 480, 5, "min")
        if a["zieltermin"]:
            felder[vol.Required("zieltermin_halten", default=a.get("zieltermin_halten", 60))] = _zahl(0, 480, 5, "min")
        return self.async_show_form(step_id="werte", data_schema=vol.Schema(felder))

    # ------------------------------------------------------------------ 6. Mindest- und Zieltemperatur-Termine
    @mit_zurueck
    async def async_step_termin(self, user_input=None):
        fehler = {}
        a = self.a
        profile = self._alle_profile()
        arten = ([("m", "Mindesttemperatur (mindestens … °C)")] if a["mindest"] else []) + ([("z", "Zieltemperatur (spätestens … °C)")] if a["zieltermin"] else [])
        if user_input is not None:
            anzahl = sum(1 for t in a["termine"] if t["profil"] == user_input["profil"] and t["art"] == user_input["art"])
            if not user_input["tage"]:
                fehler["base"] = "kein_tag"
            elif anzahl >= (2 if user_input["profil"] == "sommer" else 4):
                fehler["base"] = "zu_viele"
            else:
                a["termine"].append({"art": user_input["art"], "profil": user_input["profil"], "tage": [t for t, _ in TAGE if t in user_input["tage"]],
                                     "zeit": user_input["zeit"], "temp": user_input["temp"]})
                if not user_input["weiterer"]:
                    return await self._weiter()
        liste = "\n".join(f"- {'Mindestens' if t['art'] == 'm' else 'Spätestens'} {t['temp']} °C um {t['zeit'][:5]} Uhr, "
                          f"{', '.join(t['tage'])} (Profil {ra.PROFILNAMEN[t['profil']]})" for t in a["termine"]) or "- noch keiner"
        return self.async_show_form(step_id="termin", errors=fehler, data_schema=vol.Schema({
            vol.Required("art", default=arten[0][0]): _wahl(arten),
            vol.Required("profil", default=profile[0]): _wahl([(p, ra.PROFILNAMEN[p]) for p in profile]),
            vol.Required("tage", default=ALLE): _wahl(TAGE, mehrfach=True),
            vol.Required("zeit", default="06:00:00"): _ZEIT,
            vol.Required("temp", default=21): _zahl(5, 28, 0.5, "°C"),
            vol.Required("weiterer", default=False): _JA}), description_placeholders={"liste": liste})

    # ------------------------------------------------------------------ 7. Klimaanlage (IR-Sender je Raum)
    IR_SCHLUESSEL = ("ir_geraet", "befehl_kuehlen", "befehl_zusatz", "befehl_aus", "stufe_min", "stufe_max", "luefter",
                     "befehl_heizen", "befehl_heizen_aus", "pv_heizstufe", "heiz_stufe_min", "heiz_stufe_max")

    async def _altdaten(self):
        """Konfiguration aller UI-Skripte und -Automationen (nur lesend, einmal je Ablauf). None = nicht lesbar."""
        if not hasattr(self, "_altdaten_cache"):
            try:
                self._altdaten_cache = await mit_verbindung(self.hass, al.sammeln)
            except Exception as ex:  # noqa: BLE001 – dann nur die im Sender gespeicherten Befehle verwenden
                _LOGGER.warning("Alte Steuerung für die IR-Erkennung nicht lesbar: %s", ex)
                self._altdaten_cache = None
        return self._altdaten_cache

    async def _uebernahme_holen(self):
        """Geräte für das PV-Heizen aus der alten Steuerung dieses Raums (nur Entitäten); je Raum und Thermostat einmal."""
        a = self.a
        merkmal = (a.get("key"), a.get("bt"))
        cache = getattr(self, "_uebernahme", None)
        if cache is not None and cache.get("merkmal") == merkmal:
            return cache
        daten = await self._altdaten()
        try:
            v = {"pv": au.pv_geraete(daten.get("autos") or {}, daten.get("zustaende") or {}, a["key"], a.get("bt"), a.get("aussen"))} if daten else {}
        except Exception:  # noqa: BLE001 – ohne Vorschlag geht die Einrichtung mit Standardwerten weiter
            _LOGGER.exception("Übernahme aus der alten Steuerung fehlgeschlagen")
            v = {}
        v = dict(v, merkmal=merkmal)
        self._uebernahme = v
        return v

    async def _ir_erkennen(self, sender):
        """Vorschlag für die IR-Befehle dieses Senders: aus der alten Steuerung, sonst aus den im Sender gespeicherten Befehlen."""
        cache = getattr(self, "_erkennung", None)
        if cache is not None and cache.get("sender") == sender:
            return cache
        daten = await self._altdaten()
        quellen = ie.quellen_aus(daten["skripte"], daten["autos"], sender) if daten else {}
        quellen = {k: v for k, v in quellen.items() if not k.startswith(f"automation.hz_")}  # eigene Automationen senden über Blueprint-Eingaben
        gelernt = await gespeicherte_befehle(self.hass, sender)
        erg = ie.erkennen(quellen, gelernt)
        erg.update(sender=sender, gelernt=gelernt)
        self._erkennung = erg
        return erg

    def _ir_vorgabe(self, k, standard):
        """Bisherige Eingabe dieses Raums, sonst erkannter Wert, sonst Standard."""
        if k in self.a and self.a[k] not in (None,):
            return self.a[k]
        return (getattr(self, "_erkennung", None) or {}).get(k, standard)

    def _ir_stand(self, liste):
        """(vorhanden, fehlend) der benötigten Befehle im Sender; None, None = nicht feststellbar."""
        gelernt = (getattr(self, "_erkennung", None) or {}).get("gelernt")
        if gelernt is None:
            return None, None
        im_sender = set(gelernt.get(self.a.get("ir_geraet") or "", set()))
        return [n for n, _ in liste if n in im_sender], [n for n, _ in liste if n not in im_sender]

    @mit_zurueck
    async def async_step_klima_sender(self, user_input=None):
        fehler, meldung = {}, ""
        a = self.a
        if user_input is not None:
            sender = user_input.get("klima_sender") or ""
            zustand = self.hass.states.get(sender)
            if not sender:
                fehler["base"] = "pflichtfeld"
            elif zustand is None or zustand.state != "on":
                fehler["base"] = "sender_nicht_bereit"
                meldung = "nicht vorhanden" if zustand is None else zustand.state
            else:
                if a.get("klima_sender") and sender != a["klima_sender"]:  # anderer Sender: Befehle neu erkennen statt alte Angaben zu übernehmen
                    for k in self.IR_SCHLUESSEL:
                        a.pop(k, None)
                a["klima_sender"] = sender
                return await self.async_step_klima()
        vorschlag, grund = a.get("klima_sender") or "", ""
        if not vorschlag:
            daten = await self._altdaten()
            if daten:
                vorschlag = ie.sender_der_altsteuerung(daten["skripte"], daten["autos"], a["key"], a.get("raum_name", "")) or ""
                if vorschlag:
                    grund = f"Vorgeschlagen ist `{vorschlag}`, weil die bisherige Klimasteuerung dieses Raums über ihn sendet."
        return self.async_show_form(step_id="klima_sender", errors=fehler, data_schema=vol.Schema({
            vol.Optional("klima_sender", **({"default": vorschlag} if vorschlag else {})): _ent("remote")}),
            description_placeholders={"raum": a["raum_name"], "grund": grund, "fehler": meldung})

    @mit_zurueck
    async def async_step_klima(self, user_input=None):
        fehler = {}
        a = self.a
        e = await self._ir_erkennen(a["klima_sender"])
        if user_input is not None:
            if user_input["stufe_min"] > user_input["stufe_max"]:
                fehler["base"] = "stufen"
            else:
                steckdose = user_input.get("klima_steckdose") or ""
                a.update(ir_geraet=user_input["ir_geraet"].strip(), stufe_min=int(user_input["stufe_min"]), stufe_max=int(user_input["stufe_max"]),
                         befehl_kuehlen=user_input["befehl_kuehlen"].strip(), befehl_zusatz=", ".join(zusatzbefehle(user_input.get("befehl_zusatz"))),
                         befehl_aus=user_input["befehl_aus"].strip(), luefter=(user_input.get("luefter") or "").strip(),
                         klima_steckdose=steckdose,
                         klima_leistung=user_input.get("klima_leistung") or (leistung_zur_steckdose(self.hass, steckdose) if steckdose else ""),
                         laeuft_ab_w=float(user_input.get("laeuft_ab_w", 15)))
                kuehl = [(n, t) for n, t in befehlsliste(a) if n not in {x for x, _ in heizbefehle(a)}]
                _, fehlend = self._ir_stand(kuehl)
                if user_input.get("ir_pruefen") or fehlend:  # fehlende Befehle: direkt zum Anlernen (vorausgewählt), vorhandene bleiben unverändert
                    self._lern_nur = {n for n, _ in kuehl}
                    return await self.async_step_lernen_auswahl()
                return await self._weiter()
        vorschau = dict(a, ir_geraet=self._ir_vorgabe("ir_geraet", "klima"), befehl_kuehlen=self._ir_vorgabe("befehl_kuehlen", "power_{stufe}"),
                        befehl_zusatz=self._ir_vorgabe("befehl_zusatz", ""), befehl_aus=self._ir_vorgabe("befehl_aus", "power_off"),
                        stufe_min=self._ir_vorgabe("stufe_min", 16), stufe_max=self._ir_vorgabe("stufe_max", 23), pv=False)
        gelernt = e.get("gelernt")
        zeilen = list(e.get("hinweise") or [])
        if gelernt is None:
            zeilen.append("Die im Sender gespeicherten Befehle lassen sich nicht auslesen – bitte die Befehlsnamen prüfen.")
        else:
            im_sender = gelernt.get(vorschau["ir_geraet"], set())
            benoetigt = [n for n, _ in befehlsliste(vorschau)]
            fehlend = [n for n in benoetigt if n not in im_sender]
            zeilen.append(f"Im Sender unter „{vorschau['ir_geraet']}“ gespeichert: {len(im_sender)} Befehle. Benötigt für Kühlen und Aus: {len(benoetigt)} – "
                          + ("**alle vorhanden** ✓" if not fehlend else f"**es fehlen {len(fehlend)}:** {kurzliste(fehlend)} (werden im nächsten Schritt angelernt)"))
        if not e.get("herkunft"):
            zeilen.append("Keine bisherigen Befehle gefunden – Standardnamen vorgeschlagen.")
        felder = {
            vol.Required("ir_geraet", default=vorschau["ir_geraet"]): _TEXT,
            vol.Required("befehl_kuehlen", default=vorschau["befehl_kuehlen"]): _TEXT,
            vol.Optional("befehl_zusatz", default=vorschau["befehl_zusatz"]): _TEXT,
            vol.Required("befehl_aus", default=vorschau["befehl_aus"]): _TEXT,
            vol.Required("stufe_min", default=vorschau["stufe_min"]): _zahl(16, 30, 1, "°C"),
            vol.Required("stufe_max", default=vorschau["stufe_max"]): _zahl(16, 30, 1, "°C"),
            vol.Optional("luefter", default=a.get("luefter", "")): _TEXT,
            vol.Required("ir_pruefen", default=False): _JA,
            # optional: schaltbare Messsteckdose vor der Klimaanlage (bleibt dauerhaft an) und Leistungsmessung für die Rückmeldung
            vol.Optional("klima_steckdose", description={"suggested_value": a.get("klima_steckdose") or None}): _ent("switch"),
            vol.Optional("klima_leistung", description={"suggested_value": a.get("klima_leistung") or None}): _ent("sensor", "power"),
            vol.Required("laeuft_ab_w", default=a.get("laeuft_ab_w", 15)): _zahl(2, 500, 1, "W")}
        return self.async_show_form(step_id="klima", errors=fehler, data_schema=vol.Schema(felder),
                                    description_placeholders=dict(KLAMMERN, raum=a["raum_name"], sender=a["klima_sender"],
                                                                  erkennung="\n".join(f"- {z}" for z in zeilen)))

    async def _nach_lernen(self):
        return await self._weiter()

    @mit_zurueck
    async def async_step_klima_schalter(self, user_input=None):
        a = self.a
        if user_input is not None and user_input.get("klima_schalter"):
            a.update(klima_schalter=user_input["klima_schalter"], klima_ziel_start=user_input["klima_ziel_start"], ein_ueber=user_input["ein_ueber"],
                     aus_unter=user_input["aus_unter"], kuehl_profile=user_input.get("kuehl_profile") or ["Sommer", "Aus"],
                     anwesenheit=user_input.get("anwesenheit") or "", abwesend_aus=user_input.get("abwesend_aus", True))
            return await self._weiter()
        schalter = {"default": a["klima_schalter"]} if a.get("klima_schalter") else {}
        anwesend = {"description": {"suggested_value": a["anwesenheit"]}} if a.get("anwesenheit") else {}
        return self.async_show_form(step_id="klima_schalter", errors={"base": "pflichtfeld"} if user_input is not None else {}, data_schema=vol.Schema({
            vol.Optional("klima_schalter", **schalter): _ent(["switch", "input_boolean"]),
            vol.Required("klima_ziel_start", default=a.get("klima_ziel_start", 22)): _zahl(16, 28, 0.5, "°C"),
            vol.Required("ein_ueber", default=a.get("ein_ueber", 0.5)): _zahl(0, 3, 0.1, "K"),
            vol.Required("aus_unter", default=a.get("aus_unter", 0.0)): _zahl(0, 3, 0.1, "K"),
            vol.Required("kuehl_profile", default=a.get("kuehl_profile") or ["Sommer", "Aus"]): _wahl(
                [(p, p) for p in ("Komfort", "Übergang", "Urlaub", "Sommer", "Aus")], mehrfach=True),
            vol.Optional("anwesenheit", **anwesend): _ent(["person", "device_tracker", "binary_sensor", "input_boolean", "group"]),
            vol.Required("abwesend_aus", default=a.get("abwesend_aus", True)): _JA}),
            description_placeholders={"raum": a["raum_name"]})

    # ------------------------------------------------------------------ 8. PV-Überschussheizen
    @mit_zurueck
    async def async_step_pv(self, user_input=None):
        a = self.a
        fehler, meldung = {}, ""
        if user_input is not None:
            zustand = self.hass.states.get(user_input.get("pv_sender") or "")
            pflicht = ["pv_sender", "pv_trvs", "soc", "netz", "akku_leistung", "pv_leistung", "verbrauch"] + ([] if a["raumfuehler"] else ["pv_raumfuehler"])
            if any(not user_input.get(k) for k in pflicht):
                fehler["base"] = "pflichtfeld"
            elif user_input["heiz_stufe_min"] > user_input["heiz_stufe_max"]:
                fehler["base"] = "stufen"
            elif "{stufe}" in user_input["befehl_heizen"] and not user_input["heiz_stufe_min"] <= user_input["pv_heizstufe"] <= user_input["heiz_stufe_max"]:
                fehler["base"] = "heizstufe_bereich"
            elif zustand is None or zustand.state != "on":
                fehler["base"] = "sender_nicht_bereit"
                meldung = "nicht vorhanden" if zustand is None else zustand.state
        if user_input is not None and not fehler:
            # der Broadlink der Klimaanlage: gilt für Klimaautomatik und PV-Heizen gemeinsam (eine Zuordnung je Raum)
            a.update(klima_sender=user_input["pv_sender"], befehl_heizen=user_input["befehl_heizen"].strip(), befehl_heizen_aus=user_input["befehl_heizen_aus"].strip(),
                     heiz_stufe_min=int(user_input["heiz_stufe_min"]), heiz_stufe_max=int(user_input["heiz_stufe_max"]), pv_heizstufe=int(user_input["pv_heizstufe"]))
            a.update(pv_raumfuehler=a["raumfuehler"] or user_input.get("pv_raumfuehler"), pv_trvs=user_input["pv_trvs"],
                     pv_ventile=user_input.get("pv_ventile") or [],
                     zeitstempel_attribut=(user_input.get("zeitstempel_attribut") or "").strip(),
                     **{k: user_input[k] for k in ("soc", "netz", "akku_leistung", "pv_leistung", "verbrauch", "start_leistung", "soc_start", "soc_halten", "pv_ziel")})
            if user_input["heiz_anlernen"] == "einzeln":  # direkt prüfen, fehlende anlernen und testen – über genau diesen Broadlink
                self._lern_nur = {n for n, _ in heizbefehle(a)}
                return await self.async_step_lernen_auswahl()
            return await self._weiter()

        # Geräte (nur Entitäten): bisherige Eingabe, sonst aus der alten PV-Steuerung (Energiesensoren notfalls aus einem anderen Raum),
        # Heizkörperthermostate notfalls aus dem Better Thermostat des Raums
        ueb_pv = dict((await self._uebernahme_holen()).get("pv") or {})
        for anderer in [e.data.get("a") or {} for e in self.hass.config_entries.async_entries(DOMAIN)]:  # Energiesensoren gelten für das ganze Haus
            if anderer.get("pv") and anderer is not a:
                for k in au.ENERGIE + ("zeitstempel_attribut",):
                    if not ueb_pv.get(k) and anderer.get(k):
                        ueb_pv[k] = anderer[k]
                        ueb_pv.setdefault("quelle", {}).setdefault("energie_raum", anderer.get("raum_name", ""))
        bt_trvs = [e for e in bt_geraete(self.hass, a.get("bt")) if e.startswith("climate.")]
        # Ventilsensoren der vorgeschlagenen Heizkörperthermostate und Zeitstempel-Attribut des Ladestand-Sensors
        ventile_aus = []
        if not ueb_pv.get("pv_ventile"):
            v, ventile_aus = ventile_zu_trvs(self.hass, a.get("pv_trvs") or ueb_pv.get("pv_trvs") or bt_trvs)
            if v:
                ueb_pv["pv_ventile"] = v
        if not ueb_pv.get("zeitstempel_attribut"):
            zs = zeitstempel_attribut(self.hass, a.get("soc") or ueb_pv.get("soc"))
            if zs:
                ueb_pv["zeitstempel_attribut"] = zs

        def vg(k):
            if a.get(k):
                return {"default": a[k]}
            v = ueb_pv.get(k) or (bt_trvs if k == "pv_trvs" else None)
            return {"default": v} if v else {}

        def zv(k, standard):  # Zeitstempel-Attribut gehört zu den Energiesensoren
            return a.get(k, ueb_pv.get(k, standard))
        quelle = ueb_pv.get("quelle") or {}
        uebernahme = ""
        if any(k in ueb_pv for k in ("pv_trvs", "soc", "netz", "pv_raumfuehler")) or bt_trvs:  # Hinweis, woher die Vorbelegung stammt
            uebernahme = ("**Vorausgefüllt:** " + "; ".join(x for x in (
                f"Geräte aus {quelle['pv']}" if quelle.get("pv") else "",
                f"Energiesensoren aus {quelle['energie']}" if quelle.get("energie") else "",
                f"Energiesensoren wie im Raum „{quelle['energie_raum']}“" if quelle.get("energie_raum") and not quelle.get("energie") else "",
                "Heizkörperthermostate aus dem Better Thermostat" if not ueb_pv.get("pv_trvs") and bt_trvs else "") if x) + " – bitte nur prüfen.")
        if ventile_aus:
            uebernahme += ("\n\n⚠ Ventilöffnungs-Sensor vorhanden, aber in Home Assistant deaktiviert: " + ", ".join(f"`{x}`" for x in ventile_aus)
                           + ". Zum Verwenden erst aktivieren (Einstellungen → Geräte & Dienste → Entitäten), dann ist er hier auswählbar. Das Feld ist optional.")
        # Heizbefehle: bisherige Eingabe, sonst aus alter Steuerung / Sender erkannt (z. B. heizen_{stufe}, heizen_24_off), Stufen 22–28
        if a.get("klima_sender"):
            await self._ir_erkennen(a["klima_sender"])

        def iv(k, standard):
            return a.get(k) or (getattr(self, "_erkennung", None) or {}).get(k) or standard
        vorschau = dict(a, pv=True, befehl_heizen=iv("befehl_heizen", "heizen_{stufe}"), befehl_heizen_aus=iv("befehl_heizen_aus", "heizen_aus"),
                        heiz_stufe_min=iv("heiz_stufe_min", ie.HEIZ_STUFEN[0]), heiz_stufe_max=iv("heiz_stufe_max", ie.HEIZ_STUFEN[1]),
                        pv_heizstufe=iv("pv_heizstufe", 24), ir_geraet=a.get("ir_geraet") or "klima")
        vorhanden, fehlend = self._ir_stand(heizbefehle(vorschau)) if a.get("ir_geraet") else (None, None)
        if vorhanden is None:
            heiz_stand = ""
        else:
            heiz_stand = (f"**Im Sender unter „{vorschau['ir_geraet']}“:** vorhanden {kurzliste(vorhanden) or 'keiner'}"
                          + (f" · **fehlen noch:** {kurzliste(fehlend)} – sie werden im nächsten Schritt mit Ihnen angelernt (je Befehl einmal die "
                             "Fernbedienung auf den genannten Zustand stellen und drücken)." if fehlend else " · **alle Heizbefehle vorhanden** ✓"))
        felder = {
            vol.Optional("pv_sender", **vg("klima_sender")): _ent("remote"),
            vol.Required("befehl_heizen", default=vorschau["befehl_heizen"]): _TEXT,
            vol.Required("heiz_stufe_min", default=vorschau["heiz_stufe_min"]): _zahl(16, 30, 1, "°C"),
            vol.Required("heiz_stufe_max", default=vorschau["heiz_stufe_max"]): _zahl(16, 30, 1, "°C"),
            vol.Required("pv_heizstufe", default=vorschau["pv_heizstufe"]): _zahl(16, 30, 1, "°C"),
            vol.Required("befehl_heizen_aus", default=vorschau["befehl_heizen_aus"]): _TEXT,
            vol.Required("heiz_anlernen", default="einzeln" if fehlend or vorhanden is None else "vorhanden"): _wahl([
                ("einzeln", "Heizbefehle jetzt prüfen: fehlende anlernen, vorhandene testen (empfohlen)"),
                ("vorhanden", "Alle Heizbefehle sind bereits angelernt – nichts senden, nichts anlernen")])}
        if not a["raumfuehler"]:
            felder[vol.Optional("pv_raumfuehler", **vg("pv_raumfuehler"))] = _ent("sensor", "temperature")
        felder.update({
            vol.Optional("pv_trvs", **vg("pv_trvs")): _ent("climate", mehrfach=True),
            vol.Optional("pv_ventile", default=a.get("pv_ventile") or ueb_pv.get("pv_ventile") or []): _ent("sensor", mehrfach=True),
            vol.Optional("soc", **vg("soc")): _ent("sensor"), vol.Optional("netz", **vg("netz")): _ent("sensor"),
            vol.Optional("akku_leistung", **vg("akku_leistung")): _ent("sensor"),
            vol.Optional("pv_leistung", **vg("pv_leistung")): _ent("sensor"), vol.Optional("verbrauch", **vg("verbrauch")): _ent("sensor"),
            vol.Optional("zeitstempel_attribut", default=zv("zeitstempel_attribut", "")): _TEXT,
            vol.Required("start_leistung", default=a.get("start_leistung", 1000)): _zahl(500, 3000, 50, "W"),
            vol.Required("soc_start", default=a.get("soc_start", 95)): _zahl(50, 100, 1, "%"),
            vol.Required("soc_halten", default=a.get("soc_halten", 85)): _zahl(20, 100, 1, "%"),
            vol.Required("pv_ziel", default=a.get("pv_ziel", 24)): _zahl(18, 28, 0.5, "°C")})
        return self.async_show_form(step_id="pv", errors=fehler, data_schema=vol.Schema(felder),
                                    description_placeholders=dict(KLAMMERN, raum=a["raum_name"], geraet=a.get("ir_geraet", ""), fehler=meldung,
                                                                  heiz_stand=heiz_stand, uebernahme=uebernahme))

    async def _nach_platz(self):
        return await self._weiter()

    # ------------------------------------------------------------------ Alte Dashboard-Karten (beim Anlegen und unter Konfigurieren)
    def _status_aller_raeume(self):
        out = {}
        for e in self.hass.config_entries.async_entries(DOMAIN):
            st = ((e.data.get("rueckbau") or {}).get("entitaeten") or {}).get("status")
            if st and (e.data.get("a") or {}).get("key"):
                out[e.data["a"]["key"]] = {"status": st, "bt": e.data["a"].get("bt")}
        return out

    async def _alte_karten_kandidaten(self, alt, eigener_status):
        a = self.a
        namen = {z.entity_id: z.name for z in self.hass.states.async_all() if z.name}
        status = self._status_aller_raeume()
        if eigener_status:
            status[a["key"]] = {"status": eigener_status, "bt": a["bt"]}
        return await mit_verbindung(self.hass, lambda ha: ra.alte_karten_suchen(ha, a, alt, status, namen))

    @staticmethod
    def _karten_beschriftung(k):
        return f"{k['dashboard']} › {k['ort']} › „{k['name']}“"


class Einrichtung(Raumschritte, config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self.a = {"profile": {}, "termine": []}
        self.ziele = []
        self._ablauf = []

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return Anpassung()

    # ------------------------------------------------------------------ 1. Raum und Geräte
    @mit_zurueck
    async def async_step_user(self, user_input=None):
        fehler, belegt = {}, ""
        if user_input is not None:
            name = user_input["raum_name"].strip()
            key = ra.slug(name.replace("ü", "ue").replace("ö", "oe").replace("ä", "ae").replace("ß", "ss"))
            await self.async_set_unique_id(key)
            self._abort_if_unique_id_configured()
            andere = [e.title for e in self._async_current_entries() if (e.data.get("a") or {}).get("bt") == user_input["bt"]]
            if andere:
                fehler["base"] = "bt_belegt"
                belegt = ", ".join(andere)
        if user_input is not None and not fehler:
            bt_vorher = self.a.get("bt")
            self.a.update(raum_name=name, key=key, bt=user_input["bt"], raumfuehler=user_input.get("raumfuehler") or "",
                          aussen=user_input["aussen"], haus_aus=user_input.get("haus_aus") or "")
            if self._ablauf:  # Rücksprung aus der Zusammenfassung: anderes Thermostat → alte Steuerung neu suchen
                if bt_vorher != self.a["bt"] and "altsteuerung" not in self._ablauf:
                    self._ablauf.insert(0, "altsteuerung")
                return await self._weiter()
            return await self.async_step_funktionen()
        a = self.a

        def vg(k):
            return {"default": a[k]} if a.get(k) else {}

        def vorschlag(k):
            return {"description": {"suggested_value": a[k]}} if a.get(k) else {}
        return self.async_show_form(step_id="user", errors=fehler, description_placeholders={"belegt": belegt}, data_schema=vol.Schema({
            vol.Required("raum_name", **vg("raum_name")): _TEXT,
            vol.Required("bt", **vg("bt")): _ent("climate"),
            vol.Optional("raumfuehler", **vorschlag("raumfuehler")): _ent("sensor", "temperature"),
            vol.Required("aussen", **vg("aussen")): _ent("sensor", "temperature"),
            vol.Optional("haus_aus", **vorschlag("haus_aus")): _ent("input_boolean")}))

    # ------------------------------------------------------------------ 8b. Alte Steuerung dieses Raums
    @mit_zurueck
    async def async_step_altsteuerung(self, user_input=None):
        a = self.a
        if user_input is not None:
            e = self._alt
            a["alt"] = {"abschalten": [x for x in user_input.get("abschalten", []) if x in e["automationen"] + e["skripte"]],
                        "helfer": [x for x in user_input.get("helfer", []) if x in e["helfer"]],
                        "umstellen": bool(user_input.get("umstellen")), "abhaengig": list(e["abhaengig"])}
            a["alt_geprueft"] = True
            return await self._weiter()

        def suchen(ha):
            daten = al.sammeln(ha)
            e = al.einstufen(daten, *ra.alt_geraete(a))
            neue = ra.plane(a, ra.Bestand(list(daten["zustaende"].values()), daten["registry"]), None)["entitaeten"]
            e["karte"] = al.zuordnung(e["helfer"], daten["zustaende"], neue)
            return e

        try:
            e = await mit_verbindung(self.hass, suchen)
        except Exception as ex:  # noqa: BLE001
            _LOGGER.exception("Suche nach der alten Steuerung fehlgeschlagen")
            return self.async_abort(reason="vorschau_fehlgeschlagen", description_placeholders={"fehler": str(ex)})
        self._alt = e
        if not (e["automationen"] or e["skripte"] or e["helfer"]):
            a["alt"], a["alt_geprueft"] = None, True
            return await self._weiter()
        n = e["namen"]
        logik = e["automationen"] + e["skripte"]
        abh = []
        for i, hs in e["abhaengig"].items():
            teile = [f"`{h}` → `{e['karte'][h]}`" if h in e["karte"] else f"`{h}` (kein gleichwertiger neuer Helfer – bitte selbst anpassen)" for h in hs]
            abh.append(f"- **{n.get(i, i)}**: " + ", ".join(teile))
        warn = []
        if e["pv_laeuft"]:
            warn.append("⚠ Das alte PV-Heizen läuft gerade (" + ", ".join(e["pv_laeuft"]) + "). Der Raum kann erst angelegt werden, wenn es beendet ist.")
        if e["klima_an"]:
            warn.append("⚠ Die alte Klimasteuerung meldet die Klimaanlage als eingeschaltet. Nach dem Umstellen schaltet sie niemand mehr ab – "
                        "bitte vorher ausschalten.")
        return self.async_show_form(step_id="altsteuerung", data_schema=vol.Schema({
            vol.Optional("abschalten", default=[x for x in (a.get("alt") or {}).get("abschalten", logik) if x in logik]): _wahl([(i, n.get(i, i) + (" (Skript)" if i.startswith("script.") else "")) for i in logik], mehrfach=True),
            vol.Optional("helfer", default=[x for x in (a.get("alt") or {}).get("helfer", e["helfer"]) if x in e["helfer"]]): _wahl([(h, f"{n.get(h, h)} ({h})") for h in e["helfer"]], mehrfach=True),
            vol.Required("umstellen", default=(a.get("alt") or {}).get("umstellen", bool(abh))): _JA}), description_placeholders={
            "raum": a["raum_name"], "anz_auto": str(len(e["automationen"])), "anz_skript": str(len(e["skripte"])), "anz_helfer": str(len(e["helfer"])),
            "abhaengig": "\n".join(abh) or "- keine",
            "gemeinsam": "\n".join(f"- {n.get(i, i)}" for i in e["gemeinsam"]) or "- keine",
            "warnungen": "\n\n".join(warn)})

    # ------------------------------------------------------------------ 8c. Alte Dashboard-Karten dieses Raums
    @mit_zurueck
    async def async_step_alte_karten(self, user_input=None):
        a = self.a
        if user_input is not None:
            a["alte_karten"] = [k["id"] for k in self._karten if k["id"] in set(user_input.get("karten", []))]  # gleiche Reihenfolge wie die Namen
            a["alte_karten_namen"] = [self._karten_beschriftung(k) for k in self._karten if k["id"] in a["alte_karten"]]
            return await self._weiter()
        a["alte_karten_geprueft"] = True
        if not (a.get("alt") or {}).get("abschalten") and not (a.get("alt") or {}).get("helfer"):
            a["alte_karten"] = []
            return await self._weiter()
        try:
            self._karten = await self._alte_karten_kandidaten(a.get("alt"), None)
        except Exception as ex:  # noqa: BLE001
            return self.async_abort(reason="vorschau_fehlgeschlagen", description_placeholders={"fehler": str(ex)})
        if not self._karten:
            a["alte_karten"] = []
            return await self._weiter()
        return self.async_show_form(step_id="alte_karten", data_schema=vol.Schema({
            vol.Optional("karten", default=[x for x in a.get("alte_karten", []) if x in {k["id"] for k in self._karten}]): _wahl(
                [(k["id"], self._karten_beschriftung(k)) for k in self._karten], mehrfach=True)}),
            description_placeholders={"raum": a["raum_name"], "anzahl": str(len(self._karten))})

    # ------------------------------------------------------------------ 9. Zusammenfassung, „Etwas ändern“ und Anlegen
    def _sprungziele(self):
        a = self.a
        z = [("nichts", "Nichts ändern"), ("user", "Raumname und Geräte"), ("funktionen", "Funktionen (neu gewählte fragen danach nur ihre eigenen Angaben ab)"),
             ("profil", "Heizzeiten und Temperaturen aller Profile")]
        if a.get("fenster_modus") in ("eigen", "extern"):
            z.append(("fenster", "Fenster"))
        z.append(("werte", "Grundwerte (Frostschutz, Außensperre, Boost-Dauer …)"))
        if a.get("mindest") or a.get("zieltermin"):
            z.append(("termin", "Termine neu eintragen (die bisherigen werden verworfen)"))
        if a.get("klima"):
            z.append(("klima", "Klimaanlage (Steckdose, Schwellen, Anwesenheit)" if a.get("klima_art") == "schalter" else "Klimaanlage und IR-Befehle"))
        if a.get("pv"):
            z.append(("pv", "PV-Überschussheizen"))
        if a.get("alt_geprueft"):
            z.append(("altsteuerung", "Alte Steuerung"))
        if (a.get("alt") or {}).get("abschalten") or (a.get("alt") or {}).get("helfer"):
            z.append(("alte_karten", "Alte Dashboard-Karten, die entfernt werden sollen"))
        z.append(("dashboard", "Dashboard-Karte (Dashboards, Bereich, Position, Design)"))
        return z

    async def _springen(self, ziel):
        """Zurück zu einem Schritt; alle bisherigen Eingaben bleiben als Vorgabe erhalten. Danach wieder zur Zusammenfassung."""
        a = self.a
        if ziel == "funktionen":
            self._ablauf = ["funktionen"]  # der Schritt plant den weiteren Ablauf selbst
            self._nur_neues = True
        elif ziel == "profil":
            self._profile, self._pi = self._alle_profile(), 0
            self._ablauf = ["profil", "bestaetigen"]
        elif ziel == "fenster":
            self._ablauf = ["fenster" if a["fenster_modus"] == "eigen" else "fenster_extern", "bestaetigen"]
        elif ziel == "termin":
            a["termine"] = []
            self._ablauf = ["termin", "bestaetigen"]
        elif ziel == "dashboard":
            self._karte, self.ziele = True, []
            self._ablauf = ["dashboard", "bestaetigen"]
        elif ziel == "altsteuerung":
            self._ablauf = ["altsteuerung", "alte_karten", "bestaetigen"]
        elif ziel == "klima":
            self._ablauf = ["klima_schalter" if a.get("klima_art") == "schalter" else "klima_sender", "bestaetigen"]
        else:
            self._ablauf = [ziel, "bestaetigen"]
        return await self._weiter()


    @mit_zurueck
    async def async_step_bestaetigen(self, user_input=None):
        fehler, meldung = {}, ""
        a = self.a
        ordner = self.hass.config.path("heizung_universal", a["key"])
        if user_input is not None and user_input.get("aendern", "nichts") != "nichts":
            return await self._springen(user_input["aendern"])
        if user_input is not None:
            if not user_input["bestaetigt"]:
                fehler["base"] = "nicht_bestaetigt"
            else:
                try:
                    erg = await mit_verbindung(self.hass, lambda ha: ra.einrichten(ha, a, self.ziele, ordner))
                except ra.AltPVLaeuft as ex:  # erwartete Sperre, kein Fehler
                    _LOGGER.info("Raum %s nicht angelegt: %s", a["raum_name"], ex)
                    fehler["base"] = "alt_pv_laeuft"
                    meldung = str(ex)
                except Exception as ex:  # noqa: BLE001
                    _LOGGER.exception("Einrichtung des Raums %s fehlgeschlagen", a["raum_name"])
                    fehler["base"] = "anlegen_fehlgeschlagen"
                    meldung = str(ex)
                else:
                    bt_fenster = None
                    ziel = fenster_ziel(a, erg["rueckbau"].get("entitaeten"))
                    if a.get("fenster_reaktion") == "bt" and ziel:
                        try:
                            bt_fenster = {"bt": a["bt"], "alt": await bt_fenster_setzen(self.hass, a["bt"], ziel), "neu": ziel}
                        except Exception:  # noqa: BLE001
                            _LOGGER.exception("Fenstersensor von Better Thermostat für %s nicht umgestellt", a["raum_name"])
                    hinweise = erg.get("hinweise") or []
                    await self._ir_freigabe_setzen(erg["rueckbau"].get("entitaeten"))
                    return self.async_create_entry(title=a["raum_name"], data={
                        "a": a, "rueckbau": erg["rueckbau"], "betriebsart": erg["betriebsart"], "automationen": erg["automationen"], "ziele": self.ziele,
                        "alt_status": "neu_aktiv" if erg["rueckbau"].get("alt") else None, "bt_fenster": bt_fenster},
                        **({"description": "hinweis", "description_placeholders": {"raum": a["raum_name"], "hinweis": "\n\n".join(hinweise)}} if hinweise else {}))

        def vorschau(ha):
            b = ra.Bestand(ha.befehl("get_states"), ha.befehl("config/entity_registry/list"))
            return ra.plane(a, b, None), ra.bt_fremdnutzung(ha, a)

        try:
            plan, fremd = await mit_verbindung(self.hass, vorschau)
        except Exception as ex:  # noqa: BLE001
            return self.async_abort(reason="vorschau_fehlgeschlagen", description_placeholders={"fehler": str(ex)})
        hinweise = []
        if plan["konflikte"]:
            hinweise.append("⚠ Diese Helfer existieren bereits – bitte abbrechen und einen anderen Raumnamen wählen: " + ", ".join(plan["konflikte"]))
        if fremd:
            hinweise.append("⚠ Das Better Thermostat wird bereits von " + ", ".join(fremd) + " verwendet. Damit es keine zwei Sollwertschreiber gibt, "
                            "wird die neue Automation im TESTBETRIEB angelegt (rechnet, sendet nichts). Umschalten im Abschnitt „Erweitert“ der Blueprint, "
                            "sobald Sie die alte Automation selbst deaktiviert haben.")
        if a.get("fenster_reaktion") == "bt" and a["fenster_modus"] != "ohne":
            hinweise.append(f"**Fenster:** Der Fensterstatus dieses Raums wird in Better Thermostat ({a['bt']}) als Fenstersensor eingetragen "
                            f"(bisher: {bt_fenster_lesen(self.hass, a['bt']) or 'keiner'}); dessen Verzögerungen bleiben. Kontakte tauschen: nur in „Heizung {a['raum_name']}“.")
        if a.get("klima") and a.get("klima_art", "ir") == "ir" and (a.get("klima_steckdose") or a.get("klima_leistung")):
            hinweise.append("**Klima-Steckdose:** "
                            + (f"{a['klima_steckdose']} bleibt dauerhaft eingeschaltet; vor jedem IR-Befehl wird sie bei Bedarf eingeschaltet. "
                               if a.get("klima_steckdose") else "")
                            + (f"Rückmeldung über {a['klima_leistung']} (läuft ab {a.get('laeuft_ab_w', 15):g} W): Befehle ohne Wirkung werden einmal "
                               "wiederholt, danach gibt es eine Meldung." if a.get("klima_leistung") else "Ohne Leistungsmessung keine Rückmeldung."))
        alt = a.get("alt") or {}
        if alt.get("abschalten") or alt.get("helfer"):
            n_auto = sum(1 for x in alt.get("abschalten", []) if x.startswith("automation."))
            hinweise.append(f"**Alte Steuerung:** {n_auto} Automationen werden ausgeschaltet, {len(alt.get('abschalten', [])) - n_auto} Skripte deaktiviert, "
                            f"beide mit „(alt)“ gekennzeichnet; {len(alt.get('helfer', []))} Helfer erhalten „(alt)“ im Namen"
                            + ("; abhängige Automationen werden auf die neuen Helfer umgestellt" if alt.get("umstellen") else "")
                            + ". Rückgängig über „Konfigurieren → Alte Steuerung wieder einschalten“.")
        if a.get("alte_karten"):
            hinweise.append("**Alte Dashboard-Karten werden entfernt** (Dashboards vorher gesichert; „Alte Steuerung wieder einschalten“ setzt sie zurück):\n"
                            + "\n".join(f"- {n}" for n in a.get("alte_karten_namen", [])))
        return self.async_show_form(step_id="bestaetigen", errors=fehler, data_schema=vol.Schema({
            vol.Required("bestaetigt", default=False): _JA,
            vol.Required("aendern", default="nichts"): _wahl(self._sprungziele())}),
                                    description_placeholders={
                                        "raum": a["raum_name"], "fehler": meldung,
                                        "helfer": "\n".join(f"- {x['name']} (`{x['entity_id']}`)" for x in plan["helfer"]),
                                        "anzahl": str(len(plan["helfer"])),
                                        "automationen": "\n".join(f"- {x['alias']}" for x in plan["automationen"]),
                                        "karte": ("\n" + "\n".join(f"- {z['name']} – Design: {ra.DESIGNS[z['design']]}" for z in self.ziele)) if self.ziele else "wird nicht eingefügt",
                                        "hinweise": "\n\n".join(hinweise)})


class Anpassung(Raumschritte, config_entries.OptionsFlow):
    """Nachträglich: Funktionen ändern, IR-Befehle (neu) anlernen, Dashboard-Karte neu platzieren, alte Steuerung verwalten."""

    async def async_step_init(self, user_input=None):
        self.a = json.loads(json.dumps(self.config_entry.data["a"]))
        a = self.a
        a.setdefault("profile", {})
        for p in self._alle_profile():  # vorhandene Profile und Grundwerte gelten als erfasst – gefragt wird nur nach Neuem
            a["profile"].setdefault(p, {"soll": STANDARD[p][0], "absenk": STANDARD[p][1], "phasen": []})["erfasst"] = True
        a["werte_erfasst"] = True
        self._a_alt = json.loads(json.dumps(a))
        self._ablauf, self.ziele = [], []
        status = self.config_entry.data.get("alt_status")
        menue = (["funktionen", "geraet", "ir"] + (["steckdose"] if a.get("klima") and a.get("klima_art", "ir") == "ir" else [])
                 + ["karte", "alte_karten"])
        if (self.config_entry.data.get("rueckbau") or {}).get("alt"):
            menue += {"neu_aktiv": ["alt_zurueck", "alt_loeschen"], "alt_aktiv": ["alt_neu"]}.get(status, [])
        return self.async_show_menu(step_id="init", menu_options=menue)

    def _alt_daten(self):
        daten = dict(self.config_entry.data)
        return daten, dict(daten["rueckbau"]), daten["rueckbau"]["alt"]

    def _neue_automationen(self):
        return [x for x in (self.config_entry.data.get("automationen") or {}).values() if x]

    @staticmethod
    def _liste(p):
        teile = [f"- {x['alias']}" for x in p.get("automationen", [])] + [f"- {x['alias']} (Skript)" for x in p.get("skripte", [])]
        return "\n".join(teile) or "- keine"

    async def async_step_alt_zurueck(self, user_input=None):
        daten, r, p = self._alt_daten()
        neue = self._neue_automationen()
        if user_input is not None and user_input.get("bestaetigt"):
            def zurueck(ha):
                for eid in neue:  # neue Steuerung anhalten, damit nicht zwei Automationen dasselbe Thermostat stellen
                    ha.befehl("call_service", domain="automation", service="turn_off", service_data={}, target={"entity_id": eid})
                return al.wiederherstellen(ha, p) + ra.alte_karten_zurueck(ha, r.get("alte_karten") or [])
            try:
                fehler = await mit_verbindung(self.hass, zurueck)
            except Exception as ex:  # noqa: BLE001
                return self.async_abort(reason="vorschau_fehlgeschlagen", description_placeholders={"fehler": str(ex)})
            bf = daten.get("bt_fenster") or {}
            if bf.get("bt") and "alt" in bf:  # Better Thermostat wieder auf den alten Fenster-Helfer
                await bt_fenster_setzen(self.hass, bf["bt"], bf["alt"])
            daten["alt_status"] = "alt_aktiv"
            daten["rueckbau"] = dict(r, alte_karten=[])  # wieder eingesetzt – bei Bedarf über „Alte Dashboard-Karten entfernen“ erneut entfernen
            self.hass.config_entries.async_update_entry(self.config_entry, data=daten)
            return self.async_abort(reason="alt_zurueck_fertig", description_placeholders={"fehler": "\n".join(fehler) or "keine"})
        return self.async_show_form(step_id="alt_zurueck", data_schema=vol.Schema({vol.Required("bestaetigt", default=False): _JA}),
                                    description_placeholders={"liste": self._liste(p), "helfer": str(len(p.get("helfer", []))),
                                                              "abhaengig": str(len(p.get("abhaengig", []))), "neu": ", ".join(neue)})

    async def async_step_alt_neu(self, user_input=None):
        daten, r, p = self._alt_daten()
        neue = self._neue_automationen()
        if user_input is not None and user_input.get("bestaetigt"):
            logik = [x["entity_id"] for x in p.get("automationen", []) + p.get("skripte", [])]
            helfer = [x["entity_id"] for x in p.get("helfer", [])]
            abhaengig = [x["entity_id"] for x in p.get("abhaengig", [])]
            karte = p.get("karte") or {}

            def wieder_neu(ha):
                altdaten = al.sammeln(ha)
                p2 = al.abschalten(ha, altdaten, logik, helfer)
                p2["karte"] = karte
                p2["abhaengig"] = al.umstellen(ha, altdaten, abhaengig, karte)
                for eid in neue:
                    ha.befehl("call_service", domain="automation", service="turn_on", service_data={}, target={"entity_id": eid})
                return p2
            try:
                p2 = await mit_verbindung(self.hass, wieder_neu)
            except Exception as ex:  # noqa: BLE001
                return self.async_abort(reason="vorschau_fehlgeschlagen", description_placeholders={"fehler": str(ex)})
            r["alt"] = p2
            bf = daten.get("bt_fenster") or {}
            if bf.get("bt") and bf.get("neu"):
                await bt_fenster_setzen(self.hass, bf["bt"], bf["neu"])
            daten["rueckbau"], daten["alt_status"] = r, "neu_aktiv"
            self.hass.config_entries.async_update_entry(self.config_entry, data=daten)
            return self.async_abort(reason="alt_neu_fertig")
        return self.async_show_form(step_id="alt_neu", data_schema=vol.Schema({vol.Required("bestaetigt", default=False): _JA}),
                                    description_placeholders={"liste": self._liste(p), "neu": ", ".join(neue)})

    async def async_step_alt_loeschen(self, user_input=None):
        daten, r, p = self._alt_daten()
        helfer = [x["entity_id"] for x in p.get("helfer", [])]
        ordner = self.hass.config.path("heizung_universal", self.a["key"])
        if user_input is not None and user_input.get("bestaetigt"):
            auswahl = [h for h in user_input.get("helfer", []) if h in helfer]
            try:
                datei, fehler = await mit_verbindung(self.hass, lambda ha: al.loeschen(ha, p, ordner, auswahl))
            except Exception as ex:  # noqa: BLE001
                return self.async_abort(reason="vorschau_fehlgeschlagen", description_placeholders={"fehler": str(ex)})
            r["alt"] = dict(p, geloescht=datei)
            daten["rueckbau"], daten["alt_status"] = r, "geloescht"
            self.hass.config_entries.async_update_entry(self.config_entry, data=daten)
            return self.async_abort(reason="alt_geloescht", description_placeholders={"datei": datei, "fehler": "\n".join(fehler) or "keine"})
        alt_eids = {x["entity_id"] for x in p.get("automationen", []) + p.get("skripte", [])}

        def pruefen(ha):
            altdaten = al.sammeln(ha)
            for eid in alt_eids:
                altdaten["autos"].pop(eid, None)
                altdaten["skripte"].pop(eid, None)
            return al.noch_verwendet(altdaten, helfer)
        try:
            verwendet = await mit_verbindung(self.hass, pruefen)
        except Exception as ex:  # noqa: BLE001
            return self.async_abort(reason="vorschau_fehlgeschlagen", description_placeholders={"fehler": str(ex)})
        frei = [h for h in helfer if h not in verwendet]
        return self.async_show_form(step_id="alt_loeschen", data_schema=vol.Schema({
            vol.Optional("helfer", default=frei): _wahl([(h, h + (" – noch verwendet von: " + ", ".join(verwendet[h]) if h in verwendet else "")) for h in helfer], mehrfach=True),
            vol.Required("bestaetigt", default=False): _JA}),
            description_placeholders={"liste": self._liste(p), "verwendet": "\n".join(f"- `{h}`: {', '.join(v)}" for h, v in verwendet.items()) or "- keine"})

    async def async_step_ir(self, user_input=None):
        if not self.a.get("klima"):
            return self.async_abort(reason="keine_klima")
        key = self.a["key"]

        def lesen(ha):
            kl = ha.rest("GET", f"/api/config/automation/config/hz_{key}_klima")["use_blueprint"]["input"]
            pv = {}
            if self.a.get("pv"):  # aktuelle Heizstufe des PV-Heizens (in der Automation jederzeit änderbar)
                try:
                    pv = ha.rest("GET", f"/api/config/automation/config/hz_{key}_pv")["use_blueprint"]["input"]
                except Exception:  # noqa: BLE001
                    pv = {}
            return kl, pv

        try:  # aktuelle Zuordnung aus der Blueprint-Instanz lesen (dort wird ein neuer Broadlink gewählt)
            inp, pv_inp = await mit_verbindung(self.hass, lesen)
        except Exception as ex:  # noqa: BLE001
            return self.async_abort(reason="vorschau_fehlgeschlagen", description_placeholders={"fehler": str(ex)})
        if pv_inp.get("heizstufe"):
            self.a["pv_heizstufe"] = int(pv_inp["heizstufe"])
        self.a.update(klima_sender=inp["klima_sender"], ir_geraet=inp.get("ir_geraet", "klima"), befehl_kuehlen=inp.get("befehl_kuehlen", "power_{stufe}"),
                      befehl_zusatz=inp.get("befehl_kuehlen_zusatz", "eco_{stufe}"), befehl_aus=inp.get("befehl_aus", "power_off"),
                      luefter=inp.get("luefter", ""), stufe_min=inp.get("stufe_min", 16), stufe_max=inp.get("stufe_max", 23),
                      befehl_heizen=inp.get("befehl_heizen", self.a.get("befehl_heizen", "")), befehl_heizen_aus=inp.get("befehl_heizen_aus", self.a.get("befehl_heizen_aus", "")))
        self._lern_nur = None
        return await self.async_step_lernen_auswahl()

    async def async_step_steckdose(self, user_input=None):
        """Klima-Steckdose nachträglich einrichten, ändern oder entfernen – in Klimaautomatik und PV-Heizen gemeinsam."""
        a = self.a
        if not a.get("klima") or a.get("klima_art", "ir") != "ir":
            return self.async_abort(reason="keine_klima_ir")
        key = a["key"]
        ids = [f"hz_{key}_klima"] + ([f"hz_{key}_pv"] if a.get("pv") else [])
        if user_input is not None:
            steckdose = user_input.get("klima_steckdose") or ""
            neu = {"klima_steckdose": steckdose,
                   "klima_leistung": user_input.get("klima_leistung") or (leistung_zur_steckdose(self.hass, steckdose) if steckdose else ""),
                   "laeuft_ab_w": float(user_input.get("laeuft_ab_w", 15))}
            try:
                geaendert = await mit_verbindung(self.hass, lambda ha: ra.strom_setzen(ha, ids, {**a, **neu}))
            except Exception as ex:  # noqa: BLE001
                _LOGGER.exception("Klima-Steckdose für %s nicht geändert", a["raum_name"])
                return self.async_abort(reason="steckdose_fehlgeschlagen", description_placeholders={"fehler": str(ex)})
            daten = dict(self.config_entry.data)
            daten["a"] = {**dict(daten["a"]), **neu}
            self.hass.config_entries.async_update_entry(self.config_entry, data=daten)
            if steckdose:
                stand = (f"Steckdose {steckdose}: bleibt dauerhaft eingeschaltet, vor jedem IR-Befehl wird sie bei Bedarf eingeschaltet. "
                         + (f"Rückmeldung über {neu['klima_leistung']} (läuft ab {neu['laeuft_ab_w']:g} W)." if neu["klima_leistung"]
                            else "Keine Leistungsmessung gefunden – ohne Rückmeldung."))
            elif neu["klima_leistung"]:
                stand = f"Keine Steckdose; Rückmeldung über {neu['klima_leistung']} (läuft ab {neu['laeuft_ab_w']:g} W)."
            else:
                stand = "Klima-Steckdose und Rückmeldung entfernt."
            return self.async_abort(reason="steckdose_fertig", description_placeholders={
                "stand": stand, "liste": "\n".join(f"- {x}" for x in geaendert) or "- keine (war bereits so eingetragen)"})

        def lesen(ha):  # aktueller Stand steht in der Klimaautomatik (dort kann auch von Hand geändert worden sein)
            return ha.rest("GET", f"/api/config/automation/config/hz_{key}_klima")["use_blueprint"]["input"]

        try:
            inp = await mit_verbindung(self.hass, lesen)
        except Exception:  # noqa: BLE001
            inp = {}

        def vorgabe(k):
            w = inp.get(k) if isinstance(inp.get(k), str) and inp.get(k) else a.get(k)
            return {"description": {"suggested_value": w}} if w else {}
        return self.async_show_form(step_id="steckdose", data_schema=vol.Schema({
            vol.Optional("klima_steckdose", **vorgabe("klima_steckdose")): _ent("switch"),
            vol.Optional("klima_leistung", **vorgabe("klima_leistung")): _ent("sensor", "power"),
            vol.Required("laeuft_ab_w", default=inp.get("laeuft_ab_w", a.get("laeuft_ab_w", 15))): _zahl(2, 500, 1, "W")}),
            description_placeholders={"raum": a["raum_name"], "automationen": "„Klima " + a["raum_name"] + "“"
                                      + (" und „PV-Heizen " + a["raum_name"] + "“" if a.get("pv") else "")})

    async def _nach_lernen(self):
        if self._ablauf:  # Klimaanlage wurde über „Funktionen ändern“ ergänzt → weiter im Ablauf
            return await self._weiter()
        gesetzt = await self._ir_freigabe_setzen(((self.config_entry.data.get("rueckbau") or {}).get("entitaeten") or {}))
        return self.async_abort(reason="ir_fertig", description_placeholders={
            "anzahl": str(len(getattr(self, "_gelernt", []))),
            "freigabe": ("\n\nDie Heizbefehle des PV-Heizens wurden getestet und bestätigt – die IR-Prüffreigabe ist jetzt eingeschaltet." if gesetzt else "")})

    async def async_step_funktionen(self, user_input=None):
        self._modus = "anpassen"
        return await super().async_step_funktionen(user_input)

    async def async_step_geraet(self, user_input=None):
        """Gerät austauschen: altes Gerät wählen (alle Geräte, die die Automationen dieses Raums verwenden)."""
        ids = list((self.config_entry.data.get("rueckbau") or {}).get("automationen") or [])
        if user_input is not None and user_input.get("alt") in getattr(self, "_geraete", {}):
            self._geraet_alt = user_input["alt"]
            return await self.async_step_geraet_neu()
        try:
            self._geraete = await mit_verbindung(self.hass, lambda ha: ra.geraete_im_raum(ha, ids))
        except Exception as ex:  # noqa: BLE001
            return self.async_abort(reason="vorschau_fehlgeschlagen", description_placeholders={"fehler": str(ex)})
        for eid in bt_geraete(self.hass, self.a.get("bt")):
            self._geraete.setdefault(eid, []).append("Better Thermostat")

        def text(eid):
            z = self.hass.states.get(eid)
            return f"{z.name if z else eid} ({eid}) – in: {', '.join(self._geraete[eid])}"
        reihen = sorted(self._geraete, key=lambda e: (e.split(".")[0], text(e)))
        return self.async_show_form(step_id="geraet", data_schema=vol.Schema({vol.Required("alt"): _wahl([(e, text(e)) for e in reihen])}),
                                    description_placeholders={"raum": self.a["raum_name"]})

    async def _andere_raeume_mit(self, alt):
        """Andere Räume dieser Integration, deren Automationen oder Better Thermostat dieses Gerät ebenfalls verwenden (z. B. Energiesensoren, Außenfühler)."""
        andere = [e for e in self.hass.config_entries.async_entries(DOMAIN) if e.entry_id != self.config_entry.entry_id]

        def finden(ha):
            return [e for e in andere if alt in ra.geraete_im_raum(ha, list((e.data.get("rueckbau") or {}).get("automationen") or []))]
        try:
            treffer = await mit_verbindung(self.hass, finden)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Andere Räume mit %s nicht feststellbar", alt)
            treffer = []
        treffer += [e for e in andere if e not in treffer and alt in bt_geraete(self.hass, (e.data.get("a") or {}).get("bt"))]
        return treffer

    async def _geraet_in_raum_tauschen(self, eintrag, alt, neu):
        """Ersetzt das Gerät in einem Raum: Blueprint-Eingaben seiner Automationen, sein Better Thermostat und die gespeicherten Raumdaten."""
        ids = list((eintrag.data.get("rueckbau") or {}).get("automationen") or [])
        geaendert = list(await mit_verbindung(self.hass, lambda ha: ra.geraet_tauschen(ha, ids, alt, neu)))
        a_raum = eintrag.data.get("a") or {}
        bt_hinweis = None
        try:
            bt_geaendert, bt_hinweis = await bt_geraet_tauschen(self.hass, a_raum.get("bt"), alt, neu)
        except Exception as ex:  # noqa: BLE001
            _LOGGER.exception("Gerät %s im Better Thermostat nicht getauscht", alt)
            bt_geaendert, bt_hinweis = False, f"Im Better Thermostat nicht getauscht: {ex}"
        if bt_geaendert:
            geaendert.append(f"Better Thermostat ({a_raum.get('bt')})")
        daten = dict(eintrag.data)
        daten["a"] = ra.a_tauschen(dict(daten["a"]), alt, neu)
        bf = dict(daten.get("bt_fenster") or {})
        if bf.get("bt") == alt and bf.get("neu"):  # neues Better Thermostat bekommt denselben Fenstersensor
            await bt_fenster_setzen(self.hass, neu, bf["neu"])
            daten["bt_fenster"] = dict(bf, bt=neu)
        self.hass.config_entries.async_update_entry(eintrag, data=daten)
        return geaendert, bt_hinweis

    async def async_step_geraet_neu(self, user_input=None):
        alt = self._geraet_alt
        domain = alt.split(".")[0]
        if not hasattr(self, "_andere_mit_geraet") or getattr(self, "_andere_fuer", None) != alt:
            self._andere_mit_geraet, self._andere_fuer = await self._andere_raeume_mit(alt), alt
        if user_input is not None and user_input.get("neu"):
            neu = user_input["neu"]
            try:
                geaendert, bt_hinweis = await self._geraet_in_raum_tauschen(self.config_entry, alt, neu)
                if user_input.get("alle_raeume", True):
                    for e in self._andere_mit_geraet:
                        g, h = await self._geraet_in_raum_tauschen(e, alt, neu)
                        geaendert += [f"{e.title}: {x}" for x in g]
                        bt_hinweis = bt_hinweis or (f"{e.title}: {h}" if h else None)
            except Exception as ex:  # noqa: BLE001
                return self.async_abort(reason="vorschau_fehlgeschlagen", description_placeholders={"fehler": str(ex)})
            return self.async_abort(reason="geraet_fertig", description_placeholders={
                "alt": alt, "neu": neu, "liste": "\n".join(f"- {x}" for x in geaendert) or ("- nirgends" if bt_hinweis else "- keine (Gerät wird nicht mehr verwendet)"),
                "hinweis": f"\n\n⚠ {bt_hinweis}" if bt_hinweis else ""})
        z = self.hass.states.get(alt)
        felder = {vol.Optional("neu"): _ent(domain)}
        if self._andere_mit_geraet:
            felder[vol.Required("alle_raeume", default=True)] = _JA
        andere = ", ".join(e.title for e in self._andere_mit_geraet)
        return self.async_show_form(step_id="geraet_neu", errors={"base": "pflichtfeld"} if user_input is not None else {},
                                    data_schema=vol.Schema(felder),
                                    description_placeholders={"alt": f"{z.name if z else alt} ({alt})", "verwendet": ", ".join(self._geraete.get(alt, [])),
                                                              "andere": (f"\n\n**Auch verwendet in:** {andere}" if andere else "")})

    async def async_step_alte_karten(self, user_input=None):
        daten = dict(self.config_entry.data)
        r = dict(daten.get("rueckbau") or {})
        if user_input is not None:
            gewaehlt = [k for k in self._karten if k["id"] in (user_input.get("karten") or [])]
            if not gewaehlt:
                return self.async_abort(reason="keine_auswahl")
            ordner = self.hass.config.path("heizung_universal", self.a["key"])
            try:
                protokoll, fehler = await mit_verbindung(self.hass, lambda ha: ra.alte_karten_entfernen(ha, gewaehlt, ordner))
            except Exception as ex:  # noqa: BLE001
                return self.async_abort(reason="vorschau_fehlgeschlagen", description_placeholders={"fehler": str(ex)})
            r["alte_karten"] = list(r.get("alte_karten") or []) + protokoll
            daten["rueckbau"] = r
            self.hass.config_entries.async_update_entry(self.config_entry, data=daten)
            return self.async_abort(reason="alte_karten_fertig", description_placeholders={
                "liste": "\n".join(f"- {k['dashboard']} › „{k['name']}“" for k in protokoll) or "- keine", "fehler": "\n".join(fehler) or "keine"})
        try:
            self._karten = await self._alte_karten_kandidaten(r.get("alt"), (r.get("entitaeten") or {}).get("status"))
        except Exception as ex:  # noqa: BLE001
            return self.async_abort(reason="vorschau_fehlgeschlagen", description_placeholders={"fehler": str(ex)})
        if not self._karten:
            return self.async_abort(reason="keine_alten_karten")
        return self.async_show_form(step_id="alte_karten", data_schema=vol.Schema({
            vol.Optional("karten", default=[]): _wahl([(k["id"], self._karten_beschriftung(k)) for k in self._karten], mehrfach=True)}),
            description_placeholders={"raum": self.a["raum_name"], "anzahl": str(len(self._karten))})

    @mit_zurueck
    async def async_step_aendern_bestaetigen(self, user_input=None):
        daten = dict(self.config_entry.data)
        r = daten["rueckbau"]
        a_alt, a_neu = self._a_alt, self.a
        ordner = self.hass.config.path("heizung_universal", a_neu["key"])
        if user_input is not None and user_input.get("bestaetigt"):
            try:
                erg = await mit_verbindung(self.hass, lambda ha: ra.aendern(ha, a_alt, a_neu, r, ordner, daten.get("automationen") or {}))
            except Exception as ex:  # noqa: BLE001
                _LOGGER.exception("Funktionen des Raums %s nicht geändert", a_neu["raum_name"])
                return self.async_abort(reason="aendern_fehlgeschlagen", description_placeholders={"fehler": str(ex)})
            daten.update(a=a_neu, rueckbau=erg["rueckbau"], automationen=erg["automationen"])
            ziel = fenster_ziel(a_neu, erg["rueckbau"].get("entitaeten"))
            bf = dict(daten.get("bt_fenster") or {})
            if a_neu.get("fenster_reaktion") == "bt" and ziel and bf.get("neu") != ziel:
                alt_wert = await bt_fenster_setzen(self.hass, a_neu["bt"], ziel)
                daten["bt_fenster"] = {"bt": a_neu["bt"], "alt": bf.get("alt", alt_wert), "neu": ziel}
            self.hass.config_entries.async_update_entry(self.config_entry, data=daten)
            await self._ir_freigabe_setzen(erg["rueckbau"].get("entitaeten"))
            return self.async_abort(reason="funktionen_fertig", description_placeholders={
                "liste": "\n".join(f"- {x}" for x in erg["log"][:-1]) or "- nichts", "fehler": "\n".join(erg["fehler"]) or "keine"})
        try:
            pl = await mit_verbindung(self.hass, lambda ha: ra.aenderung_planen(ha, a_alt, a_neu, r))
        except Exception as ex:  # noqa: BLE001
            return self.async_abort(reason="vorschau_fehlgeschlagen", description_placeholders={"fehler": str(ex)})
        if not (pl["helfer_neu"] or pl["helfer_weg"] or pl["helfer_anders"] or pl["autos_neu"] or pl["autos_weg"] or pl["autos_anders"] or pl["autos_ersetzt"]):
            return self.async_abort(reason="nichts_geaendert")
        zeilen = []
        for titel, liste in (("Neue Helfer", [f"{x['name']} (`{x['entity_id']}`)" for x in pl["helfer_neu"]]),
                             ("Angepasste Helfer", [f"{x['name']}" for x in pl["helfer_anders"]]),
                             ("Neue Automationen", [x["alias"] for x in pl["autos_neu"]]),
                             ("Angepasste Automationen", [x["alias"] for x in pl["autos_anders"]]),
                             ("Auf ein anderes Blueprint umgestellt", [x["alias"] for x in pl["autos_ersetzt"]]),
                             ("Gelöschte Automationen", [x["alias"] for x in pl["autos_weg"]]),
                             ("Gelöschte Helfer", [f"{x['name']} (`{x['entity_id']}`)" for x in pl["helfer_weg"]])):
            if liste:
                zeilen.append(f"**{titel}**\n" + "\n".join(f"- {x}" for x in liste))
        if pl["konflikte"]:
            zeilen.append("⚠ Diese Helfer gibt es schon (nicht von diesem Raum): " + ", ".join(pl["konflikte"]) + " – die Änderung wird abgewiesen.")
        karten = len({d.get("url_path") for d in (r.get("dashboards") or [])})
        return self.async_show_form(step_id="aendern_bestaetigen", data_schema=vol.Schema({vol.Required("bestaetigt", default=False): _JA}),
                                    description_placeholders={"raum": a_neu["raum_name"], "aenderungen": "\n\n".join(zeilen),
                                                              "karten": str(karten) if pl["karte_anders"] else "0"})

    async def async_step_karte(self, user_input=None):
        return await self.async_step_dashboard()

    async def _nach_platz(self):
        daten = dict(self.config_entry.data)
        r = dict(daten["rueckbau"])
        ordner = self.hass.config.path("heizung_universal", self.a["key"])
        merkmal = r["entitaeten"]["status"]
        ziele = list(self.ziele)
        a = self.a

        def versetzen(ha):
            helfer = r.get("kartenhelfer") or ra.plane(a, ra.Bestand([], []), None)["kartenhelfer"]
            ra.karten_entfernen(ha, r)
            x = ra.Ausfuehrung(ha, ra.Path(ordner), False)
            x.leise = True
            x.rueckbau = dict(r, dashboard=None, dashboards=[], kartenhelfer=helfer)
            for z in ziele:
                x.karte(dict(z, merkmal=merkmal), ra.raumkarte(helfer, z.get("design", "glas")))
            return x.rueckbau

        try:
            daten["rueckbau"] = await mit_verbindung(self.hass, versetzen)
        except Exception as ex:  # noqa: BLE001
            return self.async_abort(reason="vorschau_fehlgeschlagen", description_placeholders={"fehler": str(ex)})
        daten["ziele"] = ziele
        self.hass.config_entries.async_update_entry(self.config_entry, data=daten)
        return self.async_abort(reason="karte_fertig", description_placeholders={"anzahl": str(len(ziele))})
