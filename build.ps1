param(
    [string]$Wix = 'wix',
    [string]$Version = '1.2.0',
    [string]$Out = (Join-Path $PSScriptRoot 'dist')
)
$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$build = (New-Item -ItemType Directory -Force (Join-Path $Out 'build')).FullName
$dest = (Resolve-Path $Out).Path
$base = & $python -c "import sys; print(sys.base_prefix)"
$site = Join-Path $PSScriptRoot '.venv\Lib\site-packages'
$notices = Join-Path $build 'Notices.txt'
$licenses = @(
    (Join-Path $base 'LICENSE.txt'),
    (Join-Path $base 'tcl\tk8.6\license.terms'),
    "$site\pillow-*.dist-info\licenses\LICENSE",
    "$site\pywin32-*.dist-info\licenses\win32\License.txt",
    "$site\pyinstaller-*.dist-info\licenses\COPYING.txt"
)
$(foreach ($license in $licenses) { Get-Content -Path $license -Raw }) | Set-Content -LiteralPath $notices -Encoding UTF8
& $python -m PyInstaller --noconfirm --onefile --windowed --name WoWDing --add-data "$PSScriptRoot\Ding;Ding" --specpath $build --workpath "$build\cache" --distpath "$build\app" "$PSScriptRoot\windows.py"
if ($LASTEXITCODE) { throw 'Watcher build failed.' }
& $Wix build -arch x64 -d "Version=$Version" -d "Exe=$build\app\WoWDing.exe" -d "Notices=$notices" -intermediateFolder "$build\msi" -pdbtype none -o "$dest\WoW-Ding.msi" "$PSScriptRoot\package.wxs"
if ($LASTEXITCODE) { throw 'Installer build failed.' }
