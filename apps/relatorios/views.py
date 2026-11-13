"""
Views do módulo Relatórios.

Pacote 4.7: a tela /relatorios/, só para o administrador, com as vendas por período e canal
(4.7.1) e a posição de estoque (4.7.2), como no protótipo de tela.

A view só lê os filtros, chama o serviço e mostra o resultado (CLAUDE.md).
"""
from django.shortcuts import render

from apps.contas.decorators import perfil_requerido
from apps.contas.services import PERFIL_ADMINISTRADOR

from .forms import FiltroDeEstoque, FiltroDeVendas
from .services import posicao_de_estoque, resumo_da_posicao, vendas_por_periodo


@perfil_requerido(PERFIL_ADMINISTRADOR)
def painel(request):
    filtro_de_vendas = FiltroDeVendas(request.GET)
    filtro_de_estoque = FiltroDeEstoque(request.GET)

    relatorio_de_vendas = None
    if filtro_de_vendas.is_valid():
        dados = filtro_de_vendas.cleaned_data
        relatorio_de_vendas = vendas_por_periodo(dados["data_inicial"], dados["data_final"], dados["canal"])

    # Categoria inválida ou inativa: a tela mostra o erro e volta para todas as categorias.
    categoria, incluir_inativos = filtro_de_estoque.filtros()
    produtos = list(posicao_de_estoque(categoria, incluir_inativos))

    return render(request, "relatorios/painel.html", {
        "filtro_de_vendas": filtro_de_vendas,
        "filtro_de_estoque": filtro_de_estoque,
        "vendas": relatorio_de_vendas,
        "categoria": categoria,
        "incluir_inativos": incluir_inativos,
        "produtos": produtos,
        "resumo_de_estoque": resumo_da_posicao(produtos),
    })
