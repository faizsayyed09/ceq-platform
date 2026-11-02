param location string = resourceGroup().location
param keyVaultName string
param tenantId string = subscription().tenantId
param runtimePrincipalId string = ''

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  properties: {
    tenantId: tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }

    var keyVaultSecretsUserRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')

    resource keyVaultRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(runtimePrincipalId)) {
      name: guid(vault.id, runtimePrincipalId, keyVaultSecretsUserRoleId)
      scope: vault
      properties: {
        principalId: runtimePrincipalId
        principalType: 'ServicePrincipal'
        roleDefinitionId: keyVaultSecretsUserRoleId
      }
    }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 90
    enablePurgeProtection: true
    publicNetworkAccess: 'enabled'
  }
}

output id string = vault.id
output uri string = vault.properties.vaultUri
