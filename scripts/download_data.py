"""Download the raw Sivep-Gripe CSVs listed in data/raw/README.md (skips existing files)."""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"
BASE_URL = "https://s3.sa-east-1.amazonaws.com/ckan.saude.gov.br/SRAG"
FILES = {
    "INFLUD26-02-11-2026.csv": f"{BASE_URL}/2026/INFLUD26-02-11-2026.csv",
    "INFLUD25-02-11-2026.csv": f"{BASE_URL}/2025/INFLUD25-02-11-2026.csv",
    "dicionario-de-dados-2019-a-2025.pdf": f"{BASE_URL}/dicionario-de-dados-2019-a-2025.pdf",
}
CHUNK_BYTES = 1 << 20


def download(url: str, destination: Path) -> None:
    """Stream `url` to `destination`, verifying the declared content length."""
    partial = destination.with_suffix(destination.suffix + ".part")
    timeout = httpx.Timeout(60.0, read=300.0)
    with (
        httpx.Client(timeout=timeout, follow_redirects=True) as client,
        client.stream("GET", url) as response,
        partial.open("wb") as handle,
    ):
        response.raise_for_status()
        expected = int(response.headers.get("content-length", 0))
        received = 0
        for chunk in response.iter_bytes(CHUNK_BYTES):
            handle.write(chunk)
            received += len(chunk)
            print(f"\r  {received / 1_048_576:8.1f} MB", end="", file=sys.stderr)
    print(file=sys.stderr)
    if expected and received != expected:
        partial.unlink(missing_ok=True)
        msg = f"Incomplete download for {url}: {received} of {expected} bytes"
        raise RuntimeError(msg)
    partial.replace(destination)


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for name, url in FILES.items():
        destination = RAW_DIR / name
        if destination.exists() and destination.stat().st_size > 0:
            print(f"ok   {name} already present ({destination.stat().st_size / 1_048_576:.1f} MB)")
            continue
        print(f"get  {name}")
        download(url, destination)
    print("done")


if __name__ == "__main__":
    main()
