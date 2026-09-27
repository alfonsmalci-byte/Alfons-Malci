import subprocess
import tempfile
import unittest
from pathlib import Path

from nube_luna import comprobar_nube, configuracion_nube, formatear_estado_nube


class NubeLunaTests(unittest.TestCase):
    def test_instancia_no_equivale_a_ssh_configurado(self):
        estado = comprobar_nube({}, ssh="/usr/bin/ssh")
        self.assertFalse(estado["configurada"])
        self.assertFalse(estado["ssh"])
        self.assertIn("falta LUNA_CLOUD_HOST", estado["detalle"])

    def test_rechaza_clave_inexistente_sin_intentar_ssh(self):
        llamado = []

        def ejecutor(*_args, **_kwargs):
            llamado.append(True)

        estado = comprobar_nube(
            {"LUNA_CLOUD_HOST": "203.0.113.10", "LUNA_CLOUD_KEY": "/no/existe"},
            ejecutor=ejecutor,
            ssh="ssh",
        )
        self.assertFalse(estado["ssh"])
        self.assertFalse(llamado)
        self.assertIn("clave SSH", estado["detalle"])

    def test_ssh_y_servicio_activo_se_verifican_con_salida_real(self):
        with tempfile.TemporaryDirectory() as temporal:
            clave = Path(temporal) / "oracle.key"
            clave.write_text("privada", encoding="utf-8")

            def ejecutor(comando, **_kwargs):
                self.assertIn("opc@203.0.113.10", comando)
                self.assertIn(str(clave), comando)
                return subprocess.CompletedProcess(comando, 0, "LUNA_SSH_OK\nactive\n", "")

            estado = comprobar_nube(
                {
                    "LUNA_CLOUD_HOST": "203.0.113.10",
                    "LUNA_CLOUD_USER": "opc",
                    "LUNA_CLOUD_KEY": str(clave),
                },
                ejecutor=ejecutor,
                ssh="ssh",
            )
        self.assertTrue(estado["ssh"])
        self.assertEqual(estado["servicio"], "active")
        self.assertIn("VERIFICADO", formatear_estado_nube(estado))

    def test_configuracion_rechaza_host_con_comando(self):
        config = configuracion_nube({"LUNA_CLOUD_HOST": "host;reboot"})
        self.assertIn("host inválido", config["errores"])

    def test_en_oracle_comprueba_systemd_local_sin_ssh(self):
        def ejecutor(comando, **_kwargs):
            self.assertEqual(comando[:2], ["systemctl", "is-active"])
            return subprocess.CompletedProcess(comando, 0, "active\n", "")

        estado = comprobar_nube(
            {"LUNA_RUNNING_IN_CLOUD": "1"},
            ejecutor=ejecutor,
            ssh="no-debe-usarse",
        )
        self.assertTrue(estado["en_nube"])
        self.assertEqual(estado["servicio"], "active")
        self.assertIn("este proceso está en Oracle", formatear_estado_nube(estado))


if __name__ == "__main__":
    unittest.main()
