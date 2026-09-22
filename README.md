# Luna Agent — núcleo 1.0

Luna ya tiene una capa reutilizable de razonamiento y seguridad, además de su
búsqueda real en Internet. Está pensada para funcionar tanto en Termux como en
GitHub Actions y no necesita paquetes externos de Python.

## Qué incorpora

- Reglas de honestidad, verificación y prevención de bucles.
- Separación entre hechos, inferencias y dudas.
- Medición de cobertura por fuentes independientes.
- Protección frente a instrucciones maliciosas encontradas en páginas web.
- Memoria privada local que Git no publica.
- Pruebas automáticas antes de ejecutar la búsqueda en GitHub Actions.

## Actualizar y comprobar en Termux

```bash
cd ~/luna && git pull && python -m unittest -v && python luna.py --mente
```

Para hacer una búsqueda:

```bash
python luna.py "qué quieres investigar"
```

El informe queda en `resultados/ultima_busqueda.json` e incluye la cobertura de
fuentes. Una cobertura alta significa que aparecieron varios orígenes; no
garantiza por sí sola que todos digan la verdad.

## Memoria privada opcional

Puedes crear en Termux un archivo llamado `memoria_privada.json`:

```json
{
  "nombre_preferido": "Alfons",
  "objetivos": ["mejorar Luna"],
  "preferencias": ["respuestas claras y directas"]
}
```

Ese nombre ya está excluido por `.gitignore`: permanece en tu teléfono y no se
sube al repositorio. No guardes allí contraseñas ni tokens.

## Límite real de esta versión

Este núcleo transmite reglas y método de trabajo, no copia el modelo interno de
ChatGPT ni sus pesos. Las respuestas de Telegram se generan mediante las APIs
que Alfons tenga configuradas en su `.env` privado.

## Telegram en Termux

El puente `telegram_luna.py`:

- conecta el bot de Telegram con Luna;
- usa Groq, Gemini, Cerebras, OpenRouter, DeepSeek y OpenAI en modo automático;
- cambia al siguiente proveedor cuando uno falla;
- guarda la conversación únicamente en `memoria_telegram.json` dentro del móvil;
- vincula el bot al primer chat privado que le escriba y rechaza otros usuarios;
- puede buscar en Internet con `/buscar tema` o cuando detecta una consulta actual.

El orden inicial prioriza Groq, Gemini, Cerebras y OpenRouter. Si todos fallan,
puede usar DeepSeek u OpenAI; esas dos APIs podrían consumir saldo según la
cuenta. Se puede cambiar el orden con `LUNA_PROVIDERS` dentro del `.env`.

Comprobar la configuración sin generar texto ni consumir una respuesta de IA:

```bash
python telegram_luna.py --check
```

Iniciar el bot:

```bash
python telegram_luna.py
```

Termux debe permanecer abierto durante la primera prueba. Para detenerlo, pulsa
`CTRL+C`. Nunca publiques `.env`, `.telegram_owner`, `memoria_privada.json` ni
`memoria_telegram.json`.

## GitHub Actions

En GitHub abre **Actions → Luna - búsqueda y núcleo → Run workflow**. La
ejecución debe pasar primero las pruebas y después mostrar `✅ INTERNET OK`.

## Seguridad

Nunca pongas API keys, contraseñas, tokens ni memoria privada dentro del código
del repositorio público. Cuando Luna necesite una API, usa GitHub Secrets o una
variable local de Termux.
