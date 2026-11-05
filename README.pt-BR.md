# Relational Fixture Slice

Versão de desenvolvimento **0.1.0**, da [Lofrano Tecnologia](https://lofranotecnologia.com.br). SQL original e pequeno transporte/laboratório psycopg, sob licença MIT. Repositório: [martinlofranodeoliveira/relational-fixture-slice](https://github.com/martinlofranodeoliveira/relational-fixture-slice).

Extrai uma fixture PostgreSQL 17 limitada a partir de PKs explícitas, seguindo somente FKs **de saída**. Restaura CSV e DDL suportado regenerado em outro esquema vazio. A tarefa 100 traz seu projeto e organização, mas não a tarefa irmã 101. Não é backup geral nem ferramenta de anonimização.

## Instalação, testes e demonstração

Requisitos: Linux sem root, Python 3.11+ e ferramentas PostgreSQL **17** em `/usr/lib/postgresql/17/bin`. O laboratório exige `/proc`, pidfds, subreaper e `renameat2`. Use um processo dedicado, com SIGCHLD padrão, sem outro reaper e sem filhos alheios ao laboratório. Não paralelize os testes.

Na raiz do repositório, em diretório gravável por usuário sem privilégios:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.lock
. .venv/bin/activate
python3 tests/run.py
python3 bin/fixture_slice.py demo --assert
python3 bin/fixture_slice.py demo --assert --json
```

Para instalar também o pacote Python e os dois scripts SQL confiáveis no ambiente virtual:

```sh
.venv/bin/python -m pip install .
```

Os scripts ficam em `share/relational-fixture-slice/sql` dentro do ambiente. `fixture_slice.resources.read_sql('install.sql')` lê o instalador confiável. A demo não depende de arquivos da suíte de testes.

A instalação das dependências usa o índice Python configurado. Depois disso, testes e demo são offline: sem modelo/API, telemetria, listener externo, banco instalado, socket Docker ou credenciais. Execuções normais bem-sucedidas encerram ambos os clusters privados, verificam os status dos filhos e removem seu diretório temporário. **Encerramento incerto é uma falha que preserva o diretório**, informa seu caminho e exige o descarte do ambiente isolado antes de removê-lo. Não há mecanismo para matar descendentes arbitrários.

O CI usa o digest fixo da imagem PostgreSQL 17 bookworm registrado em [testes](docs/testing.md), prepara Python e executa com o usuário sem privilégios `postgres`. O executor informa as versões reais de Python, psycopg, ferramentas e servidores PostgreSQL. Execuções nativas dizem explicitamente quando não receberam um digest de imagem.

## Exemplo de saída

Prefixo legível determinístico:

```text
Relational Fixture Slice — development 0.1.0
task-100: 3 rows; verified
shared-parent: 4 rows; verified
project-only: 2 rows; verified
null-reference: 1 rows; verified
cycle: 2 rows; verified
snapshot: 3 rows; verified
row-cap: ROW_CAP; rollback verified
composite: UNSUPPORTED_SCHEMA; rollback verified
corrupt-reference: FOREIGN_KEY; rollback verified
```

Segue um relatório JSON com contagens por tabela, seis casos válidos e três rejeições esperadas. `--json` imprime somente esse relatório. As versões aparecem no executor de testes, fora da saída determinística da demo. São exemplos de saída, não uma alegação de testes já executados.

## Uso pequeno em SQL

Instale `sql/install.sql` na origem sintética com o papel que fará o planejamento. A função é SECURITY INVOKER, sem execução pública por padrão. Use `sql/demo_data.sql` somente em banco sintético isolado.

```sql
BEGIN ISOLATION LEVEL REPEATABLE READ;
SET LOCAL statement_timeout = '5s';
SET LOCAL lock_timeout = '5s';
LOCK TABLE ONLY sample.organization, ONLY sample.project,
           ONLY sample.task, ONLY sample.node IN SHARE UPDATE EXCLUSIVE MODE;
SELECT fixture.plan('sample', '[{"table":"project","pk":10}]'::jsonb, 10000);
SELECT t.name, s.pk FROM pg_temp.rf_selected s
JOIN pg_temp.rf_tables t USING (table_oid) ORDER BY t.name, s.pk;
COMMIT;
```

Seleciona organização 1 e projeto 10, sem tarefas. Descubra a lista de tabelas antes de BEGIN. Os locks devem vir antes do primeiro snapshot; não consulte catálogos com SELECT nessa transação antes deles. O transporte Python implementa essa sequência e revalida a estrutura.

## Uso pequeno em Python

```python
from fixture_slice.bundle import export_bundle, import_bundle

# Conexões psycopg ociosas, autocommit, para bancos PG17 sintéticos separados.
# 'bundles' já existe, é confiável e não tem ancestrais symlink.
resultado = export_bundle(origem, 'sample', [{'table': 'task', 'pk': 100}], 'bundles/task-100')
restaurado = import_bundle(destino, 'restored', 'bundles/task-100')
print(resultado['rows'], restaurado['rows'])  # 3 3
```

Sem instalar o pacote, execute a partir do checkout com `src` no caminho de importação Python. A CLI não aceita DSN arbitrário nem seletor SQL. Integrações controlam suas conexões e a autorização dos dados.

## Contrato, escolhas e limites

Suporte restrito: tabelas permanentes comuns; uma PK bigint não adiável; FKs de uma coluna bigint, adiáveis, apontando para PKs suportadas; payload bigint, integer, text ou boolean. Preserva NOT NULL, MATCH, ações e estado inicial das FKs. Aceita triggers internos de FK e rejeita triggers de usuário, defaults, identities, colunas geradas, CHECK, índices/restrições extras, RLS, partições, herança, arrays e tipos definidos pelo usuário.

Padrões: 10.000 linhas selecionadas, 16 MiB de CSV agregado e cinco segundos por instrução SQL do transporte. Há limites adicionais de sementes, tabelas, colunas, FKs, razões e manifesto. PostgreSQL COPY e psycopg tratam NULL, texto vazio, aspas, quebras de linha e Unicode. O marcador de NULL independe da configuração de literais de string da sessão.

Uma transação REPEATABLE READ e locks estruturais preservam o snapshot da origem, permitindo atualizações concorrentes de linhas. O conjunto visitado `(OID, PK)` encerra ciclos e elimina pais duplicados. A importação não executa SQL do bundle: regenera DDL finito e valida dados e FKs adiadas numa única transação. A publicação é atômica, sem sobrescrita, somente após sucesso completo.

Não é clonagem geral de PostgreSQL, conformidade ampla com padrões, snapshot de filesystem/entre bancos, quota rígida de disco/RSS, backup durável contra falhas ou alegação de prontidão para produção. Tabelas sem linhas selecionadas permanecem para preservar o DDL das FKs. Não copia permissões, donos, comentários, sequências, funções, opções físicas de armazenamento ou locale do banco. Exige diretório-pai confiável e esquema de destino exclusivo; escritores hostis concorrentes no filesystem e administradores privilegiados estão fora do modelo. O payload não é anonimizado. Todos os registros distribuídos são sintéticos.

Detalhes técnicos em inglês: [contrato](docs/contract.md), [projeto](docs/design.md), [manifesto](docs/manifest.md), [testes](docs/testing.md), [exemplos](docs/examples.md) e [segurança](docs/security-model.md).

Contato geral: [site oficial](https://lofranotecnologia.com.br). Relatos privados de vulnerabilidades: [SECURITY.md](SECURITY.md).

O `requirements.lock` versionado registra os wheels reais para Linux amd64/CPython 3.11, conferidos com os hashes SHA-256 oficiais do PyPI. Outros ambientes exigem resolução própria e não estão qualificados por este lock.
