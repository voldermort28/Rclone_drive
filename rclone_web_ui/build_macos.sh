pyinstaller --noconfirm --clean \
    --name "GDriveDL" \
    --windowed \
    --add-data "templates:templates" \
    --add-data "static:static" \
    --hidden-import "flask" \
    --hidden-import "engineio.async_drivers.threading" \
    app.py
