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
python manage.py criar_perfis             # cria os quatro perfis e suas permissões
python manage.py loaddata dados_exemplo   # catálogo de demonstração (opcional)
python manage.py runserver
```

Acesse http://localhost:8000 e a administração em http://localhost:8000/admin.

A fixture `dados_exemplo` carrega 6 categorias e 10 produtos para demonstração. Os saldos que
ela traz são apenas carga inicial: a partir daí, o estoque só muda pelo serviço de estoque.

## Perfis e acesso

A entrada do sistema é http://localhost:8000/contas/entrar/, com **e-mail e senha**. Todos os
perfis entram por essa tela; o Django Admin mantém a sua própria tela, por nome de usuário.

Os perfis são grupos do Django, criados pelo comando `criar_perfis`:

| Perfil | Acesso hoje | Precisa de "Membro da equipe" (`is_staff`) |
| --- | --- | --- |
| `administrador` | Admin completo de produtos, estoque e vendas, mais o painel de estoque e o PDV | sim |
| `vendedor` | PDV em `/vendas/pdv/`; no Admin, consulta produtos e vendas | só se for usar o Admin |
| `estoquista` | painel de estoque em `/estoque/`; no Admin, consulta produtos e o histórico de movimentos | só se for usar o Admin |
| `cliente` | nenhum acesso ao Admin; usa a loja online (pacote 4.5) | não |

Depois de entrar, cada perfil vai direto para a sua tela: o vendedor para o PDV, o estoquista
para o painel de estoque, o administrador para o Admin e o cliente para o painel provisório.

Rode `python manage.py criar_perfis` de novo sempre que um pacote novo acrescentar permissões
(o comando é idempotente). Um superusuário conta como administrador mesmo fora do grupo.

### Criar um usuário de cada perfil pelo Admin

1. Entre no Admin como superusuário e vá em **Autenticação e autorização > Usuários > Adicionar**.
2. Informe o nome de usuário e a senha e salve.
3. Na tela seguinte, preencha o **endereço de e-mail** — é por ele que a pessoa entra no
   sistema. Use um e-mail diferente para cada usuário.
4. Em **Permissões**, mova para "Grupos escolhidos" apenas o grupo do perfil dela.
5. Marque **Membro da equipe** se o perfil usa o Admin (veja a tabela acima). Deixe
   **Superusuário** só para quem administra o projeto.
6. Salve e peça para a pessoa entrar em `/contas/entrar/` com o e-mail e a senha.

Para trocar o perfil de alguém, basta trocar o grupo: as permissões vêm do grupo, não do usuário.

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
