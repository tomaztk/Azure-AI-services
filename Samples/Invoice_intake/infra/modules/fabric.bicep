// Optional Fabric capacity. This is the only Fabric piece Azure Resource Manager can create;
// workspace items are created in the Fabric portal (docs/FABRIC_SETUP.md).
// A capacity bills while it runs: pause it after the event.
param location string
param tags object
param name string
param skuName string

@description('UPNs of the capacity admins.')
param adminMembers array

resource capacity 'Microsoft.Fabric/capacities@2023-11-01' = {
  name: name
  location: location
  tags: tags
  sku: {
    name: skuName
    tier: 'Fabric'
  }
  properties: {
    administration: {
      members: adminMembers
    }
  }
}

output name string = capacity.name
