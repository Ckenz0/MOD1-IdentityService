# Verificação do candidato 0.1.0 — 11/10/2026

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
