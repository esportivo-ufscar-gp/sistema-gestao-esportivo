"""
Testes unitários do módulo Contas e acesso.

Pacote 4.1: autenticação (4.1.1) e perfis e permissões (4.1.2).

Cada critério de aceite das histórias HU01 e HU02 tem pelo menos um teste. O urlconf do fim
do arquivo existe só para exercitar o decorator perfil_requerido sem criar telas de PDV,
estoque ou catálogo, que são de outros pacotes.
"""
from io import StringIO

from django.contrib.auth import authenticate
from django.contrib.auth.models import AnonymousUser, Group, User
from django.core.management import call_command
from django.http import HttpResponse
from django.test import TestCase, override_settings
from django.urls import include, path, reverse

from .decorators import perfil_requerido
from .services import (
    PERFIL_ADMINISTRADOR,
    PERFIL_CLIENTE,
    PERFIL_ESTOQUISTA,
    PERFIL_VENDEDOR,
    PERFIS,
    criar_perfis,
    destino_apos_login,
    perfil_do_usuario,
)

SENHA = "senha-de-teste-123"


def cria_usuario(nome, email, perfil=None, **campos):
    """Cria um usuário já com a senha de teste e, se for o caso, dentro do grupo do perfil."""
    usuario = User.objects.create_user(username=nome, email=email, password=SENHA, **campos)
    if perfil:
        usuario.groups.add(Group.objects.get(name=perfil))
    return usuario


class BaseDeContas(TestCase):
    """Perfis criados e um usuário de cada tipo, usados pelos testes de acesso."""

    @classmethod
    def setUpTestData(cls):
        call_command("criar_perfis", verbosity=0)
        cls.administrador = User.objects.create_superuser(
            "gerente", "gerente@exemplo.com", SENHA
        )
        cls.vendedor = cria_usuario("vendedor", "vendedor@exemplo.com", PERFIL_VENDEDOR, is_staff=True)
        cls.estoquista = cria_usuario("estoquista", "estoquista@exemplo.com", PERFIL_ESTOQUISTA)
        cls.cliente = cria_usuario("cliente", "cliente@exemplo.com", PERFIL_CLIENTE)
        cls.sem_perfil = cria_usuario("avulso", "avulso@exemplo.com")


# ----------------------------------------------------------- HU01 Autenticação (4.1.1)
class EntradaTests(BaseDeContas):
    """HU01: entrar com e-mail e senha."""

    def test_tela_de_entrada_tem_titulo_campos_e_aviso(self):
        resposta = self.client.get(reverse("contas:entrar"))

        self.assertTemplateUsed(resposta, "registration/login.html")
        self.assertTemplateUsed(resposta, "base.html")
        self.assertContains(resposta, "Entrar")
        self.assertContains(resposta, "E-mail")
        self.assertContains(resposta, "Senha")
        self.assertContains(resposta, "Vendedores, estoquistas e administradores")

    def test_credenciais_validas_levam_a_pagina_inicial_do_perfil(self):
        resposta = self.client.post(
            reverse("contas:entrar"),
            {"username": "vendedor@exemplo.com", "password": SENHA},
        )

        # A página inicial do vendedor é o PDV; o mapa está em services.DESTINO_POR_PERFIL.
        self.assertRedirects(resposta, reverse("vendas:pdv"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.vendedor.pk)

    def test_email_pode_ser_escrito_com_maiusculas(self):
        resposta = self.client.post(
            reverse("contas:entrar"),
            {"username": "Vendedor@Exemplo.COM", "password": SENHA},
        )

        self.assertRedirects(resposta, reverse("vendas:pdv"))

    def test_mensagem_de_erro_nao_revela_qual_campo_esta_errado(self):
        endereco = reverse("contas:entrar")

        senha_errada = self.client.post(endereco, {"username": "vendedor@exemplo.com", "password": "outra"})
        email_desconhecido = self.client.post(endereco, {"username": "ninguem@exemplo.com", "password": SENHA})

        mensagens = senha_errada.context["form"].non_field_errors()
        self.assertEqual(list(mensagens), ["E-mail ou senha inválidos."])
        self.assertEqual(list(mensagens), list(email_desconhecido.context["form"].non_field_errors()))
        self.assertEqual(senha_errada.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_invalido_mostra_a_mensagem_na_tela(self):
        resposta = self.client.post(
            reverse("contas:entrar"),
            {"username": "vendedor@exemplo.com", "password": "outra"},
        )

        self.assertContains(resposta, "E-mail ou senha inválidos.")

    def test_pagina_interna_sem_login_redireciona_para_a_entrada(self):
        resposta = self.client.get(reverse("contas:painel"))

        self.assertRedirects(resposta, f"{reverse('contas:entrar')}?next={reverse('contas:painel')}")

    def test_depois_de_entrar_o_usuario_volta_para_a_pagina_pedida(self):
        endereco = f"{reverse('contas:entrar')}?next={reverse('contas:painel')}"

        resposta = self.client.post(endereco, {"username": "cliente@exemplo.com", "password": SENHA})

        self.assertRedirects(resposta, reverse("contas:painel"))

    def test_painel_mostra_o_perfil_de_quem_entrou(self):
        self.client.force_login(self.estoquista)

        resposta = self.client.get(reverse("contas:painel"))

        self.assertEqual(resposta.context["perfil"], PERFIL_ESTOQUISTA)
        self.assertContains(resposta, PERFIL_ESTOQUISTA)


class SaidaTests(BaseDeContas):
    """HU01: sair encerra a sessão."""

    def test_sair_por_post_encerra_a_sessao(self):
        self.client.force_login(self.cliente)

        resposta = self.client.post(reverse("contas:sair"))

        self.assertRedirects(resposta, reverse("core:home"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_sair_nao_aceita_get(self):
        self.client.force_login(self.cliente)

        resposta = self.client.get(reverse("contas:sair"))

        self.assertEqual(resposta.status_code, 405)
        self.assertIn("_auth_user_id", self.client.session)

    def test_navbar_mostra_entrar_para_o_visitante(self):
        resposta = self.client.get(reverse("core:home"))

        self.assertContains(resposta, reverse("contas:entrar"))
        self.assertNotContains(resposta, reverse("contas:sair"))

    def test_navbar_mostra_sair_para_quem_entrou(self):
        self.client.force_login(self.cliente)

        resposta = self.client.get(reverse("contas:painel"))

        self.assertContains(resposta, reverse("contas:sair"))
        self.assertContains(resposta, "Sair")
        self.assertNotContains(resposta, reverse("contas:entrar"))

    def test_navbar_mostra_administracao_so_para_a_equipe(self):
        self.client.force_login(self.cliente)
        de_fora = self.client.get(reverse("contas:painel"))

        self.client.force_login(self.administrador)
        da_equipe = self.client.get(reverse("contas:painel"))

        self.assertNotContains(de_fora, reverse("admin:index"))
        self.assertContains(da_equipe, reverse("admin:index"))


class BackendDeEmailTests(BaseDeContas):
    """O backend encontra o usuário pelo e-mail, sem diferenciar maiúsculas e minúsculas."""

    def test_autentica_por_email_em_qualquer_caixa(self):
        self.assertEqual(authenticate(username="VENDEDOR@exemplo.com", password=SENHA), self.vendedor)
        self.assertEqual(authenticate(email="vendedor@exemplo.com", password=SENHA), self.vendedor)

    def test_senha_errada_e_email_desconhecido_nao_autenticam(self):
        self.assertIsNone(authenticate(username="vendedor@exemplo.com", password="outra"))
        self.assertIsNone(authenticate(username="ninguem@exemplo.com", password=SENHA))
        self.assertIsNone(authenticate(username="", password=SENHA))
        self.assertIsNone(authenticate(username="vendedor@exemplo.com", password=""))

    def test_login_por_nome_de_usuario_continua_funcionando(self):
        """O Admin tem a sua própria tela de login, por nome de usuário (ModelBackend)."""
        self.assertEqual(authenticate(username="vendedor", password=SENHA), self.vendedor)

    def test_usuario_inativo_nao_autentica(self):
        cria_usuario("afastado", "afastado@exemplo.com", is_active=False)

        self.assertIsNone(authenticate(username="afastado@exemplo.com", password=SENHA))

    def test_email_repetido_nao_autentica(self):
        cria_usuario("outro", "vendedor@exemplo.com")

        self.assertIsNone(authenticate(username="vendedor@exemplo.com", password=SENHA))


# ------------------------------------------------ HU02 Perfis e permissões (4.1.2)
class PerfisTests(BaseDeContas):
    """HU02: existem quatro perfis, cada um com as suas permissões."""

    def test_os_quatro_perfis_existem(self):
        self.assertEqual(
            sorted(Group.objects.values_list("name", flat=True)),
            sorted(PERFIS),
        )
        self.assertEqual(PERFIS, ("administrador", "vendedor", "estoquista", "cliente"))

    def test_administrador_tem_todas_as_permissoes_dos_modulos_entregues(self):
        self.assertEqual(
            self._codenames(PERFIL_ADMINISTRADOR, "produtos"),
            {
                "add_categoria", "change_categoria", "delete_categoria", "view_categoria",
                "add_produto", "change_produto", "delete_produto", "view_produto",
            },
        )
        self.assertEqual(
            self._codenames(PERFIL_ADMINISTRADOR, "estoque"),
            {
                "add_movimentoestoque", "change_movimentoestoque",
                "delete_movimentoestoque", "view_movimentoestoque",
            },
        )
        self.assertEqual(
            self._codenames(PERFIL_ADMINISTRADOR, "vendas"),
            {
                "add_venda", "change_venda", "delete_venda", "view_venda",
                "add_itemvenda", "change_itemvenda", "delete_itemvenda", "view_itemvenda",
            },
        )

    def test_vendedor_visualiza_produtos_e_vendas(self):
        self.assertEqual(self._codenames(PERFIL_VENDEDOR, "produtos"), {"view_categoria", "view_produto"})
        self.assertEqual(self._codenames(PERFIL_VENDEDOR, "vendas"), set())
        self.assertEqual(self._codenames(PERFIL_VENDEDOR, "estoque"), set())

    def test_estoquista_visualiza_produtos_e_registra_movimentos(self):
        self.assertEqual(self._codenames(PERFIL_ESTOQUISTA, "produtos"), {"view_categoria", "view_produto"})
        self.assertEqual(self._codenames(PERFIL_ESTOQUISTA, "estoque"), set())

    def test_cliente_nao_tem_permissao_no_admin(self):
        self.assertEqual(self._codenames(PERFIL_CLIENTE), set())

    def test_criar_perfis_pode_rodar_de_novo_sem_duplicar(self):
        antes = self._codenames(PERFIL_ADMINISTRADOR)

        criar_perfis()
        criar_perfis()

        self.assertEqual(Group.objects.filter(name__in=PERFIS).count(), 4)
        self.assertEqual(self._codenames(PERFIL_ADMINISTRADOR), antes)

    def test_comando_criar_perfis_mostra_o_resumo(self):
        saida = StringIO()

        call_command("criar_perfis", stdout=saida)
        resumo = saida.getvalue()

        for perfil in PERFIS:
            self.assertIn(perfil, resumo)
        self.assertIn("Perfis atualizados.", resumo)

    def test_perfil_do_usuario(self):
        self.assertEqual(perfil_do_usuario(self.administrador), PERFIL_ADMINISTRADOR)
        self.assertEqual(perfil_do_usuario(self.vendedor), PERFIL_VENDEDOR)
        self.assertEqual(perfil_do_usuario(self.estoquista), PERFIL_ESTOQUISTA)
        self.assertEqual(perfil_do_usuario(self.cliente), PERFIL_CLIENTE)
        self.assertIsNone(perfil_do_usuario(self.sem_perfil))
        self.assertIsNone(perfil_do_usuario(AnonymousUser()))
        self.assertIsNone(perfil_do_usuario(None))

    def test_superusuario_conta_como_administrador_mesmo_fora_do_grupo(self):
        self.assertFalse(self.administrador.groups.exists())
        self.assertEqual(perfil_do_usuario(self.administrador), PERFIL_ADMINISTRADOR)

    def _codenames(self, perfil, app_label=None):
        permissoes = Group.objects.get(name=perfil).permissions
        if app_label:
            permissoes = permissoes.filter(content_type__app_label=app_label)
        return set(permissoes.values_list("codename", flat=True))


class DestinoAposLoginTests(BaseDeContas):
    """HU01/HU02: cada perfil cai na sua página inicial depois de entrar."""

    def test_administrador_vai_para_o_admin(self):
        self.assertEqual(destino_apos_login(self.administrador), reverse("admin:index"))

        resposta = self.client.post(
            reverse("contas:entrar"),
            {"username": "gerente@exemplo.com", "password": SENHA},
        )

        self.assertRedirects(resposta, reverse("admin:index"))

    def test_cliente_vai_para_o_painel_provisorio(self):
        self.assertEqual(destino_apos_login(self.cliente), reverse("contas:painel"))

    def test_vendedor_vai_para_o_pdv(self):
        self.assertEqual(destino_apos_login(self.vendedor), reverse("vendas:pdv"))

        resposta = self.client.post(
            reverse("contas:entrar"),
            {"username": "vendedor@exemplo.com", "password": SENHA},
        )

        self.assertRedirects(resposta, reverse("vendas:pdv"))

    def test_estoquista_vai_para_o_painel_de_estoque(self):
        self.assertEqual(destino_apos_login(self.estoquista), reverse("estoque:painel"))

        resposta = self.client.post(
            reverse("contas:entrar"),
            {"username": "estoquista@exemplo.com", "password": SENHA},
        )

        self.assertRedirects(resposta, reverse("estoque:painel"))

    def test_usuario_sem_perfil_vai_para_o_painel(self):
        self.assertEqual(destino_apos_login(self.sem_perfil), reverse("contas:painel"))

    def test_administrador_fora_da_equipe_nao_e_mandado_para_o_admin(self):
        administrador = cria_usuario("coordenador", "coord@exemplo.com", PERFIL_ADMINISTRADOR)

        self.assertFalse(administrador.is_staff)
        self.assertEqual(destino_apos_login(administrador), reverse("contas:painel"))


class PermissoesNoAdminTests(BaseDeContas):
    """As permissões do grupo valem no Admin: o vendedor vê produtos, mas não cadastra."""

    def test_vendedor_ve_a_lista_de_produtos(self):
        self.client.force_login(self.vendedor)

        resposta = self.client.get(reverse("admin:produtos_produto_changelist"))

        self.assertEqual(resposta.status_code, 200)

    def test_vendedor_nao_pode_cadastrar_produto(self):
        self.client.force_login(self.vendedor)

        resposta = self.client.get(reverse("admin:produtos_produto_add"))

        self.assertEqual(resposta.status_code, 403)


# ------------------------------------------------ Decorator perfil_requerido (4.1.2)
@perfil_requerido(PERFIL_VENDEDOR)
def _area_do_vendedor(request):
    """View de mentira, só para testar o decorator; as telas reais vêm nos pacotes 4.3 a 4.5."""
    return HttpResponse("área do vendedor")


urlpatterns = [
    path("contas/", include("apps.contas.urls")),
    path("clientes/", include(("apps.clientes.urls", "clientes"), namespace="clientes")),
    path("area-do-vendedor/", _area_do_vendedor, name="area-do-vendedor"),
    path("", include("apps.core.urls")),
]


@override_settings(ROOT_URLCONF="apps.contas.tests")
class PerfilRequeridoTests(BaseDeContas):
    """HU02: uma página fora do perfil do usuário retorna 403."""

    def setUp(self):
        self.endereco = reverse("area-do-vendedor")

    def test_perfil_certo_entra(self):
        self.client.force_login(self.vendedor)

        resposta = self.client.get(self.endereco)

        self.assertEqual(resposta.status_code, 200)

    def test_outro_perfil_recebe_403(self):
        for usuario in (self.cliente, self.estoquista, self.administrador, self.sem_perfil):
            with self.subTest(usuario=usuario.username):
                self.client.force_login(usuario)

                resposta = self.client.get(self.endereco)

                self.assertEqual(resposta.status_code, 403)

    def test_visitante_vai_para_a_tela_de_entrada(self):
        resposta = self.client.get(self.endereco)

        self.assertRedirects(resposta, f"{reverse('contas:entrar')}?next={self.endereco}")
