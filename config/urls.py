from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "Esportivo UFSCar | Administração"
admin.site.site_title = "Esportivo UFSCar"
admin.site.index_title = "Gestão da loja"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("contas/", include("apps.contas.urls")),
    path("clientes/", include("apps.clientes.urls")),
    path("estoque/", include("apps.estoque.urls")),
    path("vendas/", include("apps.vendas.urls")),
    path("", include("apps.core.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
