"""
Registro dos modelos do módulo Vendas (PDV) no Django Admin.

Pacote 4.4: registro de venda (4.4.1) e cancelamento (4.4.2) na loja física.

A venda é histórico: no Admin ela é só de consulta. Quem cria venda é o PDV (e, no pacote
4.5, o checkout da loja online); quem cancela é o serviço, que devolve os itens ao estoque.
"""
from django.contrib import admin

from .models import ItemVenda, Venda


class ItemVendaInline(admin.TabularInline):
    model = ItemVenda
    extra = 0
    readonly_fields = ("produto", "quantidade", "preco_unitario", "subtotal")
    can_delete = False

    @admin.display(description="subtotal")
    def subtotal(self, item):
        return item.subtotal

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Venda)
class VendaAdmin(admin.ModelAdmin):
    list_display = ("numero_formatado", "criado_em", "canal", "status", "forma_pagamento", "total", "vendedor")
    list_filter = ("canal", "status", "forma_pagamento", "criado_em")
    search_fields = ("numero",)
    list_select_related = ("vendedor",)
    date_hierarchy = "criado_em"
    inlines = [ItemVendaInline]
    readonly_fields = (
        "numero", "canal", "status", "forma_pagamento", "total", "vendedor",
        "criado_em", "cancelada_em", "cancelada_por",
    )

    @admin.display(description="número", ordering="numero")
    def numero_formatado(self, venda):
        return venda.numero_formatado

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
