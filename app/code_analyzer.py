from __future__ import annotations

import ast
from pathlib import Path
from typing import Any


class CodeAnalyzer:
    """
    Static code analyzer.

    Important:
    This class NEVER executes uploaded code.
    It only parses and inspects the source statically.
    """

    DANGEROUS_IMPORTS = {
        "subprocess",
        "ctypes",
        "pickle",
        "marshal",
        "pty",
        "commands",
        "winreg",
    }

    DANGEROUS_CALLS = {
        "exec",
        "eval",
        "compile",
        "__import__",
    }

    DANGEROUS_ATTRIBUTES = {
        "system",
        "popen",
        "run",
        "Popen",
        "check_call",
        "check_output",
        "loads",
        "load",
    }

    def __init__(self):
        pass

    def analyze(
        self,
        filename: str,
        source: str,
    ) -> dict[str, Any]:
        extension = Path(filename).suffix.lower()

        result: dict[str, Any] = {
            "filename": filename,
            "extension": extension,
            "language": self._detect_language(extension),
            "parseable": True,
            "risk_level": "low",
            "findings": [],
            "summary": "",
            "execution_performed": False,
        }

        if extension not in {
            ".py",
            ".pyw",
        }:
            result["summary"] = (
                "تم استلام الملف. التحليل الثابت المتقدم متاح "
                "حالياً لملفات Python فقط."
            )
            return result

        try:
            tree = ast.parse(
                source,
                filename=filename,
            )
        except SyntaxError as exc:
            result["parseable"] = False
            result["risk_level"] = "unknown"
            result["findings"].append(
                {
                    "severity": "error",
                    "type": "syntax_error",
                    "line": exc.lineno,
                    "message": (
                        "تعذر تحليل الملف بسبب خطأ نحوي: "
                        f"{exc.msg}"
                    ),
                }
            )
            result["summary"] = (
                "الملف يحتوي على خطأ نحوي ويحتاج إلى التصحيح "
                "قبل إجراء تحليل أعمق."
            )
            return result

        visitor = _SecurityVisitor(
            dangerous_imports=self.DANGEROUS_IMPORTS,
            dangerous_calls=self.DANGEROUS_CALLS,
            dangerous_attributes=self.DANGEROUS_ATTRIBUTES,
        )

        visitor.visit(tree)

        result["findings"] = visitor.findings
        result["risk_level"] = self._calculate_risk(
            visitor.findings
        )
        result["summary"] = self._build_summary(
            result["risk_level"],
            visitor.findings,
        )

        return result

    @staticmethod
    def _detect_language(
        extension: str,
    ) -> str:
        mapping = {
            ".py": "Python",
            ".pyw": "Python",
            ".js": "JavaScript",
            ".ts": "TypeScript",
            ".tsx": "TypeScript React",
            ".jsx": "JavaScript React",
            ".json": "JSON",
            ".html": "HTML",
            ".css": "CSS",
            ".yaml": "YAML",
            ".yml": "YAML",
            ".md": "Markdown",
        }

        return mapping.get(
            extension,
            "Unknown",
        )

    @staticmethod
    def _calculate_risk(
        findings: list[dict[str, Any]],
    ) -> str:
        if not findings:
            return "low"

        severities = {
            finding.get("severity")
            for finding in findings
        }

        if "critical" in severities:
            return "critical"

        if "high" in severities:
            return "high"

        if "medium" in severities:
            return "medium"

        return "low"

    @staticmethod
    def _build_summary(
        risk_level: str,
        findings: list[dict[str, Any]],
    ) -> str:
        if not findings:
            return (
                "لم يتم العثور على أنماط خطرة واضحة في التحليل "
                "الثابت. هذا لا يعني أن الكود آمن بشكل مطلق."
            )

        count = len(findings)

        if risk_level == "critical":
            return (
                f"تم العثور على {count} مؤشر خطورة حرج. "
                "يجب عدم تنفيذ الملف قبل المراجعة البشرية."
            )

        if risk_level == "high":
            return (
                f"تم العثور على {count} مؤشرات خطورة عالية. "
                "يجب مراجعة الملف قبل أي تشغيل."
            )

        if risk_level == "medium":
            return (
                f"تم العثور على {count} مؤشرات تستحق المراجعة. "
                "ينصح بفحص الكود قبل تشغيله."
            )

        return (
            f"تم العثور على {count} ملاحظات منخفضة الخطورة."
        )


class _SecurityVisitor(ast.NodeVisitor):
    def __init__(
        self,
        dangerous_imports: set[str],
        dangerous_calls: set[str],
        dangerous_attributes: set[str],
    ):
        self.dangerous_imports = dangerous_imports
        self.dangerous_calls = dangerous_calls
        self.dangerous_attributes = dangerous_attributes
        self.findings: list[dict[str, Any]] = []

    def _add(
        self,
        severity: str,
        finding_type: str,
        node: ast.AST,
        message: str,
    ) -> None:
        line = getattr(
            node,
            "lineno",
            None,
        )

        self.findings.append(
            {
                "severity": severity,
                "type": finding_type,
                "line": line,
                "message": message,
            }
        )

    def visit_Import(
        self,
        node: ast.Import,
    ) -> Any:
        for alias in node.names:
            root_name = alias.name.split(".")[0]

            if root_name in self.dangerous_imports:
                self._add(
                    severity="high",
                    finding_type="dangerous_import",
                    node=node,
                    message=(
                        f"استيراد مكتبة حساسة: {alias.name}"
                    ),
                )

        self.generic_visit(node)

    def visit_ImportFrom(
        self,
        node: ast.ImportFrom,
    ) -> Any:
        module = node.module or ""
        root_name = module.split(".")[0]

        if root_name in self.dangerous_imports:
            self._add(
                severity="high",
                finding_type="dangerous_import",
                node=node,
                message=(
                    f"استيراد مكتبة حساسة: {module}"
                ),
            )

        self.generic_visit(node)

    def visit_Call(
        self,
        node: ast.Call,
    ) -> Any:
        function_name = self._get_call_name(
            node.func
        )

        if function_name in self.dangerous_calls:
            severity = "critical"

            if function_name == "__import__":
                severity = "high"

            self._add(
                severity=severity,
                finding_type="dangerous_call",
                node=node,
                message=(
                    f"استخدام استدعاء حساس: "
                    f"{function_name}()"
                ),
            )

        attribute_name = self._get_attribute_name(
            node.func
        )

        if attribute_name in self.dangerous_attributes:
            self._add(
                severity="high",
                finding_type="dangerous_attribute_call",
                node=node,
                message=(
                    f"استخدام دالة قد تنفذ عملية خارجية أو "
                    f"تفك ترميز بيانات غير موثوقة: "
                    f"{attribute_name}()"
                ),
            )

        self.generic_visit(node)

    def visit_Attribute(
        self,
        node: ast.Attribute,
    ) -> Any:
        if node.attr in {
            "system",
            "popen",
            "Popen",
        }:
            self._add(
                severity="high",
                finding_type="sensitive_attribute",
                node=node,
                message=(
                    f"الوصول إلى خاصية حساسة: "
                    f"{node.attr}"
                ),
            )

        self.generic_visit(node)

    def visit_Subscript(
        self,
        node: ast.Subscript,
    ) -> Any:
        """
        Flag common environment/credential access patterns.
        This is advisory only and does not mean the code is malicious.
        """

        if isinstance(node.value, ast.Name):
            if node.value.id in {
                "os",
                "environ",
            }:
                self._add(
                    severity="medium",
                    finding_type="environment_access",
                    node=node,
                    message=(
                        "الوصول إلى متغيرات البيئة قد يتضمن "
                        "أسراراً أو مفاتيح تشغيل."
                    ),
                )

        self.generic_visit(node)

    @staticmethod
    def _get_call_name(
        node: ast.AST,
    ) -> str | None:
        if isinstance(node, ast.Name):
            return node.id

        if isinstance(node, ast.Attribute):
            return node.attr

        return None

    @staticmethod
    def _get_attribute_name(
        node: ast.AST,
    ) -> str | None:
        if isinstance(node, ast.Attribute):
            return node.attr

        return None
