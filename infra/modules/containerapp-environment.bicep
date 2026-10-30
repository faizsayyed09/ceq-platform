param location string = resourceGroup().location

resource env 'Microsoft.App/managedEnvironments@2026-01-01' = {
  name: 'cae-ceq-dev'
  location: location
}

output id string = env.id
output defaultDomain string = env.properties.defaultDomain
