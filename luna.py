import json
import os
import re
import sys
import urllib.parse
import urllib.request
import unicodedata
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser

from sabiduria_luna import (
    REGLAS_NUCLEO,
    cargar_memoria_privada,
    evaluar_evidencia,
    tarjeta_nucleo,
)


USER_AGENT = "Mozilla/5.0 (Luna-Agent/1.0)"
FUENTES_BUSQUEDA = ("google-news", "gdelt", "duckduckgo", "wikipedia")
PALABRAS_ACTUALIDAD = (
    "actual",
    "actualidad",
    "ahora",
    "hoy",
    "latest",
    "news",
    "noticia",
    "noticias",
    "reciente",
    "recientes",
    "ultimo",
    "ultimos",
    "ultima",
    "ultimas",
)
PALABRAS_RUIDO_NOTICIAS = {
    "actual",
    "actuales",
    "actualidad",
    "ahora",
    "al",
    "de",
    "del",
    "el",
    "en",
    "hoy",
    "la",
    "las",
    "latest",
    "los",
    "news",
    "noticia",
    "noticias",
    "sobre",
    "un",
    "una",
    "ultimo",
    "ultimos",
    "ultima",
    "ultimas",
}


def _sin_acentos(texto):
    return "".join(
        caracter
        for caracter in unicodedata.normalize("NFKD", str(texto).lower())
        if not unicodedata.combining(caracter)
    )


def _texto_limpio(texto):
    texto = re.sub(r"<[^>]+>", " ", unescape(str(texto or "")))
    return " ".join(texto.split())


def _url_publica(url):
    url = unescape(str(url or "")).strip()
    parsed = urllib.parse.urlparse(url)
    return url if parsed.scheme in ("http", "https") and parsed.netloc else ""


def es_consulta_actual(query):
    texto = _sin_acentos(query)
    palabras = set(re.findall(r"[a-z0-9]+", texto))
    return bool(palabras.intersection(PALABRAS_ACTUALIDAD))


def limpiar_consulta_noticias(query):
    """Quita palabras genéricas sin borrar nombres, lugares ni fechas."""
    tokens = re.findall(r"[^\W_]+(?:[-'][^\W_]+)*", str(query), flags=re.UNICODE)
    utiles = [token for token in tokens if _sin_acentos(token) not in PALABRAS_RUIDO_NOTICIAS]
    return " ".join(utiles).strip() or str(query).strip()


class DuckResultParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.results = []
        self._capture_title = False
        self._capture_snippet = False
        self._current = {"title": "", "url": "", "snippet": ""}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        cls = attrs.get("class", "")
        if tag == "a" and "result__a" in cls:
            self._capture_title = True
            self._current = {"title": "", "url": attrs.get("href", ""), "snippet": ""}
        elif tag in ("a", "div") and "result__snippet" in cls:
            self._capture_snippet = True

    def handle_endtag(self, tag):
        if tag == "a" and self._capture_title:
            self._capture_title = False
        elif tag in ("a", "div") and self._capture_snippet:
            self._capture_snippet = False
            if self._current.get("title"):
                self.results.append(self._current.copy())
                self._current = {"title": "", "url": "", "snippet": ""}

    def handle_data(self, data):
        if self._capture_title:
            self._current["title"] += (" " if self._current["title"] else "") + data.strip()
        elif self._capture_snippet:
            self._current["snippet"] += (" " if self._current["snippet"] else "") + data.strip()


def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as respuesta:
        return respuesta.read().decode("utf-8", errors="replace")


def wikipedia_search(query, limit=5):
    consulta = limpiar_consulta_noticias(query) if es_consulta_actual(query) else query
    params = urllib.parse.urlencode(
        {
            "action": "query",
            "list": "search",
            "srsearch": consulta,
            "format": "json",
            "utf8": 1,
            "srlimit": limit,
        }
    )
    url = f"https://es.wikipedia.org/w/api.php?{params}"
    data = json.loads(fetch(url))
    out = []
    for item in data.get("query", {}).get("search", []):
        title = item.get("title", "")
        out.append(
            {
                "title": _texto_limpio(title),
                "url": "https://es.wikipedia.org/wiki/"
                + urllib.parse.quote(title.replace(" ", "_")),
                "snippet": _texto_limpio(item.get("snippet", "")),
                "source": "wikipedia",
            }
        )
    return out


def gdelt_search(query, limit=8):
    """Busca noticias actuales en el índice público GDELT DOC 2.0."""
    consulta = limpiar_consulta_noticias(query)
    params = urllib.parse.urlencode(
        {
            "query": consulta,
            "mode": "artlist",
            "maxrecords": max(10, min(int(limit) * 3, 50)),
            "format": "json",
            "sort": "datedesc",
            "timespan": "7d" if es_consulta_actual(query) else "3months",
        }
    )
    url = f"https://api.gdeltproject.org/api/v2/doc/doc?{params}"
    data = json.loads(fetch(url, timeout=25))
    out = []
    for item in data.get("articles", []):
        if not isinstance(item, dict):
            continue
        enlace = _url_publica(item.get("url"))
        titulo = _texto_limpio(item.get("title"))
        if not enlace or not titulo:
            continue
        detalles = [
            _texto_limpio(item.get("domain")),
            _texto_limpio(item.get("sourcecountry")),
            _texto_limpio(item.get("seendate")),
        ]
        out.append(
            {
                "title": titulo,
                "url": enlace,
                "snippet": " · ".join(parte for parte in detalles if parte),
                "source": "gdelt",
            }
        )
        if len(out) >= limit:
            break
    return out


def google_news_search(query, limit=8):
    """Busca titulares recientes en el feed público de Google News."""
    consulta = limpiar_consulta_noticias(query)
    if es_consulta_actual(query):
        consulta += " when:7d"
    params = urllib.parse.urlencode(
        {"q": consulta, "hl": "es", "gl": "ES", "ceid": "ES:es"}
    )
    xml = fetch(f"https://news.google.com/rss/search?{params}", timeout=25)
    raiz = ET.fromstring(xml)
    out = []
    for item in raiz.findall(".//item"):
        titulo = _texto_limpio(item.findtext("title"))
        enlace = _url_publica(item.findtext("link"))
        if not titulo or not enlace:
            continue
        origen = _texto_limpio(item.findtext("source"))
        fecha = _texto_limpio(item.findtext("pubDate"))
        out.append(
            {
                "title": titulo,
                "url": enlace,
                "snippet": " · ".join(parte for parte in (origen, fecha) if parte),
                "source": "google-news",
            }
        )
        if len(out) >= limit:
            break
    return out


def duckduckgo_search(query, limit=5):
    body = urllib.parse.urlencode({"q": query}).encode()
    req = urllib.request.Request(
        "https://html.duckduckgo.com/html/",
        data=body,
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as respuesta:
        html = respuesta.read().decode("utf-8", errors="replace")
    parser = DuckResultParser()
    parser.feed(html)
    out = []
    for item in parser.results[:limit]:
        url = item["url"]
        if url.startswith("//duckduckgo.com/l/?"):
            parsed = urllib.parse.urlparse("https:" + url)
            query_string = urllib.parse.parse_qs(parsed.query)
            url = query_string.get("uddg", [url])[0]
        url = _url_publica(url)
        titulo = _texto_limpio(item["title"])
        if url and titulo:
            out.append(
                {
                    "title": titulo,
                    "url": url,
                    "snippet": _texto_limpio(item["snippet"]),
                    "source": "duckduckgo",
                }
            )
    return out


def _clave_resultado(resultado):
    url = _url_publica(resultado.get("url"))
    if url:
        parsed = urllib.parse.urlsplit(url)
        query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        query = [
            (clave, valor)
            for clave, valor in query
            if not clave.lower().startswith("utm_")
            and clave.lower() not in {"fbclid", "gclid"}
        ]
        return urllib.parse.urlunsplit(
            (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), urllib.parse.urlencode(query), "")
        )
    return _sin_acentos(resultado.get("title", ""))


def search_web(query, limit=8, providers=None):
    """Consulta varias fuentes a la vez y combina resultados sin duplicados."""
    query = str(query).strip()
    if not query:
        return [], ["La consulta está vacía"]

    proveedores = providers or {
        "google-news": google_news_search,
        "gdelt": gdelt_search,
        "duckduckgo": duckduckgo_search,
        "wikipedia": wikipedia_search,
    }
    orden = list(FUENTES_BUSQUEDA)
    if not es_consulta_actual(query):
        orden = ["duckduckgo", "wikipedia", "google-news", "gdelt"]
    orden = [nombre for nombre in orden if nombre in proveedores]
    if not orden:
        return [], ["No hay fuentes de búsqueda configuradas"]

    por_fuente = {}
    errors = []
    with ThreadPoolExecutor(max_workers=len(orden), thread_name_prefix="luna-web") as executor:
        futuros = {
            executor.submit(proveedores[nombre], query, max(5, limit)): nombre
            for nombre in orden
        }
        for futuro in as_completed(futuros):
            nombre = futuros[futuro]
            try:
                resultados = futuro.result()
                por_fuente[nombre] = resultados if isinstance(resultados, list) else []
                if not por_fuente[nombre]:
                    errors.append(f"{nombre} devolvió 0 resultados")
            except Exception as error:
                por_fuente[nombre] = []
                errors.append(f"{nombre} falló: {type(error).__name__}: {error}")

    combinados = []
    vistos = set()
    profundidad = max((len(por_fuente.get(nombre, [])) for nombre in orden), default=0)
    for indice in range(profundidad):
        for nombre in orden:
            resultados_fuente = por_fuente.get(nombre, [])
            if indice >= len(resultados_fuente):
                continue
            item = resultados_fuente[indice]
            if not isinstance(item, dict):
                continue
            titulo = _texto_limpio(item.get("title"))
            url = _url_publica(item.get("url"))
            if not titulo or not url:
                continue
            normalizado = {
                "title": titulo,
                "url": url,
                "snippet": _texto_limpio(item.get("snippet")),
                "source": str(item.get("source") or nombre),
            }
            clave = _clave_resultado(normalizado)
            if not clave or clave in vistos:
                continue
            vistos.add(clave)
            combinados.append(normalizado)
            if len(combinados) >= limit:
                return combinados, errors
    return combinados, errors


def mostrar_mente():
    memoria, advertencias = cargar_memoria_privada()
    resumen = {
        "nucleo": tarjeta_nucleo(),
        "reglas": list(REGLAS_NUCLEO),
        "memoria_privada_detectada": bool(memoria),
        "memoria_privada_publicada": False,
        "advertencias": advertencias,
    }
    print(json.dumps(resumen, ensure_ascii=False, indent=2))


def main():
    argumentos = sys.argv[1:]
    if argumentos == ["--mente"]:
        mostrar_mente()
        return

    query = " ".join(argumentos).strip() or os.getenv(
        "LUNA_QUERY", "OpenAI artificial intelligence"
    )
    results, errors = search_web(query)

    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "query": query,
        "internet_ok": bool(results),
        "nucleo": tarjeta_nucleo(),
        "evaluacion_evidencia": evaluar_evidencia(results, errors),
        "results": results,
        "errors": errors,
    }

    os.makedirs("resultados", exist_ok=True)
    with open("resultados/ultima_busqueda.json", "w", encoding="utf-8") as salida:
        json.dump(report, salida, ensure_ascii=False, indent=2)

    print(json.dumps(report, ensure_ascii=False, indent=2))

    if not results:
        raise SystemExit("❌ Luna no consiguió resultados de Internet.")
    cobertura = report["evaluacion_evidencia"]["nivel_cobertura"]
    print(f"\n✅ INTERNET OK: {len(results)} resultados para: {query}")
    print(f"🧠 Cobertura de fuentes: {cobertura}")


if __name__ == "__main__":
    main()
