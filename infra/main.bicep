targetScope = 'subscription'

param rgName string = 'rg-ceq-dev-eastus'

param location string = 'eastus'

@secure()
param serviceApiToken string

param storageAccountName string
param searchServiceName string
param keyVaultName string
param managedIdentityName string = 'id-ceq-dev'
param imageDigest string

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: rgName
  location: location
}

module acr './modules/acr.bicep' = {
  name: 'acr'
  scope: rg
}

module identity './modules/identity.bicep' = {
  name: 'identity'
  scope: rg
  params: {
    identityName: managedIdentityName
  }
}

module storage './modules/storage.bicep' = {
  name: 'storage'
  scope: rg
  params: {
    storageAccountName: storageAccountName
    runtimePrincipalId: identity.outputs.principalId
  }
}

module search './modules/search.bicep' = {
  name: 'search'
  scope: rg
  params: {
    searchServiceName: searchServiceName
  }
}

module keyVault './modules/keyvault.bicep' = {
  name: 'keyVault'
  scope: rg
  params: {
    keyVaultName: keyVaultName
    runtimePrincipalId: identity.outputs.principalId
  }
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
    acrName: acr.outputs.name
    managedIdentityPrincipalId: identity.outputs.principalId
    serviceApiToken: serviceApiToken
    managedIdentityId: identity.outputs.id
    managedIdentityClientId: identity.outputs.clientId
    storageAccountEndpoint: storage.outputs.accountEndpoint
    searchServiceEndpoint: search.outputs.endpoint
    imageDigest: imageDigest
  }
}

output fqdn string = app.outputs.fqdn
output storageEndpoint string = storage.outputs.accountEndpoint
output searchEndpoint string = search.outputs.endpoint
output keyVaultUri string = keyVault.outputs.uri
