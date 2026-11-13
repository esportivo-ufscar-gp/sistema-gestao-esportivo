"""
Testes unitários do módulo Relatórios.

Pacote 4.7: vendas por período e canal (4.7.1, HU16) e posição de estoque (4.7.2, HU17).

Cada critério de aceite das duas histórias tem pelo menos um teste. As vendas são criadas
direto no modelo, com o total já definido e a data ajustada, porque o relatório só lê o que
está gravado: quem calcula total e baixa estoque é o serviço de vendas, já testado no 4.4.
"""
from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.clientes.models import Cliente
from apps.contas.services import PERFIL_ADMINISTRADOR, PERFIL_ESTOQUISTA, PERFIL_VENDEDOR
from apps.produtos.models import Categoria, Produto
from apps.vendas.models import CanalDeVenda, FormaDePagamento, StatusDeVenda, Venda

from .forms import FiltroDeVendas
from .services import (
    SITUACAO_ABAIXO_DO_MINIMO,
    SITUACAO_NORMAL,
    SITUACAO_SEM_ESTOQUE,
    PeriodoInvalido,
    periodo_padrao,
    posicao_de_estoque,
    ticket_medio,
    vendas_por_periodo,
)

SENHA = "senha-de-teste-123"


def momento(ano, mes, dia, hora=12, minuto=0):
    """Data e hora no fuso do sistema (São Paulo)."""
    return timezone.make_aware(datetime(ano, mes, dia, hora, minuto))


class ComVendas:
    """Ajudantes para gravar vendas com total e data escolhidos pelo teste."""

    numero = 0

    def cliente(self):
        if not hasattr(self, "_cliente"):
            self._cliente = Cliente.objects.create(
                nome="Marina Souza",
                email="marina@exemplo.com",
                telefone="16999990000",
                consentimento_em=timezone.now(),
            )
        return self._cliente

    def venda(self, total, quando, canal=CanalDeVenda.LOJA_FISICA, status=None):
        ComVendas.numero += 1
        online = canal == CanalDeVenda.ONLINE
        venda = Venda.objects.create(
            numero=ComVendas.numero,
            canal=canal,
            status=status or (StatusDeVenda.AGUARDANDO_RETIRADA if online else StatusDeVenda.CONCLUIDA),
            forma_pagamento=FormaDePagamento.PIX,
            total=Decimal(total),
            cliente=self.cliente() if online else None,
        )
        # criado_em usa auto_now_add; a data do teste entra depois, com update().
        Venda.objects.filter(pk=venda.pk).update(criado_em=quando)
        return venda


# ------------------------------------------------------ HU16 Vendas por período e canal (4.7.1)
class VendasPorPeriodoTests(ComVendas, TestCase):
    """HU16: total vendido no período, separado por loja física e online."""

    def setUp(self):
        self.venda("100.00", momento(2026, 10, 5))
        self.venda("200.00", momento(2026, 10, 10))
        self.venda("300.00", momento(2026, 10, 12), canal=CanalDeVenda.ONLINE)
        self.venda("999.00", momento(2026, 9, 30))       # antes do período
        self.venda("888.00", momento(2026, 11, 1))       # depois do período

    def relatorio(self, **kwargs):
        return vendas_por_periodo(date(2026, 10, 1), date(2026, 10, 31), **kwargs)

    def test_mostra_numero_valor_e_ticket_por_canal(self):
        fisica, online = self.relatorio().canais

        self.assertEqual((fisica.canal, fisica.vendas, fisica.valor_total), ("loja_fisica", 2, Decimal("300.00")))
        self.assertEqual(fisica.ticket_medio, Decimal("150.00"))
        self.assertEqual((online.canal, online.vendas, online.valor_total), ("online", 1, Decimal("300.00")))
        self.assertEqual(online.ticket_medio, Decimal("300.00"))

    def test_mostra_numero_valor_e_ticket_no_total(self):
        total = self.relatorio().total

        self.assertEqual(total.vendas, 3)
        self.assertEqual(total.valor_total, Decimal("600.00"))
        self.assertEqual(total.ticket_medio, Decimal("200.00"))

    def test_filtro_usa_data_inicial_e_final(self):
        relatorio = vendas_por_periodo(date(2026, 10, 10), date(2026, 10, 12))

        self.assertEqual(relatorio.total.vendas, 2)
        self.assertEqual(relatorio.total.valor_total, Decimal("500.00"))

    def test_datas_inicial_e_final_entram_no_periodo_no_fuso_de_sao_paulo(self):
        self.venda("10.00", momento(2026, 10, 1, 0, 5))
        # 23h50 em São Paulo já é dia 1º/11 em UTC, mas ainda é 31/10 para a loja.
        self.venda("20.00", momento(2026, 10, 31, 23, 50))

        self.assertEqual(self.relatorio().total.valor_total, Decimal("630.00"))

    def test_vendas_e_pedidos_cancelados_nao_entram_na_conta(self):
        self.venda("50.00", momento(2026, 10, 6), status=StatusDeVenda.CANCELADA)
        self.venda("70.00", momento(2026, 10, 7), canal=CanalDeVenda.ONLINE, status=StatusDeVenda.CANCELADA)

        relatorio = self.relatorio()

        self.assertEqual(relatorio.total.vendas, 3)
        self.assertEqual(relatorio.total.valor_total, Decimal("600.00"))

    def test_pedidos_retirados_e_aguardando_entram_na_conta(self):
        self.venda("40.00", momento(2026, 10, 8), canal=CanalDeVenda.ONLINE, status=StatusDeVenda.RETIRADA)

        self.assertEqual(self.relatorio().canais[1].vendas, 2)

    def test_filtro_por_canal_mostra_so_o_canal_escolhido(self):
        relatorio = self.relatorio(canal=CanalDeVenda.ONLINE)

        self.assertEqual([linha.canal for linha in relatorio.canais], ["online"])
        self.assertEqual(relatorio.total.valor_total, Decimal("300.00"))

    def test_canal_desconhecido_e_recusado(self):
        with self.assertRaises(ValueError):
            self.relatorio(canal="telefone")

    def test_percentual_de_cada_canal_no_valor_total(self):
        fisica, online = self.relatorio().canais

        self.assertEqual(fisica.percentual, Decimal("50.0"))
        self.assertEqual(online.percentual, Decimal("50.0"))

    def test_periodo_sem_vendas_mostra_zeros(self):
        relatorio = vendas_por_periodo(date(2025, 1, 1), date(2025, 1, 31))

        self.assertEqual(relatorio.total.vendas, 0)
        self.assertEqual(relatorio.total.valor_total, Decimal("0.00"))
        self.assertEqual(relatorio.total.ticket_medio, Decimal("0.00"))
        self.assertEqual([linha.percentual for linha in relatorio.canais], [Decimal("0.0"), Decimal("0.0")])

    def test_data_inicial_depois_da_final_e_recusada(self):
        with self.assertRaises(PeriodoInvalido):
            vendas_por_periodo(date(2026, 10, 31), date(2026, 10, 1))


class TicketMedioTests(TestCase):
    def test_arredonda_ao_centavo(self):
        self.assertEqual(ticket_medio(Decimal("100.00"), 3), Decimal("33.33"))
        self.assertEqual(ticket_medio(Decimal("0.05"), 2), Decimal("0.03"))

    def test_sem_vendas_e_zero(self):
        self.assertEqual(ticket_medio(Decimal("0.00"), 0), Decimal("0.00"))


class FiltroDeVendasTests(TestCase):
    def test_sem_datas_abre_no_mes_corrente(self):
        filtro = FiltroDeVendas({})

        self.assertTrue(filtro.is_valid())
        self.assertEqual(
            (filtro.cleaned_data["data_inicial"], filtro.cleaned_data["data_final"]),
            periodo_padrao(),
        )

    def test_periodo_padrao_vai_do_dia_primeiro_ate_hoje(self):
        self.assertEqual(periodo_padrao(date(2026, 11, 13)), (date(2026, 11, 1), date(2026, 11, 13)))

    def test_aceita_data_no_formato_brasileiro(self):
        filtro = FiltroDeVendas({"data_inicial": "01/10/2026", "data_final": "22/10/2026"})

        self.assertTrue(filtro.is_valid())
        self.assertEqual(filtro.cleaned_data["data_inicial"], date(2026, 10, 1))

    def test_data_final_antes_da_inicial_e_erro_do_formulario(self):
        filtro = FiltroDeVendas({"data_inicial": "2026-10-31", "data_final": "2026-10-01"})

        self.assertFalse(filtro.is_valid())
        self.assertIn("data_final", filtro.errors)


# ------------------------------------------------------ HU17 Posição de estoque (4.7.2)
class PosicaoDeEstoqueTests(TestCase):
    """HU17: saldo atual de cada produto, com destaque para os que estão no mínimo ou abaixo."""

    def setUp(self):
        self.academia = Categoria.objects.create(nome="Academia")
        self.futebol = Categoria.objects.create(nome="Futebol")
        self.camisa = self.produto("1", "Camisa térmica", self.academia, saldo=0, minimo=3)
        self.chuteira = self.produto("2", "Chuteira society", self.futebol, saldo=2, minimo=4)
        self.bola = self.produto("3", "Bola de futebol", self.futebol, saldo=5, minimo=5)
        self.garrafa = self.produto("4", "Garrafa térmica", self.academia, saldo=25, minimo=8)
        self.inativo = self.produto("5", "Produto antigo", self.academia, saldo=1, minimo=3, ativo=False)

    def produto(self, codigo, nome, categoria, saldo, minimo, ativo=True):
        # Carga direta do saldo só para montar o cenário, como a fixture de exemplo faz.
        return Produto.objects.create(
            codigo=codigo, nome=nome, categoria=categoria, preco=Decimal("10.00"),
            estoque_atual=saldo, estoque_minimo=minimo, ativo=ativo,
        )

    def test_lista_produto_categoria_saldo_e_minimo(self):
        linha = posicao_de_estoque().get(pk=self.chuteira.pk)

        self.assertEqual(
            (linha.nome, linha.categoria.nome, linha.estoque_atual, linha.estoque_minimo),
            ("Chuteira society", "Futebol", 2, 4),
        )

    def test_lista_so_produtos_ativos(self):
        self.assertNotIn(self.inativo, posicao_de_estoque())
        self.assertEqual(posicao_de_estoque().count(), 4)

    def test_filtra_por_categoria(self):
        self.assertEqual(set(posicao_de_estoque(self.futebol)), {self.chuteira, self.bola})

    def test_saldo_igual_ou_abaixo_do_minimo_e_destacado(self):
        situacoes = {produto.pk: produto.situacao for produto in posicao_de_estoque()}

        self.assertEqual(situacoes[self.camisa.pk], SITUACAO_SEM_ESTOQUE)
        self.assertEqual(situacoes[self.chuteira.pk], SITUACAO_ABAIXO_DO_MINIMO)
        self.assertEqual(situacoes[self.bola.pk], SITUACAO_ABAIXO_DO_MINIMO)  # igual ao mínimo
        self.assertEqual(situacoes[self.garrafa.pk], SITUACAO_NORMAL)

    def test_mais_criticos_aparecem_primeiro(self):
        self.assertEqual(
            list(posicao_de_estoque()),
            [self.camisa, self.bola, self.chuteira, self.garrafa],
        )

    def test_relatorio_nao_altera_o_estoque(self):
        list(posicao_de_estoque())
        self.camisa.refresh_from_db()

        self.assertEqual(self.camisa.estoque_atual, 0)
        self.assertFalse(self.camisa.movimentos.exists())


# ------------------------------------------------------ Tela /relatorios/
class TelaDeRelatoriosTests(ComVendas, TestCase):
    """A tela junta os dois relatórios e é só do administrador."""

    @classmethod
    def setUpTestData(cls):
        call_command("criar_perfis", verbosity=0)
        cls.url = reverse("relatorios:painel")
        cls.admin = cls.usuario("carla", PERFIL_ADMINISTRADOR, is_staff=True)
        cls.vendedor = cls.usuario("ana", PERFIL_VENDEDOR)
        cls.estoquista = cls.usuario("bruno", PERFIL_ESTOQUISTA)
        futebol = Categoria.objects.create(nome="Futebol")
        corrida = Categoria.objects.create(nome="Corrida")
        cls.chuteira = Produto.objects.create(
            codigo="1", nome="Chuteira society", categoria=futebol, preco=Decimal("199.90"),
            estoque_atual=2, estoque_minimo=4,
        )
        cls.tenis = Produto.objects.create(
            codigo="2", nome="Tênis de corrida", categoria=corrida, preco=Decimal("349.90"),
            estoque_atual=12, estoque_minimo=4,
        )

    @staticmethod
    def usuario(nome, perfil, **campos):
        usuario = User.objects.create_user(username=nome, email=f"{nome}@exemplo.com", password=SENHA, **campos)
        usuario.groups.add(Group.objects.get(name=perfil))
        return usuario

    def test_visitante_vai_para_o_login(self):
        resposta = self.client.get(self.url)

        self.assertEqual(resposta.status_code, 302)
        self.assertIn(reverse("contas:entrar"), resposta["Location"])

    def test_vendedor_e_estoquista_nao_entram(self):
        for usuario in (self.vendedor, self.estoquista):
            self.client.force_login(usuario)
            self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_administrador_ve_os_dois_relatorios(self):
        self.venda("1234.50", momento(2026, 10, 5))
        self.venda("100.00", momento(2026, 10, 6), status=StatusDeVenda.CANCELADA)
        self.client.force_login(self.admin)

        resposta = self.client.get(self.url, {"data_inicial": "2026-10-01", "data_final": "2026-10-31"})

        self.assertEqual(resposta.status_code, 200)
        self.assertTemplateUsed(resposta, "relatorios/painel.html")
        self.assertContains(resposta, "R$ 1.234,50")
        self.assertContains(resposta, "01/10/2026 a 31/10/2026")
        self.assertContains(resposta, "Posição de estoque")
        self.assertContains(resposta, "Chuteira society")
        self.assertContains(resposta, 'class="table-warning"')
        self.assertContains(resposta, "Abaixo do mínimo")

    def test_sem_filtro_abre_no_mes_corrente(self):
        self.client.force_login(self.admin)

        vendas = self.client.get(self.url).context["vendas"]

        self.assertEqual((vendas.data_inicial, vendas.data_final), periodo_padrao())

    def test_filtro_por_canal_na_tela(self):
        self.venda("80.00", momento(2026, 10, 5), canal=CanalDeVenda.ONLINE)
        self.client.force_login(self.admin)

        vendas = self.client.get(
            self.url, {"data_inicial": "2026-10-01", "data_final": "2026-10-31", "canal": "online"}
        ).context["vendas"]

        self.assertEqual(vendas.total.valor_total, Decimal("80.00"))

    def test_periodo_invertido_mostra_erro_sem_quebrar_a_tela(self):
        self.client.force_login(self.admin)

        resposta = self.client.get(self.url, {"data_inicial": "2026-10-31", "data_final": "2026-10-01"})

        self.assertEqual(resposta.status_code, 200)
        self.assertIsNone(resposta.context["vendas"])
        self.assertContains(resposta, "A data final precisa ser igual ou posterior à data inicial.")

    def test_filtro_por_categoria_na_tela(self):
        self.client.force_login(self.admin)

        resposta = self.client.get(self.url, {"categoria": self.chuteira.categoria_id})

        self.assertEqual(list(resposta.context["produtos"]), [self.chuteira])

    def test_link_de_relatorios_aparece_so_para_o_administrador(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(self.url), f'href="{self.url}"')

        self.client.force_login(self.estoquista)
        self.assertNotContains(self.client.get(reverse("estoque:painel")), f'href="{self.url}"')
