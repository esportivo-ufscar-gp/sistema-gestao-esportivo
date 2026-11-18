"""
Views do módulo Clientes.

Pacote 4.6.1: cadastro de cliente com consentimento LGPD (HU14).
Pacote 4.6.2: histórico de compras, "Meus pedidos" (HU15).
"""
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.urls import reverse

from apps.contas.decorators import perfil_requerido
from apps.contas.services import PERFIL_CLIENTE, destino_apos_login
from apps.vendas.models import StatusDeVenda

from .forms import FormularioDeCadastroCliente
from .services import STATUS_DO_HISTORICO, cadastrar_cliente, contagem_por_status, pedidos_do_cliente

# Texto de cada botão de filtro de "Meus pedidos", na ordem da tela.
ROTULOS_DOS_FILTROS = {
    StatusDeVenda.AGUARDANDO_RETIRADA: "Aguardando retirada",
    StatusDeVenda.RETIRADA: "Retirados",
    StatusDeVenda.CANCELADA: "Cancelados",
}


def cadastro(request):
    """Tela de cadastro de cliente (HU14). Visitante cadastra-se; usuário logado é redirecionado."""
    if request.user.is_authenticated:
        return redirect(destino_apos_login(request.user))

    if request.method == "POST":
        form = FormularioDeCadastroCliente(request.POST)
        if form.is_valid():
            try:
                usuario, cliente = cadastrar_cliente(
                    nome=form.cleaned_data["nome"],
                    email=form.cleaned_data["email"],
                    telefone=form.cleaned_data["telefone"],
                    senha=form.cleaned_data["senha"],
                )
                login(request, usuario, backend="apps.contas.backends.BackendDeEmail")
                messages.success(request, f"Conta criada com sucesso! Seja bem-vindo(a), {cliente.nome}.")
                return redirect(destino_apos_login(usuario))
            except ValidationError as erro:
                # Erros com campo (e-mail, senha) vão para o campo; os demais, para o topo do formulário.
                form.add_error(None, erro)
    else:
        form = FormularioDeCadastroCliente()

    return render(request, "clientes/cadastro.html", {"form": form})


@perfil_requerido(PERFIL_CLIENTE)
def meus_pedidos(request):
    """
    Tela "Meus pedidos" (HU15): os pedidos online do cliente logado, com filtro por status.

    A equipe recebe 403 e o visitante vai para a tela de entrada (perfil_requerido).
    """
    status = request.GET.get("status", "")
    if status not in STATUS_DO_HISTORICO:
        status = ""

    contagem = contagem_por_status(request.user)

    return render(request, "clientes/meus_pedidos.html", {
        "pedidos": pedidos_do_cliente(request.user, status=status),
        "status_atual": status,
        "filtros": _filtros(contagem, status),
        "tem_pedidos": contagem["todos"] > 0,
        "loja_endereco": settings.LOJA_ENDERECO,
        "loja_horario": settings.LOJA_HORARIO,
    })


def _filtros(contagem, status_atual):
    """Botões "Todos (N)" e um por status, com o endereço e a marca do filtro ativo."""
    endereco = reverse("clientes:meus_pedidos")
    filtros = [{"rotulo": "Todos", "quantidade": contagem["todos"], "url": endereco, "ativo": not status_atual}]
    filtros += [
        {
            "rotulo": ROTULOS_DOS_FILTROS[status],
            "quantidade": contagem[status],
            "url": f"{endereco}?status={status}",
            "ativo": status == status_atual,
        }
        for status in STATUS_DO_HISTORICO
    ]
    return filtros
