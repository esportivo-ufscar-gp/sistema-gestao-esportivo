"""
Testes unitários do módulo Loja online.

Pacote 4.5: catálogo com busca (4.5.1, HU10) e carrinho (4.5.2, HU11).

Cada critério de aceite tem pelo menos um teste. Os saldos dos produtos de teste são gravados
direto na criação; quando um teste precisa que o saldo caia "porque alguém comprou antes",
ele usa o serviço de estoque, como a venda faria.
"""
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.contrib.sessions.backends.db import SessionStore
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.contas.services import PERFIL_CLIENTE
from apps.estoque.models import MovimentoEstoque
from apps.estoque.services import registrar_ajuste
from apps.produtos.models import Categoria, Produto
from apps.vendas.carrinho import CHAVE_NA_SESSAO as CHAVE_DO_PDV

from .carrinho import CHAVE_NA_SESSAO, CarrinhoDaLoja, ErroDeCarrinho
from .services import (
    EM_ESTOQUE,
    ESGOTADO,
    ULTIMAS_UNIDADES,
    categorias_do_catalogo,
    disponibilidade,
    produtos_do_catalogo,
)
from .templatetags.loja import reais

SENHA = "senha-de-teste-123"


def cria_produto(codigo, nome, categoria, preco="100.00", saldo=10, minimo=2, **campos):
    return Produto.objects.create(
        codigo=codigo,
        nome=nome,
        categoria=categoria,
        preco=Decimal(preco),
        estoque_atual=saldo,
        estoque_minimo=minimo,
        **campos,
    )


class BaseDaLoja(TestCase):
    """Vitrine pequena: três categorias ativas, uma inativa e produtos em cada situação."""

    @classmethod
    def setUpTestData(cls):
        cls.corrida = Categoria.objects.create(nome="Corrida")
        cls.futebol = Categoria.objects.create(nome="Futebol")
        cls.natacao = Categoria.objects.create(nome="Natação")  # só tem produto inativo
        cls.inativa = Categoria.objects.create(nome="Patinação", ativa=False)

        cls.tenis = cria_produto("100110", "Tênis de corrida amortecido", cls.corrida, "349.90", saldo=12)
        cls.chuteira = cria_produto("100120", "Chuteira society", cls.futebol, "279.90", saldo=2, minimo=3)
        cls.bola = cria_produto("100130", "Bola de futebol de campo", cls.futebol, "149.90", saldo=0)
        cls.relogio = cria_produto("100140", "Relógio de corrida GPS", cls.corrida, "1234.56", saldo=5, minimo=1)
        cls.oculos = cria_produto("100150", "Óculos de natação", cls.natacao, "59.90", ativo=False)
        cls.patins = cria_produto("100160", "Patins in-line", cls.inativa, "499.90")

    def adiciona(self, produto, **extra):
        return self.client.post(reverse("loja:adicionar"), {"produto": produto.pk, **extra})

    def acao(self, acao, produto):
        return self.client.post(reverse("loja:carrinho"), {"acao": acao, "produto": produto.pk})

    def carrinho_da_sessao(self):
        return self.client.session.get(CHAVE_NA_SESSAO, {})


# ------------------------------------------------------------------ HU10 Catálogo (4.5.1)
class CatalogoTests(BaseDaLoja):
    """HU10: só aparecem produtos ativos de categorias ativas, com filtro, busca e ordenação."""

    def test_visitante_ve_o_catalogo(self):
        resposta = self.client.get(reverse("loja:catalogo"))

        self.assertEqual(resposta.status_code, 200)
        self.assertTemplateUsed(resposta, "loja/catalogo.html")
        self.assertContains(resposta, "Todos os produtos")

    def test_so_aparecem_produtos_ativos_de_categorias_ativas(self):
        resposta = self.client.get(reverse("loja:catalogo"))

        self.assertEqual(
            set(resposta.context["produtos"]),
            {self.tenis, self.chuteira, self.bola, self.relogio},
        )
        self.assertNotContains(resposta, self.oculos.nome)
        self.assertNotContains(resposta, self.patins.nome)

    def test_cartao_mostra_nome_categoria_preco_e_disponibilidade(self):
        resposta = self.client.get(reverse("loja:catalogo"))

        self.assertContains(resposta, "Tênis de corrida amortecido")
        self.assertContains(resposta, "Corrida")
        self.assertContains(resposta, "R$ 349,90")
        self.assertContains(resposta, "Em estoque")
        self.assertContains(resposta, "Últimas 2 unidades")
        self.assertContains(resposta, "Esgotado")

    def test_preco_no_formato_brasileiro_com_milhar(self):
        resposta = self.client.get(reverse("loja:catalogo"))

        self.assertContains(resposta, "R$ 1.234,56")
        self.assertEqual(reais(Decimal("1234.5")), "R$ 1.234,50")
        self.assertEqual(reais(Decimal("49.9")), "R$ 49,90")

    def test_produto_sem_imagem_mostra_espaco_reservado(self):
        resposta = self.client.get(reverse("loja:catalogo"))

        self.assertContains(resposta, "Foto do produto")
        self.assertNotContains(resposta, "<img")

    def test_filtro_tem_todos_e_so_categorias_ativas_com_produtos_ativos(self):
        self.assertEqual(list(categorias_do_catalogo()), [self.corrida, self.futebol])

        resposta = self.client.get(reverse("loja:catalogo"))
        nomes = [filtro["nome"] for filtro in resposta.context["filtros"]]

        self.assertEqual(nomes, ["Todos", "Corrida", "Futebol"])
        self.assertTrue(resposta.context["filtros"][0]["ativo"])

    def test_filtro_por_categoria(self):
        resposta = self.client.get(reverse("loja:catalogo"), {"categoria": self.futebol.pk})

        self.assertEqual(set(resposta.context["produtos"]), {self.chuteira, self.bola})
        self.assertEqual(resposta.context["categoria"], self.futebol)
        self.assertNotContains(resposta, self.tenis.nome)

    def test_categoria_inativa_ou_invalida_mostra_todos(self):
        for valor in (self.inativa.pk, "abc", "999"):
            with self.subTest(categoria=valor):
                resposta = self.client.get(reverse("loja:catalogo"), {"categoria": valor})

                self.assertIsNone(resposta.context["categoria"])
                self.assertEqual(len(resposta.context["produtos"]), 4)
                self.assertNotContains(resposta, self.patins.nome)

    def test_busca_pelo_nome_sem_diferenciar_maiusculas(self):
        resposta = self.client.get(reverse("loja:catalogo"), {"busca": "CHUTEIRA"})

        self.assertEqual(list(resposta.context["produtos"]), [self.chuteira])
        self.assertEqual(list(produtos_do_catalogo(busca="  de CORRIDA ")), [self.relogio, self.tenis])

    def test_busca_nao_encontra_produto_inativo(self):
        self.assertEqual(list(produtos_do_catalogo(busca="óculos")), [])
        self.assertEqual(list(produtos_do_catalogo(busca="patins")), [])

    def test_busca_combinada_com_categoria(self):
        resposta = self.client.get(reverse("loja:catalogo"), {"busca": "corrida", "categoria": self.futebol.pk})

        self.assertEqual(list(resposta.context["produtos"]), [])
        self.assertContains(resposta, "Nenhum produto encontrado.")

    def test_filtros_mantem_busca_e_ordenacao(self):
        resposta = self.client.get(reverse("loja:catalogo"), {"busca": "bola", "ordem": "maior_preco"})
        futebol = resposta.context["filtros"][2]

        self.assertIn("busca=bola", futebol["url"])
        self.assertIn("ordem=maior_preco", futebol["url"])
        self.assertIn(f"categoria={self.futebol.pk}", futebol["url"])

    def test_filtro_todos_sem_parametros_quando_nada_foi_escolhido(self):
        resposta = self.client.get(reverse("loja:catalogo"))

        self.assertEqual(resposta.context["filtros"][0]["url"], reverse("loja:catalogo"))

    def test_ordenacao_por_nome_menor_e_maior_preco(self):
        esperado = {
            "nome": [self.bola, self.chuteira, self.relogio, self.tenis],
            "menor_preco": [self.bola, self.chuteira, self.tenis, self.relogio],
            "maior_preco": [self.relogio, self.tenis, self.chuteira, self.bola],
        }

        for ordem, produtos in esperado.items():
            with self.subTest(ordem=ordem):
                resposta = self.client.get(reverse("loja:catalogo"), {"ordem": ordem})

                self.assertEqual(list(resposta.context["produtos"]), produtos)
                self.assertEqual(resposta.context["ordem"], ordem)

    def test_ordenacao_desconhecida_usa_o_nome(self):
        resposta = self.client.get(reverse("loja:catalogo"), {"ordem": "preco; drop table"})

        self.assertEqual(resposta.context["ordem"], "nome")
        self.assertEqual(list(resposta.context["produtos"])[0], self.bola)

    def test_esgotado_aparece_com_botao_desabilitado(self):
        resposta = self.client.get(reverse("loja:catalogo"), {"busca": "bola"})

        self.assertContains(resposta, self.bola.nome)
        self.assertContains(resposta, "Indisponível")
        self.assertContains(resposta, "disabled")
        self.assertNotContains(resposta, "Adicionar ao carrinho")

    def test_produto_disponivel_tem_botao_de_adicionar(self):
        resposta = self.client.get(reverse("loja:catalogo"), {"busca": "tênis"})

        self.assertContains(resposta, "Adicionar ao carrinho")
        self.assertContains(resposta, f'name="produto" value="{self.tenis.pk}"')


class DisponibilidadeTests(BaseDaLoja):
    """HU10: em estoque, últimas unidades ou esgotado, conforme o saldo e o mínimo."""

    def _situacao(self, saldo, minimo):
        return disponibilidade(Produto(estoque_atual=saldo, estoque_minimo=minimo))

    def test_saldo_acima_do_minimo_esta_em_estoque(self):
        situacao = self._situacao(saldo=4, minimo=3)

        self.assertEqual(situacao.situacao, EM_ESTOQUE)
        self.assertEqual(situacao.rotulo, "Em estoque")
        self.assertTrue(situacao.pode_comprar)

    def test_saldo_igual_ao_minimo_sao_ultimas_unidades(self):
        situacao = self._situacao(saldo=3, minimo=3)

        self.assertEqual(situacao.situacao, ULTIMAS_UNIDADES)
        self.assertEqual(situacao.rotulo, "Últimas 3 unidades")
        self.assertTrue(situacao.pode_comprar)

    def test_saldo_abaixo_do_minimo_sao_ultimas_unidades(self):
        self.assertEqual(self._situacao(saldo=2, minimo=3).rotulo, "Últimas 2 unidades")
        self.assertEqual(self._situacao(saldo=1, minimo=3).rotulo, "Última unidade")

    def test_saldo_zero_esta_esgotado(self):
        situacao = self._situacao(saldo=0, minimo=3)

        self.assertEqual(situacao.situacao, ESGOTADO)
        self.assertEqual(situacao.rotulo, "Esgotado")
        self.assertFalse(situacao.pode_comprar)

    def test_minimo_zero_com_saldo_esta_em_estoque(self):
        self.assertEqual(self._situacao(saldo=1, minimo=0).situacao, EM_ESTOQUE)
        self.assertEqual(self._situacao(saldo=0, minimo=0).situacao, ESGOTADO)


# ------------------------------------------------------------------ HU11 Carrinho (4.5.2)
class CarrinhoDaLojaTests(BaseDaLoja):
    """HU11: regras do carrinho guardado na sessão."""

    def setUp(self):
        self.sessao = SessionStore()
        self.carrinho = CarrinhoDaLoja(self.sessao)

    def test_adicionar_soma_a_quantidade(self):
        self.carrinho.adicionar(self.tenis)
        self.carrinho.adicionar(self.tenis, 2)

        self.assertEqual(self.carrinho.quantidade_de(self.tenis), 3)
        self.assertEqual(self.sessao[CHAVE_NA_SESSAO], {str(self.tenis.pk): 3})

    def test_quantidade_acima_do_saldo_e_recusada_sem_mudar_o_carrinho(self):
        self.carrinho.alterar(self.chuteira, 2)

        with self.assertRaisesMessage(ErroDeCarrinho, "tem só 2 em estoque"):
            self.carrinho.adicionar(self.chuteira)
        with self.assertRaises(ErroDeCarrinho):
            self.carrinho.alterar(self.chuteira, 3)

        self.assertEqual(self.carrinho.quantidade_de(self.chuteira), 2)

    def test_esgotado_nao_entra_no_carrinho(self):
        with self.assertRaisesMessage(ErroDeCarrinho, "está esgotado"):
            self.carrinho.adicionar(self.bola)

        self.assertFalse(self.carrinho)

    def test_produto_ou_categoria_inativos_nao_entram_no_carrinho(self):
        for produto in (self.oculos, self.patins):
            with self.subTest(produto=produto.nome):
                with self.assertRaisesMessage(ErroDeCarrinho, "não está mais à venda"):
                    self.carrinho.adicionar(produto)

        self.assertFalse(self.carrinho)

    def test_alterar_para_zero_remove(self):
        self.carrinho.adicionar(self.tenis)

        self.assertEqual(self.carrinho.alterar(self.tenis, 0), 0)
        self.assertEqual(len(self.carrinho), 0)

    def test_remover_e_limpar(self):
        self.carrinho.adicionar(self.tenis)
        self.carrinho.adicionar(self.relogio)

        self.carrinho.remover(self.tenis)
        self.assertEqual(len(self.carrinho), 1)

        self.carrinho.limpar()
        self.assertFalse(self.carrinho)
        self.assertNotIn(CHAVE_NA_SESSAO, self.sessao)

    def test_subtotal_e_total_sao_recalculados(self):
        self.carrinho.alterar(self.tenis, 2)
        self.carrinho.alterar(self.relogio, 1)

        linhas = self.carrinho.linhas()
        self.assertEqual([linha["subtotal"] for linha in linhas], [Decimal("1234.56"), Decimal("699.80")])
        self.assertEqual(self.carrinho.total(), Decimal("1934.36"))
        self.assertEqual(self.carrinho.quantidade_de_itens, 3)

        self.carrinho.alterar(self.tenis, 1)
        self.assertEqual(self.carrinho.total(), Decimal("1584.46"))

        self.carrinho.remover(self.relogio)
        self.assertEqual(self.carrinho.total(), Decimal("349.90"))

    def test_preco_e_lido_do_banco(self):
        self.carrinho.adicionar(self.tenis)
        Produto.objects.filter(pk=self.tenis.pk).update(preco=Decimal("300.00"))

        self.assertEqual(self.carrinho.total(), Decimal("300.00"))

    def test_chave_da_sessao_e_diferente_da_venda_do_pdv(self):
        self.assertNotEqual(CHAVE_NA_SESSAO, CHAVE_DO_PDV)
        self.sessao[CHAVE_DO_PDV] = {str(self.relogio.pk): 1}

        self.carrinho.adicionar(self.tenis)
        self.carrinho.limpar()

        self.assertEqual(self.sessao[CHAVE_DO_PDV], {str(self.relogio.pk): 1})

    def test_aviso_quando_o_saldo_fica_menor_que_o_carrinho(self):
        self.carrinho.alterar(self.relogio, 4)
        registrar_ajuste(self.relogio, 3, motivo="Venda no balcão antes do cliente")

        linha = self.carrinho.linhas()[0]

        self.assertIn("Agora só há 2 em estoque", linha["aviso"])
        self.assertFalse(linha["pode_aumentar"])

    def test_aviso_quando_o_produto_esgota_ou_sai_de_venda(self):
        self.carrinho.alterar(self.relogio, 1)
        self.carrinho.alterar(self.tenis, 1)
        registrar_ajuste(self.relogio, 5, motivo="Quebra")
        Produto.objects.filter(pk=self.tenis.pk).update(ativo=False)

        avisos = {linha["produto"].pk: linha["aviso"] for linha in self.carrinho.linhas()}

        self.assertIn("esgotou", avisos[self.relogio.pk])
        self.assertIn("não está mais à venda", avisos[self.tenis.pk])

    def test_carrinho_nao_reserva_estoque_nem_cria_movimentos(self):
        self.carrinho.alterar(self.tenis, 5)
        self.carrinho.adicionar(self.relogio)
        self.carrinho.alterar(self.tenis, 2)
        self.carrinho.remover(self.relogio)
        self.carrinho.limpar()

        self.tenis.refresh_from_db()
        self.relogio.refresh_from_db()
        self.assertEqual(self.tenis.estoque_atual, 12)
        self.assertEqual(self.relogio.estoque_atual, 5)
        self.assertFalse(MovimentoEstoque.objects.exists())


class PaginaDoCarrinhoTests(BaseDaLoja):
    """HU11: adicionar, alterar e remover pela tela, com as mensagens do motivo."""

    def test_visitante_usa_o_carrinho(self):
        resposta = self.adiciona(self.tenis)

        self.assertRedirects(resposta, reverse("loja:catalogo"))
        self.assertEqual(self.carrinho_da_sessao(), {str(self.tenis.pk): 1})

        pagina = self.client.get(reverse("loja:carrinho"))
        self.assertEqual(pagina.status_code, 200)
        self.assertContains(pagina, self.tenis.nome)
        self.assertContains(pagina, "Carrinho (1)")

    def test_adicionar_mostra_mensagem_e_volta_para_a_pagina_de_origem(self):
        origem = f"{reverse('loja:catalogo')}?categoria={self.corrida.pk}"

        resposta = self.adiciona(self.tenis, next=origem)

        self.assertRedirects(resposta, origem, fetch_redirect_response=False)
        pagina = self.client.get(origem)
        self.assertContains(pagina, "Tênis de corrida amortecido foi para o carrinho.")

    def test_next_para_outro_site_e_ignorado(self):
        resposta = self.adiciona(self.tenis, next="https://exemplo.com/")

        self.assertRedirects(resposta, reverse("loja:catalogo"))

    def test_adicionar_so_aceita_post(self):
        resposta = self.client.get(reverse("loja:adicionar"), {"produto": self.tenis.pk})

        self.assertEqual(resposta.status_code, 405)
        self.assertEqual(self.carrinho_da_sessao(), {})

    def test_esgotado_nao_entra_nem_por_post_direto(self):
        resposta = self.adiciona(self.bola)

        self.assertEqual(self.carrinho_da_sessao(), {})
        pagina = self.client.get(resposta.url)
        self.assertContains(pagina, "Bola de futebol de campo está esgotado.")

    def test_inativo_nao_entra_por_post_direto(self):
        self.adiciona(self.oculos)
        self.adiciona(self.patins)

        self.assertEqual(self.carrinho_da_sessao(), {})

    def test_produto_inexistente_da_404(self):
        for valor in ("999999", "abc", ""):
            with self.subTest(produto=valor):
                resposta = self.client.post(reverse("loja:adicionar"), {"produto": valor})

                self.assertEqual(resposta.status_code, 404)

    def test_quantidade_acima_do_saldo_e_recusada(self):
        self.adiciona(self.chuteira)
        self.adiciona(self.chuteira)

        resposta = self.adiciona(self.chuteira)
        self.assertEqual(self.carrinho_da_sessao(), {str(self.chuteira.pk): 2})
        self.assertContains(self.client.get(resposta.url), "Chuteira society tem só 2 em estoque")

        self.acao("aumentar", self.chuteira)
        self.assertEqual(self.carrinho_da_sessao(), {str(self.chuteira.pk): 2})

    def test_mais_menos_e_remover_recalculam_subtotal_e_total(self):
        self.adiciona(self.tenis)

        self.acao("aumentar", self.tenis)
        pagina = self.client.get(reverse("loja:carrinho"))
        self.assertEqual(pagina.context["total"], Decimal("699.80"))
        self.assertContains(pagina, "Subtotal (2 itens)")
        self.assertContains(pagina, "R$ 699,80")
        self.assertContains(pagina, "Carrinho (2)")

        self.acao("diminuir", self.tenis)
        pagina = self.client.get(reverse("loja:carrinho"))
        self.assertEqual(pagina.context["total"], Decimal("349.90"))
        self.assertContains(pagina, "Subtotal (1 item)")

        resposta = self.acao("remover", self.tenis)
        self.assertRedirects(resposta, reverse("loja:carrinho"), fetch_redirect_response=False)
        pagina = self.client.get(reverse("loja:carrinho"))
        self.assertEqual(self.carrinho_da_sessao(), {})
        self.assertContains(pagina, "Seu carrinho está vazio.")
        self.assertContains(pagina, "Tênis de corrida amortecido saiu do carrinho.")

    def test_pagina_segue_o_prototipo(self):
        self.adiciona(self.tenis)

        pagina = self.client.get(reverse("loja:carrinho"))

        for texto in (
            "Carrinho", "Identificação e pagamento", "Confirmação", "Seu carrinho",
            "Corrida", "R$ 349,90 cada · 12 em estoque", "Remover", "Resumo do pedido",
            "Entrega: retirada na loja", "Grátis", "Total", "Continuar comprando",
        ):
            self.assertContains(pagina, texto)

    def test_continuar_para_o_pagamento_fica_desabilitado(self):
        self.adiciona(self.tenis)

        pagina = self.client.get(reverse("loja:carrinho"))

        self.assertContains(pagina, "Continuar para o pagamento")
        self.assertContains(pagina, "4.5.3")
        self.assertRegex(pagina.content.decode(), r'<button[^>]*disabled[^>]*>\s*Continuar para o pagamento')

    def test_aviso_e_ajuste_quando_alguem_comprou_antes(self):
        self.adiciona(self.relogio)
        self.acao("aumentar", self.relogio)
        self.acao("aumentar", self.relogio)
        registrar_ajuste(self.relogio, 4, motivo="Venda no balcão antes do cliente")

        pagina = self.client.get(reverse("loja:carrinho"))
        self.assertContains(pagina, "Agora só há 1 em estoque")
        self.assertContains(pagina, "Ajustar para 1")

        self.acao("ajustar", self.relogio)
        self.assertEqual(self.carrinho_da_sessao(), {str(self.relogio.pk): 1})
        self.assertNotContains(self.client.get(reverse("loja:carrinho")), "Agora só há")

    def test_acao_desconhecida_nao_muda_o_carrinho(self):
        self.adiciona(self.tenis)

        resposta = self.acao("dobrar", self.tenis)

        self.assertEqual(self.carrinho_da_sessao(), {str(self.tenis.pk): 1})
        self.assertContains(self.client.get(resposta.url), "Ação desconhecida.")

    def test_usar_o_carrinho_nao_altera_saldo_nem_cria_movimentos(self):
        self.adiciona(self.tenis)
        self.acao("aumentar", self.tenis)
        self.acao("diminuir", self.tenis)
        self.adiciona(self.chuteira)
        self.acao("remover", self.chuteira)
        self.client.get(reverse("loja:carrinho"))

        self.tenis.refresh_from_db()
        self.chuteira.refresh_from_db()
        self.assertEqual(self.tenis.estoque_atual, 12)
        self.assertEqual(self.chuteira.estoque_atual, 2)
        self.assertFalse(MovimentoEstoque.objects.exists())


class CarrinhoELoginTests(BaseDaLoja):
    """HU11: o carrinho do visitante continua depois do login; o cliente cai no catálogo."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        call_command("criar_perfis", verbosity=0)
        cls.cliente = User.objects.create_user(
            "marina@exemplo.com", "marina@exemplo.com", SENHA, first_name="Marina Silva"
        )
        cls.cliente.groups.add(Group.objects.get(name=PERFIL_CLIENTE))

    def entra(self):
        return self.client.post(
            reverse("contas:entrar"),
            {"username": "marina@exemplo.com", "password": SENHA},
        )

    def test_carrinho_continua_depois_do_login(self):
        self.adiciona(self.tenis)
        self.adiciona(self.relogio)

        resposta = self.entra()

        self.assertRedirects(resposta, reverse("loja:catalogo"))
        self.assertIn("_auth_user_id", self.client.session)
        self.assertEqual(
            self.carrinho_da_sessao(),
            {str(self.tenis.pk): 1, str(self.relogio.pk): 1},
        )
        self.assertContains(self.client.get(reverse("loja:carrinho")), "Carrinho (2)")

    def test_cliente_cai_no_catalogo_e_ve_o_nome_e_sair(self):
        resposta = self.entra()

        self.assertRedirects(resposta, reverse("loja:catalogo"))
        pagina = self.client.get(reverse("loja:catalogo"))
        self.assertContains(pagina, "Marina Silva")
        self.assertContains(pagina, reverse("contas:sair"))
        self.assertNotContains(pagina, f'href="{reverse("contas:entrar")}"')

    def test_visitante_ve_entrar_e_carrinho_vazio(self):
        pagina = self.client.get(reverse("loja:catalogo"))

        self.assertContains(pagina, f'href="{reverse("contas:entrar")}"')
        self.assertContains(pagina, "Carrinho (0)")
