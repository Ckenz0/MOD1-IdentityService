# Validação CORS em produção — 15/11/2026

As três APIs do Módulo 1 foram verificadas após a atualização de `CORS_ORIGINS`
aplicada pelo responsável no Azure Cloud Shell. As consultas ARM confirmaram
revisões prontas, estado `Healthy` e preservação das imagens anteriores:

| API | Revisão pronta | Preflights aprovados |
| --- | --- | --- |
| Identidade | `mod1-auth--0000008` | 20/20 |
| Projetos | `mod1-projects--0000008` | 4/4 |
| Backlog | `mod1-backlog--0000007` | 12/12 |

## Origens verificadas

- `https://green-river-02e44e810.2.azurestaticapps.net` — frontend atual do Módulo 1.
- `https://mackai-conversas.calmfield-d7c6c49f.brazilsouth.azurecontainerapps.io` — Módulo 7.
- `http://localhost:5173` — desenvolvimento autorizado.
- `https://ai-platform-github-service-eduardo-frapb8fbbcd0bfdm.brazilsouth-01.azurewebsites.net` — Módulo 2.

As listas adicionais estão em `deploy/azure/cors-origins.json`; o módulo Bicep
preserva a origem primária por `union`. A alteração de infraestrutura permanece
na branch local `ops/mackai-cors`; esta verificação não implica publicação de
código nem implantação das mudanças locais Gemini/Resend.

## Verificações e limites

Os 36 preflights conferiram HTTP 200, `Access-Control-Allow-Origin` igual à origem
enviada, método permitido e cabeçalhos `Authorization`/`Content-Type` permitidos.
Identidade cobriu POST em `/auth/token`, `/auth/mfa/verify`, `/auth/refresh`,
`/auth/logout` e GET em `/auth/me`. Projetos cobriu GET em `/projects`. Backlog
cobriu GET/POST em `/projects/{id}/items` e PATCH em `/projects/{id}/items/{id}`.
Os UUIDs sintéticos dos preflights não foram usados para executar operações.

As seis consultas `/health/live` e `/health/ready` retornaram HTTP 200. Uma origem
não autorizada permaneceu sem permissão CORS em cada API. GET `/auth/me` e
`/projects` sem Bearer continuaram retornando 401 com cabeçalho CORS correto.
O JWKS retornou 200 com chaves públicas.

Esses testes foram somente leitura e OPTIONS: não fizeram login, não criaram
contas/projetos/itens, não enviaram notificações e não alteraram dados. Eles
comprovam a liberação CORS observada, sem comprovar o fluxo completo dos clientes
externos. A publicação de notificações no Módulo 6 é uma integração separada.

## Diagnóstico da ativação anterior

As revisões `0000007` de Identidade e Projetos falharam porque `CORS_ORIGINS`
estava vazio. O mesmo valor reproduziu `SettingsError` localmente; o JSON de
quatro origens foi aceito. A correção passou o JSON diretamente a
`--set-env-vars`, sem depender de uma variável de terminal previamente definida.
As novas revisões ativaram preservando os digests das imagens.
