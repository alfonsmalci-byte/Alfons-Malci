# Resumen completo de Luna en Termux

## Lo que construimos

Luna pasó de ser un conjunto de pruebas sueltas a una IA privada conectada a
Telegram y ejecutada desde Termux. La configuración sensible vive solo en
`~/luna/.env`; el repositorio contiene código, pruebas y documentación, nunca
las claves ni la memoria privada.

La versión integrada incluye:

- conexión privada con Telegram y vinculación al primer propietario;
- seis proveedores de IA con cambio automático: Groq, Gemini, Cerebras,
  OpenRouter, DeepSeek y OpenAI;
- estado separado de las seis IA, Telegram, Tavily y Brave: configuración,
  autenticación, respuesta completa y resultado exacto;
- motor de vuelos estructurado con SerpAPI/Google Flights cuando existe
  `SERPAPI_API_KEY`; exige fecha y no presenta enlaces genéricos como precio;
- búsqueda real y relevante mediante DuckDuckGo, Bing RSS, Wikipedia, Google
  News y GDELT, más Tavily o Brave cuando ya existe su clave;
- memoria local de conversación y memoria privada excluidas de GitHub;
- lectura de fotos, audios, PDF, DOCX, texto, Markdown, CSV, JSON y código;
- reconocimiento y validación segura de más de 30 lenguajes de programación;
- siete etapas de mantenimiento con resultado guardado: inspección,
  diagnóstico, reparación, verificación, políglota, evolución y actualización;
- servicios `luna-telegram` y `luna-automejora`, con reinicio por runit y
  arranque mediante Termux:Boot cuando Android lo permite;
- vigilancia de APIs y avisos por Telegram si un proveedor falla o se recupera;
- pruebas automáticas, copia recuperable y vuelta atrás ante una actualización
  defectuosa.

## Qué une este integrador

El integrador instala el núcleo actual comprobado y añade dos piezas:

1. `inventario_luna.py` examina las descargas relacionadas con Luna, calcula su
   huella, valida Python/JSON y conserva copias seguras para revisión.
2. `luna_control.py` ofrece un único mando para estado, pruebas, servicios,
   claves, inventario y registros.

No mezcla a ciegas cada archivo antiguo. Un instalador viejo puede sobrescribir
una mejora nueva; un archivo para servidor usa `/opt/luna` y `systemd`, mientras
Termux usa `~/luna` y `runit`. Por eso esos archivos se catalogan y conservan,
pero no se ejecutan automáticamente.

## Datos que se conservan

Antes de cambiar el núcleo se crea una copia recuperable. No se reemplazan:

- `.env` y sus claves;
- `memoria_privada.json`;
- `memoria_telegram.json`;
- `.telegram_owner`;
- resultados, estados y registros locales válidos.

Los archivos privados, el inventario del teléfono y las copias de descargas
están incluidos en `.gitignore` y no deben subirse a GitHub.

## Comando único de control

Después de instalar:

```bash
luna-control estado
```

Otros comandos:

```bash
luna-control probar
luna-control diagnostico-real
luna-control claves
luna-control inventario
luna-control reiniciar
luna-control logs
```

`luna-control probar` compila el código, ejecuta todas las pruebas y comprueba
Telegram y los proveedores sin pedir una respuesta de IA. Usa
`luna-control probar --sin-red` para limitarse a pruebas locales.

Para consultar un vuelo, incluye siempre la fecha:

```text
/busca primer vuelo de Albania a Milano Malpensa mañana
```

Si falta la fecha o SerpAPI no está configurada, Luna lo indica y no inventa
horarios, precios ni una falsa “búsqueda completada”.

## Límite de Android

Cerrar la ventana de Termux normalmente no debería detener los servicios. Sí
puede detenerlos Android por ahorro de batería o al pulsar **Forzar detención**.
Para reducirlo, Termux debe tener batería **Sin restricciones**, Termux:Boot debe
abrirse una vez y no debe usarse **Forzar detención**. Ningún programa local
puede enviar una alerta después de que Android haya matado todos sus procesos.

## Oracle Cloud

`desplegar_luna_oracle.sh` instala el código desde GitHub, copia `.env` solo por
SSH cuando se usa `--copiar-claves`, crea un servicio `systemd` y lo verifica.
La copia local se detiene solo después de que Oracle devuelve `active`, para no
provocar HTTP 409 en Telegram. La captura de Oracle confirma que la instancia
existe y está encendida; todavía se necesitan la IP pública y la clave SSH para
demostrar la conexión y completar el despliegue.
