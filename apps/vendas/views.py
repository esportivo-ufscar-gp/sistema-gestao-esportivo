"""
Views do módulo Vendas (PDV).

Pacote 4.4: a tela do balcão em /vendas/pdv/, para vendedor e administrador.

A view só recebe a requisição, chama o serviço e mostra o resultado (CLAUDE.md). Ela cuida da
"Venda atual" na sessão; quem grava venda e mexe em estoque é apps/vendas/services.py.
"""
from urllib.parse import urlencode

from django.contrib import messages
from django.db.models import Q
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.formats import number_format

from apps.contas.decorators import perfil_requerido
from apps.contas.services import PERFIL_ADMINISTRADOR, PERFIL_VENDEDOR
from apps.estoque.services import ErroDeEstoque
from apps.produtos.models import Produto

from .carrinho import CarrinhoDoPDV
from .models import FormaDePagamento, Venda
from .services import ErroDeVenda, cancelar_venda, registrar_venda_pdv, ultimas_vendas_do_pdv


@perfil_requerido(PERFIL_VENDEDOR, PERFIL_ADMINISTRADOR)
def pdv(request):
    """Tela do PDV: busca de produtos, venda atual, pagamento e últimas vendas."""
    if request.method == "POST":
        busca = request.POST.get("busca", "").strip()
        _executa_acao(request)

        # Depois de agir, volta para a tela por GET (sem reenvio ao atualizar a página),
        # mantendo a busca que o vendedor já tinha feito.
        endereco = reverse("vendas:pdv")
        return redirect(f"{endereco}?{urlencode({'busca': busca})}" if busca else endereco)

    busca = request.GET.get("busca", "").strip()
    carrinho = CarrinhoDoPDV(request.session)
    linhas = carrinho.linhas()

    return render(request, "vendas/pdv.html", {
        "busca": busca,
        "resultados": _procura_produtos(busca),
        "linhas": linhas,
        "total": carrinho.total(linhas),
        "formas_de_pagamento": FormaDePagamento.choices,
        "ultimas_vendas": ultimas_vendas_do_pdv(),
    })


def _procura_produtos(busca):
    """Produtos ativos que casam com o nome ou com o código; sem busca, mostra todos."""
    produtos = Produto.objects.filter(ativo=True).select_related("categoria").order_by("nome")

    if busca:
        produtos = produtos.filter(Q(nome__icontains=busca) | Q(codigo__icontains=busca))

    return produtos


def _executa_acao(request):
    acao = request.POST.get("acao")
    carrinho = CarrinhoDoPDV(request.session)

    if acao == "limpar":
        carrinho.limpar()
        messages.info(request, "Venda atual limpa.")
    elif acao == "finalizar":
        _finaliza(request, carrinho)
    elif acao == "cancelar":
        _cancela(request)
    elif acao in ("adicionar", "aumentar", "diminuir", "remover"):
        _mexe_no_carrinho(request, carrinho, acao)
    else:
        messages.error(request, "Ação desconhecida.")


def _mexe_no_carrinho(request, carrinho, acao):
    produto = _produto_do_pedido(request)
    quantidade_antes = carrinho.quantidade_de(produto)

    if acao == "remover":
        carrinho.remover(produto)
        messages.info(request, f"{produto.nome} saiu da venda.")
        return

    if acao == "diminuir":
        carrinho.definir(produto, quantidade_antes - 1)
        return

    quantidade = carrinho.acrescentar(produto)
    if quantidade == quantidade_antes:
        messages.error(
            request,
            f"{produto.nome} tem {produto.estoque_atual} em estoque; a venda não pode passar disso.",
        )


def _finaliza(request, carrinho):
    try:
        venda = registrar_venda_pdv(
            request.user,
            carrinho.pares(),
            request.POST.get("forma_pagamento", ""),
        )
    except (ErroDeVenda, ErroDeEstoque) as erro:
        messages.error(request, str(erro))
        return

    carrinho.limpar()
    messages.success(
        request,
        f"Venda {venda.numero_formatado} finalizada no total de R$ {number_format(venda.total, 2)}.",
    )


def _cancela(request):
    venda = _objeto_do_pedido(Venda, request.POST.get("venda"))

    try:
        cancelar_venda(venda, request.user)
    except ErroDeVenda as erro:
        messages.error(request, str(erro))
        return

    messages.success(request, f"Venda {venda.numero_formatado} cancelada; os itens voltaram ao estoque.")


def _produto_do_pedido(request):
    return _objeto_do_pedido(Produto, request.POST.get("produto"))


def _objeto_do_pedido(modelo, valor):
    """Busca o objeto pelo id vindo do formulário; qualquer coisa estranha vira 404."""
    try:
        return modelo.objects.get(pk=int(valor))
    except (TypeError, ValueError, modelo.DoesNotExist):
        raise Http404(f"{modelo._meta.verbose_name} não encontrada.")
