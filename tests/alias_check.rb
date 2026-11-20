# Prüft, dass jeder Trigger, jede Bedingung und jede Aktion (rekursiv) einen alias besitzt.
require "psych"
$fehlend = []
def check_cond(c, pfad)
  return unless c.is_a?(Hash)
  $fehlend << pfad unless c["alias"]
  (c["conditions"] || []).each_with_index { |x, i| check_cond(x, "#{pfad}.conditions[#{i}]") } if c["conditions"].is_a?(Array)
end
def check_actions(liste, pfad)
  return unless liste.is_a?(Array)
  liste.each_with_index do |a, i|
    p = "#{pfad}[#{i}]"
    next unless a.is_a?(Hash)
    $fehlend << p unless a["alias"]
    if a.key?("condition") then check_cond(a, p) end
    (a["if"] || []).each_with_index { |x, j| check_cond(x, "#{p}.if[#{j}]") } if a["if"].is_a?(Array)
    check_actions(a["then"], "#{p}.then"); check_actions(a["else"], "#{p}.else")
    check_actions(a["sequence"], "#{p}.sequence"); check_actions(a["default"], "#{p}.default")
    (a["choose"] || []).each_with_index do |b, j|
      $fehlend << "#{p}.choose[#{j}]" unless b["alias"]
      (b["conditions"] || []).each_with_index { |x, k| check_cond(x, "#{p}.choose[#{j}].conditions[#{k}]") }
      check_actions(b["sequence"], "#{p}.choose[#{j}].sequence")
    end
    (a["parallel"] || []).each_with_index { |b, j| check_actions(b.is_a?(Array) ? b : [b], "#{p}.parallel[#{j}]") } if a["parallel"].is_a?(Array)
    check_actions(a.dig("repeat", "sequence"), "#{p}.repeat.sequence") if a["repeat"].is_a?(Hash)
  end
end
ok = true
ARGV.each do |f|
  $fehlend = []
  d = Psych.safe_load(File.read(f, encoding: "UTF-8").gsub(/!input\s+([a-z0-9_]+)/, '"!input \1"'))
  (d["triggers"] || []).each_with_index { |t, i| $fehlend << "triggers[#{i}]" unless t["alias"] }
  (d["conditions"] || []).each_with_index { |x, i| check_cond(x, "conditions[#{i}]") }
  check_actions(d["actions"] || d["sequence"], "actions")
  ok &&= $fehlend.empty?
  puts "#{$fehlend.empty? ? 'OK ' : 'ERR'} #{File.basename(f)}#{$fehlend.empty? ? '' : ' fehlende Aliasse: ' + $fehlend.first(15).join(', ')}"
end
exit(ok ? 0 : 1)
