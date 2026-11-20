# Prüft erzeugte Instanzen: bekannter Blueprint-Pfad, nur deklarierte Inputs, alle Pflicht-Inputs gesetzt, Typen plausibel.
require "psych"
def inputs(bp)
  out = {}
  walk = ->(h) { h.each { |k, v| if v.is_a?(Hash) && v["input"].is_a?(Hash) then walk.(v["input"]) else out[k] = v end } }
  walk.(bp["blueprint"]["input"]); out
end
load = ->(f) { Psych.safe_load(File.read(f, encoding: "UTF-8").gsub(/!input\s+([a-z0-9_]+)/, '"!input \1"')) }
base = "blueprints/automation/"
fehler = 0
ARGV.each do |f|
  d = load.(f); ub = d["use_blueprint"]; decl = inputs(load.(base + ub["path"]))
  unknown = ub["input"].keys - decl.keys
  pflicht = decl.select { |_, v| !v.key?("default") }.keys - ub["input"].keys
  typ = ub["input"].select do |k, v|
    s = decl[k] && decl[k]["selector"]; next false unless s
    (s["number"] && !v.is_a?(Numeric)) || (s["boolean"] && ![true, false].include?(v)) ||
      (s["entity"] && (s["entity"]["multiple"] ? !v.is_a?(Array) : !(v.is_a?(String) && v.include?("."))) ) ||
      (s["time"] && !(v.to_s =~ /\A\d\d:\d\d:\d\d\z/))
  end.keys
  ok = unknown.empty? && pflicht.empty? && typ.empty?
  fehler += 1 unless ok
  puts "   #{ok ? 'OK ' : 'ERR'} #{f.split('/')[-2..].join('/')} (#{ub['input'].size} Werte)#{unknown.empty? ? '' : ' unbekannt=' + unknown.join(',')}#{pflicht.empty? ? '' : ' fehlend=' + pflicht.join(',')}#{typ.empty? ? '' : ' Typ?=' + typ.join(',')}"
end
exit(fehler.zero? ? 0 : 1)
