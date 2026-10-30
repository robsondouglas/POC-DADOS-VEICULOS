# RESUMO
Essa solução deve receber arquivos txt com diversas linhas, onde cada linha tem a informação do número do lote, quantidade de veículos no lote, a placa, o modelo, fabricante e o ano de fabricação do veículo.
Esses arquivos podem chegar com centenas de registros.
O SLA de processamento de um lote é de 30 segundos e devemos notificar se houve falha ou sucesso no cumprimento.

# Layout posicional dos registros
Índices base-0, ambas as pontas inclusivas.

| Campo          | Posições | Tamanho |
|----------------|----------|---------|
| LOTE           | 0-5      | 6       |
| LOTE-ITEMS     | 6-9      | 4       |
| PLACA          | 10-16    | 7       |
| ANO FABRICACAO | 17-20    | 4       |
| MODELO         | 21-40    | 20      |
| FABRICANTE     | 41-60    | 20      |

Observações:
- Toda linha repete o campo LOTE-ITEMS (quantidade total de veículos do lote).
- A placa ocupa 7 posições. Placas válidas (ABC1234 / ABC1D23) nunca são "0000000", portanto não há conflito com o registro de controle do lote.

# INFORMAÇÕES IMPORTANTES
- A geração não é confiável e pode ser que o mesmo arquivo seja enviado mais de uma vez.
- A placa do veículo é única.
- O Lote é apenas um agrupador de veículos. Ele possui a informação de quantos veículos agrupa.
- Precisamos garantir que o mesmo veículo não seja inserido duas vezes no mesmo lote.
- O mesmo veículo pode vir em lotes diferentes.
- Devemos persistir o percentual de completude de preenchimento do lote. Quando alcançar 100%, pegamos os registros dos veículos desse lote e armazenamos na SOT.

# ARQUITETURA PROPOSTA
- Os arquivos serão incluídos em um Bucket S3 de ingestão.
- Cada arquivo inserido faz com que o Bucket notifique um SNS.
- Esse SNS notifica uma SQS que será consumida por uma Lambda Function.
- Essa Lambda lê o arquivo que chegou através das informações de key e bucket, que chegaram na mensagem.
- Esse arquivo contém as linhas com os registros dos lotes. Para cada linha, essa Lambda insere um registro em um DynamoDB.
- Essa tabela do DynamoDB seguirá o conceito de Single Table Design, onde a PK é o lote e a SK é a placa, mas deve seguir as seguintes regras:
    - Se o lote não existe na tabela, iremos cadastrá-lo com a placa '0000000' (registro de controle).
        - Esse registro terá 3 campos adicionais: quantidade de itens do lote (vem do campo "LOTE-ITEMS"), a quantidade de itens registrados=0 e status, que pode ser 'PREENCHENDO' | 'PREENCHIDO' | 'CONCLUIDO' | 'EXPIRADO'. O estado inicial é 'PREENCHENDO'.
        - A Lambda deve criar um schedule no EventBridge Scheduler de 30 segundos, com o ID igual ao do lote. Ele irá acionar uma Lambda que verifica o status do lote. Marca como 'EXPIRADO' **somente se o status for 'PREENCHENDO'** (ou seja, nem todos os veículos chegaram no prazo). Se já estiver 'PREENCHIDO' ou 'CONCLUIDO', não expira (os dados chegaram no SLA; a carga da SOT pode estar em andamento).
    - Quando incluir os dados dos veículos, teremos outros campos para armazenar modelo, fabricante e ano de fabricação.
    - Quando incluir os dados dos veículos, deve atualizar a quantidade de itens registrados no registro de controle do lote.
    - Quando a quantidade de veículos registrados alcançar a quantidade definida no lote, iremos realizar três ações:
        - Remove o schedule referente ao ID desse lote.
        - Inicia o processo de carga da SOT.
        - Atualiza o controle de lote com 'CONCLUIDO'.
- Essa tabela do DynamoDB tem TTL de 1 dia.
- Essa tabela do DynamoDB tem um DynamoDB Stream que notifica um Kinesis Data Stream com o registro inserido.
- Esse Kinesis Data Stream deve particionar pelo ID do lote.
- Esse Kinesis Data Stream não deve considerar quando a placa for '0000000', pois é apenas o controle do lote. Se esse filtro puder ser aplicado no DynamoDB Stream, sem problemas.

# CAMADAS DE DADOS (SOR e SOT)
Motivação: consultar todos os veículos de um lote grande diretamente no DynamoDB seria ofensor
(carga de leitura na tabela OLTP). Por isso usamos uma camada intermediária consultável/durável (SOR)
alimentada pelo Kinesis, e a SOT é materializada a partir da SOR.

Fluxo:
```
DynamoDB Stream → Kinesis Data Stream → Lambda consumidora → SOR (S3) → processo de carga → SOT (S3)
```

- **SOR (bruto, S3):** a Lambda consumidora do Kinesis grava **1 objeto por micro-batch**, particionado por lote
  (estratégia A2). Como o Kinesis particiona por lote, cada micro-batch tende a conter registros do mesmo lote,
  reduzindo a quantidade de objetos sem perder a localidade por lote. Evita read-modify-write (não há perda por concorrência).
  Prefixo sugerido: `sor/lote=<LOTE>/...`.
- **Gatilho da SOT:** quando `itens_registrados == lote_items` no registro de controle, o lote vira 'CONCLUIDO'
  e isso dispara a carga da SOT.
- **SOT (consolidado, S3):** a carga faz `ListObjectsV2` no prefixo do lote na SOR, consolida e grava
  **1 arquivo Parquet por lote** na SOT. Assim os small files ficam confinados à SOR (camada bruta, descartável
  por lifecycle) e não contaminam a SOT.
- **Lifecycle da SOR:** aplicar expiração curta nos objetos da SOR após a consolidação (mitiga small files).

# PONTOS DE ATENÇÃO
- **Consistência SOR x conclusão:** o caminho até a SOR é assíncrono (DynamoDB Stream → Kinesis → consumidora → SOR).
  No momento em que o lote é marcado CONCLUIDO, pode haver registro ainda "em trânsito" para a SOR.
  A carga da SOT deve validar que a contagem de objetos/registros na SOR bate com `lote_items` antes de materializar,
  e reprocessar/aguardar se faltar.
- **SLA de 30s com múltiplos arquivos:** o schedule de 30s é criado na primeira linha do lote. Se as linhas do mesmo
  lote chegarem em arquivos diferentes com intervalo maior que 30s, o lote expira antes de completar.
  **Decisão de negócio: isso é aceitável.**

# INGESTÃO (1 arquivo = vários lotes)
Um arquivo pode conter linhas de **múltiplos lotes misturados**. A Lambda de ingestão deve:
- Agrupar as linhas por lote.
- Para cada lote distinto, garantir o registro de controle sob demanda (upsert condicional com
  `attribute_not_exists` para não recriar) e criar o schedule de 30s apenas na primeira vez.
- Usar o `lote_items` que vem repetido nas próprias linhas ao criar o registro de controle.
- Linhas do mesmo lote podem estar espalhadas entre arquivos diferentes (comportamento aceito;
  o SLA de 30s pode expirar — ver PONTOS DE ATENÇÃO).

# CICLO DE VIDA DO STATUS DO LOTE
```
PREENCHENDO  → lote criado, recebendo veículos
PREENCHIDO   → itens_registrados == lote_items (todos no DynamoDB), SOT ainda NÃO carregada
CONCLUIDO    → SOT carregada com sucesso
EXPIRADO     → SLA de 30s estourou com status ainda em PREENCHENDO
```

# CONTADOR E IDEMPOTÊNCIA (transição única)
Vários registros do mesmo lote são processados concorrentemente. Garantias:
- **Idempotência:** inserção do veículo com condição `attribute_not_exists(PK) AND attribute_not_exists(SK)`.
  Veículo duplicado ou arquivo reenviado falha a condição e **não** reincrementa o contador.
- **Estratégia escolhida (item 4): duas operações separadas** (sem TransactWriteItems).
  1. Insere o veículo (condicional). 2. Somente se a inserção teve sucesso, faz `ADD itens_registrados 1`
  no registro de controle (incremento atômico, sem read-modify-write).
  Trade-off aceito: pequeno risco de inconsistência se a Lambda morrer entre as duas chamadas (aceitável para POC).
- **Detecção de conclusão exatamente uma vez:** o `ADD` retorna o novo valor (`ReturnValues: UPDATED_NEW`).
  Apenas a execução que observar `novo_itens_registrados == lote_items` conduz a conclusão:
  1. Marca o controle como **PREENCHIDO** (condição `status = 'PREENCHENDO'`, garante passo único).
  2. Dispara a carga da SOT (lê a SOR do lote, valida contagem, materializa o Parquet).
  3. Sucesso da carga → marca **CONCLUIDO** e remove o schedule.
  4. Falha da carga → permanece em PREENCHIDO para retry (não regride de estado).

# SOT — SCHEMA E ESTRUTURA
- **Particionamento por lote.** Como o ID do lote é único (não se repete), não há risco de colisão/sobrescrita.
- **Estrutura de chaves:** `sot/lote=<LOTE>/dados.parquet` (1 arquivo Parquet por lote).
- **Schema (1 registro por veículo, sem o registro de controle `0000000`):**
  `lote`, `placa`, `ano_fabricacao`, `modelo`, `fabricante`.

# TRATAMENTO DE ERROS
- **Linhas malformadas** (tamanho incorreto, ano inválido): **descarte silencioso**. A linha inválida é
  ignorada e o processamento das demais linhas continua. Sem log específico e sem envio para fila de erro.
- **SQS com DLQ:** a fila de ingestão terá uma Dead Letter Queue (`maxReceiveCount = 3`) para isolar
  mensagens que a Lambda não conseguir processar (ex.: arquivo inacessível, key inexistente, erro de runtime).
  Observação: isso é falha de processamento da mensagem/arquivo inteiro; o descarte de **linhas** malformadas
  continua sendo silencioso e não aciona a DLQ.

# NOTIFICAÇÃO DE SLA (SNS)
Um SNS Topic recebe o resultado do SLA em **ambos os casos**:
- **SUCESSO** (lote CONCLUIDO dentro do prazo): além de notificar, serve como **ponto de integração** —
  sinaliza a uma infraestrutura downstream (fora do escopo desta POC) que deve consumir os dados da SOT do lote.
- **FALHA** (lote EXPIRADO): notifica o descumprimento do SLA.

# LOTE EXPIRADO
- A Lambda do schedule marca o lote como EXPIRADO (somente se status == PREENCHENDO).
- Não há ação de exclusão ativa: o lote incompleto **não gera SOT** e os registros são limpos
  automaticamente pelo **TTL de 1 dia** do DynamoDB.

# DÚVIDAS EM ABERTO
Nenhuma. Todas as definições necessárias para iniciar a Spec oficial foram fechadas.

---
Os diagramas gerados devem usar a notação mermaid.
