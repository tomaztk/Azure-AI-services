// Linux App Service running the FastAPI app (mobile page, presenter screen, API, intake pipeline).
param location string
param tags object
param name string
param planName string
param skuName string

@description('App settings. The app reads everything from environment variables.')
param appSettings object

resource plan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: planName
  location: location
  tags: tags
  kind: 'linux'
  sku: { name: skuName }
  properties: { reserved: true }
}

resource site 'Microsoft.Web/sites@2024-04-01' = {
  name: name
  location: location
  tags: union(tags, { 'azd-service-name': 'web' })
  kind: 'app,linux'
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.12'
      alwaysOn: true
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      http20Enabled: true
      appCommandLine: 'bash startup.sh'
      healthCheckPath: '/api/health'
    }
  }
}

resource settings 'Microsoft.Web/sites/config@2024-04-01' = {
  parent: site
  name: 'appsettings'
  properties: union(appSettings, {
    SCM_DO_BUILD_DURING_DEPLOYMENT: 'true'
    ENABLE_ORYX_BUILD: 'true'
    WEBSITES_CONTAINER_START_TIME_LIMIT: '900'
    PYTHONUNBUFFERED: '1'
  })
}

output name string = site.name
output uri string = 'https://${site.properties.defaultHostName}'
output principalId string = site.identity.principalId
