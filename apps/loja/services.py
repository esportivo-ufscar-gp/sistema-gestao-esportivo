"""
Regras de negócio do módulo Loja online.

Pacote 4.5: catálogo (4.5.1), carrinho (4.5.2), checkout (4.5.3) e pedidos (4.5.4).

O catálogo é só leitura: mostra os produtos ativos de categorias ativas com a disponibilidade
calculada a partir do saldo e do estoque mínimo. A confirmação do pedido (confirmar_pedido)
junta a identificação do cliente e o serviço de vendas; quem mexe em estoque continua sendo só
apps/estoque/services.py (CLAUDE.md).
"""
from dataclasses import dataclass

from django.db import transaction

from apps.clientes.services import cliente_do_checkout
from apps.produtos.models import Categoria, Produto
from apps.vendas.models import FormaDePagamento
from apps.vendas.services import ErroDeVenda, registrar_pedido_online

# Formas aceitas na loja online, com o texto do protótipo.
FORMAS_DE_PAGAMENTO_DA_LOJA = (
    (FormaDePagamento.CARTAO, "Cartão de crédito"),
    (FormaDePagamento.PIX, "PIX"),
)


class ProdutoForaDeVenda(ErroDeVenda):
    """Um item do carrinho deixou de estar à venda antes da confirmação."""


# Valor do ?ordem= -> campos do order_by. O nome desempata os preços iguais.
ORDENACOES = {
    "nome": ("nome", "id"),
    "menor_preco": ("preco", "nome", "id"),
    "maior_preco": ("-preco", "nome", "id"),
}
ORDENACAO_PADRAO = "nome"
ROTULOS_DAS_ORDENACOES = (
    ("nome", "Nome"),
    ("menor_preco", "Menor preço"),
    ("maior_preco", "Maior preço"),
)

EM_ESTOQUE = "em_estoque"
ULTIMAS_UNIDADES = "ultimas_unidades"
ESGOTADO = "esgotado"


@dataclass(frozen=True)
class Disponibilidade:
    """Faixa de disponibilidade de um produto na vitrine (HU10)."""

    situacao: str
    rotulo: str

    @property
    def pode_comprar(self):
        return self.situacao != ESGOTADO


def disponibilidade(produto):
    """
    Em estoque, últimas unidades ou esgotado (HU10).

    Saldo acima do mínimo é "Em estoque"; saldo maior que zero e até o mínimo (inclusive) é
    "Últimas N unidades"; saldo zero é "Esgotado".
    """
    saldo = produto.estoque_atual

    if saldo <= 0:
        return Disponibilidade(ESGOTADO, "Esgotado")
    if saldo <= produto.estoque_minimo:
        rotulo = "Última unidade" if saldo == 1 else f"Últimas {saldo} unidades"
        return Disponibilidade(ULTIMAS_UNIDADES, rotulo)
    return Disponibilidade(EM_ESTOQUE, "Em estoque")


def esta_a_venda(produto):
    """O produto aparece na loja online: ele e a sua categoria estão ativos."""
    return produto.ativo and produto.categoria.ativa


def categorias_do_catalogo():
    """Categorias ativas que têm pelo menos um produto ativo, para o filtro da vitrine."""
    return Categoria.objects.filter(ativa=True, produtos__ativo=True).distinct().order_by("nome")


def produtos_do_catalogo(categoria=None, busca="", ordem=ORDENACAO_PADRAO):
    """
    Produtos da vitrine (HU10): só os ativos de categorias ativas.

    `categoria` filtra pelo id; `busca` procura no nome sem diferenciar maiúsculas e
    minúsculas; `ordem` é uma das chaves de ORDENACOES (valor desconhecido vira o padrão).
    """
    produtos = Produto.objects.filter(ativo=True, categoria__ativa=True).select_related("categoria")

    if categoria is not None:
        produtos = produtos.filter(categoria_id=categoria)

    busca = (busca or "").strip()
    if busca:
        produtos = produtos.filter(nome__icontains=busca)

    return produtos.order_by(*ORDENACOES.get(ordem, ORDENACOES[ORDENACAO_PADRAO]))


def rotulo_do_pagamento(forma_pagamento):
    """Texto da forma de pagamento como a loja online mostra ("Cartão de crédito", "PIX")."""
    return dict(FORMAS_DE_PAGAMENTO_DA_LOJA).get(forma_pagamento, forma_pagamento)


@transaction.atomic
def confirmar_pedido(usuario, itens, forma_pagamento, dados_do_visitante=None):
    """
    Confirma a compra da loja online (HU12): identifica o cliente e registra o pedido.

    Tudo numa transação só: se faltar saldo, nem o pedido nem o cadastro de um visitante novo
    ficam gravados. Levanta ProdutoForaDeVenda, os erros de identificação de
    apps/clientes/services.py, ErroDeVenda ou SaldoInsuficiente (do estoque).
    """
    fora = [produto.nome for produto, _ in itens if not esta_a_venda(produto)]
    if fora:
        raise ProdutoForaDeVenda(f"{', '.join(fora)} não está mais à venda. Remova do carrinho para continuar.")

    cliente = cliente_do_checkout(usuario, dados_do_visitante)

    return registrar_pedido_online(cliente, itens, forma_pagamento)
