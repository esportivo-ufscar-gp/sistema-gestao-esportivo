"""
Views do módulo Contas e acesso.

Pacote 4.1: autenticação (4.1.1) e perfis e permissões (4.1.2).

As views só recebem a requisição, chamam o serviço e mostram o resultado (CLAUDE.md).
O login e o logout são as views prontas do Django; aqui só trocamos o formulário e o
destino depois da entrada.
"""
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.shortcuts import render

from .forms import FormularioDeEntrada
from .services import destino_apos_login, perfil_do_usuario


class EntrarView(LoginView):
    """Tela de entrada com e-mail e senha (HU01)."""

    template_name = "registration/login.html"
    authentication_form = FormularioDeEntrada
    redirect_authenticated_user = True

    def get_success_url(self):
        # O ?next= continua valendo (é como o login_required devolve o usuário à página pedida);
        # sem ele, cada perfil vai para a sua página inicial.
        return self.get_redirect_url() or destino_apos_login(self.request.user)


@login_required
def painel(request):
    """
    Página inicial provisória de vendedor, estoquista e cliente.

    Será substituída pelo PDV (4.4.1), pelo painel de estoque (4.3.3) e pelo catálogo da
    loja online (4.5.1); o mapeamento fica em services.DESTINO_POR_PERFIL.
    """
    return render(request, "contas/painel.html", {"perfil": perfil_do_usuario(request.user)})
