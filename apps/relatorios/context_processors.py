"""
Dados de navegação do módulo Relatórios (pacote 4.7).

O cabeçalho das telas internas mostra o link "Relatórios" só para o administrador.
"""
from apps.contas.services import PERFIL_ADMINISTRADOR, perfil_do_usuario


def navegacao(request):
    usuario = getattr(request, "user", None)
    return {"pode_ver_relatorios": perfil_do_usuario(usuario) == PERFIL_ADMINISTRADOR}
