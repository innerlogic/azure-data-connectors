// Innerlogic audit log -> Microsoft Sentinel connector (Azure Functions Flex Consumption).
// Deploy into the resource group that contains your Sentinel (Log Analytics) workspace.

targetScope = 'resourceGroup'

@description('Name of the existing Log Analytics workspace that Microsoft Sentinel uses. It must be in this resource group.')
param workspaceName string

@description('Azure region for the new resources. Must be the same region as the Log Analytics workspace, and a region where Azure Functions Flex Consumption is available.')
param location string = resourceGroup().location

@secure()
@description('Innerlogic SIEM access token (starts with ilaudit_), created in the Audit Log area of the Innerlogic app.')
param innerlogicAuditToken string

@description('Innerlogic API base URL.')
param innerlogicApiBase string = 'https://node-v3.innerlogic-api.com'

@description('Collect events recorded from this UTC time (must end in Z). Defaults to deployment time. Use an earlier time to backfill (up to the 13-month retention).')
param startUtc string = utcNow()

@description('NCRONTAB schedule for polling. Default: every minute.')
param pollSchedule string = '0 * * * * *'

@description('URL of the connector package zip, pinned to a release version. To upgrade, redeploy with a newer release URL.')
param packageUri string = 'https://github.com/innerlogic/azure-data-connectors/releases/download/v1.0.0/innerlogic-sentinel-connector.zip'

var suffix = uniqueString(resourceGroup().id)
var tableName = 'InnerlogicAudit_CL'
var streamName = 'Custom-InnerlogicAudit'
var deploymentContainerName = 'deployments'
var tableDef = loadJsonContent('../schema/InnerlogicAudit_CL.table.json')
var dcrDef = loadJsonContent('../schema/dcr-stream.json')

// Built-in role definition IDs
var roles = {
  monitoringMetricsPublisher: '3913510d-42f4-4e42-8a64-420c390055eb'
  keyVaultSecretsUser: '4633458b-17de-408a-b874-0445c86b69e6'
  storageBlobDataOwner: 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'
  storageQueueDataContributor: '974c5e8b-45b9-4653-ba55-5f855dd0fb88'
  storageTableDataContributor: '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3'
}

resource workspace 'Microsoft.OperationalInsights/workspaces@2022-10-01' existing = {
  name: workspaceName
}

resource table 'Microsoft.OperationalInsights/workspaces/tables@2022-10-01' = {
  parent: workspace
  name: tableName
  properties: tableDef.properties
}

resource dce 'Microsoft.Insights/dataCollectionEndpoints@2022-06-01' = {
  name: 'dce-innerlogic-audit-${suffix}'
  location: location
  properties: {
    networkAcls: {
      publicNetworkAccess: 'Enabled'
    }
  }
}

resource dcr 'Microsoft.Insights/dataCollectionRules@2023-03-11' = {
  name: 'dcr-innerlogic-audit-${suffix}'
  location: location
  dependsOn: [
    table
  ]
  properties: {
    dataCollectionEndpointId: dce.id
    streamDeclarations: dcrDef.streamDeclarations
    destinations: {
      logAnalytics: [
        {
          name: 'sentinelWorkspace'
          workspaceResourceId: workspace.id
        }
      ]
    }
    dataFlows: dcrDef.dataFlows
  }
}

// One identity for everything. It is created first so its roles exist before the app starts.
resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-innerlogic-audit-${suffix}'
  location: location
}

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: 'kv-il-${suffix}'
  location: location
  properties: {
    tenantId: subscription().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    enableSoftDelete: true
  }
}

resource tokenSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'innerlogic-audit-token'
  properties: {
    value: innerlogicAuditToken
  }
}

// Storage: identity-only (no shared keys), so it also works where policy forbids key access.
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'ilaudit${suffix}'
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    defaultToOAuthAuthentication: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource deploymentContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: deploymentContainerName
  properties: {
    publicAccess: 'None'
  }
}

resource vaultRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: vault
  name: guid(vault.id, identity.id, roles.keyVaultSecretsUser)
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.keyVaultSecretsUser)
  }
}

resource dcrRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: dcr
  name: guid(dcr.id, identity.id, roles.monitoringMetricsPublisher)
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.monitoringMetricsPublisher)
  }
}

resource storageBlobRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, identity.id, roles.storageBlobDataOwner)
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.storageBlobDataOwner)
  }
}

resource storageQueueRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, identity.id, roles.storageQueueDataContributor)
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.storageQueueDataContributor)
  }
}

resource storageTableRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, identity.id, roles.storageTableDataContributor)
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.storageTableDataContributor)
  }
}

resource insights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-innerlogic-audit-${suffix}'
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: workspace.id
  }
}

resource plan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: 'plan-innerlogic-audit-${suffix}'
  location: location
  kind: 'functionapp'
  sku: {
    name: 'FC1'
    tier: 'FlexConsumption'
  }
  properties: {
    reserved: true
  }
}

resource functionApp 'Microsoft.Web/sites@2024-11-01' = {
  name: 'func-innerlogic-audit-${suffix}'
  location: location
  kind: 'functionapp,linux'
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identity.id}': {}
    }
  }
  // Roles and the deployment container must exist before the app is created.
  dependsOn: [
    vaultRole
    dcrRole
    storageBlobRole
    storageQueueRole
    storageTableRole
    deploymentContainer
  ]
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    keyVaultReferenceIdentity: identity.id
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: '${storage.properties.primaryEndpoints.blob}${deploymentContainerName}'
          authentication: {
            type: 'UserAssignedIdentity'
            userAssignedIdentityResourceId: identity.id
          }
        }
      }
      runtime: {
        name: 'python'
        version: '3.11'
      }
      scaleAndConcurrency: {
        maximumInstanceCount: 40
        instanceMemoryMB: 2048
      }
    }
    siteConfig: {
      minTlsVersion: '1.2'
      appSettings: [
        { name: 'AzureWebJobsStorage__blobServiceUri', value: storage.properties.primaryEndpoints.blob }
        { name: 'AzureWebJobsStorage__queueServiceUri', value: storage.properties.primaryEndpoints.queue }
        { name: 'AzureWebJobsStorage__tableServiceUri', value: storage.properties.primaryEndpoints.table }
        { name: 'AzureWebJobsStorage__credential', value: 'managedidentity' }
        { name: 'AzureWebJobsStorage__clientId', value: identity.properties.clientId }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: insights.properties.ConnectionString }
        { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId }
        { name: 'INNERLOGIC_API_BASE', value: innerlogicApiBase }
        { name: 'INNERLOGIC_AUDIT_TOKEN', value: '@Microsoft.KeyVault(SecretUri=${tokenSecret.properties.secretUri})' }
        { name: 'INNERLOGIC_START_UTC', value: startUtc }
        { name: 'POLL_SCHEDULE', value: pollSchedule }
        { name: 'DCE_ENDPOINT', value: dce.properties.logsIngestion.endpoint }
        { name: 'DCR_IMMUTABLE_ID', value: dcr.properties.immutableId }
        { name: 'DCR_STREAM_NAME', value: streamName }
        { name: 'PAGE_LIMIT', value: '500' }
      ]
    }
  }
}

// Flex Consumption deploys from a package, not WEBSITE_RUN_FROM_PACKAGE.
resource oneDeploy 'Microsoft.Web/sites/extensions@2022-09-01' = {
  parent: functionApp
  name: 'onedeploy'
  properties: {
    packageUri: packageUri
    remoteBuild: false
  }
}

output functionAppName string = functionApp.name
output keyVaultName string = vault.name
output tableName string = tableName
output dcrImmutableId string = dcr.properties.immutableId
output verifyQuery string = '${tableName} | sort by TimeGenerated desc | take 10'
