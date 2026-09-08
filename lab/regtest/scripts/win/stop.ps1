# Stoppt Fulcrum und bitcoind des SatSage Regtest-Labs.
$ErrorActionPreference = 'Continue'
. (Join-Path $PSScriptRoot '_common.ps1')

# Sauberer Core-Shutdown falls RPC noch geht.
if ((Test-Path $BitcoinCli) -and (Test-Path $BitcoinData)) {
    if (Test-RpcReady) {
        Write-Host "bitcoind stop via RPC..."
        & $BitcoinCli "-datadir=$BitcoinData" -regtest stop 2>$null | Out-Null
        $deadline = (Get-Date).AddSeconds(30)
        while ((Get-Date) -lt $deadline) {
            if (-not (Test-RpcReady)) { break }
            Start-Sleep -Milliseconds 400
        }
    }
}

Stop-PidFileProcess -PidFile $FulcrumPidFile -Name 'Fulcrum'
Stop-PidFileProcess -PidFile $BitcoindPidFile -Name 'bitcoind'

# Nachbrenner: nur Lab-Binaries
Get-Process -Name Fulcrum -ErrorAction SilentlyContinue | Where-Object {
    try { $_.Path -eq $FulcrumExe } catch { $false }
} | ForEach-Object {
    Write-Host "Force-Stop Fulcrum PID $($_.Id)"
    Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
}
Get-Process -Name bitcoind -ErrorAction SilentlyContinue | Where-Object {
    try { $_.Path -eq $Bitcoind } catch { $false }
} | ForEach-Object {
    Write-Host "Force-Stop bitcoind PID $($_.Id)"
    Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
}

Write-Host "Lab gestoppt. Daten bleiben unter $DataDir"
