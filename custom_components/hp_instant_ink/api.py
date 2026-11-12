"""Client for the local web API (CDM) of recent HP printers.

Only depends on aiohttp. The printer serves HTTPS with a self-signed
certificate, so certificate verification is disabled for these requests.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import aiohttp

PATH_IDENTITY = "/cdm/system/v1/identity"
PATH_USAGE = "/cdm/deviceUsage/v1/lifetimeCounters"
PATH_SUPPLIES = "/cdm/supply/v1/suppliesPublic"
REQUEST_TIMEOUT = 15


class HPPrinterError(Exception):
    """The printer answered, but not with the data we need."""


class HPPrinterConnectionError(HPPrinterError):
    """The printer could not be reached."""


class HPPrinterUnsupportedError(HPPrinterError):
    """The device does not expose the page counter endpoint."""


@dataclass(frozen=True)
class PrinterIdentity:
    """Who the printer is."""

    model: str
    serial: str
    firmware: str | None


@dataclass(frozen=True)
class PrinterData:
    """Counters and ink levels read from the printer."""

    total_pages: int
    mono_pages: int | None
    color_pages: int | None
    supplies: dict[str, int] = field(default_factory=dict)


def normalize_host(host: str) -> str:
    """Strip scheme, path and spaces from what the user typed."""
    host = host.strip()
    for prefix in ("https://", "http://"):
        if host.lower().startswith(prefix):
            host = host[len(prefix) :]
    return host.split("/")[0]


class HPPrinterClient:
    """Reads identity, page counters and ink levels from an HP printer."""

    def __init__(self, session: aiohttp.ClientSession, host: str) -> None:
        self._session = session
        self.host = normalize_host(host)
        self._base = f"https://{self.host}"

    async def _get_json(self, path: str) -> dict[str, Any]:
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._session.get(self._base + path, ssl=False) as resp:
                    status = resp.status
                    payload = await resp.json(content_type=None) if status == 200 else None
        except (aiohttp.ClientError, TimeoutError) as err:
            raise HPPrinterConnectionError(f"Cannot reach {self.host}: {err}") from err
        except ValueError as err:
            raise HPPrinterError(f"Invalid answer from {self.host}{path}") from err
        if status == 404:
            raise HPPrinterUnsupportedError(f"{path} not found on {self.host}")
        if status != 200 or not isinstance(payload, dict):
            raise HPPrinterError(f"HTTP {status} from {self.host}{path}")
        return payload

    async def async_get_identity(self) -> PrinterIdentity:
        """Return model and serial number."""
        data = await self._get_json(PATH_IDENTITY)
        make = data.get("makeAndModel") or {}
        return PrinterIdentity(
            model=make.get("name") or make.get("base") or "HP printer",
            serial=str(data.get("serialNumber") or data.get("deviceUuid") or self.host),
            firmware=data.get("firmwareVersion"),
        )

    async def async_get_data(self) -> PrinterData:
        """Return the lifetime page counter and the ink levels."""
        usage = await self._get_json(PATH_USAGE)
        try:
            impressions = usage["printUsage"]["impressions"]
            total = int(impressions["total"])
        except (KeyError, TypeError, ValueError) as err:
            raise HPPrinterError("No page counter in the printer's answer") from err

        supplies: dict[str, int] = {}
        try:
            for supply in (await self._get_json(PATH_SUPPLIES)).get("suppliesList", []):
                code = supply.get("supplyColorCode")
                level = supply.get("percentLifeDisplay")
                if code and isinstance(level, (int, float)):
                    supplies[str(code)] = int(level)
        except HPPrinterError:
            # Ink levels are a nice-to-have: the page counter is what matters.
            pass

        return PrinterData(
            total_pages=total,
            mono_pages=impressions.get("monochrome"),
            color_pages=impressions.get("color"),
            supplies=supplies,
        )
