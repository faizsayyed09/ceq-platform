param location string = resourceGroup().location

param managedEnvironmentId string

param registryServer string

param registryUsername string

@secure()
param registryPassword string

resource app 'Microsoft.App/containerApps@2026-01-01' = {
  name: 'ca-ceq-dev-api'
  location: location

  properties: {
    managedEnvironmentId: managedEnvironmentId

    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
      }

      registries: [
        {
          server: registryServer
          username: registryUsername
          passwordSecretRef: 'acr-password'
        }
      ]

      secrets: [
        {
          name: 'acr-password'
          value: registryPassword
        }
      ]
    }

    template: {
      containers: [
        {
          name: 'api'

          image: '${registryServer}/ceq-platform:dev'

          env: [
            {
              name: 'APP_ENV'
              value: 'development'
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
              name: 'REPORT_DIR'
              value: '/app/generated_reports'
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
