"""
Regras de negócio do módulo Contas e acesso.

Pacote 4.1: autenticação (4.1.1) e perfis e permissões (4.1.2).

Os perfis são grupos do Django (CLAUDE.md). Este módulo concentra três coisas:

1. os nomes dos quatro perfis e as permissões de Admin de cada um;
2. a leitura do perfil de um usuário;
3. para onde cada perfil vai depois de entrar no sistema.

Os pacotes seguintes só precisam acrescentar linhas em PERMISSOES_POR_PERFIL e em
DESTINO_POR_PERFIL; nada mais neste arquivo muda.
"""
from django.contrib.auth.models import Group, Permission
from django.db.models import Q
from django.urls import reverse

PERFIL_ADMINISTRADOR = "administrador"
PERFIL_VENDEDOR = "vendedor"
PERFIL_ESTOQUISTA = "estoquista"
PERFIL_CLIENTE = "cliente"

# A ordem também é a de precedência: quem estiver em mais de um grupo assume o primeiro.
PERFIS = (PERFIL_ADMINISTRADOR, PERFIL_VENDEDOR, PERFIL_ESTOQUISTA, PERFIL_CLIENTE)

TODAS_AS_ACOES = ("add", "change", "delete", "view")
SOMENTE_VER = ("view",)

# Perfil -> app da EAP -> ações liberadas no Admin. Os próximos pacotes acrescentam aqui
# os seus apps ("estoque", "vendas", "clientes"); hoje só existem os modelos de produtos.
PERMISSOES_POR_PERFIL = {
    PERFIL_ADMINISTRADOR: {"produtos": TODAS_AS_ACOES},
    PERFIL_VENDEDOR: {"produtos": SOMENTE_VER},
    PERFIL_ESTOQUISTA: {"produtos": SOMENTE_VER},
    PERFIL_CLIENTE: {},  # o cliente usa a loja online, não o Admin
}

# Perfil -> rota inicial depois do login. Trocar quando as telas existirem:
# vendedor -> "vendas:pdv" (4.4.1), estoquista -> "estoque:painel" (4.3.3),
# cliente -> "loja:catalogo" (4.5.1).
DESTINO_POR_PERFIL = {
    PERFIL_ADMINISTRADOR: "admin:index",
    PERFIL_VENDEDOR: "contas:painel",
    PERFIL_ESTOQUISTA: "contas:painel",
    PERFIL_CLIENTE: "contas:painel",
}

DESTINO_PADRAO = "contas:painel"


def criar_perfis():
    """
    Cria (ou atualiza) os quatro grupos de perfil com as suas permissões.

    É idempotente: pode rodar quantas vezes for preciso, inclusive depois de um pacote
    novo acrescentar permissões em PERMISSOES_POR_PERFIL. Devolve {perfil: quantidade
    de permissões} para o comando criar_perfis mostrar o resumo.
    """
    resumo = {}

    for perfil, acoes_por_app in PERMISSOES_POR_PERFIL.items():
        grupo, _ = Group.objects.get_or_create(name=perfil)
        permissoes = []

        for app_label, acoes in acoes_por_app.items():
            filtro = Q()
            for acao in acoes:
                filtro |= Q(codename__startswith=f"{acao}_")
            permissoes.extend(
                Permission.objects.filter(filtro, content_type__app_label=app_label)
            )

        # set() sobrescreve a lista inteira: acrescenta o que falta e tira o que saiu do mapa.
        grupo.permissions.set(permissoes)
        resumo[perfil] = len(permissoes)

    return resumo


def perfil_do_usuario(usuario):
    """
    Devolve o perfil do usuário, ou None se ele não tiver nenhum.

    Superusuário conta como administrador mesmo sem estar no grupo.
    """
    if usuario is None or not usuario.is_authenticated:
        return None

    if usuario.is_superuser:
        return PERFIL_ADMINISTRADOR

    grupos = set(usuario.groups.values_list("name", flat=True))
    for perfil in PERFIS:
        if perfil in grupos:
            return perfil

    return None


def destino_apos_login(usuario):
    """Endereço da página inicial do perfil do usuário, usado depois do login."""
    perfil = perfil_do_usuario(usuario)

    # O Admin exige is_staff; sem isso, um administrador cairia na tela de login do Admin.
    if perfil == PERFIL_ADMINISTRADOR and not usuario.is_staff:
        return reverse(DESTINO_PADRAO)

    return reverse(DESTINO_POR_PERFIL.get(perfil, DESTINO_PADRAO))
