"""The Bluetooth scale (Eureka Precisa), run as its own process:

    python3 -m espyresso.scale

Bluetooth is Python work for every D-Bus message bleak decodes. Inside the
app it competed with temperature decoding for the GIL and delayed readings
by 3-4 s per search. Here it runs at the lowest CPU priority in its own
interpreter. It never decodes advertisements: BlueZ searches, this process
asks it about the scale alone once a second (at the lowest priority it fell
behind decoding every nearby device's adverts), then connects to it by its
object path. It hands the app one line per reading on stdout:

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
from typing import Any, Awaitable, Callable, Optional, Sequence, TextIO

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


def device_path(address: str, adapter: str = "hci0") -> str:
    """BlueZ's object for a device, e.g. /org/bluez/hci0/dev_B8_CA_04_28_79_84."""
    return f"/org/bluez/{adapter}/dev_" + address.upper().replace(":", "_")


async def wait_until_seen(
    rssi: Callable[[], Awaitable[Optional[int]]], seconds: float, poll: float = 1.0
) -> bool:
    """Whether BlueZ reports the device (it has an RSSI only while its
    search sees it) within ``seconds``."""
    end = asyncio.get_running_loop().time() + seconds
    while True:
        if await rssi() is not None:
            return True
        if asyncio.get_running_loop().time() >= end:
            return False
        await asyncio.sleep(poll)


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
    from bleak.backends.device import BLEDevice
    from dbus_next import Message, MessageType, Variant
    from dbus_next.aio import MessageBus
    from dbus_next.constants import BusType

    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    adapter = "/org/bluez/hci0"
    path = device_path(config.BLUETOOTH_SCALE_ADDRESS)

    async def bluez(obj: str, interface: str, member: str, signature: str = "", body: Sequence[Any] = ()) -> Any:
        message = Message(
            destination="org.bluez", path=obj, interface=interface, member=member, signature=signature, body=list(body)
        )
        return await bus.call(message)

    async def rssi() -> Optional[int]:
        reply = await bluez(path, "org.freedesktop.DBus.Properties", "Get", "ss", ("org.bluez.Device1", "RSSI"))
        return None if reply.message_type == MessageType.ERROR else int(reply.body[0].value)

    # The scale is Bluetooth LE: skip classic inquiry while searching.
    await bluez(adapter, "org.bluez.Adapter1", "SetDiscoveryFilter", "a{sv}", ({"Transport": Variant("s", "le")},))

    loop = asyncio.get_running_loop()
    stop, wake = asyncio.Event(), asyncio.Event()
    loop.add_signal_handler(signal.SIGTERM, stop.set)
    loop.add_signal_handler(signal.SIGUSR1, wake.set)
    orphaned = asyncio.ensure_future(_orphaned(os.getppid()))
    orphaned.add_done_callback(lambda _: stop.set())

    def emit(line: str) -> None:
        out.write(line + "\n")
        out.flush()

    failures = 0
    while not stop.is_set():
        try:
            await bluez(adapter, "org.bluez.Adapter1", "StartDiscovery")
            try:
                seen = await wait_until_seen(rssi, config.BLUETOOTH_SEARCH_SECONDS)
            finally:
                await bluez(adapter, "org.bluez.Adapter1", "StopDiscovery")
            if not seen:
                raise LookupError("scale not found")
            # By path, so bleak doesn't run a search of its own first.
            device = BLEDevice(config.BLUETOOTH_SCALE_ADDRESS, "scale", {"path": path, "props": {}})
            gone = asyncio.Event()

            def on_disconnect(_: Any) -> None:
                loop.call_soon_threadsafe(gone.set)

            async with BleakClient(
                device, disconnected_callback=on_disconnect, timeout=config.BLUETOOTH_CONNECT_SECONDS
            ) as client:
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
