from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "app/main.py"

if "from app.network import NetworkManager, NetworkProfile" in MAIN.read_text(encoding="utf-8"):
    print("engineering patch already applied")
    raise SystemExit(0)


def replace(path: str, old: str, new: str) -> None:
    file = ROOT / path
    text = file.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"Expected patch anchor missing: {path}: {old[:80]!r}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


# Browser: per-context proxy support.
replace("app/browser.py", "from typing import Any\n", "from typing import Any, Optional\n")
replace("app/browser.py", "        self._pages: dict[int, Page] = {}\n", "        self._pages: dict[int, Page] = {}\n        self._network_profiles: dict[int, str] = {}\n")
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
    "app/browser.py",
    "        context_kwargs: dict[str, Any] = {\n            \"viewport\": {\n                \"width\": 1440,\n                \"height\": 900,\n            },\n            \"locale\": \"ar-SA\",\n        }\n",
    "        context_kwargs: dict[str, Any] = {\n            \"viewport\": {\n                \"width\": 1440,\n                \"height\": 900,\n            },\n            \"locale\": \"ar-SA\",\n        }\n\n        if proxy:\n            context_kwargs[\"proxy\"] = proxy\n",
)
replace(
    "app/browser.py",
    "        self._contexts[project_id] = context\n        self._pages[project_id] = page\n",
    "        self._contexts[project_id] = context\n        self._pages[project_id] = page\n        self._network_profiles[project_id] = network_profile_name or \"direct\"\n",
)
replace(
    "app/browser.py",
    "        self._pages.pop(\n            project_id,\n            None,\n        )\n\n        if context is None:\n",
    "        self._pages.pop(\n            project_id,\n            None,\n        )\n        self._network_profiles.pop(project_id, None)\n\n        if context is None:\n",
)

replace("requirements.txt", "httpx>=0.27,<1.0\n", "httpx[socks]>=0.27,<1.0\n")

replace("app/main.py", "from app.notifications import NotificationManager\n", "from app.notifications import NotificationManager\nfrom app.network import NetworkManager, NetworkProfile\n")
replace(
    "app/main.py",
    "security = SecurityManager(settings)\n\nagent = Agent(\n",
    "security = SecurityManager(settings)\n\nnetwork_manager = NetworkManager(\n    database=db,\n    security=security,\n)\n\nagent = Agent(\n",
)
replace(
    "app/main.py",
    "class BrowserOpenRequest(BaseModel):\n    project_id: int\n    site: str = Field(min_length=1, max_length=2000)\n    url: Optional[str] = Field(default=None, max_length=2000)\n",
    "class BrowserOpenRequest(BaseModel):\n    project_id: int\n    site: str = Field(min_length=1, max_length=2000)\n    url: Optional[str] = Field(default=None, max_length=2000)\n    network_profile: Optional[str] = Field(default=None, max_length=80)\n\n\nclass NetworkProfileRequest(BaseModel):\n    name: str = Field(min_length=1, max_length=80)\n    mode: str = Field(default=\"direct\", max_length=20)\n    proxy_server: str = Field(default=\"\", max_length=500)\n    username: str = Field(default=\"\", max_length=200)\n    password: str = Field(default=\"\", max_length=500)\n    bypass: str = Field(default=\"\", max_length=1000)\n\n\nclass NetworkTestRequest(BaseModel):\n    name: str = Field(min_length=1, max_length=80)\n",
)
replace(
    "app/main.py",
    "    description: str = Field(default=\"\", max_length=5000)\n   workflow_type: str = Field(default=\"assistant\", max_length=50)\n",
    "    description: str = Field(default=\"\", max_length=5000)\n    workflow_type: str = Field(default=\"assistant\", max_length=50)\n",
)
replace(
    "app/main.py",
    "   project = db.create_project(\n    name=request.name,\n    description=request.description,\n    workflow_type=request.workflow_type,\n   ) \n",
    "    project = db.create_project(\n        name=request.name,\n        description=request.description,\n        workflow_type=request.workflow_type,\n    )\n",
)
anchor = "# ================================================================\n# المتصفح\n# ================================================================\n"
network_routes = '''# ================================================================\n# الشبكة ومسارات الخروج\n# ================================================================\n\n@app.get("/api/network/profiles")\nasync def network_profiles(_: str = Depends(_require_session)):\n    return {"profiles": network_manager.list_profiles()}\n\n\n@app.post("/api/network/profiles")\nasync def save_network_profile(request: NetworkProfileRequest, _: str = Depends(_require_session)):\n    try:\n        profile = NetworkProfile(name=request.name.strip(), mode=request.mode.strip().lower(), proxy_server=request.proxy_server.strip(), username=request.username.strip(), password=request.password, bypass=request.bypass.strip())\n        return {"success": True, "profile": network_manager.save_profile(profile)}\n    except Exception as exc:\n        raise HTTPException(status_code=400, detail=str(exc)) from exc\n\n\n@app.delete("/api/network/profiles/{name}")\nasync def delete_network_profile(name: str, _: str = Depends(_require_session)):\n    return {"success": network_manager.delete_profile(name)}\n\n\n@app.post("/api/network/test")\nasync def test_network_profile(request: NetworkTestRequest, _: str = Depends(_require_session)):\n    try:\n        return await network_manager.test_profile(request.name)\n    except Exception as exc:\n        raise HTTPException(status_code=400, detail=str(exc)) from exc\n\n\n@app.post("/api/projects/{project_id}/network")\nasync def bind_project_network(project_id: int, profile_name: Optional[str] = None, _: str = Depends(_require_session)):\n    _require_project(project_id)\n    try:\n        network_manager.bind_project(project_id, profile_name)\n        return {"success": True, "profile": profile_name or "direct"}\n    except Exception as exc:\n        raise HTTPException(status_code=400, detail=str(exc)) from exc\n\n\n@app.get("/api/projects/{project_id}/network")\nasync def get_project_network(project_id: int, _: str = Depends(_require_session)):\n    _require_project(project_id)\n    profile = network_manager.get_project_profile(project_id)\n    return {"profile": profile.masked() if profile else {"name": "direct", "mode": "direct"}}\n\n\n'''
replace("app/main.py", anchor, network_routes + anchor)
replace(
    "app/main.py",
    "        result = await browser.open_project(\n            project_id=request.project_id,\n            site=target,\n        )\n",
    "        profile = (network_manager.get_profile(request.network_profile) if request.network_profile else network_manager.get_project_profile(request.project_id))\n        profile_name = profile.name if profile else \"direct\"\n        result = await browser.open_project(project_id=request.project_id, site=target, proxy=profile.to_playwright_proxy() if profile else None, network_profile_name=profile_name)\n",
)

# Dashboard network controls.
replace(
    "frontend/index.html",
    "    <section class=\"dashboard-grid\">\n\n      <div class=\"panel\">\n\n        <div class=\"panel-header\">\n          <div>\n            <h2>المتصفح</h2>",
    "    <section class=\"dashboard-grid\">\n\n      <div class=\"panel\">\n        <div class=\"panel-header\"><div><h2>الشبكة / IP</h2><p>مباشر عبر الجهاز أو Proxy للمشروع. الـVPN الحقيقي يبقى مسؤولية نظام الهاتف.</p></div></div>\n        <div class=\"form-grid\">\n          <label>الملف<select id=\"networkProfile\"><option value=\"\">مباشر (إنترنت الجهاز)</option></select></label>\n          <label>الاسم<input id=\"networkName\" value=\"phone-direct\"></label>\n          <label>الوضع<select id=\"networkMode\"><option value=\"direct\">مباشر</option><option value=\"proxy\">Proxy</option></select></label>\n          <label>Proxy Server<input id=\"networkProxy\" placeholder=\"socks5://127.0.0.1:1080\"></label>\n          <label>المستخدم<input id=\"networkUsername\"></label>\n          <label>كلمة مرور Proxy<input id=\"networkPassword\" type=\"password\"></label>\n          <label>Bypass<input id=\"networkBypass\"></label>\n        </div>\n        <div class=\"button-row\"><button id=\"networkSaveBtn\" class=\"primary-btn\">حفظ</button><button id=\"networkTestBtn\" class=\"secondary-btn\">اختبار IP</button><button id=\"networkBindBtn\" class=\"secondary-btn\">ربط بالمشروع</button></div>\n        <div id=\"networkResult\" class=\"result-box\">لم يتم الاختبار.</div>\n      </div>\n\n      <div class=\"panel\">\n        <div class=\"panel-header\">\n          <div>\n            <h2>المتصفح</h2>",
)

app_js = ROOT / "frontend/static/app.js"
js = app_js.read_text(encoding="utf-8")
if "async function loadNetworkProfiles" not in js:
    js += '''\n\nasync function loadNetworkProfiles() {\n  const data = await api("/api/network/profiles");\n  const select = $("networkProfile");\n  if (!select) return;\n  select.innerHTML = '<option value="">مباشر (إنترنت الجهاز)</option>';\n  for (const profile of data.profiles || []) {\n    const option = document.createElement("option");\n    option.value = profile.name;\n    option.textContent = `${profile.name} — ${profile.mode}${profile.proxy_server ? ` — ${profile.proxy_server}` : ""}`;\n    select.appendChild(option);\n  }\n}\nasync function saveNetworkProfile() {\n  const payload = {name: $("networkName").value.trim(), mode: $("networkMode").value, proxy_server: $("networkProxy").value.trim(), username: $("networkUsername").value.trim(), password: $("networkPassword").value, bypass: $("networkBypass").value.trim()};\n  const data = await api("/api/network/profiles", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload)});\n  $("networkResult").textContent = `تم حفظ ${data.profile.name}.`;\n  $("networkPassword").value = "";\n  await loadNetworkProfiles();\n  $("networkProfile").value = data.profile.name;\n}\nasync function testNetworkProfile() {\n  const name = $("networkProfile").value || $("networkName").value.trim();\n  const data = await api("/api/network/test", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({name})});\n  $("networkResult").textContent = `IP العام المرصود: ${data.observed_public_ip || "غير متاح"}`;\n}\nasync function bindNetworkToProject() {\n  const projectId = Number($("browserProject").value);\n  if (!projectId) throw new Error("اختر المشروع أولاً.");\n  const profile = $("networkProfile").value || null;\n  await api(`/api/projects/${projectId}/network${profile ? `?profile_name=${encodeURIComponent(profile)}` : ""}`, {method:"POST"});\n  $("networkResult").textContent = `تم ربط المشروع بمسار ${profile || "direct"}.`;\n}\n$("networkSaveBtn")?.addEventListener("click", async () => {try {await saveNetworkProfile(); showToast("تم حفظ ملف الشبكة", "success");} catch (e) {showToast(e.message, "error");}});\n$("networkTestBtn")?.addEventListener("click", async () => {try {await testNetworkProfile(); showToast("تم اختبار الشبكة", "success");} catch (e) {showToast(e.message, "error");}});\n$("networkBindBtn")?.addEventListener("click", async () => {try {await bindNetworkToProject(); showToast("تم ربط الشبكة", "success");} catch (e) {showToast(e.message, "error");}});\nloadNetworkProfiles().catch(() => {});\n'''
    app_js.write_text(js, encoding="utf-8")

print("engineering patch complete")
