"""Lokaler Ablauf-Simulator für die drei Blueprints (benötigt Jinja2).

Bildet die für die Blueprints relevanten Teile von Home Assistant nach:
  * Zustände mit Attributen und Zeitstempeln, Helfer-Dienste, Timer mit Ablaufereignis
  * Trigger: state (to/from/attribute/for), time, time_pattern, event (timer.finished), homeassistant start
  * Aktionen: variables, if/then/else, choose, condition, Dienstaufruf, stop, delay, wait_template, sequence, continue_on_error
  * Template-Umgebung: states(), is_state(), state_attr(), now(), today_at(), as_datetime(), as_timestamp(), float/int-Filter,
    Ergebnis-Typumwandlung wie in Home Assistant
Mehrere Automationen laufen im selben simulierten Raum und lösen sich gegenseitig aus (Warteschlange je Ereignis).

Das ist ein Nachbau, kein Home Assistant: Er prüft die Logik der Blueprints, nicht das Schema oder die Laufzeit von HA selbst.
Annahmen: Eine nicht erfüllte `condition`-Aktion beendet nur die Sequenz, in der sie steht (oberste Ebene = ganzer Lauf);
`stop` beendet den ganzen Lauf; Variablen aus inneren Blöcken sind außen nicht sichtbar.
"""
import ast
import collections
import copy
import datetime as dt
import json
import logging
import re
import subprocess
from pathlib import Path

import jinja2

BASIS = Path(__file__).resolve().parent.parent
BP_ORDNER = BASIS / "blueprints" / "automation" / "ha_heizung_universal"
TZ = dt.timezone(dt.timedelta(hours=1))
_OHNE = object()
_NUMERISCH = re.compile(r"^[+-]?(?!0\d)\d*(?:\.\d*)?$")
_BP_CACHE = {}


class SimFehler(Exception):
    pass


class _BedingungFalsch(Exception):
    pass


class _Stop(Exception):
    pass


def lade_blueprint(datei):
    if datei not in _BP_CACHE:
        ruby = ('d=Psych.safe_load(File.read(ARGV[0], encoding:"UTF-8").gsub(/!input\\s+([a-z0-9_]+)/, %q("!input \\1"))); puts JSON.generate(d)')
        aus = subprocess.run(["ruby", "-rjson", "-rpsych", "-e", ruby, str(BP_ORDNER / datei)], capture_output=True, text=True,
                             env={"LANG": "en_US.UTF-8", "PATH": "/usr/bin:/bin"}, check=True).stdout
        _BP_CACHE[datei] = json.loads(aus)
    return _BP_CACHE[datei]


def _eingaben(bp):
    aus = {}

    def lauf(h):
        for k, v in h.items():
            if isinstance(v, dict) and isinstance(v.get("input"), dict):
                lauf(v["input"])
            else:
                aus[k] = v
    lauf(bp["blueprint"]["input"])
    return aus


def _ersetze(o, werte):
    if isinstance(o, str) and o.startswith("!input "):
        return copy.deepcopy(werte[o[7:]])
    if isinstance(o, dict):
        return {k: _ersetze(v, werte) for k, v in o.items()}
    if isinstance(o, list):
        return [_ersetze(v, werte) for v in o]
    return o


def _liste(x):
    return x if isinstance(x, list) else [x]


def _dauer(x):
    if isinstance(x, dict):
        return dt.timedelta(hours=float(x.get("hours", 0)), minutes=float(x.get("minutes", 0)), seconds=float(x.get("seconds", 0)))
    h, m, s = (str(x).split(":") + ["0", "0"])[:3]
    return dt.timedelta(hours=int(h), minutes=int(m), seconds=float(s))


class Zustand:
    def __init__(self, entity_id, state, attributes, zeit):
        self.entity_id, self.state, self.attributes = entity_id, state, attributes
        self.last_changed = self.last_updated = self.last_reported = zeit


class _States:
    def __init__(self, sim):
        self.sim = sim

    def __call__(self, eid):
        z = self.sim.z.get(eid) if isinstance(eid, str) else None
        return z.state if z else "unknown"

    def __getitem__(self, eid):
        return self.sim.z.get(eid) if isinstance(eid, str) else None


class Automation:
    def __init__(self, sim, entity_id, datei, eingaben):
        bp = lade_blueprint(datei)
        dekl = _eingaben(bp)
        unbekannt = set(eingaben) - set(dekl)
        fehlend = {k for k, v in dekl.items() if "default" not in v} - set(eingaben)
        if unbekannt or fehlend:
            raise SimFehler(f"{datei}: unbekannte Eingaben {sorted(unbekannt)}, fehlende Pflichtfelder {sorted(fehlend)}")
        werte = {k: v.get("default") for k, v in dekl.items()}
        werte.update(eingaben)
        cfg = _ersetze({k: bp.get(k) for k in ("trigger_variables", "variables", "triggers", "conditions", "actions")}, werte)
        self.trigger_variablen = cfg.get("trigger_variables") or {}
        self.sim, self.entity_id, self.datei = sim, entity_id, datei
        self.eingaben = dict(eingaben)
        self.variablen = cfg["variables"] or {}
        self.trigger = [t for t in cfg["triggers"] if t.get("enabled", True) is not False]
        self.bedingungen = cfg["conditions"] or []
        self.aktionen = cfg["actions"]
        self.laeufe, self.abbrueche = 0, []
        sim.zustand(entity_id, "on")
        sim.autos.append(self)

    # ------------------------------------------------------------ Lauf
    def lauf(self, trigger):
        if self.sim.s(self.entity_id) != "on":
            return
        basis = {"trigger": trigger}
        for k, v in self.variablen.items():
            basis[k] = self.sim.render(v, basis)
        if not all(self.sim.bedingung(b, basis) for b in self.bedingungen):
            return
        self.laeufe += 1
        try:
            self._folge(self.aktionen, collections.ChainMap(basis), True)
        except _Stop:
            pass
        except SimFehler as f:
            self.abbrueche.append(f"{self.sim.jetzt:%a %H:%M:%S} {trigger.get('id')}: {f}")

    def _folge(self, aktionen, scope, oben):
        for a in aktionen:
            try:
                self._schritt(a, scope)
            except _BedingungFalsch:
                return
            except SimFehler:
                if a.get("continue_on_error"):
                    continue
                raise

    def _setze(self, scope, k, v):
        for m in scope.maps:
            if k in m:
                m[k] = v
                return
        scope.maps[0][k] = v

    def _schritt(self, a, scope):
        sim = self.sim
        if "variables" in a:
            for k, v in a["variables"].items():
                self._setze(scope, k, sim.render(v, scope))
        elif "if" in a:
            if all(sim.bedingung(b, scope) for b in a["if"]):
                self._folge(a.get("then", []), scope.new_child(), False)
            elif "else" in a:
                self._folge(a["else"], scope.new_child(), False)
        elif "choose" in a:
            for zweig in a["choose"]:
                if all(sim.bedingung(b, scope) for b in zweig.get("conditions", [])):
                    self._folge(zweig["sequence"], scope.new_child(), False)
                    break
            else:
                self._folge(a.get("default", []), scope.new_child(), False)
        elif "condition" in a:
            if not sim.bedingung(a, scope):
                raise _BedingungFalsch()
        elif "action" in a:
            dienst = sim.render(a["action"], scope)
            ziel = _liste(sim.render(a.get("target", {}), scope).get("entity_id", []))
            sim.dienst(dienst, ziel, sim.render(a.get("data", {}), scope), self)
        elif "stop" in a:
            raise _Stop()
        elif "delay" in a:
            sim.leere(ausser=self)
        elif "wait_template" in a:
            sim.leere(ausser=self)
            ok = sim.roh(a["wait_template"], scope).strip().lower() == "true"
            self._setze(scope, "wait", {"completed": ok})
            if not ok and a.get("continue_on_timeout", True) is False:
                raise _Stop()
        elif "sequence" in a:
            self._folge(a["sequence"], scope.new_child(), False)
        elif "repeat" in a and "for_each" in a["repeat"]:
            eintraege = _liste(sim.render(a["repeat"]["for_each"], scope))
            for i, eintrag in enumerate(eintraege, 1):
                kind = scope.new_child()
                kind["repeat"] = {"item": eintrag, "index": i, "first": i == 1, "last": i == len(eintraege)}
                self._folge(a["repeat"]["sequence"], kind, False)
        else:
            raise SimFehler(f"Unbekannte Aktion: {list(a)}")


class Sim:
    def __init__(self, start):
        self.jetzt = start.replace(tzinfo=TZ) if start.tzinfo is None else start
        self.z, self.autos, self.schlange, self.wartend, self.timer = {}, [], [], [], {}
        self.rufe, self.ir, self.logbuch, self.meldungen, self.warnungen = [], [], [], {}, []
        self.modelle, self.herzschlag, self.ir_defekt = [], [], set()
        self._tpl = {}
        protokoll = logging.getLogger(f"sim{id(self)}")
        protokoll.propagate = False

        class _H(logging.Handler):
            def emit(h, record):  # noqa: N805
                self.warnungen.append(f"{self.jetzt:%a %H:%M:%S} {record.getMessage()}")
        protokoll.addHandler(_H())
        env = jinja2.Environment(undefined=jinja2.make_logging_undefined(protokoll, jinja2.Undefined))

        def f_float(v, default=_OHNE):
            try:
                r = float(v)
                if r != r or r in (float("inf"), float("-inf")):
                    raise ValueError
                return r
            except (ValueError, TypeError):
                if default is _OHNE:
                    raise SimFehler(f"float ohne Standardwert für {v!r}")
                return default

        def f_int(v, default=_OHNE):
            try:
                return int(float(v))
            except (ValueError, TypeError):
                if default is _OHNE:
                    raise SimFehler(f"int ohne Standardwert für {v!r}")
                return default

        def is_number(v):
            try:
                r = float(v)
                return r == r and r not in (float("inf"), float("-inf"))
            except (ValueError, TypeError):
                return False

        def is_state(eid, st):
            z = self.z.get(eid) if isinstance(eid, str) else None
            return z is not None and (z.state in st if isinstance(st, list) else z.state == st)

        def state_attr(eid, name):
            z = self.z.get(eid) if isinstance(eid, str) else None
            return z.attributes.get(name) if z else None

        def as_datetime(v):
            if isinstance(v, dt.datetime) or v is None:
                return v
            return dt.datetime.fromisoformat(str(v))

        def as_timestamp(v, default=_OHNE):
            try:
                return as_datetime(v).timestamp()
            except (ValueError, TypeError, AttributeError):
                if default is _OHNE:
                    raise SimFehler(f"as_timestamp ohne Standardwert für {v!r}")
                return default

        def today_at(t="00:00:00"):
            h, m, s = (str(t).split(":") + ["0", "0"])[:3]
            return self.jetzt.replace(hour=int(h), minute=int(m), second=int(float(s)), microsecond=0)

        env.globals.update(states=_States(self), is_state=is_state, state_attr=state_attr, now=lambda: self.jetzt, today_at=today_at,
                           as_datetime=as_datetime, as_timestamp=as_timestamp, timedelta=dt.timedelta, is_number=is_number,
                           float=f_float, int=f_int)
        env.filters.update(float=f_float, int=f_int, is_number=is_number, as_datetime=as_datetime, as_timestamp=as_timestamp,
                           from_json=json.loads)
        env.tests.update(is_state=is_state, is_number=is_number)
        self.env = env

    # ------------------------------------------------------------ Templates
    def roh(self, text, variablen):
        if text not in self._tpl:
            self._tpl[text] = self.env.from_string(text)
        return self._tpl[text].render(dict(variablen))

    def render(self, wert, variablen):
        if isinstance(wert, dict):
            return {k: self.render(v, variablen) for k, v in wert.items()}
        if isinstance(wert, list):
            return [self.render(v, variablen) for v in wert]
        if not isinstance(wert, str) or ("{{" not in wert and "{%" not in wert):
            return wert
        r = self.roh(wert, variablen).strip()
        if not r:
            return r
        try:
            erg = ast.literal_eval(r)
        except (ValueError, TypeError, SyntaxError, MemoryError):
            return r
        if isinstance(erg, str):
            return r
        if isinstance(erg, (int, float)) and not isinstance(erg, bool) and not _NUMERISCH.match(r):
            return r
        return erg

    def bedingung(self, b, variablen):
        if b.get("condition") != "template":
            raise SimFehler(f"Nicht unterstützte Bedingung: {b.get('condition')}")
        return self.roh(b["value_template"], variablen).strip().lower() == "true"

    # ------------------------------------------------------------ Zustände
    def s(self, eid):
        return self.z[eid].state if eid in self.z else "unknown"

    def attr(self, eid, name):
        return self.z[eid].attributes.get(name)

    def zustand(self, eid, state, **attrs):
        """Legt eine Entität an (ohne Trigger)."""
        self.z[eid] = Zustand(eid, str(state), attrs, self.jetzt)

    def setze(self, eid, state=None, _neu=False, **attrs):
        alt = self.z.get(eid)
        neu = Zustand(eid, str(state) if state is not None else alt.state, dict(alt.attributes if alt else {}, **attrs), self.jetzt)
        if alt and not _neu:
            if alt.state == neu.state and alt.attributes == neu.attributes:
                alt.last_reported = self.jetzt
                return
            if alt.state == neu.state:
                neu.last_changed = alt.last_changed
        self.z[eid] = neu
        alt_fuer_trigger = None if _neu else alt
        for auto in self.autos:
            for t in auto.trigger:
                if t["trigger"] != "state" or eid not in _liste(t.get("entity_id") or []):
                    continue
                if "attribute" in t:
                    if alt_fuer_trigger is not None and alt_fuer_trigger.attributes.get(t["attribute"]) == neu.attributes.get(t["attribute"]):
                        continue
                elif "to" in t or "from" in t:
                    if alt_fuer_trigger is not None and alt_fuer_trigger.state == neu.state:
                        continue
                    if t.get("to") is not None and neu.state not in _liste(t["to"]):
                        continue
                    if t.get("from") is not None and (alt_fuer_trigger is None or alt_fuer_trigger.state not in _liste(t["from"])):
                        continue
                tv = {"id": t.get("id"), "platform": "state", "entity_id": eid, "from_state": alt_fuer_trigger, "to_state": neu}
                if "for" in t:
                    dauer = t["for"]
                    if isinstance(dauer, str) and "{{" in dauer:  # wie Home Assistant: Vorlage mit den Trigger-Variablen der Automation
                        dauer = self.render(dauer, dict(auto.trigger_variablen))
                    self.wartend.append((self.jetzt + _dauer(dauer), auto, tv, neu.state, neu.last_changed))
                else:
                    self.schlange.append((auto, tv))
        for m in self.modelle:
            m(self, eid, alt, neu)

    def set(self, eid, state=None, **attrs):
        """Zustandsänderung von außen (Testtreiber) inklusive aller Folgereaktionen."""
        self.setze(eid, state, **attrs)
        self.leere()

    def leere(self, ausser=None):
        n = 0
        while True:
            idx = next((i for i, (a, _) in enumerate(self.schlange) if a is not ausser), None)
            if idx is None:
                return
            auto, tv = self.schlange.pop(idx)
            auto.lauf(tv)
            n += 1
            if n > 3000:
                raise SimFehler("Endlosschleife in der Trigger-Warteschlange")

    # ------------------------------------------------------------ Dienste
    def dienst(self, name, ziele, daten, quelle=None):
        self.rufe.append((self.jetzt, quelle.entity_id if quelle else "test", name, tuple(ziele), daten))
        if name == "persistent_notification.create":
            self.meldungen[daten["notification_id"]] = daten
            return
        if name == "persistent_notification.dismiss":
            self.meldungen.pop(daten["notification_id"], None)
            return
        if name == "logbook.log":
            self.logbuch.append((self.jetzt, daten.get("name"), daten.get("message")))
            return
        if not ziele:
            raise SimFehler(f"{name}: kein Ziel")
        for e in ziele:
            if e not in self.z:
                raise SimFehler(f"{name}: unbekannte Entität {e!r}")
            if name == "input_boolean.turn_on":
                self.setze(e, "on")
            elif name == "input_boolean.turn_off":
                self.setze(e, "off")
            elif name == "input_number.set_value":
                self.setze(e, str(float(daten["value"])))
            elif name == "input_select.select_option":
                if daten["option"] not in self.z[e].attributes.get("options", [daten["option"]]):
                    raise SimFehler(f"{e}: Option {daten['option']!r} gibt es nicht")
                self.setze(e, daten["option"])
            elif name == "input_text.set_value":
                if len(str(daten["value"])) > 255:
                    raise SimFehler(f"{e}: Text länger als 255 Zeichen")
                self.setze(e, str(daten["value"]))
            elif name == "timer.start":
                ende = self.jetzt + _dauer(daten.get("duration") or self.z[e].attributes.get("duration", "0:10:00"))
                self.timer[e] = ende
                self.setze(e, "active", finishes_at=ende.isoformat())
            elif name == "timer.cancel":
                self.timer.pop(e, None)
                self.setze(e, "idle")
            elif name == "climate.set_temperature":
                self.setze(e, daten.get("hvac_mode"), temperature=float(daten["temperature"]))
            elif name == "remote.send_command":
                if daten["command"] in self.ir_defekt or self.s(e) != "on":
                    raise SimFehler(f"IR-Senden fehlgeschlagen: {daten['command']}")
                self.ir.append((self.jetzt, daten["device"], daten["command"]))
                self.ir_sender = getattr(self, "ir_sender", []) + [e]
            else:
                raise SimFehler(f"Nicht unterstützter Dienst {name}")

    # ------------------------------------------------------------ Zeit und Ereignisse
    def ereignis(self, trigger_typ, **filter_):
        for auto in self.autos:
            for t in auto.trigger:
                if t["trigger"] == trigger_typ and all(t.get(k) == v for k, v in filter_.items()):
                    self.schlange.append((auto, {"id": t.get("id"), "platform": trigger_typ, **filter_}))
        self.leere()

    def start(self):
        self.ereignis("homeassistant", event="start")

    def reload(self):
        self.ereignis("event", event_type="automation_reloaded")

    def tick(self):
        self.jetzt += dt.timedelta(seconds=30)
        for e in self.herzschlag:
            self.z[e].last_reported = self.z[e].last_updated = self.jetzt
        for e, ende in sorted(self.timer.items(), key=lambda x: x[1]):
            if ende <= self.jetzt and e in self.timer:
                del self.timer[e]
                self.setze(e, "idle")
                for auto in self.autos:
                    for t in auto.trigger:
                        if t["trigger"] == "event" and t.get("event_type") == "timer.finished" and \
                                ("event_data" not in t or t["event_data"].get("entity_id") == e):
                            self.schlange.append((auto, {"id": t.get("id"), "platform": "event",
                                                         "event": {"event_type": "timer.finished", "data": {"entity_id": e}}}))
        for w in [w for w in self.wartend if w[0] <= self.jetzt]:
            self.wartend.remove(w)
            _, auto, tv, st, seit = w
            z = self.z.get(tv["entity_id"])
            if z and z.state == st and z.last_changed == seit:
                self.schlange.append((auto, tv))
        zeit = self.jetzt.strftime("%H:%M:%S")
        for auto in self.autos:
            for t in auto.trigger:
                if t["trigger"] == "time" and t.get("at") == zeit:
                    self.schlange.append((auto, {"id": t.get("id"), "platform": "time", "now": self.jetzt}))
                elif t["trigger"] == "time_pattern":
                    if "seconds" in t and self.jetzt.second % int(str(t["seconds"]).lstrip("/")) == 0:
                        self.schlange.append((auto, {"id": t.get("id"), "platform": "time_pattern", "now": self.jetzt}))
                    elif "minutes" in t and self.jetzt.second == 0 and self.jetzt.minute % int(str(t["minutes"]).lstrip("/")) == 0:
                        self.schlange.append((auto, {"id": t.get("id"), "platform": "time_pattern", "now": self.jetzt}))
        self.leere()

    def weiter(self, minuten=0, sekunden=0, bis=None):
        if bis is not None:
            h, m = (int(x) for x in bis.split(":"))
            ziel = self.jetzt.replace(hour=h, minute=m, second=0, microsecond=0)
            if ziel <= self.jetzt:
                ziel += dt.timedelta(days=1)
        else:
            ziel = self.jetzt + dt.timedelta(minutes=minuten, seconds=sekunden)
        while self.jetzt < ziel:
            self.tick()
