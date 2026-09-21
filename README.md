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
ChatGPT ni sus pesos. Luna todavía no genera respuestas completas con un modelo
de lenguaje; queda preparada para conectarlo después mediante una API y un
secreto seguro.

## GitHub Actions

En GitHub abre **Actions → Luna - búsqueda y núcleo → Run workflow**. La
ejecución debe pasar primero las pruebas y después mostrar `✅ INTERNET OK`.

## Seguridad

Nunca pongas API keys, contraseñas, tokens ni memoria privada dentro del código
del repositorio público. Cuando Luna necesite una API, usa GitHub Secrets o una
variable local de Termux.
