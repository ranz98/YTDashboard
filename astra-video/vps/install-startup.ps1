$ErrorActionPreference = 'Stop'
$runnerDir = $PSScriptRoot
$startupDir = [Environment]::GetFolderPath('Startup')
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut((Join-Path $startupDir 'Astra Runner.lnk'))
$shortcut.TargetPath = Join-Path $runnerDir 'start.cmd'
$shortcut.WorkingDirectory = $runnerDir
$shortcut.WindowStyle = 7
$shortcut.Save()
Write-Host 'Astra will start when this Windows user signs in. Task Scheduler was not changed.'
