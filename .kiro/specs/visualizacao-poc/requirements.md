# Requirements — Visualização da POC (Resultado Consolidado dos Lotes)

## Introdução

Camada de apresentação para ilustrar a POC de processamento de lotes de veículos. Expõe publicamente uma
página web que permite selecionar um lote em uma dropdown e visualizar os veículos consolidados daquele
lote a partir da SOT (arquivos Parquet no S3). É uma camada independente do pipeline de ingestão; o contrato
entre as duas é a SOT.

### Contexto arquitetural
- Fonte de dados: **SOT** (`s3://<sot>/sot/lote=<LOTE>/dados.parquet`), somente leitura.
- Distribuição pública via **CloudFront** com **S3 privado (OAC)** para o site estático e **API Gateway + Lambda**
  para os dados, sob o mesmo domínio (evita CORS).
- Lambda da API em **Python**, usando **DuckDB** para consultar os Parquet sob demanda.
- Empacotada no **mesmo `serverless.yml`** do core da POC.

### Fora de escopo
- Autenticação/autorização de usuários.
- Auto-refresh/streaming em tempo real (a SOT é estável após conclusão; atualização é sob demanda).
- Escrita/alteração de dados (a camada é somente leitura).

---

## Requisitos

### Requisito 1 — Distribuição pública do site
**User story:** Como apresentador da POC, quero uma URL pública servindo a página, para demonstrar o
resultado a terceiros.

#### Critérios de aceitação
1. O SISTEMA DEVE servir o conteúdo estático (HTML/JS/CSS) através de CloudFront a partir de um bucket S3 privado,
   usando Origin Access Control (OAC).
2. O SISTEMA DEVE expor a aplicação por HTTPS em uma URL pública do CloudFront.
3. O SISTEMA DEVE rotear requisições `/api/*` no CloudFront para o API Gateway e as demais para o bucket estático,
   sob o mesmo domínio.

### Requisito 2 — Listagem de lotes disponíveis
**User story:** Como usuário da tela, quero ver em uma dropdown os lotes disponíveis, para escolher qual visualizar.

#### Critérios de aceitação
1. QUANDO o cliente chamar `GET /api/lotes`, O SISTEMA DEVE retornar a lista de IDs de lote presentes na SOT.
2. O SISTEMA DEVE derivar a lista a partir dos prefixos de objetos da SOT (`ListObjectsV2` com delimitador),
   sem necessidade de ler o conteúdo dos Parquet.
3. SE não houver lotes na SOT, ENTÃO O SISTEMA DEVE retornar uma lista vazia (HTTP 200).

### Requisito 3 — Detalhe dos veículos de um lote
**User story:** Como usuário da tela, quero ver os veículos do lote selecionado, para inspecionar o resultado consolidado.

#### Critérios de aceitação
1. QUANDO o cliente chamar `GET /api/lotes/{lote}`, O SISTEMA DEVE ler o Parquet do lote na SOT via DuckDB
   e retornar os veículos em JSON com os campos `lote`, `placa`, `ano_fabricacao`, `modelo`, `fabricante`.
2. SE o lote informado não existir na SOT, ENTÃO O SISTEMA DEVE retornar HTTP 404.
3. O SISTEMA DEVE validar o parâmetro `{lote}` para evitar injeção de caminho/consulta antes de montar a leitura do Parquet.

### Requisito 4 — Interface web
**User story:** Como usuário da tela, quero uma interface simples com dropdown e botão de atualizar, para
navegar pelos lotes.

#### Critérios de aceitação
1. QUANDO a página carregar, O SISTEMA DEVE popular a dropdown chamando `GET /api/lotes`.
2. QUANDO o usuário selecionar um lote (ou acionar "Atualizar"), O SISTEMA DEVE chamar `GET /api/lotes/{lote}`
   e renderizar os veículos em uma tabela.
3. A interface DEVE funcionar por atualização sob demanda (seleção/botão), sem auto-refresh.
4. A interface DEVE indicar estados de carregamento e de lista vazia/sem resultados.
