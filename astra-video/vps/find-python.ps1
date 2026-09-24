param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$probe = "import sys,struct; print(sys.executable); sys.exit(0 if sys.version_info >= (3,10) and struct.calcsize('P')==8 else 1)"
$candidates = [System.Collections.Generic.List[object]]::new()
$existing = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if ($env:ASTRA_PYTHON) {
    $candidates.Add(@($env:ASTRA_PYTHON))
}
 $saved = Join-Path $PSScriptRoot 'data\python-path.txt'
if (Test-Path -LiteralPath $saved) { $candidates.Add(@((Get-Content -LiteralPath $saved -Raw).Trim())) }
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
if (Test-Path -LiteralPath $existing) { $candidates.Add(@($existing)) }
$bestPython = $null
$bestScore = -1
foreach ($candidate in $candidates) {
    $executable = $candidate[0]
    $arguments = @($candidate | Select-Object -Skip 1)
    try {
        $output = @(& $executable @arguments -c $probe 2>$null)
        if ($LASTEXITCODE -ne 0 -or -not $output) { continue }
        $resolvedPython = "$($output[-1])".Trim()
        $scoreText = & $resolvedPython -c "import importlib.util; print(sum(importlib.util.find_spec(n) is not None for n in ['yt_dlp','cv2','numpy','PIL','openai']))" 2>$null
        $score = [int]$scoreText
        if ($score -gt $bestScore) { $bestPython = $resolvedPython; $bestScore = $score }
        if ($env:ASTRA_PYTHON -and $resolvedPython -ieq $env:ASTRA_PYTHON) { break }
    } catch {
        continue
    }
}
if ($bestPython) {
    Write-Host "Using Python: $bestPython ($bestScore of 5 existing packages found)"
    & $bestPython --version
    if (-not $CheckOnly) {
        New-Item -ItemType Directory -Force -Path (Join-Path $PSScriptRoot 'data') | Out-Null
        [IO.File]::WriteAllText($saved, $bestPython)
    }
    exit 0
}
Write-Host 'Could not find a working 64-bit Python 3.10 or newer.'
Write-Host 'If Python is in a custom folder, set ASTRA_PYTHON to its python.exe path and run install.cmd again.'
exit 1
