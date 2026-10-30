"""
Testes unitários do módulo Estoque.

Pacote 4.3: entradas (4.3.1), baixa e sincronização entre canais (4.3.2), estoque mínimo e
alertas (4.3.3).

Cada critério de aceite das histórias HU05, HU06 e HU07 tem pelo menos um teste. O teste de
concorrência usa threads de verdade e por isso precisa de TransactionTestCase e do
PostgreSQL; no SQLite ele é pulado, porque o banco não tem bloqueio de linha.
"""
import threading
import time
from decimal import Decimal
from unittest import mock, skipUnless

from django.contrib.auth.models import Group, User
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.db import IntegrityError, connection, connections, transaction
from django.db.models import ProtectedError
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from apps.contas.services import PERFIL_ADMINISTRADOR, PERFIL_CLIENTE, PERFIL_ESTOQUISTA, PERFIL_VENDEDOR
from apps.produtos.models import Categoria, Produto

from . import services
from .models import MovimentoEstoque, TipoDeMovimento
from .services import (
    ErroDeEstoque,
    MotivoObrigatorio,
    QuantidadeInvalida,
    SaldoInsuficiente,
    baixar_itens,
    estornar_itens,
    produtos_em_alerta,
    registrar_ajuste,
    registrar_entrada,
)

SENHA = "senha-de-teste-123"


def cria_produto(codigo="100110", nome="Tênis de corrida amortecido", categoria=None, **campos):
    """Produto de teste; por padrão sem saldo, para cada teste dizer o saldo que quer."""
    categoria = categoria or Categoria.objects.first() or Categoria.objects.create(nome="Corrida")
    dados = {"preco": Decimal("349.90"), "estoque_atual": 0, "estoque_minimo": 0}
    dados.update(campos)

    return Produto.objects.create(codigo=codigo, nome=nome, categoria=categoria, **dados)


def cria_usuario(nome, perfil=None, **campos):
    usuario = User.objects.create_user(
        username=nome, email=f"{nome}@exemplo.com", password=SENHA, **campos
    )
    if perfil:
        usuario.groups.add(Group.objects.get(name=perfil))
    return usuario


# ------------------------------------------------------ HU05 Registro de entradas (4.3.1)
class RegistrarEntradaTests(TestCase):
    """HU05: cada entrada aumenta o saldo e gera um movimento, na mesma operação."""

    def setUp(self):
        self.produto = cria_produto(estoque_atual=10)
        self.estoquista = cria_usuario("estoquista")

    def test_entrada_aumenta_o_saldo_e_grava_o_movimento(self):
        movimento = registrar_entrada(self.produto, 5, usuario=self.estoquista, motivo="Compra 123")
        self.produto.refresh_from_db()

        self.assertEqual(self.produto.estoque_atual, 15)
        self.assertEqual(movimento.tipo, TipoDeMovimento.ENTRADA)
        self.assertEqual(movimento.quantidade, 5)
        self.assertEqual(movimento.saldo_apos, 15)
        self.assertEqual(movimento.usuario, self.estoquista)
        self.assertEqual(movimento.motivo, "Compra 123")
        self.assertIsNotNone(movimento.criado_em)

    def test_cada_entrada_gera_um_movimento(self):
        registrar_entrada(self.produto, 2)
        registrar_entrada(self.produto, 3)
        self.produto.refresh_from_db()

        self.assertEqual(self.produto.estoque_atual, 15)
        self.assertEqual(self.produto.movimentos.count(), 2)
        self.assertEqual(
            list(self.produto.movimentos.values_list("saldo_apos", flat=True).order_by("id")),
            [12, 15],
        )

    def test_quantidade_precisa_ser_inteiro_maior_que_zero(self):
        for quantidade in (0, -3, 1.5, "2", None, True):
            with self.subTest(quantidade=quantidade):
                with self.assertRaises(QuantidadeInvalida):
                    registrar_entrada(self.produto, quantidade)

        self.produto.refresh_from_db()
        self.assertEqual(self.produto.estoque_atual, 10)
        self.assertFalse(MovimentoEstoque.objects.exists())

    def test_saldo_e_movimento_caem_na_mesma_operacao(self):
        """Se a gravação do movimento falhar, o saldo não pode ficar alterado."""
        with mock.patch.object(MovimentoEstoque.objects, "create", side_effect=RuntimeError("falhou")):
            with self.assertRaises(RuntimeError):
                registrar_entrada(self.produto, 5)

        self.produto.refresh_from_db()
        self.assertEqual(self.produto.estoque_atual, 10)
        self.assertFalse(MovimentoEstoque.objects.exists())

    def test_produto_que_sumiu_do_banco_nao_movimenta(self):
        Produto.objects.filter(pk=self.produto.pk).delete()

        with self.assertRaises(ErroDeEstoque):
            registrar_entrada(self.produto, 1)


class RegistrarAjusteTests(TestCase):
    """HU05: a saída manual exige motivo e não pode deixar o saldo negativo."""

    def setUp(self):
        self.produto = cria_produto(estoque_atual=10)

    def test_ajuste_diminui_o_saldo_e_guarda_o_motivo(self):
        movimento = registrar_ajuste(self.produto, 4, motivo="Quebra na prateleira")
        self.produto.refresh_from_db()

        self.assertEqual(self.produto.estoque_atual, 6)
        self.assertEqual(movimento.tipo, TipoDeMovimento.AJUSTE)
        self.assertEqual(movimento.saldo_apos, 6)
        self.assertEqual(movimento.motivo, "Quebra na prateleira")

    def test_ajuste_sem_motivo_e_recusado(self):
        for motivo in ("", "   ", None):
            with self.subTest(motivo=motivo):
                with self.assertRaises(MotivoObrigatorio):
                    registrar_ajuste(self.produto, 1, motivo=motivo)

        self.produto.refresh_from_db()
        self.assertEqual(self.produto.estoque_atual, 10)
        self.assertFalse(MovimentoEstoque.objects.exists())

    def test_ajuste_nao_deixa_o_saldo_negativo(self):
        with self.assertRaises(SaldoInsuficiente) as erro:
            registrar_ajuste(self.produto, 11, motivo="Conferência")

        self.produto.refresh_from_db()
        self.assertEqual(self.produto.estoque_atual, 10)
        self.assertEqual(erro.exception.produto, self.produto)
        self.assertFalse(MovimentoEstoque.objects.exists())

    def test_ajuste_pode_zerar_o_saldo(self):
        registrar_ajuste(self.produto, 10, motivo="Devolução ao fornecedor")
        self.produto.refresh_from_db()

        self.assertEqual(self.produto.estoque_atual, 0)


# ---------------------------------------- HU06 Baixa automática e sincronização (4.3.2)
class BaixarItensTests(TestCase):
    """HU06: a baixa só acontece se houver saldo para todos os itens."""

    def setUp(self):
        self.camisa = cria_produto("100245", "Camisa de futebol listrada", estoque_atual=5)
        self.bola = cria_produto("100275", "Bola de futebol de campo", estoque_atual=3)
        self.vendedor = cria_usuario("vendedor")

    def test_baixa_desconta_todos_os_itens_e_grava_um_movimento_por_produto(self):
        movimentos = baixar_itens([(self.camisa, 2), (self.bola, 1)], usuario=self.vendedor)
        self.camisa.refresh_from_db()
        self.bola.refresh_from_db()

        self.assertEqual(self.camisa.estoque_atual, 3)
        self.assertEqual(self.bola.estoque_atual, 2)
        self.assertEqual(len(movimentos), 2)
        self.assertEqual({m.tipo for m in movimentos}, {TipoDeMovimento.SAIDA_VENDA})
        self.assertEqual({m.usuario for m in movimentos}, {self.vendedor})

    def test_sem_saldo_em_um_item_nada_e_baixado(self):
        with self.assertRaises(SaldoInsuficiente):
            baixar_itens([(self.camisa, 2), (self.bola, 99)])

        self.camisa.refresh_from_db()
        self.bola.refresh_from_db()

        self.assertEqual(self.camisa.estoque_atual, 5)
        self.assertEqual(self.bola.estoque_atual, 3)
        self.assertFalse(MovimentoEstoque.objects.exists())

    def test_a_excecao_diz_qual_item_esta_indisponivel(self):
        with self.assertRaises(SaldoInsuficiente) as erro:
            baixar_itens([(self.bola, 99)])

        excecao = erro.exception
        self.assertEqual(excecao.produto, self.bola)
        self.assertEqual(excecao.solicitado, 99)
        self.assertEqual(excecao.disponivel, 3)
        self.assertIn(self.bola.codigo, str(excecao))
        self.assertIn(self.bola.nome, str(excecao))

    def test_baixa_pode_zerar_o_saldo(self):
        baixar_itens([(self.bola, 3)])
        self.bola.refresh_from_db()

        self.assertEqual(self.bola.estoque_atual, 0)

    def test_produto_repetido_soma_as_quantidades(self):
        baixar_itens([(self.camisa, 2), (self.camisa, 3)])
        self.camisa.refresh_from_db()

        self.assertEqual(self.camisa.estoque_atual, 0)
        self.assertEqual(self.camisa.movimentos.count(), 1)

    def test_produto_repetido_passando_do_saldo_e_recusado(self):
        with self.assertRaises(SaldoInsuficiente):
            baixar_itens([(self.camisa, 3), (self.camisa, 3)])

        self.camisa.refresh_from_db()
        self.assertEqual(self.camisa.estoque_atual, 5)

    def test_lista_vazia_e_recusada(self):
        with self.assertRaises(ErroDeEstoque):
            baixar_itens([])


class EstornarItensTests(TestCase):
    """HU06: o estorno devolve as quantidades ao estoque."""

    def setUp(self):
        self.camisa = cria_produto("100245", "Camisa de futebol listrada", estoque_atual=5)
        self.bola = cria_produto("100275", "Bola de futebol de campo", estoque_atual=3)

    def test_estorno_devolve_as_quantidades(self):
        itens = [(self.camisa, 2), (self.bola, 1)]
        baixar_itens(itens)

        movimentos = estornar_itens(itens, motivo="Venda cancelada")
        self.camisa.refresh_from_db()
        self.bola.refresh_from_db()

        self.assertEqual(self.camisa.estoque_atual, 5)
        self.assertEqual(self.bola.estoque_atual, 3)
        self.assertEqual({m.tipo for m in movimentos}, {TipoDeMovimento.ESTORNO})

    def test_estorno_fica_no_historico_do_produto(self):
        baixar_itens([(self.camisa, 2)])
        estornar_itens([(self.camisa, 2)])

        tipos = list(self.camisa.movimentos.order_by("id").values_list("tipo", flat=True))

        self.assertEqual(tipos, [TipoDeMovimento.SAIDA_VENDA, TipoDeMovimento.ESTORNO])


@skipUnless(connection.vendor == "postgresql", "O bloqueio de linha exige PostgreSQL.")
class ConcorrenciaTests(TransactionTestCase):
    """HU06: em duas vendas simultâneas da última unidade, apenas uma é concluída."""

    def test_duas_baixas_simultaneas_da_ultima_unidade(self):
        """
        Força as duas baixas a se cruzarem de verdade.

        Só disparar duas threads ao mesmo tempo não serve: cada baixa é rápida demais e uma
        termina antes de a outra começar, então o teste passaria mesmo sem select_for_update.
        Por isso a primeira thread é segurada depois de bloquear o produto e antes de gravar,
        enquanto a segunda tenta a mesma baixa. Com o bloqueio, a segunda espera a primeira
        confirmar e só então lê o saldo — já zerado.
        """
        categoria = Categoria.objects.create(nome="Futebol")
        produto = Produto.objects.create(
            codigo="100250",
            nome="Chuteira society",
            preco=Decimal("279.90"),
            categoria=categoria,
            estoque_atual=1,
        )

        primeira_bloqueou = threading.Event()
        segunda_tentou = threading.Event()
        resultados = []
        aplica_original = services._aplica

        def aplica_segurando_a_primeira(*args, **kwargs):
            if not primeira_bloqueou.is_set():
                primeira_bloqueou.set()
                segunda_tentou.wait(timeout=10)
                time.sleep(0.2)   # tempo de a segunda thread chegar ao banco
            return aplica_original(*args, **kwargs)

        def tenta_vender(esperar_a_primeira):
            try:
                if esperar_a_primeira:
                    primeira_bloqueou.wait(timeout=10)
                    segunda_tentou.set()
                baixar_itens([(produto, 1)])
                resultados.append("concluida")
            except SaldoInsuficiente:
                resultados.append("recusada")
            finally:
                connections.close_all()

        with mock.patch.object(services, "_aplica", aplica_segurando_a_primeira):
            threads = [
                threading.Thread(target=tenta_vender, args=(False,)),
                threading.Thread(target=tenta_vender, args=(True,)),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)

        produto.refresh_from_db()

        self.assertEqual(len(resultados), 2, "alguma das threads não terminou")
        self.assertEqual(resultados.count("concluida"), 1)
        self.assertEqual(resultados.count("recusada"), 1)
        self.assertEqual(produto.estoque_atual, 0)
        self.assertEqual(MovimentoEstoque.objects.count(), 1)


# -------------------------------------------- HU07 Estoque mínimo e alertas (4.3.3)
class AlertasTests(TestCase):
    """HU07: produto com saldo igual ou abaixo do mínimo entra no painel de alertas."""

    def setUp(self):
        self.abaixo = cria_produto("100245", "Camisa de futebol listrada", estoque_atual=2, estoque_minimo=5)
        self.no_limite = cria_produto("100250", "Chuteira society", estoque_atual=4, estoque_minimo=4)
        self.zerado = cria_produto("100480", "Capacete de ciclismo", estoque_atual=0, estoque_minimo=2)
        self.tranquilo = cria_produto("100512", "Garrafa térmica 750 ml", estoque_atual=25, estoque_minimo=8)

    def test_alerta_traz_quem_esta_abaixo_ou_no_limite_do_minimo(self):
        em_alerta = list(produtos_em_alerta())

        self.assertIn(self.abaixo, em_alerta)
        self.assertIn(self.no_limite, em_alerta)
        self.assertIn(self.zerado, em_alerta)
        self.assertNotIn(self.tranquilo, em_alerta)

    def test_alerta_mostra_o_saldo_atual_e_o_minimo(self):
        primeiro = produtos_em_alerta().first()

        self.assertEqual(primeiro, self.zerado)
        self.assertEqual(primeiro.estoque_atual, 0)
        self.assertEqual(primeiro.estoque_minimo, 2)

    def test_produto_desativado_fica_fora_do_alerta(self):
        self.abaixo.ativo = False
        self.abaixo.save(update_fields=["ativo"])

        self.assertNotIn(self.abaixo, produtos_em_alerta())

    def test_baixa_que_cruza_o_minimo_coloca_o_produto_em_alerta(self):
        self.assertNotIn(self.tranquilo, produtos_em_alerta())

        baixar_itens([(self.tranquilo, 20)])

        self.assertIn(self.tranquilo, produtos_em_alerta())


# ------------------------------------------------------------------ Painel de estoque
class PainelTests(TestCase):
    """O painel em /estoque/ é do estoquista e do administrador."""

    @classmethod
    def setUpTestData(cls):
        call_command("criar_perfis", verbosity=0)
        cls.estoquista = cria_usuario("estoquista", PERFIL_ESTOQUISTA)
        cls.administrador = cria_usuario("gerente", PERFIL_ADMINISTRADOR)
        cls.vendedor = cria_usuario("vendedor", PERFIL_VENDEDOR)
        cls.cliente = cria_usuario("cliente", PERFIL_CLIENTE)

    def setUp(self):
        self.camisa = cria_produto("100245", "Camisa de futebol listrada", estoque_atual=2, estoque_minimo=5)
        self.garrafa = cria_produto("100512", "Garrafa térmica 750 ml", estoque_atual=25, estoque_minimo=8)
        self.zerado = cria_produto("100480", "Capacete de ciclismo", estoque_atual=0, estoque_minimo=2)
        self.endereco = reverse("estoque:painel")

    def test_estoquista_e_administrador_entram(self):
        for usuario in (self.estoquista, self.administrador):
            with self.subTest(usuario=usuario.username):
                self.client.force_login(usuario)

                resposta = self.client.get(self.endereco)

                self.assertEqual(resposta.status_code, 200)
                self.assertTemplateUsed(resposta, "estoque/painel.html")

    def test_vendedor_e_cliente_recebem_403(self):
        for usuario in (self.vendedor, self.cliente):
            with self.subTest(usuario=usuario.username):
                self.client.force_login(usuario)

                resposta = self.client.get(self.endereco)

                self.assertEqual(resposta.status_code, 403)

    def test_visitante_vai_para_a_tela_de_entrada(self):
        resposta = self.client.get(self.endereco)

        self.assertRedirects(resposta, f"{reverse('contas:entrar')}?next={self.endereco}")

    def test_painel_mostra_alertas_saldo_e_sem_estoque(self):
        self.client.force_login(self.estoquista)

        resposta = self.client.get(self.endereco)

        self.assertEqual(list(resposta.context["alertas"]), [self.zerado, self.camisa])
        self.assertIn(self.garrafa, resposta.context["produtos"])
        self.assertContains(resposta, "Sem estoque")
        self.assertContains(resposta, "Movimentar estoque")
        self.assertContains(resposta, "Produtos abaixo do mínimo")

    def test_botao_de_tirar_uma_unidade_fica_desabilitado_sem_saldo(self):
        self.client.force_login(self.estoquista)

        conteudo = self.client.get(self.endereco).content.decode()
        trecho = conteudo.split(f'aria-label="Retirar uma unidade de {self.zerado.nome}"')[1]

        self.assertIn("disabled", trecho.split(">")[0])

    def test_entrada_pelo_formulario_atualiza_o_saldo_e_confirma(self):
        self.client.force_login(self.estoquista)

        resposta = self.client.post(self.endereco, {
            "produto": self.camisa.pk,
            "tipo": "entrada",
            "quantidade": 10,
            "motivo": "Compra do fornecedor",
        }, follow=True)
        self.camisa.refresh_from_db()

        self.assertEqual(self.camisa.estoque_atual, 12)
        self.assertEqual(self.camisa.movimentos.get().usuario, self.estoquista)
        self.assertIn("Entrada de 10 unidade(s)", self._mensagens(resposta))

    def test_saida_pelo_formulario_exige_motivo(self):
        self.client.force_login(self.estoquista)

        resposta = self.client.post(self.endereco, {
            "produto": self.camisa.pk,
            "tipo": "saida",
            "quantidade": 1,
            "motivo": "",
        })
        self.camisa.refresh_from_db()

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(self.camisa.estoque_atual, 2)
        self.assertFormError(resposta.context["formulario"], "motivo", "A saída manual exige um motivo.")

    def test_saida_maior_que_o_saldo_avisa_na_tela(self):
        self.client.force_login(self.estoquista)

        resposta = self.client.post(self.endereco, {
            "produto": self.camisa.pk,
            "tipo": "saida",
            "quantidade": 99,
            "motivo": "Conferência",
        })
        self.camisa.refresh_from_db()

        self.assertEqual(self.camisa.estoque_atual, 2)
        self.assertIn("Saldo insuficiente", self._mensagens(resposta))

    def test_formulario_invalido_avisa_e_nao_movimenta(self):
        self.client.force_login(self.estoquista)

        resposta = self.client.post(self.endereco, {
            "produto": self.camisa.pk,
            "tipo": "entrada",
            "quantidade": 0,
            "motivo": "",
        })
        self.camisa.refresh_from_db()

        self.assertEqual(self.camisa.estoque_atual, 2)
        self.assertIn("Confira os dados do formulário.", self._mensagens(resposta))

    def test_botao_de_uma_unidade_movimenta_o_produto_da_linha(self):
        self.client.force_login(self.estoquista)

        self.client.post(self.endereco, {
            "produto": self.garrafa.pk,
            "tipo": "saida",
            "quantidade": 1,
            "motivo": "Saída de uma unidade pelo painel",
        })
        self.garrafa.refresh_from_db()

        self.assertEqual(self.garrafa.estoque_atual, 24)
        self.assertEqual(self.garrafa.movimentos.get().tipo, TipoDeMovimento.AJUSTE)

    def _mensagens(self, resposta):
        return " ".join(str(mensagem) for mensagem in resposta.context["messages"])


# ------------------------------------------------------------------ Modelo e Admin
class MovimentoEstoqueTests(TestCase):
    def setUp(self):
        self.produto = cria_produto(estoque_atual=10)

    def test_texto_do_movimento(self):
        movimento = registrar_entrada(self.produto, 3)

        self.assertEqual(str(movimento), "Entrada de 3 em 100110")

    def test_banco_recusa_quantidade_zerada_ou_negativa(self):
        for quantidade in (0, -1):
            with self.subTest(quantidade=quantidade):
                with self.assertRaises(IntegrityError):
                    with transaction.atomic():
                        MovimentoEstoque.objects.create(
                            produto=self.produto,
                            tipo=TipoDeMovimento.ENTRADA,
                            quantidade=quantidade,
                            saldo_apos=10,
                        )

    def test_banco_recusa_saldo_apos_negativo(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MovimentoEstoque.objects.create(
                    produto=self.produto,
                    tipo=TipoDeMovimento.SAIDA_VENDA,
                    quantidade=1,
                    saldo_apos=-1,
                )

    def test_banco_recusa_ajuste_sem_motivo(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MovimentoEstoque.objects.create(
                    produto=self.produto,
                    tipo=TipoDeMovimento.AJUSTE,
                    quantidade=1,
                    saldo_apos=9,
                    motivo="",
                )

    def test_produto_com_movimento_nao_pode_ser_excluido(self):
        registrar_entrada(self.produto, 1)

        with self.assertRaises(ProtectedError):
            with transaction.atomic():
                self.produto.delete()


class MovimentoEstoqueAdminTests(TestCase):
    """O histórico é somente leitura no Admin, com filtros por tipo e por produto."""

    def setUp(self):
        self.produto = cria_produto(estoque_atual=10)
        self.movimento = registrar_entrada(self.produto, 3)
        self.usuario = User.objects.create_superuser("admin", "admin@exemplo.com", SENHA)
        self.client.force_login(self.usuario)

    def test_lista_abre_com_os_filtros_pedidos(self):
        from .admin import MovimentoEstoqueAdmin

        resposta = self.client.get(reverse("admin:estoque_movimentoestoque_changelist"))

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(MovimentoEstoqueAdmin.list_filter, ("tipo", "produto"))
        self.assertIn("saldo_apos", MovimentoEstoqueAdmin.list_display)

    def test_filtro_por_tipo_funciona(self):
        registrar_ajuste(self.produto, 1, motivo="Quebra")

        resposta = self.client.get(
            reverse("admin:estoque_movimentoestoque_changelist"),
            {"tipo__exact": TipoDeMovimento.ENTRADA},
        )

        self.assertEqual(list(resposta.context["cl"].queryset), [self.movimento])

    def test_admin_nao_deixa_criar_alterar_nem_excluir_movimento(self):
        adicionar = self.client.get(reverse("admin:estoque_movimentoestoque_add"))
        excluir = self.client.get(reverse("admin:estoque_movimentoestoque_delete", args=[self.movimento.pk]))

        self.assertEqual(adicionar.status_code, 403)
        self.assertEqual(excluir.status_code, 403)

    def test_movimento_abre_so_para_leitura(self):
        endereco = reverse("admin:estoque_movimentoestoque_change", args=[self.movimento.pk])

        resposta = self.client.get(endereco)

        self.assertEqual(resposta.status_code, 200)
        self.assertNotContains(resposta, 'name="quantidade"')


class DecoratorNoPainelTests(TestCase):
    """O painel usa perfil_requerido; aqui conferimos a exceção que vira o 403."""

    @classmethod
    def setUpTestData(cls):
        call_command("criar_perfis", verbosity=0)

    def test_perfil_errado_levanta_permission_denied(self):
        from django.test import RequestFactory

        from .views import painel

        pedido = RequestFactory().get(reverse("estoque:painel"))
        pedido.user = cria_usuario("vendedor", PERFIL_VENDEDOR)

        with self.assertRaises(PermissionDenied):
            painel(pedido)
