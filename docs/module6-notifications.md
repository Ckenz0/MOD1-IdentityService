# Contrato de notificações do Módulo 6

Contrato consultado em 14/11/2026 no [OpenAPI do próprio BFF](https://software6-bff-2-cnbqhhgdcndzgwdx.chilecentral-01.azurewebsites.net/openapi.json).
Este documento registra o contrato externo. Em 15/11/2026, os emissores de
Backlog e Projetos estão implantados e ativos; Identidade não emite esses avisos.
Veja [estado e limites da entrega](final-delivery.md).

## Publicação

`POST https://software6-bff-2-cnbqhhgdcndzgwdx.chilecentral-01.azurewebsites.net/api/integrations/notifications`

Cabeçalhos: `Content-Type: application/json` e `X-Integration-Key`, cujo valor
fica somente na configuração privada do backend emissor. O contrato dessa rota
não exige o Bearer do usuário; não o encaminhe desnecessariamente.

| Campo | Contrato observado |
| --- | --- |
| `event_id` | String obrigatória; usar identificador estável do evento |
| `scope` | `project` (padrão) ou `global` |
| `project_id` | String ou null; eventos de projeto devem identificar o projeto real autorizado |
| `source` | `code_review`, `github`, `curadoria`, `artefatos`, `rag`, `relatorios`, `backlog` ou `chat` |
| `type` | String obrigatória |
| `title` | String obrigatória |
| `body` | String obrigatória |
| `priority` | `critical`, `high`, `medium` (padrão) ou `low` |
| `link` | String ou null |
| `stack` | Array opcional de strings, no máximo 8 |
| `changed_files` | Array opcional de strings, no máximo 15 |

Sucesso documentado: HTTP 200 com objeto `Notification`. Validação de entrada:
HTTP 422. Outros erros operacionais e a semântica de duplicação não estão
detalhados no OpenAPI consultado e precisam ser tratados sem presumir sucesso.

## Limites da integração

- CORS não é necessário para publicação entre backends. A URL do BFF não confirma
  a origem do frontend do Módulo 6.
- O enum `source` não inclui `projects`, `auth` ou `modulo1`. A convenção adotada
  nesta instalação usa `source=backlog` para eventos compartilhados do Módulo 1.
  Projetos distingue os eventos por tipos `project.*` e prefixo `mod1:projects:`;
  não foi acrescentado um novo valor ao enum do receptor.
- O nome `event_id` não comprova deduplicação. Antes de habilitar reenvio
  automático, confirmar com o receptor como ele trata eventos repetidos e
  timeouts após persistência.
- Publicar somente eventos de negócio já confirmados, fora da transação de
  escrita, com estado de entrega separado das notificações internas existentes.
- O primeiro teste real deve usar evento/projeto expressamente autorizados.
  Nenhuma notificação externa foi publicada durante a descoberta deste contrato.

A implementação do emissor e seu catálogo estão nos guias de operação dos repositórios de [Backlog](https://github.com/igorcpds/MOD1-BacklogService/blob/main/docs/module6-notifications.md) e [Projetos](https://github.com/briankfreire/MOD1-ProjectsServices/blob/main/docs/module6-notifications.md). Ambos os workers estão ativos com `source=backlog`. Um aviso real de teste com
escopo de projeto foi aceito com HTTP 200; isso não comprova apresentação visual
na Central nem o percurso completo de um evento de negócio pelo outbox de produção.
Não há replay histórico nem anúncios globais.
