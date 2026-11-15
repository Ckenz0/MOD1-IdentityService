# Entrega de Identidade — 15/11/2026

A versão `0.5.0` está publicada na Azure. Este registro descreve o estado
verificado nesta data; os documentos com datas anteriores preservam suas
evidências históricas. [README e execução](../README.md).

| Evidência de publicação | Referência |
| --- | --- |
| Versão do pacote/OpenAPI | `0.5.0` |
| Commit de produção | [e4a2e701](https://github.com/Ckenz0/MOD1-IdentityService/commit/e4a2e70130d2bf80b5425e24b06d69d00b107275) |
| Integração | [PR #21](https://github.com/Ckenz0/MOD1-IdentityService/pull/21) |
| Deploy concluído com sucesso | [GitHub Actions 43728511622](https://github.com/Ckenz0/MOD1-IdentityService/actions/runs/43728511622) |

Não foi criada tag ou GitHub Release nessa publicação. Versões integradas:
Identidade 0.5.0, Projetos 0.6.0, Backlog 0.5.0 e Frontend 0.6.0.

## Integrações ativas

- Gemini real nas três APIs: `AI_PROVIDER=gemini`, `AI_SIMULATED=false` e
  `GEMINI_MODEL=gemini-3.5-flash-lite`. Os sete tipos dos adaptadores tiveram
  chamadas reais HTTP 200 com contexto sintético autorizado: análise de acessos,
  papéis, revogação, equipes, mapa de habilidades, treinamento e backlog inicial.
  A aprovação permanece humana; transporte validado não garante a qualidade de
  todos os cenários ou disponibilidade futura. [Contrato Gemini](gemini.md).
- CORS publicado nas três APIs para as origens aprovadas de GitHubSync
  (Módulo 2) e MackAI (Módulo 7), preservando frontend M1 e localhost 5173.
  Após os deploys, 36/36 preflights passaram; origens negativas foram bloqueadas
  e a ausência de Bearer continuou retornando 401 com CORS correto.
- Notificações de Backlog e Projetos ao Módulo 6 ativas, com workers separados
  e `source=backlog`. Identidade não emite esses eventos. Há um aceite real
  HTTP 200 de aviso com escopo de projeto, sem inspeção visual da Central.
  [Contrato e operação](module6-notifications.md).

## Evidências de Identidade

- CI final aprovado com testes, lint, tipos, auditoria de dependências e build.
  A suíte local anterior ao ajuste final de segurança teve 354 aprovados e
  8 ignorados; os 8 casos PostgreSQL foram executados separadamente em Docker
  local descartável e passaram.
- Login, verificação da assinatura JWT, `/auth/me` e logout foram exercitados
  em produção com uma conta sintética já existente. O JWT foi recusado com 401
  nas três APIs após logout.
- Resend real está configurado com domínio `ckenzo.me` verificado, remetente
  `Módulo 1 <noreply@ckenzo.me>` e `LOCAL_MAILBOX_ENABLED=false`. Um envio
  de teste desse domínio foi recebido e confirmado pelo usuário em 14/11.
- Em 15/11, confirmação e reset completos passaram no Edge com Resend real,
  três APIs temporárias e bancos SQLite isolados. Duas mensagens foram
  recuperadas pela API do provedor após ele reportar entrega; os links reais
  foram exercitados, com uso único, remoção do fragmento, senha antiga
  recusada, revogação da sessão nas três APIs e MFA preservado. Essa rodada
  não alterou dados de produção nem inspecionou humanamente a caixa de entrada.
  [Evidência e reprodução](resend-verification.md).

Identidade não emite avisos externos do Módulo 6. As chaves privadas, os segredos
de e-mail/IA e as credenciais de banco permanecem somente nos backends.

## Validação e limites comuns

As seis rotas públicas de saúde das três APIs responderam 200. A chave
JWT/JWKS existente e os dados anteriores foram preservados. O deploy incremental
manteve configurações de CORS, e-mail, MFA e segredos; migrações aditivas foram
executadas explicitamente, sem DDL no startup ou testes destrutivos em banco
remoto. API, aplicação, domínio e infraestrutura mantêm a
[arquitetura multicamadas](architecture.md).

O navegador em produção cobriu login, perfil, projetos e logout, em desktop e
mobile, sem overflow ou erros de página observados. Em ambiente isolado, o Edge também exerceu os sete tipos reais de Gemini,
persistência após reinício, aprovação idempotente de papéis/backlog, rejeição
e expiração de proposta após mudança de contexto. Equipes retornou vazio
válido; seu caminho positivo continua coberto pelos testes controlados.
[Aceite e reprodução de IA](https://github.com/Ckenz0/MOD1-WebFrontend/blob/main/docs/local-ai-testing.md).

O aceite do Módulo 6 comprova transporte e confirmação de um aviso autorizado,
não o percurso completo de um novo evento de negócio pelo outbox de produção
nem sua apresentação na Central. Não há replay de histórico, anúncios globais ou
emissão de eventos privados não mapeados. O contrato externo de revisão de código
US-096 permanece pendente e desabilitado.

Comandos reproduzíveis e evidências históricas estão em
[verification.md](verification.md); operação e rollback em
[deploy-azure.md](deploy-azure.md).

## Fechamento da rastreabilidade

O escopo do Módulo 1 tem 99 US implementadas com evidências de teste e
uma dependência externa aberta, US-096. US-101 duplica US-009.
A aprovação de equipes com saída não vazia do Gemini não foi exercitada
nessa rodada: a análise real vazia foi dispensada sem efeitos. Isso não
substitui os testes controlados de aplicação/notificação desse tipo.
[Matriz e limites do aceite](https://github.com/Ckenz0/MOD1-WebFrontend/blob/main/docs/backlog-status.md).
Os commits finais de documentação não alteram a versão nem o contrato
HTTP destes backends. O frontend 0.6.1 acrescenta as correções de permissões
e navegação descritas em seu changelog; `/release.json` identifica o SHA
efetivamente implantado.
