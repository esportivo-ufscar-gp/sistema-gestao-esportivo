import inspect
import json
import os
import re
import secrets
import tempfile
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest import mock

from django.apps import apps
from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from apps.clientes.models import Cliente
from config.ambiente import banco_da_url, banco_de_dados, enderecos_publicos, env_bool, env_list
from apps.estoque.models import MovimentoEstoque, TipoDeMovimento
from apps.estoque.services import produtos_em_alerta
from apps.produtos.models import Categoria, FotoDoProduto, Produto
from apps.vendas.models import CanalDeVenda, StatusDeVenda, Venda

from .demonstracao import (
    NOME_DA_FOTO_EXTRA,
    PASTA_DAS_IMAGENS,
    ErroDeDemonstracao,
    carregar_imagens,
    popular,
    saldo_pelos_movimentos,
)


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

    def test_se_vazio_carrega_no_primeiro_deploy_e_nao_faz_nada_nos_seguintes(self):
        primeira = self.comando("--se-vazio", ambiente={"DEMO_SENHA": "Senha-Do-Ambiente-42"})
        vendas = Venda.objects.count()
        usuarios = User.objects.count()

        segunda = self.comando("--se-vazio", ambiente={"DEMO_SENHA": "Outra-Senha-Forte-77"})

        self.assertIn("Dados de demonstração carregados.", primeira)
        self.assertIn("não foram carregados de novo", segunda)
        self.assertEqual(Venda.objects.count(), vendas)
        self.assertEqual(User.objects.count(), usuarios)
        self.assertTrue(self.entra("admin@esportivo.demo", "Senha-Do-Ambiente-42"))

    def test_se_vazio_nao_esconde_os_outros_erros(self):
        with self.assertRaisesMessage(CommandError, "Senha fraca"):
            self.comando("--se-vazio", "--senha", "12345678")
        self.nada_foi_gravado()


# ------------------------------------------------------------------ Hospedagem (pacote 3.3)
class ConfiguracaoDoAmbienteTests(SimpleTestCase):
    """config/ambiente.py: o que o settings lê das variáveis de ambiente, no Render e no .env."""

    def test_database_url_do_render_vira_a_configuracao_do_django(self):
        banco = banco_da_url("postgresql://esportivo:s%40nha%2F1@dpg-abc123-a:5432/esportivo?sslmode=require")

        self.assertEqual(banco, {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": "esportivo",
            "USER": "esportivo",
            "PASSWORD": "s@nha/1",
            "HOST": "dpg-abc123-a",
            "PORT": "5432",
            "OPTIONS": {"sslmode": "require"},
        })

    def test_database_url_sem_porta_nem_opcoes(self):
        banco = banco_da_url("postgres://usuario:senha@host.exemplo/banco")

        self.assertEqual(banco["PORT"], "5432")
        self.assertEqual(banco["HOST"], "host.exemplo")
        self.assertNotIn("OPTIONS", banco)

    def test_database_url_que_nao_e_postgresql_e_recusada(self):
        with self.assertRaisesMessage(ValueError, "PostgreSQL"):
            banco_da_url("mysql://usuario:senha@host/banco")

    def test_database_url_vale_mais_que_as_variaveis_db(self):
        ambiente = {"DATABASE_URL": "postgresql://u:s@render-db/demo", "DB_ENGINE": "sqlite", "DB_HOST": "localhost"}

        banco = banco_de_dados(Path("/projeto"), ambiente)

        self.assertEqual((banco["HOST"], banco["NAME"]), ("render-db", "demo"))

    def test_sem_database_url_continuam_valendo_o_sqlite_e_as_variaveis_db(self):
        sqlite = banco_de_dados(Path("/projeto"), {"DB_ENGINE": "sqlite"})
        postgres = banco_de_dados(Path("/projeto"), {"DB_NAME": "loja", "DB_HOST": "servidor", "DB_PORT": "6543"})

        self.assertEqual(sqlite["ENGINE"], "django.db.backends.sqlite3")
        self.assertEqual(sqlite["NAME"], Path("/projeto") / "db.sqlite3")
        self.assertEqual(
            (postgres["ENGINE"], postgres["NAME"], postgres["HOST"], postgres["PORT"]),
            ("django.db.backends.postgresql", "loja", "servidor", "6543"),
        )

    def test_endereco_do_render_entra_em_hosts_e_origens(self):
        hosts, origens = enderecos_publicos({
            "DJANGO_ALLOWED_HOSTS": "localhost",
            "RENDER_EXTERNAL_HOSTNAME": "esportivo-ufscar.onrender.com",
            "RENDER_EXTERNAL_URL": "https://esportivo-ufscar.onrender.com",
        })

        self.assertEqual(hosts, ["localhost", "esportivo-ufscar.onrender.com"])
        self.assertEqual(origens, ["https://esportivo-ufscar.onrender.com"])

    def test_origem_vem_do_host_quando_falta_a_url_e_nada_se_repete(self):
        hosts, origens = enderecos_publicos({
            "DJANGO_ALLOWED_HOSTS": "app.onrender.com",
            "DJANGO_CSRF_TRUSTED_ORIGINS": "https://app.onrender.com",
            "RENDER_EXTERNAL_HOSTNAME": "app.onrender.com",
        })

        self.assertEqual(hosts, ["app.onrender.com"])
        self.assertEqual(origens, ["https://app.onrender.com"])

    def test_fora_do_render_valem_so_as_variaveis_do_env(self):
        self.assertEqual(enderecos_publicos({}), (["localhost", "127.0.0.1"], []))

    def test_env_bool_e_env_list(self):
        self.assertTrue(env_bool("X", ambiente={"X": "Sim"}))
        self.assertTrue(env_bool("RENDER", ambiente={"RENDER": "true"}))
        self.assertFalse(env_bool("X", ambiente={}))
        self.assertEqual(env_list("X", ambiente={"X": " a, ,b "}), ["a", "b"])

    def test_whitenoise_serve_os_arquivos_estaticos(self):
        self.assertEqual(settings.MIDDLEWARE[1], "whitenoise.middleware.WhiteNoiseMiddleware")
        self.assertEqual(settings.MIDDLEWARE[0], "django.middleware.security.SecurityMiddleware")
        self.assertEqual(
            settings.STORAGES["staticfiles"]["BACKEND"], "whitenoise.storage.CompressedStaticFilesStorage"
        )


class ArquivosDeDeployTests(SimpleTestCase):
    """render.yaml e build.sh: o que o deploy do Render precisa encontrar no repositório."""

    def ler(self, nome):
        return (settings.BASE_DIR / nome).read_text(encoding="utf-8")

    def test_build_roda_as_etapas_na_ordem(self):
        build = self.ler("build.sh")
        etapas = [
            "pip install -r requirements.txt",
            "collectstatic --no-input",
            "migrate --no-input",
            "criar_perfis",
            "popular_demonstracao --se-vazio",
            "carregar_imagens_demonstracao",
        ]

        posicoes = [build.index(etapa) for etapa in etapas]
        self.assertEqual(posicoes, sorted(posicoes))
        self.assertIn("set -o errexit", build)
        self.assertNotIn("\r", (settings.BASE_DIR / "build.sh").read_bytes().decode("utf-8"))

    def test_blueprint_usa_os_planos_gratuitos_sem_segredos_no_arquivo(self):
        blueprint = self.ler("render.yaml")

        self.assertEqual(blueprint.count("plan: free"), 2)
        self.assertIn("property: connectionString", blueprint)
        self.assertIn("startCommand: gunicorn config.wsgi:application", blueprint)
        self.assertIn("buildCommand: bash build.sh", blueprint)
        self.assertRegex(blueprint, r"key: DJANGO_SECRET_KEY\s+generateValue: true")
        self.assertRegex(blueprint, r"key: DEMO_SENHA\s+sync: false")
        self.assertNotRegex(blueprint, r"key: DEMO_SENHA\s+value:")

    def test_dependencias_de_producao(self):
        requisitos = self.ler("requirements.txt")

        self.assertIn("gunicorn", requisitos)
        self.assertIn("whitenoise", requisitos)


def _jpeg(caminho, cor="red"):
    Image.new("RGB", (16, 10), cor).save(caminho, "JPEG")


def _usa_media_temporaria(teste):
    """Troca a MEDIA_ROOT por uma pasta temporária, apagada no fim do teste."""
    pasta = tempfile.TemporaryDirectory()
    teste.addCleanup(pasta.cleanup)
    configuracao = override_settings(MEDIA_ROOT=pasta.name)
    configuracao.enable()
    teste.addCleanup(configuracao.disable)
    return Path(pasta.name)


COMANDO_DAS_IMAGENS = "apps.core.management.commands.carregar_imagens_demonstracao.carregar_imagens"


class ImagensDaDemonstracaoTests(TestCase):
    """Pacote 3.3: as fotos versionadas são ligadas aos produtos pelo código, a cada deploy."""

    def setUp(self):
        self.media = _usa_media_temporaria(self)

        origem = tempfile.TemporaryDirectory()
        self.addCleanup(origem.cleanup)
        self.pasta = Path(origem.name)
        _jpeg(self.pasta / "100110.jpg", "red")
        _jpeg(self.pasta / "100231.jpg", "blue")
        _jpeg(self.pasta / "999999.jpg", "green")

        categoria = Categoria.objects.create(nome="Corrida")
        self.tenis = Produto.objects.create(
            codigo="100110", nome="Tênis", preco=Decimal("10.00"), categoria=categoria
        )
        self.camisa = Produto.objects.create(
            codigo="100231", nome="Camisa", preco=Decimal("5.00"), categoria=categoria
        )

    def arquivos_gravados(self):
        return sorted(p.name for p in (self.media / "produtos").iterdir())

    def troca_a_foto_do_tenis_pelo_admin(self):
        (self.media / "produtos").mkdir()
        _jpeg(self.media / "produtos" / "minha_foto.jpg")
        Produto.objects.filter(pk=self.tenis.pk).update(imagem="produtos/minha_foto.jpg")

    def roda_o_comando(self):
        saida = StringIO()
        with mock.patch(COMANDO_DAS_IMAGENS, side_effect=lambda: carregar_imagens(self.pasta)):
            call_command("carregar_imagens_demonstracao", stdout=saida)
        return saida.getvalue()

    def test_liga_cada_foto_ao_produto_do_mesmo_codigo(self):
        resultado = carregar_imagens(self.pasta)

        self.tenis.refresh_from_db()
        self.camisa.refresh_from_db()
        self.assertEqual(self.tenis.imagem.name, "produtos/100110.jpg")
        self.assertEqual(self.camisa.imagem.name, "produtos/100231.jpg")
        self.assertEqual(
            (self.media / "produtos" / "100110.jpg").read_bytes(),
            (self.pasta / "100110.jpg").read_bytes(),
        )
        self.assertEqual(resultado.ligadas, ["100110", "100231"])

    def test_foto_sem_produto_e_ignorada(self):
        resultado = carregar_imagens(self.pasta)

        self.assertEqual(resultado.sem_produto, ["999999"])
        self.assertNotIn("999999.jpg", self.arquivos_gravados())

    def test_rodar_de_novo_nao_cria_copias(self):
        carregar_imagens(self.pasta)
        carregar_imagens(self.pasta)

        self.tenis.refresh_from_db()
        self.assertEqual(self.tenis.imagem.name, "produtos/100110.jpg")
        self.assertEqual(self.arquivos_gravados(), ["100110.jpg", "100231.jpg"])

    def test_disco_recriado_recebe_os_arquivos_de_novo(self):
        carregar_imagens(self.pasta)
        (self.media / "produtos" / "100110.jpg").unlink()

        carregar_imagens(self.pasta)

        self.assertIn("100110.jpg", self.arquivos_gravados())

    def test_mantem_foto_trocada_pelo_admin_enquanto_o_arquivo_existe(self):
        self.troca_a_foto_do_tenis_pelo_admin()

        resultado = carregar_imagens(self.pasta)

        self.tenis.refresh_from_db()
        self.assertEqual(self.tenis.imagem.name, "produtos/minha_foto.jpg")
        self.assertEqual(resultado.mantidas, ["100110"])

    def test_foto_do_admin_cujo_arquivo_sumiu_volta_para_a_da_pasta(self):
        Produto.objects.filter(pk=self.tenis.pk).update(imagem="produtos/sumiu.jpg")

        carregar_imagens(self.pasta)

        self.tenis.refresh_from_db()
        self.assertEqual(self.tenis.imagem.name, "produtos/100110.jpg")

    def test_nao_mexe_no_estoque(self):
        movimentos = MovimentoEstoque.objects.count()

        carregar_imagens(self.pasta)

        self.tenis.refresh_from_db()
        self.assertEqual(self.tenis.estoque_atual, 0)
        self.assertEqual(MovimentoEstoque.objects.count(), movimentos)

    def test_comando_mostra_o_resumo(self):
        saida = self.roda_o_comando()

        self.assertIn("Fotos ligadas aos produtos: 2.", saida)
        self.assertIn("Fotos sem produto com o mesmo código: 999999.", saida)

    def test_comando_avisa_as_fotos_mantidas(self):
        self.troca_a_foto_do_tenis_pelo_admin()

        saida = self.roda_o_comando()

        self.assertIn("Mantidas as fotos trocadas pelo Admin: 100110.", saida)

    def test_catalogo_mostra_a_foto(self):
        carregar_imagens(self.pasta)

        resposta = self.client.get(reverse("loja:catalogo"))

        self.assertContains(resposta, 'src="/media/produtos/100110.jpg"')


class FotosExtrasDaDemonstracaoTests(TestCase):
    """Pacote 3.3: <código>-N.jpg vira foto extra de ordem N - 1, sem duplicar a cada deploy."""

    def setUp(self):
        self.media = _usa_media_temporaria(self)

        origem = tempfile.TemporaryDirectory()
        self.addCleanup(origem.cleanup)
        self.pasta = Path(origem.name)
        for nome in ("100110.jpg", "100110-2.jpg", "100110-3.jpg", "100110-1.jpg", "999999-2.jpg", "E2E-01.jpg"):
            _jpeg(self.pasta / nome)

        categoria = Categoria.objects.create(nome="Corrida")
        self.tenis = Produto.objects.create(
            codigo="100110", nome="Tênis", preco=Decimal("10.00"), categoria=categoria
        )
        self.bola = Produto.objects.create(
            codigo="E2E-01", nome="Bola E2E", preco=Decimal("50.00"), categoria=categoria
        )

    def fotos_do_tenis(self):
        return list(self.tenis.fotos.values_list("imagem", "ordem"))

    def test_liga_as_extras_na_ordem_do_numero_do_arquivo(self):
        resultado = carregar_imagens(self.pasta)

        self.assertEqual(self.fotos_do_tenis(), [("produtos/100110-2.jpg", 1), ("produtos/100110-3.jpg", 2)])
        self.assertEqual(resultado.extras, ["100110-2", "100110-3"])
        self.assertEqual(
            (self.media / "produtos" / "100110-2.jpg").read_bytes(),
            (self.pasta / "100110-2.jpg").read_bytes(),
        )

    def test_rodar_de_novo_nao_duplica_as_extras_nem_os_arquivos(self):
        carregar_imagens(self.pasta)
        carregar_imagens(self.pasta)

        self.assertEqual(FotoDoProduto.objects.count(), 2)
        self.assertEqual(self.fotos_do_tenis(), [("produtos/100110-2.jpg", 1), ("produtos/100110-3.jpg", 2)])
        self.assertEqual(
            sorted(p.name for p in (self.media / "produtos").iterdir()),
            ["100110-2.jpg", "100110-3.jpg", "100110.jpg", "E2E-01.jpg"],
        )

    def test_disco_recriado_recebe_as_extras_de_novo_sem_duplicar(self):
        carregar_imagens(self.pasta)
        (self.media / "produtos" / "100110-2.jpg").unlink()

        carregar_imagens(self.pasta)

        self.assertTrue((self.media / "produtos" / "100110-2.jpg").exists())
        self.assertEqual(FotoDoProduto.objects.count(), 2)

    def test_codigo_com_hifen_e_foto_principal_e_nao_extra(self):
        carregar_imagens(self.pasta)

        self.bola.refresh_from_db()
        self.assertEqual(self.bola.imagem.name, "produtos/E2E-01.jpg")
        self.assertFalse(self.bola.fotos.exists())

    def test_extra_sem_produto_ou_com_numero_1_e_ignorada(self):
        resultado = carregar_imagens(self.pasta)

        self.assertEqual(resultado.sem_produto, ["100110-1", "999999-2"])
        self.assertFalse(FotoDoProduto.objects.filter(imagem="produtos/100110-1.jpg").exists())

    def test_nao_mexe_nas_extras_cadastradas_pelo_admin(self):
        do_admin = FotoDoProduto.objects.create(produto=self.tenis, imagem="produtos/minha.jpg", ordem=5)

        carregar_imagens(self.pasta)

        do_admin.refresh_from_db()
        self.assertEqual(do_admin.ordem, 5)
        self.assertEqual(self.tenis.fotos.count(), 3)

    def test_comando_mostra_quantas_extras_ligou(self):
        saida = StringIO()
        with mock.patch(COMANDO_DAS_IMAGENS, side_effect=lambda: carregar_imagens(self.pasta)):
            call_command("carregar_imagens_demonstracao", stdout=saida)

        self.assertIn("Fotos ligadas aos produtos: 2.", saida.getvalue())
        self.assertIn("Fotos extras ligadas: 2.", saida.getvalue())

    def test_catalogo_entrega_as_extras(self):
        carregar_imagens(self.pasta)

        resposta = self.client.get(reverse("loja:catalogo"))

        self.assertContains(resposta, 'src="/media/produtos/100110-2.jpg"')
        self.assertContains(resposta, 'src="/media/produtos/100110-3.jpg"')


class PastaDeImagensTests(SimpleTestCase):
    """As fotos versionadas: uma principal por produto, extras numeradas, quadradas, leves e com crédito."""

    def codigos_da_fixture(self):
        caminho = Path(apps.get_app_config("produtos").path) / "fixtures" / "dados_exemplo.json"
        registros = json.loads(caminho.read_text(encoding="utf-8"))
        return sorted(r["fields"]["codigo"] for r in registros if r["model"] == "produtos.produto")

    def nomes_das_fotos(self):
        return sorted(p.stem for p in PASTA_DAS_IMAGENS.glob("*.jpg"))

    def test_uma_foto_principal_por_produto_do_catalogo(self):
        principais = [nome for nome in self.nomes_das_fotos() if not NOME_DA_FOTO_EXTRA.match(nome)]

        self.assertEqual(principais, self.codigos_da_fixture())

    def test_fotos_extras_sao_de_produtos_do_catalogo_numeradas_a_partir_de_2(self):
        codigos = self.codigos_da_fixture()
        extras = [NOME_DA_FOTO_EXTRA.match(nome) for nome in self.nomes_das_fotos()]

        for extra in filter(None, extras):
            with self.subTest(foto=extra.string):
                self.assertIn(extra["codigo"], codigos)
                self.assertGreaterEqual(int(extra["numero"]), 2)

    def test_fotos_sao_jpeg_quadrados_de_1200_e_leves(self):
        for foto in PASTA_DAS_IMAGENS.glob("*.jpg"):
            with self.subTest(foto=foto.name), Image.open(foto) as imagem:
                self.assertEqual(imagem.format, "JPEG")
                self.assertEqual(imagem.size, (1200, 1200))
                self.assertLess(foto.stat().st_size, 200 * 1024)

    def test_creditos_registram_autor_e_origem_de_cada_foto(self):
        creditos = (PASTA_DAS_IMAGENS / "CREDITOS.md").read_text(encoding="utf-8")

        for nome in self.nomes_das_fotos():
            with self.subTest(foto=nome):
                self.assertRegex(
                    creditos,
                    rf"\| {re.escape(nome)}\.jpg \| [^|]+ \| "
                    r"https://(unsplash\.com/photos/|www\.pexels\.com/photo/)[\w-]+/? \| Licença",
                )


class MediaTests(TestCase):
    """As fotos dos produtos só são servidas em desenvolvimento ou no ambiente de demonstração."""

    def setUp(self):
        media = _usa_media_temporaria(self)
        (media / "produtos").mkdir()
        _jpeg(media / "produtos" / "100110.jpg")

    def baixa(self, url):
        # A resposta deixa o arquivo aberto; no Windows, a pasta temporária só é apagada depois.
        resposta = self.client.get(url)
        self.addCleanup(resposta.close)
        return resposta

    @override_settings(DEBUG=False, SERVIR_MEDIA=True)
    def test_ambiente_de_demonstracao_serve_as_fotos(self):
        resposta = self.baixa("/media/produtos/100110.jpg")

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta["Content-Type"], "image/jpeg")

    @override_settings(DEBUG=True, SERVIR_MEDIA=False)
    def test_desenvolvimento_serve_as_fotos(self):
        self.assertEqual(self.baixa("/media/produtos/100110.jpg").status_code, 200)

    @override_settings(DEBUG=False, SERVIR_MEDIA=False)
    def test_sem_debug_nem_servir_media_responde_404(self):
        self.assertEqual(self.client.get("/media/produtos/100110.jpg").status_code, 404)

    @override_settings(DEBUG=False, SERVIR_MEDIA=True)
    def test_arquivo_inexistente_responde_404(self):
        self.assertEqual(self.client.get("/media/produtos/nao_existe.jpg").status_code, 404)

    @override_settings(DEBUG=False, SERVIR_MEDIA=True)
    def test_nao_sai_da_pasta_media(self):
        resposta = self.client.get("/media/..%2F..%2Fmanage.py")

        self.assertIn(resposta.status_code, (400, 404))

    def test_servir_media_liga_sozinho_no_render(self):
        configuracao = (settings.BASE_DIR / "config" / "settings.py").read_text(encoding="utf-8")

        self.assertIn('SERVIR_MEDIA = env_bool("DJANGO_SERVIR_MEDIA", env_bool("RENDER"))', configuracao)
