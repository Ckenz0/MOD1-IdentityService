param appName string
param location string
param environmentId string
param registryServer string
param vaultName string
param identityName string
param imageReference string
param targetPort int
param cpu string
param memory string
param databaseSchema string
param databaseSecretName string
param databaseSecretUri string
param jwtIssuer string
param frontendOrigin string
param privateKeySecretUri string = ''
param projectsApiBaseUrl string = ''
param authApiBaseUrl string = ''
param backlogApiBaseUrl string = ''
param mfaSecretUri string = ''
param resendSecretUri string = ''
param resendFrom string = ''

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = { name: identityName }
resource vault 'Microsoft.KeyVault/vaults@2023-07-01' existing = { name: vaultName }
resource databaseSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' existing = { parent: vault, name: databaseSecretName }
resource keySecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' existing = { parent: vault, name: 'identity-jwt-private-key' }
resource mfaSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' existing = { parent: vault, name: 'identity-mfa-encryption-key' }
resource resendSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' existing = { parent: vault, name: 'identity-resend-api-key' }

resource databaseGrant 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(databaseSecret.id, identity.id, 'read-secret')
  scope: databaseSecret
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')
  }
}

resource keyGrant 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(privateKeySecretUri)) {
  name: guid(keySecret.id, identity.id, 'read-secret')
  scope: keySecret
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')
  }
}

var hasKey = !empty(privateKeySecretUri)
var hasMfa = hasKey && !empty(mfaSecretUri)
var hasResend = hasKey && !empty(resendSecretUri) && !empty(resendFrom)
var keyVolume = [{ name: 'jwt-key', storageType: 'Secret', secrets: [{ secretRef: 'jwt-private-key', path: 'private-key.pem' }] }]

resource mfaGrant 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (hasMfa) {
  name: guid(mfaSecret.id, identity.id, 'read-secret')
  scope: mfaSecret
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')
  }
}

resource resendGrant 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (hasResend) {
  name: guid(resendSecret.id, identity.id, 'read-secret')
  scope: resendSecret
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')
  }
}

resource app 'Microsoft.App/containerApps@2025-01-01' = {
  name: appName
  location: location
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identity.id}': {} } }
  properties: {
    managedEnvironmentId: environmentId
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: { external: true, allowInsecure: false, targetPort: targetPort, transport: 'auto' }
      registries: [{ server: registryServer, identity: identity.id }]
      secrets: concat(
        [{ name: 'database-url', keyVaultUrl: databaseSecretUri, identity: identity.id }],
        hasKey ? [{ name: 'jwt-private-key', keyVaultUrl: privateKeySecretUri, identity: identity.id }] : [],
        hasMfa ? [{ name: 'mfa-encryption-key', keyVaultUrl: mfaSecretUri, identity: identity.id }] : [],
        hasResend ? [{ name: 'resend-api-key', keyVaultUrl: resendSecretUri, identity: identity.id }] : []
      )
    }
    template: {
      scale: { minReplicas: 0, maxReplicas: 1, rules: [{ name: 'http', http: { metadata: { concurrentRequests: '10' } } }] }
      volumes: hasKey ? keyVolume : []
      containers: [{
        name: 'api'
        image: imageReference
        resources: { cpu: json(cpu), memory: memory }
        env: concat([
          { name: 'DATABASE_URL', secretRef: 'database-url' }
          { name: 'DATABASE_SCHEMA', value: databaseSchema }
          { name: 'JWT_ISSUER', value: jwtIssuer }
          { name: 'JWT_AUDIENCE', value: 'engenharia-software-api' }
          { name: 'CORS_ORIGINS', value: string([frontendOrigin]) }
        ], hasKey ? [
          { name: 'JWT_PRIVATE_KEY_PATH', value: '/mnt/secrets/private-key.pem' }
          { name: 'ACCESS_TOKEN_EXPIRE_MINUTES', value: '30' }
          { name: 'FRONTEND_ORIGIN', value: frontendOrigin }
          { name: 'LOCAL_MAILBOX_ENABLED', value: 'false' }
          { name: 'MAIL_PROVIDER', value: hasResend ? 'resend' : 'disabled' }
        ] : [{ name: 'JWKS_URL', value: '${jwtIssuer}/.well-known/jwks.json' }],
        empty(projectsApiBaseUrl) ? [] : [{ name: 'PROJECTS_API_BASE_URL', value: projectsApiBaseUrl }],
        empty(authApiBaseUrl) ? [] : [{ name: 'AUTH_API_BASE_URL', value: authApiBaseUrl }],
        empty(backlogApiBaseUrl) ? [] : [{ name: 'BACKLOG_API_BASE_URL', value: backlogApiBaseUrl }],
        hasMfa ? [{ name: 'MFA_ENCRYPTION_KEY', secretRef: 'mfa-encryption-key' }] : [],
        hasResend ? [
          { name: 'RESEND_API_KEY', secretRef: 'resend-api-key' }
          { name: 'RESEND_FROM', value: resendFrom }
        ] : [])
        volumeMounts: hasKey ? [{ volumeName: 'jwt-key', mountPath: '/mnt/secrets' }] : []
        probes: [
          { type: 'Startup', httpGet: { path: '/health/live', port: targetPort }, timeoutSeconds: 2, periodSeconds: 5, failureThreshold: 30 }
          { type: 'Liveness', httpGet: { path: '/health/live', port: targetPort }, timeoutSeconds: 2, periodSeconds: 30, failureThreshold: 3 }
          { type: 'Readiness', httpGet: { path: '/health/ready', port: targetPort }, timeoutSeconds: 10, periodSeconds: 15, failureThreshold: 3 }
        ]
      }]
    }
  }
  dependsOn: [databaseGrant, keyGrant, mfaGrant, resendGrant]
}

output url string = 'https://${app.properties.configuration.ingress.fqdn}'
