"""Entry point: ``quotestack-server``."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace

from quotestack.server.app import create_app
from quotestack.server.config import ConfigError, load

__all__ = ["main"]


def main(argv: list[str] | None = None) -> int:
    """Start the server, or print its OpenAPI document.

    Args:
        argv: Command line arguments, defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(prog="quotestack-server")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--config", help="path to quotestack.toml")
    parser.add_argument(
        "--dump-openapi",
        action="store_true",
        help="print the OpenAPI document and exit",
    )
    args = parser.parse_args(argv)

    try:
        config = load(args.config)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    if args.host:
        config = replace(config, host=args.host)
    if args.port:
        config = replace(config, port=args.port)

    app = create_app(config)
    if args.dump_openapi:
        json.dump(app.openapi(), sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0

    import uvicorn

    uvicorn.run(app, host=config.host, port=config.port, log_level=config.log_level.lower())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
