from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


class HealthCheckTests(TestCase):
    def test_responde_ok_quando_banco_esta_disponivel(self):
        resposta = self.client.get(reverse("core:health"))

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.json(), {"status": "ok", "banco_de_dados": "ok"})

    def test_responde_503_quando_banco_esta_indisponivel(self):
        with mock.patch("apps.core.views.banco_disponivel", return_value=False):
            resposta = self.client.get(reverse("core:health"))

        self.assertEqual(resposta.status_code, 503)
        self.assertEqual(resposta.json()["banco_de_dados"], "indisponível")


class HomeTests(TestCase):
    def test_pagina_inicial_redireciona_para_o_catalogo(self):
        resposta = self.client.get(reverse("core:home"))

        self.assertRedirects(resposta, reverse("loja:catalogo"))

    def test_pagina_inicial_redireciona_tambem_quem_entrou(self):
        usuario = User.objects.create_user("cliente", "cliente@exemplo.com", "senha-de-teste-123")
        self.client.force_login(usuario)

        resposta = self.client.get(reverse("core:home"))

        self.assertRedirects(resposta, reverse("loja:catalogo"))
