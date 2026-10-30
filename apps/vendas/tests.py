"""
Testes unitários do módulo Vendas (PDV).

Pacote 4.4: registro de venda (4.4.1) e cancelamento (4.4.2) na loja física.

Cada critério de aceite das histórias HU08 e HU09 tem pelo menos um teste. O teste de
numeração simultânea usa threads e por isso precisa de TransactionTestCase e do PostgreSQL;
no SQLite ele é pulado, porque o banco não tem bloqueio de linha.
"""
import threading
import time
from decimal import Decimal
from unittest import mock, skipUnless

from django.contrib.auth.models import Group, User
from django.db import IntegrityError, connection, connections, transaction
from django.db.models import ProtectedError
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from apps.contas.services import PERFIL_ADMINISTRADOR, PERFIL_CLIENTE, PERFIL_ESTOQUISTA, PERFIL_VENDEDOR
from apps.estoque.models import MovimentoEstoque, TipoDeMovimento
from apps.estoque.services import SaldoInsuficiente
from apps.produtos.models import Categoria, Produto

from . import services
from .models import CanalDeVenda, FormaDePagamento, ItemVenda, StatusDeVenda, Venda
from .services import (
    FormaDePagamentoInvalida,
    VendaJaCancelada,
    VendaSemItens,
    cancelar_venda,
    registrar_venda_pdv,
)

SENHA = "senha-de-teste-123"


def cria_produto(codigo="100110", nome="Tênis de corrida amortecido", preco="349.90", saldo=10, **campos):
    categoria = Categoria.objects.first() or Categoria.objects.create(nome="Corrida")

    return Produto.objects.create(
        codigo=codigo,
        nome=nome,
        categoria=categoria,
        preco=Decimal(preco),
        estoque_atual=saldo,
        **campos,
    )


def cria_usuario(nome, perfil=None, **campos):
    usuario = User.objects.create_user(
        username=nome, email=f"{nome}@exemplo.com", password=SENHA, **campos
    )
    if perfil:
        usuario.groups.add(Group.objects.get(name=perfil))
    return usuario


# ------------------------------------------------- HU08 Registro de venda no PDV (4.4.1)
class RegistrarVendaTests(TestCase):
    """HU08: montar a venda, escolher o pagamento e finalizar."""

    def setUp(self):
        self.vendedor = cria_usuario("vendedor")
        self.tenis = cria_produto(saldo=10)
        self.bola = cria_produto("100275", "Bola de futebol de campo", preco="149.90", saldo=4)

    def test_venda_grava_itens_total_canal_e_numero(self):
        venda = registrar_venda_pdv(
            self.vendedor,
            [(self.tenis, 2), (self.bola, 1)],
            FormaDePagamento.PIX,
        )

        self.assertEqual(venda.canal, CanalDeVenda.LOJA_FISICA)
        self.assertEqual(venda.status, StatusDeVenda.CONCLUIDA)
        self.assertEqual(venda.forma_pagamento, FormaDePagamento.PIX)
        self.assertEqual(venda.vendedor, self.vendedor)
        self.assertEqual(venda.itens.count(), 2)
        # 2 x 349,90 + 1 x 149,90
        self.assertEqual(venda.total, Decimal("849.70"))

    def test_total_e_a_soma_de_quantidade_vezes_preco(self):
        venda = registrar_venda_pdv(self.vendedor, [(self.bola, 3)], FormaDePagamento.DINHEIRO)
        item = venda.itens.get()

        self.assertEqual(item.preco_unitario, Decimal("149.90"))
        self.assertEqual(item.subtotal, Decimal("449.70"))
        self.assertEqual(venda.total, item.subtotal)

    def test_preco_fica_gravado_no_item_e_nao_muda_com_o_produto(self):
        venda = registrar_venda_pdv(self.vendedor, [(self.tenis, 1)], FormaDePagamento.CARTAO)

        self.tenis.preco = Decimal("999.90")
        self.tenis.save(update_fields=["preco"])

        item = venda.itens.get()
        venda.refresh_from_db()

        self.assertEqual(item.preco_unitario, Decimal("349.90"))
        self.assertEqual(venda.total, Decimal("349.90"))

    def test_forma_de_pagamento_e_obrigatoria(self):
        for forma in ("", None, "boleto"):
            with self.subTest(forma=forma):
                with self.assertRaises(FormaDePagamentoInvalida):
                    registrar_venda_pdv(self.vendedor, [(self.tenis, 1)], forma)

        self.assertFalse(Venda.objects.exists())

    def test_as_tres_formas_de_pagamento_sao_aceitas(self):
        for forma in (FormaDePagamento.DINHEIRO, FormaDePagamento.CARTAO, FormaDePagamento.PIX):
            with self.subTest(forma=forma):
                venda = registrar_venda_pdv(self.vendedor, [(self.tenis, 1)], forma)

                self.assertEqual(venda.forma_pagamento, forma)

    def test_venda_sem_itens_e_recusada(self):
        with self.assertRaises(VendaSemItens):
            registrar_venda_pdv(self.vendedor, [], FormaDePagamento.PIX)

    def test_numero_e_sequencial_e_formatado_com_quatro_digitos(self):
        primeira = registrar_venda_pdv(self.vendedor, [(self.tenis, 1)], FormaDePagamento.PIX)
        segunda = registrar_venda_pdv(self.vendedor, [(self.tenis, 1)], FormaDePagamento.PIX)

        self.assertEqual(primeira.numero, 1)
        self.assertEqual(segunda.numero, 2)
        self.assertEqual(primeira.numero_formatado, "#0001")
        self.assertEqual(str(segunda), "#0002")

    def test_numero_nao_se_repete(self):
        registrar_venda_pdv(self.vendedor, [(self.tenis, 1)], FormaDePagamento.PIX)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Venda.objects.create(
                    numero=1,
                    canal=CanalDeVenda.LOJA_FISICA,
                    forma_pagamento=FormaDePagamento.PIX,
                )

    def test_venda_baixa_o_estoque_e_liga_os_movimentos_a_ela(self):
        venda = registrar_venda_pdv(self.vendedor, [(self.tenis, 2), (self.bola, 1)], FormaDePagamento.PIX)
        self.tenis.refresh_from_db()
        self.bola.refresh_from_db()

        movimentos = MovimentoEstoque.objects.filter(venda=venda)

        self.assertEqual(self.tenis.estoque_atual, 8)
        self.assertEqual(self.bola.estoque_atual, 3)
        self.assertEqual(movimentos.count(), 2)
        self.assertEqual({m.tipo for m in movimentos}, {TipoDeMovimento.SAIDA_VENDA})
        self.assertEqual({m.usuario for m in movimentos}, {self.vendedor})
        self.assertEqual(list(venda.movimentos.order_by("id")), list(movimentos.order_by("id")))

    def test_sem_saldo_em_um_item_nada_e_gravado(self):
        with self.assertRaises(SaldoInsuficiente) as erro:
            registrar_venda_pdv(self.vendedor, [(self.tenis, 1), (self.bola, 99)], FormaDePagamento.PIX)

        self.tenis.refresh_from_db()
        self.bola.refresh_from_db()

        self.assertEqual(erro.exception.produto, self.bola)
        self.assertIn(self.bola.nome, str(erro.exception))
        self.assertEqual(self.tenis.estoque_atual, 10)
        self.assertEqual(self.bola.estoque_atual, 4)
        self.assertFalse(Venda.objects.exists())
        self.assertFalse(ItemVenda.objects.exists())
        self.assertFalse(MovimentoEstoque.objects.exists())

    def test_numero_nao_e_gasto_quando_a_venda_falha(self):
        with self.assertRaises(SaldoInsuficiente):
            registrar_venda_pdv(self.vendedor, [(self.bola, 99)], FormaDePagamento.PIX)

        venda = registrar_venda_pdv(self.vendedor, [(self.bola, 1)], FormaDePagamento.PIX)

        self.assertEqual(venda.numero, 1)

    def test_produto_vendido_nao_pode_ser_excluido(self):
        registrar_venda_pdv(self.vendedor, [(self.tenis, 1)], FormaDePagamento.PIX)

        with self.assertRaises(ProtectedError):
            with transaction.atomic():
                self.tenis.delete()


class CancelarVendaTests(TestCase):
    """HU09: cancelar devolve os itens ao estoque e registra data e usuário."""

    def setUp(self):
        self.vendedor = cria_usuario("vendedor")
        self.gerente = cria_usuario("gerente")
        self.tenis = cria_produto(saldo=10)
        self.venda = registrar_venda_pdv(self.vendedor, [(self.tenis, 3)], FormaDePagamento.CARTAO)

    def test_cancelamento_devolve_os_itens_ao_estoque(self):
        self.tenis.refresh_from_db()
        self.assertEqual(self.tenis.estoque_atual, 7)

        cancelar_venda(self.venda, self.gerente)
        self.tenis.refresh_from_db()

        self.assertEqual(self.tenis.estoque_atual, 10)

    def test_cancelamento_registra_data_usuario_e_status(self):
        cancelada = cancelar_venda(self.venda, self.gerente)

        self.assertEqual(cancelada.status, StatusDeVenda.CANCELADA)
        self.assertTrue(cancelada.cancelada)
        self.assertEqual(cancelada.cancelada_por, self.gerente)
        self.assertIsNotNone(cancelada.cancelada_em)

    def test_estorno_fica_ligado_a_venda(self):
        cancelar_venda(self.venda, self.gerente)

        estorno = MovimentoEstoque.objects.get(tipo=TipoDeMovimento.ESTORNO)

        self.assertEqual(estorno.venda, self.venda)
        self.assertEqual(estorno.quantidade, 3)
        self.assertEqual(estorno.usuario, self.gerente)

    def test_venda_cancelada_nao_e_cancelada_de_novo(self):
        cancelar_venda(self.venda, self.gerente)

        with self.assertRaises(VendaJaCancelada):
            cancelar_venda(self.venda, self.gerente)

        self.tenis.refresh_from_db()
        self.assertEqual(self.tenis.estoque_atual, 10)
        self.assertEqual(MovimentoEstoque.objects.filter(tipo=TipoDeMovimento.ESTORNO).count(), 1)

    def test_venda_cancelada_sai_de_validas(self):
        outra = registrar_venda_pdv(self.vendedor, [(self.tenis, 1)], FormaDePagamento.PIX)

        cancelar_venda(self.venda, self.gerente)

        self.assertEqual(list(Venda.objects.validas()), [outra])
        self.assertEqual(Venda.objects.count(), 2)


@skipUnless(connection.vendor == "postgresql", "O bloqueio de linha exige PostgreSQL.")
class NumeracaoSimultaneaTests(TransactionTestCase):
    """HU08: o número é único e sequencial mesmo com duas vendas ao mesmo tempo."""

    def test_duas_vendas_simultaneas_recebem_numeros_diferentes(self):
        """
        Segura a primeira venda depois de ela pegar o número e antes de confirmar, enquanto a
        segunda tenta vender. Sem o bloqueio do contador, as duas leriam o mesmo número e a
        segunda esbarraria na restrição de unicidade.
        """
        vendedor = cria_usuario("vendedor")
        categoria = Categoria.objects.create(nome="Corrida")
        produto = Produto.objects.create(
            codigo="100110",
            nome="Tênis de corrida amortecido",
            categoria=categoria,
            preco=Decimal("349.90"),
            estoque_atual=10,
        )

        primeira_pegou_numero = threading.Event()
        segunda_tentou = threading.Event()
        resultados = []
        baixar_original = services.baixar_itens

        def baixar_segurando_a_primeira(*args, **kwargs):
            if not primeira_pegou_numero.is_set():
                primeira_pegou_numero.set()
                segunda_tentou.wait(timeout=10)
                time.sleep(0.2)   # tempo de a segunda thread chegar ao contador
            return baixar_original(*args, **kwargs)

        def vende(esperar_a_primeira):
            try:
                if esperar_a_primeira:
                    primeira_pegou_numero.wait(timeout=10)
                    segunda_tentou.set()
                venda = registrar_venda_pdv(vendedor, [(produto, 1)], FormaDePagamento.PIX)
                resultados.append(venda.numero)
            except Exception as erro:                       # noqa: BLE001 - o teste reporta
                resultados.append(f"erro: {erro}")
            finally:
                connections.close_all()

        with mock.patch.object(services, "baixar_itens", baixar_segurando_a_primeira):
            threads = [
                threading.Thread(target=vende, args=(False,)),
                threading.Thread(target=vende, args=(True,)),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)

        # set() em vez de sorted(): se uma thread falhar, a lista vem com texto e número.
        self.assertEqual(set(resultados), {1, 2}, f"resultados: {resultados}")
        self.assertEqual(Venda.objects.count(), 2)


# ------------------------------------------------------------------ Tela do PDV
class PdvTests(TestCase):
    """A tela do balcão: busca, venda atual, pagamento e últimas vendas."""

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command

        call_command("criar_perfis", verbosity=0)
        cls.vendedor = cria_usuario("vendedor", PERFIL_VENDEDOR)
        cls.administrador = cria_usuario("gerente", PERFIL_ADMINISTRADOR)
        cls.estoquista = cria_usuario("estoquista", PERFIL_ESTOQUISTA)
        cls.cliente = cria_usuario("cliente", PERFIL_CLIENTE)

    def setUp(self):
        self.endereco = reverse("vendas:pdv")
        self.tenis = cria_produto(saldo=10)
        self.camisa = cria_produto("100245", "Camisa de futebol listrada", preco="129.90", saldo=2)
        self.camisa.estoque_minimo = 5
        self.camisa.save(update_fields=["estoque_minimo"])
        self.esgotado = cria_produto("100480", "Capacete de ciclismo", preco="229.90", saldo=0)
        self.client.force_login(self.vendedor)

    # ---------------------------------------------------------- acesso
    def test_vendedor_e_administrador_entram(self):
        for usuario in (self.vendedor, self.administrador):
            with self.subTest(usuario=usuario.username):
                self.client.force_login(usuario)

                resposta = self.client.get(self.endereco)

                self.assertEqual(resposta.status_code, 200)
                self.assertTemplateUsed(resposta, "vendas/pdv.html")

    def test_estoquista_e_cliente_recebem_403(self):
        for usuario in (self.estoquista, self.cliente):
            with self.subTest(usuario=usuario.username):
                self.client.force_login(usuario)

                resposta = self.client.get(self.endereco)

                self.assertEqual(resposta.status_code, 403)

    def test_visitante_vai_para_a_tela_de_entrada(self):
        self.client.logout()

        resposta = self.client.get(self.endereco)

        self.assertRedirects(resposta, f"{reverse('contas:entrar')}?next={self.endereco}")

    # ---------------------------------------------------------- busca
    def test_busca_por_nome(self):
        resposta = self.client.get(self.endereco, {"busca": "camisa"})

        self.assertEqual(list(resposta.context["resultados"]), [self.camisa])
        self.assertContains(resposta, "100245")
        self.assertContains(resposta, "129,90")

    def test_busca_por_codigo(self):
        resposta = self.client.get(self.endereco, {"busca": "100110"})

        self.assertEqual(list(resposta.context["resultados"]), [self.tenis])

    def test_busca_mostra_os_selos_de_estoque(self):
        resposta = self.client.get(self.endereco)

        self.assertContains(resposta, "Sem estoque")
        self.assertContains(resposta, "Estoque baixo")

    def test_produto_desativado_nao_aparece(self):
        self.tenis.ativo = False
        self.tenis.save(update_fields=["ativo"])

        resposta = self.client.get(self.endereco)

        self.assertNotIn(self.tenis, resposta.context["resultados"])

    # ---------------------------------------------------------- venda atual
    def test_adicionar_produto_entra_na_venda_atual(self):
        self.client.post(self.endereco, {"acao": "adicionar", "produto": self.tenis.pk})

        resposta = self.client.get(self.endereco)
        linha = resposta.context["linhas"][0]

        self.assertEqual(linha["produto"], self.tenis)
        self.assertEqual(linha["quantidade"], 1)
        self.assertEqual(resposta.context["total"], Decimal("349.90"))

    def test_aumentar_e_diminuir_a_quantidade(self):
        self.client.post(self.endereco, {"acao": "adicionar", "produto": self.tenis.pk})
        self.client.post(self.endereco, {"acao": "aumentar", "produto": self.tenis.pk})

        resposta = self.client.get(self.endereco)
        self.assertEqual(resposta.context["linhas"][0]["quantidade"], 2)
        self.assertEqual(resposta.context["total"], Decimal("699.80"))

        self.client.post(self.endereco, {"acao": "diminuir", "produto": self.tenis.pk})

        resposta = self.client.get(self.endereco)
        self.assertEqual(resposta.context["linhas"][0]["quantidade"], 1)

    def test_diminuir_ate_zero_tira_o_item(self):
        self.client.post(self.endereco, {"acao": "adicionar", "produto": self.tenis.pk})
        self.client.post(self.endereco, {"acao": "diminuir", "produto": self.tenis.pk})

        self.assertEqual(self.client.get(self.endereco).context["linhas"], [])

    def test_remover_item_e_limpar_venda(self):
        self.client.post(self.endereco, {"acao": "adicionar", "produto": self.tenis.pk})
        self.client.post(self.endereco, {"acao": "adicionar", "produto": self.camisa.pk})

        self.client.post(self.endereco, {"acao": "remover", "produto": self.tenis.pk})
        self.assertEqual(len(self.client.get(self.endereco).context["linhas"]), 1)

        self.client.post(self.endereco, {"acao": "limpar"})
        self.assertEqual(self.client.get(self.endereco).context["linhas"], [])

    def test_quantidade_nao_passa_do_saldo(self):
        for _ in range(3):
            resposta = self.client.post(
                self.endereco, {"acao": "adicionar", "produto": self.camisa.pk}, follow=True
            )

        linha = self.client.get(self.endereco).context["linhas"][0]

        self.assertEqual(linha["quantidade"], 2)   # o saldo da camisa é 2
        self.assertIn("não pode passar disso", self._mensagens(resposta))

    def test_produto_sem_estoque_nao_entra_na_venda(self):
        resposta = self.client.post(
            self.endereco, {"acao": "adicionar", "produto": self.esgotado.pk}, follow=True
        )

        self.assertEqual(self.client.get(self.endereco).context["linhas"], [])
        self.assertIn("0 em estoque", self._mensagens(resposta))

    def test_acao_com_produto_invalido_da_404(self):
        resposta = self.client.post(self.endereco, {"acao": "adicionar", "produto": "abacaxi"})

        self.assertEqual(resposta.status_code, 404)

    def test_acao_desconhecida_avisa(self):
        resposta = self.client.post(self.endereco, {"acao": "dançar"}, follow=True)

        self.assertIn("Ação desconhecida.", self._mensagens(resposta))

    # ---------------------------------------------------------- finalizar
    def test_finalizar_venda_grava_e_confirma_com_o_numero(self):
        self.client.post(self.endereco, {"acao": "adicionar", "produto": self.tenis.pk})

        resposta = self.client.post(self.endereco, {
            "acao": "finalizar",
            "forma_pagamento": FormaDePagamento.DINHEIRO,
        }, follow=True)

        venda = Venda.objects.get()
        self.tenis.refresh_from_db()

        self.assertEqual(venda.vendedor, self.vendedor)
        self.assertEqual(venda.total, Decimal("349.90"))
        self.assertEqual(self.tenis.estoque_atual, 9)
        self.assertIn("#0001", self._mensagens(resposta))
        self.assertEqual(resposta.context["linhas"], [])   # a venda atual foi limpa

    def test_finalizar_sem_forma_de_pagamento_avisa_e_mantem_a_venda(self):
        self.client.post(self.endereco, {"acao": "adicionar", "produto": self.tenis.pk})

        resposta = self.client.post(self.endereco, {"acao": "finalizar", "forma_pagamento": ""}, follow=True)

        self.assertFalse(Venda.objects.exists())
        self.assertIn("Escolha a forma de pagamento.", self._mensagens(resposta))
        self.assertEqual(len(resposta.context["linhas"]), 1)

    def test_finalizar_venda_vazia_avisa(self):
        resposta = self.client.post(self.endereco, {
            "acao": "finalizar",
            "forma_pagamento": FormaDePagamento.PIX,
        }, follow=True)

        self.assertIn("Adicione pelo menos um item", self._mensagens(resposta))

    def test_finalizar_sem_saldo_avisa_qual_item_faltou(self):
        self.client.post(self.endereco, {"acao": "adicionar", "produto": self.camisa.pk})

        # Alguém levou as camisas entre a montagem e a finalização da venda.
        Produto.objects.filter(pk=self.camisa.pk).update(estoque_atual=0)

        resposta = self.client.post(self.endereco, {
            "acao": "finalizar",
            "forma_pagamento": FormaDePagamento.PIX,
        }, follow=True)

        self.assertFalse(Venda.objects.exists())
        self.assertIn(self.camisa.nome, self._mensagens(resposta))
        self.assertIn("Saldo insuficiente", self._mensagens(resposta))

    def test_busca_continua_depois_de_uma_acao(self):
        resposta = self.client.post(
            self.endereco,
            {"acao": "adicionar", "produto": self.camisa.pk, "busca": "camisa"},
        )

        self.assertRedirects(resposta, f"{self.endereco}?busca=camisa")

    # ---------------------------------------------------------- últimas vendas
    def test_ultimas_vendas_mostra_as_cinco_mais_recentes(self):
        for _ in range(6):
            registrar_venda_pdv(self.vendedor, [(self.tenis, 1)], FormaDePagamento.PIX)

        resposta = self.client.get(self.endereco)
        numeros = [venda.numero for venda in resposta.context["ultimas_vendas"]]

        self.assertEqual(numeros, [6, 5, 4, 3, 2])

    def test_cancelar_pela_tela_devolve_o_estoque_e_confirma(self):
        venda = registrar_venda_pdv(self.vendedor, [(self.tenis, 2)], FormaDePagamento.PIX)

        resposta = self.client.post(self.endereco, {"acao": "cancelar", "venda": venda.pk}, follow=True)
        venda.refresh_from_db()
        self.tenis.refresh_from_db()

        self.assertTrue(venda.cancelada)
        self.assertEqual(venda.cancelada_por, self.vendedor)
        self.assertEqual(self.tenis.estoque_atual, 10)
        self.assertIn("cancelada", self._mensagens(resposta))

    def test_cancelar_duas_vezes_avisa(self):
        venda = registrar_venda_pdv(self.vendedor, [(self.tenis, 1)], FormaDePagamento.PIX)
        self.client.post(self.endereco, {"acao": "cancelar", "venda": venda.pk})

        resposta = self.client.post(self.endereco, {"acao": "cancelar", "venda": venda.pk}, follow=True)

        self.assertIn("já está cancelada", self._mensagens(resposta))

    def test_tela_so_oferece_cancelar_nas_vendas_concluidas(self):
        venda = registrar_venda_pdv(self.vendedor, [(self.tenis, 1)], FormaDePagamento.PIX)

        com_botao = self.client.get(self.endereco)
        self.assertContains(com_botao, "Cancelar venda")

        cancelar_venda(venda, self.vendedor)
        sem_botao = self.client.get(self.endereco)

        self.assertNotContains(sem_botao, "Cancelar venda")
        self.assertContains(sem_botao, "Cancelada")

    def test_cancelar_venda_inexistente_da_404(self):
        resposta = self.client.post(self.endereco, {"acao": "cancelar", "venda": 999})

        self.assertEqual(resposta.status_code, 404)

    def _mensagens(self, resposta):
        return " ".join(str(mensagem) for mensagem in resposta.context["messages"])


# ------------------------------------------------------------------ Modelo e Admin
class ModeloDeVendaTests(TestCase):
    def setUp(self):
        self.vendedor = cria_usuario("vendedor")
        self.tenis = cria_produto(saldo=10)
        self.venda = registrar_venda_pdv(self.vendedor, [(self.tenis, 2)], FormaDePagamento.PIX)

    def test_texto_do_item(self):
        self.assertEqual(str(self.venda.itens.get()), "2 x Tênis de corrida amortecido")

    def test_banco_recusa_item_com_quantidade_ou_preco_zerado(self):
        for campos in ({"quantidade": 0}, {"preco_unitario": Decimal("0.00")}):
            with self.subTest(campos=campos):
                dados = {"quantidade": 1, "preco_unitario": Decimal("10.00")} | campos
                with self.assertRaises(IntegrityError):
                    with transaction.atomic():
                        ItemVenda.objects.create(venda=self.venda, produto=self.tenis, **dados)

    def test_banco_recusa_total_negativo(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Venda.objects.filter(pk=self.venda.pk).update(total=Decimal("-1.00"))

    def test_venda_com_movimento_nao_pode_ser_excluida(self):
        with self.assertRaises(ProtectedError):
            with transaction.atomic():
                self.venda.delete()


class VendaAdminTests(TestCase):
    """Venda é histórico: no Admin ela só é consultada."""

    def setUp(self):
        self.vendedor = cria_usuario("vendedor")
        self.tenis = cria_produto(saldo=10)
        self.venda = registrar_venda_pdv(self.vendedor, [(self.tenis, 1)], FormaDePagamento.CARTAO)
        self.client.force_login(User.objects.create_superuser("admin", "admin@exemplo.com", SENHA))

    def test_lista_abre_com_filtros_e_busca_por_numero(self):
        from .admin import VendaAdmin

        resposta = self.client.get(reverse("admin:vendas_venda_changelist"), {"q": "1"})

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(VendaAdmin.list_filter, ("canal", "status", "forma_pagamento", "criado_em"))
        self.assertEqual(VendaAdmin.search_fields, ("numero",))
        self.assertEqual(list(resposta.context["cl"].queryset), [self.venda])

    def test_venda_abre_so_para_leitura_com_os_itens_em_linha(self):
        resposta = self.client.get(reverse("admin:vendas_venda_change", args=[self.venda.pk]))

        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, self.tenis.nome)
        self.assertNotContains(resposta, 'name="total"')

    def test_admin_nao_deixa_criar_nem_excluir_venda(self):
        adicionar = self.client.get(reverse("admin:vendas_venda_add"))
        excluir = self.client.get(reverse("admin:vendas_venda_delete", args=[self.venda.pk]))

        self.assertEqual(adicionar.status_code, 403)
        self.assertEqual(excluir.status_code, 403)
