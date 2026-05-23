from __future__ import annotations

import sys

from sitop_loxone_bridge.bridge import configure_logging, main as bridge_main
from sitop_loxone_bridge.config import Settings


def _run_web() -> None:
    import uvicorn

    settings = Settings()
    configure_logging(settings.log_level)
    uvicorn.run(
        "sitop_loxone_bridge.web.app:create_app",
        host=settings.web_host,
        port=settings.web_port,
        factory=True,
        log_level=settings.log_level.lower(),
        access_log=False,
    )


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "bridge"
    # Drop the mode argument so downstream argparse doesn't see it.
    sys.argv = [sys.argv[0]] + sys.argv[2:]
    if mode == "web":
        _run_web()
    elif mode == "bridge":
        bridge_main()
    else:
        print(
            f"Unknown mode {mode!r}. Use 'bridge' or 'web'.",
            file=sys.stderr,
        )
        sys.exit(2)


if __name__ == "__main__":
    main()
