# Parsing - Estrutura HTML da PGE-SP

## Página de Resultado (resumo)

### Devedor
- Container: `div#consultaDebitoForm:consultaDevedor`
- Tabela com pares chave-valor:
  - `Devedor:` → nome/razão social
  - `CPF/CNPJ:` → documento

### Tabela de Débitos por Tipo
- Container: `div#consultaDebitoForm:consultaDebitoSearchResultBlock`
- Tabela: `table.rich-table`
- Headers (class `rich-table-headercell`): Tipo, Qtde, Origem, Valor Total (R$)
- Footer (class `rich-table-footercell`): Débitos: N, Valor Total Atualizado: X
- Dados (class `rich-table-cell`): cada linha é um tipo de débito

### Sem Resultados
- Bloco: `div#consultaDebitoForm:consultaDebitoSearchInfoResultBlock`
- Texto: "Nenhum resultado com os critérios de consulta"

## Página de Lista de CDAs (após click no tipo)

### Tabela de CDAs
- ID: `table#consultaDebitoForm:dataTable2`
- Class: `rich-table`
- Headers: CPF/CNPJ, IE, N° de Registro/CDA, Referência, Data de Inscrição, Valor Atualizado (R$), Opções de Pagamento, Observação
- Cada linha = uma CDA individual
- Links nas CDAs: `a` com onclick `jsfcljs(...)` para detalhe individual

## Página de Detalhe de CDA Individual

### Painel "Dados N° de Registro/CDA"
- ID: `div#consultaDebitoForm:j_id1025`
- Campos em divs filhos com formato "Label:\n\t\t\tValor":
  - N° de Registro/CDA
  - Data de Inscrição
  - Número do Processo (Unificado)
  - Número do Processo (Outros)
  - Situação
  - Saldo (R$)

### Painel "Receitas do Débito"
- ID: `div#consultaDebitoForm:j_id1133`
- Tabela com headers: Tipo de Receita | Valor (R$)
- Linhas: Principal, Juros de Mora, Multa de Mora, Honorários Advocatícios

### Painel "Natureza da Dívida / Origem"
- ID: `div#consultaDebitoForm:j_id1162`
- Primeira th: "ICMS Declarado inscrito por SECRETARIA DA FAZENDA E PLANEJAMENTO"
- Tabela de referências: Data | Valor | Data Início Juros | Data Início Correção

## Observações

- IDs JSF contêm `:` (ex: `consultaDebitoForm:j_id1025`) — precisa escapar em CSS
- Os IDs numéricos (`j_id1025`, `j_id1134`) podem variar entre deploys do servidor
- O parser busca por padrão de texto nos headers, não por IDs fixos
- Painéis usam padrão RichFaces: `div[id]` com `_header` e `_body` suffixes
