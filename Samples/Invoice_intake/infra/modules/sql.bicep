// Azure SQL Database: the "ERP" that approved invoices land in.
// Set up for Fabric mirroring: Entra-only auth, system-assigned identity on the logical server
// (mirroring requires it), "Allow Azure services" so Fabric can connect without a gateway,
// and a vCore (serverless) tier because DTU tiers below 100 DTU can't be mirrored.
param location string
param tags object
param serverName string
param databaseName string
param adminPrincipalId string
param adminLogin string

@allowed([ 'User', 'Group', 'Application' ])
param adminPrincipalType string = 'User'

param maxVCores int = 2
param autoPauseDelay int = -1

resource server 'Microsoft.Sql/servers@2023-08-01' = {
  name: serverName
  location: location
  tags: tags
  identity: { type: 'SystemAssigned' } // required by Fabric mirroring
  properties: {
    minimalTlsVersion: '1.2'
    publicNetworkAccess: 'Enabled'
    administrators: {
      administratorType: 'ActiveDirectory'
      azureADOnlyAuthentication: true
      login: adminLogin
      sid: adminPrincipalId
      tenantId: subscription().tenantId
      principalType: adminPrincipalType
    }
  }
}

// 0.0.0.0 = "Allow Azure services and resources to access this server" (App Service + Fabric).
resource allowAzureServices 'Microsoft.Sql/servers/firewallRules@2023-08-01' = {
  parent: server
  name: 'AllowAllWindowsAzureIps'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

resource database 'Microsoft.Sql/servers/databases@2023-08-01' = {
  parent: server
  name: databaseName
  location: location
  tags: tags
  sku: {
    name: 'GP_S_Gen5'
    tier: 'GeneralPurpose'
    family: 'Gen5'
    capacity: maxVCores
  }
  properties: {
    autoPauseDelay: autoPauseDelay
    minCapacity: json('0.5')
    zoneRedundant: false
    requestedBackupStorageRedundancy: 'Local'
  }
}

output serverName string = server.name
output serverFqdn string = server.properties.fullyQualifiedDomainName
output databaseName string = database.name
