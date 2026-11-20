// Führt alle [[[ ]]]-Templates der generierten Raumkarten mit verschiedenen Status-Lagen aus
// und prüft für die Better-Thermostat-2.0-Lagen, dass der passende Hinweis erscheint.
const fs = require('fs');
const karten = process.argv.slice(2).map(f => [f, JSON.parse(fs.readFileSync(f))]);
const sammle = (o, out = []) => { if (typeof o === 'string' && o.trim().startsWith('[[[')) out.push(o); else if (o && typeof o === 'object') Object.values(o).forEach(v => sammle(v, out)); return out; };
const bat = JSON.stringify({'sensor.wohnzimmer_raumfuehler_temperatur': {}, 'climate.trv_links': {}, 'climate.trv_rechts': {}});
const BT1 = {temperature: 22, hvac_action: 'heating', batteries: bat, window_open: false};                       // Better Thermostat 1.x
const BT2 = {...BT1, control_mode: 'optimal', heating_blocked_by: null, active_overrides: [], devices_released: false,
             released_trvs: [], off_temperature: 18, call_for_heat: true};                                            // Better Thermostat 2.0, Normalfall
const basis = (st, bta) => ({
  [st]: {state: ''},
  'climate.bt_neu': {state: 'heat', attributes: bta},
  'climate.trv_links': {state: 'heat', attributes: {temperature: 30.5}}, 'climate.trv_rechts': {state: 'heat', attributes: {temperature: 30.5}},
});
const HP = 'v=1|bt=climate.bt_neu|t=20.9|a=heating|p=Komfort|z=22.0|h=heat|g=Heizphase|f=zu|n=0|nx=A20:00|vh=|m=';
// [Status-Text, BT-Attribute, erwartete Texte, nicht erwartete Texte]
const lagen = {
  'Heizphase (BT 1.x)': [HP, BT1, [], ['Regelung']],
  'Vorheizen': ['v=1|bt=climate.bt_neu|t=19.1|a=heating|p=Komfort|z=21.0|h=heat|g=Vorheizen|f=zu|n=0|nx=Smi06:00|vh=21.0@06:00|m=', BT1, [], []],
  'Fenster offen + Pause': ['v=1|bt=climate.bt_neu|t=20.1|a=idle|p=Komfort|z=22.0|h=off|g=Heizphase · Fensterpause|f=offen|n=0|nx=A20:00|vh=|m=', BT1, [], []],
  'Kontaktausfall': ['v=1|bt=climate.bt_neu|t=20.1|a=idle|p=Übergang|z=17.0|h=heat|g=Absenkung|f=ausfall|n=1|nx=Sdo07:00|vh=|m=', BT1, [], []],
  'PV-Pause': ['v=1|bt=climate.bt_neu|t=22.4|a=off|p=Komfort|z=22.0|h=off|g=Heizphase · PV-Pause|f=zu|n=0|nx=A22:00|vh=|m=', BT1, [], []],
  'Testbetrieb, BT weg': ['v=1|bt=climate.gibt_es_nicht|t=|a=|p=Aus|z=5.0|h=heat|g=Aus|f=ohne|n=0|nx=|vh=|m=test', BT2, [], ['Regelung', 'freigegeben']],
  'Status leer (frisch angelegt)': ['', BT2, [], []],
  'BT 2.0 normal': [HP, BT2, ['Regelung über Raumfühler'], ['Raumfühler ausgefallen', 'freigegeben', 'BT heizt nicht', 'Thermostat ausgeschaltet']],
  'BT 2.0 Raumfühler aus': [HP, {...BT2, control_mode: 'sensor_fallback', degraded_mode: true}, ['Ersatz: Heizkörperfühler', 'Raumfühler ausgefallen – regelt mit Heizkörperfühlern'], []],
  'BT 2.0 alle Fühler aus': [HP, {...BT2, control_mode: 'hold'}, ['Ventile gehalten', 'Alle Fühler ausgefallen'], []],
  'BT 2.0 Geräte freigegeben': [HP, {...BT2, devices_released: true, active_overrides: ['devices_released'], heating_blocked_by: 'devices_released'},
                                ['Heizkörper freigegeben – Vorgaben wirken nicht'], ['1 Heizkörper freigegeben']],
  'BT 2.0 ein Heizkörper frei': [HP, {...BT2, released_trvs: ['climate.trv_links'], active_overrides: ['trvs_released']}, ['1 Heizkörper freigegeben'], []],
  'BT 2.0 Außengrenze': [HP, {...BT2, call_for_heat: false, heating_blocked_by: 'no_call_for_heat'}, ['BT heizt nicht: draußen über 18 °C'], []],
  'BT 2.0 Tür offen': [HP, {...BT2, heating_blocked_by: 'door'}, ['Tür offen – Heizpause (BT)'], []],
  'BT 2.0 aus, obwohl Heizen gewünscht': [HP, {...BT2, heating_blocked_by: 'hvac_off'}, ['Thermostat ausgeschaltet'], []],
  'BT 2.0 aus wegen Fensterpause': ['v=1|bt=climate.bt_neu|t=20.1|a=off|p=Komfort|z=22.0|h=off|g=Heizphase · Fensterpause|f=offen|n=0|nx=A20:00|vh=|m=',
                                    {...BT2, heating_blocked_by: 'hvac_off'}, ['Heizpause wegen Fenster'], ['Thermostat ausgeschaltet']],
  'BT 2.0 Lernen pausiert': [HP, {...BT2, learning_paused: true, active_overrides: ['learning_paused']}, ['Lernen pausiert'], []],
  'BT 2.0 Fenstererkennung aus': [HP, {...BT2, active_overrides: ['window_detection_off']}, [], []],
};
// Design „Mobil kompakt“: Hinweise stehen kurz in der Kopfzeile statt in Chips und Detailzeilen
const mobilLagen = {
  'Heizphase (BT 1.x)': [['20,9 °C · Komfort · Heizt'], ['Regelung']],
  'Vorheizen': [['19,1 °C · Komfort · Heizt'], []],
  'Fenster offen + Pause': [['20,1 °C · Komfort · Fenster offen', 'mdi:window-open-variant'], ['Heizt']],
  'Kontaktausfall': [['Fensterkontakt aus'], []],
  'PV-Pause': [['PV heizt'], []],
  'Testbetrieb, BT weg': [['Thermostat fehlt', '· Test'], []],
  'Status leer (frisch angelegt)': [['Status fehlt'], []],
  'BT 2.0 normal': [['· Heizt'], ['Raumfühler aus', 'Heizkörper frei', 'BT aus', 'Thermostat aus', 'mdi:alert-circle-outline']],
  'BT 2.0 Raumfühler aus': [['Raumfühler aus', 'mdi:alert-circle-outline'], []],
  'BT 2.0 alle Fühler aus': [['Fühler aus'], ['Raumfühler aus']],
  'BT 2.0 Geräte freigegeben': [['Heizkörper frei'], []],
  'BT 2.0 ein Heizkörper frei': [['Heizkörper frei'], []],
  'BT 2.0 Außengrenze': [['BT aus über 18 °C'], []],
  'BT 2.0 Tür offen': [['Tür offen'], []],
  'BT 2.0 aus, obwohl Heizen gewünscht': [['Thermostat aus'], []],
  'BT 2.0 aus wegen Fensterpause': [['Fenster offen'], ['Thermostat aus']],
  'BT 2.0 Lernen pausiert': [['· Heizt'], []],
  'BT 2.0 Fenstererkennung aus': [[], []],
};
let n = 0, fehler = 0, pruef = 0, falsch = 0;
for (const [datei, k] of karten) {
  const tpls = sammle(k);
  const st = k.card.cards[0].entity;
  const fensterBt = JSON.stringify(k).includes('window_detection_off');
  const mobil = JSON.stringify(k).includes('23px 22px');
  console.log(`### ${datei.split('/').slice(-2).join('/')}: ${tpls.length} Templates, ${k.card.cards.length} Bausteine (${k.card.cards.map(c => c.type.replace('custom:', '')).join(', ')})`);
  for (const [name, [s, bta, soll0, nicht0]] of Object.entries(lagen)) {
    const [soll, nicht] = mobil ? mobilLagen[name] : [soll0, nicht0];
    const states = basis(st, bta); states[st].state = s;
    const teile = [];
    for (const t of tpls) {
      try { const r = new Function('states', 'entity', 'variables', 'hass', t.trim().slice(3, -3)).call({}, states, states[st], {}, {states}); n++;
            teile.push(String(r).replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()); }
      catch (e) { fehler++; teile.push('FEHLER ' + e.message); }
    }
    const text = teile.join(' ‖ ');
    const fwort = mobil ? 'Fenstererkennung aus' : 'Fenstererkennung im Better Thermostat aus';
    const sollAuch = name === 'BT 2.0 Fenstererkennung aus' && fensterBt ? [fwort] : [];
    const nichtAuch = name === 'BT 2.0 Fenstererkennung aus' && !fensterBt ? [fwort] : [];
    const fehlt = [...soll, ...sollAuch].filter(x => !text.includes(x));
    const zuviel = [...nicht, ...nichtAuch].filter(x => text.includes(x));
    pruef++;
    if (fehlt.length || zuviel.length) { falsch++; console.log(`  ✘ ${name}: fehlt ${JSON.stringify(fehlt)} · unerwartet ${JSON.stringify(zuviel)}`); }
    console.log('  ' + name.padEnd(36) + ' | ' + teile.filter(x => x && !x.startsWith('rgba') && !x.startsWith('linear') && !x.startsWith('#')).join(' ‖ ').slice(0, 260));
  }
  if (mobil) {  // Antippen der Kopfzeile öffnet das Thermostat, das der Status-Helfer nennt (keine Geräte-ID in der Karte)
    const tap = k.card.cards[0].tap_action;
    const lauf = s => { const states = basis(st, BT2); states[st].state = s; return new Function('states', 'entity', 'variables', 'hass', tap.entity.trim().slice(3, -3)).call({}, states, states[st], {}, {states}); };
    pruef++;
    const a = lauf(HP), b = lauf('');
    if (tap.action !== 'more-info' || a !== 'climate.bt_neu' || b !== st) { falsch++; console.log(`  ✘ Antippen: ${tap.action} → ${a} / leer → ${b}`); }
    else console.log('  Antippen der Kopfzeile                 | öffnet ' + a + ' (ohne Status: ' + b + ')');
  }
}
console.log(`\nTemplates ausgeführt: ${n}, Fehler: ${fehler}, Lagen geprüft: ${pruef}, falsch: ${falsch}`);
process.exit(fehler || falsch ? 1 : 0);
