// Microsoft Foundry resource (kind AIServices) + project + model deployments.
// The same resource serves Content Understanding (Foundry Tools) and the Agent Service.
param location string
param tags object
param name string
param projectName string

@description('Array of { name, model: { format, name, version }, sku: { name, capacity } }')
param deployments array

resource account 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: name
  location: location
  tags: tags
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    customSubDomainName: name
    allowProjectManagement: true
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: true // keyless: everything uses Microsoft Entra ID
    networkAcls: { defaultAction: 'Allow' }
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: account
  name: projectName
  location: location
  tags: tags
  identity: { type: 'SystemAssigned' }
  properties: {
    displayName: 'Invoice intake and sales Q&A'
    description: 'Conference demo: Content Understanding + Foundry agents + Fabric IQ.'
  }
}

// Deploy one model at a time; parallel deployments on one account can conflict.
@batchSize(1)
resource modelDeployments 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = [for d in deployments: {
  parent: account
  name: d.name
  sku: d.sku
  properties: {
    model: d.model
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
    raiPolicyName: 'Microsoft.DefaultV2'
  }
  dependsOn: [ project ]
}]

output name string = account.name
output id string = account.id
output principalId string = account.identity.principalId
output endpoint string = 'https://${name}.services.ai.azure.com/'
output projectEndpoint string = 'https://${name}.services.ai.azure.com/api/projects/${projectName}'
