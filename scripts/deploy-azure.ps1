param(
    [Parameter(Mandatory = $true)][string]$SubscriptionId,
    [string]$Location = "eastus",
    [string]$ResourceGroup = "rg-ceq-v2-dev",
    [string]$AcrName,
    [string]$ContainerAppEnvironment = "cae-ceq-v2-dev",
    [string]$ContainerApp = "ca-ceq-v2-dev",
    [string]$ImageTag = "v2-dev",
    [string]$GenesysRegion = "mypurecloud.com",
    [string]$GenesysClientId = "",
    [string]$GenesysClientSecret = ""
)

$ErrorActionPreference = "Stop"

if (-not $AcrName) {
    throw "AcrName is required and must be globally unique, lowercase, and alphanumeric."
}
if ($AcrName -notmatch "^[a-z0-9]{5,50}$") {
    throw "AcrName '$AcrName' is invalid. Use 5-50 lowercase letters or numbers."
}

az account set --subscription $SubscriptionId
az group create --name $ResourceGroup --location $Location --output none
az acr create --resource-group $ResourceGroup --name $AcrName --sku Basic --admin-enabled false --output none

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $repositoryRoot
try {
    az acr build --registry $AcrName --image "ceq-platform:$ImageTag" --file docker/Dockerfile .
}
finally {
    Pop-Location
}

az containerapp env create --name $ContainerAppEnvironment --resource-group $ResourceGroup --location $Location --output none

$image = "$AcrName.azurecr.io/ceq-platform:$ImageTag"
$createArguments = @(
    "containerapp", "create",
    "--name", $ContainerApp,
    "--resource-group", $ResourceGroup,
    "--environment", $ContainerAppEnvironment,
    "--image", $image,
    "--ingress", "external",
    "--target-port", "8000",
    "--min-replicas", "0",
    "--max-replicas", "1",
    "--cpu", "1.0",
    "--memory", "2Gi",
    "--system-assigned",
    "--env-vars",
    "APP_ENV=development", "LOG_LEVEL=INFO", "GENESYS_REGION=$GenesysRegion",
    "ALLOW_MANUAL_TOKEN_TESTING=false", "PHI_PROTECTION_MODE=AUDIT_MODE",
    "MAX_FILE_SIZE_MB=500", "MAX_AUDIO_DURATION_SECONDS=14400",
    "REPORT_DIR=/app/generated_reports", "HF_HOME=/app/cache/huggingface",
    "WHISPER_MODEL_CACHE=/app/models/whisper"
)

if ($GenesysClientId) {
    $createArguments += "GENESYS_CLIENT_ID=$GenesysClientId"
}
if ($GenesysClientSecret) {
    $createArguments += "--secrets", "genesys-client-secret=$GenesysClientSecret"
    $createArguments += "GENESYS_CLIENT_SECRET=secretref:genesys-client-secret"
}

& az @createArguments

$identity = az containerapp show --name $ContainerApp --resource-group $ResourceGroup --query identity.principalId --output tsv
if ($LASTEXITCODE -ne 0 -or -not $identity) { throw "Container App system identity could not be read." }
$acrId = az acr show --name $AcrName --resource-group $ResourceGroup --query id --output tsv
az role assignment create --assignee-object-id $identity --assignee-principal-type ServicePrincipal --role AcrPull --scope $acrId --output none
az containerapp registry set --name $ContainerApp --resource-group $ResourceGroup --server "$AcrName.azurecr.io" --identity system --output none
az containerapp update --name $ContainerApp --resource-group $ResourceGroup --image $image --output none

$fqdn = az containerapp show --name $ContainerApp --resource-group $ResourceGroup --query properties.configuration.ingress.fqdn --output tsv
Write-Host "Deployment complete: https://$fqdn" -ForegroundColor Green
Write-Host "Health: https://$fqdn/health"
Write-Host "Liveness: https://$fqdn/health/live"
Write-Host "Readiness: https://$fqdn/health/ready"
