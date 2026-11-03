param location string = resourceGroup().location
param searchServiceName string
param searchSkuName string = 'basic'

var allowedSkus = [
  'basic'
  'standard'
  'standard2'
  'standard3'
]

resource search 'Microsoft.Search/searchServices@2024-06-01-preview' = {
  name: searchServiceName
  location: location
  sku: {
    name: contains(allowedSkus, searchSkuName) ? searchSkuName : 'basic'
  }

  properties: {
    hostingMode: 'default'
    publicNetworkAccess: 'enabled'
    disableLocalAuth: true
    authOptions: {
      aadOrApiKey: {
        aadAuthFailureMode: 'http401WithBearerChallenge'
      }
    }
  }
}

output id string = search.id
output endpoint string = 'https://${search.name}.search.windows.net'
