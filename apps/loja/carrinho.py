"""
O carrinho da loja online, guardado na sessão do navegador (pacote 4.5.2).

A sessão guarda só {id do produto: quantidade}, numa chave diferente da "Venda atual" do PDV;
preço e saldo são lidos do banco a cada requisição. Visitantes também usam o carrinho, e ele
continua depois do login, porque o Django mantém os dados da sessão ao autenticar.

O carrinho **não reserva estoque** (CLAUDE.md): toda alteração confere o saldo atual e recusa
o que não couber, mas a baixa só acontece na confirmação do pedido (HU06), pelo serviço de
estoque.
"""
from decimal import Decimal

from apps.produtos.models import Produto

from .services import esta_a_venda

CHAVE_NA_SESSAO = "carrinho_loja"


class ErroDeCarrinho(Exception):
    """Alteração recusada; a mensagem diz o motivo para o cliente."""


class CarrinhoDaLoja:
    """Lê e escreve o carrinho do cliente na sessão."""

    def __init__(self, sessao):
        self.sessao = sessao
        self.quantidades = sessao.get(CHAVE_NA_SESSAO, {})

    def __len__(self):
        return len(self.quantidades)

    def __bool__(self):
        return bool(self.quantidades)

    @property
    def quantidade_de_itens(self):
        """Soma das quantidades, usada em "Carrinho (N)" e em "Subtotal (N itens)"."""
        return sum(self.quantidades.values())

    def quantidade_de(self, produto):
        return self.quantidades.get(str(produto.pk), 0)

    def adicionar(self, produto, quantidade=1):
        """Soma à quantidade que já estava no carrinho; levanta ErroDeCarrinho se não couber."""
        return self.alterar(produto, self.quantidade_de(produto) + quantidade)

    def alterar(self, produto, quantidade):
        """
        Deixa o produto com essa quantidade (zero ou menos tira do carrinho).

        Recusa, sem mudar nada, produto que não está à venda, esgotado ou com quantidade acima
        do saldo atual.
        """
        if quantidade <= 0:
            self.remover(produto)
            return 0

        if not esta_a_venda(produto):
            raise ErroDeCarrinho(f"{produto.nome} não está mais à venda.")

        if produto.estoque_atual <= 0:
            raise ErroDeCarrinho(f"{produto.nome} está esgotado.")

        if quantidade > produto.estoque_atual:
            raise ErroDeCarrinho(
                f"{produto.nome} tem só {produto.estoque_atual} em estoque; "
                f"o carrinho não pode passar disso."
            )

        self.quantidades[str(produto.pk)] = quantidade
        self._grava()

        return quantidade

    def remover(self, produto):
        if self.quantidades.pop(str(produto.pk), None) is not None:
            self._grava()

    def limpar(self):
        self.quantidades = {}
        self.sessao.pop(CHAVE_NA_SESSAO, None)
        self.sessao.modified = True

    def linhas(self):
        """
        Itens do carrinho, na ordem do nome, com quantidade, subtotal e um aviso quando o item
        deixou de caber (saldo menor que a quantidade, esgotado ou fora de venda).
        """
        produtos = (
            Produto.objects.filter(pk__in=[int(pk) for pk in self.quantidades])
            .select_related("categoria")
            .order_by("nome")
        )
        linhas = []

        for produto in produtos:
            quantidade = self.quantidades[str(produto.pk)]
            linhas.append({
                "produto": produto,
                "quantidade": quantidade,
                "subtotal": produto.preco * quantidade,
                "aviso": _aviso(produto, quantidade),
                "pode_aumentar": esta_a_venda(produto) and quantidade < produto.estoque_atual,
            })

        return linhas

    def total(self, linhas=None):
        linhas = self.linhas() if linhas is None else linhas

        return sum((linha["subtotal"] for linha in linhas), Decimal("0.00"))

    def _grava(self):
        self.sessao[CHAVE_NA_SESSAO] = self.quantidades
        self.sessao.modified = True


def _aviso(produto, quantidade):
    """Explica por que o item não fecha mais com o estoque, ou None se estiver tudo certo."""
    if not esta_a_venda(produto):
        return "Este produto não está mais à venda. Remova-o do carrinho."
    if produto.estoque_atual <= 0:
        return "Este produto esgotou depois que você o colocou no carrinho. Remova-o do carrinho."
    if quantidade > produto.estoque_atual:
        return (
            f"Agora só há {produto.estoque_atual} em estoque, menos do que as {quantidade} "
            f"do seu carrinho. Ajuste a quantidade."
        )
    return None
