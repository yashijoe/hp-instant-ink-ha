"""Check what a printer exposes, without Home Assistant.

Usage: python scripts/check_printer.py 192.168.1.50
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import aiohttp

_PATH = Path(__file__).parents[1] / "custom_components" / "hp_instant_ink" / "api.py"
_SPEC = importlib.util.spec_from_file_location("hp_api", _PATH)
api = importlib.util.module_from_spec(_SPEC)
sys.modules["hp_api"] = api
_SPEC.loader.exec_module(api)


async def main(host: str) -> int:
    async with aiohttp.ClientSession() as session:
        client = api.HPPrinterClient(session, host)
        try:
            identity = await client.async_get_identity()
            data = await client.async_get_data()
        except api.HPPrinterError as err:
            print(f"Errore: {err}")
            return 1
    print(f"Modello:        {identity.model}")
    print(f"Firmware:       {identity.firmware}")
    print(f"Pagine totali:  {data.total_pages}")
    print(f"  bianco/nero:  {data.mono_pages}")
    print(f"  colore:       {data.color_pages}")
    for code, level in data.supplies.items():
        print(f"Inchiostro {code}: {level}%")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(asyncio.run(main(sys.argv[1])))
