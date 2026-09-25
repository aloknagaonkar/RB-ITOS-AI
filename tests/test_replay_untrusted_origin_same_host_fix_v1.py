from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from urllib.parse import urlsplit


def build_app():
    app = FastAPI()

    @app.middleware("http")
    async def local_mutations(request: Request, call_next):
        if request.method == "POST":
            origin = request.headers.get("origin")
            host = request.headers.get("host")
            explicit_trusted_origins = {
                "http://localhost:5173",
                "http://127.0.0.1:5173",
                "http://localhost:8000",
                "http://127.0.0.1:8000",
                "http://localhost:8123",
                "http://127.0.0.1:8123",
            }
            same_host_origin = False
            if origin and host:
                try:
                    same_host_origin = urlsplit(origin).netloc == host
                except ValueError:
                    same_host_origin = False
            if origin is not None and origin not in explicit_trusted_origins and not same_host_origin:
                return JSONResponse({"detail":"Untrusted origin"}, status_code=403)
        return await call_next(request)

    @app.post("/x")
    def x():
        return {"ok": True}

    return app


def test_external_same_host_origin_allowed():
    c = TestClient(build_app(), base_url="http://34.100.143.245:8123")
    r = c.post("/x", headers={"Origin":"http://34.100.143.245:8123"})
    assert r.status_code == 200


def test_cross_host_origin_rejected():
    c = TestClient(build_app(), base_url="http://34.100.143.245:8123")
    r = c.post("/x", headers={"Origin":"http://evil.example"})
    assert r.status_code == 403


def test_originless_cli_post_allowed():
    c = TestClient(build_app(), base_url="http://34.100.143.245:8123")
    r = c.post("/x")
    assert r.status_code == 200
