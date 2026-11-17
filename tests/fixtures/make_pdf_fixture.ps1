# Rebuilds tests/fixtures/sample_syllabus.pdf from sample_syllabus.html using Microsoft Edge.
# Run from the project root:  powershell -ExecutionPolicy Bypass -File tests\fixtures\make_pdf_fixture.ps1
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$html = Join-Path $here 'sample_syllabus.html'
$pdf = Join-Path $here 'sample_syllabus.pdf'
$edge = @(
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $edge) { throw 'Microsoft Edge not found.' }
$url = 'file:///' + ($html -replace '\\', '/')
& $edge --headless --disable-gpu --no-pdf-header-footer --print-to-pdf-no-header "--print-to-pdf=$pdf" $url | Out-Null
Start-Sleep -Seconds 2
if (-not (Test-Path $pdf)) { throw 'PDF was not created.' }
Write-Output "Wrote $pdf"
