from __future__ import annotations

from typing import Any

import httpx

from .config import Settings
from .database import Database
from .models import NotificationCode


class NotificationManager:
    def __init__(
        self,
        settings: Settings,
        database: Database,
    ):
        self.settings = settings
        self.database = database

    async def send(
        self,
        message: str,
    ) -> dict[str, Any]:

        results: dict[str, Any] = {
            "telegram": False,
            "whatsapp": False,
        }

        if (
            self.settings.telegram_bot_token
            and self.settings.telegram_chat_id
        ):
            results["telegram"] = (
                await self._send_telegram(
                    message
                )
            )

        if self.settings.whatsapp_enabled:
            results["whatsapp"] = (
                await self._send_whatsapp(
                    message
                )
            )

        return results

    async def offline(self) -> dict[str, Any]:
        return await self.send(
            NotificationCode.OFFLINE.value
        )

    async def restored(self) -> dict[str, Any]:
        return await self.send(
            NotificationCode.RESTORED.value
        )

    async def approval_required(
        self,
        project_number: int,
    ) -> dict[str, Any]:

        return await self.send(
            f"{NotificationCode.QUESTION.value} "
            f"[{project_number}]"
        )

    async def reauth_required(
        self,
        project_number: int,
    ) -> dict[str, Any]:

        return await self.send(
            f"{NotificationCode.REAUTH.value} "
            f"[{project_number}]"
        )

    async def _send_telegram(
        self,
        message: str,
    ) -> bool:

        url = (
            "https://api.telegram.org/bot"
            f"{self.settings.telegram_bot_token}"
            "/sendMessage"
        )

        payload = {
            "chat_id": self.settings.telegram_chat_id,
            "text": message,
        }

        try:
            async with httpx.AsyncClient(
                timeout=15,
            ) as client:

                response = await client.post(
                    url,
                    json=payload,
                )

                response.raise_for_status()

            return True

        except Exception as exc:
            self.database.add_event(
                event_type="error",
                message=(
                    "Telegram notification failed: "
                    f"{type(exc).__name__}"
                ),
            )

            return False

    async def _send_whatsapp(
        self,
        message: str,
    ) -> bool:

        if not (
            self.settings.whatsapp_api_url
            and self.settings.whatsapp_access_token
            and self.settings.whatsapp_phone_number_id
            and self.settings.whatsapp_recipient
        ):
            return False

        url = self.settings.whatsapp_api_url

        headers = {
            "Authorization": (
                "Bearer "
                f"{self.settings.whatsapp_access_token}"
            ),
            "Content-Type": "application/json",
        }

        payload = {
            "messaging_product": "whatsapp",
            "to": self.settings.whatsapp_recipient,
            "type": "text",
            "text": {
                "body": message,
            },
        }

        try:
            async with httpx.AsyncClient(
                timeout=15,
            ) as client:

                response = await client.post(
                    url,
                    headers=headers,
                    json=payload,
                )

                response.raise_for_status()

            return True

        except Exception as exc:
            self.database.add_event(
                event_type="error",
                message=(
                    "WhatsApp notification failed: "
                    f"{type(exc).__name__}"
                ),
            )

            return False
