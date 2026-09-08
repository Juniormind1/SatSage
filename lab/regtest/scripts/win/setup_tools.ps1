# Laedt portable Bitcoin Core + Fulcrum nach lab/regtest/.tools/ (User-Scope, kein Admin).
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
. (Join-Path $PSScriptRoot '_common.ps1')

New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null

$btcUrlDefault = 'https://bitcoincore.org/bin/bitcoin-core-28.1/bitcoin-28.1-win64.zip'
$fulUrlDefault = 'https://github.com/cculianu/Fulcrum/releases/download/v2.1.2/Fulcrum-2.1.2-win64.zip'
$urlFile = Join-Path $ToolsDir 'download-urls.json'
if (Test-Path $urlFile) {
    $urls = Get-Content $urlFile | ConvertFrom-Json
    $btcUrl = if ($urls.bitcoin) { $urls.bitcoin } else { $btcUrlDefault }
    $fulUrl = if ($urls.fulcrum) { $urls.fulcrum } else { $fulUrlDefault }
} else {
    $btcUrl = $btcUrlDefault
    $fulUrl = $fulUrlDefault
}

function Install-Zip {
    param(
        [string]$Url,
        [string]$ZipPath,
        [string]$MarkerPath,
        [scriptblock]$Place
    )
    if (Test-Path $MarkerPath) {
        Write-Host "OK bereits vorhanden: $MarkerPath"
        return
    }
    Write-Host "Download: $Url"
    Invoke-WebRequest -Uri $Url -OutFile $ZipPath -UseBasicParsing
    Write-Host "Entpacken: $ZipPath"
    $tmp = Join-Path $ToolsDir ("extract-" + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    try {
        Expand-Archive -Path $ZipPath -DestinationPath $tmp -Force
        & $Place $tmp
    } finally {
        Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
        Remove-Item $ZipPath -Force -ErrorAction SilentlyContinue
    }
}

Install-Zip -Url $btcUrl -ZipPath (Join-Path $ToolsDir 'bitcoin-win64.zip') -MarkerPath $Bitcoind -Place {
    param($tmp)
    $inner = Get-ChildItem $tmp -Directory | Select-Object -First 1
    if (-not $inner) { throw 'Bitcoin-ZIP-Struktur unerwartet' }
    $dest = Join-Path $ToolsDir 'bitcoin'
    if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
    Move-Item $inner.FullName $dest
}

Install-Zip -Url $fulUrl -ZipPath (Join-Path $ToolsDir 'fulcrum-win64.zip') -MarkerPath $FulcrumExe -Place {
    param($tmp)
    $exe = Get-ChildItem $tmp -Recurse -Filter 'Fulcrum.exe' | Select-Object -First 1
    if (-not $exe) { throw 'Fulcrum.exe nicht im ZIP' }
    $dest = Join-Path $ToolsDir 'fulcrum'
    if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    Copy-Item (Join-Path $exe.DirectoryName '*') $dest -Recurse -Force
}

Write-Host ""
Write-Host "Bitcoin: $Bitcoind"
Write-Host "Fulcrum: $FulcrumExe"
Write-Host "Fertig. Weiter mit: .\scripts\win\start.ps1"
