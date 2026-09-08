# Ein-Kommando-Start: bitcoind + Fulcrum + Szenarien (bei Bedarf) + GUI + Browser.
param(
    [switch]$SkipScenarios,
    [switch]$SkipGui,
    [switch]$NoBrowser,
    [switch]$SkipVerify,
    [switch]$ForceScenarios
)
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot

. (Join-Path $here '_common.ps1')

# Fulcrum erst NACH den Szenarien indexieren (sonst Index hinter Chain / Crash).
Write-Host '=== 1/5 bitcoind (ohne Fulcrum) ==='
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $here 'start.ps1') -SkipFulcrum
if ($LASTEXITCODE -ne 0) { throw "start.ps1 fehlgeschlagen (exit $LASTEXITCODE)" }

$envFile = Join-Path $DataDir '.regtest.env'
$needScenarios = $ForceScenarios -or (-not (Test-Path $envFile))
if (-not $needScenarios -and -not $SkipScenarios) {
    try {
        $blocks = [int](& $BitcoinCli "-datadir=$BitcoinData" -regtest getblockcount)
        if ($blocks -lt 50) { $needScenarios = $true }
    } catch {
        $needScenarios = $true
    }
}

if ($needScenarios -and -not $SkipScenarios) {
    Write-Host '=== 2/5 Szenarien ==='
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $here 'run_scenarios.ps1')
    if ($LASTEXITCODE -ne 0) { throw "run_scenarios.ps1 fehlgeschlagen (exit $LASTEXITCODE)" }
} else {
    Write-Host '=== 2/5 Szenarien uebersprungen (Env/Chain vorhanden) ==='
}

Write-Host '=== 3/5 Fulcrum (Index nach Szenarien) ==='
# Fulcrum-Index an aktuelle Chain anbinden (start.ps1 startet Fulcrum mit).
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $here 'start.ps1')
if ($LASTEXITCODE -ne 0) { throw "Fulcrum-Start fehlgeschlagen (exit $LASTEXITCODE)" }

if ($SkipGui) {
    Write-Host '=== GUI uebersprungen (-SkipGui) ==='
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $here 'status.ps1')
    exit 0
}

Write-Host '=== 4/5 SatSage-GUI ==='
$guiArgs = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $here 'start_gui.ps1'), '-NoBrowser')
if ($SkipVerify) { $guiArgs += '-SkipVerify' }
& powershell @guiArgs
if ($LASTEXITCODE -ne 0) { throw "start_gui.ps1 fehlgeschlagen (exit $LASTEXITCODE)" }

$urlFile = Join-Path $DataDir 'gui-url.txt'
if (-not (Test-Path $urlFile)) { throw "gui-url.txt fehlt nach start_gui" }
$url = (Get-Content $urlFile -Raw).Trim()
if (-not $url) { throw 'GUI-URL leer' }

Write-Host '=== 5/5 Browser ==='
if ($NoBrowser) {
    Write-Host "Browser uebersprungen. URL: $url"
} else {
    $name = Open-LabBrowser -Url $url
    Write-Host "Browser: $name"
}

Write-Host ''
Write-Host 'Lab vollstaendig gestartet.'
Write-Host "  URL (mit Token): $url"
Write-Host '  Stop: .\scripts\win\stop_lab.ps1  bzw. stop.ps1 + GUI manuell'
Write-Host $url
