# Verificação do transporte Resend — 31/10/2026

Escopo local, sem deploy ou envio externo. Base `f837559`.

- RED: campos de configuração e adaptador HTTP inexistentes; validação ausente.
- GREEN: 26 testes de wire/credenciais, modo explícito, idempotência, respostas
  do provedor, timeout, reset e confirmação reais contra o transporte controlado.
- RED: conta existente recebia 503 durante falha do provedor e ausente recebia
  202. Corrigido para corpo/status públicos iguais, rollback da credencial,
  auditoria sem conteúdo privado e cooldown também na tentativa fracassada.
- Revisão independente reproduziu RecursionError em JSON profundamente aninhado
  dentro do limite de tamanho. Regressão RED/GREEN garante sanitização.
- Mais três casos cobrem seleção automática do Resend, configuração parcial sem
  fallback SMTP e modo desabilitado mesmo com caixa postal local habilitada.
- Suíte completa de Identidade: **268 testes passaram, sem skips**, em 68,87 s,
  incluindo PostgreSQL 17 descartável em loopback. Ruff/formato e mypy aprovados.
  A fronteira arquitetural do adaptador está incluída nessa execução.

## Evidência posterior — 01/11/2026

Uma mensagem genérica de teste de transporte foi aceita pelo Resend e recebida
na caixa de entrada, com confirmação do usuário. O remetente usado foi
`onboarding@resend.dev`; a conta não tinha domínio verificado. Esse modo restringe
destinatários ao e-mail autorizado da própria conta e não demonstra envio geral.
Nenhuma chave ou endereço privado pertence a esta documentação.

Esse envio não continha links reais de recuperação/confirmação. Os fluxos completos
de credenciais continuam validados localmente com HTTP controlado; um teste de
transporte recebido não comprova sua execução externa ponta a ponta nem encerra
as limitações operacionais das US-006/011. A evidência não comprova deploy.

A integração externa de revisão (US-096) continua dependendo do contrato real do
outro grupo; o ingresso proposto já existente não foi habilitado ou apresentado
como compatível. A IA permanece pendente por orientação do usuário.

Contrato e operação: [resend.md](resend.md).
