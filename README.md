# Autenticação

## Identidade 0.4.0 — preparação de release

GET/PATCH `/auth/profile` permite editar o próprio resumo, senioridade,
competências com domínio e disponibilidade semanal. Perfil é privado à conta;
não representa alocação de equipe. [Contrato e preparação](docs/profile.md).
Instalação anterior exige `init` administrativo explícito para criar a nova tabela
e grants na role runtime; nenhum preparo remoto foi executado.

API Python/FastAPI para contas individuais, sessões, recuperação, MFA e login JWT RS256. Versão `0.4.0` preparada para publicação; este texto não comprova deploy. A execução pode usar Neon PostgreSQL ou PostgreSQL local com Docker.

Este repositório contém o serviço de identidade de Caue. Projetos/equipes/papéis por projeto e backlog são serviços separados de Brian e Igor. Consulte o [contrato de integração](docs/integration.md), o [guia com Neon](docs/database-neon.md) e a [operação Azure](docs/deploy-azure.md).

## Arquitetura

O serviço usa arquitetura multicamadas: `api.py` apresenta HTTP;
`services.py` e `profile_service.py` executam os casos de uso; `domain.py` e
`profiles.py` definem o domínio; repositórios, banco e segurança fornecem a
infraestrutura. `main.py`, `dependencies.py` e a CLI compõem os recursos.

Rotas não abrem sessões nem montam repositórios; aplicação não importa FastAPI
ou SQLAlchemy; domínio não depende de HTTP/banco. A administração executa `init`
explicitamente, sem criar tabelas/chaves ao iniciar a API. Schema exclusivo:
`mod1_identity`. Veja os diagramas, fluxos e limites em
[Arquitetura da Identidade](docs/architecture.md).

## Executar o MVP com Neon

Com o `.env` configurado e o schema/chave já preparados conforme [docs/database-neon.md](docs/database-neon.md):

```console
uv sync --locked
uv run --locked python -m uvicorn mod1_auth.main:create_app --factory --host 127.0.0.1 --port 8000
```

O frontend fica no repositório separado [MOD1-Frontend](https://github.com/Ckenz0/MOD1-Frontend), servido em `http://127.0.0.1:5173`. Configure `CORS_ORIGINS=["http://127.0.0.1:5173"]`. Os dados das contas ficam no Neon; a chave privada persistente fica no host da API. SQLite continua sendo usado pelos testes rápidos.

O usuário pode criar a própria conta no frontend e entrar imediatamente. A rota pública `POST /auth/register` reutiliza a criação de usuários existente e preserva contas anteriores em caso de e-mail duplicado. Nome, e-mail e senha são validados pelo backend; confira o contrato em [docs/integration.md](docs/integration.md).

Sessões, renovação, revogação administrativa, bloqueio, recuperação, confirmação
de e-mail, MFA e diretório profissional consentido estão descritos em
[segurança e recuperação](docs/security-and-recovery.md). O login com MFA ativo
retorna um desafio temporário antes de emitir JWT. Troca e reset de senha revogam
todas as sessões. A caixa postal local não representa entrega SMTP real;
recomendações de anomalias dependem de provedor configurado e decisão humana.

Envio real de recuperação/confirmação usa o [Resend](docs/resend.md): configure
`MAIL_PROVIDER=resend`, `RESEND_API_KEY` e `RESEND_FROM` somente no backend.
Um envio real de teste foi aceito e recebido, com confirmação do usuário. O
remetente de teste `onboarding@resend.dev`, sem domínio verificado, restringe
destinatários ao e-mail autorizado da conta. Os fluxos de recuperação/confirmação
foram validados com HTTP controlado; esse envio de teste não valida seus links
reais nem entrega geral. IA real permanece desabilitada.

## Iniciar com Docker

Para a publicação integrada das três APIs e do frontend na Azure, mantendo o Neon, siga o [passo a passo de configuração e deploy](docs/deploy-azure.md). Os workflows cloud são manuais; compilar os templates não comprova publicação.

Requisitos: Docker com daemon/Compose disponíveis. Copie `.env.example` para `.env` e substitua `CHANGE_ME`. Para o PostgreSQL local, use senha aleatória com pelo menos 32 caracteres URL-safe (`A-Z`, `a-z`, `0-9`, `_`, `-`), porque o Compose a insere no DSN. Para senhas arbitrárias, codifique a senha para URI. Preserve o `.env` do Neon antes de preparar uma configuração alternativa local.

```console
docker compose config --quiet
docker compose build
docker compose up -d db
docker compose run --rm admin init
docker compose run --rm admin create-user --email caue@example.com --name Caue
docker compose up -d api
```

A senha da conta é digitada de forma oculta, duas vezes, de 12 a 128 caracteres. Não existe argumento `--password`. A senha do usuário é distinta da senha do banco. Abra `http://127.0.0.1:8000/docs`; use **Authorize** para obter um token. JWKS público: `http://127.0.0.1:8000/.well-known/jwks.json`.

O Compose tem somente API, banco local de apoio e comando admin. API roda com UID 10001; volume `auth_keys` é somente leitura para a API e escrita para admin. `auth_db_data` persiste usuários. `docker compose down` preserva volumes; `down -v` apaga dados/chaves e exige reprovisionamento. Não use `-v` para uma instância com dados necessários.

Para desativar/reativar uma conta:

```console
docker compose run --rm admin set-active --user-id UUID_DO_USUARIO --inactive
docker compose run --rm admin set-active --user-id UUID_DO_USUARIO --active
```

Chave e conta sobrevivem ao reinício. Repetir `admin init` não sobrescreve chave/dados. Chave existente inválida causa erro e precisa ser corrigida explicitamente. Alterações de tabelas futuras exigem migrações; `init` cria tabelas ausentes, incluindo profiles, mas não altera colunas de tabelas existentes.

## Executar Python no host

Instale [uv](https://docs.astral.sh/uv/getting-started/installation/) e Python 3.12. Os comandos abaixo usam PostgreSQL local com Docker; SQLite é reservado aos testes rápidos e não comprova integração com PostgreSQL.

```console
uv python install 3.12
uv sync --locked
docker compose up -d db
uv run --locked mod1-auth init
uv run --locked mod1-auth create-user --email caue@example.com --name Caue
uv run --locked uvicorn mod1_auth.main:create_app --factory --host 127.0.0.1 --port 8000
```

O `.env.example` fornece DSN para `127.0.0.1:5432`, chave local em `keys/` e issuer `mod1-auth-local`. Para Neon, use o [guia do banco hospedado](docs/database-neon.md). As chaves do host e do volume Docker são independentes; escolha uma forma de execução para a instância. Para manter tokens entre migrações de ambiente, transfira a mesma chave por canal administrativo seguro.

Em Windows com Controle de Aplicativo que recuse lançadores de ambiente virtual, use um Python autorizado e `python -m ...`, com o ambiente preparado conforme a política da máquina; não desative a política para executar o projeto.

## Configuração

| Variável | Regra |
| --- | --- |
| `DATABASE_URL` | obrigatória, `postgresql+psycopg://...`; segredo |
| `DATABASE_SCHEMA` | `mod1_identity`, identificador SQL validado |
| `JWT_PRIVATE_KEY_PATH` | obrigatória, PEM persistente; nunca commitado |
| `JWT_ISSUER` | obrigatório, estável e exato para os consumidores |
| `JWT_AUDIENCE` | `engenharia-software-api` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | inteiro positivo, padrão 30 |
| `PASSWORD_MIN_LENGTH` | inteiro entre 12 e 128, padrão 12; máximo fixo 128 |
| `CORS_ORIGINS` | lista JSON de origens HTTP(S) exatas, padrão `[]` |
| `POSTGRES_PASSWORD` | apenas PostgreSQL de desenvolvimento/Compose |

Não configure `*` em CORS; inclua a origem do frontend quando o módulo 6 integrar o navegador. APIs consumidoras não dependem de CORS. Não grave senhas, tokens, DSNs ou PEMs privados no Git, em logs ou na imagem.

## Verificar

```console
uv lock --check
uv sync --locked
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy src/mod1_auth examples/validate_token.py
uv run --locked python -m pytest -v
uv build
```

Para integração PostgreSQL, suba o banco **local descartável** e defina `TEST_DATABASE_URL` no ambiente, com o DSN `postgresql+psycopg://auth_service:SENHA_CODIFICADA@127.0.0.1:5432/auth`. Então execute `uv run --locked python -m pytest tests/test_postgresql.py -v`. Os testes criam/removem apenas schemas/papéis sintéticos próprios; precisam da credencial administrativa local. Recusam hosts remotos. Nunca use credenciais do Neon ou de outro banco remoto nesse comando. Sem a variável, os cinco testes são pulados, não aprovados. O teste HTTP de conexão PostgreSQL recusada também exige o driver psycopg utilizável; um skip indica verificação pendente.

Testes cobrem senha literal, e-mail normalizado/duplicidade, Argon2, claims/assinaturas inválidas, health, HTTP, CLI, consumidor independente, indisponibilidade JWKS e reinício. Testar SQLite não valida PostgreSQL; compilar Bicep não valida deploy; escrever Dockerfile não valida a imagem. Registre essas evidências separadamente na entrega.

## Versionamento e colaboração

Fonte única da versão: `pyproject.toml`, refletida no OpenAPI pelos metadados do pacote. Cada serviço tem sua própria versão SemVer. Durante `0.y.z`, PATCH é correção compatível; MINOR é funcionalidade ou quebra documentada com migração. Após `1.0.0`, aplicar MAJOR/MINOR/PATCH conforme o impacto no contrato. Tags `vX.Y.Z` somente para releases verificadas; não mover tags ou substituir imagens publicadas. Versionar imagem por SemVer e identificar deploy por digest.

Use branches de funcionalidade, PRs revisados, Conventional Commits (`feat`, `fix`, `build`, `docs`, `test`) e [CHANGELOG.md](CHANGELOG.md). Ruff, mypy e testes pertinentes devem passar antes da integração. Planos locais e o PDF da disciplina não fazem parte do produto.

## Entregar tokens aos grupos

O serviço permite criar contas e obter JWT; a disponibilidade externa exige publicar uma URL HTTPS no Azure, configurar issuer/audience/JWKS, criar contas individuais e executar a validação a partir da máquina de um colega. Siga [docs/deploy-azure.md](docs/deploy-azure.md). O responsável entrega credenciais; nenhum segredo administrativo é compartilhado. JWT não contém papel global: autorização por projeto pertence ao serviço de projetos.
