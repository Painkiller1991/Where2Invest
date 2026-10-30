import uvicorn

from app.config_loader import load_config


def main() -> None:
    cfg = load_config()
    server = cfg.get("server") or {}
    uvicorn.run(
        "app.main:app",
        host=server.get("host", "127.0.0.1"),
        port=int(server.get("port", 8000)),
        reload=True,
    )


if __name__ == "__main__":
    main()
