import logging
import threading
import time
from typing import TYPE_CHECKING, Optional

from espyresso import config, shot_logger

if TYPE_CHECKING:
    from asyncio import Event

    from bleak.backends.bluezdbus.client import BleakClientBlueZDBus as BleakClient

logger = logging.getLogger(__name__)


class BluetoothScale:
    current_weight_timestamp: float = 0
    current_weight: int = 0
    bleak_client: "BleakClient" = None
    stop_event: Optional["Event"] = None
    disconnect_event: Optional["Event"] = None
    _thread: Optional[threading.Thread] = None

    def get_scale_weight(self) -> float:
        if time.perf_counter() - self.current_weight_timestamp > 5:
            return 0
        return self.current_weight / 10

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
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
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
            config.BLUETOOTH_SCALE_ADDRESS, disconnected_callback=self.disconnected
        )
        asyncio.run(self.notify())

    def stop(self) -> None:
        if self.stop_event is not None:
            self.stop_event.set()

    def disconnected(self, client: "BleakClient") -> None:
        if not self.disconnect_event:
            return

        self.disconnect_event.set()

    def callback(self, sender: int, data: bytearray) -> None:
        v_int = int.from_bytes(data[7:9], "little")
        self.current_weight = v_int
        self.current_weight_timestamp = time.perf_counter()
        sl = shot_logger.get()
        if sl is not None:
            sl.log_event("scale", grams=v_int / 10)

    async def notify(self) -> None:
        import asyncio

        self.stop_event = asyncio.Event()
        self.disconnect_event = asyncio.Event()
        while not self.stop_event.is_set():
            try:
                async with self.bleak_client as client:
                    await client.start_notify(
                        config.BLUETOOTH_NOTIFY_UUID, self.callback
                    )
                    await self.disconnect_event.wait()
                    await client.stop_notify(config.BLUETOOTH_NOTIFY_UUID)
            except Exception as e:
                logger.debug("start_notify failed: %s", e)
                # Back off before retrying — without this, a missing
                # scale produced a tight reconnect loop that allocated
                # async resources on every iteration.
                await asyncio.sleep(5)

            # Reuse the event across iterations instead of replacing it,
            # which used to leak one Event per reconnect attempt.
            self.disconnect_event.clear()
