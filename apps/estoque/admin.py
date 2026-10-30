"""
Registro dos modelos do módulo Estoque no Django Admin.

Pacote 4.3: entradas (4.3.1), baixa e sincronização entre canais (4.3.2), estoque mínimo e
alertas (4.3.3).

O movimento é histórico: aqui ele é só de leitura. Quem cria movimento é o serviço de
estoque, pelo painel em /estoque/ ou pela venda.
"""
from django.contrib import admin

from .models import MovimentoEstoque


@admin.register(MovimentoEstoque)
class MovimentoEstoqueAdmin(admin.ModelAdmin):
    list_display = ("criado_em", "produto", "tipo", "quantidade", "saldo_apos", "usuario", "motivo")
    list_filter = ("tipo", "produto")
    search_fields = ("produto__nome", "produto__codigo", "motivo")
    list_select_related = ("produto", "usuario")
    date_hierarchy = "criado_em"
    readonly_fields = ("produto", "tipo", "quantidade", "saldo_apos", "usuario", "motivo", "criado_em")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
