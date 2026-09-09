# Luna Agent — prueba 1

Objetivo de esta versión:

1. Ejecutarse en GitHub Actions sin depender del móvil.
2. Salir a Internet de verdad.
3. Hacer una búsqueda.
4. Guardar el resultado para comprobarlo.

## Qué NO tiene todavía

- Memoria personal.
- API keys.
- Modelos de IA.
- Agentes múltiples.
- Compras, pagos o acciones externas.

No añadiremos eso hasta que esta primera prueba pase.

## Prueba manual

En GitHub:

**Actions → Luna - prueba Internet → Run workflow**

Puedes escribir una búsqueda distinta y ejecutar.

La ejecución debe terminar en verde y mostrar:

`✅ INTERNET OK`

Además crea temporalmente un artifact llamado `resultado-luna`.

## Seguridad

Nunca pongas API keys, contraseñas ni memoria privada dentro del código del repositorio.
Cuando las necesitemos usaremos GitHub Secrets.
