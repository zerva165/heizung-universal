"""Erzeugt die Dashboard-Karte eines Raums in drei Designs:
  mobil    kompakte Raumkarte für das Smartphone (kompakter Kopf, Profile in drei Spalten, je Raum eigene Tönung)
  glas     Liquid-Glass ausführlich: Kopf mit Detailzeilen und Hinweis-Chips
  verlauf  Farbverlauf nach Heizprofil (breite Karte, z. B. für ein Tablet-Dashboard)

Die Karte referenziert ausschließlich Raum-Helfer. Welche Geräte gerade zugeordnet sind, liest sie aus dem
Status-Text, den die Blueprint „Universelle Raumheizungssteuerung“ pflegt. Nach einem Gerätetausch in der
Blueprint-Instanz zeigt die Karte daher ohne Änderung die richtigen Werte.
"""
import re


GLAS = ("ha-card {\n  border-radius: 24px !important;\n  padding: 8px !important;\n"
        "  background: linear-gradient(145deg,\n    rgba(255,179,91,0.20), rgba(48,45,66,0.67)) !important;\n"
        "  border: 1px solid rgba(255,218,179,0.36);\n  box-shadow: 0 7px 20px rgba(0,0,0,0.17);\n"
        "  backdrop-filter: blur(20px);\n  overflow: hidden;\n}\n")

PROFILE = [("Komfort", "mdi:sofa", "rgba(166,105,229,0.45)", "#d0a4ff"),
           ("Übergang", "mdi:leaf", "rgba(49,160,100,0.45)", "#78e0a3"),
           ("Sommer", "mdi:white-balance-sunny", "rgba(226,168,47,0.45)", "#ffd16e"),
           ("Urlaub", "mdi:palm-tree", "rgba(70,125,205,0.45)", "#87b4ff"),
           ("Aus", "mdi:power", "rgba(120,125,135,0.50)", "#c5cad1")]

# Gemeinsamer JS-Vorspann: Status-Text zerlegen und Hilfsfunktionen
JS_KOPF = r"""
const ST = '__STATUS__';
const raw = states[ST]?.state || '';
const m = {};
raw.split('|').forEach(p => { const i = p.indexOf('='); if (i > 0) m[p.slice(0, i)] = p.slice(i + 1); });
const num = x => x === undefined || x === null || x === '' || !Number.isFinite(Number(x)) ? null : Number(x);
const fmt = x => num(x) === null ? '–' : num(x).toLocaleString('de-DE', {minimumFractionDigits: 1, maximumFractionDigits: 1}) + ' °C';
const esc = x => String(x ?? '–').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const bt = m.bt ? states[m.bt] : undefined;
const btOk = !!bt && !['unknown', 'unavailable'].includes(bt.state);
const tage = {mo:'Mo', di:'Di', mi:'Mi', do:'Do', fr:'Fr', sa:'Sa', so:'So'};
"""


def _js(body, status):
    return "[[[" + JS_KOPF.replace("__STATUS__", status) + body + "\n]]]"


def kopf(h):
    st = h["status_text"]
    boost_timer = h.get("boost_timer") or ""
    icon = _js(r"""
const offen = m.f === 'offen' || bt?.attributes?.window_open === true;
const heizt = m.a === 'heating';
return `<ha-icon icon="${offen ? 'mdi:window-open-variant' : heizt ? 'mdi:fire' : 'mdi:radiator'}" style="width:30px;height:30px;color:${offen ? '#ffb4a8' : heizt ? '#ffb15c' : '#ffcb88'}"></ha-icon>`;""", st)
    info = _js(r"""
const status = !raw ? 'Status fehlt' : !btOk ? 'Thermostat nicht verfügbar' : m.a === 'heating' ? 'Heizt' : (bt.state === 'off' || m.a === 'off') ? 'Pause' : m.a === 'idle' ? 'Leerlauf' : '–';
return `<div class="kopf"><div class="name">__NAME__</div><div class="temp">${fmt(m.t)}</div><div class="sub">${esc(m.p || '–')} · ${status}${m.m === 'test' ? ' · Testbetrieb' : ''}</div></div>`;""".replace("__NAME__", h["raum_name"]), st)
    details = _js(r"""
const row = (l, x) => `<div class="row"><span>${l}</span><strong>${x}</strong></div>`;
let w = '';
if (m.nx && m.nx.startsWith('A')) w = 'bis ' + m.nx.slice(1);
else if (m.nx && m.nx.startsWith('S')) w = 'nächste Phase ' + (tage[m.nx.slice(1, 3)] || '') + ' ' + m.nx.slice(3);
let h = row('Betrieb', esc(m.g || '–')) + row('Raum-Soll', fmt(m.z) + (w ? ' · ' + w : ''));
h += row('Thermostat-Soll', btOk ? fmt(bt.attributes.temperature) : 'nicht verfügbar');
const cm = bt?.attributes?.control_mode;
if (btOk && cm) h += row('Regelung', cm === 'optimal' ? 'über Raumfühler' : cm === 'sensor_fallback' ? 'Ersatz: Heizkörperfühler' : cm === 'hold' ? 'Ventile gehalten' : esc(cm));
let trvs = [];
try { trvs = Object.keys(JSON.parse(bt?.attributes?.batteries || '{}')).filter(id => id.startsWith('climate.')); } catch (e) { trvs = []; }
trvs.forEach((id, i) => {
  const t = states[id];
  const l = trvs.length === 1 ? 'Heizkörper' : id.includes('links') ? 'Heizkörper links' : id.includes('rechts') ? 'Heizkörper rechts' : 'Heizkörper ' + (i + 1);
  h += row(l, t && !['unknown','unavailable'].includes(t.state) ? fmt(t.attributes.temperature) : 'nicht verfügbar');
});
if (m.vh) { const vp = m.vh.split('@'); h += `<div class="hinweis">Vorheizen: mindestens ${fmt(vp[0])} bis ${esc(vp[1] || '–')} Uhr</div>`; }
const bz = '__BOOSTTIMER__';
if (bz && states[bz]?.state === 'active' && states[bz].attributes.finishes_at)
  h += `<div class="hinweis">Boost bis ${new Date(states[bz].attributes.finishes_at).toLocaleTimeString('de-DE', {hour:'2-digit', minute:'2-digit'})}</div>`;
return `<div class="details">${h}</div>`;""".replace("__BOOSTTIMER__", boost_timer), st)
    chips = _js(r"""
const chip = (t, k = '') => `<span class="chip ${k}">${esc(t)}</span>`;
let c = '';
if (m.f === 'offen') c += chip('Fenster offen', 'bad');
else if (m.f === 'ausfall') c += chip('Fensterkontakt ausgefallen (' + (m.n || '?') + ')', 'bad');
else if (m.f === 'zu') c += chip('Fenster geschlossen');
else if (m.f === 'unbekannt') c += chip('Fensterstatus unbekannt', 'bad');
if ((m.g || '').includes('Fensterpause') || bt?.attributes?.window_open === true) c += chip('Heizpause wegen Fenster', 'bad');
if ((m.g || '').includes('PV-Pause')) c += chip('PV heizt – Heizkörper zu', 'pv');
const ba = btOk ? (bt.attributes || {}) : {};
const ueber = Array.isArray(ba.active_overrides) ? ba.active_overrides : [];
const frei = Array.isArray(ba.released_trvs) ? ba.released_trvs.length : 0;
if (ba.control_mode === 'sensor_fallback') c += chip('Raumfühler ausgefallen – regelt mit Heizkörperfühlern', 'bad');
else if (ba.control_mode === 'hold') c += chip('Alle Fühler ausgefallen – Ventile gehalten', 'bad');
if (ba.devices_released === true || ueber.includes('devices_released')) c += chip('Heizkörper freigegeben – Vorgaben wirken nicht', 'bad');
else if (frei > 0 || ueber.includes('trvs_released')) c += chip((frei || 1) + ' Heizkörper freigegeben', 'bad');
const sperre = ba.heating_blocked_by;
if (sperre === 'no_call_for_heat') c += chip('BT heizt nicht: draußen über ' + (num(ba.off_temperature) !== null ? num(ba.off_temperature).toLocaleString('de-DE') + ' °C' : 'Grenzwert'), 'warn');
else if (sperre === 'door') c += chip('Tür offen – Heizpause (BT)', 'bad');
else if (sperre === 'hvac_off' && m.h === 'heat') c += chip('Thermostat ausgeschaltet', 'warn');
else if (sperre === 'valve_maintenance') c += chip('Ventilpflege läuft', 'warn');
else if (sperre === 'startup') c += chip('Better Thermostat startet');
if (ueber.includes('learning_paused')) c += chip('Lernen pausiert');
__FENSTERBT__
__KLIMA__
return c ? `<div class="chips">${c}</div>` : '';""".replace("__FENSTERBT__", (
        "if (ueber.includes('window_detection_off')) c += chip('Fenstererkennung im Better Thermostat aus – Fenster wirkt nicht', 'bad');"
        if h.get("fenster_bt") else "")).replace("__KLIMA__", (
        f"const km = states['{h['klima_modus']}']?.state; if (km && km !== 'Aus') c += chip('Klima: ' + km, 'cool');"
        if h.get("klima_modus") else "")), st)
    hintergrund = _js(r"""
const alarm = m.f === 'offen' || m.f === 'ausfall' || m.f === 'unbekannt' || bt?.attributes?.window_open === true;
return alarm ? 'linear-gradient(135deg, rgba(166,55,54,.55), rgba(64,28,37,.55))' : 'rgba(255,255,255,0.09)';""", st)
    trig = [st, h["heizprofil"]] + [x for x in [h.get("boost_timer"), h.get("boost_wert"), h.get("klima_modus")] if x]
    return {
        "type": "custom:button-card", "entity": st, "show_icon": False, "show_name": False, "show_state": False,
        "tap_action": {"action": "none"}, "triggers_update": trig,
        "custom_fields": {"icon": icon, "info": info, "details": details, "chips": chips},
        "styles": {
            "card": [{"padding": "10px"}, {"border-radius": "18px"}, {"background": hintergrund},
                     {"border": "1px solid rgba(255,255,255,0.16)"}, {"box-shadow": "none"}, {"color": "#ffffff"}],
            "grid": [{"grid-template-areas": '"icon info" "details details" "chips chips"'},
                     {"grid-template-columns": "34px minmax(0,1fr)"}, {"grid-template-rows": "auto auto auto"}, {"row-gap": "6px"}],
            "custom_fields": {"icon": [{"align-self": "start"}], "info": [{"justify-self": "start"}, {"text-align": "left"}],
                              "details": [{"width": "100%"}], "chips": [{"width": "100%"}]},
        },
        "extra_styles": (
            ".kopf .name {font-size:12px;font-weight:700;color:#fff;}\n"
            ".kopf .temp {font-size:24px;font-weight:800;line-height:28px;color:#fff;}\n"
            ".kopf .sub {font-size:10px;color:#e5ecf8;}\n"
            ".details {text-align:left;background:rgba(0,0,0,.14);padding:6px 9px;border-radius:13px;box-sizing:border-box;width:100%;}\n"
            ".row {display:flex;justify-content:space-between;gap:8px;font-size:10.5px;line-height:17px;color:#e5ecf8;}\n"
            ".row strong {color:#fff;font-weight:700;text-align:right;}\n"
            ".hinweis {font-size:10.5px;font-weight:800;line-height:16px;margin-top:3px;color:#ffdbac;}\n"
            ".chips {display:flex;gap:4px;flex-wrap:wrap;}\n"
            ".chip {background:rgba(255,255,255,.14);padding:3px 8px;border-radius:999px;font-size:9.5px;font-weight:700;line-height:13px;}\n"
            ".chip.bad {background:rgba(255,90,70,.28);color:#ffd0c8;}\n"
            ".chip.cool {background:rgba(70,170,255,.22);color:#bfe8ff;}\n"
            ".chip.pv {background:rgba(80,220,190,.22);color:#c4fff2;}\n"
            ".chip.warn {background:rgba(255,190,80,.24);color:#ffe2b0;}\n"),
    }


def knopf(entity, name, icon, aktiv_wert, bg, rand, aktion, hoehe="45px", text="#ffffff", icon_farbe="#ffdbac", basis_bg="rgba(255,255,255,0.08)",
          basis_rand="rgba(255,255,255,0.13)"):
    return {"type": "custom:button-card", "entity": entity, "name": name, "icon": icon, "show_state": False, "tap_action": aktion,
            "state": [{"value": aktiv_wert, "styles": {"card": [{"background": bg}, {"border": f"1px solid {rand}"}]}}],
            "styles": {"card": [{"height": hoehe}, {"padding": "3px 1px"}, {"border-radius": "13px"}, {"background": basis_bg},
                                {"border": f"1px solid {basis_rand}"}, {"box-shadow": "none"}],
                       "icon": [{"width": "19px"}, {"color": icon_farbe}], "name": [{"font-size": "9px"}, {"font-weight": "650"}, {"color": text}]}}


def nummer(entity, name, icon, bg, rand, akzent=None):
    stil = f"ha-card {{\n  border-radius: 16px !important;\n  background: {bg} !important;\n  border: 1px solid {rand};\n  box-shadow: none !important;\n}}\n"
    if akzent:
        stil += f"mushroom-shape-icon {{\n  --shape-color: {akzent}2e !important;\n  --icon-color: {akzent} !important;\n}}\n"
    return {"type": "custom:mushroom-number-card", "entity": entity, "name": name, "icon": icon, "display_mode": "buttons",
            "secondary_info": "state", "card_mod": {"style": stil}}


DESIGNS = {"mobil": "Mobil kompakt (kompakter Kopf, Profile in drei Spalten, je Raum eigene Tönung)",
           "glas": "Liquid-Glass ausführlich (Kopf mit Detailzeilen und Hinweis-Chips)",
           "verlauf": "Farbverlauf nach Heizprofil (390 px breit, dunkle Kacheln)"}

# Tönungen der Mobil-Raumkarten: Hintergrund, Rand, Symbolfarbe
TOENUNG = {"warm": ("255,179,91", "255,218,179", "#ffcb88"), "blau": ("143,179,223", "186,211,248", "#aee0ff"),
           "lila": ("174,142,225", "215,185,248", "#e0baff"), "gruen": ("97,198,143", "147,232,188", "#96edbf"),
           "terrakotta": ("203,145,109", "236,189,155", "#ffd6af"), "violett": ("165,143,218", "214,197,248", "#d4c3ff")}
# Raumname enthält … → Symbol und Tönung; Reihenfolge zählt („Büro / Flur oben“ = Büro)
RAUMSTIL = [(("wohn",), "mdi:sofa-outline", "warm"), (("schlaf",), "mdi:bed-king-outline", "blau"), (("bad",), "mdi:bathtub-outline", "lila"),
            (("kind",), "mdi:teddy-bear", "gruen"), (("büro", "buero", "buro", "arbeit"), "mdi:desk", "violett"),
            (("eingang", "flur", "diele"), "mdi:door", "terrakotta"), (("ess",), "mdi:table-chair", "blau"),
            (("küche", "kueche", "kuche"), "mdi:stove", "gruen"), (("gast",), "mdi:bed-outline", "blau"),
            (("keller",), "mdi:stairs-down", "terrakotta")]


def mobil_stil(raum_name):
    """(Symbol, Tönungsname) für einen Raum – nach dem Vorbild der vorhandenen Mobil-Karten."""
    n = (raum_name or "").lower()
    for teile, icon, ton in RAUMSTIL:
        if any(t in n for t in teile):
            return icon, ton
    return "mdi:radiator", "warm"


def mobil_kopf(h):
    """Kompakter Kartenkopf wie in „Mobil“: Symbol, Name, eine Zeile „21,7 °C · Komfort · Heizt“. Hinweise ersetzen den Status."""
    st = h["status_text"]
    icon, ton = mobil_stil(h["raum_name"])
    ifarbe = TOENUNG[ton][2]
    lage = r"""
const ba = btOk ? (bt.attributes || {}) : {};
const ueber = Array.isArray(ba.active_overrides) ? ba.active_overrides : [];
const offen = m.f === 'offen' || ba.window_open === true;
const sperre = ba.heating_blocked_by;
let warn = '', bad = false;
if (!raw) warn = 'Status fehlt';
else if (!btOk) { warn = 'Thermostat fehlt'; bad = true; }
else if (offen) { warn = 'Fenster offen'; bad = true; }
else if (m.f === 'ausfall') { warn = 'Fensterkontakt aus'; bad = true; }
else if (m.f === 'unbekannt') { warn = 'Fenster unbekannt'; bad = true; }
else if (ba.devices_released === true || ueber.includes('devices_released') || (Array.isArray(ba.released_trvs) && ba.released_trvs.length > 0) || ueber.includes('trvs_released')) { warn = 'Heizkörper frei'; bad = true; }
else if (ba.control_mode === 'sensor_fallback') { warn = 'Raumfühler aus'; bad = true; }
else if (ba.control_mode === 'hold') { warn = 'Fühler aus'; bad = true; }
else if (sperre === 'door') { warn = 'Tür offen'; bad = true; }
__FENSTERBT__
else if ((m.g || '').includes('PV-Pause')) warn = 'PV heizt';
else if (sperre === 'no_call_for_heat') warn = 'BT aus über ' + (num(ba.off_temperature) !== null ? num(ba.off_temperature).toLocaleString('de-DE') + ' °C' : 'Grenzwert');
else if (sperre === 'hvac_off' && m.h === 'heat') warn = 'Thermostat aus';
""".replace("__FENSTERBT__", "else if (ueber.includes('window_detection_off')) { warn = 'Fenstererkennung aus'; bad = true; }" if h.get("fenster_bt") else "")
    bz = h.get("boost_timer") or ""
    label = _js(lage + r"""
const t = num(m.t) !== null ? m.t : bt?.attributes?.current_temperature;
const a = m.a || bt?.attributes?.hvac_action;
const status = a === 'heating' ? 'Heizt' : a === 'idle' ? 'Leerlauf' : (a === 'off' || bt?.state === 'off') ? 'Aus' : '–';
const bz = '__BOOSTTIMER__';
const boost = bz && states[bz]?.state === 'active';
return `${num(t) === null ? '– °C' : fmt(t)} · ${esc(m.p || '–')} · ${esc(warn || (boost ? 'Boost' : status))}${m.m === 'test' ? ' · Test' : ''}`;""".replace("__BOOSTTIMER__", bz), st)
    hintergrund = _js(lage + "\nreturn bad ? 'linear-gradient(135deg, rgba(166,55,54,.55), rgba(64,28,37,.55))' : 'rgba(255,255,255,0.09)';", st)
    symbol = _js(lage + f"\nreturn offen ? 'mdi:window-open-variant' : bad ? 'mdi:alert-circle-outline' : '{icon}';", st)
    symbolfarbe = _js(lage + f"\nreturn bad ? '#ffb4a8' : '{ifarbe}';", st)
    trig = [st, h["heizprofil"]] + [x for x in [h.get("boost_timer"), h.get("klima_modus")] if x]
    return {
        "type": "custom:button-card", "entity": st, "name": h["raum_name"], "icon": symbol, "show_state": False, "show_label": True,
        "label": label, "triggers_update": trig,
        "tap_action": {"action": "more-info", "entity": _js("return m.bt || ST;", st)},
        "styles": {
            "card": [{"height": "65px"}, {"padding": "7px"}, {"border-radius": "18px"}, {"background": hintergrund},
                     {"border": "1px solid rgba(255,255,255,0.16)"}, {"box-shadow": "none"}],
            "grid": [{"grid-template-areas": '"i n" "i l"'}, {"grid-template-columns": "25px 1fr"}, {"grid-template-rows": "23px 22px"},
                     {"column-gap": "3px"}],
            "icon": [{"width": "21px"}, {"color": symbolfarbe}],
            "name": [{"justify-self": "start"}, {"font-size": "12px"}, {"font-weight": "700"}, {"color": "#ffffff"}, {"white-space": "nowrap"}],
            "label": [{"justify-self": "start"}, {"text-align": "left"}, {"font-size": "10px"}, {"color": "#e5ecf8"}, {"white-space": "nowrap"},
                      {"overflow": "hidden"}, {"text-overflow": "ellipsis"}],
        },
    }


def _mobil(karte, h):
    """Formt die Raumkarte in das Design der Mobil-Raumkarten um (für zwei Karten nebeneinander)."""
    a, r, _ = TOENUNG[mobil_stil(h["raum_name"])[1]]
    karte["card_mod"] = {"style": GLAS.replace("rgba(255,179,91,0.20)", f"rgba({a},0.20)").replace("rgba(255,218,179,0.36)", f"rgba({r},0.36)")}
    karten = karte["card"]["cards"]
    karten[0] = mobil_kopf(h)
    karten[1]["columns"] = 3
    for k in karten:
        if k.get("type") == "grid" and k is not karten[1]:  # Klima-Knöpfe: Schrift wie in Mobil (ohne Fettung)
            for b in k.get("cards", []):
                b["styles"]["name"] = [e for e in b["styles"]["name"] if "font-weight" not in e]
        if k.get("type") == "custom:mushroom-number-card":
            k.pop("secondary_info", None)
        if k.get("type") == "custom:button-card" and k.get("name") == "PV-Überschussheizen":  # Schalter im Stil von „Klimaautomatik“
            k["name"] = "PV-Heizen"
            k["styles"]["card"] = [{"height": "52px"}, {"padding": "8px 12px"}, {"border-radius": "17px"}, {"background": "rgba(60,190,160,0.13)"},
                                   {"border": "1px solid rgba(123,230,212,0.27)"}, {"box-shadow": "none"}]
            k["styles"]["grid"] = [{"grid-template-areas": '"i n schalter" "i l schalter"'}, {"grid-template-columns": "30px 1fr auto"},
                                   {"grid-template-rows": "22px 18px"}, {"column-gap": "8px"}]
            k["styles"]["icon"][0] = {"width": "22px"}
            k["styles"]["name"] = [{"justify-self": "start"}, {"font-size": "12px"}, {"color": "#f2f9ff"}]
            k["styles"]["label"] = [{"justify-self": "start"}, {"font-size": "10px"}, {"color": "#c4fff2"}, {"white-space": "nowrap"},
                                    {"overflow": "hidden"}, {"text-overflow": "ellipsis"}]
    return karte
# aktiver Profilknopf: Verlauf von/nach, Symbolfarbe
_VERLAUF_PROFIL = {"Komfort": ("180,105,40", "90,45,20", "#ffb35c"), "Übergang": ("55,145,85", "25,70,40", "#6cf59a"),
                   "Sommer": ("220,165,45", "110,75,20", "#ffd54d"), "Urlaub": ("65,105,185", "28,45,90", "#74b2ff"),
                   "Aus": ("90,90,95", "35,35,40", "#d5d5d5")}
_KACHEL = "rgba(30,30,30,.88)"


def _verlauf(karte, h):
    """Formt die Raumkarte in das Verlauf-Design um: 390 px breit, Kopf mit Farbverlauf nach Heizprofil, dunkle Kacheln."""
    st = h["status_text"]
    karte["card_mod"] = {"style": "ha-card {\n  max-width: 390px;\n  margin: 0 auto;\n  background: none;\n  box-shadow: none;\n}\n"}
    karten = karte["card"]["cards"]
    kopf_k = karten[0]
    kopf_k["styles"]["card"] = [
        {"border-radius": "30px"}, {"padding": "12px"},
        {"background": _js(r"""
const alarm = m.f === 'offen' || m.f === 'ausfall' || m.f === 'unbekannt' || bt?.attributes?.window_open === true;
if (alarm) return 'linear-gradient(135deg,#a63736,#401c25)';
const farben = {'Komfort':'112,76,166','Übergang':'55,145,85','Urlaub':'65,105,185','Sommer':'180,135,30'};
return `linear-gradient(135deg,rgba(${farben[m.p] || '35,38,45'},.96),#151e2d)`;""", st)},
        {"box-shadow": "0 12px 35px rgba(0,0,0,.45)"}, {"border": "1px solid rgba(255,255,255,0.08)"}, {"height": "auto"},
        {"color": "white"}, {"box-sizing": "border-box"}]
    kopf_k["styles"]["grid"] = [{"grid-template-areas": '"icon info" "details details" "chips chips"'},
                                {"grid-template-columns": "52px minmax(0,1fr)"}, {"grid-template-rows": "76px auto minmax(22px,auto)"}, {"row-gap": "4px"}]
    kopf_k["styles"]["custom_fields"]["info"] = [{"justify-self": "stretch"}, {"text-align": "center"}, {"padding-right": "52px"}]
    kopf_k["styles"]["custom_fields"]["icon"] = [{"align-self": "center"}]
    kopf_k["custom_fields"]["icon"] = kopf_k["custom_fields"]["icon"].replace("width:30px;height:30px", "width:40px;height:40px")
    kopf_k["extra_styles"] += (
        ".kopf {text-align:center;}\n.kopf .name {font-size:14px;font-weight:800;}\n.kopf .temp {font-size:32px;font-weight:900;line-height:35px;}\n"
        ".kopf .sub {font-size:13px;font-weight:800;color:#fff;}\n.details {padding:5px 8px;border-radius:14px;}\n"
        ".row {font-size:11px;line-height:17px;color:rgba(255,255,255,.82);}\n.row strong {font-size:12px;}\n.hinweis {font-size:12px;line-height:18px;}\n"
        ".chips {justify-content:center;}\n.chip {padding:4px 8px;font-size:10px;font-weight:800;}\n")
    for b in karten[1]["cards"]:
        von, nach, farbe = _VERLAUF_PROFIL.get(b["name"], _VERLAUF_PROFIL["Aus"])
        b["state"] = [{"value": b["name"], "styles": {"card": [{"background": f"linear-gradient(135deg, rgba({von},.96), rgba({nach},.96))"}]}}]
        b["styles"] = {"card": [{"height": "72px"}, {"border-radius": "22px"}, {"background": _KACHEL}, {"border": "none"}, {"box-shadow": "none"}],
                       "icon": [{"color": farbe}], "name": [{"font-weight": "900"}, {"font-size": "11px"}, {"color": "white"}]}

    def kacheln(c):
        if isinstance(c, list):
            for x in c:
                kacheln(x)
        elif isinstance(c, dict):
            if c.get("type") == "custom:button-card" and isinstance(c.get("styles"), dict):
                for e in c["styles"].get("card", []):
                    if "border-radius" in e:
                        e["border-radius"] = "22px"
                    if e.get("background") == "rgba(255,255,255,0.08)":
                        e["background"] = _KACHEL
                    if "border" in e and "rgba(255,255,255,0.13)" in str(e["border"]):
                        e["border"] = "none"
            if c.get("type") == "custom:mushroom-number-card" and isinstance(c.get("card_mod"), dict):
                stil = c["card_mod"]["style"].replace("border-radius: 16px", "border-radius: 22px")
                c["card_mod"]["style"] = re.sub(r"background: [^;]+ !important;", f"background: {_KACHEL} !important;", stil, count=1)
            for v in c.values():
                kacheln(v)

    kacheln(karten[2:])
    return karte


def raumkarte(h, design="glas"):
    """h: Dict mit raum_name, status_text, heizprofil und optional boost_wert, boost_timer, vorheizen_bericht,
    klima_modus, klima_ziel, klima_manuell, pv_heizfreigabe, pv_status, pv_fehler."""
    karten = [kopf(h)]
    karten.append({"type": "grid", "columns": 5, "square": False, "cards": [
        knopf(h["heizprofil"], p, ic, p, bg, rand, {"action": "perform-action", "perform_action": "input_select.select_option",
                                                      "target": {"entity_id": h["heizprofil"]}, "data": {"option": p}})
        for p, ic, bg, rand in PROFILE if not h.get("profile") or p in h["profile"]]})
    if h.get("boost_wert"):
        karten.append({"type": "conditional", "conditions": [{"condition": "state", "entity": h["boost_wert"], "state_not": "unavailable"}],
                       "card": nummer(h["boost_wert"], "Boost", "mdi:fire", "rgba(255,107,53,0.12)", "rgba(255,150,100,0.30)", "#ff6b35")})
    if h.get("vorheizen_bericht"):
        karten.append({"type": "conditional", "conditions": [{"condition": "state", "entity": h["vorheizen_bericht"], "state_not": ""}],
                       "card": {"type": "custom:button-card", "entity": h["vorheizen_bericht"], "show_icon": True, "icon": "mdi:clock-start",
                                "show_name": False, "show_state": True, "tap_action": {"action": "more-info"},
                                "styles": {"card": [{"padding": "6px 10px"}, {"border-radius": "13px"}, {"background": "rgba(0,0,0,0.14)"},
                                                    {"border": "1px solid rgba(255,255,255,0.10)"}, {"box-shadow": "none"}],
                                           "grid": [{"grid-template-areas": '"i s"'}, {"grid-template-columns": "22px 1fr"}],
                                           "icon": [{"width": "16px"}, {"color": "#ffdbac"}],
                                           "state": [{"font-size": "10px"}, {"color": "#e5ecf8"}, {"justify-self": "start"},
                                                     {"white-space": "normal"}, {"text-align": "left"}]}}})
    if h.get("klima_modus"):
        popup = {"type": "grid", "columns": 4, "square": False, "cards": [
            {"type": "button", "name": f"{t}°", "icon": "mdi:snowflake",
             "tap_action": {"action": "perform-action", "perform_action": "input_number.set_value",
                            "target": {"entity_id": h["klima_manuell"]}, "data": {"value": t}}} for t in range(16, 24)]} if h.get("klima_manuell") else None
        kalt = dict(hoehe="46px", text="#eafaff", icon_farbe="#8fe5ff", basis_bg="rgba(87,161,196,0.12)", basis_rand="rgba(115,202,236,0.27)")
        karten.append({"type": "grid", "columns": 3, "square": False, "cards": [
            knopf(h["klima_modus"], "Auto", "mdi:air-conditioner", "Automatik Kühlen", "rgba(38,161,219,0.40)", "#7bdcff",
                  {"action": "perform-action", "perform_action": "input_select.select_option", "target": {"entity_id": h["klima_modus"]},
                   "data": {"option": "Automatik Kühlen"}}, **kalt),
            knopf(h["klima_modus"], "Manuell", "mdi:snowflake", "Manuell Kühlen", "rgba(38,161,219,0.40)", "#7bdcff",
                  {"action": "fire-dom-event", "browser_mod": {"service": "browser_mod.popup",
                                                                "data": {"title": f"{h['raum_name']} – Klima manuell", "content": popup}}}
                  if h.get("klima_manuell") else  # Klimaanlage an einer Steckdose: Manuell = Dauerbetrieb, keine Stufen
                  {"action": "perform-action", "perform_action": "input_select.select_option", "target": {"entity_id": h["klima_modus"]},
                   "data": {"option": "Manuell Kühlen"}}, **kalt),
            knopf(h["klima_modus"], "Aus", "mdi:snowflake-off", "Aus", "rgba(115,125,135,0.35)", "#b5bdc6",
                  {"action": "perform-action", "perform_action": "input_select.select_option", "target": {"entity_id": h["klima_modus"]},
                   "data": {"option": "Aus"}}, **kalt)]})
        karten.append(nummer(h["klima_ziel"], "Klima Automatik Ziel", "mdi:thermometer", "rgba(100,173,207,0.13)", "rgba(125,213,245,0.25)"))
    if h.get("pv_heizfreigabe"):
        fg = h["pv_heizfreigabe"]
        # Schalter sichtbar machen: rechts ein Kippschalter „Freigabe an/aus“; solange aus, steht der Hinweis zum Einschalten im Status
        schalter = ("[[[ const an = states['" + fg + "']?.state === 'on';"
                    " return `<div style=\"display:flex;align-items:center;gap:7px;font-size:10px;font-weight:700;"
                    "color:${an ? '#7be6d4' : 'rgba(255,255,255,0.75)'}\">${an ? 'Freigabe an' : 'Freigabe aus'}"
                    "<span style=\"position:relative;display:inline-block;width:38px;height:21px;border-radius:11px;"
                    "background:${an ? '#2bb39a' : 'rgba(255,255,255,0.22)'};border:1px solid ${an ? '#7be6d4' : 'rgba(255,255,255,0.35)'}\">"
                    "<span style=\"position:absolute;top:2px;left:${an ? '19px' : '2px'};width:15px;height:15px;border-radius:50%;"
                    "background:#ffffff;box-shadow:0 1px 3px rgba(0,0,0,0.4)\"></span></span></div>`; ]]]")
        status = ("[[[ const an = states['" + fg + "']?.state === 'on'; const s = states['" + h["pv_status"] + "']?.state || '–';"
                  " if (!an) return 'Aus – zum Einschalten antippen';"
                  " return s.includes('IR-Prueffreigabe') ? 'IR-Befehle noch nicht geprüft – Konfigurieren → IR-Befehle: Heizbefehle testen' : s; ]]]")
        karten.append({"type": "custom:button-card", "entity": fg, "name": "PV-Überschussheizen", "icon": "mdi:solar-power-variant",
                       "show_state": False, "show_label": True, "label": status,
                       "custom_fields": {"schalter": schalter},
                       "triggers_update": [h["pv_status"], fg, h["pv_fehler"]],
                       "tap_action": {"action": "toggle", "haptic": "light"},
                       "state": [{"value": "on", "styles": {"card": [{"background": "rgba(60,190,160,0.30)"}, {"border": "1px solid #7be6d4"}]}}],
                       "styles": {"card": [{"padding": "8px 12px"}, {"border-radius": "13px"}, {"background": "rgba(255,255,255,0.08)"},
                                           {"border": "1px solid rgba(255,255,255,0.13)"}, {"box-shadow": "none"}, {"cursor": "pointer"}],
                                  "grid": [{"grid-template-areas": '"i n schalter" "i l schalter"'}, {"grid-template-columns": "26px 1fr auto"},
                                           {"column-gap": "8px"}],
                                  "custom_fields": {"schalter": [{"align-self": "center"}, {"justify-self": "end"}]},
                                  "icon": [{"width": "19px"}, {"color": "[[[ return states['" + h["pv_fehler"] + "']?.state === 'on' ? '#ff8a7a' : '#7be6d4'; ]]]"}],
                                  "name": [{"font-size": "11px"}, {"font-weight": "700"}, {"justify-self": "start"}, {"color": "#ffffff"}],
                                  "label": [{"font-size": "9.5px"}, {"justify-self": "start"}, {"text-align": "left"}, {"white-space": "normal"},
                                            {"color": "#c4fff2"}]}})
    karte = {"type": "custom:mod-card", "card_mod": {"style": GLAS}, "card": {"type": "vertical-stack", "cards": karten}}
    if design == "verlauf":
        return _verlauf(karte, h)
    if design == "mobil":
        return _mobil(karte, h)
    return karte
