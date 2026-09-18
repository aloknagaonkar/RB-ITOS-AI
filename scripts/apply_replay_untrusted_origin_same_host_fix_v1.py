from pathlib import Path

PATH = Path("backend/market_lab/api.py")
text = PATH.read_text(encoding="utf-8")

if "from urllib.parse import urlsplit" not in text:
    needle = "from pathlib import Path\n"
    if needle not in text:
        raise SystemExit("Safe-stop: pathlib import not found.")
    text = text.replace(needle, needle + "from urllib.parse import urlsplit\n", 1)

old = (
'    @app.middleware("http")\n'
'    async def local_mutations(request: Request, call_next):\n'
'        if request.method == "POST" and request.headers.get("origin") not in (\n'
'            None,\n'
'            "http://localhost:5173",\n'
'            "http://127.0.0.1:5173",\n'
'            "http://localhost:8000",\n'
'            "http://127.0.0.1:8000",\n'
'            "http://localhost:8123",\n'
'            "http://127.0.0.1:8123",\n'
'        ):\n'
'            return JSONResponse({"detail": "Untrusted origin"}, status_code=403)\n'
'        return await call_next(request)\n'
)

new = (
'    @app.middleware("http")\n'
'    async def local_mutations(request: Request, call_next):\n'
'        if request.method == "POST":\n'
'            origin = request.headers.get("origin")\n'
'            host = request.headers.get("host")\n'
'\n'
'            explicit_trusted_origins = {\n'
'                "http://localhost:5173",\n'
'                "http://127.0.0.1:5173",\n'
'                "http://localhost:8000",\n'
'                "http://127.0.0.1:8000",\n'
'                "http://localhost:8123",\n'
'                "http://127.0.0.1:8123",\n'
'            }\n'
'\n'
'            same_host_origin = False\n'
'            if origin and host:\n'
'                try:\n'
'                    same_host_origin = urlsplit(origin).netloc == host\n'
'                except ValueError:\n'
'                    same_host_origin = False\n'
'\n'
'            if origin is not None and origin not in explicit_trusted_origins and not same_host_origin:\n'
'                return JSONResponse({"detail": "Untrusted origin"}, status_code=403)\n'
'\n'
'        return await call_next(request)\n'
)

if new in text:
    print("Same-host origin fix already applied.")
elif old in text:
    PATH.write_text(text.replace(old, new, 1), encoding="utf-8")
    print("Applied same-host POST origin fix.")
else:
    raise SystemExit("Safe-stop: local_mutations block not found; no file modified.")
