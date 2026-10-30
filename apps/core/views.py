from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.shortcuts import render


def home(request):
    return render(request, "core/home.html")


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
