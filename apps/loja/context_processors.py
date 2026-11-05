"""
Dados da loja que todo template recebe (pacote 4.5.2).

O cabeçalho da loja mostra "Carrinho (N)" em qualquer página; N vem só da sessão, sem
consultar o banco.
"""
from .carrinho import CarrinhoDaLoja


def carrinho(request):
    return {"itens_no_carrinho": CarrinhoDaLoja(request.session).quantidade_de_itens}
