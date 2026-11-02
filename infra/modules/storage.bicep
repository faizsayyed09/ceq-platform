param location string = resourceGroup().location
param storageAccountName string
param snowContainerName string = 'snow'
param kbContainerName string = 'ceq-kb'
param evidenceContainerName string = 'evidence'
param runtimePrincipalId string = ''

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource snowContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: snowContainerName
  properties: {
    publicAccess: 'None'
  }
}

resource kbContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: kbContainerName
  properties: {
    publicAccess: 'None'
  }
}

resource evidenceContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: evidenceContainerName
  properties: {
    publicAccess: 'None'
  }

  var blobDataContributorRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')

  resource blobRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(runtimePrincipalId)) {
    name: guid(storage.id, runtimePrincipalId, blobDataContributorRoleId)
    scope: storage
    properties: {
      principalId: runtimePrincipalId
      principalType: 'ServicePrincipal'
      roleDefinitionId: blobDataContributorRoleId
    }
  }
}

output accountId string = storage.id
output accountEndpoint string = storage.properties.primaryEndpoints.blob
output snowContainerName string = snowContainer.name
output kbContainerName string = kbContainer.name
output evidenceContainerName string = evidenceContainer.name
