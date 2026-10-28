# Perfil profissional próprio — candidato 0.3.0

GET e PATCH `/auth/profile` exigem o Bearer de uma conta ativa. O usuário é derivado
do JWT; não há parâmetro user_id nem diretório público de perfis. GET sem registro
retorna defaults sem escrever no banco.

Resposta: user_id, summary (default vazio), seniority (not_informed),
weekly_availability_hours (0), skills ([]). PATCH parcial não vazio; campos omitidos
preservados, explícito null/extras recusados, sem edição de user_id.

- summary: texto até 2000 caracteres.
- seniority: not_informed/junior/mid/senior/lead.
- weekly_availability_hours: inteiro estrito de 0 a 168.
- skills: até 30 `{name,level}`; nome aparado 1..80 e domínio inteiro 1..5.
- Nomes duplicados após normalização NFC/casefold recusados. Lista enviada substitui
  competências; [] limpa. Texto é literal e não gera HTML executável.

GET/PATCH 200, 401 padrão AuthMe, 422 sanitizado sem eco/ctx, 503 genérico; no-store em
todas respostas. Upsert atômico atualiza só os campos fornecidos e revalida conta
ativa na mutação, evitando perda de campos em PATCHs parciais concorrentes.

Tabela própria mod1_identity.profiles com FK users. Preparação explícita e
idempotente por `python -m mod1_auth.cli init`, usando administração autorizada;
não altera contas anteriores e não existe DDL no startup. Conferir a sintaxe da
CLI no README caso o ambiente use o entrypoint mod1-auth.

Exemplo administrativo, após conferir nomes da role/schema existentes:

```sql
GRANT SELECT, INSERT, UPDATE ON mod1_identity.profiles TO mod1_auth_runtime;
```

O nome da role acima segue o guia Neon: usar a role runtime já provisionada, sem
substituir credenciais ou conceder acesso a outros schemas. Não conceder DELETE,
CREATE ou propriedade de objetos. Nenhum grant foi aplicado remotamente.

Perfil não representa alocação ou recomendação de IA, e não é visível a gestores
de outros serviços neste lote. O ID da conta já retornado em `/auth/me` aparece no
frontend para que a pessoa o compartilhe voluntariamente para convites.
