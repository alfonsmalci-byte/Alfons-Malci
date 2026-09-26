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
- nueve conexiones verificables desde el mismo puente: los seis proveedores,
  Telegram, Tavily y Brave;
- búsqueda real y relevante mediante DuckDuckGo, Bing RSS, Wikipedia, Google
  News y GDELT, más Tavily o Brave cuando ya existe su clave;
- memoria local de conversación y memoria privada excluidas de GitHub;
- lectura de fotos, audios, PDF, DOCX, texto, Markdown, CSV, JSON y código;
- reconocimiento y validación segura de más de 30 lenguajes de programación;
- siete agentes de mantenimiento: centinela, diagnóstico, reparación,
  verificación, políglota, evolución y actualización;
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
luna-control claves
luna-control inventario
luna-control reiniciar
luna-control logs
```

`luna-control probar` compila el código, ejecuta todas las pruebas y comprueba
Telegram y los proveedores sin pedir una respuesta de IA. Usa
`luna-control probar --sin-red` para limitarse a pruebas locales.

## Límite de Android

Cerrar la ventana de Termux normalmente no debería detener los servicios. Sí
puede detenerlos Android por ahorro de batería o al pulsar **Forzar detención**.
Para reducirlo, Termux debe tener batería **Sin restricciones**, Termux:Boot debe
abrirse una vez y no debe usarse **Forzar detención**. Ningún programa local
puede enviar una alerta después de que Android haya matado todos sus procesos.

## Separación con la nube

Los componentes del servidor permanecen separados. En el servidor se usa
`/opt/luna` y `systemd`; en el móvil, `~/luna` y `runit`. El puente remoto puede
guardarse para revisión, pero este archivo instala únicamente la edición segura
para Termux.
