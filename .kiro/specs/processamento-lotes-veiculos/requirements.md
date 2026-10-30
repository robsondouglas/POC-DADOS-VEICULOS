# Requirements — Processamento de Lotes de Veículos

## Introdução

Esta solução recebe arquivos de texto posicionais contendo registros de veículos agrupados por lote.
Cada lote declara quantos veículos agrupa; o sistema persiste o progresso de preenchimento e, ao atingir
100%, materializa os dados do lote em uma camada analítica (SOT). O processamento de cada lote tem um
SLA de 30 segundos, e o resultado (sucesso ou falha) é notificado. A geração dos arquivos não é confiável
(arquivos podem ser reenviados e linhas podem chegar em arquivos distintos), portanto o sistema precisa ser
idempotente e tolerante a duplicidades.

### Glossário
- **Lote:** agrupador de veículos, identificado por um ID único que não se repete.
- **Registro de controle:** item do lote no DynamoDB com placa `0000000`, que mantém o progresso e o status.
- **SOR (System of Record):** camada bruta intermediária em S3, alimentada pelo Kinesis.
- **SOT (Source of Truth):** camada consolidada/analítica em S3 (Parquet, 1 arquivo por lote).
- **SLA:** 30 segundos para um lote atingir o estado concluído a partir de sua criação.

### Layout posicional do registro (índices base-0, pontas inclusivas)
| Campo          | Posições | Tamanho |
|----------------|----------|---------|
| LOTE           | 0-5      | 6       |
| LOTE-ITEMS     | 6-9      | 4       |
| PLACA          | 10-16    | 7       |
| ANO FABRICACAO | 17-20    | 4       |
| MODELO         | 21-40    | 20      |
| FABRICANTE     | 41-60    | 20      |

---

## Requisitos

### Requisito 1 — Ingestão de arquivos
**User story:** Como operador do sistema de origem, quero depositar arquivos de texto em um bucket S3,
para que eles sejam processados automaticamente.

#### Critérios de aceitação
1. QUANDO um arquivo for criado no bucket S3 de ingestão, O SISTEMA DEVE emitir uma notificação via SNS.
2. QUANDO o SNS receber a notificação de criação de objeto, O SISTEMA DEVE encaminhá-la para uma fila SQS.
3. QUANDO uma mensagem chegar na fila SQS, O SISTEMA DEVE acionar uma Lambda de ingestão que lê o arquivo
   a partir das informações de bucket e key presentes na mensagem.
4. QUANDO a Lambda de ingestão não conseguir processar a mensagem após 3 tentativas (maxReceiveCount=3),
   O SISTEMA DEVE encaminhar a mensagem para uma Dead Letter Queue (DLQ).

### Requisito 2 — Parsing e múltiplos lotes por arquivo
**User story:** Como processador de dados, quero interpretar cada linha do arquivo pelo layout posicional
e agrupar por lote, para que lotes misturados no mesmo arquivo sejam tratados corretamente.

#### Critérios de aceitação
1. QUANDO a Lambda ler uma linha, O SISTEMA DEVE extrair LOTE, LOTE-ITEMS, PLACA, ANO FABRICACAO,
   MODELO e FABRICANTE conforme as posições do layout.
2. QUANDO um arquivo contiver linhas de múltiplos lotes, O SISTEMA DEVE agrupar as linhas por lote
   antes de processá-las.
3. SE uma linha estiver malformada (tamanho incorreto ou ano inválido), ENTÃO O SISTEMA DEVE descartá-la
   silenciosamente e continuar o processamento das demais linhas.

### Requisito 3 — Registro de controle do lote
**User story:** Como gestor do processamento, quero um registro de controle por lote, para acompanhar
o progresso e o status de preenchimento.

#### Critérios de aceitação
1. SE o lote ainda não existir na tabela, ENTÃO O SISTEMA DEVE criar um registro de controle com PK=lote,
   SK=`0000000`, `lote_items` (vindo de LOTE-ITEMS), `itens_registrados=0` e `status='PREENCHENDO'`.
2. O SISTEMA DEVE criar o registro de controle de forma condicional (`attribute_not_exists`) para não
   recriar um registro já existente quando o lote reaparecer.
3. QUANDO o registro de controle de um lote for criado pela primeira vez, O SISTEMA DEVE criar um schedule
   no EventBridge Scheduler de 30 segundos com ID igual ao do lote.

### Requisito 4 — Inserção de veículos, idempotência e contagem
**User story:** Como gestor de dados, quero que cada veículo seja inserido uma única vez por lote e que o
progresso seja contado com precisão, para garantir a completude correta.

#### Critérios de aceitação
1. QUANDO a Lambda inserir um veículo, O SISTEMA DEVE gravar um item com PK=lote, SK=placa e os campos
   modelo, fabricante e ano de fabricação.
2. O SISTEMA DEVE inserir o veículo de forma condicional (`attribute_not_exists(PK) AND attribute_not_exists(SK)`),
   de modo que um veículo duplicado ou um arquivo reenviado não seja inserido novamente.
3. SE a inserção do veículo for bem-sucedida, ENTÃO O SISTEMA DEVE incrementar `itens_registrados` do
   registro de controle de forma atômica (`ADD itens_registrados 1`).
4. SE a inserção do veículo falhar pela condição de duplicidade, ENTÃO O SISTEMA NÃO DEVE incrementar
   `itens_registrados`.

### Requisito 5 — Conclusão do lote (transição única)
**User story:** Como gestor de dados, quero que a conclusão de um lote dispare a carga da SOT exatamente
uma vez, para evitar processamento duplicado.

#### Critérios de aceitação
1. QUANDO o incremento atômico resultar em `itens_registrados == lote_items`, O SISTEMA DEVE marcar o
   registro de controle como `PREENCHIDO`, usando a condição `status = 'PREENCHENDO'` para garantir que
   apenas uma execução conduza a conclusão.
2. QUANDO o lote for marcado como `PREENCHIDO`, O SISTEMA DEVE iniciar a carga da SOT.
3. SE a carga da SOT for bem-sucedida, ENTÃO O SISTEMA DEVE marcar o registro de controle como `CONCLUIDO`
   e remover o schedule do EventBridge referente ao lote.
4. SE a carga da SOT falhar, ENTÃO O SISTEMA DEVE manter o status em `PREENCHIDO` para permitir nova tentativa,
   sem regredir de estado.

### Requisito 6 — Stream para a camada SOR via Kinesis
**User story:** Como arquiteto de dados, quero propagar os veículos inseridos para uma camada SOR sem
onerar a tabela OLTP, para permitir a montagem da SOT em lotes grandes.

#### Critérios de aceitação
1. QUANDO um item for inserido na tabela DynamoDB, O SISTEMA DEVE propagar o evento por DynamoDB Stream
   para um Kinesis Data Stream.
2. O SISTEMA DEVE particionar o Kinesis Data Stream pelo ID do lote.
3. O SISTEMA NÃO DEVE propagar para o Kinesis os eventos cuja placa seja `0000000` (registro de controle);
   o filtro DEVE ser aplicado no DynamoDB Stream se possível.
4. QUANDO a Lambda consumidora ler um micro-batch do Kinesis, O SISTEMA DEVE gravar 1 objeto na SOR (S3)
   particionado por lote (prefixo `sor/lote=<LOTE>/`), sem usar read-modify-write.

### Requisito 7 — Carga da SOT
**User story:** Como consumidor analítico, quero que os dados de um lote concluído sejam materializados
em um único arquivo Parquet por lote, para consumo eficiente.

#### Critérios de aceitação
1. QUANDO a carga da SOT for iniciada, O SISTEMA DEVE listar os objetos da SOR no prefixo do lote
   (`ListObjectsV2`) e consolidar os registros de veículos.
2. ANTES de materializar a SOT, O SISTEMA DEVE validar que a contagem de registros consolidados na SOR
   é igual a `lote_items`; SE faltar registro, ENTÃO O SISTEMA DEVE aguardar/reprocessar antes de materializar.
3. QUANDO a consolidação estiver completa, O SISTEMA DEVE gravar 1 arquivo Parquet por lote em
   `sot/lote=<LOTE>/dados.parquet` com as colunas `lote`, `placa`, `ano_fabricacao`, `modelo`, `fabricante`.
4. O SISTEMA NÃO DEVE incluir o registro de controle (placa `0000000`) na SOT.

### Requisito 8 — SLA e expiração
**User story:** Como gestor de operações, quero que lotes que não completem dentro de 30 segundos sejam
marcados como expirados, para visibilidade de descumprimento de SLA.

#### Critérios de aceitação
1. QUANDO o schedule de 30 segundos de um lote disparar, O SISTEMA DEVE acionar uma Lambda que verifica
   o status do lote.
2. SE o status do lote for `PREENCHENDO` no disparo do schedule, ENTÃO O SISTEMA DEVE marcar o lote como `EXPIRADO`.
3. SE o status do lote já for `PREENCHIDO` ou `CONCLUIDO` no disparo do schedule, ENTÃO O SISTEMA NÃO DEVE
   marcar o lote como `EXPIRADO`.
4. QUANDO um lote expirar, O SISTEMA NÃO DEVE gerar SOT para esse lote, e os registros DEVEM ser removidos
   automaticamente pelo TTL de 1 dia do DynamoDB (sem exclusão ativa).

### Requisito 9 — Notificação de resultado (SNS)
**User story:** Como integrador downstream, quero ser notificado do resultado do SLA de cada lote, para
consumir a SOT quando disponível e para ter visibilidade de falhas.

#### Critérios de aceitação
1. QUANDO um lote for marcado como `CONCLUIDO`, O SISTEMA DEVE publicar uma notificação de SUCESSO em um
   SNS Topic, servindo como ponto de integração para a infraestrutura downstream que consumirá a SOT.
2. QUANDO um lote for marcado como `EXPIRADO`, O SISTEMA DEVE publicar uma notificação de FALHA no SNS Topic.

### Requisito 10 — Retenção de dados
**User story:** Como responsável por governança, quero que os dados operacionais tenham retenção limitada,
para controlar custo e ciclo de vida.

#### Critérios de aceitação
1. O SISTEMA DEVE aplicar TTL de 1 dia nos itens da tabela DynamoDB.
2. O SISTEMA DEVE aplicar uma política de lifecycle de expiração curta nos objetos da SOR após a consolidação.

---

## Fora de escopo (POC)
- A infraestrutura downstream que consome a SOT (apenas o ponto de integração via SNS é previsto).
- Autenticação/autorização de produtores de arquivos.
- Reprocessamento automático de lotes expirados.
