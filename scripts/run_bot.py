#!/usr/bin/env python3
"""Quick-start script for full bot mode."""
import sys
sys.path.insert(0, "src")
from src.main import run
import click
from click.testing import CliRunner

if __name__ == "__main__":
    import sys
    live = "--live" in sys.argv
    port = 8080
    for i, arg in enumerate(sys.argv):
        if arg == "--port" and i + 1 < len(sys.argv):
            port = int(sys.argv[i + 1])
    
    from src.main import cli
    args = ["run"]
    if live:
        args.append("--live")
    args.extend(["--port", str(port)])
    cli(args, obj={})
