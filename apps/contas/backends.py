"""
Backend de autenticação por e-mail (pacote 4.1.1).

O ModelBackend continua configurado em AUTHENTICATION_BACKENDS, então o login por nome de
usuário (usado pela tela do Django Admin) segue funcionando.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

Usuario = get_user_model()


class BackendDeEmail(ModelBackend):
    """Encontra o usuário pelo e-mail, sem diferenciar maiúsculas de minúsculas."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        email = kwargs.get("email") or username
        if not email or not password:
            return None

        try:
            usuario = Usuario._default_manager.get(email__iexact=email)
        except Usuario.DoesNotExist:
            # Mesmo custo de tempo do caminho feliz, para não entregar quais e-mails existem.
            Usuario().set_password(password)
            return None
        except Usuario.MultipleObjectsReturned:
            # O e-mail do usuário padrão do Django não é único: com repetição não dá para
            # saber de quem é a conta, então a entrada por e-mail é recusada.
            return None

        if usuario.check_password(password) and self.user_can_authenticate(usuario):
            return usuario

        return None
