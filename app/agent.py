from __future__ import annotations

import json
from typing import Any, Optional

import httpx

from app.config import Settings
from app.database import Database


class Agent:
    """
    AI agent for the Autonomous Business Manager.

    Design principles:
    - Never executes arbitrary user code.
    - Never bypasses CAPTCHA or authentication.
    - Never attempts anti-detection or fingerprint spoofing.
    - Sensitive actions must become approval-required work cards.
    - Keeps a local fallback when no OpenAI API key is configured.
    """

    def __init__(
        self,
        database: Database,
        settings: Settings,
    ):
        self.database = database
        self.settings = settings

    def _system_prompt(self) -> str:
        return """
أنت المساعد الذكي داخل نظام Autonomous Business Manager.

مهمتك:
- مساعدة المستخدم في إدارة المشاريع والأعمال الرقمية.
- تحليل الطلب وتحويل المهام العملية إلى خطوات واضحة وآمنة.
- اقتراح workflows مناسبة.
- عدم تنفيذ أي إجراء حساس بدون موافقة المستخدم.
- حماية الأسرار والمفاتيح وكلمات المرور.
- عدم طلب الأسرار الحساسة من المستخدم داخل المحادثة إذا كان النظام يستطيع تخزينها بشكل آمن.

قواعد السلامة:
1. لا تتجاوز CAPTCHA.
2. لا تتحايل على أنظمة مكافحة الروبوتات.
3. لا تستخدم fingerprint spoofing أو وسائل إخفاء الهوية.
4. لا تتحايل على rate limits.
5. لا تتجاوز تسجيل الدخول أو المصادقة.
6. لا تستخرج كلمات مرور أو session cookies أو رموز MFA من مواقع.
7. لا تنفذ كوداً مرفوعاً من المستخدم بشكل أعمى.
8. يجب تحليل الكود أولاً بشكل ثابت.
9. لا تنفذ أوامر shell غير محدودة.
10. أي عملية حساسة مثل النشر أو حذف البيانات أو تغيير الحسابات أو العمليات المالية يجب أن تتطلب موافقة صريحة.
11. عند الحاجة إلى تسجيل دخول أو إعادة مصادقة، أوقف المهمة واطلب من المستخدم إكمال العملية يدوياً.
12. إذا انقطع الإنترنت، يجب إيقاف العمليات القابلة للتنفيذ مؤقتاً واستئنافها بعد عودة الاتصال.

أسلوب الرد:
- تحدث بالعربية عندما يتحدث المستخدم بالعربية.
- كن واضحاً ومباشراً.
- لا تدّعي تنفيذ شيء لم يتم تنفيذه فعلياً.
- إذا كانت المهمة تحتاج موافقة، وضح ذلك.
- إذا كانت المهمة غير آمنة، ارفض الجزء الخطير واقترح البديل الآمن.
"""

    def _local_response(
        self,
        message: str,
        project_id: Optional[int] = None,
    ) -> str:
        text = message.strip()

        lowered = text.lower()

        if any(
            word in lowered
            for word in (
                "captcha",
                "كابتشا",
                "anti-detection",
                "fingerprint",
                "rate limit",
                "تجاوز المصادقة",
            )
        ):
            return (
                "لا أستطيع تنفيذ أو شرح طرق تجاوز CAPTCHA أو أنظمة "
                "مكافحة الروبوتات أو المصادقة أو حدود الاستخدام. "
                "يمكنني بدلاً من ذلك بناء سير عمل يعتمد على الواجهات "
                "الرسمية أو التفاعل الطبيعي مع الموقع."
            )

        if any(
            word in text
            for word in (
                "انترنت",
                "الإنترنت",
                "اتصال",
            )
        ):
            return (
                "النظام يراقب الاتصال بالإنترنت. عند انقطاع الاتصال "
                "يتم إيقاف الأعمال الجارية مؤقتاً، وعند عودة الاتصال "
                "يمكن استئناف الأعمال التي توقفت بسبب الانقطاع."
            )

        if any(
            word in text
            for word in (
                "مشروع",
                "مشروعي",
                "المشروع",
            )
        ):
            projects = self.database.list_projects()

            if not projects:
                return (
                    "لا توجد مشاريع حالياً. يمكنك إنشاء مشروع جديد "
                    "من لوحة التحكم."
                )

            names = [
                str(project.get("name", "بدون اسم"))
                for project in projects[:10]
            ]

            return (
                "المشاريع الحالية:\n- "
                + "\n- ".join(names)
            )

        if any(
            word in text
            for word in (
                "مساعدة",
                "ساعدني",
                "ماذا تستطيع",
            )
        ):
            return (
                "أستطيع مساعدتك في إدارة المشاريع، إنشاء بطاقات العمل، "
                "تحليل الكود المرفوع، تشغيل إجراءات المتصفح الطبيعية، "
                "ومراقبة الاتصال وحالة المهام. الإجراءات الحساسة "
                "تحتاج موافقة قبل تنفيذها."
            )

        if project_id is not None:
            return (
                "استلمت طلبك ضمن المشروع رقم "
                f"{project_id}. في الوضع المحلي الحالي لا يوجد مفتاح "
                "OpenAI مهيأ، لذلك أستطيع تقديم الإرشادات الأساسية "
                "وإدارة عناصر المشروع دون اتصال بالنموذج الخارجي."
            )

        return (
            "استلمت طلبك. النظام يعمل حالياً بالوضع المحلي لأن "
            "مفتاح OpenAI غير مهيأ. يمكنك متابعة إدارة المشاريع "
            "وتحليل الملفات والإجراءات الآمنة من لوحة التحكم."
        )

    async def _call_openai(
        self,
        messages: list[dict[str, str]],
    ) -> str:
        api_key = self.settings.openai_api_key

        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not configured."
            )

        url = "https://api.openai.com/v1/chat/completions"

        payload = {
            "model": self.settings.openai_model,
            "messages": messages,
            "temperature": 0.2,
        }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        timeout = max(
            30.0,
            float(self.settings.browser_timeout) / 1000,
        )

        async with httpx.AsyncClient(
            timeout=timeout,
        ) as client:
            response = await client.post(
                url,
                headers=headers,
                json=payload,
            )

        if response.status_code >= 400:
            try:
                error_data = response.json()
            except Exception:
                error_data = response.text

            raise RuntimeError(
                f"OpenAI API error: {error_data}"
            )

        data = response.json()

        choices = data.get("choices", [])

        if not choices:
            raise RuntimeError(
                "OpenAI API returned no choices."
            )

        message = choices[0].get("message", {})

        content = message.get("content")

        if not content:
            raise RuntimeError(
                "OpenAI API returned an empty response."
            )

        return str(content).strip()

    async def chat(
        self,
        message: str,
        project_id: Optional[int] = None,
    ) -> str:
        message = message.strip()

        if not message:
            return "اكتب طلبك أولاً."

        self.database.create_chat_message(
            role="user",
            content=message,
            project_id=project_id,
        )

        history = self.database.list_chat_messages(
            project_id=project_id,
            limit=30,
        )

        messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": self._system_prompt(),
            }
        ]

        for item in history:
            role = item.get("role", "user")
            content = item.get("content", "")

            if role not in {
                "system",
                "user",
                "assistant",
            }:
                role = "user"

            messages.append(
                {
                    "role": role,
                    "content": str(content),
                }
            )

        try:
            if self.settings.openai_api_key:
                response = await self._call_openai(
                    messages=messages,
                )
            else:
                response = self._local_response(
                    message=message,
                    project_id=project_id,
                )

        except Exception as exc:
            response = (
                "تعذر الاتصال بخدمة الذكاء الاصطناعي حالياً. "
                "تم الرجوع إلى الوضع المحلي.\n\n"
                + self._local_response(
                    message=message,
                    project_id=project_id,
                )
            )

            try:
                self.database.create_event(
                    event_type="warning",
                    message=(
                        "تعذر الاتصال بخدمة الذكاء الاصطناعي: "
                        f"{type(exc).__name__}"
                    ),
                    project_id=project_id,
                )
            except Exception:
                pass

        self.database.create_chat_message(
            role="assistant",
            content=response,
            project_id=project_id,
        )

        return response

    def create_work_card(
        self,
        project_id: Optional[int],
        title: str,
        description: str,
        workflow_type: str = "assistant",
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """
        Create a work card.

        New operational cards default to needs_approval so that
        sensitive work is never silently executed.
        """

        card = self.database.create_work_card(
            project_id=project_id,
            title=title,
            description=description,
            workflow_type=workflow_type,
            status="needs_approval",
            metadata=metadata or {},
        )

        card_id = card.get("id")

        try:
            self.database.create_event(
                event_type="approval_required",
                message=(
                    "تم إنشاء بطاقة عمل وتحتاج إلى موافقة المستخدم."
                ),
                project_id=project_id,
                work_card_id=card_id,
                metadata={
                    "title": title,
                    "workflow_type": workflow_type,
                },
            )
        except Exception:
            pass

        return card

    def summarize_work_card(
        self,
        card: dict[str, Any],
    ) -> str:
        title = card.get("title", "بدون عنوان")
        description = card.get("description", "")
        status = card.get("status", "unknown")
        workflow = card.get(
            "workflow_type",
            "assistant",
        )

        return (
            f"المهمة: {title}\n"
            f"النوع: {workflow}\n"
            f"الحالة: {status}\n"
            f"التفاصيل: {description}"
        )

    def parse_workflow_request(
        self,
        message: str,
    ) -> dict[str, Any]:
        """
        Lightweight workflow classifier.

        This does not execute anything. It only determines the
        likely workflow category for later approval.
        """

        text = message.lower()

        if any(
            word in text
            for word in (
                "api",
                "واجهة",
                "حساب",
                "account",
                "token",
            )
        ):
            workflow_type = "api_account"

        elif any(
            word in text
            for word in (
                "رفع",
                "upload",
                "تصميم",
                "design",
                "pod",
                "منتج",
            )
        ):
            workflow_type = "upload_design"

        elif any(
            word in text
            for word in (
                "كود",
                "code",
                "برمجة",
                "github",
                "api",
            )
        ):
            workflow_type = "code_api"

        elif any(
            word in text
            for word in (
                "dual",
                "مزدوج",
                "متعدد",
            )
        ):
            workflow_type = "dual"

        else:
            workflow_type = "assistant"

        sensitive = any(
            word in text
            for word in (
                "حذف",
                "دفع",
                "شراء",
                "نشر",
                "publish",
                "delete",
                "payment",
                "شراء",
                "تغيير كلمة المرور",
                "password",
                "token",
            )
        )

        return {
            "workflow_type": workflow_type,
            "requires_approval": sensitive or workflow_type != "assistant",
        }

    def export_state(self) -> dict[str, Any]:
        """
        Return non-secret agent configuration/state.
        """
        return {
            "model": self.settings.openai_model,
            "openai_configured": bool(
                self.settings.openai_api_key
            ),
            }
