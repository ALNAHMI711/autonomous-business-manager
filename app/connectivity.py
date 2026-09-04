from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import httpx

from .database import Database
from .models import EventType, WorkStatus


class ConnectivityMonitor:
    def __init__(
        self,
        database: Database,
        check_url: str = "https://www.google.com/generate_204",
        interval_seconds: int = 15,
    ):
        self.database = database
        self.check_url = check_url
        self.interval_seconds = interval_seconds

        self._online = True
        self._running = False

        self._on_offline: Callable[
            [], Awaitable[None]
        ] | None = None

        self._on_online: Callable[
            [], Awaitable[None]
        ] | None = None

    @property
    def online(self) -> bool:
        return self._online

    def set_callbacks(
        self,
        on_offline: Callable[
            [], Awaitable[None]
        ] | None = None,
        on_online: Callable[
            [], Awaitable[None]
        ] | None = None,
    ) -> None:
        self._on_offline = on_offline
        self._on_online = on_online

    async def check(self) -> bool:
        try:
            async with httpx.AsyncClient(
                timeout=8,
            ) as client:
                response = await client.get(
                    self.check_url
                )

            is_online = response.status_code < 500

        except (
            httpx.HTTPError,
            OSError,
        ):
            is_online = False

        previous = self._online
        self._online = is_online

        if previous and not is_online:
            self.database.add_event(
                event_type=EventType.CONNECTION_LOST.value,
                message="Internet connection lost.",
            )

            self.database.execute_script(
                """
                UPDATE work_cards
                SET status = 'paused',
                    updated_at = CURRENT_TIMESTAMP
                WHERE status = 'running'
                """
            )

            if self._on_offline:
                await self._on_offline()

        elif not previous and is_online:
            self.database.add_event(
                event_type=EventType.CONNECTION_RESTORED.value,
                message="Internet connection restored.",
            )

            if self._on_online:
                await self._on_online()

        return is_online

    async def run(self) -> None:
        self._running = True

        while self._running:
            try:
                await self.check()
            except Exception as exc:
                self.database.add_event(
                    event_type=EventType.ERROR.value,
                    message=(
                        "Connectivity monitor error: "
                        f"{type(exc).__name__}"
                    ),
                )

            await asyncio.sleep(
                self.interval_seconds
            )

    def stop(self) -> None:
        self._running = False
