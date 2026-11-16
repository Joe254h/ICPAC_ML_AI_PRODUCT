#requires -Version 7.0
# Offline tests of n8n.ps1 against a fake az. No Azure request is made.
$ErrorActionPreference = 'Stop'
$script = Join-Path $PSScriptRoot '../n8n.ps1'
$parseTokens = $null
$parseErrors = $null
[System.Management.Automation.Language.Parser]::ParseFile($script, [ref]$parseTokens, [ref]$parseErrors) | Out-Null
if ($parseErrors) { throw ('n8n.ps1 does not parse: ' + $parseErrors[0].Message) }

$global:N8nTestPut = $null
$global:N8nTestExisting = $false
function az {
    $global:LASTEXITCODE = 0
    $line = $args -join ' '
    if ($line -like 'containerapp show --name icpac-api*') {
        return (@{location = 'switzerlandnorth'; properties = @{
            environmentId = '/environments/icpac'
            configuration = @{ingress = @{fqdn = 'icpac-api.example.io'}}
            template = @{containers = @(@{env = @(
                @{name = 'DATABASE_URL'; secretRef = 'db'},
                @{name = 'PUBLIC_SITE_URL'; value = 'https://icpac.example'}
            )})}
        }} | ConvertTo-Json -Depth 20)
    }
    if ($line -like 'containerapp secret list --name icpac-api*') {
        return (@(@{name = 'db'; value = 'postgresql+psycopg://icpac:p%40ss@db.example:5432/icpacdb?sslmode=require'}) | ConvertTo-Json)
    }
    if ($line -like 'containerapp show --name icpac-n8n*') {
        if (-not $global:N8nTestExisting -and -not $global:N8nTestPut) { $global:LASTEXITCODE = 1; return $null }
        return (@{properties = @{configuration = @{ingress = @{fqdn = 'icpac-n8n.example.io'}}}} | ConvertTo-Json -Depth 10)
    }
    if ($line -like 'containerapp secret list --name icpac-n8n*') {
        return (@(@{name = 'n8n-encryption-key'; value = 'kept-encryption-key'}, @{name = 'icpac-webhook-secret'; value = 'kept-signing-secret-0123456789abcdef'}) | ConvertTo-Json)
    }
    if ($line -like 'account show*') { return '{"id": "sub-1"}' }
    if ($args[0] -eq 'rest') {
        $bodyIndex = [Array]::IndexOf($args, '--body') + 1
        $global:N8nTestPut = Get-Content -Raw -LiteralPath $args[$bodyIndex].Substring(1) | ConvertFrom-Json -AsHashtable
        return '{}'
    }
    throw "Unexpected az call: $line"
}

# A plan changes nothing.
& $script -NotifyEmail 'forecaster@icpac.test' -PlanOnly
if ($global:N8nTestPut) { throw 'Plan changed Azure' }

# A new n8n: PostgreSQL schema n8n with the service's database, one replica, secrets as
# references, generated keys, the API and the site.
& $script -NotifyEmail 'forecaster@icpac.test' -ChatWebhook 'https://chat.example/hook'
$app = $global:N8nTestPut
$container = $app.properties.template.containers[0]
$settings = @{}; foreach ($item in $container.env) { $settings[$item.name] = $item }
if ($container.image -ne 'docker.n8n.io/n8nio/n8n:2.47.7') { throw 'Unpinned n8n image' }
if ($app.properties.template.scale.maxReplicas -ne 1 -or $app.properties.template.scale.minReplicas -ne 1) { throw 'Schedules could fire twice' }
if ($settings['DB_TYPE'].value -ne 'postgresdb' -or $settings['DB_POSTGRESDB_SCHEMA'].value -ne 'n8n') { throw 'Not on PostgreSQL' }
if ($settings['DB_POSTGRESDB_HOST'].value -ne 'db.example' -or $settings['DB_POSTGRESDB_DATABASE'].value -ne 'icpacdb' -or $settings['DB_POSTGRESDB_USER'].value -ne 'icpac') { throw 'Database read wrongly' }
foreach ($name in 'N8N_ENCRYPTION_KEY', 'ICPAC_WEBHOOK_SECRET', 'DB_POSTGRESDB_PASSWORD') {
    if (-not $settings[$name].secretRef -or $settings[$name].ContainsKey('value')) { throw "$name is not a secret reference" }
}
$secrets = @{}; foreach ($s in $app.properties.configuration.secrets) { $secrets[$s.name] = $s.value }
if ($secrets['database-password'] -ne 'p@ss') { throw 'Database password not decoded' }
if ($secrets['n8n-encryption-key'].Length -ne 64 -or $secrets['icpac-webhook-secret'].Length -ne 64) { throw 'Keys not generated' }
if ($settings['ICPAC_API_URL'].value -ne 'https://icpac-api.example.io' -or $settings['ICPAC_SITE_URL'].value -ne 'https://icpac.example') { throw 'Addresses wrong' }
if ($settings['ICPAC_NOTIFY_WEBHOOK'].value -ne 'https://chat.example/hook') { throw 'Chat webhook lost' }
if ($settings['NODE_FUNCTION_ALLOW_BUILTIN'].value -ne 'crypto' -or $settings['N8N_BLOCK_ENV_ACCESS_IN_NODE'].value -ne 'false') { throw 'Workflows cannot read their settings' }

# An update keeps n8n's encryption key and the signing secret the service already uses.
$global:N8nTestPut = $null
$global:N8nTestExisting = $true
& $script -NotifyEmail 'forecaster@icpac.test'
$secrets = @{}; foreach ($s in $global:N8nTestPut.properties.configuration.secrets) { $secrets[$s.name] = $s.value }
if ($secrets['n8n-encryption-key'] -ne 'kept-encryption-key' -or $secrets['icpac-webhook-secret'] -ne 'kept-signing-secret-0123456789abcdef') { throw 'Existing keys replaced' }
Write-Host 'n8n deployment tests passed (offline).'
