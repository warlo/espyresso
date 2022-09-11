from typing import TYPE_CHECKING, Optional

from espyresso import config

if TYPE_CHECKING:
    from asyncio import Event

    from bleak.backends.bluezdbus.client import BleakClientBlueZDBus as BleakClient


class BluetoothScale:
    current_weight: int = 0
    bleak_client: "BleakClient" = None
    stop_event: Optional["Event"] = None
    disconnect_event: Optional["Event"] = None

    def get_scale_weight(self) -> int:
        return self.current_weight

    def start(self) -> None:
        import asyncio

        from bleak.backends.bluezdbus.client import BleakClientBlueZDBus as BleakClient

        self.bleak_client = BleakClient(
            config.BLUETOOTH_SCALE_ADDRESS, disconnected_callback=self.disconnected
        )
        asyncio.run(self.notify())

    def stop(self) -> None:
        import asyncio

        asyncio.run(self.stop_notify())

    def disconnected(self, client: "BleakClient") -> None:
        if not self.disconnect_event:
            return

        self.disconnect_event.set()

    def callback(self, sender: int, data: bytearray) -> None:
        v_int = int.from_bytes(data[7:9], "little")
        # print("Callback", list(data), v_int)
        self.current_weight = v_int

    async def notify(self) -> None:
        import asyncio

        self.disconnect_event = asyncio.Event()
        self.stop_event = asyncio.Event()
        while not self.stop_event.is_set():
            if not self.disconnect_event.is_set():
                print("Already connected")
                await asyncio.sleep(5)
                continue

            try:
                async with self.bleak_client as client:
                    await client.start_notify(
                        config.BLUETOOTH_NOTIFY_UUID, self.callback
                    )
                    await self.disconnect_event.wait()
            except Exception as e:
                print("start_notify exception:", e)
                pass

            self.disconnect_event = asyncio.Event()

    async def stop_notify(self) -> None:

        print("Stop")
        if self.stop_event is not None:
            self.stop_event.set()

        try:
            async with self.bleak_client as client:
                await client.stop_notify(config.BLUETOOTH_NOTIFY_UUID)
        except Exception:
            pass
