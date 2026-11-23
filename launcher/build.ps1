# Rebuild the official KBMTI launcher from KBMTILauncher.cs and x.bat.
# Requires Windows PowerShell and the .NET Framework 4.x C# compiler.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$bat = Join-Path $root "x.bat"
$source = Join-Path $PSScriptRoot "KBMTILauncher.cs"
$integrity = Join-Path $PSScriptRoot "LauncherIntegrity.cs"
$csc = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
$output = Join-Path $root "KBMTI-RAW-TEST.exe"
$icon = Join-Path $root "kbmti\assets\icon.ico"

if (-not (Test-Path $bat)) { throw "x.bat was not found at $bat" }
if (-not (Test-Path $csc)) { throw ".NET Framework C# compiler was not found at $csc" }

$hash = (Get-FileHash -LiteralPath $bat -Algorithm SHA256).Hash.ToLowerInvariant()
@"
namespace KBMTI.Launcher
{
    internal static class LauncherIntegrity
    {
        internal const string XBatSha256 = "$hash";
    }
}
"@ | Set-Content -LiteralPath $integrity -Encoding UTF8

& $csc /nologo /target:exe /platform:x64 /optimize+ "/win32icon:$icon" "/out:$output" $source $integrity
if ($LASTEXITCODE -ne 0) { throw "C# launcher build failed with exit code $LASTEXITCODE" }
Write-Host "Built $output"
Write-Host "x.bat SHA-256: $hash"
