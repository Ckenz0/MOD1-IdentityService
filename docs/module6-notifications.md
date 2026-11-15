# Contrato de notificações do Módulo 6

Contrato consultado em 14/11/2026 no [OpenAPI do próprio BFF](https://software6-bff-2-cnbqhhgdcndzgwdx.chilecentral-01.azurewebsites.net/openapi.json).
Este documento registra a integração externa; não afirma que existe um emissor
automático implantado no Módulo 1.

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

## Limites da integração proposta

- CORS não é necessário para publicação entre backends. A URL do BFF não confirma
  a origem do frontend do Módulo 6.
- O enum `source` não inclui `projects`, `auth` ou `modulo1`. `backlog` pode
  identificar eventos do nosso Backlog; eventos de equipes/projetos precisam
  de um mapeamento acordado, sem se apresentar como outro módulo.
- O nome `event_id` não comprova deduplicação. Antes de habilitar reenvio
  automático, confirmar com o receptor como ele trata eventos repetidos e
  timeouts após persistência.
- Publicar somente eventos de negócio já confirmados, fora da transação de
  escrita, com estado de entrega separado das notificações internas existentes.
- O primeiro teste real deve usar evento/projeto expressamente autorizados.
  Nenhuma notificação externa foi publicada durante a descoberta deste contrato.

A implementação do emissor e seu catálogo estão nos guias de operação dos repositórios de [Backlog](https://github.com/igorcpds/MOD1-BacklogService/blob/main/docs/module6-notifications.md) e [Projetos](https://github.com/briankfreire/MOD1-ProjectsServices/blob/main/docs/module6-notifications.md). A publicação ativa somente a origem Backlog já aceita; Projetos aguarda a convenção de origem.
