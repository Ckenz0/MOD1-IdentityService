# MVP local com Neon PostgreSQL

## Atualização local 0.3.0

Preparar a tabela profiles explicitamente com `init` administrativo e conceder
SELECT/INSERT/UPDATE à role runtime existente. [Contrato e grants](profile.md).
Startup e readiness não substituem essa preparação. Nada foi aplicado ao Neon.

A API e o frontend executam no computador; as contas ficam no Neon, no schema `mod1_identity`. O banco armazena hashes Argon2 de senha. A autenticação continua sendo responsabilidade desta API, com JWT RS256; não utiliza um serviço externo de login.

## Conexão e preparação

No painel do Neon, abra **Connect** e escolha branch, database e role. Use a conexão direta para a preparação administrativa. Nesta instância, a API também usa conexão direta, com pool de duas conexões. O prefixo SQLAlchemy deve ser `postgresql+psycopg://`. Não precisa de uma chave de API do Neon para conectar ao PostgreSQL.

O `.env` local deve conter estes campos, com os valores reais somente no arquivo ignorado pelo Git:

```dotenv
DATABASE_URL=postgresql+psycopg://ROLE:SENHA_CODIFICADA@HOST/DATABASE?sslmode=verify-full&sslrootcert=CAMINHO_ABSOLUTO_CA
DATABASE_SCHEMA=mod1_identity
JWT_PRIVATE_KEY_PATH=./keys/auth-private.pem
JWT_ISSUER=mod1-auth-local
JWT_AUDIENCE=engenharia-software-api
ACCESS_TOKEN_EXPIRE_MINUTES=30
CORS_ORIGINS=["http://127.0.0.1:5173"]
```

Codifique usuário/senha para URI e mantenha os parâmetros de conexão fornecidos pelo painel. Use `sslmode=verify-full` com um bundle de CAs confiável; nesta máquina foi usado o bundle do `certifi` presente no ambiente virtual. Ao recriar ou mover esse ambiente, atualize o caminho absoluto da CA no DSN. Preserve a chave RSA para manter a identidade das assinaturas.

Para preparar uma nova instância, configure temporariamente a conexão administrativa e execute:

```console
uv sync --locked
uv run --locked python -m mod1_auth.cli init
```

Depois, pelo PostgreSQL administrativo, crie um role runtime com senha própria e sem privilégios de superuser, criação de bancos/roles ou bypass de RLS. Conceda apenas:

```sql
REVOKE ALL ON SCHEMA mod1_identity FROM PUBLIC;
REVOKE ALL ON mod1_identity.users FROM PUBLIC;
GRANT USAGE ON SCHEMA mod1_identity TO mod1_auth_runtime;
GRANT SELECT, INSERT ON mod1_identity.users TO mod1_auth_runtime;
GRANT UPDATE (password_hash, is_active) ON mod1_identity.users TO mod1_auth_runtime;
```

Substitua `DATABASE_URL` pela conexão desse role na API. `init` exige a credencial administrativa; o runtime não possui permissão para criar tabelas.

Na versão 0.2.0, `password_hash` permite a troca autenticada de senha; `is_active`
é usado pela CLI administrativa `set-active` já existente. Somente a tabela
própria recebe UPDATE, sem privilégio em outros schemas. Para instalações com
UPDATE amplo anterior, a redução de privilégios exige revisão e `REVOKE UPDATE`
administrativo antes das concessões por coluna. Esta versão não executa DDL,
migração ou concessão remota automaticamente.

Para criar uma conta usando a conexão runtime:

```console
uv run --locked python -m mod1_auth.cli create-user --email pessoa@example.com --name Pessoa
```

A senha administrativa de uma conta é solicitada de forma oculta pela CLI. O frontend também permite cadastro público por `POST /auth/register`, com login imediato; veja o [contrato](integration.md). A conexão administrativa usada nesta preparação está guardada em `.local/neon-admin.env`, ignorado pelo Git; `.env` contém a conexão limitada. `.local/` e `keys/*.pem` também são ignorados. Esses arquivos são específicos desta máquina e não fazem parte da entrega.

## Execução e verificação

```console
uv run --locked python -m uvicorn mod1_auth.main:create_app --factory --host 127.0.0.1 --port 8000
uv run --locked python -m pytest -q
```

O segundo comando executa testes isolados. Nunca configure `TEST_DATABASE_URL` com a conexão do Neon: os cinco testes de integração PostgreSQL exigem um banco local descartável e recusam hosts remotos.

Verificação inicial nesta máquina em 10/10/2026, anterior à adição do cadastro público:

- Conexão PostgreSQL real com TLS e verificação do certificado.
- Runtime com USAGE no schema e SELECT/INSERT/UPDATE na tabela; sem CREATE, DELETE ou privilégios administrativos.
- Readiness, JWKS, login e consulta de identidade usando os dados do Neon.
- Conta sintética desativada rejeitada em login e `/auth/me`, e reativada ao final.
- Mesmo UUID de conta e mesmo identificador da chave pública após reiniciar a API.
- Frontend real: login, atualização do perfil, rejeição de senha incorreta, logout e retorno à tela de login após recarregar, sem erros de JavaScript.
- Backend: **94 testes aprovados, 5 ignorados**. Os ignorados são os testes de integração PostgreSQL local, não executados nesta verificação.

O teste no Neon foi restrito ao schema próprio e à conta sintética de demonstração. Docker e deploy Azure continuam sem validação de execução; o MVP pode ser demonstrado localmente.

## Verificação após adicionar cadastro público

Em 10/10/2026, a suíte completa do backend passou com **106 testes aprovados e 5 ignorados**, em 100,42 s; Ruff, formatação e mypy passaram. Os cinco ignorados continuam sendo os testes de PostgreSQL local descartável.

O frontend passou em **34 testes**, incluindo cadastro pela API real com banco isolado. Separadamente, no Neon, o navegador criou uma conta sintética nova: cadastro 202, login 200 e consulta protegida 200; sem sessão e após logout, a consulta retornou 401. Cadastro repetido preservou a senha original. As capturas de cadastro, validação dos campos e acesso permitido/bloqueado ficam em `docs/screenshots/` do repositório MOD1-Frontend; as evidências detalhadas ficam no seu `docs/verification.md`.

O cadastro permite login imediato; confirmação de posse do e-mail e recuperação de senha não fazem parte desta versão local.

Referência: [conectar ao Neon](https://neon.com/docs/get-started/connect-neon).
