// Blob storage for uploaded invoice images/PDFs and the raw Content Understanding results.
// Audience uploads are deleted automatically after 2 days by a lifecycle rule.
param location string
param tags object
param name string

resource account 'Microsoft.Storage/storageAccounts@2024-01-01' = {
  name: name
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false // Entra ID only
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    publicNetworkAccess: 'Enabled'
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2024-01-01' = {
  parent: account
  name: 'default'
}

resource containers 'Microsoft.Storage/storageAccounts/blobServices/containers@2024-01-01' = [for c in [ 'invoices', 'extractions' ]: {
  parent: blobService
  name: c
  properties: { publicAccess: 'None' }
}]

resource lifecycle 'Microsoft.Storage/storageAccounts/managementPolicies@2024-01-01' = {
  parent: account
  name: 'default'
  properties: {
    policy: {
      rules: [
        {
          name: 'delete-audience-uploads'
          enabled: true
          type: 'Lifecycle'
          definition: {
            filters: {
              blobTypes: [ 'blockBlob' ]
              prefixMatch: [ 'invoices/audience/', 'extractions/audience/' ]
            }
            actions: {
              baseBlob: { delete: { daysAfterCreationGreaterThan: 2 } }
            }
          }
        }
      ]
    }
  }
}

output name string = account.name
output blobEndpoint string = account.properties.primaryEndpoints.blob
