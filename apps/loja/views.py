"""
Views do módulo Loja online.

Pacote 4.5: catálogo em /loja/ (4.5.1) e carrinho em /loja/carrinho/ (4.5.2), abertos a
visitantes.

A view só recebe a requisição, chama o serviço e mostra o resultado (CLAUDE.md). O carrinho
fica na sessão e não mexe em estoque; quem confere o saldo é apps/loja/carrinho.py.
"""
from urllib.parse import urlencode

from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.produtos.models import Produto

from .carrinho import CarrinhoDaLoja, ErroDeCarrinho
from .services import (
    ORDENACAO_PADRAO,
    ORDENACOES,
    ROTULOS_DAS_ORDENACOES,
    categorias_do_catalogo,
    produtos_do_catalogo,
)


def catalogo(request):
    """Vitrine da loja: filtro por categoria, busca pelo nome e ordenação (HU10)."""
    busca = request.GET.get("busca", "").strip()
    ordem = request.GET.get("ordem", ORDENACAO_PADRAO)
    if ordem not in ORDENACOES:
        ordem = ORDENACAO_PADRAO

    categorias = list(categorias_do_catalogo())
    categoria = _categoria_escolhida(request.GET.get("categoria"), categorias)
    produtos = produtos_do_catalogo(
        categoria=categoria.pk if categoria else None,
        busca=busca,
        ordem=ordem,
    )

    return render(request, "loja/catalogo.html", {
        "produtos": produtos,
        "busca": busca,
        "ordem": ordem,
        "ordenacoes": ROTULOS_DAS_ORDENACOES,
        "categoria": categoria,
        "filtros": _filtros(categorias, categoria, busca, ordem),
    })


@require_POST
def adicionar(request):
    """Põe uma unidade do produto no carrinho e volta para a página de onde o cliente veio."""
    produto = _produto_do_pedido(request)

    try:
        CarrinhoDaLoja(request.session).adicionar(produto)
    except ErroDeCarrinho as erro:
        messages.error(request, str(erro))
    else:
        messages.success(request, f"{produto.nome} foi para o carrinho.")

    return redirect(_volta_para(request))


def carrinho(request):
    """Página do carrinho: alterar quantidade, remover e conferir o resumo (HU11)."""
    do_cliente = CarrinhoDaLoja(request.session)

    if request.method == "POST":
        _executa_acao(request, do_cliente)
        return redirect("loja:carrinho")

    linhas = do_cliente.linhas()

    return render(request, "loja/carrinho.html", {
        "linhas": linhas,
        "total": do_cliente.total(linhas),
        "quantidade_de_itens": sum(linha["quantidade"] for linha in linhas),
    })


def _executa_acao(request, carrinho):
    acao = request.POST.get("acao")

    if acao not in ("aumentar", "diminuir", "ajustar", "remover"):
        messages.error(request, "Ação desconhecida.")
        return

    produto = _produto_do_pedido(request)

    if acao == "remover":
        carrinho.remover(produto)
        messages.info(request, f"{produto.nome} saiu do carrinho.")
        return

    novas = {
        "aumentar": carrinho.quantidade_de(produto) + 1,
        "diminuir": carrinho.quantidade_de(produto) - 1,
        "ajustar": produto.estoque_atual,  # o saldo caiu: deixa o item com o que ainda existe
    }

    try:
        carrinho.alterar(produto, novas[acao])
    except ErroDeCarrinho as erro:
        messages.error(request, str(erro))


def _categoria_escolhida(valor, categorias):
    """A categoria do ?categoria=, se for uma das que aparecem no filtro; senão, "Todos"."""
    for categoria in categorias:
        if str(categoria.pk) == valor:
            return categoria
    return None


def _filtros(categorias, escolhida, busca, ordem):
    """Botões "Todos" e um por categoria, mantendo a busca e a ordenação atuais."""
    endereco = reverse("loja:catalogo")
    comuns = {"busca": busca} if busca else {}
    if ordem != ORDENACAO_PADRAO:
        comuns["ordem"] = ordem

    def url(categoria=None):
        parametros = dict(comuns, categoria=categoria.pk) if categoria else comuns
        return f"{endereco}?{urlencode(parametros)}" if parametros else endereco

    filtros = [{"nome": "Todos", "url": url(), "ativo": escolhida is None}]
    filtros += [
        {"nome": categoria.nome, "url": url(categoria), "ativo": categoria == escolhida}
        for categoria in categorias
    ]
    return filtros


def _volta_para(request):
    """O ?next= do formulário, desde que aponte para este site; senão, o catálogo."""
    destino = request.POST.get("next", "")
    if url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()},
                                       require_https=request.is_secure()):
        return destino
    return reverse("loja:catalogo")


def _produto_do_pedido(request):
    """Busca o produto pelo id vindo do formulário; qualquer coisa estranha vira 404."""
    try:
        return Produto.objects.select_related("categoria").get(pk=int(request.POST.get("produto")))
    except (TypeError, ValueError, Produto.DoesNotExist):
        raise Http404("Produto não encontrado.")
