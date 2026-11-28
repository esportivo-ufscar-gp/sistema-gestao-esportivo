"""
Configurações do Sistema de Gestão Integrada Esportivo UFSCar (projeto ESP-2026-01).

Valores sensíveis e que mudam entre ambientes vêm de variáveis de ambiente, lidas do
arquivo .env (veja .env.example). Nunca envie o .env para o repositório.
"""
import os
import warnings
from pathlib import Path

from django.contrib import messages
from dotenv import load_dotenv

from .ambiente import banco_de_dados, enderecos_publicos, env_bool

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# ------------------------------------------------------------------ Segurança
DEBUG = env_bool("DJANGO_DEBUG", False)

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "chave-insegura-somente-para-desenvolvimento"
    else:
        raise RuntimeError("Defina DJANGO_SECRET_KEY no arquivo .env")

# Inclui sozinho o endereço que o Render dá ao site (pacote 3.3); veja config/ambiente.py.
ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS = enderecos_publicos()

# Atrás de um proxy com HTTPS (o Render é um), o Django só sabe que a conexão é segura pelo
# cabeçalho que o proxy envia. Com isso, os cookies de sessão e de CSRF só trafegam por HTTPS.
# O próprio Render já redireciona http:// para https://.
if env_bool("DJANGO_ATRAS_DE_PROXY_HTTPS", env_bool("RENDER")):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

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
    # Serve o CSS e o JS em produção, sem servidor separado (logo depois do SecurityMiddleware,
    # como pede a documentação do WhiteNoise).
    "whitenoise.middleware.WhiteNoiseMiddleware",
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
                "apps.loja.context_processors.carrinho",
                "apps.relatorios.context_processors.navegacao",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# ------------------------------------------------------------------ Banco de dados
# PostgreSQL é o banco oficial do projeto. DB_ENGINE=sqlite é só um atalho para
# começar sem PostgreSQL instalado; os testes de concorrência de estoque (pacote 4.3.2)
# precisam do PostgreSQL, que é o banco usado na integração contínua. No Render, a conexão
# vem pronta na DATABASE_URL (pacote 3.3).
DATABASES = {"default": banco_de_dados(BASE_DIR)}

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
LOGOUT_REDIRECT_URL = "loja:catalogo"

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

# O collectstatic do deploy junta os arquivos em STATIC_ROOT, e o WhiteNoise os serve já
# comprimidos. Sem o "Manifest" no nome: assim os testes não precisam rodar o collectstatic.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

# Fora do deploy (testes e uso local) a pasta staticfiles/ não existe, porque o collectstatic só
# roda no build; o WhiteNoise avisaria isso a cada execução. Só esse aviso é silenciado.
warnings.filterwarnings("ignore", message=r"No directory at: .*staticfiles")

MEDIA_URL = "media/"          # imagens de produtos (pacote 4.2.2)
MEDIA_ROOT = BASE_DIR / "media"

# Com DEBUG=False o Django não serve a media/. No ambiente de demonstração (Render) as fotos
# do catálogo são poucas e pequenas, então o próprio Django as serve (veja core.views.media).
SERVIR_MEDIA = env_bool("DJANGO_SERVIR_MEDIA", env_bool("RENDER"))

# ------------------------------------------------------------------ Loja online
# Mostrados no checkout e na confirmação do pedido (pacote 4.5.3): a única entrega é a
# retirada na loja. Troque os textos provisórios pelos dados reais da loja.
LOJA_ENDERECO = "[Endereço da loja]"
LOJA_HORARIO = "[Horário de funcionamento]"
