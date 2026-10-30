@description('ACR prefix')
param namePrefix string = 'acrceqdev'

param location string = resourceGroup().location

resource acr 'Microsoft.ContainerRegistry/registries@2025-11-01' = {
  name: '${namePrefix}${uniqueString(resourceGroup().id)}'
  location: location
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: true
  }
}

output id string = acr.id
output loginServer string = acr.properties.loginServer
output name string = acr.name
