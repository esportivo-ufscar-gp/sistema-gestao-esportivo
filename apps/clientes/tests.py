"""
Testes unitários do módulo Clientes.

Pacote 4.6.1: cadastro com consentimento LGPD (HU14).
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.contas.services import PERFIL_CLIENTE, perfil_do_usuario
from .admin import ClienteAdmin
from .forms import FormularioDeCadastroCliente
from .models import Cliente
from .services import cadastrar_cliente

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

        self.assertRedirects(resposta, reverse("contas:painel"))
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
