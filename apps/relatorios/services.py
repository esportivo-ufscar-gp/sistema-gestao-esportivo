"""
Regras de negócio do módulo Relatórios.

Pacote 4.7: vendas por período e canal (4.7.1, HU16) e posição de estoque (4.7.2, HU17).

Os relatórios só leem dados: nada aqui grava no banco. As contas são feitas pelo próprio
banco (Count e Sum), então o relatório continua rápido mesmo com muitas vendas.
"""
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Case, Count, F, IntegerField, Sum, Value, When
from django.utils import timezone

from apps.produtos.models import Produto
from apps.vendas.models import CanalDeVenda, Venda

ZERO = Decimal("0.00")
CENTAVO = Decimal("0.01")

SITUACAO_SEM_ESTOQUE = "sem_estoque"
SITUACAO_ABAIXO_DO_MINIMO = "abaixo_do_minimo"
SITUACAO_NORMAL = "normal"

ROTULOS_DE_SITUACAO = {
    SITUACAO_SEM_ESTOQUE: "Sem estoque",
    SITUACAO_ABAIXO_DO_MINIMO: "Abaixo do mínimo",
    SITUACAO_NORMAL: "Normal",
}


class PeriodoInvalido(ValueError):
    """A data inicial vem depois da data final."""


# ------------------------------------------------------------------ 4.7.1 Vendas (HU16)
@dataclass(frozen=True)
class LinhaDeVendas:
    """Uma linha do relatório: um canal ou o total geral."""

    rotulo: str
    vendas: int
    valor_total: Decimal
    percentual: Decimal  # participação no valor total do período, de 0 a 100
    canal: str = ""

    @property
    def ticket_medio(self):
        return ticket_medio(self.valor_total, self.vendas)


@dataclass(frozen=True)
class RelatorioDeVendas:
    data_inicial: date
    data_final: date
    canal: str
    canais: list
    total: LinhaDeVendas


def periodo_padrao(hoje=None):
    """Do primeiro dia do mês até hoje, no fuso do sistema (São Paulo)."""
    hoje = hoje or timezone.localdate()
    return hoje.replace(day=1), hoje


def ticket_medio(valor_total, vendas):
    """Valor total dividido pelo número de vendas, arredondado ao centavo; zero sem vendas."""
    if not vendas:
        return ZERO
    return (Decimal(valor_total) / vendas).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def vendas_por_periodo(data_inicial, data_final, canal=""):
    """
    Total vendido entre as duas datas (inclusive), separado por canal (HU16).

    - As datas são dias do calendário de São Paulo: uma venda das 23h50 do dia final entra.
    - Vendas do PDV e pedidos online cancelados não entram na conta.
    - `canal` vazio traz os dois canais; com um canal, só ele aparece.
    """
    if data_inicial > data_final:
        raise PeriodoInvalido("A data inicial precisa ser igual ou anterior à data final.")

    if canal and canal not in CanalDeVenda.values:
        raise ValueError(f"Canal desconhecido: {canal}")

    vendas = Venda.objects.validas().filter(
        criado_em__date__gte=data_inicial,
        criado_em__date__lte=data_final,
    )
    if canal:
        vendas = vendas.filter(canal=canal)

    por_canal = {
        linha["canal"]: linha
        for linha in vendas.values("canal").annotate(vendas=Count("id"), valor_total=Sum("total")).order_by()
    }

    canais_do_relatorio = [canal] if canal else CanalDeVenda.values
    numero_total = sum(linha["vendas"] for linha in por_canal.values())
    valor_total = sum((linha["valor_total"] for linha in por_canal.values()), ZERO)

    linhas = []
    for codigo in canais_do_relatorio:
        dados = por_canal.get(codigo, {})
        valor = dados.get("valor_total") or ZERO
        linhas.append(LinhaDeVendas(
            rotulo=CanalDeVenda(codigo).label,
            canal=codigo,
            vendas=dados.get("vendas", 0),
            valor_total=valor,
            percentual=_percentual(valor, valor_total),
        ))

    total = LinhaDeVendas(
        rotulo="Total",
        vendas=numero_total,
        valor_total=valor_total,
        percentual=Decimal("100.0") if valor_total else Decimal("0.0"),
    )

    return RelatorioDeVendas(
        data_inicial=data_inicial,
        data_final=data_final,
        canal=canal,
        canais=linhas,
        total=total,
    )


def _percentual(parte, todo):
    if not todo:
        return Decimal("0.0")
    return (Decimal(parte) * 100 / todo).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


# ------------------------------------------------------------------ 4.7.2 Estoque (HU17)
def posicao_de_estoque(categoria=None):
    """
    Saldo atual de cada produto ativo, com categoria e estoque mínimo (HU17).

    Cada produto recebe `situacao`: sem estoque (saldo zero), abaixo do mínimo (saldo igual ou
    abaixo do mínimo, a mesma regra do alerta do 4.3.3) ou normal. Os mais críticos vêm
    primeiro, para a gestão ver logo o que precisa comprar.
    """
    produtos = (
        Produto.objects.filter(ativo=True)
        .select_related("categoria")
        .annotate(
            situacao=Case(
                When(estoque_atual=0, then=Value(SITUACAO_SEM_ESTOQUE)),
                When(estoque_atual__lte=F("estoque_minimo"), then=Value(SITUACAO_ABAIXO_DO_MINIMO)),
                default=Value(SITUACAO_NORMAL),
            ),
            gravidade=Case(
                When(estoque_atual=0, then=Value(0)),
                When(estoque_atual__lte=F("estoque_minimo"), then=Value(1)),
                default=Value(2),
                output_field=IntegerField(),
            ),
        )
        .order_by("gravidade", "nome")
    )

    if categoria is not None:
        produtos = produtos.filter(categoria=categoria)

    return produtos


def rotulo_da_situacao(situacao):
    return ROTULOS_DE_SITUACAO.get(situacao, "")
