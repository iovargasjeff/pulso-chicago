param(
    [Parameter(Mandatory)][string]$Project,
    [Parameter(Mandatory)][string]$BuildAccount,
    [Parameter(Mandatory)][string]$RepoOwner,
    [string]$RepoName = 'pulso-chicago',
    [string]$Region = 'us-central1'
)
$ErrorActionPreference = 'Stop'
$triggerName = 'pulso-chicago-main'
$current = & gcloud builds triggers list --project $Project --region global     --filter "name=$triggerName" '--format=value(id)'
if ($LASTEXITCODE -ne 0) { throw 'No se pudieron consultar los disparadores.' }
if ($current) {
    Write-Output "Disparador existente: $current"
    return
}
& gcloud builds triggers create github --project $Project --region global --name $triggerName     --repo-owner $RepoOwner --repo-name $RepoName --branch-pattern '^main$'     --build-config 'cloudbuild.yaml' --substitutions "_REGION=$Region"     --service-account "projects/$Project/serviceAccounts/$BuildAccount"
if ($LASTEXITCODE -ne 0) { throw 'Conecta primero el repositorio en Cloud Build y verifica los permisos.' }
