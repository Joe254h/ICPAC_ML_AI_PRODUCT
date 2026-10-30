<#
.SYNOPSIS
Run the service's routine work on the deployed API in one go, as the website's buttons do:
update the rainfall monitoring, verify finished forecasts, check ECMWF and run the weekly
cycle, then report System status.

If the newest forecast waits for the one-time real-time confirmation and every input check
passed, the checks are shown and your confirmation is recorded only when you type CONFIRM;
the forecast is then run again with the AI/ML correction.

Run in Azure Cloud Shell PowerShell (or any PowerShell 7) while the app has public
evaluation access. Nothing is deployed and no secret is read or needed.
#>
[CmdletBinding()]
param(
    [ValidatePattern('^https://')][string]$ApiUrl = 'https://icpac-api.politepond-f2c81e8c.switzerlandnorth.azurecontainerapps.io',
    [ValidateLength(2, 60)][string]$Reviewer = 'Joe254h',
    [ValidateRange(1, 120)][int]$MinutesPerStep = 45,
    [switch]$SkipCycle
)
$ErrorActionPreference = 'Stop'
$api = $ApiUrl.TrimEnd('/')

function Invoke-Api([string]$Method, [string]$Path, $Body = $null) {
    $request = @{ Uri = $api + $Path; Method = $Method; TimeoutSec = 120 }
    if ($null -ne $Body) {
        $request['ContentType'] = 'application/json'
        $request['Body'] = ConvertTo-Json -InputObject $Body -Depth 6 -Compress
    }
    try { return Invoke-RestMethod @request }
    catch {
        $detail = [string]$_.ErrorDetails.Message
        if ($detail) {
            try {
                $parsed = ConvertFrom-Json -InputObject $detail
                if ($parsed.detail) { $detail = [string](ConvertTo-Json -InputObject $parsed.detail -Compress) }
            }
            catch { }
        }
        else { $detail = $_.Exception.Message }
        throw ('The service refused ' + $Method + ' ' + $Path + ': ' + $detail)
    }
}

# Dates arrive as text or, converted by PowerShell, as DateTime.
function Get-Day($Value) {
    if ($Value -is [datetime]) { return $Value.ToString('yyyy-MM-dd') }
    return ([string]$Value).Substring(0, 10)
}

function Invoke-Operation([string]$Action, [hashtable]$Extra = @{}) {
    $body = @{ action = $Action; actor = $Reviewer }
    foreach ($key in $Extra.Keys) { $body[$key] = $Extra[$key] }
    $operation = Invoke-Api 'Post' '/operations' $body
    Write-Host ''
    Write-Host ('== ' + $operation.title) -ForegroundColor Cyan
    $shown = 0
    $deadline = [DateTime]::UtcNow.AddMinutes($MinutesPerStep)
    while ($true) {
        $state = Invoke-Api 'Get' ('/operations/' + $operation.id)
        $messages = @($state.messages)
        for ($i = $shown; $i -lt $messages.Count; $i++) { Write-Host ('   ' + $messages[$i].text) }
        $shown = $messages.Count
        if ($state.status -in @('complete', 'failed', 'interrupted')) { break }
        if ([DateTime]::UtcNow -gt $deadline) {
            Write-Host "   Still running after $MinutesPerStep minutes; it carries on on the server (Operations page)." -ForegroundColor Yellow
            return $state
        }
        Start-Sleep -Seconds 10
    }
    if ($state.status -eq 'complete') { Write-Host '   -> complete' -ForegroundColor Green }
    else { Write-Host ('   -> ' + $state.status + ': ' + $state.error) -ForegroundColor Red }
    return $state
}

$health = Invoke-Api 'Get' '/health'
if ($health.access_mode -ne 'public') {
    throw 'The service is in staff access mode; use the website with your staff key instead.'
}
$schedule = if ($health.automation_scheduler_enabled) { 'on, ' + $health.automation_schedule } else { 'off' }
Write-Host ('Service ' + $api + ' | source ' + $health.version + ' | weekly schedule ' + $schedule)

$null = Invoke-Operation 'update_chirps'
$null = Invoke-Operation 'verify_due'
$null = Invoke-Operation 'check_ecmwf'
if (-not $SkipCycle) { $null = Invoke-Operation 'cycle' }

$latest = Invoke-Api 'Get' '/forecasts/latest'
$hybrid = $latest.products.hybrid
$gate = $latest.provenance.realtime_gate
Write-Host ''
Write-Host ('== Latest forecast: ECMWF run of ' + (Get-Day $latest.initialization) + ', valid ' + (Get-Day $latest.valid_start) + ' to ' + (Get-Day $latest.valid_end)) -ForegroundColor Cyan
if ($hybrid -and $hybrid.status -eq 'available') {
    Write-Host '   The MBC + AI/ML layer is issued.' -ForegroundColor Green
}
elseif ($hybrid -and $hybrid.status -eq 'in_progress' -and $gate -and $gate.required -and -not $gate.review) {
    $checks = @($latest.provenance.input_checks)
    $failed = @($checks | Where-Object { $_.status -eq 'failed' })
    foreach ($check in $checks) { Write-Host ('   [' + $check.status + '] ' + $check.check + ': ' + $check.detail) }
    if ($checks.Count -eq 0 -or $failed.Count -gt 0) {
        Write-Host ('   ' + ($checks.Count - $failed.Count) + ' of ' + $checks.Count + ' input checks passed; the real-time input cannot be confirmed until all of them pass.') -ForegroundColor Yellow
    }
    else {
        Write-Host ''
        Write-Host ('All ' + $checks.Count + ' automated input checks passed. The AI/ML model was trained and tested on ECMWF reforecasts. Confirming records, as ' + $Reviewer + ', that the real-time ECMWF Open Data input matches them, with this run as the evidence, and runs the forecast again with the AI/ML correction. The 2022-2024 test scores still describe reforecasts, not real-time skill.')
        $answer = Read-Host 'Type CONFIRM to record your confirmation (anything else skips it)'
        if ($answer -ceq 'CONFIRM') {
            $comment = Read-Host 'A short comment for the record (what you reviewed)'
            if (-not ([string]$comment).Trim()) {
                $comment = 'Reviewed the ' + $checks.Count + ' passed input checks of the run of ' + (Get-Day $latest.initialization) + '.'
            }
            $review = @{
                source = 'ecmwf_opendata'
                forecast_id = $latest.forecast_id
                withdraw = $false
                actor = $Reviewer
                confirmed = $true
                comment = $comment
            }
            $null = Invoke-Api 'Post' ('/models/' + $latest.model_id + '/realtime-review') $review
            Write-Host '   Confirmation recorded.' -ForegroundColor Green
            $null = Invoke-Operation 'run_forecast' @{ initialization = (Get-Day $latest.initialization) }
            $after = Invoke-Api 'Get' '/forecasts/latest'
            Write-Host ('   MBC + AI/ML layer: ' + $after.products.hybrid.status)
        }
        else { Write-Host '   Skipped; it can be confirmed later on the forecast page.' }
    }
}
elseif ($hybrid) {
    Write-Host ('   The MBC + AI/ML layer is waiting for ' + $hybrid.reason + '.') -ForegroundColor Yellow
}

$health = Invoke-Api 'Get' '/health'
Write-Host ''
Write-Host '== System status' -ForegroundColor Cyan
foreach ($name in @(
    'ECMWF input', 'Operational forecasts', 'MBC + AI/ML forecast', 'CHIRPS verification',
    'CHIRPS monitoring', 'TAMSAT monitoring', 'ARC 2.0 monitoring', 'RFE 2.0 monitoring',
    'GPM IMERG monitoring', 'Copilot language model'
)) {
    $value = $health.components.$name
    if ($value) { Write-Host ('   ' + $name.PadRight(24) + ' ' + $value) }
}
