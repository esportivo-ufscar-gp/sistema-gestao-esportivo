# Sistema de Gestão Integrada Esportivo UFSCar

Instruções para o Claude Code trabalhar neste repositório. Leia este arquivo inteiro antes de qualquer tarefa.

## Contexto

- Projeto acadêmico ESP-2026-01: MVP de um sistema web de gestão para uma loja de artigos esportivos com loja física (PDV) e loja online, que compartilham o mesmo estoque.
- Equipe: Gabriel Urbano (gerente do projeto, front-end, qualidade) e Eric Lopes (líder técnico, back-end, banco de dados).
- Cada tarefa corresponde a um pacote de trabalho da EAP (ex.: 4.2.2) e a uma história de usuário (ex.: HU04), que serão informados no pedido com seus critérios de aceite.

## Stack

- Python 3.12, Django 5.2, PostgreSQL 16 (SQLite apenas como atalho local).
- Páginas geradas no servidor com templates Django, Bootstrap 5.3 via CDN e JavaScript só onde houver interatividade.
- Testes com o framework do Django, cobertura com coverage.py e estilo com flake8.
- Configuração por variáveis no `.env` (ver `.env.example`).

## Estrutura

```
config/           configurações, urls, wsgi e asgi
apps/core/        página inicial, template base e /health/
apps/contas/      4.1 login, logout, perfis e permissões
apps/produtos/    4.2 categorias e produtos
apps/estoque/     4.3 serviço de estoque, movimentos, estoque mínimo e alertas
apps/vendas/      4.4 venda, itens, PDV e cancelamento
apps/loja/        4.5 catálogo, carrinho na sessão, checkout e pedidos
apps/clientes/    4.6 cadastro com consentimento LGPD e histórico
apps/relatorios/  4.7 relatórios (somente leitura)
templates/        base.html
static/           CSS e JS próprios
```

## Regras de arquitetura

- Regras de negócio ficam em `apps/<app>/services.py`. As views só recebem a requisição, chamam o serviço e mostram o resultado.
- **Toda mudança de saldo de estoque passa por `apps/estoque/services.py`.** Nunca altere `Produto.estoque_atual` fora desse serviço. O serviço usa `transaction.atomic()` e bloqueia os produtos com `select_for_update()`, sempre em ordem de `id`, e grava um `MovimentoEstoque` para cada mudança.
- Venda do PDV e pedido online são a mesma entidade `Venda`, diferenciados pelo campo `canal`.
- O preço é copiado para `ItemVenda.preco_unitario` no momento da venda.
- O carrinho fica na sessão do navegador e não reserva estoque.
- Produtos e categorias com histórico usam `on_delete=models.PROTECT` e são desativados, nunca excluídos.
- Cadastros internos usam o Django Admin, com permissões por grupo.
- Perfis são grupos do Django: `administrador`, `vendedor`, `estoquista` e `cliente`.

## Modelo de dados

- **Categoria:** `nome` (único), `ativa`.
- **Produto:** `codigo` (único), `nome`, `descricao`, `imagem` (opcional), `preco` (Decimal 10,2, maior que zero), `categoria` (FK, PROTECT), `estoque_atual` (inteiro, nunca negativo), `estoque_minimo` (inteiro, nunca negativo), `ativo`.
- **MovimentoEstoque:** `produto`, `tipo` (`entrada`, `saida_venda`, `estorno`, `ajuste`), `quantidade` (maior que zero), `saldo_apos`, `venda` (opcional), `usuario`, `motivo`, `criado_em`. O tipo `ajuste` é uma saída manual: exige motivo e não pode deixar o saldo negativo.
- **Venda:** `numero` (sequencial), `canal` (`loja_fisica`, `online`), `status` (`concluida`, `aguardando_retirada`, `retirada`, `cancelada`), `forma_pagamento` (`dinheiro`, `cartao`, `pix`), `total`, `cliente` (só online), `vendedor` (só PDV), `criado_em`, `cancelada_em`, `cancelada_por`.
- **ItemVenda:** `venda`, `produto` (PROTECT), `quantidade` (maior que zero), `preco_unitario`.
- **Cliente:** `nome`, `email` (único), `telefone`, `usuario` (OneToOne opcional), `consentimento_em` (obrigatório), `criado_em`.

## Convenções de código

- Identificadores de domínio em português e sem acentos (`estoque_minimo`, `forma_pagamento`); textos exibidos ao usuário em português com acentos.
- Todo modelo e campo tem `verbose_name` em português.
- Valores monetários sempre em `DecimalField`, nunca `float`.
- Restrições importantes também no banco, com `CheckConstraint` e `UniqueConstraint`, além da validação no Python.
- PEP 8 com linhas de até 120 caracteres; o `flake8` precisa passar sem erros.
- Templates estendem `base.html`, usam classes do Bootstrap e todo campo de formulário tem `<label>`.

## Testes e critério de pronto

Um pacote só está pronto quando:

1. Cada critério de aceite da história tem pelo menos um teste em `apps/<app>/tests.py`.
2. As migrações foram criadas e fazem parte do commit.
3. Todas as verificações abaixo passam:

```
flake8
python manage.py makemigrations --check --dry-run
coverage run manage.py test
coverage report
```

A cobertura mínima das regras de negócio é 70% durante os sprints e 80% na entrega final.

## Fluxo de Git

- Nunca trabalhe nem faça commit direto na `main`.
- Uma branch por pacote, com o número no nome: `4.2.2-cadastro-produtos`.
- Commits pequenos, com mensagens em português no imperativo: "Adiciona modelo de produto".
- Nunca envie o `.env`, `db.sqlite3` ou a pasta `media/`.
- O pull request leva `Closes #<número da issue>` na descrição e precisa da aprovação do outro integrante.

## Fora do escopo do MVP

Não implemente, a menos que o pedido diga explicitamente: variações de tamanho e cor, cupons e campanhas, programa de pontos, pagamento real por gateway, frete ou entrega (só retirada na loja), nota fiscal, identificação do cliente no PDV e ranking de produtos mais e menos vendidos.

## Ao terminar uma tarefa

Informe o que foi feito, os arquivos criados ou alterados, o resultado das verificações e como testar manualmente no navegador.
