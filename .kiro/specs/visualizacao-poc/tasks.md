# Plano de Implementação — Visualização da POC

> Depende da SOT já existente (spec `processamento-lotes-veiculos`). Recursos adicionados ao mesmo `serverless.yml`.

- [x] 1. Provisionar bucket do site e distribuição CloudFront
  - Criar bucket S3 privado para o site estático.
  - Criar distribuição CloudFront com OAC apontando para o bucket; HTTPS habilitado.
  - _Requisitos: 1.1, 1.2_

- [x] 2. Configurar roteamento CloudFront para a API
  - Adicionar origem do API Gateway e behavior `/api/*` (cache desabilitado/TTL curto); default behavior para o S3.
  - _Requisitos: 1.3_

- [x] 3. Implementar a Lambda API (Python + DuckDB)
- [x] 3.1 Endpoint GET /api/lotes
  - Listar prefixos da SOT (`ListObjectsV2` com `Delimiter='/'`) e extrair os IDs de lote; retornar lista (vazia se não houver).
  - Testes unitários (mock S3) para lista preenchida e vazia.
  - _Requisitos: 2.1, 2.2, 2.3_
- [x] 3.2 Endpoint GET /api/lotes/{lote}
  - Validar `{lote}` por allowlist; verificar existência do Parquet (404 se ausente).
  - Consultar via DuckDB (`read_parquet` parametrizado) e retornar JSON com os campos definidos.
  - Testes unitários cobrindo lote existente, inexistente (404) e parâmetro inválido.
  - _Requisitos: 3.1, 3.2, 3.3_
- [x] 3.3 Empacotamento do DuckDB/httpfs
  - Garantir DuckDB e extensão `httpfs` disponíveis (layer ou requirements com dockerizePip); conceder leitura da SOT na role.
  - _Requisitos: 3.1_

- [x] 4. Definir as rotas no API Gateway (serverless.yml)
  - Mapear `GET /api/lotes` e `GET /api/lotes/{lote}` para a Lambda API.
  - _Requisitos: 2.1, 3.1_

- [x] 5. Implementar o front estático
- [x] 5.1 Página e dropdown
  - `index.html` + `app.js`: no load, chamar `/api/lotes` e popular a dropdown; indicar carregando.
  - _Requisitos: 4.1, 4.4_
- [x] 5.2 Renderização do lote e atualização sob demanda
  - Ao selecionar/atualizar, chamar `/api/lotes/{lote}` e renderizar a tabela; tratar lista vazia.
  - _Requisitos: 4.2, 4.3, 4.4_
- [x] 5.3 Publicação dos estáticos
  - Publicar os arquivos no bucket do site (ex.: via plugin de sync no deploy do Serverless).
  - _Requisitos: 1.1_

- [ ] 6. Teste de integração da visualização (requer ambiente AWS implantado)
  - Com uma SOT populada, validar ponta a ponta: URL pública → dropdown lista lotes → seleção exibe veículos.
  - _Requisitos: 1.2, 2.1, 3.1, 4.2_
