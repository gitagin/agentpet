# Regenerate the committed OpenAPI snapshot (apps/backend/openapi.json).
# Run whenever backend routes or response models change; the snapshot test
# (apps/backend/tests/test_openapi_snapshot.py) fails until you do. Then run
# `npm run generate:api-contracts` from apps/desktop so downstream artifacts
# carry the same OpenAPI snapshot.
$ErrorActionPreference = "Stop"

Push-Location (Join-Path $PSScriptRoot "..\apps\backend")
try {
    python -m app.openapi_export
}
finally {
    Pop-Location
}
