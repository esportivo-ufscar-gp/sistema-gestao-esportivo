"""
Registro dos modelos do módulo Loja online no Django Admin.

Pacote 4.5.4: gestão de pedidos. A lista mostra só os pedidos do canal online, com filtros por
status e por data e as ações "Marcar como retirado" e "Cancelar pedido". O pedido é histórico:
nenhum campo é editado à mão; quem muda o status (e devolve o estoque no cancelamento) são os
serviços de apps/vendas/services.py.
"""
from django.contrib import admin, messages
from django.db.models import Q

from apps.vendas.admin import ItemVendaInline
from apps.vendas.models import StatusDeVenda
from apps.vendas.services import ErroDeVenda, cancelar_venda, marcar_retirado

from .models import PedidoOnline


class StatusDoPedidoFilter(admin.SimpleListFilter):
    """Os três status que um pedido online pode ter (o "concluída" é só do PDV)."""

    title = "status"
    parameter_name = "status"
    STATUS = (StatusDeVenda.AGUARDANDO_RETIRADA, StatusDeVenda.RETIRADA, StatusDeVenda.CANCELADA)

    def lookups(self, request, model_admin):
        return [(status.value, status.label) for status in self.STATUS]

    def queryset(self, request, queryset):
        if self.value() in StatusDeVenda.values:
            return queryset.filter(status=self.value())
        return queryset


@admin.register(PedidoOnline)
class PedidoOnlineAdmin(admin.ModelAdmin):
    list_display = ("numero_formatado", "criado_em", "cliente", "forma_pagamento", "total", "status")
    list_filter = (StatusDoPedidoFilter, "criado_em")
    date_hierarchy = "criado_em"
    search_fields = ("cliente__nome", "cliente__email")
    search_help_text = "Busque pelo número (ex.: 43 ou #0043), pelo nome ou pelo e-mail do cliente."
    list_select_related = ("cliente",)
    inlines = [ItemVendaInline]
    actions = ["marcar_como_retirado", "cancelar_pedido"]
    fields = (
        "numero", "status", "cliente", "forma_pagamento", "total",
        "criado_em", "retirada_em", "cancelada_em", "cancelada_por",
    )
    readonly_fields = fields

    @admin.display(description="número", ordering="numero")
    def numero_formatado(self, pedido):
        return pedido.numero_formatado

    def get_search_results(self, request, queryset, search_term):
        """Além do nome e do e-mail, acha o pedido pelo número, com ou sem "#" e zeros."""
        resultado, tem_duplicados = super().get_search_results(request, queryset, search_term)

        numero = search_term.strip().lstrip("#")
        if numero.isdigit():
            resultado = queryset.filter(
                Q(pk__in=resultado.values("pk")) | Q(numero=int(numero))
            )

        return resultado, tem_duplicados

    @admin.action(description="Marcar como retirado", permissions=["change"])
    def marcar_como_retirado(self, request, queryset):
        self._aplica(request, queryset, marcar_retirado, "marcado(s) como retirado(s)")

    @admin.action(description="Cancelar pedido", permissions=["change"])
    def cancelar_pedido(self, request, queryset):
        self._aplica(request, queryset, cancelar_venda, "cancelado(s); os itens voltaram ao estoque")

    def _aplica(self, request, queryset, servico, feito):
        """Chama o serviço pedido a pedido e conta, na mensagem, o que deu certo e o que não deu."""
        alterados, recusados = [], []

        for pedido in queryset.order_by("numero"):
            try:
                servico(pedido, request.user)
            except ErroDeVenda as erro:
                recusados.append(str(erro))
            else:
                alterados.append(pedido.numero_formatado)

        if alterados:
            self.message_user(
                request, f"{len(alterados)} pedido(s) {feito}: {', '.join(alterados)}.", messages.SUCCESS
            )
        if recusados:
            self.message_user(
                request, f"{len(recusados)} pedido(s) não puderam ser alterados: {' '.join(recusados)}",
                messages.WARNING,
            )

    def has_add_permission(self, request):
        return False  # pedido só nasce pelo checkout

    def has_delete_permission(self, request, obj=None):
        return False  # pedido é histórico: cancela-se, não se exclui

    def change_view(self, request, object_id, form_url="", extra_context=None):
        # Todos os campos são só de leitura; não há o que salvar no formulário.
        extra_context = {
            **(extra_context or {}),
            "show_save": False,
            "show_save_and_continue": False,
            "show_save_and_add_another": False,
        }
        return super().change_view(request, object_id, form_url, extra_context)
