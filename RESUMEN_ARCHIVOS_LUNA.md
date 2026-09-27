# Inventario consolidado de Luna 8

Este documento sustituye la cadena de instaladores llamados “final”,
“definitivo” o “reparador”. Se encontraron **85 archivos relacionados con
Luna** guardados durante el trabajo. Muchos eran versiones sucesivas o
duplicados: que existieran no significaba que el bot los estuviera usando.

## Única versión activa

La versión que debe quedar en `~/luna` y en la rama `main` de GitHub es Luna
8.0. Sus piezas activas son:

| Archivo | Función comprobable |
|---|---|
| `telegram_luna.py` | Telegram, proveedores de IA, búsquedas y comandos |
| `luna.py` | búsqueda multifuente y filtro de evidencia exacta |
| `viajes_luna.py` | rutas/IATA y vuelos estructurados con SerpAPI |
| `nube_luna.py` | prueba SSH real y estado de `luna-telegram` en Oracle |
| `sabiduria_luna.py` | reglas y memoria privada local |
| `gestor_keys_luna.py` | valida claves sin mostrar sus valores |
| `automejora_luna.py` | mantenimiento local, pruebas y recuperación |
| `poliglota_luna.py` | reconoce formatos y usa validadores instalados |
| `inventario_luna.py` | cataloga descargas sin ejecutarlas |
| `luna_control.py` | mando único de estado, pruebas, servicios y registros |
| `desplegar_luna_oracle.sh` | instala desde GitHub en Oracle y activa systemd |
| `instalar_servicio_termux.sh` | servicio local runit para Termux |

Los archivos `test_*.py` son pruebas internas. Una prueba interna superada no
demuestra que una API externa haya generado una respuesta; por eso Luna 8 lo
indica por separado.

## Archivos privados que se conservan

Nunca se sobrescriben ni se suben a GitHub:

- `.env` (claves y configuración SSH);
- `memoria_privada.json` y `memoria_telegram.json`;
- `.telegram_owner` y el offset de Telegram;
- estadísticas, estados, registros y copias recuperables.

## Archivos históricos sustituidos

Quedan como historial recuperable, pero **no deben ejecutarse encima de Luna
8**:

- `integrar_todo_luna_termux_v5.sh`, `v6.sh`, `v7.sh` y sus duplicados;
- `luna_reparador_integral.py`, instaladores `luna_web_real*` y
  `activar_busqueda_real_luna.sh`;
- `instalar_gestor_keys_luna.sh`, `activar_luna_permanente_github.sh` e
  `instalar_luna_telegram_github.sh`;
- `mejorar_luna_total_v2.sh`, `mejorar_luna_autonoma_v3.sh` y
  `mejorar_luna_poliglota_v4.sh`;
- instaladores/actualizadores multimedia anteriores;
- `luna_puente_total_v1_0_0.py`, `luna_nucleo_propio_v1_0_1.py`,
  `luna_avanzador_v1_0_0.py`, `luna_doctor_ia_v1_0_0.py` y
  `autorreparador_luna_v1_1_0.py`;
- diagnósticos antiguos que declaraban “9/9 activo” después de comprobar solo
  autenticación.

El integrador 8 crea una copia antes de cambiar el núcleo. No borra el historial
automáticamente.

## Qué corrige Luna 8

- Una página genérica ya no se presenta como coche, precio, horario o vuelo
  exacto.
- Si se pide precio u hora, el resultado debe contener ese dato y coincidir con
  la consulta; si no, Luna dice que no lo encontró y muestra enlaces como “NO
  exactos”.
- `Prishtina`, `Pristina`, `Kosovo` y `PRN` se reconocen como el aeropuerto PRN.
- El diagnóstico separa: configurado, autenticado, respuesta completa
  registrada y resultado exacto.
- “Instancia Oracle Running” y “Luna activa en Oracle” ya no se confunden. El
  segundo estado solo aparece después de una conexión SSH y un
  `systemctl is-active luna-telegram` reales.
- El despliegue de Oracle detiene la copia de Termux únicamente después de
  verificar el servicio remoto, evitando dos procesos y el error Telegram 409.

## Límites que no se ocultan

- Tavily y Brave son buscadores, no inventarios de aerolíneas. Para afirmar un
  horario y precio de vuelo se necesita `SERPAPI_API_KEY` u otra API de vuelos
  estructurada.
- Una clave configurada no garantiza saldo, cuota ni una respuesta correcta.
- Luna no crea cuentas, acepta condiciones ni renueva claves automáticamente
  usando el correo: eso requiere autorización del propietario en cada proveedor
  y no debe automatizar CAPTCHAs, pagos o identidades.
- Cerrar o forzar la detención de Termux puede matar el proceso local; Oracle
  evita esa dependencia cuando su servicio remoto está verificado.
- La instancia mostrada en Oracle está encendida, pero para desplegar faltan la
  IP pública y la clave privada SSH del propietario. No deben publicarse.

## Comandos únicos

```bash
luna-control estado
luna-control probar
luna-control diagnostico-real   # consume una prueba mínima de cada API
luna-control logs
```

En Telegram:

```text
/estado
/diagnostico
/nube
/busca ...
```
