"""Ponto de entrada WSGI, usado na hospedagem do ambiente de demonstração (pacote 3.3)."""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_wsgi_application()
