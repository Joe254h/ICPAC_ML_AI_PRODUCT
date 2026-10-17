#requires -Version 7.0
<#
.SYNOPSIS
Update the existing ICPAC Container App from an exact, CI-tested source revision.
.DESCRIPTION
Run in Azure Cloud Shell PowerShell. Existing environment variables, secrets and region
are preserved. Missing durable storage or staff credentials stop deployment. No credentials
are printed or written into this repository. Keep a database backup before updating.
Use -VerifyOnly to check an existing deployment without reading secrets or changing Azure.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{40}$')][string]$ExpectedCommit,
    [string]$ResourceGroup = 'icpac',
    [string]$AppName = 'icpac-api',
    [ValidateSet('evaluation', 'production')][string]$ReleaseMode = 'evaluation',
    [ValidateSet('staff', 'public')][string]$AccessMode = 'staff',
    [switch]$EnableAutomation,
    [switch]$DisableAutomation,
    [ValidateRange(0, 23)][int]$AutomationHourUtc = 10,
    [switch]$PlanOnly,
    [switch]$VerifyOnly
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($PlanOnly -and $VerifyOnly) { throw 'Choose either -PlanOnly or -VerifyOnly.' }
if ($EnableAutomation -and $DisableAutomation) { throw 'Choose either -EnableAutomation or -DisableAutomation.' }
if ($VerifyOnly -and ($EnableAutomation -or $DisableAutomation)) { throw 'Verification cannot change the automation schedule.' }
if ($AccessMode -eq 'public' -and $ReleaseMode -ne 'evaluation') { throw 'Public access requires an evaluation release.' }

function Invoke-Azure([string[]]$Arguments) {
    $result = & az @Arguments --only-show-errors --output json
    if ($LASTEXITCODE -ne 0) { throw 'Azure command failed; deployment stopped.' }
    if ($result) { return ($result -join "`n" | ConvertFrom-Json -AsHashtable) }
}

function Read-Private([string]$Prompt) {
    $secure = Read-Host $Prompt -AsSecureString
    return [System.Net.NetworkCredential]::new('', $secure).Password
}

function Confirm-Deployment([switch]$Once) {
    $deadline = [DateTime]::UtcNow.AddMinutes(15)
    $environmentMode = $null
    do {
        $current = Invoke-Azure @('containerapp', 'show', '--name', $AppName, '--resource-group', $ResourceGroup)
        $properties = $current.properties
        $state = [string]$properties['provisioningState']
        if ($state -in @('Failed', 'Canceled')) { throw "Azure provisioning $state. Inspect the revision system logs." }
        $pending = [System.Collections.Generic.List[string]]::new()
        if ($state -ne 'Succeeded') { $pending.Add("provisioning=$state") }
        $revision = [string]$properties['latestRevisionName']
        $readyRevision = [string]$properties['latestReadyRevisionName']
        if (-not $revision) { $pending.Add('latest revision is missing') }
        if ($readyRevision) {
            if ($readyRevision -ne $revision) { $pending.Add('latest revision is not the ready revision') }
        } else {
            # Express rolls updates into its active revision and can omit the ready
            # revision field. Confirm the environment mode rather than guessing
            # from the revision suffix or accepting missing readiness everywhere.
            if ($null -eq $environmentMode) {
                $environmentId = $properties['environmentId']
                if (-not $environmentId) { $environmentId = $properties['managedEnvironmentId'] }
                if (-not $environmentId) { throw 'Azure did not return the app environment ID.' }
                $environment = Invoke-Azure @('rest', '--method', 'get', '--url', "https://management.azure.com${environmentId}?api-version=2026-07-01")
                $environmentMode = [string]$environment.properties['environmentMode']
            }
            if ($environmentMode -ne 'Express') { $pending.Add('ready revision is missing outside an Express environment') }
            if ($properties['runningStatus'] -ne 'Running') { $pending.Add('Express app is not Running') }
        }
        $containers = @($properties.template.containers)
        if ($containers.Count -ne 1 -or $containers[0].image -ne $image) { $pending.Add('configured image does not match the expected immutable digest') }
        if ($properties.template.scale.minReplicas -lt 1) { $pending.Add('worker minimum replicas is below one') }
        $fqdn = [string]$properties.configuration.ingress['fqdn']
        $health = $null
        if (-not $fqdn) { $pending.Add('ingress hostname is missing') }
        else {
            try { $health = Invoke-RestMethod "https://$fqdn/health" -TimeoutSec 20 }
            catch { $pending.Add("health endpoint unavailable: $($_.Exception.Message)") }
        }
        if ($null -ne $health) {
            # Normalize HTTP JSON for safe optional-field access under strict mode.
            $health = $health | ConvertTo-Json -Depth 20 | ConvertFrom-Json -AsHashtable
            if ($health -isnot [System.Collections.IDictionary]) { $pending.Add('health response is not an object') }
            else {
                if ($health['version'] -ne $ExpectedCommit) { $pending.Add('health source version differs from the expected commit') }
                if ($health['access_configured'] -ne $true) { $pending.Add('staff access is not configured') }
                $reportedAccessMode = $health['access_mode']
                if (-not $reportedAccessMode) { $reportedAccessMode = 'staff' }
                if ($reportedAccessMode -ne $AccessMode) { $pending.Add('access mode differs from the requested mode') }
                if ($EnableAutomation -and $health['automation_scheduler_enabled'] -ne $true) { $pending.Add('automation scheduler is not enabled') }
                if ($DisableAutomation -and $health['automation_scheduler_enabled'] -ne $false) { $pending.Add('automation scheduler is not disabled') }
                if ($health['durable_storage'] -ne $true) { $pending.Add('durable storage is not configured') }
                if ($health['release_mode'] -ne $ReleaseMode) { $pending.Add('release mode differs from the requested mode') }
                if ($health['components'] -isnot [System.Collections.IDictionary] -or $health['components']['Database'] -ne 'Healthy') { $pending.Add('database is not Healthy') }
            }
        } else { $pending.Add('health response is missing') }
        if (-not $pending.Count) {
            Write-Host "Deployment verified: https://$fqdn"
            Write-Host "Vercel API_URL=https://$fqdn (server environment variable)."
            Write-Host "Release mode: $($health['release_mode']). Health: $($health['status']). Review /health for scientific/data warnings."
            return
        }
        $reason = $pending -join '; '
        if ($Once) { throw "Deployment verification failed for ${ExpectedCommit}: $reason. No Azure resources were changed." }
        Write-Host "Waiting for deployment: $reason"
        Start-Sleep -Seconds 10
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "Deployment did not become ready for ${ExpectedCommit}: $reason. Check Azure revision logs."
}

# A success from another revision, a skipped job, or a pending check is insufficient.
$repoApi = 'https://api.github.com/repos/Joe254h/ICPAC_ML_AI_PRODUCT'
$runs = Invoke-RestMethod "$repoApi/actions/runs?head_sha=$ExpectedCommit&per_page=100"
foreach ($workflow in @('CI', 'Container build', 'Publish backend image')) {
    $latest = @($runs.workflow_runs | Where-Object name -EQ $workflow | Sort-Object run_number -Descending)
    if (-not $latest.Count -or $latest[0].conclusion -ne 'success' -or $latest[0].status -ne 'completed') {
        throw "Wait for '$workflow' to succeed for $ExpectedCommit in GitHub Actions."
    }
}

# Pin the registry digest as well as checking the application-reported source version.
$registryToken = (Invoke-RestMethod 'https://ghcr.io/token?service=ghcr.io&scope=repository:joe254h/icpac-backend:pull').token
$manifest = Invoke-WebRequest "https://ghcr.io/v2/joe254h/icpac-backend/manifests/$ExpectedCommit" -Method Head -Headers @{
    Authorization = "Bearer $registryToken"
    Accept = 'application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.oci.image.manifest.v1+json'
}
$digest = [string](@($manifest.Headers['Docker-Content-Digest'])[0])
if ($digest -notmatch '^sha256:[0-9a-f]{64}$') { throw 'Registry did not return an immutable image digest.' }
$image = "ghcr.io/joe254h/icpac-backend@$digest"
$app = Invoke-Azure @('containerapp', 'show', '--name', $AppName, '--resource-group', $ResourceGroup)
if ($app.properties.template.containers.Count -ne 1) { throw 'This script expects one API container.' }
if ($VerifyOnly) {
    Confirm-Deployment -Once
    Write-Host 'Read-only verification complete. No secrets were read or Azure resources changed.'
    return
}
$secrets = @(Invoke-Azure @('containerapp', 'secret', 'list', '--name', $AppName, '--resource-group', $ResourceGroup, '--show-values'))
$variables = @{}
foreach ($item in $app.properties.template.containers[0].env) { $variables[$item.name] = $item }

function Get-Setting([string]$Name) {
    if (-not $variables.ContainsKey($Name)) { return '' }
    $item = $variables[$Name]
    if ($item.ContainsKey('value')) { return [string]$item.value }
    $entry = @($secrets | Where-Object name -EQ $item.secretRef)
    if ($entry.Count -and $entry[0].ContainsKey('value')) { return [string]$entry[0].value }
    return ''
}
function Set-Value([string]$Name, [string]$Value) { $variables[$Name] = @{ name = $Name; value = $Value } }
function Set-Private([string]$Name, [string]$Reference, [string]$Value) {
    # Script scope is required: this replaces the existing list, rather than a local copy.
    $script:secrets = @($script:secrets | Where-Object name -NE $Reference) + @(@{name = $Reference; value = $Value})
    $variables[$Name] = @{name = $Name; secretRef = $Reference}
}

$database = Get-Setting 'DATABASE_URL'
if (-not $database) {
    if ($PlanOnly) { throw 'DATABASE_URL is missing. Configure persistent PostgreSQL first.' }
    $database = Read-Private 'Paste your PostgreSQL/Supabase DATABASE_URL (hidden)'
    Set-Private 'DATABASE_URL' 'database-url' $database
}
if ($database -notmatch '^postgres(?:ql)?(?:\+psycopg)?://') { throw 'A persistent PostgreSQL DATABASE_URL is required; SQLite is refused.' }
if (-not (Get-Setting 'PACKAGE_STORE_CONNECTION')) {
    if ($PlanOnly) { throw 'PACKAGE_STORE_CONNECTION is missing; rerun without -PlanOnly to provision private Blob Storage.' }
    $account = Invoke-Azure @('account', 'show')
    $storageName = 'icpac' + $account.id.Replace('-', '').Substring(0, 12)
    $accounts = @(Invoke-Azure @('storage', 'account', 'list', '--resource-group', $ResourceGroup))
    if (-not @($accounts | Where-Object name -EQ $storageName).Count) {
        $null = Invoke-Azure @('storage', 'account', 'create', '--name', $storageName,
            '--resource-group', $ResourceGroup, '--location', $app.location, '--sku', 'Standard_LRS',
            '--kind', 'StorageV2', '--min-tls-version', 'TLS1_2', '--allow-blob-public-access', 'false')
    }
    $connection = Invoke-Azure @('storage', 'account', 'show-connection-string', '--name', $storageName, '--resource-group', $ResourceGroup)
    Set-Private 'PACKAGE_STORE_CONNECTION' 'package-store' $connection.connectionString
}
if (-not (Get-Setting 'PACKAGE_STORE_CONTAINER')) { Set-Value 'PACKAGE_STORE_CONTAINER' 'forecast-packages' }
if ($AccessMode -eq 'staff') {
    if (-not (Get-Setting 'STAFF_CREDENTIALS')) {
        if ($PlanOnly) { throw 'STAFF_CREDENTIALS is missing; rerun without -PlanOnly to configure Joe254h.' }
        $staffKey = Read-Private 'Enter a unique staff access key for Joe254h (at least 32 characters; save it in your password manager)'
        if ($staffKey.Length -lt 32) { throw 'Staff key must contain at least 32 characters.' }
        $staff = ConvertTo-Json -Compress -InputObject @(@{name = 'Joe254h'; key = $staffKey; roles = @('admin')})
        Set-Private 'STAFF_CREDENTIALS' 'staff-credentials' $staff
    }
    try {
        $staffRecords = @(Get-Setting 'STAFF_CREDENTIALS' | ConvertFrom-Json -AsHashtable)
        if (-not $staffRecords.Count) { throw 'Empty staff list' }
        $names = @{}
        $keys = @{}
        foreach ($person in $staffRecords) {
            if (-not ($person.name -is [string]) -or $person.name.Trim().Length -lt 2 -or $person.name.Length -gt 80 -or
                $person.name -ne $person.name.Trim() -or -not ($person.key -is [string]) -or $person.key.Length -lt 32 -or
                $names.ContainsKey($person.name) -or $keys.ContainsKey($person.key) -or -not ($person.roles -is [array]) -or -not $person.roles.Count -or
                @($person.roles | Where-Object { $_ -notin @('admin','operator','reviewer','publisher','chat') }).Count) {
                throw 'Invalid staff entry'
            }
            $names[$person.name] = $true
            $keys[$person.key] = $true
        }
    } catch { throw 'STAFF_CREDENTIALS must contain distinct named people, strong keys and valid roles.' }
}
Set-Value 'ACCESS_MODE' $AccessMode
if ($EnableAutomation) { Set-Value 'AUTOMATION_SCHEDULER_ENABLED' 'true' }
elseif ($DisableAutomation -or -not (Get-Setting 'AUTOMATION_SCHEDULER_ENABLED')) { Set-Value 'AUTOMATION_SCHEDULER_ENABLED' 'false' }
if ($PSBoundParameters.ContainsKey('AutomationHourUtc') -or -not (Get-Setting 'AUTOMATION_DAILY_HOUR_UTC')) { Set-Value 'AUTOMATION_DAILY_HOUR_UTC' ([string]$AutomationHourUtc) }
Set-Value 'RELEASE_MODE' $ReleaseMode
Set-Value 'CLOUD_DEPLOYMENT' 'true'
Set-Value 'OPERATION_WORKER_ENABLED' 'true'
Set-Value 'LLM_TOTAL_SECONDS' '120'
Set-Value 'DEPLOYED_AT' ([DateTime]::UtcNow.ToString('o'))
Set-Value 'AUTO_REGISTER_MODELS' 'true'
if (-not (Get-Setting 'EMAIL_ACTION_SECRET')) {
    if ($PlanOnly) { throw 'EMAIL_ACTION_SECRET is missing; rerun without -PlanOnly to generate it.' }
    Set-Private 'EMAIL_ACTION_SECRET' 'email-action-secret' ([Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(48)))
}
$container = $app.properties.template.containers[0]
$container.image = $image
$container.env = @($variables.Values)
# The persistent worker needs a running replica even after the browser is closed.
$app.properties.template.scale.minReplicas = 1
$app.properties.template.scale.maxReplicas = 1
# Single revision is built in for the existing Express app. Omit revision-control
# fields instead of sending management defaults back as unsupported Express settings.
$app.properties.configuration.Remove('activeRevisionsMode') | Out-Null
$app.properties.configuration.Remove('maxInactiveRevisions') | Out-Null
$app.properties.configuration.secrets = $secrets
$app.properties.configuration.ingress.external = $true
$app.properties.configuration.ingress.targetPort = 8000
$app.properties.configuration.ingress.Remove('fqdn') | Out-Null
# Single revision mode routes to the new ready revision automatically. Sending traffic
# configuration or read-only/null GET fields can be rejected by Express environments.
$app.properties.configuration.ingress.Remove('traffic') | Out-Null
$environmentId = $app.properties['environmentId']
if (-not $environmentId) { $environmentId = $app.properties['managedEnvironmentId'] }
if (-not $environmentId) { throw 'Azure did not return the existing app environment ID.' }
$definition = @{
    location = $app.location
    properties = @{
        environmentId = $environmentId
        configuration = $app.properties.configuration
        template = $app.properties.template
    }
}
if ($app.ContainsKey('identity')) { $definition.identity = $app.identity }
if ($app.ContainsKey('tags')) { $definition.tags = $app.tags }
$definition.properties.template.Remove('revisionSuffix') | Out-Null
function Remove-NullFields($Object) {
    if ($Object -is [System.Collections.IDictionary]) {
        foreach ($key in @($Object.Keys)) {
            if ($null -eq $Object[$key]) { $Object.Remove($key) | Out-Null }
            else { Remove-NullFields $Object[$key] }
        }
    } elseif ($Object -is [System.Collections.IList]) {
        foreach ($item in $Object) { Remove-NullFields $item }
    }
}
Remove-NullFields $definition
Write-Host "App: $AppName | source: $ExpectedCommit | mode: $ReleaseMode | access: $AccessMode | replicas: 1"
if ($PlanOnly) { Write-Host 'Preflight passed. No Azure resources were changed.'; return }

$file = [System.IO.Path]::GetTempFileName()
try {
    if (-not $IsWindows) { & chmod 600 $file; if ($LASTEXITCODE -ne 0) { throw 'Cannot secure temporary definition.' } }
    $definition | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $file -Encoding utf8
    $null = Invoke-Azure @('rest', '--method', 'put', '--url', "https://management.azure.com$($app.id)?api-version=2025-07-01", '--body', "@$file")
} finally {
    Remove-Item -LiteralPath $file -Force
}

Confirm-Deployment
