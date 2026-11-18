"""
Registro dos modelos do módulo Clientes no Django Admin.

Pacote 4.6: cadastro com consentimento LGPD (4.6.1) e histórico de compras (4.6.2).
"""
from django.contrib import admin

from apps.loja.models import PedidoOnline

from .models import Cliente


class PedidosDoClienteInline(admin.TabularInline):
    """
    Histórico de compras do cliente na página dele (HU15), só para consulta.

    Usa o proxy PedidoOnline (4.5.4), que já enxerga só o canal online: as vendas do PDV não
    identificam o cliente. O link de cada linha abre o pedido na gestão de pedidos, onde ficam
    as ações de retirada e cancelamento.
    """

    model = PedidoOnline
    fk_name = "cliente"
    fields = ("numero_formatado", "criado_em", "status", "total")
    readonly_fields = fields
    ordering = ("-criado_em", "-id")
    extra = 0
    can_delete = False
    show_change_link = True
    verbose_name = "pedido"
    verbose_name_plural = "pedidos online"

    @admin.display(description="número")
    def numero_formatado(self, pedido):
        return pedido.numero_formatado

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ("nome", "email", "telefone", "consentimento_em", "criado_em")
    search_fields = ("nome", "email")
    readonly_fields = ("consentimento_em", "criado_em")
    ordering = ("nome",)
    inlines = [PedidosDoClienteInline]

    def has_add_permission(self, request):
        # O cliente nasce pelo cadastro da loja ou pelo checkout, com o consentimento LGPD dado
        # por ele mesmo. A equipe não registra consentimento em nome de ninguém; além disso,
        # consentimento_em é obrigatório e só de leitura, e o formulário daria erro ao salvar.
        return False
