"""
Configurações do Sistema de Gestão Integrada Esportivo UFSCar (projeto ESP-2026-01).

Valores sensíveis e que mudam entre ambientes vêm de variáveis de ambiente, lidas do
arquivo .env (veja .env.example). Nunca envie o .env para o repositório.
"""
import os
from pathlib import Path

from django.contrib import messages
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(nome, padrao=False):
    return os.getenv(nome, str(padrao)).strip().lower() in ("1", "true", "sim", "yes")


def env_list(nome, padrao=""):
    return [item.strip() for item in os.getenv(nome, padrao).split(",") if item.strip()]


# ------------------------------------------------------------------ Segurança
DEBUG = env_bool("DJANGO_DEBUG", False)

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "chave-insegura-somente-para-desenvolvimento"
    else:
        raise RuntimeError("Defina DJANGO_SECRET_KEY no arquivo .env")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

# ------------------------------------------------------------------ Aplicações
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

# Um app por módulo da EAP (ramo 4. Sistema)
PROJECT_APPS = [
    "apps.core",        # páginas gerais e verificação de saúde
    "apps.contas",      # 4.1 Acesso e Segurança
    "apps.produtos",    # 4.2 Produtos
    "apps.estoque",     # 4.3 Estoque
    "apps.vendas",      # 4.4 Vendas na Loja Física (PDV)
    "apps.loja",        # 4.5 Loja Online
    "apps.clientes",    # 4.6 Clientes
    "apps.relatorios",  # 4.7 Relatórios
]

INSTALLED_APPS = DJANGO_APPS + PROJECT_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

# O Bootstrap chama de "danger" o que o Django chama de "error" (alert-danger no base.html).
MESSAGE_TAGS = {messages.ERROR: "danger"}

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# ------------------------------------------------------------------ Banco de dados
# PostgreSQL é o banco oficial do projeto. DB_ENGINE=sqlite é só um atalho para
# começar sem PostgreSQL instalado; os testes de concorrência de estoque (pacote 4.3.2)
# precisam do PostgreSQL, que é o banco usado na integração contínua.
if os.getenv("DB_ENGINE", "postgresql") == "sqlite":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("DB_NAME", "esportivo"),
            "USER": os.getenv("DB_USER", "postgres"),
            "PASSWORD": os.getenv("DB_PASSWORD", ""),
            "HOST": os.getenv("DB_HOST", "localhost"),
            "PORT": os.getenv("DB_PORT", "5432"),
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ------------------------------------------------------------------ Autenticação
# O backend de e-mail atende a tela de entrada do sistema (pacote 4.1.1); o ModelBackend
# continua atendendo o login por nome de usuário da tela do Django Admin.
AUTHENTICATION_BACKENDS = [
    "apps.contas.backends.BackendDeEmail",
    "django.contrib.auth.backends.ModelBackend",
]

LOGIN_URL = "contas:entrar"
LOGIN_REDIRECT_URL = "contas:painel"   # usado quando o perfil não tem destino próprio
LOGOUT_REDIRECT_URL = "core:home"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ------------------------------------------------------------------ Idioma e fuso
LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

# ------------------------------------------------------------------ Arquivos estáticos e mídia
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"          # imagens de produtos (pacote 4.2.2)
MEDIA_ROOT = BASE_DIR / "media"
