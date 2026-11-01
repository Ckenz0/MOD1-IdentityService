# Validação adicional — 31/10/2026, US locais

Atualização posterior do transporte de e-mail: [verificação do Resend](resend-verification.md),
com testes adicionais, revisão e distinção entre contrato controlado e envio real.

Branch `feat/remaining-user-stories`, sem publicação. Validação atual:
`python -m pytest -q` com PostgreSQL 17 descartável em loopback:
**238 testes passaram, sem skips**, em 64,17 s.
`ruff check src tests`, `ruff format --check src tests`, `mypy` (23 módulos)
e `uv build` passaram.

Inclui recuperação/MFA/diretório, refresh e consumo concorrente de segredos,
revogação, bloqueio administrativo e propostas de análise. Regressão específica
intercala redefinição de senha entre a verificação cara e a criação de sessão:
o login com a senha antiga é recusado. Migrações preservam dados existentes.
O teste usa banco temporário/loopback; não acessa Neon/produção.

O frontend validou MFA, código de recuperação, confirmação de e-mail e reset
contra APIs reais em SQLite local. SMTP e IA reais não foram chamados/validados.
Veja [security-and-recovery.md](security-and-recovery.md).

## Histórico das validações anteriores

# Verificação do candidato 0.1.0 — 11/10/2026

## Arquitetura multicamadas — 30/10/2026, somente local

- Baseline: **193 passaram, 7 ignorados**, em 52,15 s. Ruff check/formato,
  mypy (14 arquivos), lock e wheel/sdist passaram antes da refatoração.
- TDD de fronteiras: **2 falharam e 5 passaram** antes da extração; os testes
  detectaram imports reais de repositórios/banco e abertura de sessões/acesso
  ao engine em `api.py`. Após extrair a composição para `dependencies.py`,
  **7 testes de arquitetura passaram**.
- Suíte completa final: `python -m pytest -q -ra` com Python 3.12.15,
  **200 passaram, 7 ignorados**, em 50,14 s. Cobre HTTP, erros uniformes,
  política/troca de senha, perfil, JWT/JWKS, CLI, readiness e reinício.
- `python -m ruff check .`, `python -m ruff format --check .`,
  `python -m mypy src/mod1_auth examples/validate_token.py`, `uv lock --check`
  e `git diff --check` passaram. Mypy verificou 15 arquivos.
- `uv build --no-build-isolation` gerou wheel/sdist **0.3.0**, sem mudança de
  versão. Auditoria dos dois pacotes confirmou `dependencies.py` incluído e
  ausência de instruções locais, planos e `.local/`. A lista de arquivos
  rastreados também não contém esses artefatos; as regras de ignore permanecem.
- Os **7 testes de `tests/test_postgresql.py`** foram ignorados porque
  `TEST_DATABASE_URL` estava ausente: normalização/rollback, perfil/reinício,
  login/reinício, troca de senha/hash anterior, schema ausente, falha de
  permissões e isolamento da role runtime. Essa execução usou apenas SQLite temporário;
  não comprova integração PostgreSQL. A conexão PostgreSQL local recusada do
  teste HTTP foi exercitada com psycopg disponível, sem acesso a banco remoto.
- Sem deploy, push, merge, grants ou acesso ao Neon. Integração dos três
  serviços com navegador e revisão independente são verificações separadas.
  Diagramas e limites atuais: [Arquitetura da Identidade](architecture.md).

## Colaboração/perfil 0.3.0 — 28/10/2026, somente local

- Suíte completa com PostgreSQL 16.15 descartável em loopback, UTF-8/ICU und:
  **200 testes passaram, nenhum skip**, em 136,16 s.
- Ruff check/formato, mypy, lock e wheel/sdist verificados no candidato.
- Frontend 0.4.0: **96 testes passaram sem skips**, com três APIs reais e bancos/chaves
  temporários. Teste ampliado de duas contas também passou: convite, perfil,
  Desenvolvedor/status, promoção a PO e remoção/reutilização negada do código.
- Revisão própria de isolamento, contratos, expiração e concorrência. A revisão
  independente deste lote ficou indisponível por limite de uso dos auxiliares;
  a revisão independente histórica abaixo cobre somente o lote anterior.
- PostgreSQL encerrado e dados temporários removidos. Sem main/push/deploy/tag,
  sem acesso ao Neon ou alteração de grants/configuração remota.

## Candidato local 0.2.0 — 28/10/2026

### Conferência integrada concluída

- Suíte completa com PostgreSQL 16.15 descartável em loopback: **156 passaram,
  nenhum skip**, em 125,75 s. Inclui os seis testes PostgreSQL e o CAS concorrente.
- Frontend candidato 0.3.0: **85 testes aprovados sem skips**, com as três APIs
  reais e SQLite/chaves temporários. A troca por navegador encerra a sessão local,
  a senha anterior é recusada no novo login e a nova senha autentica.
- Revisão independente dos três backends concluída sem achados críticos/importantes.
- Banco temporário encerrado e removido; nenhum grant/deploy/SQL remoto executado.
- JWT já emitido permanece válido nos consumidores até expirar, conforme contrato;
  esta entrega não implementa revogação/refresh/MFA ou recuperação por e-mail.

### Registro da implementação antes da conferência integrada

- Baseline antes da implementação: **125 passaram, 5 ignorados**.
- TDD: testes de política/troca/CAS falharam antes da implementação (22 casos);
  o teste da CLI também comprovou que o mínimo configurado era ignorado.
- Suíte completa após implementar: **150 passaram, 5 ignorados**, em 178,33 s.
  Um sexto caso opt-in PostgreSQL foi acrescentado durante essa execução e
  coletado separadamente: os **6 casos PostgreSQL foram ignorados** sem DSN.
- Ruff, formatação, mypy (11 arquivos), `uv lock --check` e `git diff --check`
  passaram; `uv build --no-build-isolation` gerou wheel e sdist 0.2.0.
- Windows: bootstrap local de `hatchling` e `editables`, seguido de
  `uv sync --locked --no-build-isolation`; dependências de runtime continuam
  travadas no lock. Nenhuma alteração de política da máquina.
- Os testes cobrem senhas literais/Unicode até 128 caracteres, política no
  cadastro/CLI/troca, 204 vazio, 400 uniforme, autenticação, 422 sem segredos,
  503 genérico, no-store e CAS com duas trocas simultâneas.

Tudo ficou na branch local `feat/us-account-security`, sem publicação, deploy,
concessões remotas ou alteração de schema. A validação PostgreSQL descartável e
a revisão independente estavam pendentes nesta etapa (concluídas acima). Nenhum acesso ao
Neon foi feito neste lote. JWTs emitidos conservam o TTL residual documentado;
logout local após trocar senha não implementa revogação.

## Evidência histórica 0.1.0

O recorte permite criar conta, entrar, consultar a identidade e consumir o JWT
RS256 nos demais serviços. Contas ficam no Neon e a chave privada permanece no
host da API. Frontend e serviço de projetos executam separadamente.

Antes de publicar a branch `feat/auth-mvp`:

- Suíte completa: **108 passaram, 5 ignorados**, em 97,55 segundos.
- Os cinco ignorados exigem PostgreSQL local descartável e `TEST_DATABASE_URL`;
  nunca configurar essa variável com o Neon. Host remoto e parâmetros que
  sobrescrevam o endereço são recusados antes de inicializar o banco.
- Ruff, formatação, mypy estrito e `uv lock --check` passaram.
- Wheel/sdist foram construídos com Hatchling no ambiente local autorizado;
  arquivos privados, `.env`, chaves e `.local/` ficaram fora dos pacotes.
- Frontend: **48 testes passaram**, incluindo identidade e projetos com APIs reais
  e bancos/chaves sintéticos. Backend de projetos: **73 passaram, 1 opt-in ignorado**.
- A demonstração anterior no Neon comprovou cadastro, login, consulta, isolamento
  de contas e persistência após reinício. Evidências em `database-neon.md` e no
  repositório MOD1-Frontend, `docs/verification.md`.

Não foram executados Docker/deploy Azure nesta conferência. Cadastro permite login
imediato sem confirmar posse do e-mail. Logout não revoga JWT já emitido; equipes,
papéis por projeto e backlog pertencem aos próximos recortes.

Versão SemVer candidata definida em `pyproject.toml`. Esta publicação de branch/PR
não cria tag/release nem integra alterações na main. Brian Freire é coautor dos
novos commits; a revisão será solicitada a `briankfreire`.

## Integração coordenada das camadas — 30/10/2026

- Revisão independente das mudanças de Identidade, Projetos, Backlog e Frontend
  não encontrou regressão funcional ou de segurança nos caminhos inspecionados.
  A lacuna de testes sem DOM do frontend foi corrigida com Worker e verificação
  negativa das fronteiras; a suíte final de navegador passou 124 testes sem skips.
- A suíte usa os três backends reais refatorados, SQLite/RSA temporários e os
  caminhos AUTH_BACKEND_PATH, PROJECTS_BACKEND_PATH e BACKLOG_BACKEND_PATH.
  Inclui login, perfil, projetos, backlog, convite, promoção de papel e remoção.
- O teste HTTP específico Projetos→Backlog passou com BACKLOG_SERVICE_PATH
  configurado. Não se presume teste de PostgreSQL a partir desse resultado.
- O ambiente local persistente foi reiniciado com os mesmos bancos e chave:
  readiness 200 nas três APIs, CORS 127.0.0.1:5173, login da conta de teste
  preservada e consulta de projetos 200 pelo navegador, sem erro JavaScript.
- Nenhum banco remoto, grant, configuração Azure, deploy ou dado de produção
  foi alterado. A integração PostgreSQL opt-in continua pendente nesta etapa.
- Componentes e limites das camadas estão em [architecture.md](architecture.md).
# Remaining identity stories — local validation, 30/10/2026

- Session slice: 205 passed, seven PostgreSQL tests skipped before a disposable
  database was configured. Ruff/format, mypy and wheel/sdist build passed.
- Recovery/MFA/consented directory slice: **232 passed, zero skips**, in 64.44 s,
  using temporary SQLite databases and a disposable PostgreSQL on loopback with
  randomly isolated schemas. Tests cover concurrent refresh replay on both engines,
  explicit migration preserving old users, password reset single use/concurrency,
  lockout, MFA password/challenge/recovery isolation, encrypted seeds and hashed
  tokens, administrator bootstrap, jti revocation, protected mailbox and consent.
- Ruff check/format, strict mypy and package build passed; wheel/sdist inspection
  found no local instruction, plan or `.local` artifacts. Existing exact-profile
  assertions were updated only for the additive consent field; old password-change
  expectations were updated for the approved all-session revocation policy.
- SMTP delivery used the explicitly enabled local mailbox only. No external SMTP,
  AI provider, production database, remote schema, push, merge or deployment was
  verified or changed. Cross-service/browser validation is a separate task.
