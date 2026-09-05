"use strict";

const state = {
  projects: [],
  cards: [],
  events: [],
  selectedProjectId: null,
  browserProjectId: null,
};

const $ = (id) => document.getElementById(id);

async function api(url, options = {}) {
  const response = await fetch(url, {
    credentials: "same-origin",
    ...options,
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}),
    },
  });

  if (response.status === 401) {
    window.location.href = "/";
    throw new Error("انتهت الجلسة.");
  }

  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    throw new Error(data.detail || data.message || "حدث خطأ.");
  }

  return data;
}

function showToast(message, type = "info") {
  const toast = $("toast");

  if (!toast) return;

  toast.textContent = message;
  toast.className = `toast show ${type}`;

  window.clearTimeout(showToast.timer);

  showToast.timer = window.setTimeout(() => {
    toast.className = "toast";
  }, 3500);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
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
    assistant: "مساعد ذكي",
    api_account: "API / حساب",
    upload_design: "رفع / تصميم / POD",
    code_api: "كود + API",
    dual: "سير عمل مزدوج",
  };

  return labels[type] || type || "غير محدد";
}

function formatDate(value) {
  if (!value) return "";

  try {
    return new Date(value).toLocaleString("ar");
  } catch {
    return String(value);
  }
}

async function loadProjects() {
  const data = await api("/api/projects");

  state.projects = Array.isArray(data)
    ? data
    : data.projects || [];

  renderProjects();
  renderProjectSelectors();

  $("projectsCount").textContent = state.projects.length;
}

function renderProjects() {
  const container = $("projectsList");

  if (!container) return;

  if (!state.projects.length) {
    container.innerHTML = `
      <div class="empty-state">
        لا توجد مشاريع حالياً.
      </div>
    `;
    return;
  }

  container.innerHTML = state.projects.map((project) => `
    <div class="project-item">

      <div class="project-main">
        <strong>${escapeHtml(project.name)}</strong>

        <span>
          ${escapeHtml(workflowLabel(project.workflow_type))}
        </span>

        <p>
          ${escapeHtml(project.description || "بدون وصف")}
        </p>
      </div>

      <div class="project-actions">
        <button
          class="secondary-btn small-btn"
          data-browser-project="${project.id}"
        >
          المتصفح
        </button>
      </div>

    </div>
  `).join("");

  container
    .querySelectorAll("[data-browser-project]")
    .forEach((button) => {
      button.addEventListener("click", () => {
        const id = Number(button.dataset.browserProject);

        state.selectedProjectId = id;

        const select = $("browserProject");

        if (select) {
          select.value = String(id);
        }

        $("browserUrl")?.focus();
      });
    });
}

function renderProjectSelectors() {
  const select = $("browserProject");

  if (!select) return;

  const current = select.value;

  select.innerHTML = `
    <option value="">اختر المشروع</option>
    ${state.projects.map((project) => `
      <option value="${project.id}">
        ${escapeHtml(project.name)}
      </option>
    `).join("")}
  `;

  if (
    current &&
    state.projects.some(
      (project) => String(project.id) === current
    )
  ) {
    select.value = current;
  }
}

async function loadCards() {
  const data = await api("/api/work-cards");

  state.cards = Array.isArray(data)
    ? data
    : data.cards || [];

  renderCards();
  updateStats();
}

function renderCards() {
  const container = $("workCardsList");

  if (!container) return;

  if (!state.cards.length) {
    container.innerHTML = `
      <div class="empty-state">
        لا توجد بطاقات عمل.
      </div>
    `;
    return;
  }

  container.innerHTML = state.cards.map((card) => {
    const id = card.id;

    return `
      <article class="work-card">

        <div class="work-card-header">

          <div>
            <h3>
              ${escapeHtml(card.title || `مهمة #${id}`)}
            </h3>

            <span class="status-badge status-${escapeHtml(card.status)}">
              ${escapeHtml(statusLabel(card.status))}
            </span>
          </div>

          <span class="card-id">
            #${id}
          </span>

        </div>

        <p>
          ${escapeHtml(card.description || "بدون وصف")}
        </p>

        ${
          card.error_message
            ? `
              <div class="error-box">
                ${escapeHtml(card.error_message)}
              </div>
            `
            : ""
        }

        ${
          card.next_step
            ? `
              <div class="next-step">
                <strong>الخطوة التالية:</strong>
                ${escapeHtml(card.next_step)}
              </div>
            `
            : ""
        }

        <div class="button-row">

          ${
            card.status === "needs_approval" ||
            card.status === "paused"
              ? `
                <button
                  class="primary-btn small-btn"
                  data-card-action="approve"
                  data-card-id="${id}"
                >
                  موافقة / استئناف
                </button>
              `
              : ""
          }

          ${
            card.status === "needs_approval" ||
            card.status === "queued" ||
            card.status === "running" ||
            card.status === "paused"
              ? `
                <button
                  class="secondary-btn small-btn"
                  data-card-action="pause"
                  data-card-id="${id}"
                >
                  إيقاف مؤقت
                </button>

                <button
                  class="danger-btn small-btn"
                  data-card-action="stop"
                  data-card-id="${id}"
                >
                  إيقاف
                </button>
              `
              : ""
          }

        </div>

      </article>
    `;
  }).join("");

  container
    .querySelectorAll("[data-card-action]")
    .forEach((button) => {
      button.addEventListener("click", async () => {
        const id = Number(button.dataset.cardId);
        const action = button.dataset.cardAction;

        await performCardAction(id, action);
      });
    });
}

async function performCardAction(id, action) {
  try {
    await api(`/api/work-cards/${id}/action`, {
      method: "POST",
      body: JSON.stringify({ action }),
    });

    showToast("تم تحديث بطاقة العمل.", "success");

    await Promise.all([
      loadCards(),
      loadEvents(),
    ]);
  } catch (error) {
    showToast(error.message, "error");
  }
}

function updateStats() {
  $("cardsCount").textContent = state.cards.length;

  $("runningCount").textContent =
    state.cards.filter(
      (card) => card.status === "running"
    ).length;

  $("approvalCount").textContent =
    state.cards.filter(
      (card) => card.status === "needs_approval"
    ).length;
}

async function loadEvents() {
  const data = await api("/api/events");

  state.events = Array.isArray(data)
    ? data
    : data.events || [];

  renderEvents();
}

function renderEvents() {
  const container = $("eventsList");

  if (!container) return;

  if (!state.events.length) {
    container.innerHTML = `
      <div class="empty-state">
        لا توجد أحداث.
      </div>
    `;
    return;
  }

  container.innerHTML = state.events
    .slice(0, 50)
    .map((event) => `
      <div class="event-item">

        <div class="event-type">
          ${escapeHtml(event.event_type || event.type || "info")}
        </div>

        <div class="event-message">
          ${escapeHtml(event.message || event.description || "")}
        </div>

        <time>
          ${escapeHtml(
            formatDate(event.created_at || event.timestamp)
          )}
        </time>

      </div>
    `)
    .join("");
}

async function sendChat(message) {
  const data = await api("/api/chat", {
    method: "POST",
    body: JSON.stringify({
      message,
    }),
  });

  return data;
}

function addChatMessage(role, content) {
  const container = $("chatMessages");

  if (!container) return;

  const message = document.createElement("div");

  message.className = `chat-message ${role}`;

  const inner = document.createElement("div");

  inner.className = "message-content";
  inner.textContent = content;

  message.appendChild(inner);
  container.appendChild(message);

  container.scrollTop = container.scrollHeight;
}

async function handleChat(event) {
  event.preventDefault();

  const input = $("chatInput");
  const button = $("chatSendBtn");

  const message = input.value.trim();

  if (!message) return;

  addChatMessage("user", message);

  input.value = "";
  input.disabled = true;
  button.disabled = true;
  button.textContent = "جاري المعالجة...";

  try {
    const data = await sendChat(message);

    const reply =
      data.reply ||
      data.message ||
      data.response ||
      "تم استلام طلبك.";

    addChatMessage("assistant", reply);

    await Promise.all([
      loadCards(),
      loadEvents(),
      loadProjects(),
    ]);

  } catch (error) {
    addChatMessage(
      "assistant",
      `تعذر تنفيذ الطلب: ${error.message}`
    );
  } finally {
    input.disabled = false;
    button.disabled = false;
    button.textContent = "إرسال";
    input.focus();
  }
}

async function createProject(event) {
  event.preventDefault();

  const name = $("projectName").value.trim();
  const description = $("projectDescription").value.trim();
  const workflowType = $("projectWorkflow").value;

  if (!name) {
    showToast("اكتب اسم المشروع.", "error");
    return;
  }

  try {
    await api("/api/projects", {
      method: "POST",
      body: JSON.stringify({
        name,
        description,
        workflow_type: workflowType,
      }),
    });

    closeProjectModal();

    $("projectForm").reset();

    showToast("تم إنشاء المشروع بنجاح.", "success");

    await loadProjects();

  } catch (error) {
    showToast(error.message, "error");
  }
}

function openProjectModal() {
  $("projectModal")?.classList.remove("hidden");
  $("projectName")?.focus();
}

function closeProjectModal() {
  $("projectModal")?.classList.add("hidden");
}

function selectedBrowserProject() {
  const value = $("browserProject")?.value;

  if (!value) {
    throw new Error("اختر مشروعاً أولاً.");
  }

  return Number(value);
}

async function browserOpen() {
  try {
    const projectId = selectedBrowserProject();
    const url = $("browserUrl").value.trim();

    if (!url) {
      throw new Error("أدخل رابط الموقع.");
    }

    state.browserProjectId = projectId;

    const data = await api("/api/browser/open", {
      method: "POST",
      body: JSON.stringify({
        project_id: projectId,
        site: url,
      }),
    });

    renderBrowserResult(data);

    if (data.session_expired) {
      showToast(
        "الجلسة تحتاج إلى إعادة تسجيل الدخول.",
        "error"
      );
    } else {
      showToast("تم فتح الموقع.", "success");
    }

  } catch (error) {
    showToast(error.message, "error");
    renderBrowserResult({
      error: error.message,
    });
  }
}

async function browserNavigate() {
  try {
    const projectId = selectedBrowserProject();
    const url = $("browserUrl").value.trim();

    if (!url) {
      throw new Error("أدخل الرابط المطلوب.");
    }

    const data = await api("/api/browser/navigate", {
      method: "POST",
      body: JSON.stringify({
        project_id: projectId,
        url,
      }),
    });

    renderBrowserResult(data);

    if (data.session_expired) {
      showToast(
        "انتهت جلسة الموقع. يلزم تسجيل الدخول يدوياً.",
        "error"
      );
    } else {
      showToast("تم الانتقال.", "success");
    }

  } catch (error) {
    showToast(error.message, "error");
  }
}

async function browserStatus() {
  try {
    const projectId = selectedBrowserProject();

    const data = await api(
      `/api/browser/status/${projectId}`
    );

    renderBrowserResult(data);

  } catch (error) {
    showToast(error.message, "error");
  }
}

async function browserClose() {
  try {
    const projectId = selectedBrowserProject();

    await api("/api/browser/close", {
      method: "POST",
      body: JSON.stringify({
        project_id: projectId,
      }),
    });

    renderBrowserResult({
      status: "closed",
      url: null,
    });

    showToast("تم إغلاق جلسة المتصفح.", "success");

  } catch (error) {
    showToast(error.message, "error");
  }
}

function renderBrowserResult(data) {
  const box = $("browserResult");

  if (!box) return;

  if (data.error) {
    box.textContent = data.error;
    return;
  }

  const status =
    data.status ||
    "غير معروف";

  const url =
    data.url ||
    "لا يوجد رابط";

  const session =
    data.session_expired
      ? "الجلسة تحتاج إعادة تسجيل الدخول"
      : "الجلسة سليمة";

  box.innerHTML = `
    <strong>الحالة:</strong>
    ${escapeHtml(status)}
    <br>

    <strong>الرابط:</strong>
    ${escapeHtml(url)}
    <br>

    <strong>الجلسة:</strong>
    ${escapeHtml(session)}
  `;
}

async function analyzeCode() {
  const code = $("codeInput").value;

  if (!code.trim()) {
    showToast("ألصق الكود أولاً.", "error");
    return;
  }

  const result = $("codeResult");

  result.textContent = "جاري تحليل الكود...";

  try {
    const data = await api("/api/code/analyze", {
      method: "POST",
      body: JSON.stringify({
        code,
      }),
    });

    renderCodeResult(data);

  } catch (error) {
    result.textContent = error.message;
    showToast(error.message, "error");
  }
}

function renderCodeResult(data) {
  const result = $("codeResult");

  const findings =
    data.findings ||
    data.issues ||
    [];

  const safe =
    data.safe ??
    data.is_safe ??
    (findings.length === 0);

  if (!findings.length) {
    result.innerHTML = `
      <strong>
        ${safe ? "لم يتم العثور على مؤشرات خطرة." : "يحتاج الكود إلى مراجعة."}
      </strong>
    `;
    return;
  }

  result.innerHTML = `
    <strong>نتائج التحليل:</strong>

    <ul>
      ${findings.map((finding) => `
        <li>
          ${escapeHtml(
            typeof finding === "string"
              ? finding
              : JSON.stringify(finding)
          )}
        </li>
      `).join("")}
    </ul>
  `;
}

async function verifySecrets(event) {
  event.preventDefault();

  const password =
    $("secretPanelPassword").value;

  if (!password) return;

  const result = $("secretResult");

  result.textContent =
    "جاري التحقق...";

  try {
    const data = await api(
      "/api/secrets/panel/verify",
      {
        method: "POST",
        body: JSON.stringify({
          password,
        }),
      }
    );

    result.textContent =
      data.message ||
      "تم التحقق من لوحة الأسرار.";

    showToast(
      "تم التحقق بنجاح.",
      "success"
    );

  } catch (error) {
    result.textContent =
      error.message;

    showToast(
      error.message,
      "error"
    );
  }
}

async function logout() {
  try {
    await api("/api/logout", {
      method: "POST",
    });
  } catch {
    // الانتقال لصفحة الدخول حتى لو انتهت الجلسة.
  }

  window.location.href = "/";
}

async function checkHealth() {
  try {
    const response = await fetch(
      "/health",
      {
        credentials: "same-origin",
      }
    );

    if (!response.ok) {
      throw new Error();
    }

    const data = await response.json();

    const status = $("connectionStatus");

    if (!status) return;

    if (data.status === "ok") {
      status.textContent =
        "● النظام متصل";
      status.className =
        "online";
    } else {
      status.textContent =
        "● النظام يحتاج مراجعة";
      status.className =
        "warning";
    }

  } catch {
    const status = $("connectionStatus");

    if (!status) return;

    status.textContent =
      "● تعذر الاتصال بالخادم";

    status.className =
      "offline";
  }
}

function bindEvents() {
  $("chatForm")
    ?.addEventListener(
      "submit",
      handleChat
    );

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

  $("projectForm")
    ?.addEventListener(
      "submit",
      createProject
    );

  $("logoutBtn")
    ?.addEventListener(
      "click",
      logout
    );

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

  $("analyzeCodeBtn")
    ?.addEventListener(
      "click",
      analyzeCode
    );

  $("secretForm")
    ?.addEventListener(
      "submit",
      verifySecrets
    );

  $("browserProject")
    ?.addEventListener(
      "change",
      (event) => {
        state.selectedProjectId =
          Number(event.target.value) || null;
      }
    );

  $("projectModal")
    ?.addEventListener(
      "click",
      (event) => {
        if (
          event.target === $("projectModal")
        ) {
          closeProjectModal();
        }
      }
    );
}

async function initialize() {
  bindEvents();

  try {
    await Promise.all([
      loadProjects(),
      loadCards(),
      loadEvents(),
      checkHealth(),
    ]);
  } catch (error) {
    showToast(
      error.message ||
      "تعذر تحميل بيانات لوحة التحكم.",
      "error"
    );
  }

  window.setInterval(
    checkHealth,
    30000
  );

  window.setInterval(
    async () => {
      try {
        await Promise.all([
          loadCards(),
          loadEvents(),
        ]);
      } catch {
        // يتم التعامل مع الخطأ عبر الجلسة والواجهة.
      }
    },
    15000
  );
}

document.addEventListener(
  "DOMContentLoaded",
  initialize
);
