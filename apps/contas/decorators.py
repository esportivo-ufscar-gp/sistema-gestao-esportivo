"""
Decorators de controle de acesso por perfil (pacote 4.1.2).

As telas dos próximos pacotes (PDV, painel de estoque, área do cliente) usam
perfil_requerido para que um usuário não entre em uma página de outro perfil.
"""
from functools import wraps

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied

from .services import perfil_do_usuario


def perfil_requerido(*perfis):
    """
    Libera a view só para os perfis informados.

    Visitante sem login vai para a tela de entrada (com ?next=); usuário logado em um perfil
    diferente recebe 403.

    Uso:
        @perfil_requerido(PERFIL_VENDEDOR, PERFIL_ADMINISTRADOR)
        def pdv(request):
            ...
    """
    def decorador(view):
        @wraps(view)
        def protegida(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)

            if perfil_do_usuario(request.user) not in perfis:
                raise PermissionDenied("Esta página é de outro perfil.")

            return view(request, *args, **kwargs)

        return protegida

    return decorador
