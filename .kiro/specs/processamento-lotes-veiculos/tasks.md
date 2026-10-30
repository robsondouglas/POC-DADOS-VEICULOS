# Plano de Implementação — Processamento de Lotes de Veículos

- [x] 1. Estruturar o projeto Serverless Framework (Python) e a infraestrutura base
  - Inicializar o projeto com `serverless.yml` (provider AWS, runtime `python3.12`).
  - Configurar `serverless-python-requirements` com `dockerizePip` (para libs nativas como `pyarrow`).
  - Declarar os buckets S3 (ingestão, SOR, SOT) no bloco `resources`.
  - Configurar lifecycle de expiração curta na SOR.
  - Criar a estrutura de pastas `src/` (ingestao, sor_consumer, carga_sot, expiracao, common) e `tests/`.
  - Configurar `pytest` para os testes.
  - _Requisitos: 1.1, 7.3, 10.2_

- [x] 2. Configurar a cadeia de ingestão de eventos
- [x] 2.1 Criar SNS de ingestão e notificação do bucket
  - Configurar notificação `s3:ObjectCreated:*` do bucket de ingestão para o SNS.
  - _Requisitos: 1.1, 1.2_
- [x] 2.2 Criar SQS de ingestão com DLQ
  - Assinar a SQS no SNS; configurar DLQ com `maxReceiveCount = 3`.
  - _Requisitos: 1.2, 1.4_

- [x] 3. Criar a tabela DynamoDB (Single Table Design)
  - PK=lote, SK=placa; habilitar TTL (1 dia) e DynamoDB Stream (NEW_IMAGE).
  - Configurar filtro para excluir eventos com SK=`0000000` (no event source mapping, se suportado).
  - _Requisitos: 3.1, 6.1, 6.3, 10.1_

- [x] 4. Implementar o parser posicional
- [x] 4.1 Implementar função de parse por layout posicional
  - Extrair LOTE, LOTE-ITEMS, PLACA, ANO FABRICACAO, MODELO, FABRICANTE pelas posições definidas.
  - _Requisitos: 2.1_
- [x] 4.2 Implementar validação e descarte silencioso de linhas malformadas
  - Descartar linhas com tamanho incorreto ou ano inválido, continuando o processamento das demais.
  - Escrever testes unitários cobrindo linhas válidas, malformadas e agrupamento por lote.
  - _Requisitos: 2.3, 2.2_

- [x] 5. Implementar a Lambda de Ingestão
- [x] 5.1 Leitura do arquivo e agrupamento por lote
  - Ler bucket/key da mensagem SQS, baixar o arquivo, parsear e agrupar linhas por lote.
  - _Requisitos: 1.3, 2.2_
- [x] 5.2 Criação condicional do registro de controle e schedule
  - Put condicional (`attribute_not_exists`) do controle com status PREENCHENDO; criar schedule de 30s (ID=lote) só na criação.
  - _Requisitos: 3.1, 3.2, 3.3_
- [x] 5.3 Inserção idempotente de veículos e contagem atômica
  - Put condicional do veículo; em sucesso, `ADD itens_registrados 1` com `UPDATED_NEW`.
  - Garantir que duplicados não incrementem o contador.
  - _Requisitos: 4.1, 4.2, 4.3, 4.4_
- [x] 5.4 Transição de conclusão (PREENCHIDO) exatamente uma vez
  - Ao detectar `itens_registrados == lote_items`, marcar PREENCHIDO com condição `status = 'PREENCHENDO'` e invocar a carga da SOT.
  - Escrever testes (incluindo concorrência simulada) para a transição única.
  - _Requisitos: 5.1, 5.2_

- [x] 6. Implementar a propagação DynamoDB Stream → Kinesis
  - Configurar Kinesis Data Stream com partition key = lote.
  - Conectar o DynamoDB Stream ao Kinesis (EventBridge Pipe ou Lambda de forwarding), aplicando o filtro de `0000000`.
  - _Requisitos: 6.1, 6.2, 6.3_

- [x] 7. Implementar a Lambda Consumidora SOR
  - Consumir micro-batches do Kinesis e gravar 1 objeto por micro-batch em `sor/lote=<LOTE>/...` (sem read-modify-write).
  - Escrever testes unitários do mapeamento registro→objeto SOR.
  - _Requisitos: 6.4_

- [x] 8. Implementar a Lambda de Carga da SOT
- [x] 8.1 Consolidação a partir da SOR
  - `ListObjectsV2` no prefixo do lote, ler e consolidar registros de veículos (excluir controle).
  - _Requisitos: 7.1, 7.4_
- [x] 8.2 Validação de completude e materialização em Parquet
  - Validar `count == lote_items` antes de materializar; aguardar/reprocessar se faltar.
  - Gravar `sot/lote=<LOTE>/dados.parquet` com as colunas definidas, usando `pyarrow` (ou `awswrangler`).
  - _Requisitos: 7.2, 7.3_
- [x] 8.3 Finalização de estado e notificação de sucesso
  - Em sucesso: marcar CONCLUIDO, remover schedule e publicar SUCESSO no SNS.
  - Em falha: manter PREENCHIDO para retry.
  - _Requisitos: 5.3, 5.4, 9.1_

- [x] 9. Implementar a Lambda de Expiração (SLA)
  - Acionada pelo schedule; marcar EXPIRADO somente se status == PREENCHENDO; publicar FALHA no SNS.
  - Não marcar se já PREENCHIDO/CONCLUIDO. Confiar no TTL para limpeza.
  - Escrever testes cobrindo os três estados no disparo.
  - _Requisitos: 8.1, 8.2, 8.3, 8.4, 9.2_

- [x] 10. Criar o SNS de resultado de SLA e integrações
  - Criar o SNS Topic de resultado e conceder publish às Lambdas de Carga SOT e Expiração.
  - _Requisitos: 9.1, 9.2_

- [ ] 11. Testes de integração ponta a ponta (requer ambiente AWS implantado)
  - Cenário feliz (lote completo → SOT + SUCESSO), reenvio de arquivo (idempotência),
    lote incompleto (EXPIRADO + FALHA), e arquivo com múltiplos lotes misturados.
  - _Requisitos: 1.3, 2.2, 4.2, 5.3, 8.2, 9.1, 9.2_
