# Deploy do MVP na Azure com Neon

Este guia publica frontend e três APIs com custo orientado à demonstração: Static Web Apps Free, Container Apps Consumption com zero a uma réplica, ACR Basic, Key Vault e Log Analytics. O PostgreSQL continua no Neon. Os serviços e usuários mantêm seus dados; cada API usa seu próprio schema e papel runtime.

A infraestrutura e os workflows estão preparados para validação e publicação. Compilação Bicep e testes locais não comprovam deploy Azure. As imagens precisam passar pelo build/smoke do CI; nenhuma disponibilidade pública é presumida.

## 1. Preparar a assinatura e as ferramentas

1. No portal Azure, selecione a assinatura que será usada e confira saldo/créditos, moeda de cobrança e permissões.
2. Defina o orçamento mensal e o e-mail de alertas. O orçamento gera alertas em 50%, 80% e 100%; não corta automaticamente o consumo.
3. Confira a região do compute Neon no painel. Escolha uma região Azure próxima com Container Apps Consumption disponível e uma região suportada para o gerenciamento do Static Web Apps. Não é preciso mover o Neon.
4. Instale Azure CLI, extensão Container Apps, Bicep, Docker e uv. O CI usa runners Linux; localmente os comandos abaixo são PowerShell. Use os checkouts que contêm o MVP integrado.

O operador de bootstrap precisa criar recursos e atribuir RBAC no Resource Group. Contributor sozinho não permite atribuir papéis: use uma atribuição administrativa adequada ao escopo, sem compartilhar essa permissão com as aplicações.

```powershell
az login
az account list --output table
$subscriptionId = 'SUA_SUBSCRIPTION'
az account set --subscription $subscriptionId
az extension add --name containerapp --upgrade
az bicep install
```

Registre os providers necessários na assinatura, se ainda não estiverem registrados:

```powershell
$providers = @('Microsoft.App', 'Microsoft.OperationalInsights', 'Microsoft.ContainerRegistry', 'Microsoft.KeyVault', 'Microsoft.ManagedIdentity', 'Microsoft.Web', 'Microsoft.Consumption')
foreach ($provider in $providers) {
    az provider register --namespace $provider --wait
}
$resourceGroup = 'rg-mod1-demo'
$region = 'REGIAO_AZURE_ESCOLHIDA'
az group create --name $resourceGroup --location $region --output none
```

## 2. Criar os recursos compartilhados

No repositório de identidade, copie `deploy/azure/parameters.example.json` para `deploy/azure/parameters.local.json`. O arquivo local é ignorado. Substitua o orçamento zero por um inteiro positivo na moeda da assinatura, o e-mail fictício pelo responsável e `frontendLocation` por uma região suportada pelo SWA. `resourcePrefix` usa letras minúsculas, números e hífens, começa por letra e tem entre 3 e 15 caracteres.

O exemplo mantém orçamento zero propositalmente: ele precisa ser escolhido antes de aplicar. Esse valor não é uma estimativa de custo.

```powershell
Copy-Item deploy/azure/parameters.example.json deploy/azure/parameters.local.json
az bicep build --file deploy/azure/main.bicep --outfile "$env:TEMP/mod1-bootstrap.json"
az deployment group what-if --resource-group $resourceGroup --template-file deploy/azure/main.bicep --parameters '@deploy/azure/parameters.local.json'
az deployment group create --name mod1-bootstrap --resource-group $resourceGroup --template-file deploy/azure/main.bicep --parameters '@deploy/azure/parameters.local.json' --query properties.outputs --output json
```

O bootstrap cria somente recursos compartilhados: environment Consumption, ACR Basic, Key Vault, três identidades com AcrPull, SWA Free, logs e orçamento. Não cria APIs com imagens fictícias. Anote os outputs `registryName`, `vaultName`, `environmentName`, `frontendName`, `frontendOrigin` e `apiUrls`. Os nomes globais de ACR e Key Vault são derivados do Resource Group.

## 3. Conferir o Neon e cadastrar os segredos

Preserve o Neon existente. Confira tabelas e permissões pelo [guia do banco](database-neon.md) e pelos guias dos serviços de projetos e backlog. Runtime usa somente os schemas `mod1_identity`, `projects` e `backlog`, com credenciais distintas. A preparação administrativa é explícita; as APIs não criam tabelas no startup.

Cada DSN de produção deve usar `postgresql+psycopg://`, senha codificada para URI, `sslmode=verify-full` e `sslrootcert=/etc/ssl/certs/ca-certificates.crt`. O caminho é o do container Linux, não o caminho Windows. A conexão direta basta para o pool inicial: até seis conexões estáveis de aplicação, com margem adicional para rollout e administração. Confira o limite real do Neon.

O operador precisa de acesso para gravar segredos no vault. As identidades das aplicações recebem leitura por segredo na fase de APIs; não recebem leitura de todo o vault.

Prepare quatro arquivos privados em `.local/`, sem versionar: três DSNs runtime e o PEM RSA persistente. Arquivos de DSN devem ser UTF-8 sem BOM ou quebra de linha final. O PEM deve preservar suas quebras de linha, também sem BOM. Reutilize a chave da instância se a estiver migrando; não gere uma chave nova a cada deploy.

```powershell
$vault = 'NOME_DO_VAULT_DO_OUTPUT'
az keyvault secret set --vault-name $vault --name identity-database-url --file .local/identity-database-url.txt --encoding utf-8 --query id --output tsv
az keyvault secret set --vault-name $vault --name projects-database-url --file .local/projects-database-url.txt --encoding utf-8 --query id --output tsv
az keyvault secret set --vault-name $vault --name backlog-database-url --file .local/backlog-database-url.txt --encoding utf-8 --query id --output tsv
az keyvault secret set --vault-name $vault --name identity-jwt-private-key --file .local/identity-jwt-private-key.pem --encoding utf-8 --query id --output tsv
```

Guarde as quatro URIs versionadas retornadas, para a fase de APIs. Não coloque os conteúdos dos segredos nos parâmetros Bicep, workflows, imagens ou configuração pública. A chave privada pertence somente à identidade.

## 4. Configurar GitHub Environments e OIDC

Em cada repositório, crie um GitHub Environment chamado `demo`, em Settings → Environments. O deploy das APIs executa automaticamente em cada push/merge em `main`, após as verificações. O workflow de infraestrutura e o do frontend continuam manuais; mudanças devem passar pelo fluxo normal de revisão/integração antes de virarem fonte de release.

Para cada repositório de API, configure uma identidade de CI/deploy com credencial federada do GitHub. Em Microsoft Entra ID → App registrations → sua aplicação → Certificates & secrets → Federated credentials → GitHub Actions, selecione o repositório e o environment `demo`. O subject deve ser `repo:ORGANIZACAO/REPOSITORIO:environment:demo` e a audience `api://AzureADTokenExchange`. Use uma credencial federada por repositório. Não crie um client secret.

A identidade de publicação precisa de AcrPush no ACR RBAC convencional e permissão para atualizar apenas sua Container App; conceda a atribuição de identidade gerenciada somente se necessária ao fluxo. A identidade de infraestrutura é separada e precisa criar recursos e atribuir RBAC no grupo. As três identidades runtime criadas pelo Bicep não são identidades de CI.

Variáveis de Environment nas três APIs:

| Variável | Valor |
| --- | --- |
| AZURE_CLIENT_ID | Client ID da identidade federada do repositório |
| AZURE_TENANT_ID | Tenant ID |
| AZURE_SUBSCRIPTION_ID | Assinatura |
| AZURE_RESOURCE_GROUP | Grupo criado no passo 1 |
| ACR_NAME | Output registryName |
| AZURE_CONTAINER_APP | PREFIX-auth, PREFIX-projects ou PREFIX-backlog |

Não há senha Azure ou ACR nos workflows. PRs executam lint, tipos, testes, auditoria de dependências e build/smoke, sem login cloud nem acesso aos segredos do ambiente.

Para usar o workflow `Azure infrastructure` em vez dos comandos locais, crie um segundo Environment no repositório de identidade, chamado `demo-infrastructure`. Configure ali `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID` e `AZURE_RESOURCE_GROUP` com a identidade de infraestrutura, separada da publicadora da API. Sua credencial federada deve usar o subject `repo:ORGANIZACAO/REPOSITORIO:environment:demo-infrastructure`. Somente essa identidade administrativa recebe as permissões de provisionamento/RBAC.

No Environment `demo-infrastructure`, configure `AZURE_BOOTSTRAP_PARAMETERS_JSON` com o JSON ARM de bootstrap revisado e `AZURE_APP_REFERENCES_JSON` com as referências do passo 6. São configurações/referências, não conteúdos de segredos. O workflow roda `what-if` por padrão; a opção `apply` deve ser selecionada explicitamente para criar/alterar recursos. O Environment `demo` continua usando somente a identidade limitada de publicação da API.

## 5. Publicar as três imagens no ACR

No GitHub de cada API, abra Actions → Publish API to Azure → Run workflow → branch `main`. Na primeira publicação, deixe `deploy_revision` desmarcado, pois as Container Apps ainda não existem.

Cada workflow executa lint, tipos, testes, auditoria das dependências fixadas no `uv.lock` (incluindo desenvolvimento), build Docker e smoke HTTP com SQLite/chave sintéticos. O `pip-audit` usa o export com hashes e falha se encontrar vulnerabilidades conhecidas ou não conseguir concluir a coleta. Só depois faz login OIDC e publica a mesma imagem testada. Os repositórios no ACR são `identity`, `projects` e `backlog`; a tag é o SHA do código. O resumo do workflow informa a referência imutável com `@sha256:...`. Guarde as três referências.

Se Docker não funcionar localmente, o CI é o local da validação das imagens; não considere o build/smoke aprovado antes do resultado real desse job.

## 6. Criar as APIs com suas configurações

Copie `deploy/azure/apps.references.example.json` para `deploy/azure/apps.references.local.json`. Substitua todos os valores fictícios pelos outputs do bootstrap, três digests reais e quatro URIs versionadas de segredos.

```powershell
Copy-Item deploy/azure/apps.references.example.json deploy/azure/apps.references.local.json
uv run --locked python scripts/azure_config.py deploy/azure/apps.references.local.json deploy/azure/apps.parameters.local.json
az bicep build --file deploy/azure/apps.bicep --outfile "$env:TEMP/mod1-apps.json"
az deployment group what-if --resource-group $resourceGroup --template-file deploy/azure/apps.bicep --parameters '@deploy/azure/apps.parameters.local.json'
az deployment group create --name mod1-apps --resource-group $resourceGroup --template-file deploy/azure/apps.bicep --parameters '@deploy/azure/apps.parameters.local.json' --query properties.outputs --output json
```

O gerador recusa imagens mutáveis, outro registro, origem não HTTPS e segredo que pertença a outro serviço/vault. Não lê os conteúdos dos segredos. O Bicep atribui leitura individual por segredo, monta o PEM somente na identidade e configura:

- HTTPS externo para as três APIs, mantendo a autenticação JWT da aplicação.
- Issuer igual à URL HTTPS estável da identidade e audience `engenharia-software-api`.
- JWKS da identidade para projetos/backlog; URL de projetos para autorização do backlog.
- CORS com a origem exata do frontend, sem liberar previews automaticamente.
- Zero a uma réplica por API, probes independentes e portas alvo 8000/8001/8002.
- Identidade em 0,5 vCPU/1 GiB; projetos/backlog em 0,25 vCPU/0,5 GiB, sujeitos à validação real de capacidade.

A propagação inicial de RBAC pode levar algum tempo. Se a revisão não obtiver imagem/segredo, confira o erro nos logs e a atribuição no escopo correto antes de repetir a aplicação; não amplie a permissão para todo o vault como atalho.

## 7. Publicar o frontend

No Environment `demo` do frontend, configure:

| Nome | Tipo | Valor |
| --- | --- | --- |
| AUTH_API_URL | Variable | Output authUrl da fase de APIs |
| PROJECTS_API_URL | Variable | Output projectsUrl |
| BACKLOG_API_URL | Variable | Output backlogUrl |
| AZURE_STATIC_WEB_APPS_API_TOKEN | Secret | Token de deploy do SWA criado no bootstrap |

Obtenha o token no portal Azure → Static Web App → Manage deployment token. Cadastre-o diretamente no GitHub Secret, sem colar em arquivos públicos ou logs. O upload SWA usa esse token dedicado; não é o client secret do login OIDC das APIs.

Execute Actions → Publish frontend to Azure → Run workflow, em `main`. O job testa a interface, copia apenas `public/` para o artefato, gera `config.js` com as três URLs HTTPS e faz o upload. A configuração local do frontend permanece apontando para localhost no código fonte. Abra a `frontendOrigin` do bootstrap.

## 8. Validar a demonstração publicada

1. Abra o frontend HTTPS em outra máquina/rede.
2. Cadastre uma conta de demonstração e faça login.
3. Crie um projeto, abra o backlog e registre uma história.
4. Altere prioridade e status, recarregue e confira a persistência.
5. Entre com outra conta e confirme que não consulta projetos/histórias da primeira.
6. Reinicie uma API ou publique uma revisão com a mesma chave e banco; confira dados e aceitação do token anterior até sua expiração.
7. Aguarde escala a zero e repita o acesso. A interface prepara serviços por GET antes das operações, com prazo global de 90 segundos e possibilidade de nova tentativa explícita. Não há keep-alive periódico.
8. Confira logs sem senhas/JWT/DSNs e o funcionamento dos alertas de orçamento.

Startup/liveness usam `/health/live`; readiness usa `/health/ready` e o banco próprio. Uma API indisponível não concede acesso por omissão. Timeout de POST/PATCH não produz reenvio automático: consulte a lista antes de repetir uma gravação com resultado incerto.

Registre evidências sanitizadas em documentação do produto: data, SHA, versão, digest, revisão Azure, URLs públicas e resultados. Não use testes destrutivos de PostgreSQL contra o Neon.

## 9. Atualizações e rollback

Depois da primeira implantação, cada push/merge em `main` dispara Publish API to Azure e atualiza automaticamente a API correspondente, após lint, testes, auditoria e build/smoke. O workflow espera a revisão nova ficar pronta; a resposta de uma revisão antiga não basta. A execução manual em `main` continua disponível, com `deploy_revision=true` por padrão; desmarque a opção somente quando quiser publicar a imagem sem atualizar o app. Atualize também as referências guardadas para que uma reaplicação Bicep não volte a uma imagem antiga por acidente.

### CI/CD da atividade P8

PRs executam [API and container checks](https://github.com/Ckenz0/MOD1-IdentityService/actions/workflows/container-check.yml). O fluxo completo de lint → testes → auditoria de dependências → build/smoke → publicação e deploy automático está em [Publish API to Azure](https://github.com/Ckenz0/MOD1-IdentityService/actions/workflows/azure-deploy.yml). Para comprovar a automação, abra uma execução bem-sucedida cujo evento seja `push`.

O [Dependabot](../.github/dependabot.yml) verifica semanalmente dependências Python (`uv`, incluindo `uv.lock`) e GitHub Actions e abre PRs para atualizações. Esses PRs passam pelo mesmo CI; a configuração não faz merge automático. A auditoria do `pip-audit` é uma verificação adicional que bloqueia o deploy quando encontra vulnerabilidades conhecidas. Referências: [uv com Dependabot](https://docs.astral.sh/uv/guides/integration/dependabot/) e [pip-audit](https://github.com/pypa/pip-audit).

Para rollback, use o digest anterior registrado:

```powershell
az containerapp update --resource-group $resourceGroup --name PREFIX-auth --image REGISTRY.azurecr.io/identity@sha256:DIGEST_ANTERIOR
```

Preserve issuer, chave RSA e banco. Rollback de imagem não desfaz migração ou alteração de dados. O frontend pode ser republicado a partir de uma revisão anterior revisada; não altere diretamente seus arquivos hospedados.

## 10. Custos e encerramento

APIs suspensas deixam de consumir compute de réplicas, mas ACR, Key Vault, logs, tráfego e Neon têm cobranças próprias. As franquias Azure e o plano Free do SWA não garantem custo total zero. Réplicas máximas e alertas não são um teto financeiro.

Ao terminar a demonstração, inventarie os recursos do grupo, preserve chave e informações de recuperação necessárias e remova somente os recursos que decidir encerrar. Excluir o Resource Group também remove o frontend e o registro; o Key Vault tem soft-delete. O Neon é externo e seus dados devem ser preservados. Não use remoção de volumes/schemas como procedimento de deploy.

## Referências

- [Container Apps](https://learn.microsoft.com/en-us/azure/container-apps/overview), [escala](https://learn.microsoft.com/en-us/azure/container-apps/scale-app) e [cobrança](https://learn.microsoft.com/en-us/azure/container-apps/billing).
- [Segredos e Key Vault](https://learn.microsoft.com/en-us/azure/container-apps/manage-secrets), [pull por identidade](https://learn.microsoft.com/en-us/azure/container-apps/managed-identity-image-pull).
- [SWA Free](https://learn.microsoft.com/en-us/azure/static-web-apps/plans), [upload sem build](https://learn.microsoft.com/en-us/azure/static-web-apps/build-configuration).
- [OIDC GitHub/Azure](https://learn.microsoft.com/en-us/azure/developer/github/connect-from-azure-openid-connect), [orçamentos](https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/tutorial-acm-create-budgets).
- [TLS no Neon](https://neon.com/docs/connect/connect-securely).
