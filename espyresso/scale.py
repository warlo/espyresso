"""The Bluetooth scale (Eureka Precisa), run as its own process:

    python3 -m espyresso.scale

Bluetooth on the Pi Zero is Python work for every advertisement while
searching and every notification while connected (bleak decodes BlueZ's
D-Bus messages). Inside the app it competed with temperature decoding for
the GIL and delayed readings by 3-4 s per search. Here it runs at the lowest
CPU priority in its own interpreter, and only hands the app one line per
reading on stdout:

    w <grams>              a weight notification
    link connected         notifications started
    link disconnected      the scale went away

SIGUSR1 makes it search now instead of after its back-off; SIGTERM stops it.
"""
import asyncio
import logging
import os
import signal
import sys
from typing import Any, Awaitable, Optional, TextIO

from espyresso import config

logger = logging.getLogger("espyresso.scale")


def retry_delay(failures: int) -> float:
    """Seconds before the next search after ``failures`` in a row: searching
    for a scale that is asleep or away is the expensive part."""
    return float(
        min(
            config.BLUETOOTH_RETRY_MAX_SECONDS,
            config.BLUETOOTH_RETRY_SECONDS * 2 ** max(0, failures - 1),
        )
    )


def grams_from(data: bytearray) -> float:
    """Eureka Precisa weight notification: tenths of a gram in bytes 7-8
    (little endian), the sign in byte 6."""
    grams = int.from_bytes(data[7:9], "little") / 10
    return -grams if data[6] else grams


async def _first(*aws: Awaitable[Any], timeout: Optional[float] = None) -> None:
    """Wait until the first of ``aws`` finishes (or ``timeout``)."""
    tasks = [asyncio.ensure_future(a) for a in aws]
    _, pending = await asyncio.wait(tasks, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()


async def _orphaned(parent: int) -> None:
    """Returns once the app that started us is gone."""
    while os.getppid() == parent:
        await asyncio.sleep(2.0)


async def run(out: TextIO = sys.stdout) -> None:
    from bleak.backends.bluezdbus.client import BleakClientBlueZDBus as BleakClient
    from bleak.backends.bluezdbus.scanner import BleakScannerBlueZDBus as BleakScanner

    loop = asyncio.get_running_loop()
    stop, wake = asyncio.Event(), asyncio.Event()
    loop.add_signal_handler(signal.SIGTERM, stop.set)
    loop.add_signal_handler(signal.SIGUSR1, wake.set)
    orphaned = asyncio.ensure_future(_orphaned(os.getppid()))
    orphaned.add_done_callback(lambda _: stop.set())
    address = config.BLUETOOTH_SCALE_ADDRESS.lower()

    def emit(line: str) -> None:
        out.write(line + "\n")
        out.flush()

    failures = 0
    while not stop.is_set():
        try:
            # Our own search, so BlueZ can drop repeated advertisements
            # (bleak's connect() would search again, unfiltered).
            device = await BleakScanner.find_device_by_filter(
                lambda d, ad: d.address.lower() == address,
                timeout=config.BLUETOOTH_SEARCH_SECONDS,
                filters={"DuplicateData": False},
            )
            if device is None:
                raise LookupError("scale not found")
            gone = asyncio.Event()

            def on_disconnect(_: Any) -> None:
                loop.call_soon_threadsafe(gone.set)

            async with BleakClient(device, disconnected_callback=on_disconnect) as client:
                failures = 0
                await client.start_notify(
                    config.BLUETOOTH_NOTIFY_UUID, lambda _, data: emit(f"w {grams_from(data)}")
                )
                emit("link connected")
                await _first(gone.wait(), stop.wait())
                emit("link disconnected")
        except BrokenPipeError:
            return  # the app is gone
        except Exception as e:  # noqa: BLE001 - any failure means "try again later"
            failures += 1
            logger.info("scale not reachable (%s in a row): %s", failures, e)
        if failures and not stop.is_set():
            wake.clear()
            await _first(wake.wait(), stop.wait(), timeout=retry_delay(failures))
    orphaned.cancel()


def main() -> None:
    os.nice(19)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    asyncio.run(run())


if __name__ == "__main__":
    main()
