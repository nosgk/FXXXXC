param(
    [string]$Version = "dev",
    [string]$Root = "."
)

$ErrorActionPreference = "Stop"

$rootPath = (Resolve-Path $Root).Path
$releaseRoot = Join-Path $rootPath "release"
$packageName = "FXXXXC-windows-x64-$Version"
$packageDir = Join-Path $releaseRoot $packageName
$zipPath = Join-Path $releaseRoot "$packageName.zip"

if (Test-Path $packageDir) { Remove-Item -Recurse -Force $packageDir }
if (Test-Path $zipPath) { Remove-Item -Force $zipPath }
New-Item -ItemType Directory -Force -Path $packageDir | Out-Null

$guiRelease = Join-Path $rootPath "gui/build/windows/x64/runner/Release"
if (Test-Path $guiRelease) {
    Copy-Item -Recurse -Force (Join-Path $guiRelease "*") $packageDir
    Write-Host "Copied Flutter GUI from $guiRelease"
} else {
    Write-Host "Flutter GUI release not found; packaging engine only."
}

$engineDist = Join-Path $rootPath "dist/fxxxxc-engine"
if (Test-Path $engineDist) {
    $engineTarget = Join-Path $packageDir "engine"
    New-Item -ItemType Directory -Force -Path $engineTarget | Out-Null
    Copy-Item -Recurse -Force (Join-Path $engineDist "*") $engineTarget
    Write-Host "Copied engine from $engineDist"
} else {
    Write-Warning "Engine dist not found at $engineDist"
}

$resourceSource = Join-Path $rootPath "resource"
if (Test-Path $resourceSource) {
    $resourceTarget = Join-Path $packageDir "engine/resource"
    New-Item -ItemType Directory -Force -Path $resourceTarget | Out-Null
    Copy-Item -Recurse -Force (Join-Path $resourceSource "*") $resourceTarget
}

foreach ($name in @("config_template.ini", "LICENSE", "README.md")) {
    $source = Join-Path $rootPath $name
    if (Test-Path $source) { Copy-Item -Force $source $packageDir }
}

$readme = Join-Path $packageDir "README.txt"
@"
FXXXXC Windows x64 portable build

Version: $Version
Build:   $env:GITHUB_SHA

Run FXXXXC.exe for the desktop client.
The Python engine lives in engine/ and is started by the GUI.

Configuration and logs are stored under %APPDATA%\FXXXXC and
%LOCALAPPDATA%\FXXXXC by the desktop client. The CLI keeps the legacy
current-directory behavior unless --data-dir is supplied.

License: GPL-3.0. See LICENSE.
"@ | Set-Content -Encoding UTF8 $readme

Compress-Archive -Path (Join-Path $packageDir "*") -DestinationPath $zipPath -CompressionLevel Optimal
Write-Host "Created $zipPath"
