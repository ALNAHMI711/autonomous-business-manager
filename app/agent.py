
from __future__ import annotations

import json
from typing import Any

import httpx

from .config import Settings
from .database import Database
from .models import EventType, WorkStatus, WorkflowType


SYSTEM_PROMPT = """
أنت المدير الذكي لنظام Autonomous Business Manager.

مهمتك:
1. فهم طلب المستخدم.
2. تحديد نوع سير العمل المناسب.
3. تقسيم المهمة إلى خطوات واضحة.
4. إنشاء Work Card عند الحاجة.
5. طلب موافقة المستخدم قبل أي إجراء حساس أو خارجي.
6. عدم تنفيذ أو اقتراح تجاوز CAPTCHA أو أنظمة الحماية أو حدود الاستخدام.
7. عدم طلب كلمات مرور أو مفاتيح سرية داخل المحادثة إذا كان يمكن إدارتها عبر النظام الآمن.
8. أي تداول مالي أو نشر أو شراء أو إرسال خارجي يجب أن يبقى في وضع الموافقة البشرية ما لم توجد سياسة آمنة وصريحة تسمح بغير ذلك.
9. أي كود يرسله المستخدم يجب تحليله أولاً وعدم تنفيذه مباشرة.

أنواع سير العمل:
- assistant
- api_account
- upload_design
- code_api
- dual

أعد JSON صالحاً فقط عندما يطلب منك النظام خطة منظمة.
"""


class AgentError(Exception):
    pass


class Agent:
    def __init__(
        self,
        settings: Settings,
        database: Database,
    ):
        self.settings = settings
        self.database = database

    async def chat(
        self,
        message: str,
        project_id: int | None = None,
        workflow_type: str = WorkflowType.ASSISTANT.value,
    ) -> dict[str, Any]:

        if not message.strip():
            raise AgentError("الرسالة فارغة.")

        self.database.add_message(
            role="user",
            content=message,
            project_id=project_id,
        )

        if not self.settings.openai_api_key:
            reply = self._local_fallback(
                message,
                workflow_type,
            )

            self.database.add_message(
                role="assistant",
                content=reply,
                project_id=project_id,
            )

            return {
                "reply": reply,
                "source": "local_fallback",
                "work_card": None,
            }

        try:
            reply = await self._openai_chat(
                message=message,
                workflow_type=workflow_type,
            )

            self.database.add_message(
                role="assistant",
                content=reply,
                project_id=project_id,
            )

            return {
                "reply": reply,
                "source": "openai",
                "work_card": None,
            }

        except Exception as exc:
            self.database.add_event(
                event_type=EventType.ERROR.value,
                message=f"OpenAI request failed: {type(exc).__name__}",
                project_id=project_id,
            )

            reply = self._local_fallback(
                message,
                workflow_type,
            )

            self.database.add_message(
                role="assistant",
                content=reply,
                project_id=project_id,
            )

            return {
                "reply": reply,
                "source": "local_fallback_after_error",
                "work_card": None,
            }

    async def _openai_chat(
        self,
        message: str,
        workflow_type: str,
    ) -> str:

        payload = {
            "model": self.settings.openai_model,
            "messages": [
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "system",
                    "content": (
                        f"Current workflow type: {workflow_type}"
                    ),
                },
                {
                    "role": "user",
                    "content": message,
                },
            ],
        }

        headers = {
            "Authorization": (
                f"Bearer {self.settings.openai_api_key}"
            ),
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(
            timeout=60,
        ) as client:

            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload,
            )

            response.raise_for_status()

            data = response.json()

        try:
            return data["choices"][0]["message"]["content"]

        except (KeyError, IndexError, TypeError) as exc:
            raise AgentError(
                "Unexpected OpenAI response."
            ) from exc

    def create_work_card(
        self,
        title: str,
        workflow_type: str,
        description: str,
        project_id: int | None = None,
        next_step: str | None = None,
        requires_approval: bool = True,
    ) -> int:

        card_id = self.database.create_work_card(
            title=title,
            workflow_type=workflow_type,
            description=description,
            project_id=project_id,
            status=(
                WorkStatus.NEEDS_APPROVAL.value
                if requires_approval
                else WorkStatus.QUEUED.value
            ),
            next_step=next_step,
            requires_approval=requires_approval,
        )

        self.database.add_event(
            event_type=(
                EventType.APPROVAL_REQUIRED.value
                if requires_approval
                else EventType.INFO.value
            ),
            message=f"Work Card created: {title}",
            project_id=project_id,
            metadata_json=json.dumps(
                {"work_card_id": card_id},
                ensure_ascii=False,
            ),
        )

        return card_id

    def _local_fallback(
        self,
        message: str,
        workflow_type: str,
    ) -> str:

        workflow_names = {
            "assistant": "المساعد العام",
            "api_account": "API والحساب",
            "upload_design": "رفع التصميم",
            "code_api": "الكود وAPI",
            "dual": "السير المزدوج",
        }

        workflow_name = workflow_names.get(
            workflow_type,
            workflow_type,
        )

        return (
            f"تم استلام طلبك ضمن وضع «{workflow_name}».\n\n"
            "محرك الذكاء غير متصل حالياً بمفتاح API صالح، "
            "لذلك لن أقوم بتنفيذ أي إجراء خارجي تلقائياً.\n\n"
            f"الطلب المستلم:\n{message}\n\n"
            "بعد إعداد OPENAI_API_KEY سيقوم النظام بتحليل الطلب "
            "وتحويل المهام القابلة للتنفيذ إلى Work Cards "
            "مع طلب الموافقة قبل الإجراءات الحساسة."
            )
