targetScope = 'subscription'

param rgName string = 'rg-ceq-dev-eastus'

param location string = 'eastus'

@secure()
param registryPassword string

@secure()
param serviceApiToken string

param registryUsername string

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: rgName
  location: location
}

module acr './modules/acr.bicep' = {
  name: 'acr'
  scope: rg
}

module env './modules/containerapp-environment.bicep' = {
  name: 'environment'
  scope: rg
}

module app './modules/containerapp.bicep' = {
  name: 'containerapp'
  scope: rg

  params: {
    managedEnvironmentId: env.outputs.id
    registryServer: acr.outputs.loginServer
    registryUsername: registryUsername
    registryPassword: registryPassword
    serviceApiToken: serviceApiToken
  }
}

output fqdn string = app.outputs.fqdn
