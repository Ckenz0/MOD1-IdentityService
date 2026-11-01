# Sessões, recuperação e MFA

Implementação local com quatro camadas: contratos HTTP em `identity_api.py`,
casos de uso em `identity_service.py`, `credential_service.py` e
`recommendation_service.py`, contratos puros em `domain.py`, `profiles.py` e
`recommendations.py`, persistência/criptografia/envio/HTTP nos adaptadores.
O frontend e os consumidores não consultam diretamente o banco de identidade.

## Política de sessão

- JWT RS256 contém identificador de sessão. Refresh opaco é armazenado por hash,
  consumido atomicamente e rotacionado. Reutilização revoga a família.
- Inatividade padrão de 15 minutos; limite absoluto de 8 horas. Apenas atividade
  do usuário em primeiro plano renova o prazo de inatividade, respeitando o limite
  absoluto. Requisições de fundo não contam como atividade.
- Logout, revogação por sessão, revogação total e desativação são verificados
  online por Projetos e Backlog. Indisponibilidade retorna 503; a interface mantém
  formulários e permite nova tentativa. Não há cache positivo de autorização.
- Cinco falhas em 15 minutos bloqueiam por 15 minutos, por padrão. Respostas de
  login permanecem genéricas. Administrador global pode desbloquear e revogar.
- Troca e redefinição de senha revogam todas as sessões, inclusive a atual.
  Login revalida o hash dentro da transação para não aceitar senha substituída
  durante a verificação. Refresh compartilhado no navegador sobrevive à troca de
  tela, e nunca restaura uma conta que já saiu.

## Recuperação, confirmação e segundo fator

Tokens de recuperação/validação são de uso único, com finalidade e hash no banco.
Recuperação vence em 30 minutos; confirmação em 24 horas. A resposta ao pedido de
recuperação não revela existência de conta. Se nenhum transporte estiver
configurado, retorna 503 uniformemente.

Links usam fragmentos `#recovery=` ou `#verify-email=`. A interface remove o
fragmento e transmite o segredo somente no corpo do POST. Não grava credenciais
em localStorage/sessionStorage. Uma conta sem e-mail confirmado pode entrar;
confirmar e-mail não concede papéis.

MFA usa TOTP SHA-1, seis dígitos e janela de um passo. O segredo fica cifrado com
`MFA_ENCRYPTION_KEY`, independente da chave JWT. Configuração exige senha atual e
confirmação do primeiro código. Códigos de recuperação são exibidos uma vez,
armazenados por hash e consumidos atomicamente. Um código temporal não pode ser
reutilizado. Login em duas etapas só emite JWT depois do fator. Redefinir senha
não remove nem ignora o MFA.

## Administração e configuração

Bootstrap explícito: `mod1-auth set-admin --user-id UUID --admin`.
Product Owner e PM de projeto não se tornam administradores globais.
`init`/`migrate` são comandos administrativos explícitos e preservam dados;
subir a aplicação não executa DDL. Faça backup antes de migrar um banco existente.

`LOCAL_MAILBOX_ENABLED=true` oferece caixa postal de desenvolvimento somente a
administradores em `/admin/mailbox`. Não representa entrega de e-mail real.
O transporte escolhido para envio real é o [Resend](resend.md), com chave secreta
e remetente verificado no backend. SMTP legado permanece compatível. Envio real
requer configuração e validação externa separadas.
Não inclua segredos nos arquivos de configuração públicos ou no Git.

## Recomendações de anomalias

`/admin/recommendations` usa um adaptador HTTP estruturado, desabilitado sem
`AI_BASE_URL`. Envia apenas eventos reais de auditoria e identificadores/estado
das contas envolvidas, sem senha, token ou e-mail. Resposta tem limite de tamanho,
ações de revisão conhecidas e evidências que precisam existir no contexto.
Propostas têm versão e expiração, são revalidadas antes da decisão e exigem
aprovação humana. Aprovar uma análise registra a decisão; não revoga, desativa
ou concede acesso automaticamente. `AI_SIMULATED=true` identifica simulação.
Nenhum provedor real foi validado nesta entrega local.

## Evidência

`tests/test_sessions.py`, `test_identity_hardening.py`, `test_recovery_mfa.py`,
`test_postgresql.py` e `test_recommendations.py` exercitam as políticas.
No frontend, `test_session_security.py`, `test_refresh_cancellation.py` e
`test_advanced_real_api.py` cobrem renovação, navegação, MFA e recuperação.
Suítes de PostgreSQL destrutivas usam somente loopback descartável.
