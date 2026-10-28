# Changelog

## 0.3.0 — candidato local, 2026-10-28

### Added

- Perfil profissional privado com resumo, senioridade, disponibilidade e até 30 competências com domínio de 1 a 5.
- GET sem escrita e PATCH parcial atômico, derivando usuário do Bearer e recusando extras/null/duplicatas.
- Nova tabela própria profiles, criada apenas por preparação administrativa explícita; sem DDL no startup.
- Testes de isolamento, concorrência e persistência PostgreSQL; evolução MINOR local.

Mudanças de produto seguem Keep a Changelog e SemVer. A versão candidata do pacote é `0.3.0`; nenhuma release publicada é presumida.

## 0.2.0 — candidato local, 2026-10-28

### Added

- Consulta pública da política de senha e troca autenticada da própria senha, com senha literal, hash Argon2, respostas sem cache e validação sem ecoar segredos.
- `PASSWORD_MIN_LENGTH` entre 12 e 128, padrão 12, aplicado no cadastro, CLI e troca; máximo fixo 128.
- Atualização condicionada ao hash anterior e à conta ativa para impedir duas trocas concorrentes com a mesma senha anterior. Nenhuma mudança de schema.

### Security

- JWTs emitidos permanecem válidos até o TTL residual (padrão 30 minutos); revogação e refresh não fazem parte desta versão.
- Runtime precisa de UPDATE em `password_hash` da tabela própria; concessões continuam sendo operações administrativas explícitas.

## Unreleased

### Added

- Infraestrutura Bicep integrada Azure + Neon: bootstrap separado das APIs, identidades por serviço, segredos com escopo individual e escala a zero.
- Workflows manuais OIDC por digest, checks de imagem e guia completo de configuração, validação e rollback.

- API Python/FastAPI em camadas, PostgreSQL/SQLAlchemy e conexão com Neon.
- Contas individuais persistentes, hashing Argon2 e administração local por CLI.
- Cadastro público com login imediato, validação de dados e resposta uniforme para e-mails já cadastrados, preservando senha e situação da conta existente.
- Login JWT RS256 com perfil estrito, chave RSA persistente e JWKS público.
- Consulta de identidade, saúde, OpenAPI e CORS explícito.
- Exemplo consumidor independente com JWKS ou PEM público.
- Testes de segurança, HTTP, CLI, persistência e integração PostgreSQL opt-in.
- Dependências travadas, Ruff, mypy estrito, Docker/Compose e template Azure Container Apps.

### Removed

- Scripts de impressão e conteúdo de teste inicial, substituídos pela aplicação.
