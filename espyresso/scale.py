"""The Bluetooth scale (Eureka Precisa), run as its own process:

    python3 -m espyresso.scale

Bluetooth is Python work for every D-Bus message bleak decodes. Inside the
app it competed with temperature decoding for the GIL and delayed readings
by 3-4 s per search. Here it runs at the lowest CPU priority in its own
interpreter. It never decodes advertisements: BlueZ searches, this process
asks it about the scale alone once a second (at the lowest priority it fell
behind decoding every nearby device's adverts), then connects to it by its
object path. Readings come over a socket from BlueZ (AcquireNotify) instead
of one D-Bus message each, and only the newest is kept: decoding ten
messages a second at the lowest priority fell ~10 s behind during a shot.
It hands the app one line per reading on stdout:

    w <grams>              a weight notification
    link connected         notifications started
    link disconnected      the scale went away

SIGUSR1 makes it search now instead of after its back-off. SIGTERM ends it
at once (no handler: a busy event loop would never run one), and the kernel
kills it when the app dies.
"""
import asyncio
import logging
import os
import signal
import sys
from typing import Any, Awaitable, Callable, Optional, Sequence, TextIO, Tuple

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


def newest_packet(fd: int, size: int) -> Optional[bytes]:
    """Read every packet waiting on ``fd`` and return the newest: None if
    there was none, b"" once the other end has closed."""
    os.set_blocking(fd, False)
    newest = None
    while True:
        try:
            packet = os.read(fd, size)
        except BlockingIOError:
            return newest
        if not packet:
            return b""
        newest = packet


async def _first(*aws: Awaitable[Any], timeout: Optional[float] = None) -> None:
    """Wait until the first of ``aws`` finishes (or ``timeout``)."""
    tasks = [asyncio.ensure_future(a) for a in aws]
    _, pending = await asyncio.wait(tasks, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()


def die_with_parent() -> None:
    """Have the kernel kill this process when the app that started it dies
    (Linux prctl PR_SET_PDEATHSIG), however busy its event loop is."""
    try:
        import ctypes

        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        libc.prctl(1, signal.SIGKILL)  # PR_SET_PDEATHSIG
    except OSError:
        return
    if os.getppid() == 1:
        sys.exit(0)  # the app died before we got here


async def run(out: TextIO = sys.stdout) -> None:
    from bleak.backends.bluezdbus.client import BleakClientBlueZDBus as BleakClient
    from bleak.backends.device import BLEDevice
    from dbus_next import Message, MessageType, Variant
    from dbus_next.aio import MessageBus
    from dbus_next.constants import BusType

    bus = await MessageBus(bus_type=BusType.SYSTEM, negotiate_unix_fd=True).connect()
    adapter = "/org/bluez/hci0"
    path = device_path(config.BLUETOOTH_SCALE_ADDRESS)

    async def bluez(obj: str, interface: str, member: str, signature: str = "", body: Sequence[Any] = ()) -> Any:
        message = Message(
            destination="org.bluez", path=obj, interface=interface, member=member, signature=signature, body=list(body)
        )
        return await bus.call(message)

    async def device_property(name: str) -> Any:
        reply = await bluez(path, "org.freedesktop.DBus.Properties", "Get", "ss", ("org.bluez.Device1", name))
        return None if reply.message_type == MessageType.ERROR else reply.body[0].value

    async def acquire_notify(char_path: str) -> Tuple[Optional[int], int]:
        """A socket that carries the characteristic's notifications, or
        (None, 0) if BlueZ refuses."""
        reply = await bluez(char_path, "org.bluez.GattCharacteristic1", "AcquireNotify", "a{sv}", ({},))
        if reply.message_type == MessageType.ERROR:
            logger.info("AcquireNotify refused (%s); falling back to D-Bus notifications", reply.error_name)
            return None, 0
        handle, mtu = reply.body
        fds = getattr(reply, "unix_fds", None) or []
        return (fds[handle] if isinstance(handle, int) and handle < len(fds) else handle), int(mtu)

    async def rssi() -> Optional[int]:
        value = await device_property("RSSI")
        return None if value is None else int(value)

    # The scale is Bluetooth LE: skip classic inquiry while searching.
    await bluez(adapter, "org.bluez.Adapter1", "SetDiscoveryFilter", "a{sv}", ({"Transport": Variant("s", "le")},))

    loop = asyncio.get_running_loop()
    wake = asyncio.Event()
    loop.add_signal_handler(signal.SIGUSR1, wake.set)

    def emit(line: str) -> None:
        out.write(line + "\n")
        out.flush()

    failures = 0
    while True:
        try:
            if await device_property("Connected"):
                # Left connected by a scale process that was killed: start clean.
                await bluez(path, "org.bluez.Device1", "Disconnect")
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
                char = client.services.get_characteristic(config.BLUETOOTH_NOTIFY_UUID)
                fd, mtu = await acquire_notify(char.path)
                if fd is None:
                    await client.start_notify(
                        config.BLUETOOTH_NOTIFY_UUID, lambda _, data: emit(f"w {grams_from(data)}")
                    )
                else:

                    def readable(fd: int = fd, size: int = max(mtu, 64)) -> None:
                        packet = newest_packet(fd, size)
                        if packet == b"":
                            gone.set()
                        elif packet:
                            emit(f"w {grams_from(bytearray(packet))}")

                    loop.add_reader(fd, readable)
                emit("link connected")
                try:
                    await gone.wait()
                finally:
                    if fd is not None:
                        loop.remove_reader(fd)
                        os.close(fd)
                emit("link disconnected")
        except BrokenPipeError:
            return  # the app is gone
        except Exception as e:  # noqa: BLE001 - any failure means "try again later"
            failures += 1
            logger.info("scale not reachable (%s in a row): %s", failures, e)
        if failures:
            wake.clear()
            await _first(wake.wait(), timeout=retry_delay(failures))


def main() -> None:
    die_with_parent()
    os.nice(19)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    asyncio.run(run())


if __name__ == "__main__":
    main()
