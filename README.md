# Audio Admin

Aplicación local para Mac que edita metadatos y carátulas de tu música, en una pista o en muchas a la vez. Tus archivos no salen del ordenador.

## Descargar y abrir

1. Instala [FFmpeg](https://ffmpeg.org/): con Homebrew, `brew install ffmpeg`.
2. Descarga el ZIP de la [última versión](https://github.com/Paispe02/audio-admin/releases/latest) y descomprímelo.
3. Haz doble clic en `Abrir Audio Admin.command`. Se abre `http://127.0.0.1:8060` en el navegador; deja la ventana de Terminal abierta y usa `Ctrl+C` para cerrar.

El lanzador no está firmado por Apple. La primera vez ve a Ajustes del Sistema › Privacidad y seguridad › «Abrir igualmente». Como alternativa, abre Terminal en la carpeta y ejecuta `python3 app.py`.

Requiere macOS, Python 3.9 o posterior y FFmpeg. Usa solo la biblioteca estándar de Python.

## Privacidad y formatos

- Todo ocurre en tu Mac: el servidor escucha solo en `127.0.0.1` y rechaza peticiones de otras webs.
- Admite MP3, M4A/AAC, FLAC, OGG/Opus, WAV y AIFF. La escritura de etiquetas y carátulas es más completa en MP3, M4A y FLAC; WAV tiene metadatos limitados por el propio formato.
- La carátula se convierte a JPG cuadrado de 1400×1400 antes de incrustarse.
- La exportación copia el audio sin recodificar y descarga un ZIP nuevo. «Guardar en archivos originales» los sobrescribe y deja antes una copia en `.audio-admin/backups`.

## Pruebas

```bash
python3 tests/test_app.py
```

Licencia [MIT](LICENSE). Hecho por Alejandro Pais, [alejandropais.com](https://alejandropais.com/).
