"""
Serviço de estoque.

Pacote 4.3: entradas (4.3.1), baixa e sincronização entre canais (4.3.2), estoque mínimo e
alertas (4.3.3).

**Toda mudança de saldo passa por aqui** (CLAUDE.md). Nenhum outro módulo escreve em
Produto.estoque_atual: o PDV (4.4) e o checkout da loja online (4.5) chamam baixar_itens e
estornar_itens, e é isso que mantém os dois canais olhando para o mesmo saldo.

Cada função:

- abre uma transação (transaction.atomic), para o saldo e o movimento caírem juntos;
- bloqueia os produtos com select_for_update() em ordem de id, para duas vendas simultâneas
  da última unidade não passarem as duas (a ordem fixa evita travamento entre transações);
- grava um MovimentoEstoque por produto, com o saldo depois da mudança.
"""
from django.db import transaction
from django.db.models import F

from apps.produtos.models import Produto

from .models import MovimentoEstoque, TIPOS_DE_ENTRADA, TipoDeMovimento


class ErroDeEstoque(Exception):
    """Erro de regra de negócio do estoque."""


class QuantidadeInvalida(ErroDeEstoque):
    """A quantidade precisa ser um número inteiro maior que zero."""


class MotivoObrigatorio(ErroDeEstoque):
    """A saída manual (ajuste) só é aceita com motivo."""


class SaldoInsuficiente(ErroDeEstoque):
    """Não há saldo para atender a quantidade pedida; diz qual produto faltou."""

    def __init__(self, produto, solicitado, disponivel):
        self.produto = produto
        self.solicitado = solicitado
        self.disponivel = disponivel
        super().__init__(
            f"Saldo insuficiente de {produto.codigo} - {produto.nome}: "
            f"{solicitado} solicitada(s) e {disponivel} em estoque."
        )


# ------------------------------------------------------------------ Entradas e ajustes
@transaction.atomic
def registrar_entrada(produto, quantidade, usuario=None, motivo=""):
    """Dá entrada de mercadoria: aumenta o saldo e grava o movimento (HU05)."""
    _valida_quantidade(quantidade)
    bloqueado = _bloqueia([produto.pk])[produto.pk]

    return _aplica(bloqueado, quantidade, TipoDeMovimento.ENTRADA, usuario, motivo)


@transaction.atomic
def registrar_ajuste(produto, quantidade, usuario=None, motivo=""):
    """
    Saída manual de mercadoria (perda, quebra, conferência).

    Exige motivo e não pode deixar o saldo negativo (HU05).
    """
    _valida_quantidade(quantidade)

    motivo = (motivo or "").strip()
    if not motivo:
        raise MotivoObrigatorio("A saída manual exige um motivo.")

    bloqueado = _bloqueia([produto.pk])[produto.pk]
    if bloqueado.estoque_atual < quantidade:
        raise SaldoInsuficiente(bloqueado, quantidade, bloqueado.estoque_atual)

    return _aplica(bloqueado, quantidade, TipoDeMovimento.AJUSTE, usuario, motivo)


# ------------------------------------------------------------------ Vendas e estornos
@transaction.atomic
def baixar_itens(itens, usuario=None, motivo="", venda=None):
    """
    Baixa do estoque os itens de uma venda, do PDV ou da loja online (HU06).

    `itens` é uma sequência de pares (produto, quantidade). Ou todos os itens são baixados,
    ou nenhum: se faltar saldo em qualquer um deles, levanta SaldoInsuficiente — que diz qual
    produto faltou — e a transação volta atrás.

    `venda` liga os movimentos à venda que os gerou; fica em branco nas baixas sem venda.
    """
    quantidades = _consolida(itens)
    produtos = _bloqueia(quantidades)

    # Confere todos antes de mexer em qualquer saldo.
    for pk, quantidade in quantidades.items():
        produto = produtos[pk]
        if produto.estoque_atual < quantidade:
            raise SaldoInsuficiente(produto, quantidade, produto.estoque_atual)

    return [
        _aplica(produtos[pk], quantidade, TipoDeMovimento.SAIDA_VENDA, usuario, motivo, venda)
        for pk, quantidade in quantidades.items()
    ]


@transaction.atomic
def estornar_itens(itens, usuario=None, motivo="", venda=None):
    """Devolve ao estoque os itens de uma venda cancelada (HU06)."""
    quantidades = _consolida(itens)
    produtos = _bloqueia(quantidades)

    return [
        _aplica(produtos[pk], quantidade, TipoDeMovimento.ESTORNO, usuario, motivo, venda)
        for pk, quantidade in quantidades.items()
    ]


# ------------------------------------------------------------------ Consultas do painel
def produtos_em_alerta():
    """
    Produtos ativos com saldo igual ou abaixo do mínimo, os mais críticos primeiro (HU07).

    Saldo zero também entra aqui: o painel mostra esses como "Sem estoque".
    """
    return (
        Produto.objects.filter(ativo=True, estoque_atual__lte=F("estoque_minimo"))
        .select_related("categoria")
        .order_by("estoque_atual", "nome")
    )


def saldo_por_produto():
    """Todos os produtos ativos com o seu saldo, para a tabela do painel."""
    return Produto.objects.filter(ativo=True).select_related("categoria").order_by("nome")


# ------------------------------------------------------------------ Apoio interno
def _valida_quantidade(quantidade):
    if not isinstance(quantidade, int) or isinstance(quantidade, bool) or quantidade <= 0:
        raise QuantidadeInvalida("A quantidade precisa ser um número inteiro maior que zero.")


def _consolida(itens):
    """
    Soma as quantidades por produto, mantendo a ordem em que os itens chegaram.

    O mesmo produto pode vir duas vezes no carrinho; o estoque precisa enxergar o total.
    """
    quantidades = {}

    for produto, quantidade in itens:
        _valida_quantidade(quantidade)
        quantidades[produto.pk] = quantidades.get(produto.pk, 0) + quantidade

    if not quantidades:
        raise ErroDeEstoque("Informe pelo menos um item.")

    return quantidades


def _bloqueia(pks):
    """Bloqueia os produtos para escrita, sempre em ordem de id, e devolve {pk: produto}."""
    produtos = {
        produto.pk: produto
        for produto in Produto.objects.select_for_update().filter(pk__in=pks).order_by("id")
    }

    ausentes = set(pks) - set(produtos)
    if ausentes:
        raise ErroDeEstoque(f"Produto não encontrado (id {sorted(ausentes)}).")

    return produtos


def _aplica(produto, quantidade, tipo, usuario, motivo, venda=None):
    """Muda o saldo do produto já bloqueado e grava o movimento correspondente."""
    produto.estoque_atual += quantidade if tipo in TIPOS_DE_ENTRADA else -quantidade
    produto.save(update_fields=["estoque_atual"])

    return MovimentoEstoque.objects.create(
        produto=produto,
        tipo=tipo,
        quantidade=quantidade,
        saldo_apos=produto.estoque_atual,
        usuario=usuario,
        motivo=motivo,
        venda=venda,
    )
