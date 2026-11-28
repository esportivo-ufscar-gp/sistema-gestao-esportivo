from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from apps.core.views import media

admin.site.site_header = "Esportivo UFSCar | Administração"
admin.site.site_title = "Esportivo UFSCar"
admin.site.index_title = "Gestão da loja"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("contas/", include("apps.contas.urls")),
    path("clientes/", include("apps.clientes.urls")),
    path("estoque/", include("apps.estoque.urls")),
    path("loja/", include("apps.loja.urls")),
    path("relatorios/", include("apps.relatorios.urls")),
    path("vendas/", include("apps.vendas.urls")),
    # Fotos dos produtos: a view só responde com DEBUG ou SERVIR_MEDIA ligados.
    path(f"{settings.MEDIA_URL.strip('/')}/<path:caminho>", media, name="media"),
    path("", include("apps.core.urls")),
]
