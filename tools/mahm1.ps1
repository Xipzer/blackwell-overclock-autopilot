# One sample of MSI Afterburner's live data: "clockMHz voltageV powerW usage%".
# Needs Afterburner running. The voltage only appears after enabling the voltage graph (Settings, Monitoring).
# Assumes the first GPU; change GPU1 to GPU2 for a second card. With a single GPU (no iGPU) Afterburner drops the
# "GPU1 " prefix, so each value falls back to the plain name ("Core clock", "GPU voltage", "Power", "GPU usage").
$m = [System.IO.MemoryMappedFiles.MemoryMappedFile]::OpenExisting('MAHMSharedMemory')
$v = $m.CreateViewAccessor(); $hs = $v.ReadUInt32(8); $ne = $v.ReadUInt32(12); $es = $v.ReadUInt32(16); $r = @{}
for ($i = 0; $i -lt $ne; $i++) { $o = $hs + $i * $es; $b = New-Object byte[] 260; [void]$v.ReadArray($o, $b, 0, 260); $r[([Text.Encoding]::ASCII.GetString($b)).Split([char]0)[0]] = $v.ReadSingle($o + 1300) }
function G($a, $b) { if ($r.ContainsKey($a)) { $r[$a] } else { $r[$b] } }
'{0} {1:F3} {2:F1} {3}' -f (G 'GPU1 core clock' 'Core clock'), (G 'GPU1 voltage' 'GPU voltage'), (G 'GPU1 power' 'Power'), (G 'GPU1 usage' 'GPU usage')
