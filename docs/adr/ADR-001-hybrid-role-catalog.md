# ADR-001 — Catálogo híbrido de roles

- **Estado:** aceito para protótipo
- **Data:** 07/08/2026
- **Decisores:** Paulo Cesar Benjamin Junior, core maintainer

## Contexto

O HubICG precisa manter roles oficiais atualizáveis e roles personalizadas
privadas, funcionar em múltiplas IDEs e sistemas operacionais, operar offline e
permanecer agnóstico ao modelo de IA. Conectar cada cliente diretamente a um
banco remoto exporia credenciais e aumentaria o acoplamento. Manter somente
arquivos JSON não oferece índices, migrações ou consistência transacional.

## Decisão

1. Usar SQLite como fonte operacional local para roles personalizadas,
   preferências e cache verificado das roles oficiais.
2. Manter o catálogo oficial em MongoDB Atlas atrás de uma API HubICG
   versionada; clientes nunca acessam o Atlas diretamente.
3. Usar JSON como formato de autoria, contribuição e intercâmbio, não como o
   único mecanismo operacional.
4. Realizar seleção local determinística por padrão; FTS5 é uma otimização com
   fallback obrigatório.
5. Tornar a busca semântica remota opcional e limitada ao catálogo oficial,
   enviando somente intenção minimizada mediante política autorizada.
6. Exigir manifesto com versão, hashes, assinatura e lista de revogações para
   promover dados oficiais no cache local.

## Consequências

### Positivas

- instalação sem serviço local e sem dependência Python adicional;
- operação offline e privacidade das roles personalizadas;
- curadoria central sem distribuir segredos do Atlas;
- busca, migração e auditoria com contratos explícitos;
- caminho evolutivo para ranking semântico agnóstico a modelo.

### Custos e riscos

- schema local e migrações passam a ser responsabilidade do produto;
- múltiplas IDEs exigem testes de concorrência e política de timeout;
- assinatura, revogação e autenticação da API ainda precisam de decisões;
- busca remota pode revelar intenção se não houver minimização e opt-in.

## Alternativas rejeitadas

- **somente JSON:** insuficiente como armazenamento operacional;
- **MongoDB direto no cliente:** expõe credenciais e amplia operação;
- **MongoDB local obrigatório:** pesado para a edição Community;
- **DuckDB como banco principal:** orientado a análise, não à carga operacional;
- **dependência obrigatória da rede:** incompatível com operação local-first.

## Evidência associada

Ver [estudo de armazenamento e seleção](../architecture/ROLE-STORAGE-SELECTION-STUDY.md).
