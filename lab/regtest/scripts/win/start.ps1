# Startet portable bitcoind (regtest) + Fulcrum fuer SatSage-Lab.
param(
    [switch]$SkipFulcrum,
    [switch]$NoWait
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_common.ps1')
Assert-Tools
Ensure-LabDirs
Write-BitcoinConf
Write-FulcrumConf

$BitcoindOut = Join-Path $DataDir 'bitcoind.out.log'
$BitcoindErr = Join-Path $DataDir 'bitcoind.err.log'
$FulcrumOut = Join-Path $DataDir 'fulcrum.out.log'
$FulcrumErr = Join-Path $DataDir 'fulcrum.err.log'

# bitcoind
$btcProc = Get-ProcFromPidFile $BitcoindPidFile
if (-not $btcProc) {
    $existing = Get-Process -Name bitcoind -ErrorAction SilentlyContinue | Where-Object {
        try { $_.Path -eq $Bitcoind } catch { $false }
    }
    if ($existing) {
        $existing | Select-Object -First 1 | ForEach-Object {
            Set-Content $BitcoindPidFile $_.Id
            $btcProc = $_
        }
    }
}
if (-not $btcProc) {
    Write-Host "Starte bitcoind (regtest, datadir=$BitcoinData)..."
    foreach ($f in @($BitcoindOut, $BitcoindErr)) {
        if (Test-Path $f) { Remove-Item $f -Force -ErrorAction SilentlyContinue }
    }
    $p = Start-Process -FilePath $Bitcoind `
        -ArgumentList @("-datadir=$BitcoinData", "-conf=$BitcoinConf", "-regtest") `
        -RedirectStandardOutput $BitcoindOut `
        -RedirectStandardError $BitcoindErr `
        -WindowStyle Hidden `
        -PassThru
    Set-Content -Path $BitcoindPidFile -Value $p.Id
    Write-Host "  PID $($p.Id); debug: $BitcoinData\regtest\debug.log"
} else {
    Write-Host "bitcoind laeuft bereits (PID $($btcProc.Id))"
}

if (-not $NoWait) {
    Write-Host "Warte auf RPC 127.0.0.1:$RpcPort ..."
    if (-not (Wait-RpcReady -TimeoutSec 90)) {
        Write-Host "--- bitcoind.err.log ---"
        if (Test-Path $BitcoindErr) { Get-Content $BitcoindErr -Tail 40 }
        $dbg = Join-Path $BitcoinData 'regtest\debug.log'
        if (Test-Path $dbg) { Write-Host "--- debug.log ---"; Get-Content $dbg -Tail 40 }
        throw "bitcoind RPC nicht erreichbar."
    }
    $info = & $BitcoinCli "-datadir=$BitcoinData" -regtest getblockchaininfo | ConvertFrom-Json
    Write-Host "  chain=$($info.chain) blocks=$($info.blocks)"
}

# Fulcrum wartet bei Tip 0 ewig auf "headers download". Ein Genesis-Block reicht.
function Ensure-BootstrapBlock {
    $count = [int](& $BitcoinCli "-datadir=$BitcoinData" -regtest getblockcount)
    if ($count -gt 0) { return }
    Write-Host "Mine Bootstrap-Block (Fulcrum braucht Tip > 0)..."
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'SilentlyContinue'
    & $BitcoinCli "-datadir=$BitcoinData" -regtest loadwallet "lab-bootstrap" 1>$null 2>$null
    if ($LASTEXITCODE -ne 0) {
        & $BitcoinCli "-datadir=$BitcoinData" -regtest createwallet "lab-bootstrap" 1>$null 2>$null
    }
    $ErrorActionPreference = $prev
    $addr = & $BitcoinCli "-datadir=$BitcoinData" -regtest "-rpcwallet=lab-bootstrap" getnewaddress
    & $BitcoinCli "-datadir=$BitcoinData" -regtest "-rpcwallet=lab-bootstrap" generatetoaddress 1 $addr | Out-Null
    $count = [int](& $BitcoinCli "-datadir=$BitcoinData" -regtest getblockcount)
    Write-Host "  blocks=$count"
}

function Reset-FulcrumIndexIfStale {
    # Nach Chain-Wipe (bitcoind tip klein, Fulcrum-DB noch alt) crasht Fulcrum mit
    # "Failed to rewind". Index dann neu aufbauen.
    if (-not (Test-Path $FulcrumData)) { return }
    $tip = 0
    try { $tip = [int](& $BitcoinCli "-datadir=$BitcoinData" -regtest getblockcount) } catch { return }
    $marker = Join-Path $FulcrumData '.lab_btc_tip'
    $prev = -1
    if (Test-Path $marker) {
        [void][int]::TryParse((Get-Content $marker -Raw).Trim(), [ref]$prev)
    }
    $hasDb = (Get-ChildItem $FulcrumData -Force -ErrorAction SilentlyContinue | Where-Object { $_.Name -ne '.lab_btc_tip' } | Measure-Object).Count -gt 0
    if ($hasDb -and $tip -lt $prev) {
        Write-Host "Fulcrum-Index veraltet (DB tip-marker=$prev, bitcoind=$tip) - Index loeschen..."
        Get-ChildItem $FulcrumData -Force | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    }
    Set-Content -Path $marker -Value $tip -Encoding ASCII
}

if (-not $SkipFulcrum) {
    Ensure-BootstrapBlock
    Reset-FulcrumIndexIfStale

    $fulProc = Get-ProcFromPidFile $FulcrumPidFile
    if (-not $fulProc) {
        $existingF = Get-Process -Name Fulcrum -ErrorAction SilentlyContinue | Where-Object {
            try { $_.Path -eq $FulcrumExe } catch { $false }
        }
        if ($existingF) {
            $existingF | Select-Object -First 1 | ForEach-Object {
                Set-Content $FulcrumPidFile $_.Id
                $fulProc = $_
            }
        }
    }
    if (-not $fulProc) {
        Write-Host "Starte Fulcrum (Protokoll-Port 127.0.0.1:$ElectrumPort)..."
        foreach ($f in @($FulcrumOut, $FulcrumErr)) {
            if (Test-Path $f) { Remove-Item $f -Force -ErrorAction SilentlyContinue }
        }
        $p2 = Start-Process -FilePath $FulcrumExe `
            -ArgumentList @($FulcrumConf) `
            -RedirectStandardOutput $FulcrumOut `
            -RedirectStandardError $FulcrumErr `
            -WindowStyle Hidden `
            -PassThru
        Set-Content -Path $FulcrumPidFile -Value $p2.Id
        Write-Host "  PID $($p2.Id); log: $FulcrumOut / $FulcrumErr"
    } else {
        Write-Host "Fulcrum laeuft bereits (PID $($fulProc.Id))"
    }

    if (-not $NoWait) {
        Write-Host "Warte auf Fulcrum-TCP 127.0.0.1:$ElectrumPort ..."
        if (-not (Wait-ElectrumReady -TimeoutSec 180)) {
            Write-Host "WARNUNG: Fulcrum-Port noch nicht offen." -ForegroundColor Yellow
            if (Test-Path $FulcrumErr) { Get-Content $FulcrumErr -Tail 30 }
            if (Test-Path $FulcrumOut) { Get-Content $FulcrumOut -Tail 40 }
        } else {
            Write-Host "  Fulcrum bereit (Electrum-Protokoll)."
            try {
                $tip = [int](& $BitcoinCli "-datadir=$BitcoinData" -regtest getblockcount)
                Set-Content -Path (Join-Path $FulcrumData '.lab_btc_tip') -Value $tip -Encoding ASCII
            } catch { }
        }
    }
}

Write-Host ""
Write-Host "Regtest-Lab laeuft:"
Write-Host "  RPC:      127.0.0.1:$RpcPort  user=$RpcUser"
Write-Host "  Fulcrum:  127.0.0.1:$ElectrumPort (Electrum-Protokoll, SSL aus)"
Write-Host "  Komplett (Szenarien+GUI+Browser): .\scripts\win\start_lab.ps1"
Write-Host "  Nur Szenarien: .\scripts\win\run_scenarios.ps1"
Write-Host "  Nur GUI:       .\scripts\win\start_gui.ps1"
Write-Host "  Stop:          .\scripts\win\stop_lab.ps1"
