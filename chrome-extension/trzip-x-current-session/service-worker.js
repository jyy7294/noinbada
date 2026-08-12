const X_URL = "https://x.com/explore/tabs/trending";
const ALARM_NAME = "trzip-x-top-of-hour";
const OUTPUT_FILE = "TRZIP/x-current-session.json";
const HOUR_MS = 60 * 60 * 1000;

let runningCollection = null;

function nextTopOfHour(now = Date.now()) {
  return Math.floor(now / HOUR_MS + 1) * HOUR_MS;
}

async function ensureHourlyAlarm() {
  const existing = await chrome.alarms.get(ALARM_NAME);
  const aligned = existing
    && existing.periodInMinutes === 60
    && existing.scheduledTime % HOUR_MS < 1000;
  if (!aligned) {
    if (existing) await chrome.alarms.clear(ALARM_NAME);
    await chrome.alarms.create(ALARM_NAME, {
      when: nextTopOfHour(),
      periodInMinutes: 60,
      persistAcrossSessions: true,
    });
  }
}

function waitForTabComplete(tabId, timeoutMs = 30000) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const timer = setTimeout(() => finish(new Error("X page load timeout")), timeoutMs);
    const finish = (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      chrome.tabs.onUpdated.removeListener(onUpdated);
      error ? reject(error) : resolve();
    };
    const onUpdated = (updatedId, changeInfo) => {
      if (updatedId === tabId && changeInfo.status === "complete") finish();
    };
    chrome.tabs.onUpdated.addListener(onUpdated);
    chrome.tabs.get(tabId).then((tab) => {
      if (tab.status === "complete") finish();
    }).catch(finish);
  });
}

async function collectRowsInPage() {
  const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
  const seen = new Map();

  const normalize = (value) => String(value || "")
    .normalize("NFKC")
    .replace(/\s+/g, " ")
    .trim();

  const isContextLine = (line) => {
    const folded = line.toLocaleLowerCase("ko-KR");
    return line === "·"
      || line === "•"
      || folded === "더 보기"
      || folded === "show more"
      || folded.includes("대한민국에서 트렌드 중")
      || folded.includes("trending in south korea")
      || folded.includes("trends in south korea")
      || /^(only on x|entertainment|sports|politics|music|gaming)\s*[·•]\s*trending$/i.test(line)
      || /^(실시간 트렌드|트렌드 중)$/i.test(line)
      || /^[\d,.만천]+\s*(posts|게시물)$/i.test(line);
  };

  const inspectVisibleRows = () => {
    for (const cell of document.querySelectorAll('[data-testid="trend"]')) {
      const lines = String(cell.innerText || "")
        .split(/\r?\n/)
        .map(normalize)
        .filter(Boolean);
      if (!lines.length || !/^\d{1,3}$/.test(lines[0])) continue;
      const rank = Number(lines[0]);
      if (rank < 1 || rank > 100 || seen.has(rank)) continue;
      const candidates = lines.slice(1).filter((line) => !isContextLine(line));
      if (!candidates.length) continue;
      const topic = normalize(candidates[candidates.length - 1]);
      if (!topic || topic.length > 200) continue;
      seen.set(rank, topic);
    }
  };

  const pageUrl = location.href;
  if (/\/login|\/onboarding\/|mode=login/i.test(pageUrl)) {
    return { ok: false, code: "auth_required", pageUrl, regionVerified: false, trends: [] };
  }

  window.scrollTo({ top: 0, behavior: "instant" });
  await sleep(1500);
  let noProgress = 0;
  let previousCount = 0;
  for (let attempt = 0; attempt < 70; attempt += 1) {
    inspectVisibleRows();
    const complete = Array.from({ length: 30 }, (_, index) => index + 1)
      .every((rank) => seen.has(rank));
    if (complete) break;

    if (seen.size === previousCount) noProgress += 1;
    else noProgress = 0;
    previousCount = seen.size;

    const before = window.scrollY;
    window.scrollBy({
      top: Math.max(650, Math.floor(window.innerHeight * 0.82)),
      behavior: "instant",
    });
    await sleep(1000);
    if (window.scrollY === before && noProgress >= 4) break;
  }
  inspectVisibleRows();

  const rowText = Array.from(document.querySelectorAll('[data-testid="trend"]'))
    .map((element) => String(element.innerText || ""))
    .join("\n")
    .toLocaleLowerCase("ko-KR");
  const regionVerified = rowText.includes("대한민국에서 트렌드 중")
    || rowText.includes("대한민국 트렌드")
    || rowText.includes("trending in south korea")
    || rowText.includes("trends in south korea");
  const trends = [...seen.entries()]
    .sort((left, right) => left[0] - right[0])
    .map(([rank, topic]) => ({ rank, topic }));
  const hasAllThirty = Array.from({ length: 30 }, (_, index) => index + 1)
    .every((rank) => seen.has(rank));
  return {
    ok: regionVerified && hasAllThirty,
    code: !regionVerified ? "region_unverified" : (!hasAllThirty ? "incomplete_scroll" : null),
    pageUrl: location.href,
    regionVerified,
    trends,
  };
}

async function waitForDownload(downloadId, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const [item] = await chrome.downloads.search({ id: downloadId });
    if (item?.state === "complete") return;
    if (item?.state === "interrupted") throw new Error(`snapshot download interrupted: ${item.error || "unknown"}`);
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error("snapshot download timeout");
}

async function writeSanitizedSnapshot(payload) {
  const json = JSON.stringify(payload, null, 2);
  const url = `data:application/json;charset=utf-8,${encodeURIComponent(json)}`;
  const downloadId = await chrome.downloads.download({
    url,
    filename: OUTPUT_FILE,
    conflictAction: "overwrite",
    saveAs: false,
  });
  await waitForDownload(downloadId);
  await chrome.downloads.erase({ id: downloadId });
}

async function setBadge(text, color) {
  await chrome.action.setBadgeBackgroundColor({ color });
  await chrome.action.setBadgeText({ text });
}

async function performCollection(reason, scheduledTime = null) {
  await setBadge("…", "#5f6368");
  let createdTabId = null;
  try {
    const tab = await chrome.tabs.create({ url: X_URL, active: false });
    createdTabId = tab.id;
    if (!createdTabId) throw new Error("Chrome did not create the X collection tab");
    await waitForTabComplete(createdTabId);
    const results = await chrome.scripting.executeScript({
      target: { tabId: createdTabId },
      func: collectRowsInPage,
    });
    const result = results?.[0]?.result;
    if (!result?.ok) {
      throw new Error(`${result?.code || "collection_failed"}: rows=${result?.trends?.length || 0}`);
    }
    const observedAt = new Date().toISOString();
    const payload = {
      schema_version: 1,
      source: "x",
      collector: "chrome_extension_current_session",
      observed_at: observedAt,
      scheduled_for: scheduledTime ? new Date(scheduledTime).toISOString() : null,
      trigger: reason,
      url: X_URL,
      region: "KR",
      region_verified: true,
      row_count: result.trends.length,
      trends: result.trends,
    };
    await writeSanitizedSnapshot(payload);
    await setBadge("30", "#137333");
    return payload;
  } catch (error) {
    console.error("TRZIP X collection failed", error);
    await setBadge("!", "#b3261e");
    throw error;
  } finally {
    if (createdTabId !== null) {
      try {
        await chrome.tabs.remove(createdTabId);
      } catch (_ignored) {
        // Only the tab created by this run is ever closed.
      }
    }
  }
}

function collectNow(reason, scheduledTime = null) {
  if (!runningCollection) {
    runningCollection = performCollection(reason, scheduledTime)
      .finally(() => { runningCollection = null; });
  }
  return runningCollection;
}

chrome.runtime.onInstalled.addListener(() => {
  void ensureHourlyAlarm().catch(console.error);
  void collectNow("installed").catch(() => {});
});

chrome.runtime.onStartup.addListener(() => {
  void ensureHourlyAlarm().catch(console.error);
  void collectNow("chrome_startup").catch(() => {});
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === ALARM_NAME) {
    void collectNow("top_of_hour_alarm", alarm.scheduledTime).catch(() => {});
  }
});

chrome.action.onClicked.addListener(() => {
  void collectNow("manual_action").catch(() => {});
});

void ensureHourlyAlarm().catch(console.error);
