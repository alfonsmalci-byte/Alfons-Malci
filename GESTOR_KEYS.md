# Gestor privado de claves de Luna

El gestor trabaja únicamente con credenciales creadas en las cuentas de su
propietario. Nunca busca claves ajenas, no guarda contraseñas y no publica el
correo ni el archivo `.env` en GitHub.

## Comandos

Comprobar todas las claves sin generar respuestas de IA:

```bash
cd ~/luna && python gestor_keys_luna.py estado
```

Ver o abrir los portales con acceso gratuito:

```bash
cd ~/luna && python gestor_keys_luna.py enlaces
cd ~/luna && python gestor_keys_luna.py enlaces --abrir
```

Guardar el correo solo en el móvil y completar claves que falten:

```bash
cd ~/luna && python gestor_keys_luna.py correo TU_CORREO
cd ~/luna && python gestor_keys_luna.py configurar
```

Validar una clave nueva antes de sustituir la anterior:

```bash
cd ~/luna && python gestor_keys_luna.py rotar groq
```

También se aceptan `gemini`, `openrouter`, `cerebras`, `deepseek`, `openai` y
`telegram`. La nueva credencial se solicita de forma oculta, se valida y solo
entonces se actualiza `.env`; si falla, se conserva la anterior.

## Lo que se vigila

El servicio `luna-keys` ejecuta `gestor_keys_luna.py servicio` y comprueba
periódicamente la autenticación sin generar
texto ni gastar una respuesta del modelo. Envía un aviso al chat privado de
Telegram si una clave deja de funcionar o vuelve a funcionar. El intervalo por
defecto es de seis horas y se puede cambiar en `.env`:

```text
LUNA_KEYS_INTERVAL=21600
```

La cuota gratuita pertenece a la cuenta del proveedor. Cambiar o crear otra
key no reinicia esa cuota y el gestor no intenta evitar sus límites.
