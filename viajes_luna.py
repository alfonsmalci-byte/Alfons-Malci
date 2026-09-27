#!/usr/bin/env python3
"""Consultas de vuelos verificables para Luna.

Las búsquedas web genéricas no demuestran horarios ni precios. Este módulo
solo declara éxito cuando recibe una oferta estructurada para la ruta y fecha
solicitadas. Las credenciales se leen de ``.env`` mediante el entorno y nunca
se imprimen.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


USER_AGENT = "Luna-Travel/1.0"
TIMEZONE = "Europe/Tirane"
FLIGHT_API_URL = "https://serpapi.com/search.json"
ACCOUNT_API_URL = "https://serpapi.com/account.json"
VIAJES_VERSION = "8.0.0"


class ViajesError(RuntimeError):
    """Error controlado que nunca contiene credenciales."""


AIRPORT_ALIASES = {
    "albania": "TIA",
    "tirana": "TIA",
    "rinas": "TIA",
    "tia": "TIA",
    "milano malpensa": "MXP",
    "milano malpense": "MXP",
    "milan malpensa": "MXP",
    "milan malpense": "MXP",
    "malpensa": "MXP",
    "malpense": "MXP",
    "mxp": "MXP",
    "milano bergamo": "BGY",
    "milan bergamo": "BGY",
    "bergamo": "BGY",
    "bgy": "BGY",
    "milano linate": "LIN",
    "milan linate": "LIN",
    "linate": "LIN",
    "lin": "LIN",
    "bari": "BRI",
    "bri": "BRI",
    "roma fiumicino": "FCO",
    "rome fiumicino": "FCO",
    "fiumicino": "FCO",
    "fco": "FCO",
    "atene": "ATH",
    "athens": "ATH",
    "ath": "ATH",
    "pristina": "PRN",
    "prishtina": "PRN",
    "kosovo": "PRN",
    "kosova": "PRN",
    "prn": "PRN",
    "skopje": "SKP",
    "skp": "SKP",
    "istanbul": "IST",
    "ist": "IST",
}

MESES = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}


def _sin_acentos(texto: str) -> str:
    return "".join(
        caracter
        for caracter in unicodedata.normalize("NFKD", str(texto).lower())
        if not unicodedata.combining(caracter)
    )


def _hoy_tirana() -> date:
    try:
        return datetime.now(ZoneInfo(TIMEZONE)).date()
    except Exception:
        return date.today()


def es_consulta_vuelo(texto: str) -> bool:
    normalizado = _sin_acentos(texto)
    patrones = (
        r"\bvuelo(?:s)?\b",
        r"\bflight(?:s)?\b",
        r"\bbil(?:lete|letes|ieto|ietos|ierto|iertos)\b",
        r"\bavion(?:es)?\b",
        r"\baeropuerto(?:s)?\b",
    )
    return any(re.search(patron, normalizado) for patron in patrones)


def _extraer_fecha(texto: str, hoy: date) -> tuple[str, str]:
    normalizado = _sin_acentos(texto)
    if re.search(r"\bpasado\s+manana\b", normalizado):
        return (hoy + timedelta(days=2)).isoformat(), ""
    if re.search(r"\bmanana\b", normalizado):
        return (hoy + timedelta(days=1)).isoformat(), ""
    if re.search(r"\bhoy\b", normalizado):
        return hoy.isoformat(), ""

    coincidencia = re.search(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b", normalizado)
    if coincidencia:
        partes = tuple(int(valor) for valor in coincidencia.groups())
    else:
        coincidencia = re.search(r"\b(\d{1,2})[-/](\d{1,2})[-/](20\d{2})\b", normalizado)
        if coincidencia:
            dia, mes, anio = (int(valor) for valor in coincidencia.groups())
            partes = (anio, mes, dia)
        else:
            meses = "|".join(sorted(MESES, key=len, reverse=True))
            coincidencia = re.search(
                rf"\b(\d{{1,2}})\s+(?:de\s+)?({meses})\s+(?:de\s+)?(20\d{{2}})\b",
                normalizado,
            )
            if not coincidencia:
                return "", ""
            dia = int(coincidencia.group(1))
            mes = MESES[coincidencia.group(2)]
            anio = int(coincidencia.group(3))
            partes = (anio, mes, dia)
    try:
        fecha = date(*partes)
    except ValueError:
        return "", "La fecha escrita no es válida."
    if fecha < hoy:
        return "", "La fecha ya pasó."
    return fecha.isoformat(), ""


def _extraer_aeropuertos(texto: str) -> list[str]:
    normalizado = _sin_acentos(texto)
    encontrados: list[tuple[int, int, str]] = []
    for alias, codigo in sorted(AIRPORT_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        coincidencia = re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", normalizado)
        if coincidencia:
            encontrados.append((coincidencia.start(), -len(alias), codigo))

    for coincidencia in re.finditer(r"\b[A-Z]{3}\b", texto):
        encontrados.append((coincidencia.start(), -3, coincidencia.group(0)))

    codigos: list[str] = []
    for _, _, codigo in sorted(encontrados):
        if codigo not in codigos:
            codigos.append(codigo)
    return codigos


def _extraer_ruta_dirigida(texto: str) -> tuple[str, str] | None:
    """Respeta origen/destino incluso si el usuario escribe el destino primero."""
    normalizado = _sin_acentos(texto)
    patrones = (
        (r"\b(?:desde|de|from)\s+(.+?)\s+(?:a|hasta|to)\s+(.+)", False),
        (r"\b(?:a|hasta|to)\s+(.+?)\s+(?:desde|from)\s+(.+)", True),
    )
    for patron, inverso in patrones:
        coincidencia = re.search(patron, normalizado)
        if not coincidencia:
            continue
        primero = _extraer_aeropuertos(coincidencia.group(1))
        segundo = _extraer_aeropuertos(coincidencia.group(2))
        if primero and segundo:
            return (segundo[0], primero[0]) if inverso else (primero[0], segundo[0])
    return None


def analizar_consulta_vuelo(texto: str, *, hoy: date | None = None) -> dict:
    hoy = hoy or _hoy_tirana()
    if not es_consulta_vuelo(texto):
        return {"es_vuelo": False}
    ruta_dirigida = _extraer_ruta_dirigida(texto)
    codigos = list(ruta_dirigida) if ruta_dirigida else _extraer_aeropuertos(texto)
    fecha, error_fecha = _extraer_fecha(texto, hoy)
    normalizado = _sin_acentos(texto)
    fecha_inferida = False
    if not fecha and not error_fecha and re.search(
        r"\b(?:primer|primero|proximo|proxima|siguiente|mas\s+temprano)\b",
        normalizado,
    ):
        # Una petición de "primer/próximo vuelo" ya expresa intención temporal.
        # Usamos mañana como única suposición explícita para evitar devolver al
        # usuario la misma pregunta que acaba de hacer.
        fecha = (hoy + timedelta(days=1)).isoformat()
        fecha_inferida = True
    if re.search(r"\b(?:barato|barata|economico|economica|menor precio)\b", normalizado):
        ordenar = "precio"
    elif re.search(r"\b(?:primer|primero|temprano|antes)\b", normalizado):
        ordenar = "salida"
    else:
        ordenar = "recomendado"
    faltan = []
    if len(codigos) < 1:
        faltan.append("origen")
    if len(codigos) < 2:
        faltan.append("destino")
    if not fecha:
        faltan.append("fecha")
    return {
        "es_vuelo": True,
        "origen": codigos[0] if codigos else "",
        "destino": codigos[1] if len(codigos) > 1 else "",
        "fecha": fecha,
        "fecha_inferida": fecha_inferida,
        "error_fecha": error_fecha,
        "ordenar": ordenar,
        "faltan": faltan,
    }


def _pedir_json_serpapi(parametros: dict[str, str], clave: str, timeout: int = 30) -> dict:
    consulta = urllib.parse.urlencode({**parametros, "api_key": clave})
    peticion = urllib.request.Request(
        f"{FLIGHT_API_URL}?{consulta}",
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
            bruto = respuesta.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        raise ViajesError(f"SerpAPI rechazó la consulta (HTTP {int(error.code)}).") from None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise ViajesError(f"No hubo conexión con el motor de vuelos ({type(error).__name__}).") from None
    try:
        datos = json.loads(bruto)
    except json.JSONDecodeError:
        raise ViajesError("El motor de vuelos devolvió datos inválidos.") from None
    if not isinstance(datos, dict):
        raise ViajesError("El motor de vuelos devolvió una respuesta inesperada.")
    if datos.get("error"):
        detalle = re.sub(re.escape(clave), "***", str(datos["error"]))
        raise ViajesError("SerpAPI: " + " ".join(detalle.split())[:240])
    return datos


def _pedir_cuenta_serpapi(clave: str, timeout: int = 20) -> dict:
    consulta = urllib.parse.urlencode({"api_key": clave})
    peticion = urllib.request.Request(
        f"{ACCOUNT_API_URL}?{consulta}",
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
            bruto = respuesta.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        raise ViajesError(f"SerpAPI rechazó la clave (HTTP {int(error.code)}).") from None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise ViajesError(f"No hubo conexión con SerpAPI ({type(error).__name__}).") from None
    try:
        datos = json.loads(bruto)
    except json.JSONDecodeError:
        raise ViajesError("SerpAPI devolvió datos inválidos.") from None
    if not isinstance(datos, dict):
        raise ViajesError("SerpAPI devolvió una respuesta inesperada.")
    if datos.get("error"):
        detalle = re.sub(re.escape(clave), "***", str(datos["error"]))
        raise ViajesError("SerpAPI: " + " ".join(detalle.split())[:240])
    return datos


def comprobar_serpapi(clave: str, *, solicitante=_pedir_cuenta_serpapi) -> tuple[bool, str]:
    """Comprueba cuenta y créditos sin gastar una búsqueda."""
    clave = clave.strip()
    if not clave:
        return False, "no configurada"
    try:
        datos = solicitante(clave)
    except ViajesError as error:
        return False, str(error)
    estado = str(datos.get("account_status", "")).strip().lower()
    restantes = datos.get("total_searches_left", datos.get("plan_searches_left"))
    if not estado and not isinstance(restantes, (int, float)):
        return False, "respuesta de cuenta sin estado verificable"
    if estado and estado not in {"active", "activo"}:
        return False, f"cuenta {estado}"
    if isinstance(restantes, (int, float)) and restantes <= 0:
        return False, "autenticada, pero sin búsquedas disponibles"
    detalle = "activa"
    if isinstance(restantes, (int, float)):
        detalle += f"; {int(restantes)} búsquedas disponibles"
    return True, detalle


def _hora_ordenable(valor: str) -> datetime:
    try:
        return datetime.fromisoformat(valor)
    except (TypeError, ValueError):
        return datetime.max


def _url_google_segura(datos: dict) -> str:
    url = str((datos.get("search_metadata") or {}).get("google_flights_url") or "").strip()
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme == "https" and parsed.hostname in {"google.com", "www.google.com"}:
        return url
    return ""


def buscar_vuelos_serpapi(
    texto: str,
    *,
    clave: str = "",
    hoy: date | None = None,
    solicitante=_pedir_json_serpapi,
    limite: int = 3,
) -> dict:
    analisis = analizar_consulta_vuelo(texto, hoy=hoy)
    if not analisis.get("es_vuelo"):
        raise ViajesError("La consulta no parece una búsqueda de vuelos.")
    if analisis.get("error_fecha"):
        raise ViajesError(str(analisis["error_fecha"]))
    if analisis.get("faltan"):
        raise ViajesError("Faltan datos: " + ", ".join(analisis["faltan"]))
    clave = (
        clave.strip()
        or os.getenv("SERPAPI_API_KEY", "").strip()
        or os.getenv("SERPAPI_KEY", "").strip()
    )
    if not clave:
        raise ViajesError("Falta SERPAPI_API_KEY en .env para consultar horarios y precios reales.")

    parametros = {
        "engine": "google_flights",
        "departure_id": analisis["origen"],
        "arrival_id": analisis["destino"],
        "outbound_date": analisis["fecha"],
        "type": "2",
        "travel_class": "1",
        "adults": "1",
        "currency": "EUR",
        "hl": "es",
        "gl": "al",
    }
    datos = solicitante(parametros, clave)
    opciones = []
    for grupo in ("best_flights", "other_flights"):
        for oferta in datos.get(grupo, []) or []:
            if not isinstance(oferta, dict):
                continue
            tramos = [tramo for tramo in oferta.get("flights", []) if isinstance(tramo, dict)]
            if not tramos:
                continue
            salida = tramos[0].get("departure_airport") or {}
            llegada = tramos[-1].get("arrival_airport") or {}
            if str(salida.get("id", "")).upper() != analisis["origen"]:
                continue
            if str(llegada.get("id", "")).upper() != analisis["destino"]:
                continue
            precio = oferta.get("price")
            hora_salida = str(salida.get("time", "")).strip()
            hora_llegada = str(llegada.get("time", "")).strip()
            if not isinstance(precio, (int, float)) or not hora_salida or not hora_llegada:
                continue
            aerolineas = []
            numeros = []
            for tramo in tramos:
                aerolinea = str(tramo.get("airline", "")).strip()
                numero = str(tramo.get("flight_number", "")).strip()
                if aerolinea and aerolinea not in aerolineas:
                    aerolineas.append(aerolinea)
                if numero and numero not in numeros:
                    numeros.append(numero)
            opciones.append(
                {
                    "precio_eur": float(precio),
                    "salida": hora_salida,
                    "llegada": hora_llegada,
                    "aerolineas": aerolineas,
                    "vuelos": numeros,
                    "escalas": max(0, len(tramos) - 1),
                    "duracion_minutos": int(oferta.get("total_duration") or 0),
                }
            )

    if analisis["ordenar"] == "salida":
        opciones.sort(key=lambda item: (_hora_ordenable(item["salida"]), item["precio_eur"]))
    elif analisis["ordenar"] == "precio":
        opciones.sort(key=lambda item: (item["precio_eur"], _hora_ordenable(item["salida"])))
    if not opciones:
        raise ViajesError(
            "El motor respondió, pero no devolvió una oferta con ruta, horario y precio verificables."
        )
    return {
        "consulta": analisis,
        "opciones": opciones[: max(1, min(int(limite), 5))],
        "fuente": "Google Flights vía SerpAPI",
        "url": _url_google_segura(datos),
    }


def _duracion(minutos: int) -> str:
    if minutos <= 0:
        return "no indicada"
    horas, resto = divmod(minutos, 60)
    return f"{horas} h {resto:02d} min" if horas else f"{resto} min"


def _precio(valor: float) -> str:
    return f"{int(valor)} €" if float(valor).is_integer() else f"{valor:.2f} €"


def formatear_vuelos(resultado: dict) -> str:
    consulta = resultado["consulta"]
    fecha = datetime.strptime(consulta["fecha"], "%Y-%m-%d").strftime("%d/%m/%Y")
    lineas = [
        "✈️ Vuelos con horario y precio comprobados",
        f"Ruta: {consulta['origen']} → {consulta['destino']}",
        f"Fecha: {fecha} · Solo ida · 1 adulto · EUR",
    ]
    if consulta.get("fecha_inferida"):
        lineas.append("Suposición explícita: interpreté «primer/próximo vuelo» como mañana.")
    for indice, opcion in enumerate(resultado["opciones"], 1):
        aerolinea = ", ".join(opcion["aerolineas"]) or "Aerolínea no indicada"
        numero = ", ".join(opcion["vuelos"])
        escalas = "directo" if opcion["escalas"] == 0 else f"{opcion['escalas']} escala(s)"
        lineas.extend(
            [
                "",
                f"{indice}. {aerolinea} — {_precio(opcion['precio_eur'])}",
                f"Salida: {opcion['salida']}",
                f"Llegada: {opcion['llegada']}",
                f"Trayecto: {escalas} · {_duracion(opcion['duracion_minutos'])}",
            ]
        )
        if numero:
            lineas.append(f"Vuelo: {numero}")
    lineas.extend(
        [
            "",
            "Fuente: " + str(resultado.get("fuente", "motor de vuelos")),
            "Precio observado en esta consulta; puede cambiar al reservar.",
        ]
    )
    if resultado.get("url"):
        lineas.append("Verificar/reservar: " + str(resultado["url"]))
    return "\n".join(lineas)


def responder_consulta_vuelo(texto: str, entorno: dict[str, str]) -> str:
    analisis = analizar_consulta_vuelo(texto)
    if not analisis.get("es_vuelo"):
        raise ViajesError("La consulta no es de vuelos.")
    ejemplo_fecha = (_hoy_tirana() + timedelta(days=1)).strftime("%d/%m/%Y")
    if analisis.get("error_fecha"):
        return (
            "⚠️ " + str(analisis["error_fecha"])
            + f" Escribe una fecha futura, por ejemplo {ejemplo_fecha}."
        )
    faltan = set(analisis.get("faltan", []))
    if "origen" in faltan or "destino" in faltan:
        return (
            "✈️ Necesito origen y destino exactos (ciudad, aeropuerto o código IATA). "
            f"Ejemplo: /busca vuelo Tirana TIA a Milano Malpensa MXP el {ejemplo_fecha}"
        )
    if "fecha" in faltan:
        return (
            f"✈️ Entendí la ruta {analisis['origen']} → {analisis['destino']}, "
            "pero falta la fecha exacta. Escríbela, por ejemplo: "
            f"/busca vuelo {analisis['origen']} a {analisis['destino']} el {ejemplo_fecha}"
        )
    clave = (
        entorno.get("SERPAPI_API_KEY", "").strip()
        or entorno.get("SERPAPI_KEY", "").strip()
    )
    if not clave:
        return (
            "❌ No puedo verificar horario y precio real: falta SERPAPI_API_KEY en ~/luna/.env. "
            "Tavily y Brave encuentran páginas, pero no ofrecen inventario de vuelos. "
            "No voy a llamar a eso una búsqueda completada."
        )
    try:
        return formatear_vuelos(buscar_vuelos_serpapi(texto, clave=clave))
    except ViajesError as error:
        return f"⚠️ No pude confirmar vuelos reales: {error} No voy a inventar horarios ni precios."
