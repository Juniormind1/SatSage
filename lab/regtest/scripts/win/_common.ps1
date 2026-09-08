# Gemeinsame Pfade/Defaults fuer SatSage Regtest-Lab (Windows portable).
$ErrorActionPreference = 'Stop'

$LabRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$ToolsDir = Join-Path $LabRoot '.tools'
$DataDir = Join-Path $LabRoot '.data'
$BitcoinData = Join-Path $DataDir 'bitcoin'
$FulcrumData = Join-Path $DataDir 'fulcrum'
$BitcoinBin = Join-Path $ToolsDir 'bitcoin\bin'
$FulcrumBin = Join-Path $ToolsDir 'fulcrum'
$Bitcoind = Join-Path $BitcoinBin 'bitcoind.exe'
$BitcoinCli = Join-Path $BitcoinBin 'bitcoin-cli.exe'
$FulcrumExe = Join-Path $FulcrumBin 'Fulcrum.exe'
$BitcoinConf = Join-Path $BitcoinData 'bitcoin.conf'
$FulcrumConf = Join-Path $DataDir 'fulcrum.conf'
$PidDir = Join-Path $DataDir 'run'
$BitcoindPidFile = Join-Path $PidDir 'bitcoind.pid'
$FulcrumPidFile = Join-Path $PidDir 'fulcrum.pid'
$BitcoindLog = Join-Path $DataDir 'bitcoind.log'
$FulcrumLog = Join-Path $DataDir 'fulcrum.log'

$RpcUser = if ($env:RPCUSER) { $env:RPCUSER } else { 'bitcoin' }
$RpcPassword = if ($env:RPCPASSWORD) { $env:RPCPASSWORD } else { 'secret' }
$RpcPort = if ($env:RPCPORT) { $env:RPCPORT } else { '18443' }
$P2pPort = if ($env:P2PPORT) { $env:P2PPORT } else { '18444' }
$ElectrumPort = if ($env:ELECTRUM_PORT) { $env:ELECTRUM_PORT } else { '50001' }

function Ensure-LabDirs {
    New-Item -ItemType Directory -Force -Path $BitcoinData, $FulcrumData, $PidDir | Out-Null
}

function Assert-Tools {
    if (-not (Test-Path $Bitcoind)) {
        throw "bitcoind fehlt: $Bitcoind - bitte scripts\win\setup_tools.ps1 ausfuehren."
    }
    if (-not (Test-Path $BitcoinCli)) {
        throw "bitcoin-cli fehlt: $BitcoinCli"
    }
    if (-not (Test-Path $FulcrumExe)) {
        throw "Fulcrum fehlt: $FulcrumExe - bitte scripts\win\setup_tools.ps1 ausfuehren."
    }
}

function Write-BitcoinConf {
    # Core >=0.17: netzspezifische Keys nur in [regtest] (sonst Start-Abbruch).
    $lines = @(
        '# SatSage Regtest-Lab - lokal, nicht committen.'
        'regtest=1'
        'server=1'
        'txindex=1'
        'blockfilterindex=1'
        'fallbackfee=0.0001'
        "rpcuser=$RpcUser"
        "rpcpassword=$RpcPassword"
        'rpcallowip=127.0.0.1'
        ''
        '[regtest]'
        'listen=1'
        'bind=127.0.0.1'
        "port=$P2pPort"
        'dnsseed=0'
        'fixedseeds=0'
        'upnp=0'
        'natpmp=0'
        'discover=0'
        'listenonion=0'
        "rpcport=$RpcPort"
        'rpcbind=127.0.0.1'
        'zmqpubhashblock=tcp://127.0.0.1:28332'
        'zmqpubrawtx=tcp://127.0.0.1:28333'
    )
    $utf8 = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllLines($BitcoinConf, $lines, $utf8)
}

function Write-FulcrumConf {
    $dataFs = ($FulcrumData -replace '\\', '/')
    $lines = @(
        '# SatSage Regtest-Lab Fulcrum - lokal, nicht committen.'
        "datadir = $dataFs"
        "bitcoind = 127.0.0.1:$RpcPort"
        "rpcuser = $RpcUser"
        "rpcpassword = $RpcPassword"
        "tcp = 127.0.0.1:$ElectrumPort"
        'peering = false'
        'announce = false'
    )
    $utf8 = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllLines($FulcrumConf, $lines, $utf8)
}

function Test-RpcReady {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'SilentlyContinue'
    try {
        & $BitcoinCli "-datadir=$BitcoinData" -regtest getblockchaininfo 1>$null 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    } finally {
        $ErrorActionPreference = $prev
    }
}

function Wait-RpcReady {
    param([int]$TimeoutSec = 60)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-RpcReady) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Test-ElectrumReady {
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $iar = $client.BeginConnect('127.0.0.1', [int]$ElectrumPort, $null, $null)
        $ok = $iar.AsyncWaitHandle.WaitOne(500)
        if ($ok -and $client.Connected) {
            $client.Close()
            return $true
        }
        $client.Close()
    } catch { }
    return $false
}

function Wait-ElectrumReady {
    param([int]$TimeoutSec = 120)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-ElectrumReady) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Get-ProcFromPidFile {
    param([string]$PidFile)
    if (-not (Test-Path $PidFile)) { return $null }
    $raw = (Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    if (-not $raw) { return $null }
    $procId = 0
    if (-not [int]::TryParse($raw.Trim(), [ref]$procId)) { return $null }
    try { return Get-Process -Id $procId -ErrorAction Stop } catch { return $null }
}

function Stop-PidFileProcess {
    param([string]$PidFile, [string]$Name)
    $proc = Get-ProcFromPidFile $PidFile
    if ($proc) {
        Write-Host "Stoppe $Name (PID $($proc.Id))..."
        try {
            $proc.CloseMainWindow() | Out-Null
        } catch { }
        Start-Sleep -Milliseconds 800
        if (-not $proc.HasExited) {
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        }
    }
    if (Test-Path $PidFile) { Remove-Item $PidFile -Force -ErrorAction SilentlyContinue }
}

function Get-LabBrowser {
    # Reihenfolge: Edge (Windows-Standard), Chrome, Firefox, sonst Shell-Default.
    $kandidaten = @(
        @{ Name = 'Edge'; Path = "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe"; Args = @('--new-window') },
        @{ Name = 'Edge'; Path = "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"; Args = @('--new-window') },
        @{ Name = 'Chrome'; Path = "$env:ProgramFiles\Google\Chrome\Application\chrome.exe"; Args = @('--new-window') },
        @{ Name = 'Chrome'; Path = "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"; Args = @('--new-window') },
        @{ Name = 'Firefox'; Path = "$env:ProgramFiles\Mozilla Firefox\firefox.exe"; Args = @('-new-window') },
        @{ Name = 'Firefox'; Path = "${env:ProgramFiles(x86)}\Mozilla Firefox\firefox.exe"; Args = @('-new-window') },
        @{ Name = 'Firefox'; Path = "$env:LOCALAPPDATA\Mozilla Firefox\firefox.exe"; Args = @('-new-window') }
    )
    foreach ($k in $kandidaten) {
        if ($k.Path -and (Test-Path -LiteralPath $k.Path)) {
            return $k
        }
    }
    return $null
}

function Open-LabBrowser {
    param(
        [Parameter(Mandatory = $true)][string]$Url
    )
    if (-not $Url) { throw 'Open-LabBrowser: URL fehlt' }
    $urlFile = Join-Path $DataDir 'gui-url.txt'
    Set-Content -Path $urlFile -Value $Url -Encoding ASCII

    $browser = Get-LabBrowser
    if ($browser) {
        Write-Host "Oeffne $($browser.Name): $Url"
        $argList = @($browser.Args) + @($Url)
        Start-Process -FilePath $browser.Path -ArgumentList $argList | Out-Null
        return $browser.Name
    }
    Write-Host "Kein Edge/Chrome/Firefox gefunden - Shell-Default: $Url"
    Start-Process $Url | Out-Null
    return 'default'
}
