const LIVE_DATA_BASE = 'https://raw.githubusercontent.com/jyy7294/noinbada/live-data/latest';
const INTELLIGENCE_URL = `${LIVE_DATA_BASE}/intelligence.json`;
const STATUS_URL = `${LIVE_DATA_BASE}/status.json`;
const METADATA_URL = `${LIVE_DATA_BASE}/metadata.json`;
const CACHE_KEY = 'trzip:latest-intelligence:v2';
const PORTFOLIO_KEY = 'trzip:portfolios:v1';
const FRESH_FOR_MINUTES = 90;
const STALE_AFTER_MINUTES = 180;

const CATEGORY_KO = {
  food_culinary: '음식·식품',
  seasonal_food_ritual: '음식·식품',
  music_performance: '음악',
  screen_content: '콘텐츠',
  gaming_digital: '게임',
  sports_participation: '스포츠',
  sports_attendance: '스포츠',
  place_experience: '여행·공간',
  lifestyle_behavior: '생활',
  wellness_behavior: '생활',
  participation_meme: '밈·참여',
  product_brand: '제품·브랜드',
  technology_tool: '기술',
  fashion_beauty: '패션·뷰티',
  fashion_collectible: '패션·굿즈',
  investment_market: '금융·투자',
  unclassified: '기타',
};

function readJson(key, fallback) {
  try { return JSON.parse(localStorage.getItem(key)) ?? fallback; }
  catch { return fallback; }
}

function writeJson(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}

function asDate(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isFinite(date.getTime()) ? date : null;
}

function normalizedSourceStatus(payload, metadata, runtimeStatus) {
  const published = runtimeStatus?.source_status || {};
  const direct = payload.collection_status?.source_status || {};
  const audit = metadata.collection?.audit || {};
  return {
    x: published.x || direct.x || audit.x_korea_realtime?.status || 'unknown',
    google_trends: published.google_trends || direct.google_trends || audit.google_geo_kr?.status || 'unknown',
  };
}

function dataStatus(payload, metadata, runtimeStatus, { fromCache = false, now = new Date() } = {}) {
  const payloadAt = asDate(payload.window?.to || payload.generated_at);
  const metadataAt = asDate(runtimeStatus?.observed_at || metadata.observed_at || metadata.collection?.observed_at);
  const observedAt = metadataAt || payloadAt;
  const ageMinutes = observedAt
    ? Math.max(0, Math.round((now.getTime() - observedAt.getTime()) / 60000))
    : null;
  const snapshotMismatch = Boolean(
    payloadAt && metadataAt && Math.abs(payloadAt.getTime() - metadataAt.getTime()) > 60000,
  );
  const sourceStatus = normalizedSourceStatus(payload, metadata, runtimeStatus);
  const unavailableSources = Object.entries(sourceStatus)
    .filter(([, status]) => status !== 'observed')
    .map(([source]) => source);
  const partial = Boolean(runtimeStatus?.partial || payload.collection_status?.partial || unavailableSources.length);
  const delayed = Boolean(!fromCache && observedAt && ageMinutes > FRESH_FOR_MINUTES && ageMinutes <= STALE_AFTER_MINUTES);
  const stale = Boolean(
    fromCache || !observedAt || ageMinutes > STALE_AFTER_MINUTES || snapshotMismatch,
  );

  return {
    observedAt: observedAt?.toISOString() || null,
    ageMinutes,
    freshness: stale ? 'stale' : delayed ? 'delayed' : partial ? 'partial' : 'fresh',
    stale,
    delayed,
    partial,
    fromCache,
    snapshotMismatch,
    sourceStatus,
    unavailableSources,
    errors: runtimeStatus?.errors || payload.collection_status?.errors || metadata.collection?.errors || {},
    reason: fromCache
      ? '네트워크 응답 대신 마지막 정상 저장본을 표시합니다.'
      : snapshotMismatch
        ? '순위와 수집 상태의 기준시각이 일치하지 않습니다.'
        : !observedAt
          ? '관측 기준시각을 확인할 수 없습니다.'
          : ageMinutes > STALE_AFTER_MINUTES
            ? `마지막 관측 후 ${ageMinutes}분이 지나 최신 상태가 아닙니다.`
            : delayed
              ? `마지막 관측 후 ${ageMinutes}분이 지나 다음 수집을 기다리고 있습니다.`
            : partial
              ? `${unavailableSources.join(', ')} 수집이 완료되지 않았습니다.`
              : 'X와 Google Trends 최신 수집을 모두 확인했습니다.',
  };
}

function rankDelta(item) {
  const values = Object.values(item.rank_change_by_source || {}).filter(Number.isFinite);
  if (!values.length) return item.lifecycle === 'new' ? '신규 포착' : '순위 유지';
  const best = [...values].sort((a, b) => Math.abs(b) - Math.abs(a))[0];
  if (best === 0) return '순위 유지';
  return best > 0 ? `순위 +${best}` : `순위 ${best}`;
}

function normalizeTrend(item) {
  return {
    id: item.topic,
    topic: item.topic,
    displayName: item.display_name || item.topic,
    rank: Number(item.rank || 0),
    rankLabel: String(item.rank || '--').padStart(2, '0'),
    category: item.category,
    categoryKo: CATEGORY_KO[item.category] || '기타',
    delta: rankDelta(item),
    lifecycle: item.lifecycle,
    lifecycleLabel: item.lifecycle_reason,
    summary: item.phenomenon_summary,
    selectionReason: item.selection_reason,
    confidence: item.data_confidence,
    contextStatus: item.context_status,
    homeContextStatus: item.home_context_status || 'resolved',
    reviewRequired: item.home_context_status === 'review_required',
    sourceBadge: item.source_badge,
    scoreComponents: item.score_components || {},
    // 공개 키워드는 X/Google 원천에서 실제 관측된 표현만 허용한다.
    keywords: (item.keywords || [])
      .filter((row) => row.status === 'observed_source_expression')
      .slice(0, 5),
    keywordCandidates: (item.keywords || [])
      .filter((row) => row.status === 'operator_candidate_not_rank_evidence')
      .slice(0, 5),
    keywordEvidence: item.keyword_evidence || {},
    companies: Array.isArray(item.companies) ? item.companies : [],
    companyEligible: Boolean(item.company_eligible),
    companyResolution: item.company_resolution,
    sources: item.latest_source_ranks || {},
    sourceCount: Number(item.source_count || 0),
    firstSeenAt: item.first_seen_at,
    lastSeenAt: item.last_seen_at,
    ageHours: Number(item.age_hours || 0),
    persistence: Number(item.persistence || 0),
    momentum: Number(item.momentum || 0),
    score: Number(item.score || 0),
    series: Array.isArray(item.series) ? item.series : [],
    raw: item,
  };
}

function validatedBundle(payload, metadata, runtimeStatus = null) {
  if (payload?.mode !== 'live' || !Array.isArray(payload.unified_ranking)) {
    throw new Error('실시간 순위 데이터 계약이 올바르지 않습니다.');
  }
  if (metadata?.mode !== 'live' || !metadata.observed_at) {
    throw new Error('실시간 수집 상태 데이터 계약이 올바르지 않습니다.');
  }
  if (runtimeStatus && (runtimeStatus.mode !== 'live' || !runtimeStatus.observed_at)) {
    throw new Error('실행 상태 데이터 계약이 올바르지 않습니다.');
  }
  return { payload, metadata, runtimeStatus };
}

function viewModel(bundle, { source, fromCache }) {
  const { payload, metadata, runtimeStatus } = bundle;
  const status = dataStatus(payload, metadata, runtimeStatus, { fromCache });
  const rankingByTopic = new Map(payload.unified_ranking.map((item) => [item.topic, item]));
  const publicRows = (payload.public_top10 || [])
    .map((item) => rankingByTopic.get(item.topic) || item)
    .filter((item) => item && item.topic);
  return {
    source,
    stale: status.stale,
    partial: status.partial,
    observedAt: status.observedAt,
    status,
    trends: payload.unified_ranking.map(normalizeTrend),
    featuredTrends: publicRows.map(normalizeTrend),
    metadata,
    raw: payload,
  };
}

export async function loadTrends({ mode = 'live' } = {}) {
  if (mode !== 'live') throw new Error('운영 화면은 live-data만 사용합니다.');
  try {
    const nonce = Date.now();
    const [intelligenceResponse, statusResponse, metadataResponse] = await Promise.all([
      fetch(`${INTELLIGENCE_URL}?t=${nonce}`, { cache: 'no-store' }),
      fetch(`${STATUS_URL}?t=${nonce}`, { cache: 'no-store' }),
      fetch(`${METADATA_URL}?t=${nonce}`, { cache: 'no-store' }),
    ]);
    if (!intelligenceResponse.ok) throw new Error(`TRZIP intelligence ${intelligenceResponse.status}`);
    if (!statusResponse.ok) throw new Error(`TRZIP status ${statusResponse.status}`);
    if (!metadataResponse.ok) throw new Error(`TRZIP metadata ${metadataResponse.status}`);
    const bundle = validatedBundle(
      await intelligenceResponse.json(),
      await metadataResponse.json(),
      await statusResponse.json(),
    );
    writeJson(CACHE_KEY, bundle);
    return viewModel(bundle, { source: 'live-data', fromCache: false });
  } catch (error) {
    const cached = readJson(CACHE_KEY, null);
    if (!cached?.payload || !cached?.metadata) throw error;
    return {
      ...viewModel(validatedBundle(cached.payload, cached.metadata, cached.runtimeStatus || null), {
        source: 'local-cache',
        fromCache: true,
      }),
      error: String(error),
    };
  }
}

export function sortTrends(trends, mode = 'score') {
  const rows = [...trends];
  if (mode === 'persistence') return rows.sort((a, b) => b.persistence - a.persistence || a.rank - b.rank);
  if (mode === 'momentum') return rows.sort((a, b) => b.momentum - a.momentum || a.rank - b.rank);
  return rows.sort((a, b) => a.rank - b.rank);
}

function normalizePortfolio(record) {
  if (!record || typeof record !== 'object') return null;
  const id = String(record.id || '').trim();
  if (!id) return null;
  return {
    schemaVersion: 'trzip-portfolio-v1',
    id,
    name: String(record.name || '이름 없는 밈트폴리오'),
    trendTopic: record.trendTopic || null,
    observedAt: record.observedAt || null,
    keywords: Array.isArray(record.keywords) ? record.keywords.map(String).slice(0, 10) : [],
    companies: Array.isArray(record.companies) ? record.companies.slice(0, 10) : [],
    createdAt: record.createdAt || null,
    updatedAt: record.updatedAt || null,
  };
}

export function listPortfolios() {
  const stored = readJson(PORTFOLIO_KEY, []);
  return Array.isArray(stored) ? stored.map(normalizePortfolio).filter(Boolean) : [];
}

export function getPortfolio(id) {
  return listPortfolios().find((portfolio) => portfolio.id === String(id)) || null;
}

export function savePortfolio(input) {
  const portfolios = listPortfolios();
  const keywords = [...new Set((input.keywords || [])
    .map((keyword) => String(keyword).trim())
    .filter(Boolean))]
    .slice(0, 10);
  const id = input.id || globalThis.crypto?.randomUUID?.() || `portfolio-${Date.now()}`;
  const record = normalizePortfolio({
    schemaVersion: 'trzip-portfolio-v1',
    id,
    name: String(input.name || '새 밈트폴리오').trim().slice(0, 80) || '새 밈트폴리오',
    trendTopic: input.trendTopic || null,
    observedAt: input.observedAt || null,
    keywords,
    companies: (input.companies || []).slice(0, 10),
    createdAt: input.createdAt || new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  });
  const next = [record, ...portfolios.filter((item) => item.id !== record.id)];
  if (!writeJson(PORTFOLIO_KEY, next)) {
    throw new Error('브라우저 저장공간에 밈트폴리오를 저장하지 못했습니다.');
  }
  return record;
}

function download(filename, text, type) {
  const blob = new Blob([text], { type });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export function exportPortfoliosJson() {
  const payload = {
    schemaVersion: 'trzip-export-v1',
    exportedAt: new Date().toISOString(),
    portfolios: listPortfolios(),
  };
  download(`trzip-portfolios-${new Date().toISOString().slice(0, 10)}.json`, JSON.stringify(payload, null, 2), 'application/json;charset=utf-8');
  return payload.portfolios.length;
}

export function exportPortfoliosCsv() {
  const quote = (value) => `"${String(value ?? '').replaceAll('"', '""')}"`;
  const rows = [['portfolio_id', 'portfolio_name', 'trend_topic', 'keyword', 'company', 'stock_code', 'relation_category', 'verification_status', 'created_at']];
  listPortfolios().forEach((portfolio) => {
    const keywords = portfolio.keywords.length ? portfolio.keywords : [''];
    const companies = portfolio.companies.length ? portfolio.companies : [{}];
    keywords.forEach((keyword) => companies.forEach((company) => rows.push([
      portfolio.id, portfolio.name, portfolio.trendTopic, keyword, company.company,
      company.stock_code, company.relation_category, company.verification_status, portfolio.createdAt,
    ])));
  });
  const csv = '\ufeff' + rows.map((row) => row.map(quote).join(',')).join('\r\n');
  download(`trzip-portfolios-${new Date().toISOString().slice(0, 10)}.csv`, csv, 'text/csv;charset=utf-8');
  return Math.max(0, rows.length - 1);
}

export const dataContract = Object.freeze({
  intelligence: INTELLIGENCE_URL,
  status: STATUS_URL,
  metadata: METADATA_URL,
  cache: CACHE_KEY,
  portfolios: PORTFOLIO_KEY,
  exportSchema: 'trzip-export-v1',
  freshForMinutes: FRESH_FOR_MINUTES,
  staleAfterMinutes: STALE_AFTER_MINUTES,
});
