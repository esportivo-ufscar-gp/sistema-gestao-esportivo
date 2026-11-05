"""
Views do módulo Loja online.

Pacote 4.5: catálogo em /loja/ (4.5.1), carrinho em /loja/carrinho/ (4.5.2), checkout em
/loja/checkout/ e confirmação em /loja/pedidos/<numero>/confirmado/ (4.5.3), abertos a
visitantes.

A view só recebe a requisição, chama o serviço e mostra o resultado (CLAUDE.md). O carrinho
fica na sessão e não mexe em estoque; quem confere o saldo é apps/loja/carrinho.py, e quem grava
o pedido e baixa o estoque é services.confirmar_pedido.
"""
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.clientes.services import (
    ConsentimentoObrigatorio,
    EmailDeUmaConta,
    ErroDeIdentificacao,
    cliente_da_conta,
)
from apps.estoque.services import ErroDeEstoque
from apps.produtos.models import Produto
from apps.vendas.models import Venda
from apps.vendas.services import ErroDeVenda

from .carrinho import CarrinhoDaLoja, ErroDeCarrinho
from .forms import FormularioDeCheckout
from .services import (
    ORDENACAO_PADRAO,
    ORDENACOES,
    ROTULOS_DAS_ORDENACOES,
    ProdutoForaDeVenda,
    categorias_do_catalogo,
    confirmar_pedido,
    produtos_do_catalogo,
    rotulo_do_pagamento,
)

# Números dos pedidos feitos nesta sessão: é o que deixa o visitante ver a confirmação.
CHAVE_DOS_PEDIDOS = "pedidos_confirmados"


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


def checkout(request):
    """Identificação, retirada na loja e pagamento simulado (HU12)."""
    cesta = CarrinhoDaLoja(request.session)
    linhas = cesta.linhas()

    # No GET, o carrinho precisa estar em ordem; no POST, quem decide o saldo é o serviço,
    # com os produtos bloqueados, e a mensagem diz qual produto faltou.
    problema = _impede_o_checkout(request.user, linhas, conferir_saldo=request.method != "POST")
    if problema:
        messages.error(request, problema)
        return redirect("loja:carrinho")

    cliente = cliente_da_conta(request.user) if request.user.is_authenticated else None
    dados = request.POST if request.method == "POST" else None  # POST vazio também é validado
    formulario = FormularioDeCheckout(dados, identificado=cliente is not None)
    email_de_uma_conta = False

    if request.method == "POST" and formulario.is_valid():
        try:
            venda = confirmar_pedido(
                request.user,
                cesta.pares(linhas),
                formulario.cleaned_data["forma_pagamento"],
                formulario.dados_do_visitante(),
            )
        except EmailDeUmaConta as erro:
            formulario.add_error("email", str(erro))
            email_de_uma_conta = True
        except ConsentimentoObrigatorio as erro:
            formulario.add_error("consentimento", str(erro))
        except (ErroDeEstoque, ProdutoForaDeVenda, ErroDeIdentificacao) as erro:
            # Faltou saldo (alguém comprou antes) ou o produto saiu de venda: o carrinho fica
            # como estava, para o cliente ajustar.
            messages.error(request, str(erro))
            return redirect("loja:carrinho")
        except ErroDeVenda as erro:
            formulario.add_error(None, str(erro))
        else:
            cesta.limpar()
            _lembra_o_pedido(request, venda)
            return redirect("loja:pedido_confirmado", numero=venda.numero)

    return render(request, "loja/checkout.html", {
        "formulario": formulario,
        "cliente": cliente,
        "linhas": linhas,
        "total": cesta.total(linhas),
        "quantidade_de_itens": sum(linha["quantidade"] for linha in linhas),
        "email_de_uma_conta": email_de_uma_conta,
        "entrar_e_voltar": f"{reverse('contas:entrar')}?{urlencode({'next': reverse('loja:checkout')})}",
        "loja_endereco": settings.LOJA_ENDERECO,
        "loja_horario": settings.LOJA_HORARIO,
    })


def pedido_confirmado(request, numero):
    """
    Confirmação do pedido (HU12). Só quem fez o pedido vê: o cliente logado dono dele ou o
    visitante na mesma sessão; os outros recebem 404, sem saber se o número existe.
    """
    venda = get_object_or_404(Venda.objects.online().select_related("cliente"), numero=numero)

    if not _fez_o_pedido(request, venda):
        raise Http404("Pedido não encontrado.")

    return render(request, "loja/pedido_confirmado.html", {
        "venda": venda,
        "itens": venda.itens.select_related("produto__categoria"),
        "forma_pagamento": rotulo_do_pagamento(venda.forma_pagamento),
        "loja_endereco": settings.LOJA_ENDERECO,
        "loja_horario": settings.LOJA_HORARIO,
    })


def _impede_o_checkout(usuario, linhas, conferir_saldo):
    """O motivo para não abrir o checkout, ou None se estiver tudo certo."""
    if usuario.is_authenticated:
        try:
            cliente_da_conta(usuario)
        except ErroDeIdentificacao as erro:
            return str(erro)

    if not linhas:
        return "Seu carrinho está vazio. Escolha os produtos antes de continuar."

    if conferir_saldo and any(linha["aviso"] for linha in linhas):
        return "Alguns itens do carrinho mudaram de estoque. Ajuste-os antes de continuar."

    return None


def _lembra_o_pedido(request, venda):
    numeros = request.session.get(CHAVE_DOS_PEDIDOS, [])
    request.session[CHAVE_DOS_PEDIDOS] = numeros + [venda.numero]


def _fez_o_pedido(request, venda):
    if venda.numero in request.session.get(CHAVE_DOS_PEDIDOS, []):
        return True

    usuario = request.user
    return usuario.is_authenticated and venda.cliente.usuario_id == usuario.pk


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
