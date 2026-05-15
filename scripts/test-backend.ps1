$ErrorActionPreference = "Stop"

Push-Location "$PSScriptRoot\..\apps\backend"
try {
  python -m pytest
}
finally {
  Pop-Location
}
