import logging
import threading
import time
from typing import TYPE_CHECKING, Any, Optional

from espyresso import config, shot_logger

if TYPE_CHECKING:
    from asyncio import Event

    from bleak.backends.bluezdbus.client import BleakClientBlueZDBus as BleakClient

logger = logging.getLogger(__name__)


def retry_delay(failures: int) -> float:
    """Seconds before the next connection attempt after ``failures`` in a
    row: searching for a scale that is asleep or away loads the Pi Zero."""
    return float(
        min(
            config.BLUETOOTH_RETRY_MAX_SECONDS,
            config.BLUETOOTH_RETRY_SECONDS * 2 ** max(0, failures - 1),
        )
    )


class BluetoothScale:
    current_weight_timestamp: float = 0
    current_weight: float = 0.0
    _logged_weight: Optional[float] = None
    _logged_at: float = 0.0
    _loop: Any = None
    _wake: Any = None
    bleak_client: "BleakClient" = None
    stop_event: Optional["Event"] = None
    disconnect_event: Optional["Event"] = None
    _thread: Optional[threading.Thread] = None

    def get_scale_weight(self) -> float:
        if time.perf_counter() - self.current_weight_timestamp > 5:
            return 0
        return self.current_weight

    def start(self) -> None:
        """Spawn the bluetooth notify loop on its own thread.

        Previously ``start`` called ``asyncio.run(self.notify())``
        directly, which blocks the caller. Since ``app.start()`` invokes
        ``self.bluetooth_scale.start()`` before ``self.display.start()``,
        a paired scale (or a sufficiently slow first failure) would
        prevent the display from ever launching."""
        if config.DEBUG:
            # Skip bluetooth in debug
            return
        if not config.BLUETOOTH_ENABLED:
            logger.info("bluetooth disabled via config.BLUETOOTH_ENABLED")
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        logger.info("bluetooth thread starting")
        try:
            import asyncio

            if config.PLATFORM == "darwin":
                from bleak.backends.corebluetooth.client import (
                    BleakClientCoreBluetooth as BleakClient,
                )
            else:
                from bleak.backends.bluezdbus.client import (
                    BleakClientBlueZDBus as BleakClient,
                )

            self.bleak_client = BleakClient(
                config.BLUETOOTH_SCALE_ADDRESS,
                disconnected_callback=self.disconnected,
                timeout=config.BLUETOOTH_CONNECT_TIMEOUT,
            )
            asyncio.run(self.notify())
        except Exception:
            # Defensive: this is a daemon thread, so an unhandled exception
            # here would otherwise die silently and leave the scale reading
            # frozen at its last value.
            logger.exception("bluetooth thread crashed")
        finally:
            logger.info("bluetooth thread exiting")

    def stop(self) -> None:
        if self.stop_event is not None:
            self.stop_event.set()

    def request_connect(self) -> None:
        """Try to connect now instead of after the back-off, e.g. a shot is
        starting and the scale was just woken. Safe from any thread."""
        loop, wake = self._loop, self._wake
        if loop is not None and wake is not None:
            loop.call_soon_threadsafe(wake.set)

    def disconnected(self, client: "BleakClient") -> None:
        if not self.disconnect_event:
            return

        self.disconnect_event.set()

    def callback(self, sender: int, data: bytearray) -> None:
        """Eureka Precisa weight notification: tenths of a gram in bytes 7-8
        (little endian), the sign in byte 6."""
        grams = int.from_bytes(data[7:9], "little") / 10
        if data[6]:
            grams = -grams
        now = time.perf_counter()
        self.current_weight = grams
        self.current_weight_timestamp = now
        # The scale notifies several times a second: log changes, at most once
        # a second, so the Pi Zero isn't writing an event per notification.
        if grams != self._logged_weight and now - self._logged_at >= 1.0:
            self._logged_weight, self._logged_at = grams, now
            sl = shot_logger.get()
            if sl is not None:
                sl.log_event("scale", grams=grams)

    def _log_connection(self, state: str) -> None:
        logger.info("scale %s", state)
        sl = shot_logger.get()
        if sl is not None:
            sl.log_event("scale_link", state=state)

    async def notify(self) -> None:
        import asyncio

        self.stop_event = asyncio.Event()
        self.disconnect_event = asyncio.Event()
        self._wake = asyncio.Event()
        self._loop = asyncio.get_running_loop()
        failures = 0
        while not self.stop_event.is_set():
            try:
                async with self.bleak_client as client:
                    failures = 0
                    await client.start_notify(
                        config.BLUETOOTH_NOTIFY_UUID, self.callback
                    )
                    self._log_connection("connected")
                    await self.disconnect_event.wait()
                    self._log_connection("disconnected")
                    await client.stop_notify(config.BLUETOOTH_NOTIFY_UUID)
            except Exception as e:
                failures += 1
                logger.debug("scale not reachable (%s attempts): %s", failures, e)

            # Reuse the event across iterations instead of replacing it,
            # which used to leak one Event per reconnect attempt.
            self.disconnect_event.clear()
            if failures:
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), retry_delay(failures))
                except asyncio.TimeoutError:
                    pass
