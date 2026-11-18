"""
Testes unitários do módulo Loja online.

Pacote 4.5: catálogo com busca (4.5.1, HU10), carrinho (4.5.2, HU11), checkout com pagamento
simulado (4.5.3, HU12) e gestão de pedidos no Admin (4.5.4, HU13).

Cada critério de aceite tem pelo menos um teste. Os saldos dos produtos de teste são gravados
direto na criação; quando um teste precisa que o saldo caia "porque alguém comprou antes",
ele usa o serviço de estoque ou o PDV, como a venda faria.
"""
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.contrib.sessions.backends.db import SessionStore
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.clientes.models import Cliente
from apps.clientes.services import cadastrar_cliente
from apps.contas.services import PERFIL_ADMINISTRADOR, PERFIL_CLIENTE, PERFIL_ESTOQUISTA, PERFIL_VENDEDOR
from apps.estoque.models import MovimentoEstoque
from apps.estoque.services import registrar_ajuste
from apps.produtos.models import Categoria, Produto
from apps.vendas.carrinho import CHAVE_NA_SESSAO as CHAVE_DO_PDV
from apps.vendas.models import CanalDeVenda, ContadorDeVendas, FormaDePagamento, StatusDeVenda, Venda
from apps.vendas.services import cancelar_venda, marcar_retirado, registrar_pedido_online, registrar_venda_pdv

from .admin import PedidoOnlineAdmin
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

    def test_continuar_para_o_pagamento_leva_ao_checkout(self):
        self.adiciona(self.tenis)

        pagina = self.client.get(reverse("loja:carrinho"))

        self.assertContains(
            pagina,
            f'<a class="btn btn-primary btn-lg w-100" href="{reverse("loja:checkout")}">Continuar para o pagamento</a>',
            html=True,
        )

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


# ------------------------------------------------------------------ HU12 Checkout (4.5.3)
DADOS_DO_VISITANTE = {
    "nome": "Marina Silva",
    "email": "marina@exemplo.com",
    "telefone": "(16) 99888-7766",
    "consentimento": "on",
    "forma_pagamento": FormaDePagamento.PIX,
}


class BaseDoCheckout(BaseDaLoja):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        call_command("criar_perfis", verbosity=0)
        cls.vendedor = User.objects.create_user("vendedor", "vendedor@exemplo.com", SENHA, is_staff=True)
        cls.vendedor.groups.add(Group.objects.get(name=PERFIL_VENDEDOR))

    def confirma(self, **campos):
        dados = {chave: valor for chave, valor in (DADOS_DO_VISITANTE | campos).items() if valor is not None}
        return self.client.post(reverse("loja:checkout"), dados)

    def mensagens(self, resposta):
        return " ".join(str(mensagem) for mensagem in resposta.context["messages"])

    def nada_foi_gravado(self, clientes=0):
        self.assertFalse(Venda.objects.online().exists())
        self.assertEqual(Cliente.objects.count(), clientes)
        self.assertFalse(MovimentoEstoque.objects.filter(venda__canal=CanalDeVenda.ONLINE).exists())


class CheckoutTests(BaseDoCheckout):
    """HU12: identificação, retirada na loja e pagamento simulado."""

    def test_carrinho_vazio_volta_ao_carrinho(self):
        resposta = self.client.get(reverse("loja:checkout"), follow=True)

        self.assertRedirects(resposta, reverse("loja:carrinho"))
        self.assertIn("Seu carrinho está vazio", self.mensagens(resposta))

    def test_item_acima_do_saldo_volta_ao_carrinho(self):
        self.adiciona(self.relogio)
        self.acao("aumentar", self.relogio)
        registrar_ajuste(self.relogio, 4, motivo="Venda no balcão antes do cliente")

        resposta = self.client.get(reverse("loja:checkout"), follow=True)

        self.assertRedirects(resposta, reverse("loja:carrinho"))
        self.assertIn("Ajuste-os antes de continuar", self.mensagens(resposta))

    def test_pagina_segue_o_prototipo(self):
        self.adiciona(self.tenis)

        pagina = self.client.get(reverse("loja:checkout"))

        self.assertEqual(pagina.status_code, 200)
        self.assertContains(
            pagina,
            '<li class="etapa ativa" aria-current="step"><span class="etapa__numero">2</span> '
            "Identificação e pagamento</li>",
            html=True,
        )
        for texto in (
            "Finalizar compra", "Identificação", "Já tem cadastro?", "Nome completo", "E-mail", "Telefone",
            "(obrigatório)", "Entrega", "Retirada na loja", "Grátis", "[Endereço da loja]",
            "[Horário de funcionamento]", "Pagamento", "Cartão de crédito", "PIX",
            "o pagamento é simulado e nenhuma cobrança real é realizada", "Resumo do pedido",
            "1 × Tênis de corrida amortecido", "R$ 349,90", "Confirmar pedido", "Voltar ao carrinho",
            "Compra segura",
        ):
            self.assertContains(pagina, texto)

    def test_endereco_e_horario_vem_das_configuracoes(self):
        self.adiciona(self.tenis)

        with self.settings(LOJA_ENDERECO="Rua das Flores, 100", LOJA_HORARIO="Seg. a sáb., 9h às 18h"):
            pagina = self.client.get(reverse("loja:checkout"))

        self.assertContains(pagina, "Rua das Flores, 100 · Seg. a sáb., 9h às 18h")

    def test_entrega_e_somente_retirada_na_loja(self):
        self.adiciona(self.tenis)

        pagina = self.client.get(reverse("loja:checkout"))

        self.assertEqual(
            set(pagina.context["formulario"].fields),
            {"nome", "email", "telefone", "consentimento", "forma_pagamento"},
        )
        self.assertEqual(pagina.content.decode().count('type="radio"'), 3)  # retirada + cartão + PIX
        self.assertNotContains(pagina, "frete")

    def test_nome_email_telefone_consentimento_e_pagamento_sao_obrigatorios(self):
        self.adiciona(self.tenis)

        resposta = self.client.post(reverse("loja:checkout"), {})

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(
            set(resposta.context["formulario"].errors),
            {"nome", "email", "telefone", "consentimento", "forma_pagamento"},
        )
        self.nada_foi_gravado()
        self.assertEqual(self.carrinho_da_sessao(), {str(self.tenis.pk): 1})

    def test_visitante_sem_consentimento_e_recusado(self):
        self.adiciona(self.tenis)

        resposta = self.confirma(consentimento=None)

        self.assertContains(resposta, "autorize o uso dos seus dados (LGPD)")
        self.assertIn("consentimento", resposta.context["formulario"].errors)
        self.nada_foi_gravado()

    def test_dinheiro_e_recusado_na_loja_online(self):
        self.adiciona(self.tenis)

        resposta = self.confirma(forma_pagamento=FormaDePagamento.DINHEIRO)

        self.assertContains(resposta, "cartão de crédito ou PIX")
        self.nada_foi_gravado()

    def test_visitante_com_email_novo_gera_cliente_sem_conta_e_pedido(self):
        self.adiciona(self.tenis)
        self.adiciona(self.relogio)

        resposta = self.confirma(email="Marina@Exemplo.com", forma_pagamento=FormaDePagamento.CARTAO)

        pedido = Venda.objects.get()
        self.assertRedirects(resposta, reverse("loja:pedido_confirmado", args=[pedido.numero]))
        self.assertEqual(pedido.canal, CanalDeVenda.ONLINE)
        self.assertEqual(pedido.status, StatusDeVenda.AGUARDANDO_RETIRADA)
        self.assertEqual(pedido.forma_pagamento, FormaDePagamento.CARTAO)
        self.assertEqual(pedido.total, Decimal("1584.46"))
        self.assertEqual(pedido.cliente.email, "marina@exemplo.com")
        self.assertIsNone(pedido.cliente.usuario)
        self.assertFalse(User.objects.filter(email__iexact="marina@exemplo.com").exists())

    def test_confirmacao_baixa_o_estoque_com_os_movimentos_ligados_ao_pedido(self):
        self.adiciona(self.tenis)
        self.adiciona(self.tenis)

        self.confirma()

        pedido = Venda.objects.get()
        self.tenis.refresh_from_db()
        self.assertEqual(self.tenis.estoque_atual, 10)
        self.assertEqual(list(MovimentoEstoque.objects.values_list("venda", "quantidade")), [(pedido.pk, 2)])

    def test_numero_do_pedido_continua_a_sequencia_do_pdv(self):
        registrar_venda_pdv(self.vendedor, [(self.relogio, 1)], FormaDePagamento.DINHEIRO)
        self.adiciona(self.tenis)

        self.confirma()

        self.assertEqual(Venda.objects.online().get().numero, 2)

    def test_carrinho_e_esvaziado_no_sucesso(self):
        self.adiciona(self.tenis)

        resposta = self.confirma()
        pagina = self.client.get(resposta.url)

        self.assertEqual(self.carrinho_da_sessao(), {})
        self.assertContains(pagina, "Carrinho (0)")

    def test_email_de_cliente_sem_conta_e_reaproveitado(self):
        self.adiciona(self.tenis)
        self.confirma()
        self.adiciona(self.relogio)

        self.confirma(email="MARINA@exemplo.com")

        self.assertEqual(Cliente.objects.count(), 1)
        self.assertEqual(set(Venda.objects.values_list("cliente", flat=True)), {Cliente.objects.get().pk})

    def test_email_de_uma_conta_exige_login_e_o_link_volta_ao_checkout(self):
        cadastrar_cliente("Marina Silva", "marina@exemplo.com", "1699999999", "SenhaForte123!")
        self.adiciona(self.tenis)

        resposta = self.confirma(email="Marina@exemplo.com")

        entrar = f"{reverse('contas:entrar')}?next=%2Floja%2Fcheckout%2F"
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("Entre na conta", resposta.context["formulario"].errors["email"][0])
        self.assertContains(resposta, f'href="{entrar}"')
        self.nada_foi_gravado(clientes=1)
        self.assertEqual(self.carrinho_da_sessao(), {str(self.tenis.pk): 1})

        login = self.client.post(entrar, {"username": "marina@exemplo.com", "password": "SenhaForte123!"})
        self.assertRedirects(login, reverse("loja:checkout"))
        self.assertEqual(self.carrinho_da_sessao(), {str(self.tenis.pk): 1})

    def test_cliente_logado_usa_o_proprio_cadastro(self):
        usuario, cliente = cadastrar_cliente("Marina Silva", "marina@exemplo.com", "16 99888-7766", "SenhaForte123!")
        self.client.force_login(usuario)
        self.adiciona(self.tenis)

        pagina = self.client.get(reverse("loja:checkout"))
        self.assertContains(pagina, "Marina Silva")
        self.assertContains(pagina, "16 99888-7766")
        self.assertContains(pagina, "autorizou o uso dos seus dados (LGPD) no cadastro")
        self.assertEqual(set(pagina.context["formulario"].fields), {"forma_pagamento"})
        self.assertNotContains(pagina, 'name="email"')

        self.client.post(reverse("loja:checkout"), {"forma_pagamento": FormaDePagamento.PIX, "email": "x@x.com"})

        self.assertEqual(Venda.objects.get().cliente, cliente)
        self.assertEqual(Cliente.objects.count(), 1)

    def test_equipe_e_bloqueada_e_volta_ao_carrinho(self):
        administrador = User.objects.create_superuser("gerente", "gerente@exemplo.com", SENHA)
        estoquista = User.objects.create_user("estoquista", "estoquista@exemplo.com", SENHA)
        estoquista.groups.add(Group.objects.get(name=PERFIL_ESTOQUISTA))

        for usuario in (administrador, self.vendedor, estoquista):
            with self.subTest(usuario=usuario.username):
                self.client.force_login(usuario)
                self.adiciona(self.tenis)

                pagina = self.client.get(reverse("loja:checkout"), follow=True)
                pedido = self.client.post(reverse("loja:checkout"), DADOS_DO_VISITANTE, follow=True)

                self.assertRedirects(pagina, reverse("loja:carrinho"))
                self.assertIn("Contas da equipe não fazem pedidos", self.mensagens(pagina))
                self.assertRedirects(pedido, reverse("loja:carrinho"))
        self.nada_foi_gravado()

    def test_conta_sem_cadastro_de_cliente_volta_ao_carrinho(self):
        self.client.force_login(User.objects.create_user("avulso", "avulso@exemplo.com", SENHA))
        self.adiciona(self.tenis)

        resposta = self.client.get(reverse("loja:checkout"), follow=True)

        self.assertRedirects(resposta, reverse("loja:carrinho"))
        self.assertIn("ainda não tem cadastro de cliente", self.mensagens(resposta))

    def test_sem_saldo_na_confirmacao_nada_e_gravado_e_o_carrinho_fica(self):
        self.adiciona(self.tenis)
        self.adiciona(self.relogio)
        self.acao("aumentar", self.relogio)
        registrar_ajuste(self.relogio, 4, motivo="Quebra")

        resposta = self.confirma()

        self.assertRedirects(resposta, reverse("loja:carrinho"), fetch_redirect_response=False)
        carrinho = self.client.get(resposta.url)
        self.assertIn("Saldo insuficiente de 100140 - Relógio de corrida GPS", self.mensagens(carrinho))
        self.nada_foi_gravado()
        self.assertEqual(ContadorDeVendas.objects.get(pk=1).proximo_numero, 1)
        self.assertEqual(self.carrinho_da_sessao(), {str(self.tenis.pk): 1, str(self.relogio.pk): 2})
        self.tenis.refresh_from_db()
        self.assertEqual(self.tenis.estoque_atual, 12)

    def test_produto_que_saiu_de_venda_antes_da_confirmacao(self):
        self.adiciona(self.tenis)
        Produto.objects.filter(pk=self.tenis.pk).update(ativo=False)

        resposta = self.confirma()

        self.assertRedirects(resposta, reverse("loja:carrinho"), fetch_redirect_response=False)
        self.assertIn("não está mais à venda", self.mensagens(self.client.get(resposta.url)))
        self.nada_foi_gravado()


class SincronizacaoEntreCanaisTests(BaseDoCheckout):
    """O PDV vende a última unidade de um produto que está no carrinho da loja online."""

    def test_confirmacao_online_e_recusada_sem_gravar_nada(self):
        capacete = cria_produto("100170", "Capacete de ciclismo", self.corrida, "229.90", saldo=1, minimo=0)
        self.adiciona(capacete)
        self.assertEqual(self.client.get(reverse("loja:checkout")).status_code, 200)

        venda_do_pdv = registrar_venda_pdv(self.vendedor, [(capacete, 1)], FormaDePagamento.DINHEIRO)
        resposta = self.confirma()

        self.assertRedirects(resposta, reverse("loja:carrinho"), fetch_redirect_response=False)
        carrinho = self.client.get(resposta.url)
        self.assertIn("Saldo insuficiente de 100170 - Capacete de ciclismo", self.mensagens(carrinho))
        capacete.refresh_from_db()
        self.assertEqual(capacete.estoque_atual, 0)
        self.assertEqual(list(Venda.objects.all()), [venda_do_pdv])
        self.assertEqual(list(MovimentoEstoque.objects.values_list("venda", flat=True)), [venda_do_pdv.pk])
        self.assertFalse(Cliente.objects.exists())
        self.assertEqual(self.carrinho_da_sessao(), {str(capacete.pk): 1})


class ConfirmacaoDoPedidoTests(BaseDoCheckout):
    """HU12: a confirmação mostra o pedido só para quem o fez."""

    def faz_pedido(self, **campos):
        self.adiciona(self.tenis)
        self.confirma(**campos)
        return Venda.objects.online().latest("numero")

    def endereco(self, pedido):
        return reverse("loja:pedido_confirmado", args=[pedido.numero])

    def test_visitante_ve_a_confirmacao_na_mesma_sessao(self):
        pedido = self.faz_pedido()

        pagina = self.client.get(self.endereco(pedido))

        self.assertEqual(pagina.status_code, 200)
        self.assertContains(
            pagina,
            '<li class="etapa ativa" aria-current="step"><span class="etapa__numero">3</span> Confirmação</li>',
            html=True,
        )
        for texto in (
            "Pedido confirmado", "#0001", "o pagamento é simulado", "Aguardando retirada", "Retirada na loja",
            "[Endereço da loja]", "PIX", "Resumo do pedido", "1 × Tênis de corrida amortecido", "R$ 349,90",
            "Continuar comprando",
        ):
            self.assertContains(pagina, texto)
        self.assertNotContains(pagina, "Ver meus pedidos")

    def test_forma_de_pagamento_aparece_como_no_checkout(self):
        pedido = self.faz_pedido(forma_pagamento=FormaDePagamento.CARTAO)

        self.assertContains(self.client.get(self.endereco(pedido)), "Cartão de crédito")

    def test_outra_sessao_recebe_404(self):
        pedido = self.faz_pedido()

        self.assertEqual(Client().get(self.endereco(pedido)).status_code, 404)

    def test_cliente_logado_dono_ve_em_outra_sessao_e_outro_cliente_nao(self):
        usuario, _ = cadastrar_cliente("Marina Silva", "marina@exemplo.com", "1699999999", "SenhaForte123!")
        outro, _ = cadastrar_cliente("Outro", "outro@exemplo.com", "1699999999", "SenhaForte123!")
        self.client.force_login(usuario)
        pedido = self.faz_pedido()

        dono = Client()
        dono.force_login(usuario)
        estranho = Client()
        estranho.force_login(outro)
        equipe = Client()
        equipe.force_login(User.objects.create_superuser("gerente", "gerente@exemplo.com", SENHA))

        self.assertEqual(dono.get(self.endereco(pedido)).status_code, 200)
        self.assertEqual(estranho.get(self.endereco(pedido)).status_code, 404)
        self.assertEqual(equipe.get(self.endereco(pedido)).status_code, 404)

    def test_numero_inexistente_ou_venda_do_pdv_dao_404(self):
        venda = registrar_venda_pdv(self.vendedor, [(self.relogio, 1)], FormaDePagamento.DINHEIRO)
        sessao = self.client.session
        sessao["pedidos_confirmados"] = [venda.numero, 999]
        sessao.save()

        for numero in (venda.numero, 999):
            with self.subTest(numero=numero):
                resposta = self.client.get(reverse("loja:pedido_confirmado", args=[numero]))
                self.assertEqual(resposta.status_code, 404)


# ------------------------------------------------------------------ HU13 Gestão de pedidos (4.5.4)
class GestaoDePedidosNoAdminTests(BaseDoCheckout):
    """HU13: lista dos pedidos online no Admin, com filtros, busca e ações que chamam os serviços."""

    def setUp(self):
        self.gerente = User.objects.create_user("gerente", "gerente@exemplo.com", SENHA, is_staff=True)
        self.gerente.groups.add(Group.objects.get(name=PERFIL_ADMINISTRADOR))
        self.client.force_login(self.gerente)

        marina = Cliente.objects.create(nome="Marina Silva", email="marina@exemplo.com", telefone="1",
                                        consentimento_em=timezone.now())
        joao = Cliente.objects.create(nome="João Souza", email="joao@exemplo.com", telefone="2",
                                      consentimento_em=timezone.now())

        self.venda_do_pdv = registrar_venda_pdv(self.vendedor, [(self.tenis, 1)], FormaDePagamento.DINHEIRO)
        self.aguardando = registrar_pedido_online(marina, [(self.tenis, 2)], FormaDePagamento.PIX)
        self.retirado = registrar_pedido_online(joao, [(self.relogio, 1)], FormaDePagamento.CARTAO)
        self.cancelado = registrar_pedido_online(joao, [(self.chuteira, 1)], FormaDePagamento.PIX)
        marcar_retirado(self.retirado, self.gerente)
        cancelar_venda(self.cancelado, self.gerente)

        self.lista = reverse("admin:loja_pedidoonline_changelist")

    def pedidos(self, **parametros):
        resposta = self.client.get(self.lista, parametros)
        self.assertEqual(resposta.status_code, 200)
        return set(venda.pk for venda in resposta.context["cl"].queryset)

    def executa_acao(self, acao, *pedidos):
        return self.client.post(
            self.lista, {"action": acao, "_selected_action": [pedido.pk for pedido in pedidos]}, follow=True
        )

    def test_lista_mostra_so_os_pedidos_online_com_as_colunas_pedidas(self):
        resposta = self.client.get(self.lista)

        self.assertEqual(self.pedidos(), {self.aguardando.pk, self.retirado.pk, self.cancelado.pk})
        self.assertEqual(
            PedidoOnlineAdmin.list_display,
            ("numero_formatado", "criado_em", "cliente", "forma_pagamento", "total", "status"),
        )
        self.assertContains(resposta, "#0002")
        self.assertContains(resposta, "Marina Silva")
        self.assertNotContains(resposta, "#0001")

    def test_filtro_por_status(self):
        self.assertEqual(self.pedidos(status=StatusDeVenda.AGUARDANDO_RETIRADA), {self.aguardando.pk})
        self.assertEqual(self.pedidos(status=StatusDeVenda.RETIRADA), {self.retirado.pk})
        self.assertEqual(self.pedidos(status=StatusDeVenda.CANCELADA), {self.cancelado.pk})

        resposta = self.client.get(self.lista)
        lista = resposta.context["cl"]
        opcoes = [escolha["display"] for escolha in lista.filter_specs[0].choices(lista)]
        self.assertEqual(opcoes, ["Todos", "Aguardando retirada", "Retirada", "Cancelada"])

    def test_filtro_por_data(self):
        antigo = timezone.now() - timedelta(days=40)
        Venda.objects.filter(pk=self.retirado.pk).update(criado_em=antigo)
        # Meia-noite de hoje no fuso da loja, como o filtro de datas do Admin envia.
        hoje = timezone.make_aware(datetime.combine(timezone.localdate(), time.min))

        self.assertEqual(
            self.pedidos(criado_em__gte=str(hoje), criado_em__lt=str(hoje + timedelta(days=1))),
            {self.aguardando.pk, self.cancelado.pk},
        )
        data_antiga = timezone.localtime(antigo).date()
        self.assertEqual(
            self.pedidos(criado_em__year=data_antiga.year, criado_em__month=data_antiga.month,
                         criado_em__day=data_antiga.day),
            {self.retirado.pk},
        )

    def test_busca_por_numero_nome_e_email(self):
        self.assertEqual(self.pedidos(q="#0002"), {self.aguardando.pk})
        self.assertEqual(self.pedidos(q="3"), {self.retirado.pk})
        self.assertEqual(self.pedidos(q="marina"), {self.aguardando.pk})
        self.assertEqual(self.pedidos(q="joao@exemplo"), {self.retirado.pk, self.cancelado.pk})
        self.assertEqual(self.pedidos(q="#0001"), set())  # venda do PDV não entra

    def test_pedido_abre_com_itens_em_linha_somente_leitura(self):
        resposta = self.client.get(reverse("admin:loja_pedidoonline_change", args=[self.aguardando.pk]))

        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, self.tenis.nome)
        self.assertContains(resposta, "Marina Silva")
        self.assertNotContains(resposta, 'name="status"')
        self.assertNotContains(resposta, 'name="itens-0-quantidade"')
        self.assertNotContains(resposta, 'name="_save"')

    def test_admin_nao_cria_nem_exclui_pedido(self):
        adicionar = self.client.get(reverse("admin:loja_pedidoonline_add"))
        excluir = self.client.get(reverse("admin:loja_pedidoonline_delete", args=[self.aguardando.pk]))

        self.assertEqual(adicionar.status_code, 403)
        self.assertEqual(excluir.status_code, 403)

    def test_acao_marcar_como_retirado_informa_os_que_nao_puderam(self):
        resposta = self.executa_acao("marcar_como_retirado", self.aguardando, self.retirado, self.cancelado)

        self.aguardando.refresh_from_db()
        self.assertEqual(self.aguardando.status, StatusDeVenda.RETIRADA)
        self.assertIsNotNone(self.aguardando.retirada_em)
        mensagens = self.mensagens(resposta)
        self.assertIn("1 pedido(s) marcado(s) como retirado(s): #0002.", mensagens)
        self.assertIn("2 pedido(s) não puderam ser alterados", mensagens)
        self.assertIn("O pedido #0003 está retirada", mensagens)
        self.assertIn("O pedido #0004 está cancelada", mensagens)

    def test_acao_cancelar_pedido_devolve_o_estoque_e_recusa_o_retirado(self):
        self.tenis.refresh_from_db()
        saldo_antes = self.tenis.estoque_atual

        resposta = self.executa_acao("cancelar_pedido", self.aguardando, self.retirado)

        self.aguardando.refresh_from_db()
        self.retirado.refresh_from_db()
        self.tenis.refresh_from_db()
        self.assertEqual(self.aguardando.status, StatusDeVenda.CANCELADA)
        self.assertEqual(self.aguardando.cancelada_por, self.gerente)
        self.assertEqual(self.tenis.estoque_atual, saldo_antes + 2)
        self.assertEqual(self.retirado.status, StatusDeVenda.RETIRADA)
        mensagens = self.mensagens(resposta)
        self.assertIn("1 pedido(s) cancelado(s); os itens voltaram ao estoque: #0002.", mensagens)
        self.assertIn("O pedido #0003 já foi retirado e não pode ser cancelado.", mensagens)

    def test_permissoes_do_pedido_ficam_com_o_administrador(self):
        def codenames(perfil):
            return set(
                Group.objects.get(name=perfil).permissions.filter(content_type__app_label="loja")
                .values_list("codename", flat=True)
            )

        self.assertEqual(
            codenames(PERFIL_ADMINISTRADOR),
            {"add_pedidoonline", "change_pedidoonline", "delete_pedidoonline", "view_pedidoonline"},
        )
        for perfil in (PERFIL_VENDEDOR, PERFIL_ESTOQUISTA, PERFIL_CLIENTE):
            self.assertEqual(codenames(perfil), set())

        self.client.force_login(self.vendedor)
        self.assertEqual(self.client.get(self.lista).status_code, 403)
