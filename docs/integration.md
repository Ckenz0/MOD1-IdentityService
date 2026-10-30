# Integração com autenticação

Serviço candidato `0.2.0`. Caue mantém identidade/tokens; Brian mantém projetos, equipes e papéis por projeto; Igor mantém backlog. Cada serviço valida o token e aplica a autorização do seu domínio. Nenhum serviço deve consultar diretamente tabelas de outro.

## Configuração dos consumidores

| Parâmetro | Desenvolvimento local | Ambiente publicado |
| --- | --- | --- |
| API | `http://127.0.0.1:8000` | URL HTTPS do Container App |
| Issuer | `mod1-auth-local` | valor estável de `JWT_ISSUER` informado pelo responsável |
| Audience | `engenharia-software-api` | mesmo valor nos serviços |
| JWKS | `http://127.0.0.1:8000/.well-known/jwks.json` | URL HTTPS da API + `/.well-known/jwks.json` |

`localhost` aponta para a própria máquina; não é o endereço de entrega aos colegas. Não escolha emissor, audiência, algoritmo ou endereço JWKS pelo conteúdo recebido no token.

## Obter acesso

O MVP permite cadastro público com login imediato por `POST /auth/register`, JSON com `display_name`, `email` e `password`. Nome é aparado e deve ter 1 a 120 caracteres; e-mail válido é aparado/normalizado; senha literal segue a política pública (12 a 128 caracteres por padrão). Outros campos são recusados. Confirmação de senha é uma validação do frontend e não é enviada à API.

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

Resposta de login: `access_token`, `token_type: "bearer"`, `expires_in: 1800` (TTL padrão de 30 minutos), `Cache-Control: no-store`. Envie `Authorization: Bearer <JWT>` ao serviço de destino. Senha errada, conta inexistente e inativa retornam o mesmo 401: `{"detail":"Invalid credentials"}`, com `WWW-Authenticate: Bearer`. Formulário incompleto retorna 422. O cliente não pode escolher as claims.

`GET /auth/me` retorna apenas `id`, `email`, `display_name`, `is_active`, `created_at` UTC ISO 8601. Token ausente, inválido, usuário inexistente/inativo retornam 401 com `{"detail":"Invalid authentication credentials"}` e cabeçalho Bearer. Falha de banco retorna 503 genérico.

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
Não há migração ou DDL para esta versão. Runtime precisa de UPDATE em
`password_hash` apenas em `mod1_identity.users`; veja as concessões administrativas
em [database-neon.md](database-neon.md). Nenhuma concessão remota é automática.

Após sucesso, o frontend limpa as senhas, encerra a sessão local e exige novo login.
Isso não revoga JWTs já emitidos: permanecem utilizáveis até expirar, inclusive em
`/auth/me` e nos consumidores, com TTL residual de até 30 minutos por padrão
(`ACCESS_TOKEN_EXPIRE_MINUTES`, mais tolerância de relógio do consumidor).
Refresh e revogação continuam pendentes.

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

JWT identifica o usuário; não concede acesso global aos projetos. Os papéis PO, PM/ScrumMaster e desenvolvedor/estudante serão definidos por projeto no serviço de Brian. As verificações do backlog devem respeitar essa autorização, com timeout e recusa se não puderem determiná-la.

Conta desativada perde acesso imediato a login e `/auth/me`. Tokens já emitidos continuam válidos em consumidores offline até expirar. `jti` identifica o token; não implementa uma lista de revogação. O MVP tem uma chave ativa e não oferece refresh tokens, login social, recuperação de senha, tokens de máquina ou rotação com sobreposição. Login próprio não significa servidor OAuth/OIDC completo.

Para encerrar a pendência dos grupos: publicar uma URL HTTPS acessível, informar issuer/audience/JWKS, criar contas individuais, entregar credenciais pelo responsável e executar login/validação a partir de outra máquina.
