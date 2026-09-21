import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser

from sabiduria_luna import (
    REGLAS_NUCLEO,
    cargar_memoria_privada,
    evaluar_evidencia,
    tarjeta_nucleo,
)


USER_AGENT = "Mozilla/5.0 (Luna-Agent/1.0)"


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
            self._current["title"] += data.strip()
        elif self._capture_snippet:
            self._current["snippet"] += data.strip()


def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as respuesta:
        return respuesta.read().decode("utf-8", errors="replace")


def wikipedia_search(query, limit=5):
    params = urllib.parse.urlencode(
        {
            "action": "query",
            "list": "search",
            "srsearch": query,
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
                "title": title,
                "url": "https://es.wikipedia.org/wiki/"
                + urllib.parse.quote(title.replace(" ", "_")),
                "snippet": item.get("snippet", "")
                .replace('<span class="searchmatch">', "")
                .replace("</span>", ""),
                "source": "wikipedia",
            }
        )
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
        out.append(
            {
                "title": item["title"],
                "url": url,
                "snippet": item["snippet"],
                "source": "duckduckgo",
            }
        )
    return out


def search_web(query):
    errors = []
    try:
        resultados = duckduckgo_search(query)
        if resultados:
            return resultados, errors
        errors.append("DuckDuckGo devolvió 0 resultados")
    except Exception as error:
        errors.append(f"DuckDuckGo falló: {type(error).__name__}: {error}")

    try:
        resultados = wikipedia_search(query)
        if resultados:
            return resultados, errors
        errors.append("Wikipedia devolvió 0 resultados")
    except Exception as error:
        errors.append(f"Wikipedia falló: {type(error).__name__}: {error}")

    return [], errors


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
