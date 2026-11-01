# E-mails transacionais com Resend

Recuperação e confirmação usam o mesmo contrato HTTP do módulo. O transporte
Resend fica em `resend_adapter.py`, dentro da infraestrutura, reutilizando httpx.
Não há chave no frontend, dependência do SDK nem mudanças no formato dos links.

## Configuração

Configure somente no backend, por segredo de ambiente ou `.env` ignorado:

```dotenv
MAIL_PROVIDER=resend
RESEND_API_KEY=re_SUBSTITUA_PELA_CHAVE_SECRETA
RESEND_FROM=Modulo 1 <access@SEU_DOMINIO_VERIFICADO>
RESEND_TIMEOUT_SECONDS=5
LOCAL_MAILBOX_ENABLED=false
FRONTEND_ORIGIN=http://127.0.0.1:5173
```

Use um remetente autorizado em seu domínio verificado. Uma chave com permissão
de envio e escopo restrito ao domínio é suficiente; não é necessário liberar
gerenciamento da conta. [Permissões de chave do Resend](https://resend.com/changelog/new-api-key-permissions).
O domínio, DNS e remetente são configurados na conta do usuário; este código não
cria nem altera esses recursos automaticamente.

`resend` exige chave e remetente válidos. Se faltar configuração, o serviço falha
de forma explícita, sem encaminhar para SMTP ou caixa postal. `auto` preserva a
compatibilidade: caixa postal local habilitada, depois Resend quando configurado,
depois SMTP legado. Configuração parcial de Resend não vira fallback silencioso.
`local` exige a caixa de desenvolvimento habilitada; `disabled` impede envios.

## Contrato e proteção de segredos

O adaptador usa exclusivamente `POST https://api.resend.com/emails`, com Bearer,
User-Agent, remetente, destinatário, assunto e corpo em texto simples.
[Contrato oficial de envio](https://resend.com/docs/api-reference/emails/send-email).
Cada payload completo recebe uma chave de idempotência por hash, sem endereço ou
token no header. Mesmo payload reutiliza a chave; mensagem diferente usa outra.
O Resend mantém a idempotência por 24 horas; isso não cria uma transação distribuída
entre o banco local e o provedor. [Idempotência do Resend](https://resend.com/docs/dashboard/emails/idempotency-keys).

Não há redirecionamento, proxy herdado ou retentativa automática. O timeout é
configurável (padrão 5 segundos por fase HTTP, máximo 30), e a resposta tem limite
de 16 KiB. Apenas 200 com identificador UUID válido confirma aceitação pelo
provedor. JSON malformado/profundamente aninhado, falhas HTTP e timeout viram erro
genérico; chave, link e mensagem privada do provedor não são retornados ou logados.

Tokens continuam armazenados por hash, com propósito, expiração e uso único.
Troca/reset revogam sessões e recuperação não ignora MFA. Os links usam fragmento
no endereço e o frontend o remove antes de transmitir o token por POST.

Pedidos públicos de reset mantêm o mesmo corpo/status 202 para contas existentes
ou ausentes quando o transporte está configurado, inclusive em falha do Resend.
A credencial da tentativa fracassada é revertida, a falha é auditada sem conteúdo
do e-mail e o cooldown também se aplica ao erro. Sem transporte configurado,
503 permanece uniforme antes da busca da conta. A resposta pública não garante
entrega ou existência de conta. Falhas autenticadas de confirmação retornam 503.

## Validação

`tests/test_resend_mail.py` exercita o contrato com transporte HTTP controlado,
sem envio externo: Bearer/User-Agent, seleção de transporte, idempotência,
redirecionamento, 401/403/409/429/5xx, timeout, limites/JSON, rollback/cooldown,
respostas públicas e os fluxos reais de credenciais de reset/confirmação.

Um teste real exige chave, remetente e destinatário explicitamente autorizados.
Aceitação da API não é prova de chegada à caixa de entrada. Endereços especiais
`delivered@resend.dev` simulam eventos e não comprovam entrega a uma pessoa;
também consomem cota. [Endereços oficiais de teste](https://resend.com/docs/dashboard/emails/send-test-emails).
Em 01/11/2026, uma mensagem genérica de teste foi aceita e recebida, confirmada
pelo usuário. Foi usado `onboarding@resend.dev`, sem domínio verificado: o envio
fica restrito ao destinatário autorizado da conta. Não foram validados links
reais de recuperação/confirmação nessa mensagem. Esses fluxos têm evidência local
com HTTP controlado; não marcar US-006/011 integralmente concluídas externamente
a partir desse teste. Veja [evidências e limites](resend-verification.md).
