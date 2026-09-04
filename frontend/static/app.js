"use strict";

/*
 * Autonomous Business Manager
 * Frontend controller
 *
 * Authentication:
 * - Uses HttpOnly "session" cookie from the backend.
 * - No API/session token is stored in localStorage or sessionStorage.
 */

const state = {
    projects: [],
    cards: [],
    events: [],
    selectedProjectId: null,
    currentSection: "dashboard",
    secretUnlocked: false,
};


// ============================================================
// Helpers
// ============================================================

function $(id) {
    return document.getElementById(id);
}


function escapeHtml(value) {
    if (value === null || value === undefined) {
        return "";
    }

    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}


function showToast(message, type = "info") {
    const toast = $("toast");

    if (!toast) {
        return;
    }

    toast.textContent = message;
    toast.className = `toast ${type} show`;

    window.clearTimeout(showToast.timer);

    showToast.timer = window.setTimeout(() => {
        toast.classList.remove("show");
    }, 3500);
}


async function api(url, options = {}) {
    const config = {
        credentials: "same-origin",
        ...options,
        headers: {
            ...(options.headers || {}),
        },
    };

    const response = await fetch(url, config);

    let data = null;

    try {
        data = await response.json();
    } catch {
        data = null;
    }

    if (response.status === 401) {
        showToast("انتهت الجلسة. سيتم إعادتك لتسجيل الدخول.", "error");

        window.setTimeout(() => {
            window.location.href = "/";
        }, 700);

        throw new Error("UNAUTHORIZED");
    }

    if (!response.ok) {
        const message =
            data?.detail ||
            data?.message ||
            `حدث خطأ HTTP ${response.status}`;

        throw new Error(message);
    }

    return data;
}


function formatDate(value) {
    if (!value) {
        return "غير معروف";
    }

    try {
        return new Date(value).toLocaleString("ar-YE", {
            dateStyle: "medium",
            timeStyle: "short",
        });
    } catch {
        return value;
    }
}


function statusLabel(status) {
    const labels = {
        queued: "في الانتظار",
        running: "قيد التنفيذ",
        needs_approval: "تحتاج موافقة",
        paused: "متوقفة مؤقتاً",
        stopped: "متوقفة",
        completed: "مكتملة",
        error: "خطأ",
        needs_reauth: "تحتاج إعادة تسجيل الدخول",
    };

    return labels[status] || status || "غير معروف";
}


function workflowLabel(type) {
    const labels = {
        assistant: "مساعد عام",
        api_account: "API / حساب",
        upload_design: "رفع / تصميم",
        code_api: "كود + API",
        dual: "سير عمل مزدوج",
    };

    return labels[type] || type || "غير محدد";
}


function statusClass(status) {
    const allowed = [
        "queued",
        "running",
        "needs_approval",
        "paused",
        "stopped",
        "completed",
        "error",
        "needs_reauth",
    ];

    return allowed.includes(status)
        ? status
        : "unknown";
}


function projectNameById(id) {
    const project = state.projects.find(
        item => Number(item.id) === Number(id)
    );

    return project ? project.name : `مشروع #${id}`;
}


// ============================================================
// Navigation
// ============================================================

function setupNavigation() {
    document.querySelectorAll(".nav-item").forEach(button => {
        button.addEventListener("click", () => {
            const section = button.dataset.section;

            if (!section) {
                return;
            }

            showSection(section);
        });
    });
}


function showSection(sectionName) {
    state.currentSection = sectionName;

    document.querySelectorAll(".nav-item").forEach(button => {
        button.classList.toggle(
            "active",
            button.dataset.section === sectionName
        );
    });

    document.querySelectorAll(".section").forEach(section => {
        section.classList.remove("active");
    });

    const target = $(`section-${sectionName}`);

    if (target) {
        target.classList.add("active");
    }

    const titles = {
        dashboard: [
            "الرئيسية",
            "أهلاً بك. النظام جاهز لإدارة أعمالك.",
        ],

        projects: [
            "المشاريع",
            "إدارة مشاريعك وسير العمل.",
        ],

        cards: [
            "بطاقات العمل",
            "المهام والموافقات وحالة التنفيذ.",
        ],

        browser: [
            "المتصفح الآلي",
            "إدارة جلسات المتصفح عبر Playwright.",
        ],

        code: [
            "تحليل الكود",
            "فحص ثابت قبل أي تشغيل أو سير عمل برمجي.",
        ],

        secrets: [
            "اللوحة السرية",
            "إدارة المعلومات الحساسة بشكل مشفر.",
        ],

        events: [
            "سجل الأحداث",
            "آخر أحداث النظام والتنبيهات.",
        ],
    };

    const title = titles[sectionName] || titles.dashboard;

    $("pageTitle").textContent = title[0];
    $("pageSubtitle").textContent = title[1];

    if (sectionName === "projects") {
        loadProjects();
    }

    if (sectionName === "cards") {
        loadCards();
    }

    if (sectionName === "events") {
        loadEvents();
    }

    if (sectionName === "browser") {
        populateProjectSelects();
    }

    if (sectionName === "secrets") {
        populateProjectSelects();
    }
}


// ============================================================
// Projects
// ============================================================

async function loadProjects() {
    try {
        const data = await api("/api/projects");

        state.projects = data.projects || [];

        renderProjects();
        populateProjectSelects();
        updateStats();

    } catch (error) {
        if (error.message !== "UNAUTHORIZED") {
            showToast(error.message, "error");
        }
    }
}


function renderProjects() {
    const container = $("projectsList");

    if (!container) {
        return;
    }

    if (!state.projects.length) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">▣</div>
                <h3>لا توجد مشاريع بعد</h3>
                <p>أنشئ أول مشروع لبدء العمل.</p>

                <button
                    class="primary-btn"
                    onclick="openProjectModal()"
                >
                    + إنشاء مشروع
                </button>
            </div>
        `;

        return;
    }

    container.innerHTML = state.projects.map(project => `
        <article class="project-card">

            <div class="project-card-top">

                <div class="project-icon">
                    ◈
                </div>

                <span class="status-pill ${statusClass(project.status)}">
                    ${escapeHtml(statusLabel(project.status))}
                </span>

            </div>

            <h3>
                ${escapeHtml(project.name)}
            </h3>

            <p>
                ${escapeHtml(
                    project.description || "لا يوجد وصف للمشروع."
                )}
            </p>

            <div class="project-meta">

                <span>
                    ${escapeHtml(workflowLabel(project.workflow_type))}
                </span>

                <span>
                    #${escapeHtml(project.id)}
                </span>

            </div>

            <button
                class="secondary-btn full-btn"
                onclick="selectProject(${Number(project.id)})"
            >
                فتح المشروع
            </button>

        </article>
    `).join("");
}


function populateProjectSelects() {
    const selects = [
        $("browserProject"),
        $("secretProject"),
    ];

    selects.forEach(select => {
        if (!select) {
            return;
        }

        const current = select.value;

        select.innerHTML = `
            <option value="">
                بدون مشروع
            </option>

            ${state.projects.map(project => `
                <option value="${Number(project.id)}">
                    ${escapeHtml(project.name)}
                </option>
            `).join("")}
        `;

        if (current) {
            select.value = current;
        }
    });
}


function selectProject(projectId) {
    state.selectedProjectId = Number(projectId);

    const project = state.projects.find(
        item => Number(item.id) === Number(projectId)
    );

    if (!project) {
        return;
    }

    showToast(
        `تم اختيار المشروع: ${project.name}`,
        "success"
    );

    $("chatInput").focus();
    showSection("dashboard");
}


function openProjectModal() {
    $("projectModal").classList.remove("hidden");

    $("projectName").value = "";
    $("projectDescription").value = "";
    $("projectWorkflow").value = "assistant";

    window.setTimeout(() => {
        $("projectName").focus();
    }, 50);
}


function closeProjectModal() {
    $("projectModal").classList.add("hidden");
}


async function createProject() {
    const name = $("projectName").value.trim();
    const description = $("projectDescription").value.trim();
    const workflowType = $("projectWorkflow").value;

    if (!name) {
        showToast("اكتب اسم المشروع أولاً.", "error");
        $("projectName").focus();
        return;
    }

    try {
        const data = await api("/api/projects", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                name,
                description,
                workflow_type: workflowType,
            }),
        });

        closeProjectModal();

        showToast(
            `تم إنشاء المشروع #${data.project_id}`,
            "success"
        );

        await loadProjects();

        state.selectedProjectId = Number(data.project_id);

    } catch (error) {
        if (error.message !== "UNAUTHORIZED") {
            showToast(error.message, "error");
        }
    }
}


// ============================================================
// Chat
// ============================================================

function addChatMessage(role, text) {
    const container = $("chatMessages");

    const element = document.createElement("div");

    element.className =
        `chat-message ${role === "user" ? "user" : "assistant"}`;

    if (role === "user") {
        element.innerHTML = `
            <div class="message-content">
                ${escapeHtml(text)}
            </div>

            <div class="message-avatar">
                أنت
            </div>
        `;
    } else {
        element.innerHTML = `
            <div class="message-avatar">
                AI
            </div>

            <div class="message-content">
                ${escapeHtml(text)}
            </div>
        `;
    }

    container.appendChild(element);

    container.scrollTop = container.scrollHeight;
}


function addTypingMessage() {
    const container = $("chatMessages");

    const element = document.createElement("div");

    element.id = "typingMessage";
    element.className = "chat-message assistant";

    element.innerHTML = `
        <div class="message-avatar">
            AI
        </div>

        <div class="message-content typing">
            <span></span>
            <span></span>
            <span></span>
        </div>
    `;

    container.appendChild(element);
    container.scrollTop = container.scrollHeight;
}


function removeTypingMessage() {
    $("typingMessage")?.remove();
}


async function sendChat() {
    const input = $("chatInput");
    const button = $("sendChatBtn");
    const workflow = $("chatWorkflow").value;

    const message = input.value.trim();

    if (!message) {
        return;
    }

    addChatMessage("user", message);

    input.value = "";
    input.disabled = true;
    button.disabled = true;

    addTypingMessage();

    try {
        const data = await api("/api/chat", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                message,
                project_id: state.selectedProjectId,
                workflow_type: workflow,
            }),
        });

        removeTypingMessage();

        const reply =
            data.reply ||
            data.message ||
            data.response ||
            "تم استلام الطلب.";

        addChatMessage("assistant", reply);

        if (data.work_card || data.card) {
            await loadCards();
        }

    } catch (error) {
        removeTypingMessage();

        if (error.message !== "UNAUTHORIZED") {
            addChatMessage(
                "assistant",
                `تعذر تنفيذ الطلب: ${error.message}`
            );
        }

    } finally {
        input.disabled = false;
        button.disabled = false;
        input.focus();
    }
}


// ============================================================
// Work Cards
// ============================================================

async function loadCards() {
    try {
        const query = state.selectedProjectId
            ? `?project_id=${encodeURIComponent(state.selectedProjectId)}`
            : "";

        const data = await api(`/api/work-cards${query}`);

        state.cards = data.cards || [];

        renderCards();
        renderDashboardCards();
        updateStats();

    } catch (error) {
        if (error.message !== "UNAUTHORIZED") {
            showToast(error.message, "error");
        }
    }
}


function cardActions(card) {
    const actions = [];

    if (
        card.status === "needs_approval" ||
        card.status === "paused"
    ) {
        actions.push(`
            <button
                class="primary-btn small-btn"
                onclick="cardAction(${Number(card.id)}, 'approve')"
            >
                موافقة
            </button>
        `);
    }

    if (
        card.status === "running" ||
        card.status === "queued"
    ) {
        actions.push(`
            <button
                class="secondary-btn small-btn"
                onclick="cardAction(${Number(card.id)}, 'pause')"
            >
                إيقاف مؤقت
            </button>
        `);
    }

    if (
        card.status !== "completed" &&
        card.status !== "stopped"
    ) {
        actions.push(`
            <button
                class="danger-btn small-btn"
                onclick="cardAction(${Number(card.id)}, 'stop')"
            >
                إيقاف
            </button>
        `);
    }

    if (card.status === "paused") {
        actions.push(`
            <button
                class="secondary-btn small-btn"
                onclick="cardAction(${Number(card.id)}, 'resume')"
            >
                استئناف
            </button>
        `);
    }

    return actions.join("");
}


function renderCards() {
    const container = $("allCardsList");

    if (!container) {
        return;
    }

    if (!state.cards.length) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">◉</div>
                <h3>لا توجد بطاقات عمل</h3>
                <p>
                    عند إنشاء مهام تحتاج متابعة ستظهر هنا.
                </p>
            </div>
        `;

        return;
    }

    container.innerHTML = state.cards.map(card => `
        <article class="work-card">

            <div class="work-card-header">

                <div>
                    <span class="card-number">
                        #${escapeHtml(card.id)}
                    </span>

                    <h3>
                        ${escapeHtml(
                            card.title ||
                            card.name ||
                            "مهمة بدون عنوان"
                        )}
                    </h3>
                </div>

                <span class="status-pill ${statusClass(card.status)}">
                    ${escapeHtml(statusLabel(card.status))}
                </span>

            </div>


            <p class="work-description">
                ${escapeHtml(
                    card.description ||
                    "لا يوجد وصف."
                )}
            </p>


            <div class="work-details">

                <div>
                    <small>المشروع</small>
                    <strong>
                        ${escapeHtml(
                            projectNameById(card.project_id)
                        )}
                    </strong>
                </div>

                <div>
                    <small>الخطوة التالية</small>
                    <strong>
                        ${escapeHtml(
                            card.next_step ||
                            "غير محددة"
                        )}
                    </strong>
                </div>

            </div>


            ${
                card.error_message
                    ? `
                        <div class="error-box">
                            ${escapeHtml(card.error_message)}
                        </div>
                    `
                    : ""
            }


            <div class="card-actions">
                ${cardActions(card)}
            </div>

        </article>
    `).join("");
}


function renderDashboardCards() {
    const container = $("dashboardCards");

    if (!container) {
        return;
    }

    const latest = state.cards.slice(0, 6);

    if (!latest.length) {
        container.innerHTML = `
            <div class="empty-small">
                لا توجد مهام حالياً.
            </div>
        `;

        return;
    }

    container.innerHTML = latest.map(card => `
        <div class="mini-card">

            <div>
                <strong>
                    ${escapeHtml(
                        card.title ||
                        card.name ||
                        `مهمة #${card.id}`
                    )}
                </strong>

                <small>
                    ${escapeHtml(
                        card.next_step ||
                        statusLabel(card.status)
                    )}
                </small>
            </div>

            <span class="status-pill ${statusClass(card.status)}">
                ${escapeHtml(statusLabel(card.status))}
            </span>

        </div>
    `).join("");
}


async function cardAction(cardId, action) {
    const labels = {
        approve: "الموافقة",
        reject: "الرفض",
        pause: "الإيقاف المؤقت",
        stop: "الإيقاف",
        resume: "الاستئناف",
    };

    const label = labels[action] || action;

    if (
        ["approve", "reject", "stop"].includes(action)
    ) {
        const confirmed = window.confirm(
            `هل تريد تنفيذ: ${label}؟`
        );

        if (!confirmed) {
            return;
        }
    }

    try {
        await api(`/api/work-cards/${cardId}/action`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                action,
            }),
        });

        showToast(
            `تم تنفيذ ${label}.`,
            "success"
        );

        await loadCards();

    } catch (error) {
        if (error.message !== "UNAUTHORIZED") {
            showToast(error.message, "error");
        }
    }
}


// ============================================================
// Statistics
// ============================================================

function updateStats() {
    $("statProjects").textContent =
        state.projects.length;

    $("statCards").textContent =
        state.cards.length;

    $("statRunning").textContent =
        state.cards.filter(
            card => card.status === "running"
        ).length;

    $("statApproval").textContent =
        state.cards.filter(
            card => card.status === "needs_approval"
        ).length;
}


// ============================================================
// Browser
// ============================================================

function getBrowserPayload() {
    const projectId = Number(
        $("browserProject").value
    );

    const siteName =
        $("browserSite").value.trim();

    const url =
        $("browserUrl").value.trim();

    if (!projectId) {
        throw new Error("اختر مشروعاً أولاً.");
    }

    if (!siteName) {
        throw new Error("أدخل اسم الموقع.");
    }

    if (!url) {
        throw new Error("أدخل الرابط.");
    }

    return {
        project_id: projectId,
        site_name: siteName,
        url,
    };
}


async function browserOpen() {
    try {
        const payload = getBrowserPayload();

        const result = await api("/api/browser/open", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify(payload),
        });

        renderBrowserOutput(result);

        showToast(
            "تم فتح جلسة المتصفح.",
            "success"
        );

    } catch (error) {
        if (error.message !== "UNAUTHORIZED") {
            showToast(error.message, "error");
            renderBrowserOutput({
                error: error.message,
            });
        }
    }
}


async function browserNavigate() {
    try {
        const payload = getBrowserPayload();

        const result = await api("/api/browser/navigate", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify(payload),
        });

        renderBrowserOutput(result);

    } catch (error) {
        if (error.message !== "UNAUTHORIZED") {
            showToast(error.message, "error");
            renderBrowserOutput({
                error: error.message,
            });
        }
    }
}


async function browserStatus() {
    try {
        const projectId = Number(
            $("browserProject").value
        );

        const siteName =
            $("browserSite").value.trim();

        if (!projectId || !siteName) {
            throw new Error(
                "اختر المشروع وأدخل اسم الموقع."
            );
        }

        const query =
            `?project_id=${encodeURIComponent(projectId)}` +
            `&site_name=${encodeURIComponent(siteName)}`;

        const result = await api(
            `/api/browser/status${query}`
        );

        renderBrowserOutput(result);

    } catch (error) {
        if (error.message !== "UNAUTHORIZED") {
            showToast(error.message, "error");
            renderBrowserOutput({
                error: error.message,
            });
        }
    }
}


async function browserClose() {
    try {
        const projectId = Number(
            $("browserProject").value
        );

        const siteName =
            $("browserSite").value.trim();

        if (!projectId || !siteName) {
            throw new Error(
                "اختر المشروع وأدخل اسم الموقع."
            );
        }

        const query =
            `?project_id=${encodeURIComponent(projectId)}` +
            `&site_name=${encodeURIComponent(siteName)}`;

        const result = await api(
            `/api/browser/close${query}`,
            {
                method: "POST",
            }
        );

        renderBrowserOutput(result);

        showToast(
            "تم إغلاق جلسة المتصفح.",
            "success"
        );

    } catch (error) {
        if (error.message !== "UNAUTHORIZED") {
            showToast(error.message, "error");
        }
    }
}


function renderBrowserOutput(data) {
    $("browserOutput").textContent =
        JSON.stringify(data, null, 2);
}


// ============================================================
// Code Analyzer
// ============================================================

async function analyzeCode() {
    const code =
        $("codeInput").value;

    const filename =
        $("codeFilename").value.trim() ||
        "uploaded_code.py";

    if (!code.trim()) {
        showToast(
            "ألصق الكود أولاً.",
            "error"
        );

        return;
    }

    const output = $("codeOutput");

    output.textContent = "جاري التحليل...";

    try {
        const result = await api(
            "/api/code/analyze",
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    code,
                    filename,
                }),
            }
        );

        output.textContent =
            JSON.stringify(result, null, 2);

        showToast(
            "اكتمل تحليل الكود.",
            "success"
        );

    } catch (error) {
        output.textContent =
            `خطأ: ${error.message}`;

        if (error.message !== "UNAUTHORIZED") {
            showToast(
                error.message,
                "error"
            );
        }
    }
}


// ============================================================
// Secret Panel
// ============================================================

async function verifySecretPanel() {
    const password =
        $("panelPassword").value;

    if (!password) {
        showToast(
            "أدخل كلمة مرور اللوحة.",
            "error"
        );

        return;
    }

    try {
        await api(
            "/api/panel/verify",
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    password,
                }),
            }
        );

        state.secretUnlocked = true;

        $("secretLock").classList.add("hidden");
        $("secretContent").classList.remove("hidden");

        $("panelPassword").value = "";

        showToast(
            "تم فتح اللوحة السرية.",
            "success"
        );

    } catch (error) {
        if (error.message !== "UNAUTHORIZED") {
            showToast(
                error.message,
                "error"
            );
        }
    }
}


async function saveSecret() {
    if (!state.secretUnlocked) {
        showToast(
            "افتح اللوحة السرية أولاً.",
            "error"
        );

        return;
    }

    const name =
        $("secretName").value.trim();

    const value =
        $("secretValue").value;

    const projectValue =
        $("secretProject").value;

    const projectId =
        projectValue
            ? Number(projectValue)
            : null;

    if (!name) {
        showToast(
            "أدخل اسم السر.",
            "error"
        );

        return;
    }

    if (!value) {
        showToast(
            "أدخل قيمة السر.",
            "error"
        );

        return;
    }

    try {
        const result = await api(
            "/api/secrets",
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    project_id: projectId,
                    name,
                    value,
                }),
            }
        );

        $("secretValue").value = "";

        $("secretMessage").textContent =
            `تم الحفظ المشفر. رقم السجل: ${result.secret_id}`;

        showToast(
            "تم حفظ السر بشكل مشفر.",
            "success"
        );

    } catch (error) {
        if (error.message !== "UNAUTHORIZED") {
            showToast(
                error.message,
                "error"
            );
        }
    }
}


// ============================================================
// Events
// ============================================================

async function loadEvents() {
    try {
        const data = await api(
            "/api/events?limit=150"
        );

        state.events =
            data.events || [];

        renderEvents();

    } catch (error) {
        if (error.message !== "UNAUTHORIZED") {
            showToast(
                error.message,
                "error"
            );
        }
    }
}


function eventLabel(type) {
    const labels = {
        info: "معلومة",
        warning: "تحذير",
        error: "خطأ",
        approval_required: "موافقة مطلوبة",
        session_expired: "انتهاء جلسة",
        connection_lost: "انقطاع اتصال",
        connection_restored: "عودة الاتصال",
        security: "أمان",
    };

    return labels[type] || type || "حدث";
}


function renderEvents() {
    const container =
        $("eventsList");

    if (!container) {
        return;
    }

    if (!state.events.length) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">◷</div>
                <h3>لا توجد أحداث</h3>
                <p>سجل النظام فارغ حالياً.</p>
            </div>
        `;

        return;
    }

    container.innerHTML =
        state.events.map(event => `
            <div class="event-item">

                <div class="event-icon">
                    ◈
                </div>

                <div class="event-main">

                    <div class="event-top">

                        <strong>
                            ${escapeHtml(
                                eventLabel(event.event_type)
                            )}
                        </strong>

                        <time>
                            ${escapeHtml(
                                formatDate(event.created_at)
                            )}
                        </time>

                    </div>

                    <p>
                        ${escapeHtml(
                            event.message ||
                            event.description ||
                            "حدث بدون تفاصيل."
                        )}
                    </p>

                    ${
                        event.project_id
                            ? `
                                <small>
                                    المشروع:
                                    ${escapeHtml(
                                        projectNameById(
                                            event.project_id
                                        )
                                    )}
                                </small>
                            `
                            : ""
                    }

                </div>

            </div>
        `).join("");
}


// ============================================================
// Connection status
// ============================================================

async function checkConnection() {
    try {
        const response =
            await fetch(
                "/health",
                {
                    credentials: "same-origin",
                    cache: "no-store",
                }
            );

        if (!response.ok) {
            throw new Error();
        }

        setConnectionState(true);

    } catch {
        setConnectionState(false);
    }
}


function setConnectionState(online) {
    const dot =
        $("connectionDot");

    const text =
        $("connectionText");

    if (!dot || !text) {
        return;
    }

    dot.classList.toggle(
        "online",
        online
    );

    dot.classList.toggle(
        "offline",
        !online
    );

    text.textContent =
        online
            ? "متصل"
            : "غير متصل";
}


// ============================================================
// Logout
// ============================================================

async function logout() {
    try {
        await api(
            "/api/logout",
            {
                method: "POST",
            }
        );
    } catch {
        // Even if the server is unavailable,
        // redirecting to login is safer.
    }

    window.location.href = "/";
}


// ============================================================
// Initial loading
// ============================================================

async function loadDashboard() {
    await loadProjects();
    await loadCards();
    await loadEvents();

    updateStats();
    populateProjectSelects();
}


function setupEventListeners() {

    // Navigation
    setupNavigation();


    // Project modal
    $("newProjectBtn")
        ?.addEventListener(
            "click",
            openProjectModal
        );

    $("closeProjectModal")
        ?.addEventListener(
            "click",
            closeProjectModal
        );

    $("cancelProjectBtn")
        ?.addEventListener(
            "click",
            closeProjectModal
        );

    $("createProjectBtn")
        ?.addEventListener(
            "click",
            createProject
        );


    // Chat
    $("sendChatBtn")
        ?.addEventListener(
            "click",
            sendChat
        );

    $("chatInput")
        ?.addEventListener(
            "keydown",
            event => {
                if (
                    event.key === "Enter" &&
                    !event.shiftKey
                ) {
                    event.preventDefault();
                    sendChat();
                }
            }
        );


    // Refresh
    $("refreshBtn")
        ?.addEventListener(
            "click",
            async () => {
                await loadDashboard();

                showToast(
                    "تم تحديث البيانات.",
                    "success"
                );
            }
        );


    // Logout
    $("logoutBtn")
        ?.addEventListener(
            "click",
            logout
        );


    // Browser
    $("browserOpenBtn")
        ?.addEventListener(
            "click",
            browserOpen
        );

    $("browserNavigateBtn")
        ?.addEventListener(
            "click",
            browserNavigate
        );

    $("browserStatusBtn")
        ?.addEventListener(
            "click",
            browserStatus
        );

    $("browserCloseBtn")
        ?.addEventListener(
            "click",
            browserClose
        );


    // Code
    $("analyzeCodeBtn")
        ?.addEventListener(
            "click",
            analyzeCode
        );


    // Secret panel
    $("verifyPanelBtn")
        ?.addEventListener(
            "click",
            verifySecretPanel
        );

    $("saveSecretBtn")
        ?.addEventListener(
            "click",
            saveSecret
        );


    // Events
    $("refreshEventsBtn")
        ?.addEventListener(
            "click",
            loadEvents
        );


    // Close modal by clicking outside
    $("projectModal")
        ?.addEventListener(
            "click",
            event => {
                if (
                    event.target ===
                    $("projectModal")
                ) {
                    closeProjectModal();
                }
            }
        );


    // Escape closes modal
    document.addEventListener(
        "keydown",
        event => {
            if (
                event.key === "Escape" &&
                !$("projectModal")
                    .classList.contains("hidden")
            ) {
                closeProjectModal();
            }
        }
    );


    // Browser project select
    $("browserProject")
        ?.addEventListener(
            "change",
            event => {
                state.selectedProjectId =
                    event.target.value
                        ? Number(event.target.value)
                        : null;
            }
        );
}


// ============================================================
// Start
// ============================================================

document.addEventListener(
    "DOMContentLoaded",
    async () => {

        setupEventListeners();

        await loadDashboard();

        await checkConnection();

        window.setInterval(
            checkConnection,
            15000
        );

        window.setInterval(
            async () => {
                if (
                    state.currentSection ===
                    "dashboard"
                ) {
                    await loadCards();
                }
            },
            10000
        );
    }
);


// ============================================================
// Global functions used by HTML
// ============================================================

window.openProjectModal =
    openProjectModal;

window.closeProjectModal =
    closeProjectModal;

window.selectProject =
    selectProject;

window.cardAction =
    cardAction;
