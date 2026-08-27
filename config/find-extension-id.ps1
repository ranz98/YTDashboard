# Prints the Chrome extension ID for an unpacked extension loaded from -Base.
# Nothing else goes to stdout, so run.bat can read the first line as the ID.
#
# A separate file rather than an inline -Command: the query is full of
# parentheses, and inline PowerShell inside a batch for /f (...) block gets
# cut short at the first one.

param(
  [Parameter(Mandatory = $true)][string]$Base,
  [Parameter(Mandatory = $true)][string]$ProfileDir
)

$ErrorActionPreference = 'SilentlyContinue'
$want = $Base.TrimEnd('\')

foreach ($file in @('Secure Preferences', 'Preferences')) {
  $path = Join-Path (Join-Path $ProfileDir 'Default') $file
  if (-not (Test-Path -LiteralPath $path)) { continue }

  try {
    $json = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
  } catch {
    continue
  }

  $settings = $json.extensions.settings
  if (-not $settings) { continue }

  foreach ($name in $settings.PSObject.Properties.Name) {
    $extPath = $settings.$name.path
    if ($extPath -and ($extPath.TrimEnd('\') -ieq $want)) {
      Write-Output $name
      exit 0
    }
  }
}

exit 1
