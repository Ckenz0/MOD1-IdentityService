# Integração com autenticação

Serviço `0.4.0` preparado para release. Caue mantém identidade/tokens; Brian mantém projetos, equipes e papéis por projeto; Igor mantém backlog. Cada serviço valida o token e aplica a autorização do seu domínio. Nenhum serviço deve consultar diretamente tabelas de outro.

O contrato atual de sessões, renovação, revogação, recuperação, MFA e diretório
consentido está em [security-and-recovery.md](security-and-recovery.md).
O transporte e os limites de destinatário estão em [resend.md](resend.md).
Esses contratos substituem as limitações das versões 0.2/0.3: migração
administrativa explícita é necessária; consumidores devem consultar `/auth/me`
com o mesmo Bearer para observar o estado atual, além de validar RS256/JWKS.

## Configuração dos consumidores

| Parâmetro | Desenvolvimento local | Ambiente publicado |
| --- | --- | --- |
| API | `http://127.0.0.1:8000` | URL HTTPS do Container App |
| Issuer | `mod1-auth-local` | valor estável de `JWT_ISSUER` informado pelo responsável |
| Audience | `engenharia-software-api` | mesmo valor nos serviços |
| JWKS | `http://127.0.0.1:8000/.well-known/jwks.json` | URL HTTPS da API + `/.well-known/jwks.json` |

`localhost` aponta para a própria máquina; não é o endereço de entrega aos colegas. Não escolha emissor, audiência, algoritmo ou endereço JWKS pelo conteúdo recebido no token.

## Obter acesso

O serviço permite cadastro público por `POST /auth/register`, JSON com `display_name`, `email` e `password`. Nome é aparado e deve ter 1 a 120 caracteres; e-mail válido é aparado/normalizado; senha literal segue a política pública (12 a 128 caracteres por padrão). Outros campos são recusados. Confirmação de senha é uma validação do frontend e não é enviada à API.

Cadastro novo e e-mail já existente recebem o mesmo **202**, `Cache-Control: no-store` e `{"message":"If this email is available, the account is ready. Try signing in."}`. A resposta não contém UUID, dados da conta ou token. Duplicidade nunca altera senha, nome ou situação da conta anterior. Dados inválidos retornam 422 sem ecoar os valores enviados; falha de banco retorna 503. Depois, o usuário faz login normalmente.

O cadastro local não verifica a posse do e-mail. Criar uma identidade não adiciona o usuário a projetos ou equipes; essas permissões continuam no domínio dos outros módulos.

O responsável cria uma conta individual usando `mod1-auth create-user`. O grupo usa o e-mail e senha recebidos para `POST /auth/token`, com `Content-Type: application/x-www-form-urlencoded` e campos `username` (e-mail) e `password` (literal, inclusive espaços). Swagger em `/docs` oferece o formulário **Authorize**.

Exemplo Python interativo, evitando senha/token em argumentos ou histórico:

```python
import getpass
import httpx

base_url = "http://127.0.0.1:8000"
email = input("E-mail: ")
with httpx.Client(timeout=5) as client:
    response = client.post(
        base_url + "/auth/token", data={"username": email, "password": getpass.getpass("Senha: ")}
    )
    response.raise_for_status()
    token = response.json()["access_token"]
    identity = client.get(base_url + "/auth/me", headers={"Authorization": "Bearer " + token})
    identity.raise_for_status()
    print(identity.json())
```

Login concluído retorna `access_token`, `token_type: "bearer"`, `expires_in`,
`refresh_token`, `session_id`, `idle_expires_at` e `absolute_expires_at`, com
`Cache-Control: no-store`.
Com MFA ativo, a resposta inicial é um desafio temporário: o cliente precisa
verificar `/auth/mfa/verify` antes de receber tokens. O exemplo acima cobre login
sem MFA. Envie `Authorization: Bearer <JWT>` ao serviço de destino. Senha errada,
conta inexistente/inativa ou bloqueada recebem erro genérico. Formulário incompleto
retorna 422; o cliente não pode escolher claims. Confira os campos em `/openapi.json`.

`GET /auth/me` informa a identidade atual e verifica sessão, revogação e conta
ativa. Seus campos atuais são definidos em `/openapi.json`; consumidores devem
validar que `id` corresponde ao `sub` e `is_active` é true. Token ausente,
inválido, revogado ou sessão/conta indisponível para uso retorna 401 com cabeçalho
Bearer; falha de dependência retorna 503 genérico.

`GET /.well-known/jwks.json` é público e contém somente `kty`, `use`, `alg`, `kid`, `n`, `e`; nunca contém chave privada. `/health/live` retorna 200 `{"status":"ok"}` sem depender do banco. `/health/ready` confirma a tabela de usuários; retorna 200 `{"status":"ready"}` ou 503 `{"status":"unavailable"}`.

## Política e troca de senha

`GET /auth/password-policy` é público e retorna `{"min_length":12,"max_length":128}`.
O mínimo segue `PASSWORD_MIN_LENGTH` (12–128, padrão 12); o máximo é sempre 128.
A mesma política vale para cadastro, CLI e troca. Alterar o mínimo não impede login
de contas anteriores. As senhas são literais: espaços e Unicode não são aparados.

`POST /auth/password` usa o mesmo Bearer de `/auth/me` e JSON
`{"current_password":"...","new_password":"..."}` sem campos extras. Ambas são
strings de até 128 caracteres; a nova precisa satisfazer a política configurada.
Altera somente a senha da própria conta ativa. Sucesso é **204 sem corpo**;
senha atual errada ou nova igual retorna **400** com
`{"detail":"Password change rejected"}`. Token ausente/inválido ou conta
inexistente/inativa retorna o mesmo **401** de `/auth/me`, com
`WWW-Authenticate: Bearer`. Dados inválidos retornam **422** sem ecoar senhas;
banco indisponível retorna **503** `{"detail":"Service unavailable"}`.
Todas as respostas dessas duas rotas incluem `Cache-Control: no-store`.

O UPDATE verifica UUID, hash anterior e conta ativa na própria instrução SQL;
duas trocas simultâneas usando a mesma senha anterior não podem ambas gravar.
Um conflito recebe o mesmo 400 e exige nova autenticação/verificação pelo usuário.
Esta versão exige migração explícita para sessões, recuperação e MFA; startup
não executa DDL. Runtime acessa somente seu schema, incluindo tabelas de sessão e
auditoria; veja as concessões administrativas em [database-neon.md](database-neon.md)
e [security-and-recovery.md](security-and-recovery.md). Nenhuma concessão remota é automática.

Após sucesso, o frontend limpa as senhas, encerra a sessão local e exige novo login.
Troca e reset de senha revogam todas as sessões, inclusive a atual. `/auth/me`
recusa seu uso; Projetos e Backlog verificam esse estado online por padrão.
Validadores que consultam apenas assinatura/expiração continuam sujeitos ao TTL
residual. Refresh e revogação já fazem parte do contrato 0.4.0.

## Validar no seu serviço

Copie `examples/validate_token.py` para o seu serviço ou adapte sua função; depende apenas de `PyJWT[crypto]`, sem importar a API emissora. Reutilize o cliente JWKS no processo (cache de 5 minutos, timeout de rede de 5 segundos). O exemplo ignora `jku` enviado no token e usa somente a fonte configurada. HTTP é aceito apenas em loopback para desenvolvimento; use HTTPS remotamente.

```python
from validate_token import ValidationError, validate_token

try:
    claims = validate_token(
        token,
        issuer="mod1-auth-local",
        audience="engenharia-software-api",
        jwks_url="http://127.0.0.1:8000/.well-known/jwks.json",
    )
    user_id = claims["sub"]
except ValidationError:
    # Traduzir para 401 no framework usado pelo consumidor.
    raise
```

CLI para validar sem imprimir o JWT:

```console
uv run --locked python examples/validate_token.py --issuer mod1-auth-local --audience engenharia-software-api --jwks-url http://127.0.0.1:8000/.well-known/jwks.json
```

O perfil exige RS256, header `typ=JWT`, `kid` não vazio, `sub` e `jti` como UUIDs, `iss` exato, `aud` como string exata, `iat`/`exp` inteiros (não booleanos ou strings), `exp > iat`. Valida assinatura, expiração e emissão futura com tolerância de 5 segundos. Fixe `algorithms=["RS256"]`; nunca aceite `none` ou HMAC como alternativa.

Para PEM offline, obtenha a chave pública por canal confiável/JWKS HTTPS e salve fora do Git. Conversão após baixar JWKS confiável:

```python
import json
from pathlib import Path
import jwt
from cryptography.hazmat.primitives import serialization

jwks = json.loads(Path("trusted-jwks.json").read_text())
public = jwt.PyJWK.from_dict(jwks["keys"][0]).key
Path("auth-public.pem").write_bytes(
    public.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
)
```

Use `--public-key-path auth-public.pem` em lugar de `--jwks-url`. Com a chave já carregada, o consumidor pode validar tokens durante indisponibilidade do emissor. Sem chave utilizável, recuse o token; nunca aceite por indisponibilidade do JWKS.

## Limites de autorização e revogação

JWT identifica o usuário; não concede acesso global aos projetos. Papéis fixos e
personalizados, equipes e concessões são definidos por projeto no serviço de
Brian. Backlog confirma permissões em `/access/v2`, com timeout e recusa se não
puder determinar autorização.

Conta desativada perde acesso a login e `/auth/me`. Sessões e `jti` podem ser
revogados; refresh opaco é rotativo e reutilização revoga a família. Tokens ainda
podem passar em consumidores offline até expirar: validar assinatura não substitui
verificar sessão atual. Login social, tokens de máquina e rotação de chaves com
sobreposição não são oferecidos. Login próprio não significa servidor OAuth/OIDC completo.

Para encerrar a pendência dos grupos: publicar uma URL HTTPS acessível, informar issuer/audience/JWKS, criar contas individuais, entregar credenciais pelo responsável e executar login/validação a partir de outra máquina.
