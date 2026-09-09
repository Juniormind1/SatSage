# Startet SatSage-GUI gegen Lab-Env, detached, und verifiziert die Seite.
param(
    [switch]$NoBrowser,
    [switch]$SkipVerify,
    [switch]$HeadedVerify
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_common.ps1')

if (-not (Test-Path (Join-Path $DataDir '.regtest.env'))) {
    throw "Lab-Env fehlt: $(Join-Path $DataDir '.regtest.env') - zuerst start.ps1 und run_scenarios.ps1"
}

New-Item -ItemType Directory -Force -Path (Join-Path $DataDir 'utxo_cache'), (Join-Path $DataDir 'immutable_cache'), $PidDir | Out-Null

# Alte GUI auf 8730 beenden
Get-NetTCPConnection -LocalPort 8730 -ErrorAction SilentlyContinue | ForEach-Object {
    Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
}
Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and ($_.CommandLine -match 'server\.py') } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Milliseconds 800

$py = (& py -3 -c "import sys; print(sys.executable)").Trim()
$repo = (Resolve-Path (Join-Path $LabRoot '..\..')).Path
$session = Join-Path $DataDir 'gui-session.json'
$outLog = Join-Path $DataDir 'gui-server.log'
$errLog = Join-Path $DataDir 'gui-server.err.log'
$urlFile = Join-Path $DataDir 'gui-url.txt'
Remove-Item $session, $outLog, $errLog, $urlFile -Force -ErrorAction SilentlyContinue

$bat = Join-Path $PidDir 'start-gui.bat'
$batBody = @"
@echo off
set PYTHONUNBUFFERED=1
set SATSAGE_SESSION_FILE=$session
cd /d "$repo"
set SANKTION_MAX_HOPS_CAP=100
"$py" server.py --env lab\regtest\.data\.regtest.env --cache-dir lab\regtest\.data\utxo_cache --immutable-cache-dir lab\regtest\.data\immutable_cache --sanctions-dir lab\regtest\.data\sanctioned_cache --no-browser >> "$outLog" 2>> "$errLog"
"@
$utf8 = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText($bat, $batBody, $utf8)

$cmd = "cmd.exe /c `"$bat`""
$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
    CommandLine = $cmd
    CurrentDirectory = $repo
}
if ($r.ReturnValue -ne 0) {
    throw "Win32_Process.Create fehlgeschlagen: ReturnValue=$($r.ReturnValue)"
}
Set-Content -Path (Join-Path $PidDir 'gui-server.pid') -Value $r.ProcessId
Write-Host "GUI-Launcher PID $($r.ProcessId)"

$url = $null
for ($i = 0; $i -lt 90; $i++) {
    Start-Sleep -Milliseconds 400
    if (Test-Path $session) {
        try {
            $j = Get-Content $session -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($j.url) {
                $url = [string]$j.url
                Write-Host "Session pid=$($j.pid)"
                break
            }
        } catch { }
    }
}
if (-not $url) {
    Write-Host "--- gui-server.err.log ---"
    if (Test-Path $errLog) { Get-Content $errLog -Tail 40 }
    throw "GUI-Session nicht erschienen unter $session"
}

Set-Content -Path $urlFile -Value $url -Encoding ASCII
Start-Sleep -Seconds 1
$listen = Get-NetTCPConnection -LocalPort 8730 -State Listen -ErrorAction SilentlyContinue
if (-not $listen) {
    throw "Port 8730 lauscht nicht. Log: $errLog"
}

# API-Smoke mit Token
$token = ($url -split 't=')[-1]
try {
    $req = [System.Net.HttpWebRequest]::Create("http://127.0.0.1:8730/api/config")
    $req.Headers.Add('X-Satsage-Token', $token)
    $req.Timeout = 8000
    $resp = $req.GetResponse()
    $resp.Close()
    Write-Host "API /api/config OK"
} catch {
    throw "API mit Token fehlgeschlagen: $($_.Exception.Message)"
}

if (-not $SkipVerify) {
    Write-Host "Playwright-Verify..."
    $verifyArgs = @((Join-Path $PSScriptRoot 'verify_gui.py'), '--url', $url)
    if ($HeadedVerify) { $verifyArgs += '--headed' }
    & py -3 @verifyArgs
    if ($LASTEXITCODE -ne 0) {
        throw "GUI-Verify fehlgeschlagen (exit $LASTEXITCODE). Screenshot unter lab\regtest\.data\gui-verify\"
    }
}

Write-Host "GUI bereit: $url"
if (-not $NoBrowser) {
    $null = Open-LabBrowser -Url $url
} else {
    Set-Content -Path $urlFile -Value $url -Encoding ASCII
}
Write-Host $url
