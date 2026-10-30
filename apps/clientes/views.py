"""
Views do módulo Clientes.

Pacote 4.6.1: cadastro de cliente com consentimento LGPD (HU14).
"""
from django.contrib import messages
from django.contrib.auth import login
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render

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
                if hasattr(erro, "message_dict"):
                    for campo, mensagens in erro.message_dict.items():
                        for msg in mensagens:
                            form.add_error(campo, msg)
                else:
                    form.add_error(None, erro.message)
    else:
        form = FormularioDeCadastroCliente()

    return render(request, "clientes/cadastro.html", {"form": form})
