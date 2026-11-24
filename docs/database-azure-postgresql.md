# PostgreSQL de produção na Azure

O Módulo 1 usa um Azure Database for PostgreSQL Flexible Server exclusivo,
em Brazil South, com PostgreSQL 18, Burstable B1ms e 32 GB. As três APIs
continuam em Container Apps e o frontend em Static Web Apps. Login, JWT e MFA
permanecem sob responsabilidade da API de Identidade.

## Dados recuperados

A migração de 23/11/2026 restaura o backup de 16/11/2026, conforme autorizado
para a demonstração. Registros e UUIDs presentes na cópia são preservados;
contas, projetos, itens e alterações posteriores não são recuperados
automaticamente. Referências desses registros nos outros módulos podem
retornar `404`, e sessões podem exigir novo login.

O ensaio local e o destino são comparados por contagens e fingerprints das
colunas originais antes/depois das migrações aditivas. A tabela M4, posterior
ao backup, é preparada explicitamente. O Neon e o backup original permanecem
preservados. Nenhum teste usa exclusão de contas, schemas ou dados de produção.

## Conexões e permissões

| Serviço | Schema | Role runtime |
| --- | --- | --- |
| Identidade | `mod1_identity` | `mod1_auth_runtime` |
| Projetos | `projects` | `mod1_projects_runtime` |
| Backlog | `backlog` | `mod1_backlog_runtime` |

Cada runtime recebe somente os privilégios de tabela/coluna necessários no
próprio schema, sem DDL, ownership, criação de roles/bancos ou acesso cruzado.
Preparação e migração usam credencial administrativa separada. Backlog continua
consultando a API de Projetos com o mesmo Bearer para autorizar operações.

O DSN fica apenas em configuração privada e secrets do backend:

```dotenv
DATABASE_URL=postgresql+psycopg://ROLE:SENHA_CODIFICADA@SERVIDOR.postgres.database.azure.com:5432/mod1?sslmode=verify-full&sslrootcert=/etc/ssl/certs/ca-certificates.crt
```

Codifique usuário/senha para URI. O caminho da CA acima pertence ao container
Linux; ambiente local precisa de seu próprio bundle confiável. Não desative
TLS. API e worker do mesmo serviço usam a mesma conexão runtime e schema.
Os pools permanecem com duas conexões, sem overflow: até dez conexões estáveis
para as três APIs e dois workers, além da margem de rollout/administração.

O firewall permite somente os IPs de saída anunciados pelo ambiente Container
Apps. As regras administrativas temporárias da migração foram removidas;
qualquer manutenção futura exige uma liberação administrativa específica e temporária.
Não existe regra irrestrita ou permissão
genérica a todos os serviços Azure. Revise os IPs ao mudar o ambiente; IP de
entrada não identifica necessariamente o endereço de saída para o banco.

## Operação

URLs, contratos HTTP, issuer/audience/JWKS, chaves RSA/MFA, CORS, imagens e
integrações são preservados. Consumidores continuam nos mesmos endpoints.
O frontend não recebe senha administrativa nem acesso direto ao PostgreSQL.

Na troca, revisões antigas e workers param antes da primeira revisão no
destino. Workers só retomam após conferir permissões e filas: as duas outboxes
do backup estavam vazias. Não requeue eventos históricos ou incertos
automaticamente nem envie avisos globais para testar a migração.

O servidor usa backup automático com redundância local e retenção inicial de sete dias, sem HA,
geo-backup ou crescimento automático. A estimativa pública sem benefícios
para B1ms/32 GB em Brazil South é cerca de US$ 33/mês, antes de adicionais.
Acompanhe franquia e crédito da assinatura; outro servidor existente não
comprova gratuidade deste. [Preços oficiais](https://azure.microsoft.com/en-us/pricing/details/postgresql/flexible-server/).

Confira readiness, login/sessão, permissões, persistência, CORS, chave pública
e workers antes de liberar o tráfego. Após aceitar novas gravações no Azure,
não volte automaticamente ao Neon ou a uma cópia antiga: pause as escritas e
preserve uma cópia atual do destino antes de qualquer retorno.

Testes destrutivos continuam exclusivos de um PostgreSQL local descartável.
Credenciais, backups e relatórios pessoais não pertencem ao repositório.
O [guia Neon](database-neon.md) registra a configuração anterior.
