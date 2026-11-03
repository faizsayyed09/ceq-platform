param location string = resourceGroup().location

param managedEnvironmentId string

param registryServer string

@secure()
param serviceApiToken string

param managedIdentityId string
param managedIdentityClientId string
param storageAccountEndpoint string
param searchServiceEndpoint string
param acrName string
param managedIdentityPrincipalId string
param externalIngress bool = false
param imageDigest string

resource acr 'Microsoft.ContainerRegistry/registries@2025-11-01' existing = {
  name: acrName
}

var acrPullRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-2eb6cdb0984e')

resource acrPullRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, managedIdentityId, acrPullRoleId)
  scope: acr
  properties: {
    principalId: managedIdentityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: acrPullRoleId
  }
}

resource app 'Microsoft.App/containerApps@2026-01-01' = {
  name: 'ca-ceq-dev-api'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${managedIdentityId}': {}
    }
  }
  dependsOn: [
    acrPullRoleAssignment
  ]

  properties: {
    managedEnvironmentId: managedEnvironmentId

    configuration: {
      ingress: {
        external: externalIngress
        targetPort: 8000
        transport: 'auto'
      }

      registries: [
        {
          server: registryServer
          identity: managedIdentityId
        }
      ]

      secrets: [
        {
          name: 'ceq-api-service-token'
          value: serviceApiToken
        }
      ]
    }

    template: {
      containers: [
        {
          name: 'api'

          image: '${registryServer}/ceq-platform@${imageDigest}'

          env: [
            {
              name: 'APP_ENV'
              value: 'production'
            }
            {
              name: 'LOG_LEVEL'
              value: 'INFO'
            }
            {
              name: 'PHI_PROTECTION_MODE'
              value: 'AUDIT_MODE'
            }
            {
              name: 'PREMATCH_MODE'
              value: 'shadow'
            }
            {
              name: 'PREMATCH_CACHE_ENABLED'
              value: 'false'
            }
            {
              name: 'PREMATCH_TOP_N'
              value: '3'
            }
            {
              name: 'REPORT_DIR'
              value: '/app/generated_reports'
            }
            {
              name: 'CEQ_API_SERVICE_TOKEN'
              secretRef: 'ceq-api-service-token'
            }
            {
              name: 'AZURE_CLIENT_ID'
              value: managedIdentityClientId
            }
            {
              name: 'AZURE_STORAGE_ACCOUNT_URL'
              value: storageAccountEndpoint
            }
            {
              name: 'AZURE_SEARCH_ENDPOINT'
              value: searchServiceEndpoint
            }
          ]

          resources: {
            cpu: 1
            memory: '2Gi'
          }

          probes: [
            {
              type: 'Startup'
              httpGet: {
                path: '/health'
                port: 8000
              }
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/health/ready'
                port: 8000
              }
            }
            {
              type: 'Liveness'
              httpGet: {
                path: '/health/live'
                port: 8000
              }
            }
          ]
        }
      ]

      scale: {
        minReplicas: 0
        maxReplicas: 1
      }
    }
  }
}

output fqdn string = app.properties.latestRevisionFqdn
