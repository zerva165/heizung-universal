# YAML-Syntaxprüfung inkl. HA-Tag !input (wird als String "!input <name>" abgebildet)
require "psych"
ok = true
ARGV.each do |f|
  begin
    doc = Psych.parse_stream(File.read(f, encoding: "UTF-8"))
    inputs_used = []
    doc.each { |n| inputs_used << n.value if n.respond_to?(:tag) && n.tag == "!input" }
    data = Psych.safe_load(File.read(f, encoding: "UTF-8").gsub(/!input\s+([a-z0-9_]+)/, '"!input \1"'), permitted_classes: [], aliases: false)
    msg = "OK   #{File.basename(f)}"
    if data.is_a?(Hash) && data["blueprint"]
      declared = []
      walk = ->(h) { h.each { |k, v| if v.is_a?(Hash) && v["input"].is_a?(Hash) then walk.(v["input"]) else declared << k end } }
      walk.(data["blueprint"]["input"])
      missing = inputs_used.uniq - declared
      unused = declared - inputs_used.uniq
      msg += " | Inputs deklariert=#{declared.size} benutzt=#{inputs_used.uniq.size}"
      msg += " | FEHLEND: #{missing.join(',')}" unless missing.empty?
      msg += " | unbenutzt: #{unused.join(',')}" unless unused.empty?
      ok &&= missing.empty?
      msg += " | triggers=#{data['triggers'].size} actions=#{data['actions'].size}"
    end
    puts msg
  rescue => e
    ok = false
    puts "FEHLER #{File.basename(f)}: #{e.message}"
  end
end
exit(ok ? 0 : 1)
