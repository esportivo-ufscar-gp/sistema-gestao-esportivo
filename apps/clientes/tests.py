"""
Testes unitários do módulo Clientes.

Pacote 4.6.1: cadastro com consentimento LGPD (HU14).
Pacote 4.6.2: histórico de compras ("Meus pedidos") (HU15).
Pacote 4.5.3: identificação do cliente no checkout da loja online (HU12).
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Group, User
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.contas.services import PERFIL_CLIENTE, PERFIL_ESTOQUISTA, PERFIL_VENDEDOR, perfil_do_usuario
from apps.produtos.models import Categoria, Produto
from apps.vendas.models import CanalDeVenda, FormaDePagamento, ItemVenda, StatusDeVenda, Venda
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
