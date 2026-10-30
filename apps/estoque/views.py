"""
Views do módulo Estoque.

Pacote 4.3: o painel de estoque em /estoque/, para estoquista e administrador.

A view só recebe a requisição, chama o serviço e mostra o resultado (CLAUDE.md): quem muda
saldo é sempre apps/estoque/services.py.
"""
from django.contrib import messages
from django.shortcuts import redirect, render

from apps.contas.decorators import perfil_requerido
from apps.contas.services import PERFIL_ADMINISTRADOR, PERFIL_ESTOQUISTA

from .forms import ENTRADA, FormularioDeMovimento
from .services import (
    ErroDeEstoque,
    produtos_em_alerta,
    registrar_ajuste,
    registrar_entrada,
    saldo_por_produto,
)


@perfil_requerido(PERFIL_ESTOQUISTA, PERFIL_ADMINISTRADOR)
def painel(request):
    """Painel de estoque: movimentar, ver os alertas e conferir o saldo de cada produto."""
    formulario = FormularioDeMovimento()

    if request.method == "POST":
        formulario = FormularioDeMovimento(request.POST)

        if formulario.is_valid():
            try:
                movimento = _movimenta(formulario.cleaned_data, request.user)
            except ErroDeEstoque as erro:
                messages.error(request, str(erro))
            else:
                messages.success(request, _confirmacao(movimento))
                return redirect("estoque:painel")
        else:
            messages.error(request, "Confira os dados do formulário.")

    return render(request, "estoque/painel.html", {
        "formulario": formulario,
        "alertas": produtos_em_alerta(),
        "produtos": saldo_por_produto(),
    })


def _movimenta(dados, usuario):
    """Chama a função do serviço que corresponde ao tipo escolhido no formulário."""
    registrar = registrar_entrada if dados["tipo"] == ENTRADA else registrar_ajuste

    return registrar(
        dados["produto"],
        dados["quantidade"],
        usuario=usuario,
        motivo=dados["motivo"],
    )


def _confirmacao(movimento):
    acao = "Entrada" if movimento.soma_ao_saldo else "Saída"

    return (
        f"{acao} de {movimento.quantidade} unidade(s) de {movimento.produto.nome} registrada. "
        f"Saldo atual: {movimento.saldo_apos}."
    )
