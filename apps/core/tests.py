from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


class HealthCheckTests(TestCase):
    def test_responde_ok_quando_banco_esta_disponivel(self):
        resposta = self.client.get(reverse("core:health"))

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.json(), {"status": "ok", "banco_de_dados": "ok"})

    def test_responde_503_quando_banco_esta_indisponivel(self):
        with mock.patch("apps.core.views.banco_disponivel", return_value=False):
            resposta = self.client.get(reverse("core:health"))

        self.assertEqual(resposta.status_code, 503)
        self.assertEqual(resposta.json()["banco_de_dados"], "indisponível")


class HomeTests(TestCase):
    def test_pagina_inicial_redireciona_para_o_catalogo(self):
        resposta = self.client.get(reverse("core:home"))

        self.assertRedirects(resposta, reverse("loja:catalogo"))

    def test_pagina_inicial_redireciona_tambem_quem_entrou(self):
        usuario = User.objects.create_user("cliente", "cliente@exemplo.com", "senha-de-teste-123")
        self.client.force_login(usuario)

        resposta = self.client.get(reverse("core:home"))

        self.assertRedirects(resposta, reverse("loja:catalogo"))


class PaginasLegaisTests(TestCase):
    """Termos de Uso e Política de Privacidade, abertos pelo cadastro de cliente (HU14)."""

    def test_termos_e_privacidade_abrem_sem_login(self):
        for rota, template in (("core:termos", "core/termos.html"), ("core:privacidade", "core/privacidade.html")):
            resposta = self.client.get(reverse(rota))

            self.assertEqual(resposta.status_code, 200, rota)
            self.assertTemplateUsed(resposta, template)


class DadosDeDemonstracaoTests(TestCase):
    """Pacote 3.3: o comando popular_demonstracao prepara o banco para a apresentação."""

    def popular(self):
        from apps.core.demonstracao import popular

        return popular(senha="senha-de-teste-123", vendas_pdv=20, pedidos_online=4)

    def test_cria_um_usuario_de_cada_perfil(self):
        self.popular()

        for email, perfil in (
            ("admin@esportivo.demo", "administrador"),
            ("vendedor@esportivo.demo", "vendedor"),
            ("estoquista@esportivo.demo", "estoquista"),
            ("marina@esportivo.demo", "cliente"),
        ):
            usuario = User.objects.get(email=email)
            self.assertTrue(usuario.groups.filter(name=perfil).exists(), email)
        self.assertTrue(User.objects.get(email="admin@esportivo.demo").is_staff)

    def test_cria_vendas_nos_dois_canais_com_cancelamentos(self):
        from apps.vendas.models import CanalDeVenda, StatusDeVenda, Venda

        resumo = self.popular()

        self.assertEqual(Venda.objects.filter(canal=CanalDeVenda.LOJA_FISICA).count(), 20)
        self.assertEqual(Venda.objects.filter(canal=CanalDeVenda.ONLINE).count(), 4)
        self.assertEqual(Venda.objects.filter(status=StatusDeVenda.CANCELADA).count(), resumo.canceladas)
        self.assertTrue(Venda.objects.filter(status=StatusDeVenda.RETIRADA).exists())

    def test_vendas_ficam_nos_ultimos_30_dias(self):
        from datetime import timedelta

        from django.utils import timezone

        from apps.vendas.models import Venda

        self.popular()
        agora = timezone.now()

        self.assertFalse(Venda.objects.filter(criado_em__gt=agora).exists())
        self.assertFalse(Venda.objects.filter(criado_em__lt=agora - timedelta(days=31)).exists())

    def test_estoque_bate_com_os_movimentos_e_mantem_produtos_em_alerta(self):
        from apps.estoque.services import produtos_em_alerta
        from apps.produtos.models import Produto

        self.popular()

        for produto in Produto.objects.all():
            ultimo = produto.movimentos.order_by("-id").first()
            self.assertEqual(produto.estoque_atual, ultimo.saldo_apos if ultimo else produto.estoque_atual)
        self.assertFalse(Produto.objects.filter(estoque_atual__lt=0).exists())
        self.assertTrue(produtos_em_alerta().exists())

    def test_historico_de_estoque_fica_em_ordem_cronologica(self):
        from apps.produtos.models import Produto

        self.popular()

        for produto in Produto.objects.all():
            por_data = list(produto.movimentos.order_by("criado_em", "id").values_list("id", flat=True))
            por_ordem_real = list(produto.movimentos.order_by("id").values_list("id", flat=True))
            self.assertEqual(por_data, por_ordem_real, produto.nome)

    def test_canais_ficam_intercalados_no_periodo(self):
        from apps.vendas.models import CanalDeVenda, Venda

        self.popular()
        numeros_online = Venda.objects.filter(canal=CanalDeVenda.ONLINE).values_list("numero", flat=True)
        numeros_pdv = Venda.objects.filter(canal=CanalDeVenda.LOJA_FISICA).values_list("numero", flat=True)

        # Algum pedido online acontece antes da última venda do PDV: um canal não vem todo depois do outro.
        self.assertLess(min(numeros_online), max(numeros_pdv))

    def test_senha_fraca_e_recusada_antes_de_gravar(self):
        from apps.core.demonstracao import ErroDeDemonstracao, popular
        from apps.vendas.models import Venda

        with self.assertRaises(ErroDeDemonstracao):
            popular(senha="123")

        self.assertFalse(Venda.objects.exists())
        self.assertFalse(User.objects.exists())

    def test_nao_roda_em_banco_com_vendas(self):
        from apps.core.demonstracao import ErroDeDemonstracao

        self.popular()

        with self.assertRaises(ErroDeDemonstracao):
            self.popular()

    def test_comando_mostra_os_acessos(self):
        from io import StringIO

        from django.core.management import CommandError, call_command

        saida = StringIO()
        call_command("popular_demonstracao", "--senha", "senha-de-teste-123", stdout=saida)

        self.assertIn("admin@esportivo.demo", saida.getvalue())
        with self.assertRaises(CommandError):
            call_command("popular_demonstracao", stdout=StringIO())
