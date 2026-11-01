targetScope = 'resourceGroup'

param resourcePrefix string = 'mod1-demo'
param environmentName string
param registryName string
param vaultName string
param frontendOrigin string
@description('Immutable ACR image reference including @sha256:digest.')
param authImage string
param projectsImage string
param backlogImage string
param authDatabaseSecretUri string
param projectsDatabaseSecretUri string
param backlogDatabaseSecretUri string
param jwtKeySecretUri string
@description('Optional versioned Key Vault reference; never the MFA key value.')
param authMfaSecretUri string = ''
@description('Optional versioned Key Vault reference; never the Resend API key value.')
param authResendSecretUri string = ''
param resendFrom string = ''

resource environment 'Microsoft.App/managedEnvironments@2025-01-01' existing = { name: environmentName }
resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = { name: registryName }

var authUrl = 'https://${resourcePrefix}-auth.${environment.properties.defaultDomain}'
var projectsUrl = 'https://${resourcePrefix}-projects.${environment.properties.defaultDomain}'
var backlogUrl = 'https://${resourcePrefix}-backlog.${environment.properties.defaultDomain}'
var services = [
  { name: 'auth', image: authImage, port: 8000, cpu: '0.5', memory: '1Gi', databaseSchema: 'mod1_identity', databaseSecretName: 'identity-database-url', databaseSecretUri: authDatabaseSecretUri }
  { name: 'projects', image: projectsImage, port: 8001, cpu: '0.25', memory: '0.5Gi', databaseSchema: 'projects', databaseSecretName: 'projects-database-url', databaseSecretUri: projectsDatabaseSecretUri }
  { name: 'backlog', image: backlogImage, port: 8002, cpu: '0.25', memory: '0.5Gi', databaseSchema: 'backlog', databaseSecretName: 'backlog-database-url', databaseSecretUri: backlogDatabaseSecretUri }
]

module apps 'modules/api.bicep' = [for service in services: {
  name: '${resourcePrefix}-${service.name}'
  params: {
    appName: '${resourcePrefix}-${service.name}'
    location: environment.location
    environmentId: environment.id
    registryServer: registry.properties.loginServer
    vaultName: vaultName
    identityName: '${resourcePrefix}-${service.name}-id'
    imageReference: service.image
    targetPort: service.port
    cpu: service.cpu
    memory: service.memory
    databaseSchema: service.databaseSchema
    databaseSecretName: service.databaseSecretName
    databaseSecretUri: service.databaseSecretUri
    jwtIssuer: authUrl
    frontendOrigin: frontendOrigin
    privateKeySecretUri: service.name == 'auth' ? jwtKeySecretUri : ''
    authApiBaseUrl: service.name != 'auth' ? authUrl : ''
    backlogApiBaseUrl: service.name == 'projects' ? backlogUrl : ''
    projectsApiBaseUrl: service.name == 'backlog' ? projectsUrl : ''
    mfaSecretUri: service.name == 'auth' ? authMfaSecretUri : ''
    resendSecretUri: service.name == 'auth' ? authResendSecretUri : ''
    resendFrom: service.name == 'auth' ? resendFrom : ''
  }
}]

output authUrl string = authUrl
output projectsUrl string = projectsUrl
output backlogUrl string = backlogUrl
