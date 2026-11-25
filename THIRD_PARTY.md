# Сторонние компоненты

- Python и Tk: https://www.python.org/psf/license/ — используются в Windows-пакете PyInstaller.
- Pillow: https://github.com/python-pillow/Pillow/blob/main/LICENSE — обработка JPEG/ICC и экранный предпросмотр.
- PyInstaller: https://pyinstaller.org/en/stable/license.html — сборка распространяемого приложения.
- FFmpeg: https://ffmpeg.org/legal.html — отдельная внешняя программа. Лицензия конкретной сборки зависит от опций LGPL/GPL. Бинарник FFmpeg в исходный репозиторий и переносимую сборку не включён.
- imageio-ffmpeg: https://github.com/imageio/imageio-ffmpeg — только среда разработчика/тесты; содержит платформенный FFmpeg. Не включается в приложение.
- pytest: https://github.com/pytest-dev/pytest — только тесты.

При распространении бинарной сборки сохраняйте лицензионные тексты поставляемых зависимостей. Если самостоятельно добавляете FFmpeg, выполните требования лицензии именно выбранной сборки, включая доступ к соответствующему исходному коду там, где он требуется.
