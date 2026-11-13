"""
Views do módulo Clientes.

Pacote 4.6.1: cadastro de cliente com consentimento LGPD (HU14).
"""
from django.contrib import messages
from django.contrib.auth import login
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render

from apps.contas.decorators import perfil_requerido
from apps.clientes.services import pedidos_do_cliente
from apps.contas.services import destino_apos_login
from .forms import FormularioDeCadastroCliente
from .services import cadastrar_cliente


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


@perfil_requerido('cliente')
def meus_pedidos(request):
    """
    Exibe a tela 'Meus pedidos' para o cliente autenticado,
    com suporte a filtros por status e contadores.
    """
    status_filtro = request.GET.get('status', '')
    if status_filtro not in ['aguardando_retirada', 'retirada', 'cancelada']:
        status_filtro = None

    pedidos = pedidos_do_cliente(request.user, status=status_filtro)
    todos_pedidos = pedidos_do_cliente(request.user)

    counts = {
        'todos': todos_pedidos.count(),
        'aguardando': todos_pedidos.filter(status='aguardando_retirada').count(),
        'retirados': todos_pedidos.filter(status='retirada').count(),
        'cancelados': todos_pedidos.filter(status='cancelada').count(),
    }

    context = {
        'pedidos': pedidos,
        'status_atual': status_filtro or '',
        'counts': counts,
    }
    return render(request, 'clientes/meus_pedidos.html', context)
