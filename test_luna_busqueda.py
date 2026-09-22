import json
import unittest
from unittest.mock import patch

import luna


class LimpiezaConsultaTests(unittest.TestCase):
    def test_limpia_ruido_sin_borrar_entidad(self):
        self.assertEqual(
            luna.limpiar_consulta_noticias("últimas noticias de Albania hoy"),
            "Albania",
        )

    def test_detecta_consulta_actual_con_acentos(self):
        self.assertTrue(luna.es_consulta_actual("Últimas noticias de Albania"))
        self.assertFalse(luna.es_consulta_actual("historia de Albania"))


class ProveedoresBusquedaTests(unittest.TestCase):
    def test_google_news_convierte_rss_en_resultados(self):
        cuerpo = """<?xml version="1.0" encoding="UTF-8"?>
        <rss><channel><item>
          <title>Titular reciente - Medio</title>
          <link>https://news.google.com/rss/articles/abc</link>
          <pubDate>Tue, 22 Sep 2026 12:00:00 GMT</pubDate>
          <source>Medio</source>
        </item></channel></rss>"""
        with patch("luna.fetch", return_value=cuerpo) as fetch:
            resultados = luna.google_news_search("noticias de Albania hoy")
        self.assertEqual(resultados[0]["source"], "google-news")
        self.assertIn("Medio", resultados[0]["snippet"])
        self.assertIn("news.google.com/rss/search", fetch.call_args.args[0])
        self.assertIn("when%3A7d", fetch.call_args.args[0])

    def test_gdelt_convierte_articulos_en_resultados(self):
        cuerpo = {
            "articles": [
                {
                    "title": "Noticia de prueba",
                    "url": "https://ejemplo.test/noticia?utm_source=x",
                    "domain": "ejemplo.test",
                    "sourcecountry": "Albania",
                    "seendate": "20260922T120000Z",
                }
            ]
        }
        with patch("luna.fetch", return_value=json.dumps(cuerpo)) as fetch:
            resultados = luna.gdelt_search("noticias de Albania hoy")

        self.assertEqual(resultados[0]["source"], "gdelt")
        self.assertEqual(resultados[0]["title"], "Noticia de prueba")
        url_consultada = fetch.call_args.args[0]
        self.assertIn("api.gdeltproject.org/api/v2/doc/doc", url_consultada)
        self.assertIn("query=Albania", url_consultada)
        self.assertIn("timespan=7d", url_consultada)

    def test_wikipedia_elimina_html_del_resumen(self):
        cuerpo = {
            "query": {
                "search": [
                    {
                        "title": "Albania",
                        "snippet": "País de <span class=\"searchmatch\">Europa</span>",
                    }
                ]
            }
        }
        with patch("luna.fetch", return_value=json.dumps(cuerpo)):
            resultados = luna.wikipedia_search("Albania")
        self.assertEqual(resultados[0]["snippet"], "País de Europa")

    def test_combina_fuentes_y_elimina_duplicados(self):
        repetido = {
            "title": "Uno",
            "url": "https://medio.test/a?utm_source=boletin",
            "snippet": "A",
        }
        proveedores = {
            "google-news": lambda _q, _l: [],
            "gdelt": lambda _q, _l: [{**repetido, "source": "gdelt"}],
            "duckduckgo": lambda _q, _l: [
                {
                    **repetido,
                    "url": "https://medio.test/a",
                    "source": "duckduckgo",
                },
                {
                    "title": "Dos",
                    "url": "https://otro.test/b",
                    "snippet": "B",
                    "source": "duckduckgo",
                },
            ],
            "wikipedia": lambda _q, _l: [],
        }
        resultados, errores = luna.search_web(
            "noticias de Albania hoy",
            providers=proveedores,
        )
        self.assertEqual([r["title"] for r in resultados], ["Uno", "Dos"])
        self.assertTrue(any("wikipedia" in error for error in errores))

    def test_conserva_resultados_si_otra_fuente_falla(self):
        def falla(_q, _l):
            raise TimeoutError("sin respuesta")

        proveedores = {
            "google-news": lambda _q, _l: [],
            "gdelt": falla,
            "duckduckgo": lambda _q, _l: [
                {
                    "title": "Disponible",
                    "url": "https://ejemplo.test/ok",
                    "snippet": "",
                    "source": "duckduckgo",
                }
            ],
            "wikipedia": lambda _q, _l: [],
        }
        resultados, errores = luna.search_web("noticias hoy", providers=proveedores)
        self.assertEqual(len(resultados), 1)
        self.assertTrue(any("TimeoutError" in error for error in errores))


if __name__ == "__main__":
    unittest.main()
