# ADR-001 — Armazenamento local de roles

- **Estado:** aceito para protótipo
- **Data:** 07/08/2026
- **Decisores:** Paulo Cesar Benjamin Junior, core maintainer

## Contexto

O HubICG precisa manter roles personalizadas privadas, funcionar em múltiplas
IDEs e sistemas operacionais, operar offline e permanecer agnóstico ao modelo
de IA. Manter somente arquivos JSON não oferece índices, migrações ou
consistência transacional para o uso operacional.

## Decisão

1. Usar SQLite como fonte operacional local para roles personalizadas, roles
   do projeto e preferências.
2. Usar JSON como formato de autoria, contribuição e intercâmbio, não como o
   único mecanismo operacional.
3. Realizar seleção local determinística por padrão; FTS5 é uma otimização com
   fallback obrigatório.
4. Reservar metadados de origem e versão sem pressupor onde um eventual
   catálogo oficial será armazenado.
5. Não decidir nesta ADR por API remota, MongoDB Atlas, sincronização, busca
   semântica remota ou infraestrutura de catálogo oficial.

## Consequências

### Positivas

- instalação sem serviço local e sem dependência Python adicional;
- operação offline e privacidade das roles personalizadas;
- busca, migração e auditoria com contratos explícitos;
- evolução do seletor local independente de provedor ou serviço remoto.

### Custos e riscos

- schema local e migrações passam a ser responsabilidade do produto;
- múltiplas IDEs exigem testes de concorrência e política de timeout;
- backup, exportação e recuperação do banco local precisam ser especificados;
- um catálogo oficial futuro exigirá nova decisão arquitetural.

## Alternativas avaliadas para o armazenamento local

- **somente JSON:** insuficiente como armazenamento operacional;
- **MongoDB local obrigatório:** pesado para a edição Community;
- **DuckDB como banco principal:** orientado a análise, não à carga operacional.

## Itens explicitamente adiados

MongoDB Atlas e outras opções remotas permanecem somente no estudo
exploratório, sem prioridade. Uma eventual adoção exigirá comparação,
aprovação e ADR próprios.

## Evidência associada

Ver [estudo de armazenamento e seleção](../architecture/ROLE-STORAGE-SELECTION-STUDY.md).
