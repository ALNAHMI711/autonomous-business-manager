from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace(path: str, old: str, new: str) -> None:
    file = ROOT / path
    text = file.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"Expected patch anchor missing: {path}: {old[:80]!r}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


# Browser: per-context proxy support.
replace(
    "app/browser.py",
    "from typing import Any\n",
    "from typing import Any, Optional\n",
)
replace(
    "app/browser.py",
    "        self._pages: dict[int, Page] = {}\n",
    "        self._pages: dict[int, Page] = {}\n        self._network_profiles: dict[int, str] = {}\n",
)
replace(
    "app/browser.py",
    "    async def open_project(\n        self,\n        project_id: int,\n        site: str,\n    ) -> dict[str, Any]:\n",
    "    async def open_project(\n        self,\n        project_id: int,\n        site: str,\n        proxy: Optional[dict[str, Any]] = None,\n        network_profile_name: Optional[str] = None,\n    ) -> dict[str, Any]:\n",
)
replace(
    "app/browser.py",
    "        existing = self._contexts.get(project_id)\n\n        if existing is not None:\n",
    "        existing = self._contexts.get(project_id)\n\n        if existing is not None and self._network_profiles.get(project_id) != network_profile_name:\n            await self.close_project(project_id)\n            existing = None\n\n        if existing is not None:\n",
)
replace(
    "        context_kwargs: dict[str, Any] = {\n            \"viewport\": {\n                \"width\": 1440,\n                \"height\": 900,\n            },\n            \"locale\": \"ar-SA\",\n        }\n",
    "        context_kwargs: dict[str, Any] = {\n            \"viewport\": {\n                \"width\": 1440,\n                \"height\": 900,\n            },\n            \"locale\": \"ar-SA\",\n        }\n\n        if proxy:\n            context_kwargs[\"proxy\"] = proxy\n",
)
replace(
    "app/browser.py",
    "        self._contexts[project_id] = context\n        self._pages[project_id] = page\n",
    "        self._contexts[project_id] = context\n        self._pages[project_id] = page\n        self._network_profiles[project_id] = network_profile_name or \"direct\"\n",
)
replace(
    "        self._pages.pop(\n            project_id,\n            None,\n        )\n\n        if context is None:\n",
    "        self._pages.pop(\n            project_id,\n            None,\n        )\n        self._network_profiles.pop(project_id, None)\n\n        if context is None:\n",
)

# Requirements: SOCKS proxy testing support.
replace(
    "requirements.txt",
    "httpx>=0.27,<1.0\n",
    "httpx[socks]>=0.27,<1.0\n",
)

# Main API: network manager, request models, project/browser integration and routes.
replace(
    "app/main.py",
    "from app.notifications import NotificationManager\n",
    "from app.notifications import NotificationManager\nfrom app.network import NetworkManager, NetworkProfile\n",
)
replace(
    "security = SecurityManager(settings)\n\nagent = Agent(\n",
    "security = SecurityManager(settings)\n\nnetwork_manager = NetworkManager(\n    database=db,\n    security=security,\n)\n\nagent = Agent(\n",
)
replace(
    "class BrowserOpenRequest(BaseModel):\n    project_id: int\n    site: str = Field(min_length=1, max_length=2000)\n    url: Optional[str] = Field(default=None, max_length=2000)\n",
    "class BrowserOpenRequest(BaseModel):\n    project_id: int\n    site: str = Field(min_length=1, max_length=2000)\n    url: Optional[str] = Field(default=None, max_length=2000)\n    network_profile: Optional[str] = Field(default=None, max_length=80)\n\n\nclass NetworkProfileRequest(BaseModel):\n    name: str = Field(min_length=1, max_length=80)\n    mode: str = Field(default=\"direct\", max_length=20)\n    proxy_server: str = Field(default=\"\", max_length=500)\n    username: str = Field(default=\"\", max_length=200)\n    password: str = Field(default=\"\", max_length=500)\n    bypass: str = Field(default=\"\", max_length=1000)\n\n\nclass NetworkTestRequest(BaseModel):\n    name: str = Field(min_length=1, max_length=80)\n",
)
# Fix the known indentation errors in the project endpoint/model.
replace(
    "    description: str = Field(default=\"\", max_length=5000)\n   workflow_type: str = Field(default=\"assistant\", max_length=50)\n",
    "    description: str = Field(default=\"\", max_length=5000)\n    workflow_type: str = Field(default=\"assistant\", max_length=50)\n",
)
replace(
    "   project = db.create_project(\n    name=request.name,\n    description=request.description,\n    workflow_type=request.workflow_type,\n   ) \n",
    "    project = db.create_project(\n        name=request.name,\n        description=request.description,\n        workflow_type=request.workflow_type,\n    )\n",
)
# Network routes are intentionally before browser routes.
anchor = "# ================================================================\n# المتصفح\n# ================================================================\n"
network_routes = '''# ================================================================\n# الشبكة ومسارات الخروج\n# ================================================================\n\n@app.get("/api/network/profiles")\nasync def network_profiles(_: str = Depends(_require_session)):\n    return {"profiles": network_manager.list_profiles()}\n\n\n@app.post("/api/network/profiles")\nasync def save_network_profile(\n    request: NetworkProfileRequest,\n    _: str = Depends(_require_session),\n):\n    try:\n        profile = NetworkProfile(\n            name=request.name.strip(),\n            mode=request.mode.strip().lower(),\n            proxy_server=request.proxy_server.strip(),\n            username=request.username.strip(),\n            password=request.password,\n            bypass=request.bypass.strip(),\n        )\n        saved = network_manager.save_profile(profile)\n        return {"success": True, "profile": saved}\n    except Exception as exc:\n        raise HTTPException(status_code=400, detail=str(exc)) from exc\n\n\n@app.delete("/api/network/profiles/{name}")\nasync def delete_network_profile(\n    name: str,\n    _: str = Depends(_require_session),\n):\n    deleted = network_manager.delete_profile(name)\n    return {"success": deleted}\n\n\n@app.post("/api/network/test")\nasync def test_network_profile(\n    request: NetworkTestRequest,\n    _: str = Depends(_require_session),\n):\n    try:\n        result = await network_manager.test_profile(request.name)\n        db.create_event(\n            event_type="network_test",\n            message=f"تم اختبار ملف الشبكة: {request.name}",\n            metadata={"observed_public_ip": result.get("observed_public_ip", "")},\n        )\n        return result\n    except Exception as exc:\n        raise HTTPException(status_code=400, detail=str(exc)) from exc\n\n\n@app.post("/api/projects/{project_id}/network")\nasync def bind_project_network(\n    project_id: int,\n    profile_name: Optional[str] = None,\n    _: str = Depends(_require_session),\n):\n    _require_project(project_id)\n    try:\n        network_manager.bind_project(project_id, profile_name)\n        return {"success": True, "profile": profile_name or "direct"}\n    except Exception as exc:\n        raise HTTPException(status_code=400, detail=str(exc)) from exc\n\n\n@app.get("/api/projects/{project_id}/network")\nasync def get_project_network(\n    project_id: int,\n    _: str = Depends(_require_session),\n):\n    _require_project(project_id)\n    profile = network_manager.get_project_profile(project_id)\n    return {"profile": profile.masked() if profile else {"name": "direct", "mode": "direct"}}\n\n\n'''
replace("app/main.py", anchor, network_routes + anchor)
replace(
    "        result = await browser.open_project(\n            project_id=request.project_id,\n            site=target,\n        )\n",
    "        profile = (\n            network_manager.get_profile(request.network_profile)\n            if request.network_profile\n            else network_manager.get_project_profile(request.project_id)\n        )\n        profile_name = profile.name if profile else \"direct\"\n        result = await browser.open_project(\n            project_id=request.project_id,\n            site=target,\n            proxy=profile.to_playwright_proxy() if profile else None,\n            network_profile_name=profile_name,\n        )\n",
)

# Add network configuration to the dashboard without replacing the existing layout.
replace(
    "    <section class=\"dashboard-grid\">\n\n      <div class=\"panel\">\n\n        <div class=\"panel-header\">\n          <div>\n            <h2>المتصفح</h2>",
    "    <section class=\"dashboard-grid\">\n\n      <div class=\"panel\">\n\n        <div class=\"panel-header\">\n          <div>\n            <h2>الشبكة / IP</h2>\n            <p>استخدم اتصال الهاتف مباشرة أو Proxy محدد للمشروع. VPN النظام يبقى مسؤولية الجهاز.</p>\n          </div>\n        </div>\n\n        <div class=\"form-grid\">\n          <label>الملف<select id=\"networkProfile\"><option value=\"\">مباشر (إنترنت الجهاز)</option></select></label>\n          <label>اسم الملف<input id=\"networkName\" value=\"phone-direct\" maxlength=\"80\"></label>\n          <label>الوضع<select id=\"networkMode\"><option value=\"direct\">مباشر</option><option value=\"proxy\">Proxy</option></select></label>\n          <label>Proxy Server<input id=\"networkProxy\" placeholder=\"socks5://127.0.0.1:1080\"></label>\n          <label>اسم المستخدم<input id=\"networkUsername\"></label>\n          <label>كلمة مرور Proxy<input id=\"networkPassword\" type=\"password\"></label>\n          <label>Bypass<input id=\"networkBypass\" placeholder=\"localhost,127.0.0.1\"></label>\n        </div>\n        <div class=\"button-row\">\n          <button id=\"networkSaveBtn\" class=\"primary-btn\">حفظ</button>\n          <button id=\"networkTestBtn\" class=\"secondary-btn\">اختبار IP</button>\n          <button id=\"networkBindBtn\" class=\"secondary-btn\">ربط بالمشروع</button>\n        </div>\n        <div id=\"networkResult\" class=\"result-box\">لم يتم اختبار مسار الشبكة بعد.</div>\n      </div>\n\n      <div class=\"panel\">\n\n        <div class=\"panel-header\">\n          <div>\n            <h2>المتصفح</h2>",
)

# Append dashboard logic; it uses the existing api(), $, showToast() helpers.
app_js = ROOT / "frontend/static/app.js"
js = app_js.read_text(encoding="utf-8")
js += r'''\n\n// Network / IP routing controls\nasync function loadNetworkProfiles() {\n  const data = await api("/api/network/profiles");\n  const select = $("networkProfile");\n  if (!select) return;\n  select.innerHTML = '<option value="">مباشر (إنترنت الجهاز)</option>';\n  for (const profile of data.profiles || []) {\n    const option = document.createElement("option");\n    option.value = profile.name;\n    option.textContent = `${profile.name} — ${profile.mode}${profile.proxy_server ? ` — ${profile.proxy_server}` : ""}`;\n    select.appendChild(option);\n  }\n}\n\nasync function saveNetworkProfile() {\n  const payload = {\n    name: $("networkName").value.trim(),\n    mode: $("networkMode").value,\n    proxy_server: $("networkProxy").value.trim(),\n    username: $("networkUsername").value.trim(),\n    password: $("networkPassword").value,\n    bypass: $("networkBypass").value.trim(),\n  };\n  const data = await api("/api/network/profiles", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)});\n  $("networkResult").textContent = `تم حفظ ${data.profile.name}.`;\n  $("networkPassword").value = "";\n  await loadNetworkProfiles();\n  $("networkProfile").value = data.profile.name;\n}\n\nasync function testNetworkProfile() {\n  const name = $("networkProfile").value || $("networkName").value.trim();\n  if (!name) throw new Error("اختر أو أنشئ ملف شبكة أولاً.");\n  const data = await api("/api/network/test", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({name})});\n  $("networkResult").textContent = `نجح الاتصال. عنوان IP العام المرصود: ${data.observed_public_ip || "غير متاح"}`;\n}\n\nasync function bindNetworkToProject() {\n  const projectId = Number($("browserProject").value);\n  if (!projectId) throw new Error("اختر المشروع أولاً.");\n  const profile = $("networkProfile").value || null;\n  await api(`/api/projects/${projectId}/network${profile ? `?profile_name=${encodeURIComponent(profile)}` : ""}`, {method: "POST"});\n  $("networkResult").textContent = `تم ربط المشروع بمسار: ${profile || "direct"}.`;\n}\n\n$("networkSaveBtn")?.addEventListener("click", async () => {\n  try { await saveNetworkProfile(); showToast("تم حفظ ملف الشبكة", "success"); } catch (error) { showToast(error.message, "error"); }\n});\n$("networkTestBtn")?.addEventListener("click", async () => {\n  try { await testNetworkProfile(); showToast("تم اختبار الشبكة", "success"); } catch (error) { showToast(error.message, "error"); }\n});\n$("networkBindBtn")?.addEventListener("click", async () => {\n  try { await bindNetworkToProject(); showToast("تم ربط مسار الشبكة بالمشروع", "success"); } catch (error) { showToast(error.message, "error"); }\n});\n$("networkProfile")?.addEventListener("change", async (event) => {\n  const name = event.target.value;\n  if (!name) return;\n  try {\n    const data = await api("/api/network/profiles");\n    const profile = (data.profiles || []).find((item) => item.name === name);\n    if (!profile) return;\n    $("networkName").value = profile.name;\n    $("networkMode").value = profile.mode;\n    $("networkProxy").value = profile.proxy_server || "";\n    $("networkUsername").value = profile.username || "";\n    $("networkBypass").value = profile.bypass || "";\n    $("networkPassword").value = "";\n  } catch (error) { showToast(error.message, "error"); }\n});\nloadNetworkProfiles().catch(() => {});\n'''
app_js.write_text(js, encoding="utf-8")

# Engineering audit / delivery contract.
report = ROOT / "ENGINEERING_AUDIT.md"
report.write_text('''# Autonomous Business Manager — Engineering Audit & Delivery Plan\n\n## Baseline\n\nThe project is a FastAPI + SQLite + Playwright Arabic RTL business automation system. The repository already contains an Agent, approval manager, task manager, connectivity monitor, encrypted secrets, browser session storage, code analysis, notifications, and a web dashboard.\n\n## Findings from the current tree\n\n### Strengths\n- Clear separation of FastAPI, database, security, browser, agent and task components.\n- SQLite uses foreign keys, WAL and a busy timeout.\n- Secrets use Fernet encryption; password utilities use PBKDF2-HMAC-SHA256.\n- Browser automation is deliberately restricted: HTTPS (plus localhost HTTP), no CAPTCHA bypass, no fingerprint spoofing and no arbitrary user JavaScript/Shell execution.\n- Connectivity monitoring already pauses/resumes work through callbacks.\n\n### Critical gaps to close\n1. Persistent task execution is still weaker than a production queue/worker architecture.\n2. Sessions are currently in-memory in `app/main.py`; restart invalidates them.\n3. Authentication needs rate limiting and persistent/session rotation hardening.\n4. There were syntax/indentation defects in the project request model and project creation endpoint.\n5. There was no reliable automated test suite or CI gate.\n6. Browser network routing was not configurable per project.\n7. A VPN cannot be created by the web application itself; the operating-system VPN remains external.\n\n## Network architecture added in this phase\n\n- `direct`: uses the normal OS route. When the application runs on Termux and the phone is using mobile data, this means the phone's network path.\n- `proxy`: supports HTTP, HTTPS and SOCKS5 proxy endpoints per browser context. Playwright officially supports HTTP(S) and SOCKS proxies at browser-context level.\n- Proxy credentials are encrypted using the existing Fernet secret mechanism.\n- The dashboard can create, test and bind a network profile to a project.\n- The network test reports the observed public egress IP using `api.ipify.org`; it does not pretend that a configured destination IP is a source IP.\n- A true VPN remains a device/OS networking concern; the application can work through it when it is enabled on the host.\n\n## Target production architecture\n\n`Web UI -> FastAPI -> Auth/RBAC -> Agent/Planner -> Permissioned Tool Bus -> Persistent Queue -> Executor -> Verifier -> Recovery -> Events/Notifications -> Memory`\n\nNetwork routing is a separate policy layer: `Project -> Network Profile -> Browser/API transport`.\n\n## Required delivery gates\n\n1. Compile/static validation.\n2. Unit/API tests.\n3. CI on every push and pull request.\n4. Security review and secret scan.\n5. Browser/network smoke tests.\n6. Persistent task queue + retry/recovery.\n7. Authentication/session hardening.\n8. Observability/audit trail.\n9. Deployment packaging and health checks.\n10. Final end-to-end acceptance from login through project creation, network selection, browser execution, approval, task completion and logout.\n\n## Acceptance rule\n\nNo phase is considered complete until its code is committed, its CI result is green, and the changed behavior is verified against the intended API/UI contract.\n''', encoding="utf-8")

print("bootstrap patch complete")
