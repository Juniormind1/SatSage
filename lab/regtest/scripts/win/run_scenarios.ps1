# Erzeugt Lab-Wallets/Szenarien gegen den laufenden portable bitcoind.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '_common.ps1')
Assert-Tools
if (-not (Test-RpcReady)) {
    throw "bitcoind RPC nicht erreichbar. Zuerst .\scripts\win\start.ps1"
}
$env:BITCOIN_CLI = $BitcoinCli
$env:SATSAGE_LAB_NATIVE = '1'
$env:RPCUSER = $RpcUser
$env:RPCPASSWORD = $RpcPassword
$env:RPCPORT = $RpcPort
$script = Join-Path $LabRoot 'scripts\generate_scenarios.py'
Write-Host "BITCOIN_CLI=$BitcoinCli"
& py -3 $script --native
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$sanc = Join-Path $LabRoot 'scripts\generate_sanctions_scenarios.py'
Write-Host "Sanction hop scenarios…"
& py -3 $sanc --native
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "Env: $(Join-Path $DataDir '.regtest.env')"
Write-Host "Sanctions: $(Join-Path $DataDir 'sanctioned_cache')"
