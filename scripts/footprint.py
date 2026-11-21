"""Weak-hardware regression check (run on the host: `make footprint`).

Starts the lite stack, seeds the corpus, and fails if the containers use more than 1 GiB of memory in total or if
seeding takes longer than 5 minutes. Standard library only, so it runs with any host Python 3.
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

PORT = os.environ.get("PORT", "8000")
LIMIT_MIB = 1024
COMPOSE = ["docker", "compose", "-f", "deploy/docker-compose.yml", "--profile", "lite"]


def mib(value: str) -> float:
    number, unit = re.match(r"([\d.]+)\s*([KMG]i?B)", value).groups()
    return float(number) * {"KiB": 1 / 1024, "KB": 1 / 1024, "MiB": 1, "MB": 1, "GiB": 1024, "GB": 1024}[unit]


def ready(timeout: float = 180) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://localhost:{PORT}/readyz", timeout=3) as r:
                if json.load(r).get("ready"):
                    return True
        except OSError:
            pass
        time.sleep(2)
    return False


def main() -> int:
    subprocess.run([*COMPOSE, "up", "-d", "--build"], check=True, env={**os.environ, "PORT": PORT})
    if not ready():
        print("stack did not become ready")
        return 1
    started = time.monotonic()
    seed = subprocess.run(["make", "seed", f"API_URL=http://host.docker.internal:{PORT}"])
    seconds = time.monotonic() - started
    stats = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{.Name}} {{.MemUsage}}"],
                           capture_output=True, text=True, check=True).stdout.splitlines()
    used = {line.split()[0]: mib(line.split()[1]) for line in stats if line.startswith("distrirag-")}
    total = sum(used.values())
    for name, value in sorted(used.items()):
        print(f"{name:28s} {value:8.1f} MiB")
    print(f"total {total:.1f} MiB (limit {LIMIT_MIB}); seed {seconds:.1f}s (limit 300)")
    return 0 if seed.returncode == 0 and total <= LIMIT_MIB and seconds <= 300 else 1


if __name__ == "__main__":
    sys.exit(main())
