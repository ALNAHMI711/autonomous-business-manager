from __future__ import annotations

import json
import logging
from typing import Any, Optional

import httpx


logger = logging.getLogger(__name__)


class Agent:
    """
    العقل المنطقي للنظام.

    مسؤول عن:
    - فهم طلب المستخدم.
    - حفظ سياق المحادثة.
    - اقتراح خطة العمل.
    - إنشاء بطاقات العمل.
    - استخدام OpenAI بشكل اختياري.
    - العمل محلياً عند عدم توفر OpenAI.

    مهم:
    هذا الكلاس لا ينفذ أوامر Shell أو Python أو JavaScript
    قادمة من المستخدم.
    """

    SYSTEM_PROMPT = """
أنت المساعد الذكي لنظام Autonomous Business Manager.

مهمتك:
1. فهم طلب المستخدم باللغة العربية أو الإنجليزية.
2. تقسيم الأعمال المعقدة إلى خطوات واضحة.
3. اقتراح بطاقات عمل منظمة.
4. استخدام العمليات المسموح بها فقط.
5. عدم تنفيذ كود Python أو Shell أو JavaScript يقدمه المستخدم مباشرة.
6. عدم تجاوز CAPTCHA أو أنظمة الحماية.
7. عدم محاولة سرقة أو استخراج بيانات اعتماد.
8. عدم التحايل على حدود الاستخدام.
9. العمليات الحساسة تحتاج موافقة المستخدم.
10. عند وجود غموض أو مخاطرة، اطلب موافقة أو وضح المطلوب.

عمليات المتصفح المنظمة المسموحة:
- browser_open
- browser_navigate
- browser_click
- browser_fill
- browser_text
- wait

إذا احتاجت المهمة عملية خارج العمليات السابقة،
لا تنفذها مباشرة، بل وضح أنها تحتاج تكاملاً مخصصاً وآمناً.
"""

    ALLOWED_OPERATIONS = {
        "browser_open",
        "browser_navigate",
        "browser_click",
        "browser_fill",
        "browser_text",
        "wait",
    }

    def __init__(
        self,
        database,
        settings,
    ) -> None:
        self.db = database
        self.settings = settings

    # =========================================================
    # Helpers
    # =========================================================

    @staticmethod
    def _safe_json_loads(
        value: Any,
        default: Any,
    ) -> Any:
        if isinstance(value, (dict, list)):
            return value

        if not isinstance(value, str):
            return default

        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return default

    # =========================================================
    # Local response
    # =========================================================

    def _local_response(
        self,
        message: str,
    ) -> str:
        """
        استجابة محلية عند عدم توفر OpenAI.

        لا تحاول تنفيذ الطلب مباشرة.
        """

        text = message.strip()

        if not text:
            return (
                "ارسل طلبك وسأساعدك في تحويله إلى خطوات "
                "ومهام منظمة."
            )

        lowered = text.lower()

        if any(
            keyword in lowered
            for keyword in (
                "password",
                "كلمة المرور",
                "كلمه المرور",
                "api key",
                "مفتاح api",
                "secret",
            )
        ):
            return (
                "يمكنني مساعدتك في تنظيم بيانات الاعتماد "
                "وحفظها عبر لوحة الأسرار المشفرة، لكن لا ترسل "
                "المفاتيح السرية داخل المحادثة أو تحفظها في GitHub."
            )

        if any(
            keyword in lowered
            for keyword in (
                "browser",
                "playwright",
                "متصفح",
                "موقع",
            )
        ):
            return (
                "أستطيع تحويل طلب المتصفح إلى عمليات منظمة "
                "مثل فتح الموقع والتنقل والضغط وملء الحقول "
                "وقراءة النص، مع بقاء العمليات الحساسة تحت "
                "موافقة المستخدم."
            )

        return (
            "تم استلام طلبك. وضع الذكاء الاصطناعي الخارجي "
            "غير مفعل حالياً، لذلك أستطيع العمل بالوضع المحلي "
            "وتحويل الطلب إلى خطة أو بطاقة عمل منظمة."
        )

    # =========================================================
    # OpenAI
    # =========================================================

    async def _call_openai(
        self,
        messages: list[dict[str, str]],
    ) -> Optional[str]:
        api_key = getattr(
            self.settings,
            "openai_api_key",
            None,
        )

        if not api_key:
            return None

        model = getattr(
            self.settings,
            "openai_model",
            "gpt-5.6",
        )

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.2,
        }

        try:
            async with httpx.AsyncClient(
                timeout=60.0
            ) as client:

                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers=headers,
                    json=payload,
                )

                response.raise_for_status()

                data = response.json()

                choices = data.get(
                    "choices",
                    [],
                )

                if not choices:
                    return None

                message = choices[0].get(
                    "message",
                    {},
                )

                content = message.get(
                    "content"
                )

                if not content:
                    return None

                return str(content).strip()

        except Exception:
            logger.exception(
                "OpenAI request failed."
            )
            return None

    # =========================================================
    # Chat
    # =========================================================

    async def chat(
        self,
        message: str,
        project_id: Optional[int] = None,
    ) -> dict[str, Any]:

        user_message = message.strip()

        if not user_message:
            return {
                "ok": False,
                "response": "الرسالة فارغة.",
                "source": "local",
            }

        history: list[dict[str, str]] = []

        try:
            rows = self.db.list_chat_messages(
                project_id=project_id,
                limit=30,
            )

            for row in rows:
                role = str(
                    row.get(
                        "role",
                        "user",
                    )
                )

                content = str(
                    row.get(
                        "content",
                        "",
                    )
                )

                if role in {
                    "system",
                    "user",
                    "assistant",
                } and content:
                    history.append(
                        {
                            "role": role,
                            "content": content,
                        }
                    )

        except Exception:
            logger.exception(
                "Unable to load chat history."
            )

        try:
            self.db.create_chat_message(
                project_id=project_id,
                role="user",
                content=user_message,
            )
        except Exception:
            logger.exception(
                "Unable to save user message."
            )

        messages = [
            {
                "role": "system",
                "content": self.SYSTEM_PROMPT,
            }
        ]

        messages.extend(history)

        messages.append(
            {
                "role": "user",
                "content": user_message,
            }
        )

        response = await self._call_openai(
            messages
        )

        source = "openai"

        if not response:
            response = self._local_response(
                user_message
            )
            source = "local"

        try:
            self.db.create_chat_message(
                project_id=project_id,
                role="assistant",
                content=response,
                metadata={
                    "source": source,
                },
            )
        except Exception:
            logger.exception(
                "Unable to save assistant message."
            )

        return {
            "ok": True,
            "response": response,
            "source": source,
        }

    # =========================================================
    # Create work card
    # =========================================================

    async def create_work_card(
        self,
        project_id: int,
        title: str,
        description: str = "",
        workflow_type: str = "assistant",
        metadata: Optional[dict[str, Any]] = None,
        requires_approval: bool = True,
    ) -> dict[str, Any]:

        status = (
            "needs_approval"
            if requires_approval
            else "queued"
        )

        card = self.db.create_work_card(
            project_id=project_id,
            title=title,
            description=description,
            workflow_type=workflow_type,
            status=status,
            metadata=metadata or {},
        )

        return card

    # =========================================================
    # Summarize work card
    # =========================================================

    async def summarize_work_card(
        self,
        work_card_id: int,
    ) -> str:

        card = self.db.get_work_card(
            work_card_id
        )

        if not card:
            return "لم يتم العثور على بطاقة العمل."

        title = card.get(
            "title",
            "",
        )

        description = card.get(
            "description",
            "",
        )

        status = card.get(
            "status",
            "",
        )

        return (
            f"المهمة: {title}\n"
            f"الوصف: {description}\n"
            f"الحالة: {status}"
        )

    # =========================================================
    # Parse workflow request
    # =========================================================

    def parse_workflow_request(
        self,
        message: str,
    ) -> dict[str, Any]:

        text = message.strip()

        if not text:
            return {
                "workflow_type": "assistant",
                "requires_approval": True,
                "operations": [],
            }

        lowered = text.lower()

        workflow_type = "assistant"

        if any(
            keyword in lowered
            for keyword in (
                "api",
                "واجهة api",
                "api ",
            )
        ):
            workflow_type = "api"

        elif any(
            keyword in lowered
            for keyword in (
                "browser",
                "playwright",
                "متصفح",
                "موقع",
            )
        ):
            workflow_type = "browser"

        elif any(
            keyword in lowered
            for keyword in (
                "upload",
                "رفع",
                "ملف",
                "design",
                "تصميم",
                "pod",
            )
        ):
            workflow_type = "upload"

        operations: list[dict[str, Any]] = []

        return {
            "workflow_type": workflow_type,
            "requires_approval": True,
            "operations": operations,
            "original_request": text,
        }

    # =========================================================
    # Validate operations
    # =========================================================

    def validate_operations(
        self,
        operations: Any,
    ) -> tuple[bool, list[str]]:

        if not isinstance(
            operations,
            list,
        ):
            return (
                False,
                ["operations يجب أن تكون قائمة."],
            )

        errors: list[str] = []

        for index, operation in enumerate(
            operations
        ):
            if not isinstance(
                operation,
                dict,
            ):
                errors.append(
                    f"العملية رقم {index + 1} ليست كائناً."
                )
                continue

            operation_type = str(
                operation.get(
                    "type",
                    "",
                )
            ).strip().lower()

            if operation_type not in self.ALLOWED_OPERATIONS:
                errors.append(
                    "العملية غير مسموحة: "
                    f"{operation_type}"
                )

        return (
            len(errors) == 0,
            errors,
        )

    # =========================================================
    # Export state
    # =========================================================

    def export_state(
        self,
        project_id: Optional[int] = None,
    ) -> dict[str, Any]:

        state: dict[str, Any] = {
            "project_id": project_id,
            "chat_messages": [],
            "work_cards": [],
        }

        try:
            state["chat_messages"] = (
                self.db.list_chat_messages(
                    project_id=project_id,
                    limit=100,
                )
            )
        except Exception:
            logger.exception(
                "Unable to export chat state."
            )

        try:
            state["work_cards"] = (
                self.db.list_work_cards(
                    project_id=project_id,
                    limit=100,
                )
            )
        except Exception:
            logger.exception(
                "Unable to export work-card state."
            )

        return state
