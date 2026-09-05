from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Optional

import httpx


logger = logging.getLogger(__name__)


Callback = Callable[[], Awaitable[None]]


class ConnectivityMonitor:
    """
    Monitors internet connectivity and notifies the application when the
    connection goes offline or comes back online.

    The monitor does not perform any browser automation itself. It only
    reports connectivity changes so the task manager can pause/resume work.
    """

    def __init__(
        self,
        check_url: str,
        interval: int = 15,
    ) -> None:
        self.check_url = check_url
        self.interval = max(3, int(interval))

        self._online = True
        self._running = False
        self._task: Optional[asyncio.Task] = None

        self._offline_callbacks: list[Callback] = []
        self._online_callbacks: list[Callback] = []

    @property
    def is_online(self) -> bool:
        return self._online

    @property
    def is_running(self) -> bool:
        return self._running

    def on_offline(self, callback: Callback) -> None:
        if callback not in self._offline_callbacks:
            self._offline_callbacks.append(callback)

    def on_online(self, callback: Callback) -> None:
        if callback not in self._online_callbacks:
            self._online_callbacks.append(callback)

    async def check_now(self) -> bool:
        """
        Perform one connectivity check.

        Returns:
            True when the internet endpoint is reachable, otherwise False.
        """
        try:
            timeout = httpx.Timeout(
                connect=5.0,
                read=5.0,
                write=5.0,
                pool=5.0,
            )

            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=True,
            ) as client:
                response = await client.get(
                    self.check_url,
                    headers={
                        "User-Agent": "AutonomousBusinessManager/1.0",
                        "Cache-Control": "no-cache",
                    },
                )

            # Any normal HTTP response means the network path is alive.
            return 100 <= response.status_code < 600

        except (
            httpx.HTTPError,
            asyncio.TimeoutError,
            OSError,
        ) as exc:
            logger.debug(
                "Connectivity check failed: %s",
                exc,
            )
            return False

    async def _run_callbacks(
        self,
        callbacks: list[Callback],
    ) -> None:
        for callback in list(callbacks):
            try:
                await callback()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Connectivity callback failed."
                )

    async def _check_once(self) -> None:
        current_online = await self.check_now()

        # Online -> Offline
        if self._online and not current_online:
            self._online = False

            logger.warning(
                "Internet connection lost."
            )

            await self._run_callbacks(
                self._offline_callbacks
            )

        # Offline -> Online
        elif not self._online and current_online:
            self._online = True

            logger.info(
                "Internet connection restored."
            )

            await self._run_callbacks(
                self._online_callbacks
            )

    async def _monitor_loop(self) -> None:
        while self._running:
            try:
                await self._check_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Unexpected error in connectivity monitor."
                )

            try:
                await asyncio.sleep(self.interval)
            except asyncio.CancelledError:
                raise

    async def start(self) -> None:
        """
        Start the background connectivity monitor.
        """
        if self._running:
            return

        self._running = True

        # Establish the initial state before starting the background loop.
        initial_status = await self.check_now()
        self._online = initial_status

        logger.info(
            "Connectivity monitor started. Online=%s",
            self._online,
        )

        self._task = asyncio.create_task(
            self._monitor_loop(),
            name="connectivity-monitor",
        )

    async def stop(self) -> None:
        """
        Stop the background connectivity monitor cleanly.
        """
        if not self._running and self._task is None:
            return

        self._running = False

        task = self._task
        self._task = None

        if task is not None:
            task.cancel()

            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception(
                    "Error while stopping connectivity monitor."
                )

        logger.info(
            "Connectivity monitor stopped."
        )

    async def wait_until_online(
        self,
        timeout: Optional[float] = None,
    ) -> bool:
        """
        Wait until connectivity is restored.

        This is useful for future task execution logic that wants to wait
        rather than immediately fail when the network is temporarily down.
        """

        if self._online:
            return True

        async def _wait() -> bool:
            while self._running and not self._online:
                await asyncio.sleep(1)

            return self._online

        try:
            if timeout is None:
                return await _wait()

            return await asyncio.wait_for(
                _wait(),
                timeout=timeout,
            )

        except asyncio.TimeoutError:
            return False
