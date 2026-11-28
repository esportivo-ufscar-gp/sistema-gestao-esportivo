"""
Testes unitários do módulo Clientes.

Pacote 4.6.1: cadastro com consentimento LGPD (HU14).
Pacote 4.6.2: histórico de compras ("Meus pedidos") (HU15).
Pacote 4.5.3: identificação do cliente no checkout da loja online (HU12).
"""
from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Group, User
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.contas.services import (
    PERFIL_ADMINISTRADOR,
    PERFIL_CLIENTE,
    PERFIL_ESTOQUISTA,
    PERFIL_VENDEDOR,
    perfil_do_usuario,
)
from apps.produtos.models import Categoria, Produto
from apps.vendas.models import CanalDeVenda, FormaDePagamento, ItemVenda, StatusDeVenda, Venda
from apps.vendas.services import cancelar_venda, marcar_retirado, registrar_pedido_online, registrar_venda_pdv
from .admin import ClienteAdmin
from .forms import FormularioDeCadastroCliente
from .models import Cliente
from .services import (
    ConsentimentoObrigatorio,
    ContaSemCadastroDeCliente,
    EmailDeUmaConta,
    EquipeNaoCompraNaLoja,
    ErroDeIdentificacao,
    cadastrar_cliente,
    cliente_da_conta,
    cliente_do_checkout,
    contagem_por_status,
    identificar_visitante,
    pedidos_do_cliente,
)

Usuario = get_user_model()


class CadastroClienteServiceTests(TestCase):
    """Testes da regra de negócio cadastrar_cliente em services.py."""

    @classmethod
    def setUpTestData(cls):
        call_command("criar_perfis", verbosity=0)

    def test_cadastra_cliente_com_sucesso_e_registra_consentimento(self):
        usuario, cliente = cadastrar_cliente(
            nome="Marina Silva",
            email="marina@exemplo.com",
            telefone="(16) 99888-7766",
            senha="SenhaForte123!",
        )

        self.assertEqual(usuario.email, "marina@exemplo.com")
        self.assertEqual(usuario.username, "marina@exemplo.com")
        self.assertFalse(usuario.is_staff)
        self.assertEqual(perfil_do_usuario(usuario), PERFIL_CLIENTE)

        self.assertEqual(cliente.nome, "Marina Silva")
        self.assertEqual(cliente.email, "marina@exemplo.com")
        self.assertEqual(cliente.telefone, "(16) 99888-7766")
        self.assertIsNotNone(cliente.consentimento_em)

    def test_email_repetido_e_recusado_mesmo_com_case_diferente(self):
        cadastrar_cliente("Marina Silva", "marina@exemplo.com", "1699999999", "SenhaForte123!")

        with self.assertRaises(ValidationError) as erro:
            cadastrar_cliente("Outra Marina", "MARINA@EXEMPLO.COM", "1688888888", "SenhaForte123!")

        self.assertIn("email", erro.exception.message_dict)

    def test_email_existente_no_usuario_django_bloqueia_cadastro(self):
        User.objects.create_user(username="existente@exemplo.com", email="existente@exemplo.com", password="123")

        with self.assertRaises(ValidationError) as erro:
            cadastrar_cliente("Novo Cliente", "existente@exemplo.com", "1699999999", "SenhaForte123!")

        self.assertIn("email", erro.exception.message_dict)

    def test_senha_fraca_e_recusada_sem_criar_conta(self):
        for senha in ("1", "12345678", "password", "marina@exemplo.com"):
            with self.assertRaises(ValidationError, msg=senha) as erro:
                cadastrar_cliente("Marina Silva", "marina@exemplo.com", "1699999999", senha)

            self.assertIn("senha", erro.exception.message_dict)
        self.assertFalse(User.objects.filter(email="marina@exemplo.com").exists())
        self.assertFalse(Cliente.objects.exists())

    def test_email_unico_garantido_no_banco_de_dados(self):
        u1 = User.objects.create_user("c1@exemplo.com", "c1@exemplo.com", "SenhaForte123!")
        Cliente.objects.create(nome="C1", email="c1@exemplo.com",
                               telefone="111", usuario=u1,
                               consentimento_em=timezone.now())

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                u2 = User.objects.create_user("c2@exemplo.com", "c2@exemplo.com", "SenhaForte123!")
                Cliente.objects.create(nome="C2", email="C1@EXEMPLO.COM",
                                       telefone="222", usuario=u2,
                                       consentimento_em=timezone.now())


class FormularioCadastroClienteTests(TestCase):
    """Testes do formulário de cadastro e consentimentos."""

    def test_formulario_sem_campos_lgpd_ou_termos_e_invalido(self):
        dados = {
            "nome": "Marina Silva",
            "email": "marina@exemplo.com",
            "telefone": "(16) 99888-7766",
            "senha": "SenhaForte123!",
            "confirmacao_senha": "SenhaForte123!",
            "aceito_termos": False,
            "autorizo_lgpd": False,
        }
        form = FormularioDeCadastroCliente(dados)

        self.assertFalse(form.is_valid())
        self.assertIn("aceito_termos", form.errors)
        self.assertIn("autorizo_lgpd", form.errors)

    def test_senhas_diferentes_sao_recusadas(self):
        dados = {
            "nome": "Marina Silva",
            "email": "marina@exemplo.com",
            "telefone": "(16) 99888-7766",
            "senha": "SenhaForte123!",
            "confirmacao_senha": "SenhaDiferente123!",
            "aceito_termos": True,
            "autorizo_lgpd": True,
        }
        form = FormularioDeCadastroCliente(dados)

        self.assertFalse(form.is_valid())
        self.assertIn("confirmacao_senha", form.errors)

    def test_formulario_nao_contem_campos_cpf_ou_endereco(self):
        form = FormularioDeCadastroCliente()
        campos = set(form.fields.keys())

        self.assertNotIn("cpf", campos)
        self.assertNotIn("endereco", campos)


class ViewCadastroClienteTests(TestCase):
    """Testes de fluxo HTTP na tela /clientes/cadastro/."""

    @classmethod
    def setUpTestData(cls):
        call_command("criar_perfis", verbosity=0)

    def test_acesso_get_exibe_tela_de_cadastro(self):
        resposta = self.client.get(reverse("clientes:cadastro"))

        self.assertEqual(resposta.status_code, 200)
        self.assertTemplateUsed(resposta, "clientes/cadastro.html")
        self.assertContains(resposta, "Criar conta")
        self.assertContains(resposta, "Como usamos seus dados")

    def test_post_valido_cria_cliente_efetua_login_e_redireciona(self):
        resposta = self.client.post(
            reverse("clientes:cadastro"),
            {
                "nome": "Marina Silva",
                "email": "marina@exemplo.com",
                "telefone": "(16) 99888-7766",
                "senha": "SenhaForte123!",
                "confirmacao_senha": "SenhaForte123!",
                "aceito_termos": True,
                "autorizo_lgpd": True,
            },
        )

        self.assertRedirects(resposta, reverse("loja:catalogo"))
        self.assertTrue(Cliente.objects.filter(email="marina@exemplo.com").exists())
        self.assertIn("_auth_user_id", self.client.session)

    def dados(self, **campos):
        return {
            "nome": "Marina Silva", "email": "marina@exemplo.com", "telefone": "(16) 99888-7766",
            "senha": "SenhaForte123!", "confirmacao_senha": "SenhaForte123!",
            "aceito_termos": True, "autorizo_lgpd": True, **campos,
        }

    def test_senha_curta_mostra_erro_no_campo_e_nao_cria_conta(self):
        resposta = self.client.post(reverse("clientes:cadastro"), self.dados(senha="abc12", confirmacao_senha="abc12"))

        self.assertEqual(resposta.status_code, 200)
        self.assertIn("senha", resposta.context["form"].errors)
        self.assertContains(resposta, "pelo menos 8 caracteres")
        self.assertFalse(Cliente.objects.exists())
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_email_de_conta_da_equipe_mostra_erro_no_campo(self):
        # O formulário só confere o e-mail entre os clientes; a conta da equipe é barrada pelo serviço.
        User.objects.create_user("carla", "carla@esportivo.com", "SenhaForte123!", is_staff=True)

        resposta = self.client.post(reverse("clientes:cadastro"), self.dados(email="carla@esportivo.com"))

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.context["form"].errors["email"], ["Já existe uma conta cadastrada com este e-mail."])
        self.assertFalse(Cliente.objects.exists())

    def test_rotulos_dos_campos_em_portugues_com_acentos(self):
        # Roteiro 5.1, CT-30: a tela mostrava "Email" e "Confirmacao senha" (nomes dos campos).
        resposta = self.client.get(reverse("clientes:cadastro"))

        rotulos = [campo.label for campo in resposta.context["form"]][:5]
        self.assertEqual(rotulos, ["Nome", "E-mail", "Telefone", "Senha", "Confirmação da senha"])
        self.assertNotContains(resposta, "Confirmacao")

    def test_email_de_cliente_ja_cadastrado_mostra_erro_no_campo_sem_mensagem_tecnica(self):
        # Roteiro 5.1, CT-21: o e-mail de um cliente já cadastrado caía na restrição do banco, e a
        # tela mostrava 'Restrição "cliente_email_unico_ci" foi violada.' no topo do formulário.
        Cliente.objects.create(
            nome="Marina Souza", email="marina@exemplo.com", telefone="", consentimento_em=timezone.now()
        )

        resposta = self.client.post(reverse("clientes:cadastro"), self.dados(email="MARINA@exemplo.com"))

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.context["form"].errors["email"], ["Já existe uma conta cadastrada com este e-mail."])
        self.assertEqual(resposta.context["form"].non_field_errors(), [])
        self.assertNotContains(resposta, "cliente_email_unico_ci")
        self.assertEqual(Cliente.objects.count(), 1)

    def test_usuario_logado_ao_acessar_cadastro_e_redirecionado(self):
        usuario = User.objects.create_user("cliente", "cliente@exemplo.com", "senha")
        self.client.force_login(usuario)

        resposta = self.client.get(reverse("clientes:cadastro"))

        self.assertRedirects(resposta, reverse("contas:painel"))


class AdminClienteTests(TestCase):
    """Testes da interface do Django Admin para Clientes."""

    def test_admin_configuracao_de_colunas_e_busca(self):
        self.assertEqual(ClienteAdmin.list_display, ("nome", "email", "telefone", "consentimento_em", "criado_em"))
        self.assertEqual(ClienteAdmin.search_fields, ("nome", "email"))
        self.assertEqual(ClienteAdmin.readonly_fields, ("consentimento_em", "criado_em"))

    def test_admin_nao_cria_cliente_porque_o_consentimento_vem_do_proprio_cliente(self):
        call_command("criar_perfis", verbosity=0)
        gerente = User.objects.create_user("carla", "carla@exemplo.com", "SenhaForte123!", is_staff=True)
        gerente.groups.add(Group.objects.get(name=PERFIL_ADMINISTRADOR))
        self.client.force_login(gerente)
        adicionar = reverse("admin:clientes_cliente_add")

        # O administrador tem a permissão add_cliente: quem barra é o ClienteAdmin.
        self.assertTrue(gerente.has_perm("clientes.add_cliente"))

        lista = self.client.get(reverse("admin:clientes_cliente_changelist"))
        self.assertEqual(lista.status_code, 200)
        self.assertNotContains(lista, adicionar)
        self.assertNotContains(self.client.get(reverse("admin:index")), adicionar)

        self.assertEqual(self.client.get(adicionar).status_code, 403)
        resposta = self.client.post(adicionar, {"nome": "Sem Consentimento", "email": "x@exemplo.com",
                                                "telefone": "1"})
        self.assertEqual(resposta.status_code, 403)
        self.assertFalse(Cliente.objects.exists())


class IdentificacaoNoCheckoutTests(TestCase):
    """HU12: quem compra pela loja online é identificado sem fazer pedido no nome de outra pessoa."""

    @classmethod
    def setUpTestData(cls):
        call_command("criar_perfis", verbosity=0)

    def _visitante(self, **campos):
        dados = {"nome": "Marina Silva", "email": "marina@exemplo.com", "telefone": "(16) 99888-7766",
                 "consentiu": True}
        return identificar_visitante(**(dados | campos))

    def test_email_novo_cria_cliente_sem_conta_com_consentimento_do_servidor(self):
        antes = timezone.now()

        cliente = self._visitante(email="  Marina@Exemplo.COM ")

        self.assertIsNone(cliente.usuario)
        self.assertEqual(cliente.email, "marina@exemplo.com")
        self.assertEqual(cliente.nome, "Marina Silva")
        self.assertGreaterEqual(cliente.consentimento_em, antes)
        self.assertLessEqual(cliente.consentimento_em, timezone.now())
        self.assertFalse(User.objects.exists())

    def test_sem_consentimento_nada_e_gravado(self):
        with self.assertRaises(ConsentimentoObrigatorio):
            self._visitante(consentiu=False)

        self.assertFalse(Cliente.objects.exists())

    def test_email_de_cliente_sem_conta_reaproveita_o_cadastro_e_atualiza_o_consentimento(self):
        primeiro = self._visitante()
        Cliente.objects.filter(pk=primeiro.pk).update(consentimento_em=timezone.now() - timedelta(days=30))

        de_novo = self._visitante(email="MARINA@exemplo.com")

        self.assertEqual(de_novo.pk, primeiro.pk)
        self.assertEqual(Cliente.objects.count(), 1)
        self.assertGreater(de_novo.consentimento_em, timezone.now() - timedelta(minutes=1))

    def test_email_de_uma_conta_exige_login(self):
        cadastrar_cliente("Marina Silva", "marina@exemplo.com", "1699999999", "SenhaForte123!")
        User.objects.create_user("equipe", "vendedor@exemplo.com", "SenhaForte123!")

        for email in ("MARINA@exemplo.com", "vendedor@exemplo.com"):
            with self.subTest(email=email):
                with self.assertRaisesMessage(EmailDeUmaConta, "Entre na conta"):
                    self._visitante(email=email)

        self.assertEqual(Cliente.objects.count(), 1)

    def test_cliente_ligado_a_uma_conta_com_outro_email_tambem_exige_login(self):
        usuario = User.objects.create_user("marina", "outro@exemplo.com", "SenhaForte123!")
        Cliente.objects.create(nome="Marina", email="marina@exemplo.com", telefone="1",
                               usuario=usuario, consentimento_em=timezone.now())

        with self.assertRaises(EmailDeUmaConta):
            self._visitante()

    def test_cliente_logado_usa_o_proprio_cadastro(self):
        usuario, cliente = cadastrar_cliente("Marina Silva", "marina@exemplo.com", "1699999999", "SenhaForte123!")

        self.assertEqual(cliente_da_conta(usuario), cliente)
        self.assertEqual(cliente_do_checkout(usuario), cliente)

    def test_equipe_nao_faz_pedido_pela_loja(self):
        administrador = User.objects.create_superuser("gerente", "gerente@exemplo.com", "SenhaForte123!")
        equipe = [administrador]
        for perfil in (PERFIL_VENDEDOR, PERFIL_ESTOQUISTA):
            usuario = User.objects.create_user(perfil, f"{perfil}@exemplo.com", "SenhaForte123!")
            usuario.groups.add(Group.objects.get(name=perfil))
            equipe.append(usuario)

        for usuario in equipe:
            with self.subTest(usuario=usuario.username):
                with self.assertRaisesMessage(EquipeNaoCompraNaLoja, "Contas da equipe"):
                    cliente_da_conta(usuario)

    def test_conta_sem_cadastro_de_cliente_e_avisada(self):
        usuario = User.objects.create_user("avulso", "avulso@exemplo.com", "SenhaForte123!")

        with self.assertRaises(ContaSemCadastroDeCliente):
            cliente_da_conta(usuario)

    def test_visitante_sem_dados_e_recusado(self):
        with self.assertRaises(ErroDeIdentificacao):
            cliente_do_checkout(AnonymousUser())


class HistoricoDeComprasTests(TestCase):
    """HU15: Histórico de compras ("Meus pedidos")."""

    def setUp(self):
        call_command("criar_perfis", verbosity=0)
        self.usuario, self.cliente = cadastrar_cliente(
            "Carlos Rocha", "carlos@exemplo.com", "16999998888", "SenhaForte123!"
        )
        self.categoria = Categoria.objects.create(nome="Futebol")
        self.produto = Produto.objects.create(
            codigo="PROD001",
            nome="Bola de Futebol",
            preco=100.00,
            estoque_atual=10,
            categoria=self.categoria,
        )

    def test_cliente_visualiza_seus_pedidos(self):
        venda = Venda.objects.create(
            numero=1001,
            canal=CanalDeVenda.ONLINE,
            status=StatusDeVenda.AGUARDANDO_RETIRADA,
            forma_pagamento=FormaDePagamento.PIX,
            total=100.00,
            cliente=self.cliente,
        )
        ItemVenda.objects.create(venda=venda, produto=self.produto, quantidade=1, preco_unitario=100.00)

        pedidos = pedidos_do_cliente(self.usuario)
        self.assertEqual(len(pedidos), 1)
        self.assertEqual(pedidos[0].numero, 1001)

    def test_view_meus_pedidos_requer_login(self):
        url_login = reverse("contas:entrar")
        url_pedidos = reverse("clientes:meus_pedidos")
        resposta = self.client.get(url_pedidos)
        self.assertRedirects(resposta, f"{url_login}?next={url_pedidos}")

    def test_view_meus_pedidos_exibe_lista(self):
        venda = Venda.objects.create(
            numero=1002,
            canal=CanalDeVenda.ONLINE,
            status=StatusDeVenda.AGUARDANDO_RETIRADA,
            forma_pagamento=FormaDePagamento.PIX,
            total=100.00,
            cliente=self.cliente,
        )
        ItemVenda.objects.create(venda=venda, produto=self.produto, quantidade=1, preco_unitario=100.00)

        self.client.force_login(self.usuario)
        resposta = self.client.get(reverse("clientes:meus_pedidos"))

        self.assertEqual(resposta.status_code, 200)
        self.assertTemplateUsed(resposta, "clientes/meus_pedidos.html")
        self.assertContains(resposta, "#1002")


class MeusPedidosTests(TestCase):
    """HU15: o cliente vê só os próprios pedidos online, com filtro por status."""

    @classmethod
    def setUpTestData(cls):
        call_command("criar_perfis", verbosity=0)
        cls.categoria = Categoria.objects.create(nome="Corrida")
        cls.tenis = Produto.objects.create(
            codigo="100110", nome="Tênis de corrida", categoria=cls.categoria,
            preco=Decimal("349.90"), estoque_atual=50,
        )
        cls.garrafa = Produto.objects.create(
            codigo="100120", nome="Garrafa térmica", categoria=cls.categoria,
            preco=Decimal("49.90"), estoque_atual=50,
        )
        cls.usuario, cls.cliente = cadastrar_cliente("Marina Silva", "marina@exemplo.com", "1699999999",
                                                     "SenhaForte123!")
        cls.vendedor = User.objects.create_user("ana", "ana@exemplo.com", "SenhaForte123!", is_staff=True)
        cls.vendedor.groups.add(Group.objects.get(name=PERFIL_VENDEDOR))

    def setUp(self):
        self.client.force_login(self.usuario)
        self.endereco = reverse("clientes:meus_pedidos")

    def pedido(self, produto=None, cliente=None):
        return registrar_pedido_online(cliente or self.cliente, [(produto or self.tenis, 1)], FormaDePagamento.PIX)

    def numeros(self, resposta):
        return [pedido.numero for pedido in resposta.context["pedidos"]]

    def test_mostra_data_itens_total_e_status_de_cada_pedido(self):
        pedido = self.pedido()

        resposta = self.client.get(self.endereco)

        self.assertContains(resposta, "Pedido #0001")
        self.assertContains(resposta, timezone.localtime(pedido.criado_em).strftime("%d/%m/%Y"))
        self.assertContains(resposta, "Tênis de corrida")
        self.assertContains(resposta, "R$ 349,90")
        self.assertContains(resposta, "Aguardando retirada")

    def test_cliente_nao_ve_os_pedidos_de_outro(self):
        _, outro = cadastrar_cliente("João Souza", "joao@exemplo.com", "1688888888", "SenhaForte123!")
        meu = self.pedido()
        alheio = self.pedido(produto=self.garrafa, cliente=outro)

        resposta = self.client.get(self.endereco)

        self.assertEqual(self.numeros(resposta), [meu.numero])
        self.assertNotContains(resposta, alheio.numero_formatado)
        self.assertNotContains(resposta, "Garrafa térmica")

    def test_vendas_do_pdv_ficam_fora(self):
        registrar_venda_pdv(self.vendedor, [(self.garrafa, 1)], FormaDePagamento.DINHEIRO)
        pedido = self.pedido()

        resposta = self.client.get(self.endereco)

        self.assertEqual(self.numeros(resposta), [pedido.numero])
        self.assertEqual(resposta.context["filtros"][0]["quantidade"], 1)
        self.assertNotContains(resposta, "Garrafa térmica")

    def test_equipe_recebe_403_e_visitante_vai_para_a_entrada(self):
        administrador = User.objects.create_superuser("carla", "carla@exemplo.com", "SenhaForte123!")
        estoquista = User.objects.create_user("bruno", "bruno@exemplo.com", "SenhaForte123!")
        estoquista.groups.add(Group.objects.get(name=PERFIL_ESTOQUISTA))

        for usuario in (administrador, self.vendedor, estoquista):
            with self.subTest(usuario=usuario.username):
                self.client.force_login(usuario)
                self.assertEqual(self.client.get(self.endereco).status_code, 403)

        self.client.logout()
        resposta = self.client.get(self.endereco)
        self.assertRedirects(resposta, f"{reverse('contas:entrar')}?next={self.endereco}")

    def test_cada_filtro_mostra_so_o_seu_status_com_os_contadores(self):
        aguardando = [self.pedido(), self.pedido()]
        retirado = self.pedido()
        cancelado = self.pedido()
        marcar_retirado(retirado, self.vendedor)
        cancelar_venda(cancelado, self.vendedor)

        esperado = {
            "": sorted([pedido.numero for pedido in aguardando + [retirado, cancelado]], reverse=True),
            StatusDeVenda.AGUARDANDO_RETIRADA: sorted([pedido.numero for pedido in aguardando], reverse=True),
            StatusDeVenda.RETIRADA: [retirado.numero],
            StatusDeVenda.CANCELADA: [cancelado.numero],
        }
        for status, numeros in esperado.items():
            with self.subTest(status=status or "todos"):
                resposta = self.client.get(self.endereco, {"status": status} if status else {})

                self.assertEqual(self.numeros(resposta), numeros)
                self.assertEqual(
                    [(filtro["rotulo"], filtro["quantidade"]) for filtro in resposta.context["filtros"]],
                    [("Todos", 4), ("Aguardando retirada", 2), ("Retirados", 1), ("Cancelados", 1)],
                )
                ativos = [filtro["rotulo"] for filtro in resposta.context["filtros"] if filtro["ativo"]]
                self.assertEqual(len(ativos), 1)

        resposta = self.client.get(self.endereco, {"status": StatusDeVenda.RETIRADA})
        self.assertContains(resposta, "Todos (4)")
        self.assertContains(resposta, "Aguardando retirada (2)")
        self.assertContains(resposta, 'class="filtro-categoria ativo"')
        self.assertContains(resposta, "Retirados (1)</a>")

    def test_status_desconhecido_mostra_todos(self):
        self.pedido()

        resposta = self.client.get(self.endereco, {"status": "concluida"})

        self.assertEqual(resposta.context["status_atual"], "")
        self.assertEqual(len(self.numeros(resposta)), 1)

    def test_filtro_sem_resultados_tem_mensagem_propria(self):
        self.pedido()

        resposta = self.client.get(self.endereco, {"status": StatusDeVenda.CANCELADA})

        self.assertContains(resposta, "Nenhum pedido com esse status")
        self.assertNotContains(resposta, "Você ainda não fez nenhum pedido")
        self.assertContains(resposta, "Cancelados (0)")

    def test_cliente_sem_pedidos_ve_a_mensagem_de_primeira_compra_sem_filtros(self):
        resposta = self.client.get(self.endereco)

        self.assertContains(resposta, "Você ainda não fez nenhum pedido")
        self.assertNotContains(resposta, "Nenhum pedido com esse status")
        self.assertNotContains(resposta, "Todos (0)")

    def test_aguardando_retirada_mostra_local_e_horario(self):
        self.pedido()

        with self.settings(LOJA_ENDERECO="Rua das Flores, 100", LOJA_HORARIO="Seg. a sáb., 9h às 18h"):
            resposta = self.client.get(self.endereco)

        self.assertContains(resposta, "Rua das Flores, 100 · Seg. a sáb., 9h às 18h")

    def test_retirado_mostra_a_data_da_retirada_no_fuso_da_loja(self):
        pedido = self.pedido()
        marcar_retirado(pedido, self.vendedor)
        # 23h30 de 10/11 em São Paulo já é dia 11/11 em UTC: a tela precisa mostrar 10/11.
        retirada = timezone.make_aware(datetime(2026, 11, 10, 23, 30))
        Venda.objects.filter(pk=pedido.pk).update(retirada_em=retirada)

        resposta = self.client.get(self.endereco)

        self.assertContains(resposta, "Retirado em 10/11/2026")
        self.assertNotContains(resposta, "Retire na loja")

    def test_cancelado_mostra_total_riscado_e_observacao(self):
        pedido = self.pedido()
        cancelar_venda(pedido, self.vendedor)

        resposta = self.client.get(self.endereco)

        self.assertContains(
            resposta, "Pedido cancelado: os itens voltaram ao estoque e o valor não foi cobrado."
        )
        self.assertContains(resposta, '<s class="text-body-secondary" data-teste="total-riscado">R$ 349,90</s>',
                            html=True)
        self.assertNotContains(resposta, "Retire na loja")

    def test_contagem_por_status_numa_consulta_e_zerada_sem_cliente(self):
        self.pedido()
        usuario = User.objects.get(pk=self.usuario.pk)  # sem o cliente já carregado em memória

        with self.assertNumQueries(2):  # cliente da conta + uma agregação para todos os contadores
            contagem = contagem_por_status(usuario)

        self.assertEqual(contagem["todos"], 1)
        self.assertEqual(contagem[StatusDeVenda.AGUARDANDO_RETIRADA], 1)
        sem_cliente = User.objects.create_user("avulso", "avulso@exemplo.com", "SenhaForte123!")
        self.assertEqual(contagem_por_status(sem_cliente)["todos"], 0)
        self.assertFalse(pedidos_do_cliente(AnonymousUser()).exists())


class HistoricoDoClienteNoAdminTests(TestCase):
    """HU15: o administrador vê o histórico de cada cliente na página dele no Admin."""

    @classmethod
    def setUpTestData(cls):
        call_command("criar_perfis", verbosity=0)
        categoria = Categoria.objects.create(nome="Corrida")
        cls.tenis = Produto.objects.create(
            codigo="100110", nome="Tênis de corrida", categoria=categoria,
            preco=Decimal("349.90"), estoque_atual=50,
        )
        cls.gerente = User.objects.create_user("carla", "carla@exemplo.com", "SenhaForte123!", is_staff=True)
        cls.gerente.groups.add(Group.objects.get(name=PERFIL_ADMINISTRADOR))
        _, cls.cliente = cadastrar_cliente("Marina Silva", "marina@exemplo.com", "1699999999", "SenhaForte123!")
        _, cls.outro = cadastrar_cliente("João Souza", "joao@exemplo.com", "1688888888", "SenhaForte123!")

    def setUp(self):
        self.client.force_login(self.gerente)
        self.pedido = registrar_pedido_online(self.cliente, [(self.tenis, 2)], FormaDePagamento.PIX)
        self.alheio = registrar_pedido_online(self.outro, [(self.tenis, 1)], FormaDePagamento.CARTAO)
        cancelar_venda(self.pedido, self.gerente)
        self.pagina = reverse("admin:clientes_cliente_change", args=[self.cliente.pk])

    def test_pagina_do_cliente_lista_os_pedidos_dele(self):
        resposta = self.client.get(self.pagina)

        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Pedidos online")
        self.assertContains(resposta, "#0001")
        self.assertContains(resposta, "Cancelada")
        self.assertContains(resposta, "699,80")
        self.assertNotContains(resposta, "#0002")
        self.assertContains(resposta, reverse("admin:loja_pedidoonline_change", args=[self.pedido.pk]))

    def test_lista_e_somente_leitura_sem_adicionar_nem_excluir(self):
        resposta = self.client.get(self.pagina)
        conteudo = resposta.content.decode()

        self.assertNotIn('name="pedidos-0-status"', conteudo)
        self.assertNotIn('name="pedidos-0-total"', conteudo)
        self.assertNotIn('name="pedidos-0-DELETE"', conteudo)
        self.assertNotIn("Adicionar outro(a) pedido", conteudo)

        inline = ClienteAdmin(Cliente, admin.site).get_inline_instances(resposta.wsgi_request, self.cliente)[0]
        self.assertFalse(inline.has_add_permission(resposta.wsgi_request, self.cliente))
        self.assertFalse(inline.has_change_permission(resposta.wsgi_request, self.cliente))
        self.assertFalse(inline.can_delete)
