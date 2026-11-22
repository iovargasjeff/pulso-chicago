param(
    [Parameter(Mandatory)][string]$Project,
    [string]$Region = 'us-central1',
    [string]$Service = 'pulso-chicago',
    [string]$ClickHouseHost,
    [ValidatePattern('^pulso_[a-z0-9_]{1,45}$')][string]$Database,
    [string]$RuntimeAccount,
    [ValidatePattern('^[1-9][0-9]*$')][string]$SecretVersion = '1'
)
$ErrorActionPreference = 'Stop'
$arguments = @('run', 'deploy', $Service, '--source', '.', '--project', $Project, '--region', $Region,
    '--no-invoker-iam-check', '--max', '2', '--memory', '512Mi', '--timeout', '25s')
if ($ClickHouseHost -or $Database -or $RuntimeAccount) {
    if (-not ($ClickHouseHost -and $Database -and $RuntimeAccount)) {
        throw 'Indica ClickHouseHost, Database y RuntimeAccount para desplegar con datos.'
    }
    $arguments += @('--service-account', $RuntimeAccount, '--update-env-vars',
        "CLICKHOUSE_HOST=$ClickHouseHost,PULSO_DATABASE=$Database,CLICKHOUSE_SECURE=true",
        '--update-secrets', "CLICKHOUSE_USER=pulso-clickhouse-user:${SecretVersion},CLICKHOUSE_PASSWORD=pulso-clickhouse-password:${SecretVersion}")
}
Push-Location (Join-Path $PSScriptRoot '..')
try {
    & gcloud @arguments
    if ($LASTEXITCODE -ne 0) { throw "gcloud run deploy terminó con código $LASTEXITCODE." }
    $url = & gcloud run services describe $Service --project $Project --region $Region '--format=value(status.url)'
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo consultar la URL del servicio.' }
    $checks = @('healthz')
    if ($Database) { $checks += 'api/metadata' }
    foreach ($check in $checks) { [void](Invoke-RestMethod -Uri "$url/$check" -TimeoutSec 30) }
    Write-Output $url
} finally {
    Pop-Location
}
