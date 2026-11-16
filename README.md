# Audio Admin

Aplicación local para importar música, leer y modificar metadatos, gestionar carátulas y descargar una versión nueva de los archivos.

## Ejecutar

```bash
cd "/Users/alejandropais/Documents/Audio Admin"
python3 app.py
```

Después abre `http://127.0.0.1:8060`.

## Privacidad y formatos

- Todo el proceso ocurre en este Mac; no hay subida a servicios externos.
- Admite MP3, M4A/AAC, FLAC, OGG/Opus, WAV y AIFF. La escritura de etiquetas y carátulas es más completa en MP3, M4A y FLAC; WAV tiene soporte de metadatos limitado por el propio formato.
- La carátula se convierte localmente a JPG cuadrado de 1400×1400 y se comprime antes de incrustarse.
- La exportación conserva el flujo de audio con `-c:a copy` (sin pérdida por recodificación) y descarga un ZIP nuevo. Los originales no se sobrescriben.

Requiere `ffmpeg` y `ffprobe`, ambos disponibles en este equipo.
