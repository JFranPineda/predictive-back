# predictive-back

Backend del sistema de mantenimiento predictivo. Django 5 + DRF, arquitectura
hexagonal, módulos instalables al estilo ERP.

El diseño completo está en [`predictive-docs`](../predictive-docs): empieza por
[el análisis de las fuentes](../predictive-docs/docs/00-source-analysis.md) y
[la arquitectura](../predictive-docs/docs/01-architecture.md).

## Arranque

```bash
cp .env.example .env
make up                 # postgres+timescale, redis, minio
make install
make bootstrap          # migra e instala los módulos core y auto
make run                # http://localhost:8000/api/docs/
make worker             # en otra terminal
```

## Estructura

```
config/            settings, urls, celery
modules/<módulo>/
  manifest.py      qué es el módulo: versión, dependencias, permisos, menú
  domain/          python puro — entidades, reglas, puertos. cero django
  application/     casos de uso
  infrastructure/  ORM, repositorios, tareas, adaptadores
  interfaces/      DRF: serializers, views, urls
```

La dirección de dependencias (`interfaces → infrastructure → application →
domain`) la verifica `lint-imports` en CI. Un `import django` dentro de
`domain/` rompe el build.

## Módulos

```bash
python manage.py modules list
python manage.py modules install vibration
python manage.py modules uninstall thermography
```

Todos los módulos se cargan y migran siempre; lo que `install` cambia es un
estado en base de datos que abre o cierra sus URLs, permisos y menú. Por eso
desinstalar **nunca borra histórico** — borrar datos es una acción aparte.

## Tests

```bash
pytest                      # todo
pytest tests/unit           # dominio puro, sin base de datos, < 1 s
```

Los tests de dominio comprueban el sistema contra los datos reales del cliente:
la cascada de umbrales reproduce los límites del reporte `EB P-757` y del
histórico `EB 228`, y el importador lee el RGP de 462 equipos de AMBEV Huachipa
si tienes `predictive-docs` clonado al lado.

## Estado

| | |
|---|---|
| Listo | registro de módulos con dependencias, cascada de umbrales (T12), importador RGP, modelos de activos/mediciones/media/seguridad, pipeline de imágenes |
| Falta | migraciones iniciales, fixtures YAML, serializers y views de cada módulo, espectros, reportes PDF |
