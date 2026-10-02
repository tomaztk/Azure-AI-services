// Data-plane role assignments (no keys anywhere).
param foundryAccountName string
param storageAccountName string

@description('Array of { id, type } where type is User or ServicePrincipal.')
param principals array

var foundryUserRole = '53ca6127-db72-4b80-b1b0-d745d6d5456d' // Foundry User (agents, models)
var cognitiveServicesUserRole = 'a97b65f3-24c7-4388-baec-2e87135dc908' // Content Understanding data plane
var storageBlobDataContributorRole = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'

var foundryAssignments = flatten(map(principals, p => map([ foundryUserRole, cognitiveServicesUserRole ], r => {
  principalId: p.id
  principalType: p.type
  roleId: r
})))

var storageAssignments = map(principals, p => {
  principalId: p.id
  principalType: p.type
  roleId: storageBlobDataContributorRole
})

resource account 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: foundryAccountName
}

resource storage 'Microsoft.Storage/storageAccounts@2024-01-01' existing = {
  name: storageAccountName
}

resource foundryRoleAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for a in foundryAssignments: {
  name: guid(account.id, a.principalId, a.roleId)
  scope: account
  properties: {
    principalId: a.principalId
    principalType: a.principalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', a.roleId)
  }
}]

resource storageRoleAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for a in storageAssignments: {
  name: guid(storage.id, a.principalId, a.roleId)
  scope: storage
  properties: {
    principalId: a.principalId
    principalType: a.principalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', a.roleId)
  }
}]
