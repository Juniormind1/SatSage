# Status von bitcoind + Fulcrum im SatSage Regtest-Lab.
$ErrorActionPreference = 'Continue'
. (Join-Path $PSScriptRoot '_common.ps1')

$btc = Get-ProcFromPidFile $BitcoindPidFile
$ful = Get-ProcFromPidFile $FulcrumPidFile
Write-Host "bitcoind: $(if ($btc) { "PID $($btc.Id)" } else { 'nicht laufend (pidfile)' })"
Write-Host "Fulcrum:  $(if ($ful) { "PID $($ful.Id)" } else { 'nicht laufend (pidfile)' })"
Write-Host "RPC ready:         $(Test-RpcReady)"
Write-Host "Fulcrum TCP ready: $(Test-ElectrumReady)"

if (Test-RpcReady) {
    try {
        $info = & $BitcoinCli "-datadir=$BitcoinData" -regtest getblockchaininfo | ConvertFrom-Json
        Write-Host "chain=$($info.chain) blocks=$($info.blocks) size_on_disk=$($info.size_on_disk)"
    } catch { }
}

if (Test-Path (Join-Path $DataDir '.regtest.env')) {
    Write-Host "Lab-Env: $(Join-Path $DataDir '.regtest.env')"
} else {
    Write-Host "Lab-Env: fehlt (generate_scenarios.py --native)"
}
