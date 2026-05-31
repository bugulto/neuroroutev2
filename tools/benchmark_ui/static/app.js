/* ================================================================
   NeuroRoute Benchmark UI — Application Logic
   ================================================================ */

(function () {
    "use strict";

    // ── DOM References ────────────────────────────────────────────

    const form = document.getElementById("benchmark-form");
    const runBtn = document.getElementById("run-btn");
    const thresholdSelect = document.getElementById("threshold");
    const usersInput = document.getElementById("users");
    const spawnRateInput = document.getElementById("spawn-rate");
    const totalCountInput = document.getElementById("total-count");
    const slowRatioInput = document.getElementById("slow-ratio");
    const modeRadios = document.querySelectorAll('input[name="neuroroute_mode"]');

    const globalBadge = document.getElementById("global-status-badge");
    const logOutput = document.getElementById("log-output");
    const clearLogsBtn = document.getElementById("clear-logs-btn");
    const stepTracker = document.getElementById("step-tracker");

    const resultsPanel = document.getElementById("results-panel");
    const improvementText = document.getElementById("improvement-text");
    const summaryThead = document.getElementById("summary-thead");
    const summaryTbody = document.getElementById("summary-tbody");
    const chartImage = document.getElementById("chart-image");

    // ── State ─────────────────────────────────────────────────────

    let currentRunId = null;
    let pollTimer = null;
    let lastLogCount = 0;
    let savedThreshold = thresholdSelect.value;

    // Step order for the tracker
    const STEP_ORDER = [
        "validating",
        "generating benchmark pages",
        "switching model",
        "restarting gateway",
        "running round robin",
        "running neuroroute",
        "analyzing",
        "completed",
    ];

    const RUNNING_STATUSES = new Set([
        "queued",
        "validating",
        "generating benchmark pages",
        "switching model",
        "restarting gateway",
        "running round robin",
        "running neuroroute",
        "analyzing",
    ]);

    // ── Mode Handling ─────────────────────────────────────────────

    function getSelectedMode() {
        const checked = document.querySelector('input[name="neuroroute_mode"]:checked');
        return checked ? checked.value : "online";
    }

    function handleModeChange() {
        const mode = getSelectedMode();

        if (mode === "cache") {
            savedThreshold = thresholdSelect.value;
            thresholdSelect.value = "p93";
            thresholdSelect.disabled = true;
        } else {
            thresholdSelect.disabled = false;
            thresholdSelect.value = savedThreshold;
        }
    }

    modeRadios.forEach(function (radio) {
        radio.addEventListener("change", handleModeChange);
    });

    // ── Helpers ───────────────────────────────────────────────────

    function setFormDisabled(disabled) {
        const mode = getSelectedMode();
        thresholdSelect.disabled = disabled || mode === "cache";
        usersInput.disabled = disabled;
        spawnRateInput.disabled = disabled;
        totalCountInput.disabled = disabled;
        slowRatioInput.disabled = disabled;
        runBtn.disabled = disabled;

        modeRadios.forEach(function (radio) {
            radio.disabled = disabled;
        });

        if (disabled) {
            runBtn.innerHTML =
                '<svg class="icon spinner" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M4 2a1 1 0 011 1v2.101a7.002 7.002 0 0111.601 2.566 1 1 0 11-1.885.666A5.002 5.002 0 005.999 7H9a1 1 0 010 2H4a1 1 0 01-1-1V3a1 1 0 011-1zm.008 9.057a1 1 0 011.276.61A5.002 5.002 0 0014.001 13H11a1 1 0 110-2h5a1 1 0 011 1v5a1 1 0 11-2 0v-2.101a7.002 7.002 0 01-11.601-2.566 1 1 0 01.61-1.276z" clip-rule="evenodd"/></svg>Running...';
        } else {
            runBtn.innerHTML =
                '<svg class="icon" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM9.555 7.168A1 1 0 008 8v4a1 1 0 001.555.832l3-2a1 1 0 000-1.664l-3-2z" clip-rule="evenodd"/></svg>Run Benchmark';
        }
    }

    function updateGlobalBadge(status) {
        globalBadge.textContent = status;
        globalBadge.className = "header-badge";

        if (RUNNING_STATUSES.has(status)) {
            globalBadge.classList.add("running");
        } else if (status === "completed") {
            globalBadge.classList.add("completed");
        } else if (status === "failed") {
            globalBadge.classList.add("failed");
        }
    }

    function updateStepTracker(currentStatus) {
        const steps = stepTracker.querySelectorAll(".step");
        const connectors = stepTracker.querySelectorAll(".step-connector");
        const currentIndex = STEP_ORDER.indexOf(currentStatus);
        const isFailed = currentStatus === "failed";

        steps.forEach(function (stepEl, i) {
            stepEl.classList.remove("active", "done", "failed");

            if (isFailed) {
                // Mark completed steps as done, last active step as failed
                if (i < currentIndex) {
                    stepEl.classList.add("done");
                } else if (i === currentIndex) {
                    stepEl.classList.add("failed");
                }
            } else if (currentStatus === "completed") {
                stepEl.classList.add("done");
            } else {
                if (i < currentIndex) {
                    stepEl.classList.add("done");
                } else if (i === currentIndex) {
                    stepEl.classList.add("active");
                }
            }
        });

        connectors.forEach(function (conn, i) {
            conn.classList.remove("done");
            if (i < currentIndex || currentStatus === "completed") {
                conn.classList.add("done");
            }
        });
    }

    function updateLogs(logs) {
        if (!logs || logs.length === 0) return;

        if (logs.length > lastLogCount) {
            const newLines = logs.slice(lastLogCount);
            if (lastLogCount === 0) {
                logOutput.textContent = newLines.join("\n");
            } else {
                logOutput.textContent += "\n" + newLines.join("\n");
            }
            lastLogCount = logs.length;

            // Auto-scroll to bottom
            logOutput.scrollTop = logOutput.scrollHeight;
        }
    }

    function formatNumber(val) {
        const num = parseFloat(val);
        if (isNaN(num)) return val;
        return num.toFixed(2);
    }

    function renderSummaryTable(rows) {
        if (!rows || rows.length === 0) return;

        // Build header
        const keys = Object.keys(rows[0]);
        summaryThead.innerHTML =
            "<tr>" + keys.map(function (k) { return "<th>" + escapeHtml(k) + "</th>"; }).join("") + "</tr>";

        // Build body
        summaryTbody.innerHTML = rows
            .map(function (row) {
                const cells = keys
                    .map(function (k) {
                        var cls = "";
                        if (k === "routing_mode") {
                            cls = row[k] === "round_robin" ? "mode-rr" : "mode-nr";
                        }
                        var val =
                            k === "routing_mode" || k === "group"
                                ? escapeHtml(row[k])
                                : formatNumber(row[k]);
                        return '<td class="' + cls + '">' + val + "</td>";
                    })
                    .join("");
                return "<tr>" + cells + "</tr>";
            })
            .join("");
    }

    function escapeHtml(str) {
        const div = document.createElement("div");
        div.textContent = str;
        return div.innerHTML;
    }

    // ── Validation ────────────────────────────────────────────────

    function validateForm() {
        const users = parseInt(usersInput.value, 10);
        const spawnRate = parseInt(spawnRateInput.value, 10);
        const totalCount = parseInt(totalCountInput.value, 10);
        const slowRatio = parseFloat(slowRatioInput.value);

        if (!thresholdSelect.value) return "Select a threshold";
        if (isNaN(users) || users <= 0) return "Users must be > 0";
        if (isNaN(spawnRate) || spawnRate <= 0) return "Spawn rate must be > 0";
        if (isNaN(totalCount) || totalCount <= 0) return "Request count must be > 0";
        if (isNaN(slowRatio) || slowRatio <= 0 || slowRatio >= 1) return "Slow ratio must be between 0 and 1";

        return null;
    }

    // ── API Calls ─────────────────────────────────────────────────

    async function startBenchmark() {
        const error = validateForm();
        if (error) {
            alert(error);
            return;
        }

        const mode = getSelectedMode();

        const payload = {
            threshold: thresholdSelect.value,
            neuroroute_mode: mode,
            users: parseInt(usersInput.value, 10),
            spawn_rate: parseInt(spawnRateInput.value, 10),
            total_count: parseInt(totalCountInput.value, 10),
            slow_ratio: parseFloat(slowRatioInput.value),
        };

        setFormDisabled(true);
        resultsPanel.style.display = "none";
        lastLogCount = 0;
        logOutput.textContent = "Starting benchmark (" + mode + " mode)...";
        updateGlobalBadge("queued");
        resetStepTracker();

        try {
            const resp = await fetch("/api/run-benchmark", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });

            if (!resp.ok) {
                const data = await resp.json();
                throw new Error(data.detail || "Failed to start benchmark");
            }

            const data = await resp.json();
            currentRunId = data.run_id;

            startPolling();
        } catch (err) {
            alert("Error: " + err.message);
            setFormDisabled(false);
            updateGlobalBadge("idle");
        }
    }

    function resetStepTracker() {
        stepTracker.querySelectorAll(".step").forEach(function (s) {
            s.classList.remove("active", "done", "failed");
        });
        stepTracker.querySelectorAll(".step-connector").forEach(function (c) {
            c.classList.remove("done");
        });
    }

    function startPolling() {
        if (pollTimer) clearInterval(pollTimer);

        pollTimer = setInterval(pollStatus, 2000);
        // Immediate first poll
        pollStatus();
    }

    async function pollStatus() {
        if (!currentRunId) return;

        try {
            const resp = await fetch("/api/benchmark-status/" + encodeURIComponent(currentRunId));
            if (!resp.ok) return;

            const data = await resp.json();
            const status = data.status;

            updateGlobalBadge(status);
            updateStepTracker(status);
            updateLogs(data.logs);

            if (status === "completed") {
                clearInterval(pollTimer);
                pollTimer = null;
                setFormDisabled(false);
                loadResults();
            } else if (status === "failed") {
                clearInterval(pollTimer);
                pollTimer = null;
                setFormDisabled(false);
            }
        } catch (err) {
            // Silently retry
        }
    }

    async function loadResults() {
        if (!currentRunId) return;

        try {
            // Load summary
            const summaryResp = await fetch(
                "/api/report-summary/" + encodeURIComponent(currentRunId)
            );
            if (summaryResp.ok) {
                const summaryData = await summaryResp.json();

                if (summaryData.improvement_text) {
                    improvementText.textContent = summaryData.improvement_text;
                }

                if (summaryData.summary_table) {
                    renderSummaryTable(summaryData.summary_table);
                }
            }

            // Load chart image
            chartImage.src =
                "/api/report-image/" + encodeURIComponent(currentRunId) + "?t=" + Date.now();

            resultsPanel.style.display = "block";

            // Smooth scroll to results
            setTimeout(function () {
                resultsPanel.scrollIntoView({ behavior: "smooth", block: "start" });
            }, 200);
        } catch (err) {
            console.error("Failed to load results:", err);
        }
    }

    // ── Event Listeners ───────────────────────────────────────────

    form.addEventListener("submit", function (e) {
        e.preventDefault();
        startBenchmark();
    });

    clearLogsBtn.addEventListener("click", function () {
        logOutput.textContent = "Logs cleared.";
        lastLogCount = 0;
    });
})();
