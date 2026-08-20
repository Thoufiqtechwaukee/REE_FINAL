const state = {
  resumeId: null,
  skills: [],
};

const API_BASE = window.API_BASE_URL || "";

const $ = (id) => document.getElementById(id);

function showSection(id) {
  for (const s of ["uploadSection", "processingSection", "verificationSection", "evaluatingSection", "resultsSection"]) {
    $(s).classList.toggle("d-none", s !== id);
  }
}

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ---------- Upload ----------

const dropZone = $("dropZone");
const fileInput = $("fileInput");
let selectedFile = null;

$("selectFileBtn").addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", (e) => handleFileSelect(e.target.files[0]));

["dragenter", "dragover"].forEach((evt) =>
  dropZone.addEventListener(evt, (e) => {
    e.preventDefault();
    dropZone.classList.add("dragover");
  })
);
["dragleave", "drop"].forEach((evt) =>
  dropZone.addEventListener(evt, (e) => {
    e.preventDefault();
    dropZone.classList.remove("dragover");
  })
);
dropZone.addEventListener("drop", (e) => {
  const file = e.dataTransfer.files[0];
  if (file) handleFileSelect(file);
});

function handleFileSelect(file) {
  if (!file || file.type !== "application/pdf") {
    alert("Please select a PDF file.");
    return;
  }
  selectedFile = file;
  $("fileName").textContent = file.name;
  $("fileInfo").classList.remove("d-none");
}

$("analyzeBtn").addEventListener("click", startAnalysis);

async function startAnalysis() {
  if (!selectedFile) return;
  showSection("processingSection");
  animateStages();

  const formData = new FormData();
  formData.append("file", selectedFile);

  try {
    const resp = await fetch(`${API_BASE}/api/resumes/upload`, { method: "POST", body: formData });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new Error(err.detail || "Upload failed");
    }
    const data = await resp.json();
    state.resumeId = data.resume.resume_id;
    state.skills = data.skills;
    completeStages();
    setTimeout(() => renderSkillVerification(), 300);
  } catch (err) {
    alert("Analysis failed: " + err.message);
    showSection("uploadSection");
  }
}

function animateStages() {
  ["stage1", "stage2", "stage3", "stage4"].forEach((id) => {
    $(id).classList.remove("completed", "active", "failed");
    $(id).querySelector(".stage-icon").innerHTML = "&#9675;";
  });
  setTimeout(() => setStage(1, "active"), 100);
  setTimeout(() => setStage(1, "completed"), 600);
  setTimeout(() => setStage(2, "active"), 700);
  setTimeout(() => setStage(2, "completed"), 1200);
  setTimeout(() => setStage(3, "active"), 1300);
}

function completeStages() {
  setStage(3, "completed");
  setStage(4, "completed");
}

function setStage(n, status) {
  const el = $("stage" + n);
  if (!el) return;
  el.classList.remove("completed", "active");
  el.classList.add(status);
  el.querySelector(".stage-icon").innerHTML = status === "completed" ? "&#10003;" : status === "active" ? "&#9679;" : "&#9675;";
}

// ---------- Skill verification ----------

function renderSkillVerification() {
  showSection("verificationSection");
  const grid = $("skillChipGrid");
  grid.innerHTML = state.skills
    .map((s) => {
      const statusClass = s.verification_status === "USER_REMOVED" ? "removed" : s.verification_status === "USER_CORRECTED" ? "corrected" : "";
      const normalizedNote =
        s.detected_text.toLowerCase() !== s.canonical_name.toLowerCase()
          ? `<div class="skill-meta">Detected: "${escapeHtml(s.detected_text)}"</div>`
          : "";
      return `
      <div class="skill-chip ${statusClass}" data-id="${s.resume_skill_id}">
        <div class="d-flex justify-content-between align-items-start">
          <div>
            <div class="skill-name">${escapeHtml(s.canonical_name)}</div>
            ${normalizedNote}
            <div class="skill-meta">${Math.round(s.confidence * 100)}% confidence &middot; ${escapeHtml(s.detection_method)}</div>
          </div>
          <div class="skill-actions">
            <button class="action-confirm ${s.verification_status.startsWith("USER_CONFIRMED") || s.verification_status === "AUTO_CONFIRMED" ? "active" : ""}" title="Confirm" onclick="confirmSkill('${s.resume_skill_id}')"><i class="fa-solid fa-check"></i></button>
            <button class="action-correct" title="Correct" onclick="openCorrectSkill('${s.resume_skill_id}')"><i class="fa-solid fa-pen"></i></button>
            <button class="action-remove" title="Remove" onclick="removeSkill('${s.resume_skill_id}')"><i class="fa-solid fa-xmark"></i></button>
          </div>
        </div>
        <div class="correct-panel d-none mt-2" id="correct-panel-${s.resume_skill_id}">
          <input type="text" class="form-control form-control-sm mb-1" placeholder="Search catalog..." oninput="searchCatalog('${s.resume_skill_id}', this.value)">
          <div class="correct-results small"></div>
        </div>
      </div>`;
    })
    .join("");
  updateFreezeButtonLabel();
}

function updateFreezeButtonLabel() {
  const anyModified = state.skills.some((s) => s.user_modified);
  $("freezeSkillsBtn").textContent = anyModified ? "Save Changes & Start Evaluation" : "Confirm & Start Evaluation";
}

async function confirmSkill(id) {
  const resp = await fetch(`${API_BASE}/api/resumes/${state.resumeId}/skills/${id}/confirm`, { method: "POST" });
  const updated = await resp.json();
  applySkillUpdate(updated);
}

async function removeSkill(id) {
  const resp = await fetch(`${API_BASE}/api/resumes/${state.resumeId}/skills/${id}/remove`, { method: "POST" });
  const updated = await resp.json();
  applySkillUpdate(updated);
}

function openCorrectSkill(id) {
  const panel = $("correct-panel-" + id);
  panel.classList.toggle("d-none");
}

let searchDebounce = null;
function searchCatalog(id, query) {
  clearTimeout(searchDebounce);
  if (!query || query.trim().length < 2) return;
  searchDebounce = setTimeout(async () => {
    const resp = await fetch(`${API_BASE}/api/resumes/${state.resumeId}/skills/catalog-search?q=${encodeURIComponent(query)}`);
    const options = await resp.json();
    const container = document.querySelector(`#correct-panel-${id} .correct-results`);
    container.innerHTML = options
      .map((o) => `<div class="p-1 border-bottom" style="cursor:pointer" onclick="applyCorrection('${id}', '${o.skill_id}')">${escapeHtml(o.canonical_name)}</div>`)
      .join("") || '<div class="text-muted">No matches</div>';
  }, 250);
}

async function applyCorrection(id, newSkillId) {
  const resp = await fetch(`${API_BASE}/api/resumes/${state.resumeId}/skills/${id}/correct`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ new_skill_id: newSkillId }),
  });
  const updated = await resp.json();
  applySkillUpdate(updated);
}

function applySkillUpdate(updated) {
  const idx = state.skills.findIndex((s) => s.resume_skill_id === updated.resume_skill_id);
  if (idx >= 0) state.skills[idx] = updated;
  renderSkillVerification();
}

$("freezeSkillsBtn").addEventListener("click", async () => {
  const resp = await fetch(`${API_BASE}/api/resumes/${state.resumeId}/skills/freeze`, { method: "POST" });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    alert("Could not start evaluation: " + err.detail);
    return;
  }
  showSection("evaluatingSection");
  await runEvaluation();
});

// ---------- Evaluation ----------

async function runEvaluation() {
  try {
    const resp = await fetch(`${API_BASE}/api/resumes/${state.resumeId}/evaluation`, { method: "POST" });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new Error(err.detail || "Evaluation failed");
    }
    const data = await resp.json();
    renderResults(data);
  } catch (err) {
    alert("Evaluation failed: " + err.message);
    showSection("verificationSection");
  }
}

function renderResults(data) {
  showSection("resultsSection");
  $("totalScoreValue").textContent = Math.round(data.scores.total);
  $("expScore").textContent = Math.round(data.scores.experience);
  $("evidScore").textContent = Math.round(data.scores.evidence);
  $("growthScore").textContent = Math.round(data.scores.growth);
  $("compScore").textContent = Math.round(data.scores.completeness);

  $("expSubScores").innerHTML = data.sub_scores.experience
    .map((s) => `<div class="d-flex justify-content-between"><span>${escapeHtml(s.sub_dimension.replace(/_/g, " "))}</span><span>${s.points}/${s.points_max}</span></div>`)
    .join("");
  $("experienceRecommendation").textContent =
    data.recommendations.find((r) => r.category === "EXPERIENCE")?.description || "No specific experience recommendations.";

  const evidenceBody = $("evidenceTableBody");
  evidenceBody.innerHTML = "";
  for (const skillName of Object.keys(groupEvidence(data))) {
    // populated below via renderEvidenceTable
  }
  renderEvidenceTable(data);

  renderGrowth(data);
  renderCompleteness(data);

  $("overallAssessment").textContent = data.overall_assessment || "";
  $("strengthsList").innerHTML = (data.strengths || []).map((s) => `<li>${escapeHtml(s)}</li>`).join("") || "<li class='text-muted'>None noted</li>";
  $("weaknessesList").innerHTML = (data.weaknesses || []).map((s) => `<li>${escapeHtml(s)}</li>`).join("") || "<li class='text-muted'>None noted</li>";

  $("recommendationsList").innerHTML = (data.recommendations || [])
    .map((r) => `<div class="badge-beige-tag d-block mb-1"><strong>${escapeHtml(r.title)}</strong>: ${escapeHtml(r.description)}</div>`)
    .join("");
}

function groupEvidence(data) {
  return {};
}

function renderEvidenceTable(data) {
  const rows = data.sub_scores.evidence || [];
  const evidenceBody = $("evidenceTableBody");
  if (!rows.length) {
    evidenceBody.innerHTML = '<tr><td colspan="3" class="text-muted small">No evidence sub-scores available.</td></tr>';
    return;
  }
  evidenceBody.innerHTML = rows
    .map((s) => {
      const badge =
        s.sub_dimension === "core_skill_evidence"
          ? '<span class="badge-strong">Core Evidence</span>'
          : s.sub_dimension === "supporting_evidence"
          ? '<span class="badge-moderate">Supporting</span>'
          : '<span class="badge-none">Project Bonus</span>';
      return `<tr><td class="fw-bold">${escapeHtml(s.sub_dimension.replace(/_/g, " "))}</td><td class="text-secondary small">${escapeHtml(s.explanation || "")}</td><td>${badge}</td></tr>`;
    })
    .join("");
}

function renderGrowth(data) {
  const dims = data.sub_scores.growth || [];
  $("growthDimGrid").innerHTML = dims
    .map((d) => `<div class="growth-dim"><div class="dim-label">${escapeHtml(d.sub_dimension.replace(/_/g, " "))}</div><div class="dim-value">${escapeHtml(d.label || "N/A")}</div></div>`)
    .join("");
  $("growthObservations").innerHTML = (data.strengths || []).slice(0, 5).map((o) => `<li>${escapeHtml(o)}</li>`).join("") || "<li class='text-muted'>No observations</li>";
  $("growthInterviewPrep").innerHTML = (data.interview_preparation || []).map((o) => `<li>${escapeHtml(o)}</li>`).join("") || "<li class='text-muted'>Nothing flagged</li>";
}

function renderCompleteness(data) {
  const rows = data.sub_scores.completeness || [];
  $("compChecklist").innerHTML = rows
    .map((s) => {
      const passed = s.points >= s.points_max * 0.99;
      const icon = passed ? '<i class="fa-solid fa-check text-success me-1"></i>' : '<i class="fa-solid fa-xmark text-danger me-1"></i>';
      return `<div class="check-item d-flex align-items-center">${icon}<span class="fw-bold me-1">${escapeHtml(s.sub_dimension.replace(/_/g, " "))}</span></div>`;
    })
    .join("");
  $("compWarnings").innerHTML = (data.weaknesses || []).map((w) => `<li>${escapeHtml(w)}</li>`).join("") || "<li class='text-muted'>No warnings</li>";
}

$("startOverBtn").addEventListener("click", () => {
  state.resumeId = null;
  state.skills = [];
  selectedFile = null;
  $("fileInfo").classList.add("d-none");
  showSection("uploadSection");
});
