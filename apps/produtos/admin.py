"""
Registro dos modelos do módulo Produtos no Django Admin.

Pacote 4.2: categorias (4.2.1) e produtos (4.2.2).

Os cadastros internos ficam no Admin, com permissões por grupo. O saldo de estoque aparece
aqui somente para leitura: quem altera o saldo é o serviço de estoque (pacote 4.3).
"""
from django.contrib import admin
from django.db.models import Count

from .models import Categoria, Produto


@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ("nome", "ativa", "total_de_produtos")
    list_filter = ("ativa",)
    search_fields = ("nome",)
    ordering = ("nome",)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_total_de_produtos=Count("produtos"))

    @admin.display(description="produtos vinculados", ordering="_total_de_produtos")
    def total_de_produtos(self, categoria):
        return categoria._total_de_produtos


@admin.register(Produto)
class ProdutoAdmin(admin.ModelAdmin):
    list_display = ("codigo", "nome", "categoria", "preco", "estoque_atual", "ativo")
    list_filter = ("categoria", "ativo")
    search_fields = ("nome", "codigo")
    list_select_related = ("categoria",)
    ordering = ("nome",)
    # O saldo só muda pelo serviço de estoque; no Admin ele é apenas informativo.
    readonly_fields = ("estoque_atual",)
    fieldsets = (
        ("Identificação", {"fields": ("codigo", "nome", "categoria", "ativo")}),
        ("Apresentação", {"fields": ("descricao", "imagem")}),
        ("Preço", {"fields": ("preco",)}),
        ("Estoque", {"fields": ("estoque_atual", "estoque_minimo")}),
    )
