from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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


class BrowserManager:
    """
    مدير المتصفح باستخدام Playwright.

    الحدود الأمنية:
    - لا يتجاوز CAPTCHA.
    - لا يتجاوز أنظمة مكافحة الروبوتات.
    - لا يزوّر بصمة المتصفح.
    - لا يتجاوز حدود المعدل أو أنظمة الدخول.
    - لا ينفذ JavaScript عشوائياً من المستخدم.
    - يستخدم جلسات متصفح مستقلة لكل مشروع/موقع.
    """

    SESSION_EXPIRED_MARKERS = (
        "/login",
        "/signin",
        "/sign-in",
        "/auth/login",
        "/authenticate",
        "session-expired",
        "reauth",
    )

    def __init__(self, settings: Settings, database: Database) -> None:
        self.settings = settings
        self.db = database

        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._contexts: dict[int, BrowserContext] = {}
        self._pages: dict[int, Page] = {}

    async def initialize(self) -> None:
        if self._playwright is not None:
            return

        self._playwright = await async_playwright().start()

        self._browser = await self._playwright.chromium.launch(
            headless=self.settings.browser_headless
        )

    async def shutdown(self) -> None:
        for project_id in list(self._contexts):
            try:
                await self.close_project(project_id)
            except Exception:
                pass

        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                pass

            self._browser = None

        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:
                pass

            self._playwright = None

    def _safe_site_name(self, site: str) -> str:
        parsed = urlparse(site)

        hostname = parsed.hostname or "unknown-site"

        hostname = re.sub(
            r"[^a-zA-Z0-9._-]",
            "_",
            hostname,
        )

        return hostname[:100]

    def _profile_path(
        self,
        project_id: int,
        site: str,
    ) -> Path:
        safe_site = self._safe_site_name(site)

        path = (
            self.settings.browser_profile_directory
            / str(project_id)
            / safe_site
        )

        path.mkdir(
            parents=True,
            exist_ok=True,
        )

        return path

    def _validate_url(self, url: str) -> str:
        parsed = urlparse(url)

        if parsed.scheme == "https":
            return url

        if (
            parsed.scheme == "http"
            and parsed.hostname in {
                "127.0.0.1",
                "localhost",
            }
        ):
            return url

        raise ValueError(
            "لأسباب أمنية يسمح النظام بروابط HTTPS فقط، "
            "أو HTTP للمضيف المحلي."
        )

    async def open_project(
        self,
        project_id: int,
        site: str,
    ) -> dict[str, Any]:
        await self.initialize()

        if self._browser is None:
            raise RuntimeError(
                "المتصفح غير متاح."
            )

        site = self._validate_url(site)

        existing = self._contexts.get(project_id)

        if existing is not None:
            pages = existing.pages

            if pages:
                page = pages[0]
            else:
                page = await existing.new_page()

            self._pages[project_id] = page

            return {
                "project_id": project_id,
                "url": page.url,
                "status": "connected",
                "session_expired": self.is_session_expired(
                    page.url
                ),
            }

        profile_path = self._profile_path(
            project_id,
            site,
        )

        storage_state = (
            profile_path / "storage_state.json"
        )

        context_kwargs: dict[str, Any] = {
            "viewport": {
                "width": 1440,
                "height": 900,
            },
            "locale": "ar-SA",
        }

        if storage_state.exists():
            context_kwargs["storage_state"] = str(
                storage_state
            )

        context = await self._browser.new_context(
            **context_kwargs
        )

        page = await context.new_page()

        self._contexts[project_id] = context
        self._pages[project_id] = page

        try:
            await page.goto(
                site,
                wait_until="domcontentloaded",
                timeout=self.settings.browser_timeout,
            )
        except PlaywrightTimeoutError:
            pass

        await self._save_storage_state(
            project_id,
            site,
        )

        return {
            "project_id": project_id,
            "url": page.url,
            "status": "connected",
            "session_expired": self.is_session_expired(
                page.url
            ),
        }

    async def navigate(
        self,
        project_id: int,
        url: str,
    ) -> dict[str, Any]:
        url = self._validate_url(url)

        page = self._pages.get(project_id)

        if page is None:
            raise ValueError(
                "لا توجد جلسة متصفح للمشروع. "
                "افتح المشروع أولاً."
            )

        try:
            await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=self.settings.browser_timeout,
            )
        except PlaywrightTimeoutError:
            pass

        parsed = urlparse(url)

        site = (
            f"{parsed.scheme}://{parsed.netloc}"
        )

        await self._save_storage_state(
            project_id,
            site,
        )

        expired = self.is_session_expired(
            page.url
        )

        return {
            "project_id": project_id,
            "url": page.url,
            "session_expired": expired,
            "status": (
                "needs_reauth"
                if expired
                else "connected"
            ),
        }

    async def get_status(
        self,
        project_id: int,
    ) -> dict[str, Any]:
        page = self._pages.get(project_id)

        if page is None:
            return {
                "project_id": project_id,
                "status": "closed",
                "url": None,
                "session_expired": False,
            }

        try:
            url = page.url
        except Exception:
            url = None

        expired = self.is_session_expired(
            url or ""
        )

        return {
            "project_id": project_id,
            "status": (
                "needs_reauth"
                if expired
                else "connected"
            ),
            "url": url,
            "session_expired": expired,
        }

    async def close_project(
        self,
        project_id: int,
    ) -> None:
        context = self._contexts.pop(
            project_id,
            None,
        )

        self._pages.pop(
            project_id,
            None,
        )

        if context is None:
            return

        try:
            await context.close()
        except Exception:
            pass

    async def click(
        self,
        project_id: int,
        selector: str,
    ) -> dict[str, Any]:
        page = self._get_page(project_id)

        await page.locator(selector).click(
            timeout=self.settings.browser_timeout
        )

        try:
            await page.wait_for_load_state(
                "domcontentloaded",
                timeout=self.settings.browser_timeout,
            )
        except PlaywrightTimeoutError:
            pass

        expired = self.is_session_expired(
            page.url
        )

        return {
            "project_id": project_id,
            "url": page.url,
            "session_expired": expired,
            "status": (
                "needs_reauth"
                if expired
                else "ok"
            ),
        }

    async def fill(
        self,
        project_id: int,
        selector: str,
        value: str,
    ) -> dict[str, Any]:
        page = self._get_page(project_id)

        await page.locator(selector).fill(
            value,
            timeout=self.settings.browser_timeout,
        )

        return {
            "project_id": project_id,
            "status": "ok",
        }

    async def get_text(
        self,
        project_id: int,
        selector: str,
    ) -> str:
        page = self._get_page(project_id)

        return await page.locator(
            selector
        ).inner_text(
            timeout=self.settings.browser_timeout
        )

    async def screenshot(
        self,
        project_id: int,
        path: str,
    ) -> str:
        page = self._get_page(project_id)

        output = Path(path)

        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        await page.screenshot(
            path=str(output),
            full_page=True,
        )

        return str(output)

    async def inspect_page(
        self,
        project_id: int,
    ) -> dict[str, Any]:
        page = self._get_page(project_id)

        title = await page.title()
        url = page.url

        text = await page.locator(
            "body"
        ).inner_text(
            timeout=self.settings.browser_timeout
        )

        links = await page.locator(
            "a"
        ).all()

        link_data: list[dict[str, str]] = []

        for link in links[:100]:
            try:
                text_value = (
                    await link.inner_text()
                ).strip()
            except Exception:
                text_value = ""

            try:
                href = await link.get_attribute(
                    "href"
                )
            except Exception:
                href = None

            if text_value or href:
                link_data.append(
                    {
                        "text": text_value[:300],
                        "href": href or "",
                    }
                )

        return {
            "project_id": project_id,
            "url": url,
            "title": title,
            "text": text[:20000],
            "links": link_data,
            "session_expired": (
                self.is_session_expired(url)
            ),
        }

    async def _save_storage_state(
        self,
        project_id: int,
        site: str,
    ) -> None:
        context = self._contexts.get(
            project_id
        )

        if context is None:
            return

        profile_path = self._profile_path(
            project_id,
            site,
        )

        storage_state = (
            profile_path / "storage_state.json"
        )

        try:
            await context.storage_state(
                path=str(storage_state)
            )
        except Exception:
            pass

    def _get_page(
        self,
        project_id: int,
    ) -> Page:
        page = self._pages.get(project_id)

        if page is None:
            raise ValueError(
                "لا توجد صفحة متصفح نشطة لهذا المشروع."
            )

        return page

    @classmethod
    def is_session_expired(
        cls,
        url: str,
    ) -> bool:
        if not url:
            return False

        normalized = url.lower()

        for marker in cls.SESSION_EXPIRED_MARKERS:
            if marker in normalized:
                return True

        return False

    async def detect_session_expiry(
        self,
        project_id: int,
    ) -> bool:
        page = self._pages.get(project_id)

        if page is None:
            return False

        return self.is_session_expired(
            page.url
        )

    async def save_session(
        self,
        project_id: int,
        site: str,
    ) -> None:
        await self._save_storage_state(
            project_id,
            site,
        )

    def active_projects(self) -> list[int]:
        return list(
            self._contexts.keys()
            )
