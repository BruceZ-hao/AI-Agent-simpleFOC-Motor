param(
    [string]$Port    = 'COM6',
    [int]   $Baud    = 115200,
    [float] $Limit   = 3.0,
    [float] $Speed   = 0.5,
    [int]   $Samples = 14
)

# One-shot spin check for the SimpleFOC STAGE 2 firmware.
# Sends L/T over the Arduino Commander interface, then repeatedly sends D
# and unwraps the AS5600 angle to decide whether the shaft really spins.
#
# IMPORTANT: close the Arduino IDE Serial Monitor / Plotter first.
# Windows allows only one process to hold a COM port.

$ErrorActionPreference = 'Stop'

$p = New-Object System.IO.Ports.SerialPort
$p.PortName      = $Port
$p.BaudRate      = $Baud
$p.Parity        = [System.IO.Ports.Parity]::None
$p.DataBits      = 8
$p.StopBits      = [System.IO.Ports.StopBits]::One
$p.DtrEnable     = $false
$p.RtsEnable     = $false
$p.ReadTimeout   = 500
$p.WriteTimeout  = 500

try { $p.Open() }
catch {
    Write-Host "FAILED to open $Port"
    Write-Host "Reason: $($_.Exception.Message)"
    Write-Host ""
    Write-Host "Close the Arduino IDE Serial Monitor / Serial Plotter, then run this again."
    exit 1
}

Write-Host "Opened $Port @ $Baud"
Start-Sleep -Milliseconds 300
$p.DiscardInBuffer()

function Send-Cmd([string]$cmd) {
    $p.Write($cmd + "`n")
    Start-Sleep -Milliseconds 120
}

function Fmt([float]$v) {
    return $v.ToString('0.###', [System.Globalization.CultureInfo]::InvariantCulture)
}

Send-Cmd 'T0'
Send-Cmd ('L' + (Fmt $Limit))
Send-Cmd ('T' + (Fmt $Speed))
Write-Host ("Sent: T0, L{0}, T{1}" -f (Fmt $Limit), (Fmt $Speed))
Write-Host "Sampling AS5600 angle via D command..."
Write-Host ""

$buf = ''
for ($i = 0; $i -lt $Samples; $i++) {
    $p.Write("D`n")
    Start-Sleep -Milliseconds 300
    $buf += $p.ReadExisting()
}

$angles = New-Object System.Collections.Generic.List[float]
foreach ($m in [regex]::Matches($buf, 'angle=([0-9]+\.[0-9]+)')) {
    $v = [float]::Parse($m.Groups[1].Value, [System.Globalization.CultureInfo]::InvariantCulture)
    $angles.Add($v)
}

if ($angles.Count -eq 0) {
    Write-Host "No angle data received. Check USB CDC / AS5600 wiring."
    Write-Host $buf
    Send-Cmd 'T0'
    $p.Close()
    exit 1
}

$total = 0.0
for ($i = 1; $i -lt $angles.Count; $i++) {
    $d = $angles[$i] - $angles[$i - 1]
    if ($d -gt  3.14159) { $d -= 6.2831853 }
    if ($d -lt -3.14159) { $d += 6.2831853 }
    $total += $d
    Write-Host ("  sample {0,2}: angle={1,9:N4}   delta={2,9:N4}" -f $i, $angles[$i], $d)
}

Write-Host ""
Write-Host ("Total unwrapped angle change: {0:N3} rad" -f $total)

if ($Speed -eq 0) {
    Write-Host "Motor stopped (T0)."
    Send-Cmd 'T0'
} elseif ([Math]::Abs($total) -gt 0.8) {
    Write-Host "VERDICT: SPINNING - the shaft follows the rotating field."
    Write-Host "It keeps turning at T$Speed . Send T0 in the Serial Monitor (or run with -Speed 0) to stop."
    Write-Host "Do not leave it stalled for a long time; MP6536 gets hot."
} else {
    Write-Host "VERDICT: NOT MOVING (or losing steps). Sending T0 for safety."
    Send-Cmd 'T0'
    Write-Host ""
    Write-Host "Check before retrying:"
    Write-Host "  1) 12V external supply on driver VIN/VM, measured with a multimeter"
    Write-Host "  2) FAULT LED off (overcurrent / UVLO / overtemp)"
    Write-Host "  3) all three motor phases M1/M2/M3 firmly connected"
    Write-Host "  4) common GND between ESP32-S3, driver and AS5600"
    Write-Host "  5) measure phase resistance: any two phases / 2; if far below 10 ohm, start from L1"
    Write-Host "Then retry:  .\spin_test.bat  -Limit 4 -Speed 0.5"
}

$p.Close()
