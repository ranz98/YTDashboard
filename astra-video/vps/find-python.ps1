param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$probe = "import sys,struct; print(sys.executable); sys.exit(0 if sys.version_info >= (3,10) and struct.calcsize('P')==8 else 1)"
$candidates = [System.Collections.Generic.List[object]]::new()
$existing = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $existing) {
    $candidates.Add(@($existing))
}
if ($env:ASTRA_PYTHON) {
    $candidates.Add(@($env:ASTRA_PYTHON))
}
foreach ($name in @('python', 'python3')) {
    foreach ($command in @(Get-Command $name -All -ErrorAction SilentlyContinue)) {
        # Store aliases can open a Store window instead of running Python.
        if ($command.Source -and $command.Source -notlike '*\Microsoft\WindowsApps\*') {
            $candidates.Add(@($command.Source))
        }
    }
}
$launcher = Get-Command py -ErrorAction SilentlyContinue
if ($launcher) {
    $candidates.Add(@($launcher.Source, '-3'))
    try {
        foreach ($line in @(& $launcher.Source -0p 2>$null)) {
            if ("$line" -match '([A-Za-z]:\\.+?\.exe)\s*$') {
                $candidates.Add(@($Matches[1]))
            }
        }
    } catch { }
}
foreach ($candidate in $candidates) {
    $executable = $candidate[0]
    $arguments = @($candidate | Select-Object -Skip 1)
    try {
        $output = @(& $executable @arguments -c $probe 2>$null)
        if ($LASTEXITCODE -ne 0 -or -not $output) { continue }
        $resolvedPython = "$($output[-1])".Trim()
        Write-Host "Using Python: $resolvedPython"
        & $resolvedPython --version
        if ($CheckOnly) { exit 0 }
        if ($resolvedPython -ine $existing) {
            & $resolvedPython -m venv (Join-Path $PSScriptRoot '.venv')
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        }
        exit 0
    } catch {
        continue
    }
}
Write-Host 'Could not find a working 64-bit Python 3.10 or newer.'
Write-Host 'If Python is in a custom folder, set ASTRA_PYTHON to its python.exe path and run install.cmd again.'
exit 1
