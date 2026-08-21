function scheduleStatusParts(status, message, schedule) {
  const parts = [`Last status: ${status || "idle"}.`];
  if (message) parts.push(String(message));
  if (schedule?.last_run_at) parts.push(`Last run ${schedule.last_run_at}.`);
  if (schedule?.next_run_at) parts.push(`Next run ${schedule.next_run_at}.`);
  return parts.join(" ");
}

function reconcileScheduledFetchStatus(payload) {
  const statusElement = document.querySelector("[data-rules-schedule-status]");
  if (!statusElement) return;

  const component = payload?.components?.scheduled_rule_fetch;
  const invariant = payload?.invariants?.["F-02"];
  const schedule = component?.schedule;
  if (!schedule || !invariant) return;

  const state = String(invariant?.metrics?.effectiveness_state || "unknown");
  statusElement.dataset.functionalState = state;

  if (state === "recovered_historical") {
    const previous = String(schedule.last_message || "Scheduled fetch failed in a previous runtime.");
    statusElement.textContent = scheduleStatusParts(
      "ready",
      `Previous runtime reported: ${previous} Current runtime readiness checks pass; awaiting the next scheduled run.`,
      schedule,
    );
    return;
  }

  if (state === "historical_error_unverified") {
    const previous = String(schedule.last_message || "Scheduled fetch failed in a previous runtime.");
    statusElement.textContent = scheduleStatusParts(
      "historical error",
      `Previous runtime reported: ${previous} Current prerequisites are ready, but this historical failure has not been reproduced or cleared.`,
      schedule,
    );
    return;
  }

  statusElement.textContent = scheduleStatusParts(
    String(schedule.last_status || "idle"),
    String(schedule.last_message || ""),
    schedule,
  );
}

async function refreshRuntimeHealth() {
  if (!document.querySelector("[data-rules-schedule-status]")) return;
  try {
    const response = await fetch("/api/diagnostics/runtime", {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    if (!response.ok) return;
    reconcileScheduledFetchStatus(await response.json());
  } catch (_error) {
    // Keep the server-rendered status when diagnostics are temporarily unavailable.
  }
}

window.addEventListener("DOMContentLoaded", () => {
  void refreshRuntimeHealth();
  window.setInterval(() => void refreshRuntimeHealth(), 60_000);
});
