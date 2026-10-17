#requires -Version 7.0
# Offline contract tests. No Azure/GitHub/registry request is made.
$ErrorActionPreference = 'Stop'
$global:DeployTestcommit = 'a' * 40
$global:DeployTestwrites = 0
$global:DeployTestbadCI = $false
$global:DeployTestbadHealth = $false
$global:DeployTestsecretReads = 0
$global:DeployTestmode = 'Express'
$global:DeployTestapp = $null
function az {
    $global:LASTEXITCODE = 0
    if ($args[0] -eq 'rest') {
        if ($args -contains 'get') { return (@{properties=@{environmentMode=$global:DeployTestmode}} | ConvertTo-Json) }
        $global:DeployTestwrites++
        $bodyIndex = [Array]::IndexOf($args, '--body') + 1
        $payload = Get-Content -Raw -LiteralPath $args[$bodyIndex].Substring(1) | ConvertFrom-Json
        if ($payload.properties.template.scale.minReplicas -ne 1) { throw 'Worker can scale to zero' }
        if ($payload.properties.template.containers[0].image -notmatch '@sha256:') { throw 'Moving image tag' }
        if (-not ($payload.properties.template.containers[0].env | Where-Object name -EQ LLM_API_KEY)) { throw 'Existing Copilot setting lost' }
        if ($payload.properties.configuration.ingress.PSObject.Properties.Name -contains 'fqdn') { throw 'Read-only ingress field was sent back' }
        $global:DeployTestapp.properties.template = $payload.properties.template
        return '{}'
    }
    if ($args -contains 'secret') {
        $global:DeployTestsecretReads++
        return (@(
            @{name='db';value='postgresql://private'},
            @{name='blob';value='private-blob'},
            @{name='staff';value=(ConvertTo-Json -Compress -InputObject @(@{name='Joe254h';key=('test' * 12);roles=@('admin')}))},
            @{name='email';value='private-email'},
            @{name='llm';value='private-llm'}
        ) | ConvertTo-Json -Depth 10)
    }
    return ($global:DeployTestapp | ConvertTo-Json -Depth 30)
}
function Reset-DeploymentFixture {
    $global:DeployTestwrites = 0
    $global:DeployTestsecretReads = 0
    $global:DeployTestbadCI = $false
    $global:DeployTestbadHealth = $false
    $global:DeployTestmode = 'Express'
    $global:DeployTesthealthChanges = @{}
    $global:DeployTesthealthError = $false
    $global:DeployTestapp = @{
        id = '/subscriptions/test/resourceGroups/icpac/providers/Microsoft.App/containerApps/icpac-api'
        location = 'switzerlandnorth'
        properties = @{
            environmentId = '/existing-environment'
            provisioningState = 'Succeeded'; latestReadyRevisionName = 'new'; latestRevisionName = 'new'; runningStatus = 'Running'
            configuration = @{ ingress = @{fqdn = 'example.invalid'; traffic = @(@{weight=100}); stickySessions=$null} }
            template = @{
                scale = @{minReplicas = 1; maxReplicas = 1}
                containers = @(@{name = 'icpac-api'; image = ('ghcr.io/joe254h/icpac-backend@sha256:' + ('b' * 64)); env = @(
                    @{name = 'DATABASE_URL'; secretRef = 'db'},
                    @{name = 'PACKAGE_STORE_CONNECTION'; secretRef = 'blob'},
                    @{name = 'STAFF_CREDENTIALS'; secretRef = 'staff'},
                    @{name = 'EMAIL_ACTION_SECRET'; secretRef = 'email'},
                    @{name = 'LLM_API_KEY'; secretRef = 'llm'}
                )})
            }
        }
    }
}
function Invoke-RestMethod {
    param([string]$Uri, [int]$TimeoutSec)
    if ($Uri -like '*actions/runs*') {
        return @{ workflow_runs = @('CI', 'Container build', 'Publish backend image') | ForEach-Object {
            [pscustomobject]@{name = $_; run_number = 1; status = 'completed'; conclusion = $(if ($global:DeployTestbadCI) {'failure'} else {'success'})}
        }}
    }
    if ($Uri -like '*ghcr.io/token*') { return @{token = 'offline-token'} }
    if ($global:DeployTesthealthError) { throw 'offline HTTP timeout' }
    $health = @{
        version = $(if ($global:DeployTestbadHealth) {'old'} else {$global:DeployTestcommit})
        access_configured = $true; durable_storage = $true; release_mode = 'evaluation'
        components = @{Database = 'Healthy'}; status = 'Warning'
    }
    foreach ($entry in $global:DeployTesthealthChanges.GetEnumerator()) { $health[$entry.Key] = $entry.Value }
    return [pscustomobject]$health
}
function Invoke-WebRequest { return @{Headers = @{'Docker-Content-Digest' = @('sha256:' + ('b' * 64))}} }
function Start-Sleep { throw 'Offline test stopped an unready deployment' }
function Read-Host { throw 'Unexpected credential prompt' }
$deployment = Join-Path $PSScriptRoot '../backend.ps1'
Reset-DeploymentFixture
& $deployment -ExpectedCommit $global:DeployTestcommit -PlanOnly
if ($global:DeployTestwrites) { throw 'Plan mutated Azure' }
& $deployment -ExpectedCommit $global:DeployTestcommit
if ($global:DeployTestwrites -ne 1) { throw 'Expected one deployment write' }
$global:DeployTestbadCI = $true
try { & $deployment -ExpectedCommit $global:DeployTestcommit; throw 'Bad CI accepted' }
catch { if ($_.Exception.Message -eq 'Bad CI accepted') { throw } }
if ($global:DeployTestwrites -ne 1) { throw 'Failed CI mutated Azure' }
$global:DeployTestbadCI = $false
$global:DeployTestbadHealth = $true
try { & $deployment -ExpectedCommit $global:DeployTestcommit; throw 'Old release accepted' }
catch { if ($_.Exception.Message -ne 'Offline test stopped an unready deployment') { throw } }

# Reproduce the Express response supplied by the operator: the ready revision is
# omitted (strict-mode property access used to throw), but the app is running.
foreach ($readyShape in @('missing', 'null')) {
    Reset-DeploymentFixture
    $global:DeployTestapp.properties.latestRevisionName = 'icpac-api--latest'
    if ($readyShape -eq 'missing') { $global:DeployTestapp.properties.Remove('latestReadyRevisionName') }
    else { $global:DeployTestapp.properties.latestReadyRevisionName = $null }
    & $deployment -ExpectedCommit $global:DeployTestcommit -VerifyOnly
    if ($global:DeployTestwrites -or $global:DeployTestsecretReads) { throw 'VerifyOnly accessed secrets or wrote to Azure' }
    & $deployment -ExpectedCommit $global:DeployTestcommit
    if ($global:DeployTestwrites -ne 1) { throw 'Express deployment did not complete with one write' }
}

function Assert-VerificationRejected([string]$Reason) {
    try { & $deployment -ExpectedCommit $global:DeployTestcommit -VerifyOnly; throw 'Invalid deployment accepted' }
    catch { if ($_.Exception.Message -notlike "*$Reason*") { throw } }
    if ($global:DeployTestwrites -or $global:DeployTestsecretReads) { throw 'Failed verification accessed secrets or wrote to Azure' }
}

Reset-DeploymentFixture
& $deployment -ExpectedCommit $global:DeployTestcommit -VerifyOnly
if ($global:DeployTestwrites -or $global:DeployTestsecretReads) { throw 'Standard verification changed Azure' }
foreach ($mode in @('WorkloadProfiles', 'ConsumptionOnly', '')) {
    Reset-DeploymentFixture
    $global:DeployTestapp.properties.Remove('latestReadyRevisionName')
    $global:DeployTestmode = $mode
    Assert-VerificationRejected 'ready revision is missing outside an Express environment'
}
Reset-DeploymentFixture
$global:DeployTestapp.properties.latestReadyRevisionName = 'old'
Assert-VerificationRejected 'latest revision is not the ready revision'
foreach ($running in @('Stopped', 'Processing', $null)) {
    Reset-DeploymentFixture
    $global:DeployTestapp.properties.Remove('latestReadyRevisionName')
    $global:DeployTestapp.properties.runningStatus = $running
    Assert-VerificationRejected 'Express app is not Running'
}
Reset-DeploymentFixture
$global:DeployTestapp.properties.Remove('latestRevisionName')
Assert-VerificationRejected 'latest revision is missing'
Reset-DeploymentFixture
$global:DeployTestapp.properties.template.containers[0].image = 'ghcr.io/joe254h/icpac-backend:latest'
Assert-VerificationRejected 'configured image does not match'
Reset-DeploymentFixture
$global:DeployTestapp.properties.template.scale.minReplicas = 0
Assert-VerificationRejected 'worker minimum replicas'
Reset-DeploymentFixture
$global:DeployTestapp.properties.provisioningState = 'Failed'
Assert-VerificationRejected 'Azure provisioning Failed'
Reset-DeploymentFixture
$global:DeployTestapp.properties.provisioningState = 'Updating'
Assert-VerificationRejected 'provisioning=Updating'
foreach ($guard in @(
    @{field='version';value='old';reason='health source version'},
    @{field='access_configured';value=$false;reason='staff access'},
    @{field='durable_storage';value=$false;reason='durable storage'},
    @{field='release_mode';value='production';reason='release mode differs'},
    @{field='components';value=@{Database='Unhealthy'};reason='database is not Healthy'},
    @{field='components';value=$null;reason='database is not Healthy'}
)) {
    Reset-DeploymentFixture
    $global:DeployTesthealthChanges[$guard.field] = $guard.value
    Assert-VerificationRejected $guard.reason
}
Reset-DeploymentFixture
$global:DeployTestbadCI = $true
Assert-VerificationRejected "Wait for 'CI'"
Reset-DeploymentFixture
$global:DeployTesthealthError = $true
Assert-VerificationRejected 'health endpoint unavailable: offline HTTP timeout'
Reset-DeploymentFixture
$global:DeployTestapp.properties.configuration.ingress.Remove('fqdn')
Assert-VerificationRejected 'ingress hostname is missing'
Reset-DeploymentFixture
try { & $deployment -ExpectedCommit $global:DeployTestcommit -PlanOnly -VerifyOnly; throw 'Conflicting modes accepted' }
catch { if ($_.Exception.Message -ne 'Choose either -PlanOnly or -VerifyOnly.') { throw } }
Reset-DeploymentFixture
$global:DeployTestapp.properties.template.containers[0].env = @($global:DeployTestapp.properties.template.containers[0].env | Where-Object name -NE 'STAFF_CREDENTIALS')
$global:DeployTesthealthChanges['access_mode'] = 'public'
& $deployment -ExpectedCommit $global:DeployTestcommit -AccessMode public -PlanOnly
if ($global:DeployTestwrites) { throw 'Public plan changed Azure' }
& $deployment -ExpectedCommit $global:DeployTestcommit -AccessMode public
$configuredMode = @($global:DeployTestapp.properties.template.containers[0].env | Where-Object name -EQ ACCESS_MODE)[0].value
if ($global:DeployTestwrites -ne 1 -or $configuredMode -ne 'public') { throw 'Public deployment did not set ACCESS_MODE' }
Reset-DeploymentFixture
$global:DeployTesthealthChanges['access_mode'] = 'public'
& $deployment -ExpectedCommit $global:DeployTestcommit -AccessMode public -VerifyOnly
if ($global:DeployTestwrites -or $global:DeployTestsecretReads) { throw 'Public verification changed Azure' }
Assert-VerificationRejected 'access mode differs'
Reset-DeploymentFixture
try { & $deployment -ExpectedCommit $global:DeployTestcommit -AccessMode public -ReleaseMode production; throw 'Public production accepted' }
catch { if ($_.Exception.Message -ne 'Public access requires an evaluation release.') { throw } }
if ($global:DeployTestwrites -or $global:DeployTestsecretReads) { throw 'Invalid public production configuration touched Azure' }
Write-Host 'PowerShell deployment contract tests passed (offline).'
