"""
A "Venda atual" do PDV, guardada na sessão do vendedor (pacote 4.4.1).

A sessão guarda só {id do produto: quantidade}; preço e saldo são lidos do banco a cada
requisição, para a tela nunca mostrar um preço velho. O carrinho **não reserva estoque**
(CLAUDE.md): quem confere o saldo é o serviço de estoque, na hora de finalizar.
"""
from decimal import Decimal

from apps.produtos.models import Produto

CHAVE_NA_SESSAO = "venda_atual"


class CarrinhoDoPDV:
    """Lê e escreve a venda em andamento na sessão."""

    def __init__(self, sessao):
        self.sessao = sessao
        self.quantidades = sessao.get(CHAVE_NA_SESSAO, {})

    def __len__(self):
        return len(self.quantidades)

    def __bool__(self):
        return bool(self.quantidades)

    def acrescentar(self, produto, quantidade=1):
        """Soma à quantidade que já estava no carrinho, sem passar do saldo do produto."""
        return self.definir(produto, self.quantidade_de(produto) + quantidade)

    def definir(self, produto, quantidade):
        """
        Deixa o produto com essa quantidade e devolve a quantidade que coube.

        Quantidade zero (ou menos) tira o produto do carrinho; acima do saldo, para no saldo.
        """
        if quantidade <= 0:
            self.remover(produto)
            return 0

        cabe = min(quantidade, produto.estoque_atual)
        if cabe <= 0:
            self.remover(produto)
            return 0

        self.quantidades[str(produto.pk)] = cabe
        self._grava()

        return cabe

    def remover(self, produto):
        if self.quantidades.pop(str(produto.pk), None) is not None:
            self._grava()

    def limpar(self):
        self.quantidades = {}
        self.sessao.pop(CHAVE_NA_SESSAO, None)
        self.sessao.modified = True

    def quantidade_de(self, produto):
        return self.quantidades.get(str(produto.pk), 0)

    def linhas(self):
        """Itens do carrinho com produto, quantidade e subtotal, na ordem do nome."""
        produtos = Produto.objects.filter(pk__in=[int(pk) for pk in self.quantidades]).order_by("nome")

        return [
            {
                "produto": produto,
                "quantidade": self.quantidades[str(produto.pk)],
                "subtotal": produto.preco * self.quantidades[str(produto.pk)],
            }
            for produto in produtos
        ]

    def pares(self):
        """Itens no formato (produto, quantidade) que os serviços esperam."""
        return [(linha["produto"], linha["quantidade"]) for linha in self.linhas()]

    def total(self, linhas=None):
        linhas = self.linhas() if linhas is None else linhas

        return sum((linha["subtotal"] for linha in linhas), Decimal("0.00"))

    def _grava(self):
        self.sessao[CHAVE_NA_SESSAO] = self.quantidades
        self.sessao.modified = True
