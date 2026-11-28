from django.conf import settings
from django.db import DatabaseError, connection
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.views.static import serve


def media(request, caminho):
    """
    Serve as fotos dos produtos (pasta media/).

    Em desenvolvimento (DEBUG) e no ambiente de demonstração (SERVIR_MEDIA, ligado sozinho no
    Render). Fora disso responde 404, como o Django faz por padrão. O serve do Django recusa
    caminhos que saiam da pasta media/.
    """
    if not (settings.DEBUG or settings.SERVIR_MEDIA):
        raise Http404
    return serve(request, caminho, document_root=settings.MEDIA_ROOT)


def home(request):
    """A página inicial é o catálogo da loja online (pacote 4.5.1)."""
    return redirect("loja:catalogo")


def banco_disponivel():
    """Confirma que a conexão com o banco de dados está funcionando."""
    try:
        connection.ensure_connection()
    except DatabaseError:
        return False
    return True


def health(request):
    """Verificação de saúde usada para conferir o ambiente de demonstração (pacote 3.3)."""
    if banco_disponivel():
        return JsonResponse({"status": "ok", "banco_de_dados": "ok"})
    return JsonResponse({"status": "erro", "banco_de_dados": "indisponível"}, status=503)


def termos(request):
    """Exibe a página dos Termos de Uso do sistema."""
    return render(request, "core/termos.html")


def privacidade(request):
    """Exibe a página da Política de Privacidade e LGPD."""
    return render(request, "core/privacidade.html")
