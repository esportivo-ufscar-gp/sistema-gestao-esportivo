import inspect
import json
import os
import re
import secrets
from datetime import timedelta
from io import StringIO
from pathlib import Path
from unittest import mock

from django.apps import apps
from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.core.management import CommandError, call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.clientes.models import Cliente
from apps.estoque.models import MovimentoEstoque, TipoDeMovimento
from apps.estoque.services import produtos_em_alerta
from apps.produtos.models import Produto
from apps.vendas.models import CanalDeVenda, StatusDeVenda, Venda

from .demonstracao import ErroDeDemonstracao, popular, saldo_pelos_movimentos


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

    SENHA = "senha-de-teste-123"

    def popular(self, senha=SENHA):
        return popular(senha=senha, vendas_pdv=20, pedidos_online=4)

    def comando(self, *argumentos, ambiente=None):
        """Roda o comando com DEMO_SENHA só se `ambiente` a trouxer; devolve a saída."""
        saida = StringIO()
        with mock.patch.dict(os.environ, ambiente or {}):
            if not ambiente:
                os.environ.pop("DEMO_SENHA", None)
            call_command("popular_demonstracao", *argumentos, stdout=saida)
        return saida.getvalue()

    def entra(self, email, senha):
        return authenticate(username=email, password=senha) is not None

    def nada_foi_gravado(self, usuarios=0):
        self.assertFalse(Venda.objects.exists())
        self.assertFalse(Produto.objects.exists())
        self.assertFalse(MovimentoEstoque.objects.exists())
        self.assertEqual(User.objects.count(), usuarios)

    # -------------------------------------------------------------- usuários e perfis
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

    def test_equipe_entra_no_admin_e_cliente_nao(self):
        self.popular()

        for email in ("admin@esportivo.demo", "vendedor@esportivo.demo", "estoquista@esportivo.demo"):
            self.assertTrue(User.objects.get(email=email).is_staff, email)
        self.assertFalse(User.objects.get(email="marina@esportivo.demo").is_staff)

    def test_vendedor_e_estoquista_abrem_no_admin_o_que_o_perfil_permite(self):
        self.popular()

        self.client.force_login(User.objects.get(email="vendedor@esportivo.demo"))
        self.assertEqual(self.client.get(reverse("admin:vendas_venda_changelist")).status_code, 200)
        self.client.force_login(User.objects.get(email="estoquista@esportivo.demo"))
        self.assertEqual(self.client.get(reverse("admin:estoque_movimentoestoque_changelist")).status_code, 200)
        self.assertEqual(self.client.get(reverse("admin:vendas_venda_changelist")).status_code, 403)

    def test_recusa_quando_um_email_da_demonstracao_ja_existe(self):
        User.objects.create_user("gerente", "ADMIN@esportivo.demo", "Outra-Senha-Forte-1")

        with self.assertRaisesMessage(ErroDeDemonstracao, "admin@esportivo.demo"):
            self.popular()

        self.nada_foi_gravado(usuarios=1)
        self.assertFalse(User.objects.get(username="gerente").groups.exists())

    def test_recusa_quando_um_cliente_ou_nome_de_usuario_ja_existe(self):
        Cliente.objects.create(nome="Marina", email="marina@esportivo.demo", telefone="1",
                               consentimento_em=timezone.now())
        User.objects.create_user("ana", "ana@outro.com", "Outra-Senha-Forte-1")

        with self.assertRaises(ErroDeDemonstracao) as erro:
            self.popular()

        self.assertIn("marina@esportivo.demo", str(erro.exception))
        self.assertIn("ana", str(erro.exception))
        self.assertIn("não reaproveita contas existentes", str(erro.exception))
        self.nada_foi_gravado(usuarios=1)

    # -------------------------------------------------------------- senha
    def test_nenhuma_senha_fixa_no_codigo(self):
        from apps.core import demonstracao
        from apps.core.management.commands import popular_demonstracao

        self.assertIs(inspect.signature(popular).parameters["senha"].default, inspect.Parameter.empty)
        self.assertFalse(hasattr(demonstracao, "SENHA_PADRAO"))
        parser = popular_demonstracao.Command().create_parser("manage.py", "popular_demonstracao")
        self.assertIsNone(parser.get_default("senha"))
        for caminho in (demonstracao.__file__, popular_demonstracao.__file__, settings.BASE_DIR / "README.md"):
            texto = Path(caminho).read_text(encoding="utf-8")
            self.assertNotIn("demo-esportivo-2026", texto, caminho)
            self.assertIsNone(re.search(r"\bSENHA\w*\s*=\s*[\"']", texto), caminho)  # nenhuma constante de senha

    def test_sem_senha_informada_gera_uma_aleatoria_e_mostra_uma_vez(self):
        with mock.patch(
            "apps.core.management.commands.popular_demonstracao.secrets.token_urlsafe",
            wraps=secrets.token_urlsafe,
        ) as gerador:
            saida = self.comando()

        gerador.assert_called_once()
        senha = re.search(r"Senha gerada.*: (\S+)$", saida, re.MULTILINE).group(1)
        self.assertGreaterEqual(len(senha), 16)
        self.assertEqual(saida.count(senha), 1)
        self.assertTrue(self.entra("admin@esportivo.demo", senha))
        self.assertTrue(self.entra("marina@esportivo.demo", senha))

    def test_senha_de_demo_senha(self):
        saida = self.comando(ambiente={"DEMO_SENHA": "Senha-Do-Ambiente-42"})

        self.assertTrue(self.entra("admin@esportivo.demo", "Senha-Do-Ambiente-42"))
        self.assertIn("informada em DEMO_SENHA", saida)
        self.assertNotIn("Senha-Do-Ambiente-42", saida)
        self.assertNotIn("Senha gerada", saida)

    def test_senha_de_parametro_vale_mais_que_demo_senha(self):
        saida = self.comando("--senha", "Senha-Do-Parametro-42", ambiente={"DEMO_SENHA": "Senha-Do-Ambiente-42"})

        self.assertTrue(self.entra("vendedor@esportivo.demo", "Senha-Do-Parametro-42"))
        self.assertFalse(self.entra("vendedor@esportivo.demo", "Senha-Do-Ambiente-42"))
        self.assertIn("informada em --senha", saida)
        self.assertNotIn("Senha-Do-Parametro-42", saida)

    def test_senha_fraca_e_recusada_antes_de_gravar(self):
        with self.assertRaisesMessage(ErroDeDemonstracao, "Senha fraca"):
            popular(senha="123")
        self.nada_foi_gravado()

        for argumentos, ambiente in ((("--senha", "12345678"), None), ((), {"DEMO_SENHA": "password"})):
            with self.subTest(argumentos=argumentos, ambiente=ambiente):
                with self.assertRaisesMessage(CommandError, "Senha fraca"):
                    self.comando(*argumentos, ambiente=ambiente)
                self.nada_foi_gravado()

    # -------------------------------------------------------------- estoque
    def test_saldo_inicial_entra_pelo_servico_de_estoque(self):
        self.popular()

        caminho = Path(apps.get_app_config("produtos").path) / "fixtures" / "dados_exemplo.json"
        da_fixture = {
            registro["pk"]: registro["fields"]["estoque_atual"]
            for registro in json.loads(caminho.read_text(encoding="utf-8"))
            if registro["model"] == "produtos.produto" and registro["fields"]["estoque_atual"] > 0
        }
        entradas = MovimentoEstoque.objects.filter(tipo=TipoDeMovimento.ENTRADA, motivo="Saldo inicial")

        self.assertEqual(dict(entradas.values_list("produto", "quantidade")), da_fixture)
        primeira_venda = Venda.objects.order_by("criado_em").first().criado_em
        self.assertTrue(all(entrada.criado_em < primeira_venda for entrada in entradas))

    def test_soma_dos_movimentos_e_igual_ao_saldo_de_cada_produto(self):
        self.popular()

        for produto in Produto.objects.all():
            entradas = sum(
                movimento.quantidade for movimento in produto.movimentos.all()
                if movimento.tipo in (TipoDeMovimento.ENTRADA, TipoDeMovimento.ESTORNO)
            )
            saidas = sum(
                movimento.quantidade for movimento in produto.movimentos.all()
                if movimento.tipo in (TipoDeMovimento.SAIDA_VENDA, TipoDeMovimento.AJUSTE)
            )
            self.assertEqual(entradas - saidas, produto.estoque_atual, produto.nome)
            self.assertEqual(saldo_pelos_movimentos(produto), produto.estoque_atual, produto.nome)
        self.assertFalse(Produto.objects.filter(estoque_atual__lt=0).exists())
        self.assertTrue(produtos_em_alerta().exists())

    def test_novo_produto_depois_da_carga_recebe_um_id_novo(self):
        self.popular()

        categoria = Produto.objects.first().categoria
        novo = Produto.objects.create(codigo="999999", nome="Produto novo", categoria=categoria, preco="10.00")

        self.assertGreater(novo.pk, max(Produto.objects.exclude(pk=novo.pk).values_list("pk", flat=True)))

    def test_recusa_catalogo_com_saldo_sem_historico(self):
        call_command("loaddata", "dados_exemplo", verbosity=0)

        with self.assertRaisesMessage(ErroDeDemonstracao, "saldo sem movimento de estoque"):
            self.popular()

        self.assertFalse(Venda.objects.exists())
        self.assertFalse(MovimentoEstoque.objects.exists())
        self.assertFalse(User.objects.exists())

    def test_historico_de_estoque_fica_em_ordem_cronologica(self):
        self.popular()

        for produto in Produto.objects.all():
            por_data = list(produto.movimentos.order_by("criado_em", "id").values_list("id", flat=True))
            por_ordem_real = list(produto.movimentos.order_by("id").values_list("id", flat=True))
            self.assertEqual(por_data, por_ordem_real, produto.nome)

    # -------------------------------------------------------------- vendas
    def test_cria_vendas_nos_dois_canais_com_cancelamentos(self):
        resumo = self.popular()

        self.assertEqual(Venda.objects.filter(canal=CanalDeVenda.LOJA_FISICA).count(), 20)
        self.assertEqual(Venda.objects.filter(canal=CanalDeVenda.ONLINE).count(), 4)
        self.assertEqual(Venda.objects.filter(status=StatusDeVenda.CANCELADA).count(), resumo.canceladas)
        self.assertTrue(Venda.objects.filter(status=StatusDeVenda.RETIRADA).exists())

    def test_vendas_ficam_nos_ultimos_30_dias(self):
        self.popular()
        agora = timezone.now()

        self.assertFalse(Venda.objects.filter(criado_em__gt=agora).exists())
        self.assertFalse(Venda.objects.filter(criado_em__lt=agora - timedelta(days=31)).exists())

    def test_canais_ficam_intercalados_no_periodo(self):
        self.popular()
        numeros_online = Venda.objects.filter(canal=CanalDeVenda.ONLINE).values_list("numero", flat=True)
        numeros_pdv = Venda.objects.filter(canal=CanalDeVenda.LOJA_FISICA).values_list("numero", flat=True)

        # Algum pedido online acontece antes da última venda do PDV: um canal não vem todo depois do outro.
        self.assertLess(min(numeros_online), max(numeros_pdv))

    def test_nao_roda_em_banco_com_vendas(self):
        self.popular()

        with self.assertRaisesMessage(ErroDeDemonstracao, "já tem vendas"):
            self.popular()

    def test_comando_mostra_os_acessos_e_recusa_rodar_de_novo(self):
        saida = self.comando("--senha", self.SENHA)

        for email in ("admin@esportivo.demo", "vendedor@esportivo.demo", "estoquista@esportivo.demo",
                      "marina@esportivo.demo"):
            self.assertIn(email, saida)
        with self.assertRaises(CommandError):
            self.comando("--senha", self.SENHA)
