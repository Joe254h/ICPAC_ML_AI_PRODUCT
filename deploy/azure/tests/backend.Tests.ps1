#requires -Version 7.0
# Offline contract tests. No Azure/GitHub/registry request is made.
$ErrorActionPreference = 'Stop'
$global:DeployTestcommit = 'a' * 40
$global:DeployTestwrites = 0
$global:DeployTestbadCI = $false
$global:DeployTestbadHealth = $false
function az {
    $global:LASTEXITCODE = 0
    if ($args[0] -eq 'rest') {
        $global:DeployTestwrites++
        $bodyIndex = [Array]::IndexOf($args, '--body') + 1
        $payload = Get-Content -Raw -LiteralPath $args[$bodyIndex].Substring(1) | ConvertFrom-Json
        if ($payload.properties.template.scale.minReplicas -ne 1) { throw 'Worker can scale to zero' }
        if ($payload.properties.template.containers[0].image -notmatch '@sha256:') { throw 'Moving image tag' }
        if (-not ($payload.properties.template.containers[0].env | Where-Object name -EQ LLM_API_KEY)) { throw 'Existing Copilot setting lost' }
        if ($payload.properties.configuration.ingress.PSObject.Properties.Name -contains 'fqdn') { throw 'Read-only ingress field was sent back' }
        return '{}'
    }
    if ($args -contains 'secret') {
        return (@(
            @{name='db';value='postgresql://private'},
            @{name='blob';value='private-blob'},
            @{name='staff';value=(ConvertTo-Json -Compress -InputObject @(@{name='Joe254h';key=('test' * 12);roles=@('admin')}))},
            @{name='email';value='private-email'},
            @{name='llm';value='private-llm'}
        ) | ConvertTo-Json -Depth 10)
    }
    return (@{
        id = '/subscriptions/test/resourceGroups/icpac/providers/Microsoft.App/containerApps/icpac-api'
        location = 'switzerlandnorth'
        properties = @{
            environmentId = '/existing-environment'
            provisioningState = 'Succeeded'; latestReadyRevisionName = 'new'; latestRevisionName = 'new'
            configuration = @{ ingress = @{fqdn = 'example.invalid'; traffic = @(@{weight=100}); stickySessions=$null} }
            template = @{
                scale = @{minReplicas = 0; maxReplicas = 1}
                containers = @(@{name = 'icpac-api'; image = 'old'; env = @(
                    @{name = 'DATABASE_URL'; secretRef = 'db'},
                    @{name = 'PACKAGE_STORE_CONNECTION'; secretRef = 'blob'},
                    @{name = 'STAFF_CREDENTIALS'; secretRef = 'staff'},
                    @{name = 'EMAIL_ACTION_SECRET'; secretRef = 'email'},
                    @{name = 'LLM_API_KEY'; secretRef = 'llm'}
                )})
            }
        }
    } | ConvertTo-Json -Depth 30)
}
function Invoke-RestMethod {
    param([string]$Uri, [int]$TimeoutSec)
    if ($Uri -like '*actions/runs*') {
        return @{ workflow_runs = @('CI', 'Container build', 'Publish backend image') | ForEach-Object {
            [pscustomobject]@{name = $_; run_number = 1; status = 'completed'; conclusion = $(if ($global:DeployTestbadCI) {'failure'} else {'success'})}
        }}
    }
    if ($Uri -like '*ghcr.io/token*') { return @{token = 'offline-token'} }
    return [pscustomobject]@{
        version = $(if ($global:DeployTestbadHealth) {'old'} else {$global:DeployTestcommit})
        access_configured = $true; durable_storage = $true; release_mode = 'evaluation'
        components = @{Database = 'Healthy'}; status = 'Warning'
    }
}
function Invoke-WebRequest { return @{Headers = @{'Docker-Content-Digest' = @('sha256:' + ('b' * 64))}} }
function Start-Sleep { throw 'Offline test stopped an unready deployment' }
$deployment = Join-Path $PSScriptRoot '../backend.ps1'
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
Write-Host 'PowerShell deployment contract tests passed (offline).'
