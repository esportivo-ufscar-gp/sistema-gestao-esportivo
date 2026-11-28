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

### Dados de demonstração (pacote 3.3)

Para apresentar o sistema, rode em um banco recém-migrado, ainda sem vendas e sem as contas da
demonstração:

```bash
python manage.py migrate
python manage.py popular_demonstracao
```

Não existe senha padrão, porque o repositório é público. A senha dos usuários de demonstração
vem, nesta ordem:

1. da opção `--senha`;
2. da variável de ambiente `DEMO_SENHA` (a forma recomendada no ambiente hospedado, porque o
   que vai na linha de comando fica no histórico do terminal);
3. se nenhuma das duas for informada, de uma senha aleatória gerada pelo comando e mostrada
   **uma única vez** no fim da saída. Anote-a nesse momento.

A senha informada segue as mesmas regras do cadastro de cliente (mínimo de 8 caracteres, não
pode ser comum nem só números); uma senha fraca é recusada antes de gravar qualquer dado.

O comando cria os perfis e um usuário de cada perfil (`admin@esportivo.demo`,
`vendedor@esportivo.demo`, `estoquista@esportivo.demo` e a cliente `marina@esportivo.demo`). A
equipe entra no Admin e vê lá só o que o seu perfil permite. Se o banco não tiver produtos, o
comando carrega o catálogo de exemplo com saldo zero e dá entrada no saldo de cada produto pelo
serviço de estoque, com o motivo "Saldo inicial". Depois, registra um mês de vendas nos dois
canais, com retiradas e cancelamentos. Tudo passa pelos serviços de estoque e de vendas, então,
para cada produto, a soma dos movimentos é igual ao saldo.

O comando não grava nada e explica o motivo quando o banco já tem vendas, quando algum e-mail
da demonstração já está em uso ou quando há produto com saldo sem movimento de estoque que o
explique (por exemplo, depois de um `loaddata dados_exemplo`). Com `--se-vazio`, um banco que
já tem vendas é deixado como está, sem erro: é assim que o deploy roda o comando.

### Publicar no Render (pacote 3.3)

O arquivo `render.yaml` descreve o site e o banco PostgreSQL nos planos gratuitos do Render. A
cada deploy, o `build.sh` instala as dependências, roda o `collectstatic` e o `migrate`, reaplica
os perfis e carrega os dados de demonstração (só no primeiro deploy).

1. Entre em https://render.com com a conta do GitHub que enxerga o repositório.
2. Abra https://dashboard.render.com/blueprints e clique em **New Blueprint Instance**.
3. Escolha o repositório `sistema-gestao-esportivo` e clique em **Connect**.
4. Dê um nome ao Blueprint e, no campo `DEMO_SENHA`, digite a senha dos usuários de
   demonstração (mínimo de 8 caracteres, não pode ser comum nem só números). Guarde essa senha
   fora do repositório. Clique em **Apply**.
5. Espere o banco e o site ficarem prontos (alguns minutos). O endereço aparece no topo da
   página do serviço `esportivo-ufscar`, no formato `https://<nome>.onrender.com`.
6. Entre com `admin@esportivo.demo` e a senha do passo 4. Os outros acessos são
   `vendedor@esportivo.demo`, `estoquista@esportivo.demo` e `marina@esportivo.demo`.

A partir daí, todo merge na `main` publica a versão nova sozinho. A `DJANGO_SECRET_KEY` é
gerada pelo próprio Render, e a conexão com o banco chega ao site pela `DATABASE_URL`.

Limites do plano gratuito:

- o site **dorme depois de 15 minutos** sem acesso e leva **cerca de 1 minuto** para acordar:
  abra-o um pouco antes de apresentar;
- o banco gratuito **expira 30 dias depois de criado** e é apagado depois de mais 14 dias;
- o disco do site é temporário: **imagens de produtos enviadas pelo Admin somem** quando o site
  reinicia ou dorme. Os produtos de demonstração usam o espaço reservado "Foto do produto".

Se o deploy falhar, a aba **Logs** do serviço mostra a etapa do `build.sh` que deu erro.

### Relatórios (pacote 4.7)

O administrador acessa http://localhost:8000/relatorios/ (link "Relatórios" no cabeçalho):

- **Vendas por período e canal (HU16):** número de vendas, valor total e ticket médio por canal
  e no total, entre a data inicial e a final; canceladas não entram.
- **Posição de estoque (HU17):** produto, categoria, saldo e mínimo, com filtro por categoria;
  saldo igual ou abaixo do mínimo aparece destacado, e um resumo mostra quantos produtos estão
  em cada situação. Categorias inativas aparecem na lista marcadas como "(inativa)" e não podem
  ser escolhidas; uma categoria inválida na URL mostra um aviso e volta para todas. A opção
  "Incluir produtos inativos" mostra também os produtos desativados, no fim e sem destaque.

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
final (configurada em `.coveragerc`, que já exige 80% a partir do Sprint 4). Para o relatório
de cobertura (pacote 5.2), gere também a versão em HTML com `coverage html` (pasta `htmlcov/`).

## Documentação do projeto

- [Roteiro de testes ponta a ponta](docs/Roteiro_Testes_Ponta_a_Ponta_5.1.docx) (pacote 5.1): 33 casos de
  teste manuais que percorrem o sistema no navegador, do cadastro de um produto até a venda nos dois
  canais, o cancelamento, o histórico do cliente e os relatórios, com foco no estoque compartilhado.
- [Documentação técnica](docs/Documentacao_Tecnica_6.1.docx) (pacote 6.1): descreve o sistema como foi
  construído, com tecnologias, arquitetura, modelo de dados, regras de negócio, perfis, configuração,
  instalação, qualidade e a publicação no Render, com o deploy automático e os limites do plano gratuito.
- [Encerramento e lições aprendidas](docs/Encerramento_e_Licoes_Aprendidas_1.4.docx) (pacote 1.4): rascunho
  do relatório de encerramento, com resultados, riscos, mudanças e lições aprendidas do projeto.

## Fluxo de trabalho

1. Cada pacote de trabalho da EAP é uma issue no quadro do projeto.
2. Crie uma branch a partir da `main` com o número do pacote, por exemplo `4.3.2-baixa-estoque`.
3. Abra um pull request com `Closes #<número da issue>` na descrição.
4. O outro integrante revisa e aprova. A integração contínua precisa passar.
5. Depois da aprovação, integre o pull request. A issue é fechada automaticamente.

Um pacote só está pronto quando a funcionalidade está integrada à `main`, com testes unitários
passando e código revisado.
