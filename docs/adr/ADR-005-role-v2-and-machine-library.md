# ADR-005 — Contrato `role-v2`, biblioteca oficial e banco SQLite da máquina

- **Estado:** proposto
- **Data:** 22/10/2026
- **Decisores:** Paulo Cesar Benjamin Junior, core maintainer
- **Issue:** #144
- **Relaciona-se a:** ADR-001, que escolheu SQLite como armazenamento operacional
  local e JSON como formato de autoria

## Contexto

O contrato público `role-v1` guarda o comportamento da role num único texto
(`instructions`). A biblioteca de roles do HubICG evoluiu para um contrato
composável, com três elementos que o `role-v1` não consegue representar:

- **foundations**: fundamentos compartilhados, definidos uma vez e compostos por
  várias roles;
- **proficiência P0–P4**: nível e escopo por ferramenta, com o limite de
  decisão escrito no escopo;
- **blocos**: seções nomeadas (quando usar, responsabilidades, limites, prompt).

Em 22/10/2026 o responsável decidiu três coisas:

1. todas as 65 roles e as 17 foundations vêm para o Community;
2. elas entram num novo contrato público, e o CLI lê os dois contratos;
3. o Community distribuído traz essa biblioteca, e ela é copiada para um banco
   SQLite **da máquina**, usando JSON.

O ADR-001 previa SQLite por projeto (`.hubicg/state/roles.db`) e reservava a
origem `official` sem implementá-la.

## Decisão

1. **Contrato `role-v2`** (`schemas/role-v2.schema.json`, `schemaVersion: "2.0"`)
   e **contrato de foundation** (`schemas/foundation.schema.json`). O `role-v1`
   não muda. O CLI valida cada role pelo contrato que ela declara, e
   `role_text` dá às duas formas um texto único para busca, seleção, exportação
   e adaptadores. É uma nova versão maior de schema, como a política de
   compatibilidade exige, e não um campo novo no `role-v1`.
2. **Biblioteca oficial empacotada** em `src/hubicg/library/`, com
   `manifest.json` (SHA-256 por arquivo, contagens, licença e proveniência).
   Ela vai no wheel e no sdist. `scripts/import_role_library.py` a gera de forma
   determinística e expande os blocos compartilhados, para que cada role
   publicada seja autocontida.
3. **Banco da máquina** `library.db`, no diretório de dados do usuário de cada
   plataforma, com `HUBICG_HOME` e `--home` como override. Ele reusa o schema 1
   do banco de roles sem alterá-lo e acrescenta a tabela `foundations`. Por ser
   outro arquivo, nenhum banco de projeto existente é migrado.
4. **JSON no SQLite.** Role e foundation são guardadas como JSON canônico em
   `payload_json`. A ligação entre role e foundation é a view
   `role_foundations`, derivada por `json_each(payload_json, '$.foundations')`,
   e não uma segunda cópia do dado que poderia divergir dele. `json_valid`
   protege a tabela de foundations.
5. **Instalação** (`hubicg library install`): verifica hashes, schemas e
   composição antes de gravar, e substitui as roles `official` numa única
   transação. É idempotente e remove as roles oficiais que a biblioteca deixou
   de distribuir. Uma role de outra origem com o mesmo ID nunca é
   sobrescrita, e o comando informa o ID dela.
6. **Seleção e busca** incluem a biblioteca instalada abaixo das roles do
   projeto, na precedência que já existia: `custom` > `project` > `official`.
   Nenhum comando de leitura cria o banco da máquina.

## Alternativas avaliadas

- **Projetar a biblioteca para `role-v1`:** perde foundations e proficiência no
  Community. Rejeitada pelo responsável.
- **Acrescentar campos opcionais ao `role-v1`:** a role composável não tem
  `instructions`, e trocar o campo obrigatório quebraria o contrato. Seria uma
  versão maior disfarçada.
- **Banco por projeto, como no ADR-001:** cada projeto precisaria importar a
  mesma biblioteca de novo. O responsável escolheu o banco da máquina.
- **Coluna `JSONB`:** exige SQLite 3.45 ou mais recente. O Python dos runners e
  de distribuições estáveis pode trazer versões anteriores. JSON em texto com as
  funções JSON nativas atende a consulta sem impor essa versão mínima.
- **Banco de documentos (TinyDB, PoloDB, MongoDB local):** o ADR-001 e o estudo
  de armazenamento já os avaliaram. Nenhum é mais leve sem perder índice ou
  transação.

## Consequências

### Positivas

- quem instala o Community recebe uma biblioteca verificável e utilizável em
  qualquer projeto da máquina;
- `role-v2` preserva composição e proficiência no repositório público;
- a ligação entre role e foundation não pode divergir do JSON, porque é
  derivada dele.

### Custos e riscos

- `library install` é a primeira escrita fora de `.hubicg/`. Ela é restrita ao
  diretório da máquina, recusa link simbólico e está documentada no contrato
  do CLI;
- um banco por máquina é compartilhado entre projetos, então a atualização da
  biblioteca afeta todos de uma vez. A instalação é explícita, nunca implícita;
- as 19 roles `role-v1` de `.hubicg/roles/` continuam sendo a origem que o
  catálogo importa. Neste repositório elas têm precedência de projeto sobre as
  versões oficiais de mesmo ID. A migração do catálogo para `role-v2` é decisão
  separada.

## Fora de escopo

Skills e agentes no banco, atualização automática da biblioteca e publicação de
release. A release exige a autorização de publicação própria do gate.
