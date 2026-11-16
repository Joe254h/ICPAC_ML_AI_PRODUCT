#requires -Version 7.0
<#
.SYNOPSIS
Create or update n8n, the coordinator of the weekly forecast, as its own Container App.
.DESCRIPTION
Run in Azure Cloud Shell PowerShell after the service (icpac-api) is deployed. n8n keeps
its workflows, credentials and run history in the service's PostgreSQL, in its own schema
"n8n" (no disk is needed), and runs one replica so each schedule fires once. Its encryption
key and the events' signing secret are generated here and stored only as Container App
secrets; nothing secret is printed. Afterwards:

  1. Give the service the webhook and the same signing secret:
       & $Script -ExpectedCommit $Commit -N8nWebhookUrl '<printed address>' -SetN8nSecret
     and paste the secret, read with:
       az containerapp secret show -g icpac -n icpac-n8n --secret-name icpac-webhook-secret --query value -o tsv
  2. Open n8n (the printed address), create the owner account, import the six files of
     deploy/n8n/workflows, create the credentials "ICPAC staff key" and "ICPAC SMTP"
     (deploy/n8n/README.md) and publish workflows 1 to 4.
.PARAMETER NotifyEmail
Who is told (comma-separated).
#>
[CmdletBinding()]
param(
    [string]$ResourceGroup = 'icpac',
    [string]$ApiApp = 'icpac-api',
    [ValidatePattern('^[a-z][a-z0-9-]{1,30}$')][string]$AppName = 'icpac-n8n',
    [Parameter(Mandatory)][ValidatePattern('^[^@\s]+@[^@\s]+(,[^@\s]+@[^@\s]+)*$')][string]$NotifyEmail,
    [ValidatePattern('^[^@\s]+@[^@\s]+$')][string]$NotifyFrom = 'icpac-week2@icpac.net',
    [ValidatePattern('^(|https://\S+)$')][string]$ChatWebhook = '',
    [ValidatePattern('^\d+\.\d+\.\d+$')][string]$N8nVersion = '2.47.7',
    [switch]$PlanOnly
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Invoke-Azure([string[]]$Arguments) {
    $result = & az @Arguments --only-show-errors --output json
    if ($LASTEXITCODE -ne 0) { throw 'Azure command failed; nothing more was changed.' }
    if ($result) { return ($result -join "`n" | ConvertFrom-Json -AsHashtable) }
}
function New-Secret { [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32)).ToLower() }

$api = Invoke-Azure @('containerapp', 'show', '--name', $ApiApp, '--resource-group', $ResourceGroup)
$environment = $api.properties.environmentId
$apiUrl = 'https://' + $api.properties.configuration.ingress.fqdn
$site = @($api.properties.template.containers[0].env | Where-Object name -EQ PUBLIC_SITE_URL)
$siteUrl = if ($site.Count -and $site[0].ContainsKey('value')) { $site[0].value } else { $apiUrl }

# The service's database, read from its secret, holds n8n's schema too.
$databaseRef = @($api.properties.template.containers[0].env | Where-Object name -EQ DATABASE_URL)
if (-not $databaseRef.Count -or -not $databaseRef[0].ContainsKey('secretRef')) { throw 'The service has no PostgreSQL DATABASE_URL secret.' }
$apiSecrets = @(Invoke-Azure @('containerapp', 'secret', 'list', '--name', $ApiApp, '--resource-group', $ResourceGroup, '--show-values'))
$databaseUrl = [string](@($apiSecrets | Where-Object name -EQ $databaseRef[0].secretRef)[0].value)
$database = [Uri]($databaseUrl -replace '^postgres(ql)?(\+\w+)?://', 'postgresql://')
if ($database.Scheme -ne 'postgresql') { throw 'n8n needs the service to use PostgreSQL.' }
$user, $password = ($database.UserInfo -split ':', 2) | ForEach-Object { [Uri]::UnescapeDataString($_) }

$existing = $null
try { $existing = Invoke-Azure @('containerapp', 'show', '--name', $AppName, '--resource-group', $ResourceGroup) } catch { }
$kept = @{}
if ($existing) {
    foreach ($s in @(Invoke-Azure @('containerapp', 'secret', 'list', '--name', $AppName, '--resource-group', $ResourceGroup, '--show-values'))) { $kept[$s.name] = $s.value }
}
# Keep the encryption key and signing secret of an existing n8n: its credentials and the
# service's signatures depend on them.
$encryption = if ($kept['n8n-encryption-key']) { $kept['n8n-encryption-key'] } else { New-Secret }
$signing = if ($kept['icpac-webhook-secret']) { $kept['icpac-webhook-secret'] } else { New-Secret }

$settings = @(
    @{name = 'N8N_ENCRYPTION_KEY'; secretRef = 'n8n-encryption-key'},
    @{name = 'ICPAC_WEBHOOK_SECRET'; secretRef = 'icpac-webhook-secret'},
    @{name = 'DB_POSTGRESDB_PASSWORD'; secretRef = 'database-password'},
    @{name = 'DB_TYPE'; value = 'postgresdb'},
    @{name = 'DB_POSTGRESDB_HOST'; value = $database.Host},
    @{name = 'DB_POSTGRESDB_PORT'; value = "$(if ($database.Port -gt 0) { $database.Port } else { 5432 })"},
    @{name = 'DB_POSTGRESDB_DATABASE'; value = $database.AbsolutePath.TrimStart('/')},
    @{name = 'DB_POSTGRESDB_USER'; value = $user},
    @{name = 'DB_POSTGRESDB_SCHEMA'; value = 'n8n'},
    @{name = 'DB_POSTGRESDB_SSL_ENABLED'; value = 'true'},
    @{name = 'GENERIC_TIMEZONE'; value = 'Africa/Nairobi'},
    @{name = 'TZ'; value = 'Africa/Nairobi'},
    @{name = 'N8N_DIAGNOSTICS_ENABLED'; value = 'false'},
    @{name = 'N8N_PERSONALIZATION_ENABLED'; value = 'false'},
    @{name = 'N8N_BLOCK_ENV_ACCESS_IN_NODE'; value = 'false'},
    @{name = 'NODE_FUNCTION_ALLOW_BUILTIN'; value = 'crypto'},
    @{name = 'N8N_PROXY_HOPS'; value = '1'},
    @{name = 'ICPAC_API_URL'; value = $apiUrl},
    @{name = 'ICPAC_SITE_URL'; value = $siteUrl},
    @{name = 'ICPAC_NOTIFY_EMAIL'; value = $NotifyEmail},
    @{name = 'ICPAC_NOTIFY_FROM'; value = $NotifyFrom}
)
if ($ChatWebhook) { $settings += @{name = 'ICPAC_NOTIFY_WEBHOOK'; value = $ChatWebhook} }
$app = @{
    location = $api.location
    properties = @{
        environmentId = $environment
        configuration = @{
            ingress = @{external = $true; targetPort = 5678}
            secrets = @(
                @{name = 'n8n-encryption-key'; value = $encryption},
                @{name = 'icpac-webhook-secret'; value = $signing},
                @{name = 'database-password'; value = $password}
            )
        }
        template = @{
            containers = @(@{
                name = 'n8n'
                image = "docker.n8n.io/n8nio/n8n:$N8nVersion"
                resources = @{cpu = 1.0; memory = '2Gi'}
                env = $settings
            })
            # One replica: each schedule must fire once.
            scale = @{minReplicas = 1; maxReplicas = 1}
        }
    }
}
if ($PlanOnly) {
    Write-Host "Plan: $AppName (n8n $N8nVersion) in $ResourceGroup, database schema n8n on $($database.Host), API $apiUrl. Nothing changed."
    return
}
$body = New-TemporaryFile
try {
    $app | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $body -Encoding utf8
    $id = "/subscriptions/$((Invoke-Azure @('account', 'show')).id)/resourceGroups/$ResourceGroup/providers/Microsoft.App/containerApps/$AppName"
    Invoke-Azure @('rest', '--method', 'put', '--url', "https://management.azure.com${id}?api-version=2024-03-01", '--body', "@$body") | Out-Null
} finally { Remove-Item -LiteralPath $body -ErrorAction SilentlyContinue }
$created = Invoke-Azure @('containerapp', 'show', '--name', $AppName, '--resource-group', $ResourceGroup)
$address = 'https://' + $created.properties.configuration.ingress.fqdn
Write-Host "n8n: $address"
Write-Host "Webhook for the service (-N8nWebhookUrl): $address/webhook/icpac-events"
Write-Host 'Next: deploy/n8n/README.md, "Run it on Azure, next to the service".'
