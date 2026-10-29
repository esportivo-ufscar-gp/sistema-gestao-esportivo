# Sistema de Gestão Integrada Esportivo UFSCar

Sistema web de gestão de produtos, estoque, vendas e clientes da loja física e da loja online
da Esportivo UFSCar. Este repositório contém o MVP definido na Declaração de Escopo do projeto
**ESP-2026-01**.

**Equipe:** Gabriel Urbano (gerente do projeto) e Eric Lopes (líder técnico).

## Tecnologias

- Python 3.12 e Django 5.2
- PostgreSQL
- HTML, CSS (Bootstrap 5) e JavaScript
- Testes com o framework de testes do Django, cobertura com coverage.py e estilo PEP 8 com flake8
- Integração contínua com GitHub Actions

## Estrutura

```
config/            configurações do projeto Django
apps/
  core/            páginas gerais e verificação de saúde (/health/)
  contas/          4.1 Acesso e Segurança
  produtos/        4.2 Produtos
  estoque/         4.3 Estoque
  vendas/          4.4 Vendas na Loja Física (PDV)
  loja/            4.5 Loja Online
  clientes/        4.6 Clientes
  relatorios/      4.7 Relatórios
templates/         template base do sistema
static/            arquivos estáticos próprios (CSS e JavaScript)
```

Cada app corresponde a um módulo do ramo "4. Sistema (MVP)" da EAP.

## Como rodar localmente

Pré-requisitos: Python 3.12, Git e PostgreSQL.

```bash
git clone https://github.com/esportivo-ufscar-gp/sistema-gestao-esportivo.git
cd sistema-gestao-esportivo

python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux ou macOS

pip install -r requirements-dev.txt

copy .env.example .env          # Windows
# cp .env.example .env          # Linux ou macOS
```

Edite o `.env` com os dados do seu PostgreSQL e crie o banco `esportivo`
(por exemplo, com `createdb esportivo` ou pelo pgAdmin). Para começar sem PostgreSQL,
use `DB_ENGINE=sqlite` no `.env`, lembrando que os testes de concorrência de estoque
exigem o PostgreSQL.

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py loaddata dados_exemplo   # catálogo de demonstração (opcional)
python manage.py runserver
```

Acesse http://localhost:8000 e a administração em http://localhost:8000/admin.

A fixture `dados_exemplo` carrega 6 categorias e 10 produtos para demonstração. Os saldos que
ela traz são apenas carga inicial: a partir daí, o estoque só muda pelo serviço de estoque.

## Qualidade

Antes de abrir um pull request, rode localmente as mesmas verificações da integração contínua:

```bash
flake8
python manage.py makemigrations --check --dry-run
coverage run manage.py test
coverage report
```

A meta de cobertura das regras de negócio é de 70% nos sprints intermediários e 80% na entrega
final (configurada em `.coveragerc`).

## Fluxo de trabalho

1. Cada pacote de trabalho da EAP é uma issue no quadro do projeto.
2. Crie uma branch a partir da `main` com o número do pacote, por exemplo `4.3.2-baixa-estoque`.
3. Abra um pull request com `Closes #<número da issue>` na descrição.
4. O outro integrante revisa e aprova. A integração contínua precisa passar.
5. Depois da aprovação, integre o pull request. A issue é fechada automaticamente.

Um pacote só está pronto quando a funcionalidade está integrada à `main`, com testes unitários
passando e código revisado.
