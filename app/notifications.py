from __future__ import annotations

import logging
from typing import Optional

import httpx


logger = logging.getLogger(__name__)


class NotificationManager:
    """
    Handles Telegram and WhatsApp Business notifications.

    Supported notification meanings:
        ن؟              -> connection offline / stopped
        >س✓<            -> connection restored / resumed
        >م? [project]   -> approval/question required
        <|> [project]   -> session expired / re-authentication required

    The manager never logs access tokens or other sensitive credentials.
    """

    def __init__(self, settings) -> None:
        self.settings = settings

    # ------------------------------------------------------------------
    # Configuration status
    # ------------------------------------------------------------------

    def telegram_configured(self) -> bool:
        return bool(
            getattr(self.settings, "telegram_bot_token", None)
            and getattr(self.settings, "telegram_chat_id", None)
        )

    def whatsapp_configured(self) -> bool:
        return bool(
            getattr(self.settings, "whatsapp_api_url", None)
            and getattr(self.settings, "whatsapp_access_token", None)
            and getattr(self.settings, "whatsapp_phone_number_id", None)
            and getattr(self.settings, "whatsapp_recipient", None)
        )

    # ------------------------------------------------------------------
    # Public notification methods
    # ------------------------------------------------------------------

    async def send_offline(self) -> None:
        await self.send(
            "ن؟\n"
            "تم إيقاف الأعمال مؤقتًا بسبب انقطاع الاتصال بالإنترنت."
        )

    async def send_restored(self) -> None:
        await self.send(
            ">س✓<\n"
            "تمت استعادة الاتصال. سيتم استئناف الأعمال الموقوفة."
        )

    async def send_approval_required(
        self,
        project_number: str | int,
        message: Optional[str] = None,
    ) -> None:
        text = f">م? {project_number}"

        if message:
            text += f"\n{message}"

        text += "\n\nالمطلوب: موافقة أو رفض العملية من لوحة التحكم."

        await self.send(text)

    async def send_session_expired(
        self,
        project_number: str | int,
        message: Optional[str] = None,
    ) -> None:
        text = f"<|> {project_number}"

        if message:
            text += f"\n{message}"

        text += (
            "\n\nانتهت جلسة الموقع. "
            "يرجى تسجيل الدخول من خلال المتصفح لإعادة المصادقة."
        )

        await self.send(text)

    async def send_project_message(
        self,
        project_number: str | int,
        message: str,
    ) -> None:
        await self.send(
            f"[مشروع {project_number}]\n{message}"
        )

    async def send(self, message: str) -> dict:
        """
        Send a notification through all configured channels.

        Returns a small delivery report instead of raising channel-specific
        errors to the main application.
        """

        results = {
            "telegram": False,
            "whatsapp": False,
        }

        if not message:
            return results

        if self.telegram_configured():
            results["telegram"] = await self._send_telegram(message)

        if self.whatsapp_configured():
            results["whatsapp"] = await self._send_whatsapp(message)

        return results

    # ------------------------------------------------------------------
    # Telegram
    # ------------------------------------------------------------------

    async def _send_telegram(
        self,
        message: str,
    ) -> bool:
        token = getattr(
            self.settings,
            "telegram_bot_token",
            None,
        )

        chat_id = getattr(
            self.settings,
            "telegram_chat_id",
            None,
        )

        if not token or not chat_id:
            return False

        url = (
            f"https://api.telegram.org/bot"
            f"{token}/sendMessage"
        )

        payload = {
            "chat_id": chat_id,
            "text": message,
        }

        try:
            timeout = httpx.Timeout(
                connect=10.0,
                read=15.0,
                write=15.0,
                pool=10.0,
            )

            async with httpx.AsyncClient(
                timeout=timeout
            ) as client:
                response = await client.post(
                    url,
                    json=payload,
                )

            if 200 <= response.status_code < 300:
                return True

            logger.warning(
                "Telegram notification failed with status %s.",
                response.status_code,
            )

        except (
            httpx.HTTPError,
            OSError,
        ):
            logger.exception(
                "Telegram notification request failed."
            )

        return False

    # ------------------------------------------------------------------
    # WhatsApp Business API
    # ------------------------------------------------------------------

    async def _send_whatsapp(
        self,
        message: str,
    ) -> bool:
        api_url = getattr(
            self.settings,
            "whatsapp_api_url",
            None,
        )

        access_token = getattr(
            self.settings,
            "whatsapp_access_token",
            None,
        )

        phone_number_id = getattr(
            self.settings,
            "whatsapp_phone_number_id",
            None,
        )

        recipient = getattr(
            self.settings,
            "whatsapp_recipient",
            None,
        )

        if not all(
            [
                api_url,
                access_token,
                phone_number_id,
                recipient,
            ]
        ):
            return False

        url = api_url.rstrip("/")

        # Allow either:
        # https://graph.facebook.com/vXX.X
        # or a complete endpoint supplied in configuration.
        if not url.endswith(phone_number_id):
            url = (
                f"{url}/"
                f"{phone_number_id}/messages"
            )

        payload = {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": message,
            },
        }

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        try:
            timeout = httpx.Timeout(
                connect=10.0,
                read=20.0,
                write=20.0,
                pool=10.0,
            )

            async with httpx.AsyncClient(
                timeout=timeout
            ) as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers=headers,
                )

            if 200 <= response.status_code < 300:
                return True

            logger.warning(
                "WhatsApp notification failed with status %s.",
                response.status_code,
            )

        except (
            httpx.HTTPError,
            OSError,
        ):
            logger.exception(
                "WhatsApp notification request failed."
            )

        return False
