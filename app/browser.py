from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)

from .config import Settings
from .database import Database
from .models import EventType, WorkStatus


class BrowserManager:
    """
    مدير متصفح آمن باستخدام Playwright.

    يستخدم تفاعلات المتصفح الطبيعية فقط.

    لا يقوم بـ:
    - تجاوز CAPTCHA
    - تزوير البصمة الرقمية
    - تجاوز حدود المعدل
    - تجاوز المصادقة
    - تعطيل أنظمة مكافحة الروبوتات
    """

    def __init__(
        self,
        settings: Settings,
        database: Database,
    ):
        self.settings = settings
        self.database = database

        self.playwright: Playwright | None = None
        self.browser: Browser | None = None

        self.contexts: dict[int, BrowserContext] = {}
        self.pages: dict[int, Page] = {}
        self.session_ids: dict[int, int] = {}

        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if self.playwright is not None:
            return

        self.playwright = await async_playwright().start()

        self.browser = await self.playwright.chromium.launch(
            headless=self.settings.browser_headless,
        )

    async def stop(self) -> None:
        async with self._lock:
            for context in list(self.contexts.values()):
                try:
                    await context.close()
                except Exception:
                    pass

            self.contexts.clear()
            self.pages.clear()
            self.session_ids.clear()

            if self.browser:
                try:
                    await self.browser.close()
                except Exception:
                    pass

            self.browser = None

            if self.playwright:
                try:
                    await self.playwright.stop()
                except Exception:
                    pass

            self.playwright = None

    async def open_session(
        self,
        project_id: int,
        site_name: str,
        url: str,
    ) -> Page:
        if not self._is_safe_url(url):
            raise ValueError("URL غير مسموح به.")

        await self.start()

        if not self.browser:
            raise RuntimeError("Browser is not available.")

        session_dir = (
            Path(self.settings.upload_dir).parent
            / "browser_profiles"
            / str(project_id)
            / self._safe_name(site_name)
        )

        session_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        storage_file = session_dir / "storage_state.json"

        context = await self.browser.new_context(
            storage_state=(
                str(storage_file)
                if storage_file.exists()
                else None
            ),
            viewport={
                "width": 1440,
                "height": 900,
            },
        )

        context.set_default_timeout(
            self.settings.browser_timeout_ms
        )

        page = await context.new_page()

        session_id = self.database.create_browser_session(
            site_name=site_name,
            project_id=project_id,
            storage_path=str(storage_file),
        )

        self.contexts[project_id] = context
        self.pages[project_id] = page
        self.session_ids[project_id] = session_id

        try:
            await page.goto(
                url,
                wait_until="domcontentloaded",
            )

            await self._save_storage_state(project_id)

            self.database.update_browser_session(
                session_id,
                "active",
            )

            return page

        except PlaywrightTimeoutError as exc:
            self.database.update_browser_session(
                session_id,
                "connection_timeout",
            )

            self.database.add_event(
                event_type=EventType.CONNECTION_LOST.value,
                message="Browser navigation timed out.",
                project_id=project_id,
            )

            raise RuntimeError(
                "انتهت مهلة الاتصال بالموقع."
            ) from exc

        except Exception as exc:
            self.database.update_browser_session(
                session_id,
                "error",
            )

            self.database.add_event(
                event_type=EventType.ERROR.value,
                message=(
                    f"Browser session error: "
                    f"{type(exc).__name__}"
                ),
                project_id=project_id,
            )

            raise

    async def get_page(
        self,
        project_id: int,
    ) -> Page | None:
        return self.pages.get(project_id)

    async def save_session(
        self,
        project_id: int,
    ) -> None:
        await self._save_storage_state(project_id)

    async def close_session(
        self,
        project_id: int,
    ) -> None:
        context = self.contexts.pop(
            project_id,
            None,
        )

        self.pages.pop(
            project_id,
            None,
        )

        session_id = self.session_ids.pop(
            project_id,
            None,
        )

        if context:
            try:
                await context.close()
            except Exception:
                pass

        if session_id:
            self.database.update_browser_session(
                session_id,
                "closed",
            )

    async def navigate(
        self,
        project_id: int,
        url: str,
    ) -> dict[str, Any]:
        if not self._is_safe_url(url):
            raise ValueError("URL غير مسموح به.")

        page = self.pages.get(project_id)

        if not page:
            raise RuntimeError(
                "لا توجد جلسة متصفح لهذا المشروع."
            )

        try:
            response = await page.goto(
                url,
                wait_until="domcontentloaded",
            )

            await self._save_storage_state(project_id)

            return {
                "success": True,
                "status": (
                    response.status
                    if response
                    else None
                ),
                "url": page.url,
            }

        except PlaywrightTimeoutError:
            await self._pause_project(
                project_id,
                "انتهت مهلة الاتصال بالموقع.",
            )

            return {
                "success": False,
                "status": "timeout",
                "paused": True,
            }

        except Exception as exc:
            await self._pause_project(
                project_id,
                f"فشل الاتصال بالموقع: "
                f"{type(exc).__name__}",
            )

            return {
                "success": False,
                "status": "error",
                "paused": True,
            }

    async def inspect_page(
        self,
        project_id: int,
    ) -> dict[str, Any]:
        page = self.pages.get(project_id)

        if not page:
            raise RuntimeError(
                "لا توجد جلسة متصفح."
            )

        return {
            "url": page.url,
            "title": await page.title(),
        }

    async def check_session(
        self,
        project_id: int,
    ) -> dict[str, Any]:
        page = self.pages.get(project_id)

        if not page:
            return {
                "active": False,
                "reason": "no_browser_session",
            }

        try:
            await page.title()

            url = page.url.lower()

            session_expired = any(
                marker in url
                for marker in (
                    "login",
                    "signin",
                    "sign-in",
                    "authenticate",
                    "reauth",
                )
            )

            if session_expired:
                await self._mark_reauth(project_id)

                return {
                    "active": False,
                    "reason": "session_expired",
                }

            return {
                "active": True,
                "reason": "active",
                "url": page.url,
            }

        except Exception:
            await self._mark_reauth(project_id)

            return {
                "active": False,
                "reason": "session_check_failed",
            }

    async def click(
        self,
        project_id: int,
        selector: str,
    ) -> None:
        page = self.pages.get(project_id)

        if not page:
            raise RuntimeError(
                "لا توجد جلسة متصفح."
            )

        await page.locator(selector).click()

        await self._save_storage_state(project_id)

    async def fill(
        self,
        project_id: int,
        selector: str,
        value: str,
    ) -> None:
        page = self.pages.get(project_id)

        if not page:
            raise RuntimeError(
                "لا توجد جلسة متصفح."
            )

        await page.locator(selector).fill(value)

    async def press(
        self,
        project_id: int,
        selector: str,
        key: str,
    ) -> None:
        page = self.pages.get(project_id)

        if not page:
            raise RuntimeError(
                "لا توجد جلسة متصفح."
            )

        await page.locator(selector).press(key)

    async def _save_storage_state(
        self,
        project_id: int,
    ) -> None:
        context = self.contexts.get(project_id)

        session_id = self.session_ids.get(project_id)

        session = (
            self.database.get_browser_session(session_id)
            if session_id
            else None
        )

        if not context or not session:
            return

        storage_path = session.get("storage_path")

        if not storage_path:
            return

        path = Path(storage_path)

        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        await context.storage_state(
            path=str(path)
        )

    async def _pause_project(
        self,
        project_id: int,
        reason: str,
    ) -> None:
        self.database.update_project_status(
            project_id,
            WorkStatus.PAUSED.value,
        )

        self.database.execute_script(
            f"""
            UPDATE work_cards
            SET status = 'paused',
                error_message = 'connection_lost',
                updated_at = CURRENT_TIMESTAMP
            WHERE project_id = {int(project_id)}
              AND status = 'running'
            """
        )

        self.database.add_event(
            event_type=EventType.CONNECTION_LOST.value,
            message=reason,
            project_id=project_id,
        )

        session_id = self.session_ids.get(project_id)

        if session_id:
            self.database.update_browser_session(
                session_id,
                "paused",
            )

    async def _mark_reauth(
        self,
        project_id: int,
    ) -> None:
        self.database.update_project_status(
            project_id,
            WorkStatus.NEEDS_REAUTH.value,
        )

        self.database.execute_script(
            f"""
            UPDATE work_cards
            SET status = 'needs_reauth',
                updated_at = CURRENT_TIMESTAMP
            WHERE project_id = {int(project_id)}
              AND status IN ('running', 'queued')
            """
        )

        self.database.add_event(
            event_type=EventType.SESSION_EXPIRED.value,
            message=(
                "Browser session expired. "
                "Manual re-authentication required."
            ),
            project_id=project_id,
        )

        session_id = self.session_ids.get(project_id)

        if session_id:
            self.database.update_browser_session(
                session_id,
                "expired",
            )

    @staticmethod
    def _safe_name(
        value: str,
    ) -> str:
        allowed = (
            "abcdefghijklmnopqrstuvwxyz"
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            "0123456789_-"
        )

        result = "".join(
            char if char in allowed else "_"
            for char in value
        )

        return result[:80] or "site"

    @staticmethod
    def _is_safe_url(
        url: str,
    ) -> bool:
        lowered = url.lower().strip()

        return (
            lowered.startswith("https://")
            or lowered.startswith("http://localhost")
            or lowered.startswith("http://127.0.0.1")
            )
