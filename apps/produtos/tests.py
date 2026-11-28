"""
Testes unitários do módulo Produtos.

Pacote 4.2: categorias (4.2.1) e produtos (4.2.2).

Cada critério de aceite das histórias HU03 e HU04 tem pelo menos um teste. As restrições
importantes são verificadas duas vezes: na validação em Python (full_clean, que é o caminho
do Admin) e no banco de dados, com uma escrita que passa por cima da validação em Python.
"""
import tempfile
from decimal import Decimal
from io import BytesIO

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .admin import CategoriaAdmin, FotoDoProdutoInline, ProdutoAdmin
from .models import Categoria, FotoDoProduto, Produto


def cria_produto(categoria, codigo="100110", **campos):
    """Cria um produto válido; os campos passados substituem os valores padrão."""
    dados = {
        "codigo": codigo,
        "nome": "Tênis de corrida amortecido",
        "preco": Decimal("349.90"),
        "categoria": categoria,
    }
    dados.update(campos)
    return Produto.objects.create(**dados)


def imagem_de_teste(nome="tenis.png"):
    """Gera um PNG mínimo em memória para testar o upload."""
    conteudo = BytesIO()
    Image.new("RGB", (2, 2), "white").save(conteudo, format="PNG")
    return SimpleUploadedFile(nome, conteudo.getvalue(), content_type="image/png")


# --------------------------------------------------------------- HU03 Categorias (4.2.1)
class CategoriaTests(TestCase):
    """HU03: cadastrar categorias por modalidade esportiva."""

    def test_categoria_valida_e_criada_e_nasce_ativa(self):
        categoria = Categoria.objects.create(nome="Corrida")
        categoria.full_clean()

        self.assertTrue(categoria.ativa)
        self.assertEqual(str(categoria), "Corrida")

    def test_nome_e_obrigatorio(self):
        with self.assertRaises(ValidationError) as erro:
            Categoria(nome="").full_clean()

        self.assertIn("nome", erro.exception.error_dict)

    def test_nome_repetido_e_recusado_na_validacao(self):
        Categoria.objects.create(nome="Futebol")

        with self.assertRaises(ValidationError) as erro:
            Categoria(nome="Futebol").full_clean()

        self.assertIn("nome", erro.exception.error_dict)

    def test_nome_repetido_e_recusado_no_banco(self):
        Categoria.objects.create(nome="Natação")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Categoria.objects.create(nome="Natação")

    def test_categoria_sem_produtos_pode_ser_excluida(self):
        categoria = Categoria.objects.create(nome="Ciclismo")

        categoria.delete()

        self.assertFalse(Categoria.objects.filter(nome="Ciclismo").exists())

    def test_categoria_com_produtos_vinculados_nao_pode_ser_excluida(self):
        categoria = Categoria.objects.create(nome="Academia")
        cria_produto(categoria)

        with self.assertRaises(ProtectedError):
            with transaction.atomic():
                categoria.delete()

        self.assertTrue(Categoria.objects.filter(pk=categoria.pk).exists())


# ------------------------------------------------- HU04 Produtos: campos obrigatórios (4.2.2)
class ProdutoCamposObrigatoriosTests(TestCase):
    """HU04: código, nome, preço e categoria são obrigatórios; a imagem é opcional."""

    def setUp(self):
        self.categoria = Categoria.objects.create(nome="Corrida")

    def test_produto_sem_codigo_nome_preco_e_categoria_e_recusado(self):
        with self.assertRaises(ValidationError) as erro:
            Produto().full_clean()

        for campo in ("codigo", "nome", "preco", "categoria"):
            self.assertIn(campo, erro.exception.error_dict)

    def test_produto_com_os_campos_obrigatorios_e_valido(self):
        produto = cria_produto(self.categoria)
        produto.full_clean()

        self.assertEqual(str(produto), "100110 - Tênis de corrida amortecido")

    def test_descricao_e_imagem_sao_opcionais(self):
        produto = cria_produto(self.categoria)
        produto.full_clean()

        self.assertEqual(produto.descricao, "")
        self.assertFalse(produto.imagem)

    def test_categoria_do_produto_usa_protect(self):
        campo = Produto._meta.get_field("categoria")

        self.assertEqual(campo.remote_field.on_delete.__name__, "PROTECT")


class ProdutoCodigoTests(TestCase):
    """HU04: o código é único."""

    def setUp(self):
        self.categoria = Categoria.objects.create(nome="Futebol")
        cria_produto(self.categoria, codigo="100245", nome="Camisa de futebol listrada")

    def test_codigo_repetido_e_recusado_na_validacao(self):
        repetido = Produto(
            codigo="100245",
            nome="Outro produto",
            preco=Decimal("10.00"),
            categoria=self.categoria,
        )

        with self.assertRaises(ValidationError) as erro:
            repetido.full_clean()

        self.assertIn("codigo", erro.exception.error_dict)

    def test_codigo_repetido_e_recusado_no_banco(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                cria_produto(self.categoria, codigo="100245", nome="Outro produto")


class ProdutoPrecoTests(TestCase):
    """HU04: o preço precisa ser maior que zero."""

    def setUp(self):
        self.categoria = Categoria.objects.create(nome="Academia")

    def test_preco_zero_e_recusado_na_validacao(self):
        produto = Produto(codigo="100231", nome="Camisa", preco=Decimal("0.00"), categoria=self.categoria)

        with self.assertRaises(ValidationError) as erro:
            produto.full_clean()

        self.assertIn("preco", erro.exception.error_dict)

    def test_preco_negativo_e_recusado_na_validacao(self):
        produto = Produto(codigo="100231", nome="Camisa", preco=Decimal("-1.00"), categoria=self.categoria)

        with self.assertRaises(ValidationError) as erro:
            produto.full_clean()

        self.assertIn("preco", erro.exception.error_dict)

    def test_preco_zero_e_recusado_no_banco(self):
        produto = cria_produto(self.categoria, codigo="100231")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Produto.objects.filter(pk=produto.pk).update(preco=Decimal("0.00"))

    def test_preco_e_guardado_como_decimal(self):
        produto = cria_produto(self.categoria, codigo="100260", preco=Decimal("99.90"))
        produto.refresh_from_db()

        self.assertEqual(produto.preco, Decimal("99.90"))


class ProdutoEstoqueTests(TestCase):
    """Modelo de dados: estoque_atual e estoque_minimo nunca ficam negativos."""

    def setUp(self):
        self.categoria = Categoria.objects.create(nome="Natação")

    def test_estoques_comecam_em_zero(self):
        produto = cria_produto(self.categoria, codigo="100420")

        self.assertEqual(produto.estoque_atual, 0)
        self.assertEqual(produto.estoque_minimo, 0)

    def test_estoques_negativos_sao_recusados_na_validacao(self):
        produto = Produto(
            codigo="100420",
            nome="Óculos de natação antiembaçante",
            preco=Decimal("59.90"),
            categoria=self.categoria,
            estoque_atual=-1,
            estoque_minimo=-2,
        )

        with self.assertRaises(ValidationError) as erro:
            produto.full_clean()

        self.assertIn("estoque_atual", erro.exception.error_dict)
        self.assertIn("estoque_minimo", erro.exception.error_dict)

    def test_estoque_atual_negativo_e_recusado_no_banco(self):
        produto = cria_produto(self.categoria, codigo="100420")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Produto.objects.filter(pk=produto.pk).update(estoque_atual=-1)

    def test_estoque_minimo_negativo_e_recusado_no_banco(self):
        produto = cria_produto(self.categoria, codigo="100420")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Produto.objects.filter(pk=produto.pk).update(estoque_minimo=-1)


class ProdutoAtivoTests(TestCase):
    """HU04: produto já vendido é desativado, nunca excluído (a venda chega no pacote 4.4.1)."""

    def setUp(self):
        self.categoria = Categoria.objects.create(nome="Ciclismo")

    def test_produto_nasce_ativo(self):
        produto = cria_produto(self.categoria, codigo="100480")

        self.assertTrue(produto.ativo)

    def test_produto_desativado_continua_no_catalogo(self):
        produto = cria_produto(self.categoria, codigo="100480")

        produto.ativo = False
        produto.save()
        produto.refresh_from_db()

        self.assertFalse(produto.ativo)
        self.assertTrue(Produto.objects.filter(pk=produto.pk).exists())


class ProdutoImagemTests(TestCase):
    """HU04: a imagem é opcional e fica na pasta produtos/."""

    def setUp(self):
        self.categoria = Categoria.objects.create(nome="Corrida")
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        media = override_settings(MEDIA_ROOT=pasta.name)
        media.enable()
        self.addCleanup(media.disable)

    def test_produto_sem_imagem_e_valido(self):
        produto = cria_produto(self.categoria)
        produto.full_clean()

        self.assertEqual(produto.imagem.name, "")

    def test_imagem_enviada_e_salva_na_pasta_produtos(self):
        produto = cria_produto(self.categoria, imagem=imagem_de_teste())
        self.addCleanup(produto.imagem.close)

        self.assertTrue(produto.imagem.name.startswith("produtos/"))
        self.assertTrue(produto.imagem.storage.exists(produto.imagem.name))

    def test_campo_imagem_aponta_para_a_pasta_produtos(self):
        self.assertEqual(Produto._meta.get_field("imagem").upload_to, "produtos/")


# ----------------------------------------------------------------------- Django Admin
class ProdutoAdminTests(TestCase):
    """Os cadastros internos ficam no Admin (CLAUDE.md), com o saldo só para leitura."""

    def setUp(self):
        self.corrida = Categoria.objects.create(nome="Corrida")
        self.futebol = Categoria.objects.create(nome="Futebol")
        self.tenis = cria_produto(self.corrida, codigo="100110", estoque_atual=12, estoque_minimo=4)
        self.bola = cria_produto(self.futebol, codigo="100275", nome="Bola de futebol de campo")
        self.usuario = User.objects.create_superuser("gerente", "gerente@exemplo.com", "senha-de-teste-123")
        self.client.force_login(self.usuario)

    def test_lista_mostra_as_colunas_pedidas(self):
        self.assertEqual(
            ProdutoAdmin.list_display,
            ("codigo", "nome", "categoria", "preco", "estoque_atual", "ativo"),
        )

    def test_busca_por_nome_e_codigo(self):
        self.assertEqual(ProdutoAdmin.search_fields, ("nome", "codigo"))

        endereco = reverse("admin:produtos_produto_changelist")
        por_codigo = self.client.get(endereco, {"q": "100110"})
        por_nome = self.client.get(endereco, {"q": "Bola de futebol"})

        self.assertEqual(list(por_codigo.context["cl"].queryset), [self.tenis])
        self.assertEqual(list(por_nome.context["cl"].queryset), [self.bola])

    def test_filtros_por_categoria_e_ativo(self):
        self.assertEqual(ProdutoAdmin.list_filter, ("categoria", "ativo"))

        endereco = reverse("admin:produtos_produto_changelist")
        resposta = self.client.get(endereco, {"categoria__id__exact": self.futebol.pk, "ativo__exact": "1"})

        self.assertEqual(list(resposta.context["cl"].queryset), [self.bola])

    def test_estoque_atual_e_somente_leitura(self):
        self.assertIn("estoque_atual", ProdutoAdmin.readonly_fields)

        endereco = reverse("admin:produtos_produto_change", args=[self.tenis.pk])
        resposta = self.client.get(endereco)
        formulario = resposta.context["adminform"].form

        self.assertNotIn("estoque_atual", formulario.fields)
        self.assertNotContains(resposta, 'name="estoque_atual"')

    def test_admin_nao_altera_o_saldo_ao_salvar_o_produto(self):
        endereco = reverse("admin:produtos_produto_change", args=[self.tenis.pk])
        resposta = self.client.post(endereco, {
            "codigo": "100110",
            "nome": "Tênis de corrida amortecido",
            "categoria": self.corrida.pk,
            "ativo": "on",
            "descricao": "Modelo para treinos de rua.",
            "preco": "359.90",
            "estoque_atual": "999",   # ignorado: o campo é somente leitura
            "estoque_minimo": "4",
            # Controle do inline de fotos extras (pacote 3.3), que o navegador sempre envia.
            "fotos-TOTAL_FORMS": "0",
            "fotos-INITIAL_FORMS": "0",
            "fotos-MIN_NUM_FORMS": "0",
            "fotos-MAX_NUM_FORMS": "1000",
        })
        self.tenis.refresh_from_db()

        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(self.tenis.preco, Decimal("359.90"))
        self.assertEqual(self.tenis.estoque_atual, 12)


# ------------------------------------------------------------ Fotos extras (pacote 3.3)
class FotoDoProdutoTests(TestCase):
    """As fotos extras pertencem ao produto e saem na ordem do campo ordem."""

    def setUp(self):
        self.tenis = cria_produto(Categoria.objects.create(nome="Corrida"))

    def test_fotos_saem_pela_ordem_e_no_empate_pela_criacao(self):
        segunda = FotoDoProduto.objects.create(produto=self.tenis, imagem="produtos/b.jpg", ordem=2)
        primeira = FotoDoProduto.objects.create(produto=self.tenis, imagem="produtos/a.jpg", ordem=1)
        empatada = FotoDoProduto.objects.create(produto=self.tenis, imagem="produtos/c.jpg", ordem=2)

        self.assertEqual(list(self.tenis.fotos.all()), [primeira, segunda, empatada])

    def test_nomes_em_portugues_e_pasta_produtos(self):
        meta = FotoDoProduto._meta

        self.assertEqual(meta.verbose_name, "foto do produto")
        self.assertEqual(meta.verbose_name_plural, "fotos do produto")
        self.assertEqual(meta.get_field("produto").verbose_name, "produto")
        self.assertEqual(meta.get_field("imagem").verbose_name, "imagem")
        self.assertEqual(meta.get_field("ordem").verbose_name, "ordem")
        self.assertEqual(meta.get_field("imagem").upload_to, "produtos/")

    def test_imagem_e_obrigatoria(self):
        with self.assertRaises(ValidationError):
            FotoDoProduto(produto=self.tenis, ordem=1).full_clean()

    def test_ordem_negativa_e_recusada_no_python_e_no_banco(self):
        with self.assertRaises(ValidationError):
            FotoDoProduto(produto=self.tenis, imagem="produtos/a.jpg", ordem=-1).full_clean()
        with self.assertRaises(IntegrityError), transaction.atomic():
            FotoDoProduto.objects.create(produto=self.tenis, imagem="produtos/a.jpg", ordem=-1)

    def test_excluir_produto_sem_historico_leva_as_fotos(self):
        FotoDoProduto.objects.create(produto=self.tenis, imagem="produtos/a.jpg")

        self.tenis.delete()

        self.assertFalse(FotoDoProduto.objects.exists())

    def test_texto_da_foto(self):
        foto = FotoDoProduto(produto=self.tenis, imagem="produtos/a.jpg", ordem=2)

        self.assertEqual(str(foto), "Foto 2 de 100110 - Tênis de corrida amortecido")


class FotosExtrasNoAdminTests(TestCase):
    """As fotos extras são cadastradas, ordenadas e removidas na própria tela do produto."""

    def setUp(self):
        pasta = tempfile.TemporaryDirectory()
        self.addCleanup(pasta.cleanup)
        media = override_settings(MEDIA_ROOT=pasta.name)
        media.enable()
        self.addCleanup(media.disable)

        self.corrida = Categoria.objects.create(nome="Corrida")
        self.tenis = cria_produto(self.corrida)
        self.usuario = User.objects.create_superuser("gerente", "gerente@exemplo.com", "senha-de-teste-123")
        self.client.force_login(self.usuario)
        self.endereco = reverse("admin:produtos_produto_change", args=[self.tenis.pk])

    def salva_o_produto(self, fotos, iniciais=0):
        """Envia a tela do produto com as linhas de fotos extras informadas."""
        dados = {
            "codigo": self.tenis.codigo,
            "nome": self.tenis.nome,
            "categoria": self.corrida.pk,
            "ativo": "on",
            "descricao": "",
            "preco": "349.90",
            "estoque_minimo": "0",
            "fotos-TOTAL_FORMS": str(len(fotos)),
            "fotos-INITIAL_FORMS": str(iniciais),
            "fotos-MIN_NUM_FORMS": "0",
            "fotos-MAX_NUM_FORMS": "1000",
        }
        for indice, foto in enumerate(fotos):
            dados.update({f"fotos-{indice}-{campo}": valor for campo, valor in foto.items()})
            dados[f"fotos-{indice}-produto"] = self.tenis.pk
        return self.client.post(self.endereco, dados)

    def test_tela_do_produto_tem_o_inline_de_fotos(self):
        self.assertEqual(ProdutoAdmin.inlines, (FotoDoProdutoInline,))
        self.assertEqual(FotoDoProdutoInline.fields, ("imagem", "ordem"))

        resposta = self.client.get(self.endereco)

        self.assertContains(resposta, 'name="fotos-TOTAL_FORMS"')
        self.assertContains(resposta, "Fotos extras (aparecem no catálogo depois da foto principal)")

    def test_cadastra_foto_extra(self):
        resposta = self.salva_o_produto([{"imagem": imagem_de_teste("lado.png"), "ordem": "1"}])

        self.assertEqual(resposta.status_code, 302)
        foto = self.tenis.fotos.get()
        self.addCleanup(foto.imagem.close)
        self.assertEqual(foto.ordem, 1)
        self.assertTrue(foto.imagem.name.startswith("produtos/"))
        self.assertTrue(foto.imagem.storage.exists(foto.imagem.name))

    def test_reordena_e_remove_fotos_extras(self):
        lado = FotoDoProduto.objects.create(produto=self.tenis, imagem="produtos/lado.jpg", ordem=1)
        sola = FotoDoProduto.objects.create(produto=self.tenis, imagem="produtos/sola.jpg", ordem=2)
        detalhe = FotoDoProduto.objects.create(produto=self.tenis, imagem="produtos/detalhe.jpg", ordem=3)

        resposta = self.salva_o_produto(
            [
                {"id": lado.pk, "ordem": "3"},
                {"id": sola.pk, "ordem": "2", "DELETE": "on"},
                {"id": detalhe.pk, "ordem": "1"},
            ],
            iniciais=3,
        )

        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(list(self.tenis.fotos.all()), [detalhe, lado])


class CategoriaAdminTests(TestCase):
    def setUp(self):
        self.categoria = Categoria.objects.create(nome="Academia")
        self.usuario = User.objects.create_superuser("admin", "admin@exemplo.com", "senha-de-teste-123")
        self.client.force_login(self.usuario)

    def test_lista_mostra_quantos_produtos_a_categoria_tem(self):
        cria_produto(self.categoria, codigo="100310", nome="Luvas de musculação")

        resposta = self.client.get(reverse("admin:produtos_categoria_changelist"))
        listada = resposta.context["cl"].queryset.get(pk=self.categoria.pk)

        self.assertEqual(CategoriaAdmin.list_display, ("nome", "ativa", "total_de_produtos"))
        self.assertEqual(listada._total_de_produtos, 1)

    def test_admin_nao_exclui_categoria_com_produtos_vinculados(self):
        cria_produto(self.categoria, codigo="100310", nome="Luvas de musculação")

        endereco = reverse("admin:produtos_categoria_delete", args=[self.categoria.pk])
        resposta = self.client.post(endereco, {"post": "yes"})

        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(Categoria.objects.filter(pk=self.categoria.pk).exists())


# ------------------------------------------------------------------------- Fixture
class FixtureDadosExemploTests(TestCase):
    """A carga inicial de demonstração: 6 categorias e 10 produtos do catálogo."""

    @classmethod
    def setUpTestData(cls):
        call_command("loaddata", "dados_exemplo", app_label="produtos", verbosity=0)

    def test_carrega_as_seis_categorias(self):
        nomes = sorted(Categoria.objects.values_list("nome", flat=True))

        self.assertEqual(
            nomes,
            sorted(["Corrida", "Futebol", "Academia", "Natação", "Ciclismo", "Acessórios"]),
        )

    def test_carrega_os_dez_produtos_com_preco_e_estoque(self):
        self.assertEqual(Produto.objects.count(), 10)

        tenis = Produto.objects.get(codigo="100110")

        self.assertEqual(tenis.nome, "Tênis de corrida amortecido")
        self.assertEqual(tenis.categoria.nome, "Corrida")
        self.assertEqual(tenis.preco, Decimal("349.90"))
        self.assertEqual(tenis.estoque_atual, 12)
        self.assertEqual(tenis.estoque_minimo, 4)

    def test_produtos_da_fixture_passam_na_validacao(self):
        for produto in Produto.objects.all():
            with self.subTest(codigo=produto.codigo):
                produto.full_clean()

    def test_fixture_tem_produtos_zerados_para_a_demonstracao(self):
        zerados = set(Produto.objects.filter(estoque_atual=0).values_list("codigo", flat=True))

        self.assertEqual(zerados, {"100260", "100480"})
