# Luna Agent — versión integrada autónoma políglota 6.0

Luna reúne en un solo bot para Termux el razonamiento, la búsqueda, la memoria,
la rotación de modelos y el manejo de archivos de Telegram. El núcleo funciona
con la biblioteca estándar; la lectura de PDF usa `pypdf` cuando está instalado.

La versión 6 unifica las nueve conexiones reales: seis proveedores de IA,
Telegram, Tavily y Brave. Corrige el nombre de la variable de Brave, usa la
autenticación Bearer actual de Tavily y comprueba todo desde el mismo puente.
Consulta `RESUMEN_LUNA_COMPLETO.md` para ver la separación segura entre Termux,
archivos históricos y nube.

## Automejora segura y políglota

La versión 4 incorpora siete agentes locales y ligeros:

- **Centinela:** revisa código, JSON privados, permisos, espacio,
  bloqueo del proceso, registro y servicio.
- **Diagnóstico:** separa un error real de código de una caída temporal o una
  dependencia ausente.
- **Reparación:** solo ejecuta acciones permitidas: proteger archivos, quitar un
  bloqueo obsoleto, restaurar memoria desde copia válida, reinstalar `pypdf`,
  levantar el servicio o volver a la última versión buena.
- **Verificación:** compila todos los `.py`, valida los `.sh` y ejecuta toda la
  batería de pruebas después de cualquier reparación.
- **Políglota:** reconoce más de 30 lenguajes y valida cada archivo con un
  analizador seguro. Si el compilador local no existe, lo declara en lugar de
  fingir una prueba.
- **Evolución:** observa una mejora válida durante tres ciclos completos antes
  de convertirla en la nueva versión buena; conserva la anterior para volver
  atrás.
- **Actualización:** una vez al día revisa el repositorio configurado. Solo
  instala una versión numéricamente superior que conserve capacidades, no
  contenga archivos privados y supere todas las pruebas; si falla, revierte.

El mantenimiento corre cada cinco minutos como servicio independiente
`luna-automejora`. No modifica `.env`, tokens ni memoria válida. Guarda un
estado consultable con `/automejora`; `/reparar` fuerza un ciclo y `/actualizar`
fuerza la revisión del repositorio.

## Lenguajes de programación

Luna puede leer, explicar y revisar archivos Python, Shell, JavaScript,
TypeScript, JSON/JSONL, YAML, TOML, XML, HTML, CSS/SCSS, SQL, C/C++, Go, Rust,
Java, Kotlin, PHP, Ruby, Lua, R, Swift, Dart, C#, PowerShell, Perl, Haskell,
Scala, Vue, Svelte, Markdown, Dockerfile, Makefile y CMake.

Las comprobaciones internas de Python, JSON, TOML, XML, HTML, INI y estructuras
de texto no necesitan instalar nada. Para Bash, JavaScript, C/C++, Go, Rust,
PHP, Ruby, Lua, R, Swift o PowerShell usa la herramienta local correspondiente
solo si ya está disponible. Nunca ejecuta el programa recibido y no instala
compiladores grandes por sorpresa.

Puedes enviar esos archivos directamente por Telegram. `/lenguajes` muestra
qué encontró, qué pudo validar y qué herramienta falta. El centinela incluye
todo el código reconocido en la copia recuperable, mueve a cuarentena un
archivo nuevo con sintaxis rota y restaura uno conocido desde la última versión
buena.

Ningún programa puede garantizar la reparación de cualquier fallo desconocido.
Luna arregla automáticamente los casos comprobables y reversibles. Ante un
problema nuevo, conserva los datos, informa lo pendiente y evita aplicar código
inventado a ciegas.

## Qué incorpora

- Reglas de honestidad, verificación y prevención de bucles.
- Separación entre hechos, inferencias y dudas.
- Medición de cobertura por fuentes independientes.
- Protección frente a instrucciones maliciosas encontradas en páginas web.
- Memoria privada local que Git no publica.
- Filtro de relevancia que impide usar noticias ajenas al tema solicitado.
- Fotos, notas de voz y documentos enviados directamente por Telegram.
- Orden adaptativo de proveedores según éxitos y latencia, manteniendo los
  proveedores gratuitos por delante de DeepSeek y OpenAI.
- Catálogo de modelos renovado cada seis horas desde cada API para elegir
  versiones estables superiores sin cambiar la configuración; las APIs de pago
  continúan al final.
- Pruebas automáticas antes de ejecutar la búsqueda en GitHub Actions.

## Actualizar y comprobar en Termux

```bash
cd ~/luna && git pull && python -m unittest -v && python luna.py --mente
```

Para hacer una búsqueda:

```bash
python luna.py "qué quieres investigar"
```

Luna separa dos clases de consulta. Para preguntas generales usa DuckDuckGo,
Bing RSS y Wikipedia; para información reciente añade Google News y GDELT.
Así una pregunta sobre reparar una bicicleta no termina respondida con titulares
sin relación. También activa Tavily o Brave automáticamente si sus claves ya
existen en `.env`, sin exigirlas para funcionar.

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
- puede buscar en Internet con `/buscar tema` o cuando detecta una consulta actual;
- analiza fotos con Gemini, OpenRouter u OpenAI;
- transcribe notas de voz con Groq Whisper;
- lee PDF, DOCX, TXT, MD, CSV y JSON sin guardar el adjunto recibido.

Ejemplo de búsqueda real desde Telegram:

```text
/buscar precio actual de Bitcoin
```

Cuando hay resultados, Luna muestra `🔎 Búsqueda real completada`, resume solo
el contexto recuperado y añade los enlaces. Si fallan todas las fuentes, informa
del fallo y no deja que el modelo improvise datos ni instrucciones para crear
claves de Bing o Google.

El orden inicial prioriza Groq GPT-OSS 120B, Gemini, Cerebras GPT-OSS 120B y el
router gratuito de OpenRouter. Si todos fallan, puede usar DeepSeek u OpenAI;
esas dos APIs podrían consumir saldo según la cuenta. Se puede cambiar el orden
con `LUNA_PROVIDERS` dentro del `.env`.

Comprobar las nueve conexiones reales sin generar texto de IA:

```bash
python telegram_luna.py --check
```

La salida válida termina con `9/9 conexiones activas`. Esta comprobación hace
una búsqueda mínima con Tavily y otra con Brave; el resto solo autentica y lista
modelos.

Iniciar el bot:

```bash
python telegram_luna.py
```

Durante la primera prueba puedes detenerlo con `CTRL+C`. Nunca publiques `.env`,
`.telegram_owner`, `memoria_privada.json` ni `memoria_telegram.json`.

## Mantener Luna activa

El instalador incluido usa `termux-services` para ejecutar Luna en segundo plano
y reiniciarla si el proceso falla:

```bash
bash instalar_servicio_termux.sh
```

Comprobar el servicio y ver su registro:

```bash
sv status luna-telegram
tail -f "$PREFIX/var/log/sv/luna-telegram/current"
```

En Telegram, `/vigilar` comprueba todas las APIs sin generar texto. Luna avisa
en el chat cuando un proveedor deja de responder y cuando se recupera. El
intervalo predeterminado es de 10 minutos; se puede cambiar en `.env`, por
ejemplo con `LUNA_HEALTH_INTERVAL=300`.

Para arrancar después de reiniciar Android instala
[Termux:Boot](https://github.com/termux/termux-boot), ábrelo una vez y deja
Termux con batería **Sin restricciones**. Cerrar una ventana de Termux no detiene
el servicio, pero Android sí puede impedir todo reinicio después de pulsar
**Forzar detención**; ninguna aplicación local puede avisar mientras está
forzosamente detenida.

El comando `/diagnostico` prueba desde Telegram las APIs y una búsqueda neutral
sin gastar una generación. Nunca usa una noticia fija como prueba.

Comandos nuevos:

```text
/automejora   estado de los siete agentes
/reparar      revisión y reparación inmediata
/actualizar   busca, prueba e instala solo una versión superior
/rendimiento  orden aprendido de proveedores
/lenguajes    estado real del motor políglota
```

Android sigue teniendo un límite físico: si se pulsa **Forzar detención** sobre
Termux, Android mata tanto Luna como su centinela. Ambos vuelven a arrancar al
abrir Termux o mediante Termux:Boot si el sistema permite el inicio.

## GitHub Actions

En GitHub abre **Actions → Luna - búsqueda y núcleo → Run workflow**. La
ejecución debe pasar primero las pruebas y después mostrar `✅ INTERNET OK`.

## Seguridad

Nunca pongas API keys, contraseñas, tokens ni memoria privada dentro del código
del repositorio público. Cuando Luna necesite una API, usa GitHub Secrets o una
variable local de Termux.
