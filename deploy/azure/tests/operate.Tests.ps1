#requires -Version 7.0
# Offline tests of operate.ps1 against a fake API. No network request is made.
$ErrorActionPreference = 'Stop'
$operate = Join-Path $PSScriptRoot '../operate.ps1'
$parseTokens = $null
$parseErrors = $null
[System.Management.Automation.Language.Parser]::ParseFile($operate, [ref]$parseTokens, [ref]$parseErrors) | Out-Null
if ($parseErrors) { throw ('operate.ps1 does not parse: ' + $parseErrors[0].Message) }

function Reset-FakeService([string]$Mode = 'public') {
    $global:OperateTestMode = $Mode
    $global:OperateTestStarted = [System.Collections.Generic.List[object]]::new()
    $global:OperateTestReviews = [System.Collections.Generic.List[object]]::new()
    $global:OperateTestAnswers = [System.Collections.Generic.Queue[string]]::new()
}

function Invoke-RestMethod {
    param([string]$Uri, [string]$Method = 'Get', [int]$TimeoutSec, [string]$ContentType, [string]$Body)
    $path = $Uri.Substring('https://api.invalid'.Length)
    if ($path -eq '/health') {
        return [pscustomobject]@{
            access_mode = $global:OperateTestMode; version = 'test'
            automation_scheduler_enabled = $true; automation_schedule = 'Every Sunday at midnight (00:00 EAT on Monday)'
            components = [pscustomobject]@{ 'Copilot language model' = 'Healthy · answers questions' }
        }
    }
    if ($path -eq '/operations' -and $Method -eq 'Post') {
        $request = ConvertFrom-Json -InputObject $Body
        $global:OperateTestStarted.Add($request)
        return [pscustomobject]@{ id = 'op-' + $global:OperateTestStarted.Count; title = 'Operation ' + $request.action }
    }
    if ($path -like '/operations/op-*') {
        return [pscustomobject]@{ status = 'complete'; error = $null; messages = @([pscustomobject]@{ text = 'Finished' }) }
    }
    if ($path -eq '/forecasts/latest') {
        $confirmed = $global:OperateTestReviews.Count -gt 0
        return [pscustomobject]@{
            forecast_id = 'w2-2026-10-26-0123abcd'; model_id = 'icpac_week2_catboost_prerefit_v1'
            initialization = [datetime]'2026-10-26'; valid_start = '2026-11-02'; valid_end = '2026-11-08'
            products = [pscustomobject]@{ hybrid = [pscustomobject]@{ status = $(if ($confirmed) { 'available' } else { 'in_progress' }); reason = 'the confirmation' } }
            provenance = [pscustomobject]@{
                realtime_gate = [pscustomobject]@{ required = $true; review = $null }
                input_checks = @(
                    [pscustomobject]@{ check = 'Members'; status = 'passed'; detail = '10 perturbed members' },
                    [pscustomobject]@{ check = 'Grid'; status = 'passed'; detail = '0.25 degree' }
                )
            }
        }
    }
    if ($path -like '/models/*/realtime-review' -and $Method -eq 'Post') {
        $global:OperateTestReviews.Add((ConvertFrom-Json -InputObject $Body))
        return [pscustomobject]@{}
    }
    throw ('Unexpected request ' + $Method + ' ' + $path)
}
function Start-Sleep { }
function Read-Host([string]$Prompt) { return $global:OperateTestAnswers.Dequeue() }

# Everything runs in order, and a typed CONFIRM records the review and runs the forecast again.
Reset-FakeService
$global:OperateTestAnswers.Enqueue('CONFIRM')
$global:OperateTestAnswers.Enqueue('Checked the members and grid.')
& $operate -ApiUrl 'https://api.invalid' -Reviewer 'Joe254h' | Out-Null
$actions = @($global:OperateTestStarted | ForEach-Object action) -join ','
if ($actions -ne 'update_chirps,verify_due,check_ecmwf,cycle,run_forecast') { throw ('Unexpected operations: ' + $actions) }
$initialization = $global:OperateTestStarted[4].initialization
if ($initialization -is [datetime]) { $initialization = $initialization.ToString('yyyy-MM-dd') }
if ($initialization -ne '2026-10-26') { throw 'The forecast was not run again for its own ECMWF run' }
if (@($global:OperateTestStarted | Where-Object { $_.actor -ne 'Joe254h' }).Count) { throw 'An operation was not recorded for the reviewer' }
$review = $global:OperateTestReviews[0]
if ($global:OperateTestReviews.Count -ne 1 -or -not $review.confirmed -or $review.forecast_id -ne 'w2-2026-10-26-0123abcd' -or $review.comment -ne 'Checked the members and grid.' -or $review.source -ne 'ecmwf_opendata') {
    throw 'The confirmation was not recorded as typed'
}

# Anything but CONFIRM records nothing.
Reset-FakeService
$global:OperateTestAnswers.Enqueue('confirm')
& $operate -ApiUrl 'https://api.invalid' -SkipCycle | Out-Null
if ($global:OperateTestReviews.Count) { throw 'A confirmation was recorded without CONFIRM' }
$actions = @($global:OperateTestStarted | ForEach-Object action) -join ','
if ($actions -ne 'update_chirps,verify_due,check_ecmwf') { throw ('Unexpected operations: ' + $actions) }

# Staff access mode stops before any operation.
Reset-FakeService 'staff'
try { & $operate -ApiUrl 'https://api.invalid' | Out-Null; throw 'Staff mode accepted' }
catch { if ($_.Exception.Message -notlike '*staff access mode*') { throw } }
if ($global:OperateTestStarted.Count) { throw 'Staff mode started an operation' }
Write-Host 'Operations script tests passed (offline).'
