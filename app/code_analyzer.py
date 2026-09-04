from __future__ import annotations

import ast
from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class CodeFinding:
    severity: str
    category: str
    message: str
    line: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CodeAnalyzer:
    BLOCKED_CALLS = {
        "exec",
        "eval",
        "compile",
        "__import__",
    }

    BLOCKED_IMPORTS = {
        "subprocess",
        "ctypes",
        "pickle",
    }

    DANGEROUS_ATTRIBUTES = {
        "__globals__",
        "__subclasses__",
        "__builtins__",
    }

    def analyze(
        self,
        code: str,
    ) -> dict[str, Any]:

        findings: list[CodeFinding] = []

        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            findings.append(
                CodeFinding(
                    severity="error",
                    category="syntax",
                    message=str(exc),
                    line=exc.lineno,
                )
            )

            return {
                "safe_to_execute": False,
                "syntax_valid": False,
                "findings": [
                    finding.to_dict()
                    for finding in findings
                ],
            }

        for node in ast.walk(tree):

            if isinstance(node, ast.Call):
                function_name = self._get_call_name(
                    node.func
                )

                if function_name in self.BLOCKED_CALLS:
                    findings.append(
                        CodeFinding(
                            severity="high",
                            category="dynamic_execution",
                            message=(
                                f"Detected blocked call: "
                                f"{function_name}"
                            ),
                            line=getattr(
                                node,
                                "lineno",
                                None,
                            ),
                        )
                    )

            elif isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]

                    if root in self.BLOCKED_IMPORTS:
                        findings.append(
                            CodeFinding(
                                severity="high",
                                category="dangerous_import",
                                message=(
                                    f"Detected restricted "
                                    f"import: {root}"
                                ),
                                line=getattr(
                                    node,
                                    "lineno",
                                    None,
                                ),
                            )
                        )

            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    root = node.module.split(".")[0]

                    if root in self.BLOCKED_IMPORTS:
                        findings.append(
                            CodeFinding(
                                severity="high",
                                category="dangerous_import",
                                message=(
                                    f"Detected restricted "
                                    f"import: {root}"
                                ),
                                line=getattr(
                                    node,
                                    "lineno",
                                    None,
                                ),
                            )
                        )

            elif isinstance(node, ast.Attribute):
                if node.attr in self.DANGEROUS_ATTRIBUTES:
                    findings.append(
                        CodeFinding(
                            severity="high",
                            category="unsafe_attribute",
                            message=(
                                f"Detected unsafe attribute: "
                                f"{node.attr}"
                            ),
                            line=getattr(
                                node,
                                "lineno",
                                None,
                            ),
                        )
                    )

        has_high_risk = any(
            finding.severity == "high"
            for finding in findings
        )

        return {
            "safe_to_execute": not has_high_risk,
            "syntax_valid": True,
            "findings": [
                finding.to_dict()
                for finding in findings
            ],
        }

    @staticmethod
    def _get_call_name(
        node: ast.AST,
    ) -> str | None:

        if isinstance(node, ast.Name):
            return node.id

        if isinstance(node, ast.Attribute):
            return node.attr

        return None
