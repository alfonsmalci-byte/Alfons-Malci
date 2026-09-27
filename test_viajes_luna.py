import unittest
from datetime import date

import viajes_luna


class AnalisisVueloTests(unittest.TestCase):
    def test_detecta_ruta_de_la_captura_y_asume_manana_por_primer_vuelo(self):
        analisis = viajes_luna.analizar_consulta_vuelo(
            "/busca el primer bilieto desde Albania a milano malpense dime el horario y precio",
            hoy=date(2026, 9, 26),
        )
        self.assertTrue(analisis["es_vuelo"])
        self.assertEqual((analisis["origen"], analisis["destino"]), ("TIA", "MXP"))
        self.assertEqual(analisis["fecha"], "2026-09-27")
        self.assertTrue(analisis["fecha_inferida"])
        self.assertNotIn("fecha", analisis["faltan"])
        self.assertEqual(analisis["ordenar"], "salida")

    def test_reconoce_prishtina_kosovo_como_prn(self):
        analisis = viajes_luna.analizar_consulta_vuelo(
            "primer vuelo desde Prishtina Kosovo a Milano Malpensa",
            hoy=date(2026, 9, 26),
        )
        self.assertEqual((analisis["origen"], analisis["destino"]), ("PRN", "MXP"))
        self.assertEqual(analisis["fecha"], "2026-09-27")

    def test_convierte_manana_a_fecha_de_tirana(self):
        analisis = viajes_luna.analizar_consulta_vuelo(
            "vuelo Tirana a Malpensa mañana",
            hoy=date(2026, 9, 26),
        )
        self.assertEqual(analisis["fecha"], "2026-09-27")
        self.assertEqual(analisis["faltan"], [])

    def test_rechaza_fecha_pasada(self):
        analisis = viajes_luna.analizar_consulta_vuelo(
            "vuelo TIA a MXP 25/09/2026",
            hoy=date(2026, 9, 26),
        )
        self.assertIn("fecha", analisis["faltan"])
        self.assertIn("pasó", analisis["error_fecha"])

    def test_respeta_ruta_si_el_destino_se_escribe_primero(self):
        analisis = viajes_luna.analizar_consulta_vuelo(
            "vuelo a Milano Malpensa desde Albania mañana",
            hoy=date(2026, 9, 26),
        )
        self.assertEqual((analisis["origen"], analisis["destino"]), ("TIA", "MXP"))


class SerpApiVueloTests(unittest.TestCase):
    def respuesta(self, parametros, clave):
        self.parametros = parametros
        self.clave = clave
        return {
            "search_metadata": {"google_flights_url": "https://www.google.com/travel/flights/test"},
            "best_flights": [
                {
                    "price": 49,
                    "total_duration": 115,
                    "flights": [
                        {
                            "departure_airport": {"id": "TIA", "time": "2026-09-27 06:10"},
                            "arrival_airport": {"id": "MXP", "time": "2026-09-27 08:05"},
                            "airline": "Wizz Air Malta",
                            "flight_number": "W4 5001",
                        }
                    ],
                },
                {
                    "price": 35,
                    "total_duration": 120,
                    "flights": [
                        {
                            "departure_airport": {"id": "TIA", "time": "2026-09-27 15:00"},
                            "arrival_airport": {"id": "MXP", "time": "2026-09-27 17:00"},
                            "airline": "Air Test",
                            "flight_number": "AT 2",
                        }
                    ],
                },
                {
                    "price": 1,
                    "total_duration": 60,
                    "flights": [
                        {
                            "departure_airport": {"id": "MXP", "time": "2026-09-27 01:00"},
                            "arrival_airport": {"id": "TIA", "time": "2026-09-27 02:00"},
                        }
                    ],
                },
            ],
        }

    def test_busca_ruta_fecha_y_devuelve_primera_salida(self):
        resultado = viajes_luna.buscar_vuelos_serpapi(
            "primer vuelo Albania a Malpense mañana",
            clave="secreta",
            hoy=date(2026, 9, 26),
            solicitante=self.respuesta,
        )
        self.assertEqual(self.parametros["departure_id"], "TIA")
        self.assertEqual(self.parametros["arrival_id"], "MXP")
        self.assertEqual(self.parametros["outbound_date"], "2026-09-27")
        self.assertEqual(self.clave, "secreta")
        self.assertEqual(len(resultado["opciones"]), 2)
        self.assertEqual(resultado["opciones"][0]["precio_eur"], 49)
        texto = viajes_luna.formatear_vuelos(resultado)
        self.assertIn("TIA → MXP", texto)
        self.assertIn("49 €", texto)
        self.assertNotIn("CONTEXTO WEB", texto)
        self.assertNotIn("secreta", texto)

    def test_sin_fecha_y_sin_intencion_de_proximo_pide_fecha(self):
        texto = viajes_luna.responder_consulta_vuelo(
            "bilieto Albania a Milano Malpense",
            {"SERPAPI_API_KEY": "secreta"},
        )
        self.assertIn("falta la fecha exacta", texto)
        self.assertNotIn("completada", texto.lower())

    def test_sin_serpapi_no_finge_precio(self):
        texto = viajes_luna.responder_consulta_vuelo(
            "vuelo Albania a Milano Malpense 27/09/2099",
            {},
        )
        self.assertIn("falta SERPAPI_API_KEY", texto)
        self.assertIn("No voy a llamar", texto)

    def test_comprueba_cuenta_sin_consumir_busqueda(self):
        recibida = []

        def cuenta(clave):
            recibida.append(clave)
            return {"account_status": "Active", "total_searches_left": 17}

        ok, detalle = viajes_luna.comprobar_serpapi("secreta", solicitante=cuenta)
        self.assertTrue(ok)
        self.assertIn("17", detalle)
        self.assertEqual(recibida, ["secreta"])

    def test_cuenta_sin_evidencia_no_se_declara_activa(self):
        ok, detalle = viajes_luna.comprobar_serpapi(
            "secreta", solicitante=lambda _clave: {}
        )
        self.assertFalse(ok)
        self.assertIn("sin estado verificable", detalle)


if __name__ == "__main__":
    unittest.main()
