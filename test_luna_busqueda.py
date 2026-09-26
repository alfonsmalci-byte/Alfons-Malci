import json
import os
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
    def test_tavily_usa_bearer_y_no_mete_la_clave_en_el_cuerpo(self):
        cuerpo = json.dumps(
            {
                "results": [
                    {
                        "title": "Python",
                        "url": "https://python.org",
                        "content": "Official website",
                    }
                ]
            }
        )
        with patch.dict(os.environ, {"TAVILY_API_KEY": "tavily-secreta"}), patch(
            "luna.fetch", return_value=cuerpo
        ) as fetch:
            resultados = luna.tavily_search("Python", limit=1)
        llamada = fetch.call_args
        self.assertEqual(resultados[0]["source"], "tavily")
        self.assertEqual(
            llamada.kwargs["headers"]["Authorization"],
            "Bearer tavily-secreta",
        )
        self.assertNotIn(b"tavily-secreta", llamada.kwargs["data"])

    def test_brave_usa_su_cabecera_y_hace_busqueda_real(self):
        cuerpo = json.dumps(
            {
                "web": {
                    "results": [
                        {
                            "title": "Python",
                            "url": "https://python.org",
                            "description": "Official website",
                        }
                    ]
                }
            }
        )
        with patch.dict(
            os.environ, {"BRAVE_SEARCH_API_KEY": "brave-secreta"}
        ), patch("luna.fetch", return_value=cuerpo) as fetch:
            resultados = luna.brave_search("Python", limit=1)
        llamada = fetch.call_args
        self.assertEqual(resultados[0]["source"], "brave")
        self.assertEqual(
            llamada.kwargs["headers"]["X-Subscription-Token"],
            "brave-secreta",
        )
        self.assertNotIn("brave-secreta", llamada.args[0])

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

    def test_bing_convierte_rss_en_resultados(self):
        cuerpo = """<?xml version="1.0"?><rss><channel><item>
        <title>Reparar cadena de bicicleta</title>
        <link>https://ejemplo.test/bicicleta</link>
        <description>Guía práctica paso a paso</description>
        </item></channel></rss>"""
        with patch("luna.fetch", return_value=cuerpo):
            resultados = luna.bing_search("reparar cadena bicicleta")
        self.assertEqual(resultados[0]["source"], "bing")
        self.assertIn("Guía práctica", resultados[0]["snippet"])

    def test_consulta_general_no_usa_fuentes_de_noticias(self):
        llamadas = []

        def fuente(nombre, resultados=None):
            def ejecutar(_q, _l):
                llamadas.append(nombre)
                return resultados or []

            return ejecutar

        proveedores = {
            "google-news": fuente(
                "google-news",
                [{"title": "Ruido", "url": "https://ruido.test", "snippet": ""}],
            ),
            "gdelt": fuente("gdelt"),
            "duckduckgo": fuente(
                "duckduckgo",
                [
                    {
                        "title": "Reparar una cadena de bicicleta",
                        "url": "https://bici.test/guia",
                        "snippet": "Pasos para arreglar la cadena rota",
                    }
                ],
            ),
            "wikipedia": fuente("wikipedia"),
        }
        resultados, _ = luna.search_web(
            "cómo reparar una bicicleta con la cadena rota",
            providers=proveedores,
        )
        self.assertEqual([item["title"] for item in resultados], ["Reparar una cadena de bicicleta"])
        self.assertNotIn("google-news", llamadas)
        self.assertNotIn("gdelt", llamadas)

    def test_descarta_titular_que_no_menciona_el_tema(self):
        proveedores = {
            "google-news": lambda _q, _l: [
                {
                    "title": "Mercados europeos al alza",
                    "url": "https://ruido.test/noticia",
                    "snippet": "Economía internacional",
                },
                {
                    "title": "Nuevo gobierno de Albania",
                    "url": "https://relevante.test/noticia",
                    "snippet": "Actualidad de Albania",
                },
            ]
        }
        resultados, _ = luna.search_web(
            "noticias de Albania hoy",
            providers=proveedores,
        )
        self.assertEqual(len(resultados), 1)
        self.assertIn("Albania", resultados[0]["title"])

    def test_combina_fuentes_y_elimina_duplicados(self):
        repetido = {
            "title": "Albania uno",
            "url": "https://medio.test/a?utm_source=boletin",
            "snippet": "Albania A",
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
                    "title": "Albania dos",
                    "url": "https://otro.test/b",
                    "snippet": "Albania B",
                    "source": "duckduckgo",
                },
            ],
            "wikipedia": lambda _q, _l: [],
        }
        resultados, errores = luna.search_web(
            "noticias de Albania hoy",
            providers=proveedores,
        )
        self.assertEqual(
            [r["title"] for r in resultados],
            ["Albania uno", "Albania dos"],
        )
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
