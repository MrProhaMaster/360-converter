# Сторонние компоненты

- Python и Tk: https://www.python.org/psf/license/ — используются в Windows-пакете PyInstaller.
- Pillow: https://github.com/python-pillow/Pillow/blob/main/LICENSE — обработка JPEG/ICC и экранный предпросмотр.
- NumPy: https://numpy.org/doc/stable/license.html — быстрый расчёт сферического предпросмотра. Лицензия NumPy и сведения о включённых в wheel библиотеках находятся в `_internal/numpy-*.dist-info/` переносимой сборки.
- PyInstaller: https://pyinstaller.org/en/stable/license.html — сборка распространяемого приложения.
- FFmpeg: https://ffmpeg.org/legal.html — начиная с версии 1.4, в Windows x64 пакет включён неизменённый FFmpeg 9.0.2 essentials (Gyan) из `imageio-ffmpeg==0.8.1`. Он работает отдельным процессом. Конфигурация содержит `--enable-gpl --enable-version3`; лицензия этого бинарника — GPL версии 3 или более поздней, а не BSD-лицензия Python-обёртки. Текст GPL находится в `licenses/FFmpeg-GPLv3.txt`.
- imageio-ffmpeg: https://github.com/imageio/imageio-ffmpeg/tree/v0.8.1 — BSD-2-Clause; с версии 1.5.1 входит в обычные зависимости Python-приложения и предоставляет FFmpeg при запуске исходников. Также используется при сборке и тестировании как источник проверенного бинарника. Python-обёртка не нужна во время работы EXE и исключена из PyInstaller-пакета, чтобы не дублировать FFmpeg. Её лицензия копируется в `licenses/imageio-ffmpeg-BSD.txt`.
- pytest: https://github.com/pytest-dev/pytest — только тесты.

В собранной папке `licenses/FFmpeg-build.txt` содержит точную конфигурацию и уведомление FFmpeg; `licenses/FFmpeg-provenance.json` — версию, SHA-256 и источники. FFmpeg: https://github.com/FFmpeg/FFmpeg/tree/n9.0.2, архив исходников: https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz. Поставщик Windows-сборки и сведения о включённых библиотеках: https://www.gyan.dev/ffmpeg/builds/. Исходный рецепт получения бинарника: https://github.com/imageio/imageio-ffmpeg/blob/v0.8.1/tools/download_ffmpeg.py.

При передаче Windows-пакета сохраняйте папку `licenses` и сведения о происхождении. Условия предоставления соответствующих исходников при дальнейшем распространении определяются GPL; ссылки на исходники не меняют эти условия. Бинарники, личные фотографии и результаты экспорта не добавляются в Git.
