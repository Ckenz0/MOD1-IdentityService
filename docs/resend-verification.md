# Verificação do transporte Resend

## Fluxos completos com Resend real — 15/11/2026

Confirmação e recuperação de senha passaram com Edge, três APIs temporárias e
bancos SQLite isolados. O teste opt-in `tests/test_resend_real_api.py` fica no
[repositório Frontend](https://github.com/Ckenz0/MOD1-WebFrontend) e reutiliza o
fluxo avançado de conta. Exige `RUN_RESEND_E2E=1`, `RESEND_API_KEY`,
`RESEND_FROM`, `RESEND_TEST_TO` e os caminhos dos três backends. Segredos são
fornecidos pelo ambiente privado, nunca pelo navegador ou documentação.

- Duas mensagens reais foram enviadas ao destinatário configurado. `GET /emails`
  e `GET /emails/{id}` recuperaram as mensagens e os links, com `last_event`
  reportando `delivered`, `opened` ou `clicked`.
- Os links retornados pelo provedor foram usados no navegador. Confirmação e
  reset recusaram replay com 400; o fragmento foi removido da URL.
- A senha anterior foi recusada com 401; o JWT anterior foi recusado nas três
  APIs depois do reset. MFA permaneceu ativo.
- Nenhum dado de produção foi alterado. O status de entrega é reportado pelo
  provedor; essa rodada não inclui inspeção humana da caixa de entrada.

O domínio `ckenzo.me` está verificado e o remetente de produção é
`Módulo 1 <noreply@ckenzo.me>`, com caixa local desativada.
[Versão e deploy](final-delivery.md) e
[reprodução no Frontend](https://github.com/Ckenz0/MOD1-WebFrontend/blob/main/docs/email-acceptance.md).

## Transporte controlado — 31/10/2026

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
como compatível. Naquela etapa, a IA permanecia pendente; o estado publicado posterior está no [registro de entrega](final-delivery.md).

Contrato e operação: [resend.md](resend.md).
