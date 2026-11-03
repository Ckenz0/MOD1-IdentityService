# Gemini para análise de acessos

O candidato local 0.5.0 inclui o adaptador Gemini na infraestrutura. A aplicação
continua responsável por autorização, evidências, contexto e decisões; o domínio
valida o formato. Não há mudança de schema, migração de dados ou concessão de
acesso pela IA. Consulte também [a arquitetura](architecture.md).

## Configuração privada do backend

O padrão `AI_PROVIDER=structured-http` preserva `AI_BASE_URL`, `AI_API_KEY`,
`AI_MODEL` e `AI_SIMULATED`. Sem URL configurada, criar recomendações retorna 503
sem chamada externa. O modo Gemini exige opt-in explícito:

```dotenv
AI_PROVIDER=gemini
AI_SIMULATED=false
GEMINI_MODEL=gemini-3.5-flash-lite
GEMINI_TIMEOUT_SECONDS=30
GEMINI_MAX_OUTPUT_TOKENS=4096
GEMINI_API_BASE_URL=https://generativelanguage.googleapis.com/v1beta
```

Forneça `GEMINI_API_KEY` por variável privada do backend, nunca no frontend,
repositório ou logs. Chave ausente produz 503 sem HTTP; a configuração não troca
automaticamente de provedor. Gemini não usa `AI_API_KEY`, `AI_BASE_URL` ou
`AI_MODEL` e rejeita `AI_SIMULATED=true`. Metadados públicos retornam
`provider=gemini`, o modelo configurado e `simulated=false`, inclusive ao usar
um mock controlado. Esse metadado identifica o modo, sem comprovar execução real.

O modelo escolhido possui faixa gratuita conforme a documentação consultada
em 03/11/2026. O projeto/chave determina quotas e eventual cobrança; o aplicativo
não altera faturamento nem promete gratuidade ilimitada. Não há retry automático,
fallback para outro modelo, ferramentas ou pesquisa.

## Transporte e limites

O adaptador envia POST para `{GEMINI_API_BASE_URL}/models/{GEMINI_MODEL}:generateContent`
com `x-goog-api-key`, sem Bearer do usuário ou chave na URL. O host permitido é
`generativelanguage.googleapis.com` via HTTPS na porta padrão, caminho `/v1beta`;
para simulações permite HTTP em `127.0.0.1`, `localhost` ou `::1` com o mesmo caminho.
Não permite userinfo, query, fragmentos, traversal ou escapes no modelo.
Redirects e proxies de ambiente permanecem desabilitados.

Timeout configurável de 1–30 segundos, saída de 256–8192 tokens (padrão 4096),
contexto serializado até 128 KiB e resposta HTTP até 256 KiB. O request usa
`contents` com JSON de `kind=access_anomalies` e `context`, instruções em português
em `systemInstruction` e `generationConfig.responseFormat.text` com
`mimeType=APPLICATION_JSON` e schema do contrato. Descrições do contexto são
dados não confiáveis, nunca instruções. Ausência de evidência não autoriza
inventar pessoas, ações, custos, habilidades ou inatividade.

A resposta exige exatamente um candidato com `finishReason=STOP`. Partes
`thought=true` não entram no JSON final; chamadas de função, bloqueio, truncamento,
JSON inválido, forma incorreta, UUIDs inválidos ou tamanho excessivo retornam 503
sanitizado. Evidências e usuários inventados também são recusados na aplicação.
Falhas de quota, servidor ou timeout não persistem proposta nem alteram contas.

## Decisão humana e resultado vazio

Somente administradores autenticados geram/decidem recomendações. Evidências
devem existir nos eventos do contexto e usuários devem pertencer ao conjunto
autorizado. Mudança de contexto e expiração continuam verificadas ao decidir.
Aprovar uma proposta registra a decisão humana sem conceder/revogar acesso.

Sem ação fundamentada, `suggestions=[]` é válido; `summary` e `justification`
continuam obrigatórios. Sem eventos relevantes, `evidence=[]` também é válido.
Essa proposta pode ser consultada ou rejeitada. Tentativa de aprovação retorna
409 sem mudar status, versão, auditoria ou acessos.

## Validação local e pendência real

Os testes usam SQLite temporário e `httpx.MockTransport`, sem chave real,
chamada de nuvem, dados de produção ou publicação. Exercitam request oficial,
saída válida/vazia, dados inventados, controle administrativo, quota 429, 5xx,
timeout, redirects, JSON inválido/truncado, limites e configuração maliciosa.

Em 03/11/2026, após revisão independente, a suíte completa registrou
**336 aprovados e 8 ignorados**
(PostgreSQL sem configuração local descartável). Ruff, verificação de formato,
mypy e fronteiras AST passaram. O baseline direcionado tinha 17 testes aprovados;
os novos casos falharam antes da implementação e passaram após a mudança.
As regressões da revisão cobrem bloqueios em `safetyRatings` mesmo com STOP,
portas HTTP inválidas, marcador `thought` booleano e metadado `thoughtSignature`
em texto final. O adaptador recebe apenas um transporte injetável e cria cliente
próprio, sem herdar autenticação, cookies ou headers de clientes dos consumidores.

```powershell
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
.venv/Scripts/python.exe -m mypy
```

Testes PostgreSQL só devem receber um `TEST_DATABASE_URL` de loopback descartável;
sem essa configuração ficam explicitamente ignorados. Não usar Neon ou outro
banco remoto. Não houve validação de modelo, latência ou quotas Gemini reais:
ela permanece pendente e deve usar apenas dados sintéticos, orçamento limitado
e configuração privada quando autorizada no ambiente de teste.

Contrato oficial: [GenerateContent](https://ai.google.dev/api/generate-content),
[modelo](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite) e
[preços e quotas](https://ai.google.dev/gemini-api/docs/pricing).
