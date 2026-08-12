const DEFAULT_LIVE_BASE = 'https://raw.githubusercontent.com/jyy7294/noinbada/live-data/latest';
const CACHE_KEY = 'trzip:latest-intelligence:v1';
const PORTFOLIO_KEY = 'trzip:portfolios:v1';

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
  product_brand: '제품·브랜드',
  technology_tool: '기술',
  fashion_collectible: '패션',
  unclassified: '기타',
};

function liveBase() {
  const configured = globalThis.TRZIP_DATA_BASE
    || new URLSearchParams(globalThis.location?.search || '').get('dataBase');
  if (!configured) return DEFAULT_LIVE_BASE;
  if (configured.startsWith('/') || configured.startsWith('https://')) {
    return configured.replace(/\/$/, '');
  }
  return DEFAULT_LIVE_BASE;
}

function readJson(key, fallback) {
  try { return JSON.parse(localStorage.getItem(key)) ?? fallback; }
  catch { return fallback; }
}

function writeJson(key, value) {
  localStorage.setItem(key, JSON.stringify(value));
}

function rankDelta(item) {
  const values = Object.values(item.rank_change_by_source || {}).filter(Number.isFinite);
  if (!values.length) return item.lifecycle === 'new' ? '신규 포착' : '순위 유지';
  const best = values.sort((a, b) => Math.abs(b) - Math.abs(a))[0];
  if (best === 0) return '순위 유지';
  return best > 0 ? `순위 +${best}` : `순위 ${best}`;
}

function normalizeTrend(item) {
  return {
    id: item.topic,
    topic: item.topic,
    displayName: item.display_name || item.topic,
    rank: item.rank,
    rankLabel: String(item.rank).padStart(2, '0'),
    category: item.category,
    categoryKo: CATEGORY_KO[item.category] || '기타',
    delta: rankDelta(item),
    lifecycle: item.lifecycle,
    lifecycleLabel: item.lifecycle_reason,
    summary: item.phenomenon_summary,
    selectionReason: item.selection_reason,
    confidence: item.data_confidence,
    contextStatus: item.context_status,
    sourceBadge: item.source_badge,
    scoreComponents: item.score_components || {},
    keywords: (item.keywords || []).slice(0, 5),
    keywordEvidence: item.keyword_evidence || {},
    companies: item.companies || [],
    companyEligible: Boolean(item.company_eligible),
    companyResolution: item.company_resolution,
    sources: item.latest_source_ranks || {},
    sourceCount: item.source_count,
    firstSeenAt: item.first_seen_at,
    lastSeenAt: item.last_seen_at,
    ageHours: item.age_hours,
    persistence: item.persistence,
    momentum: item.momentum,
    score: item.score,
    series: item.series || [],
    raw: item,
  };
}

export async function loadTrends({ mode = 'live' } = {}) {
  if (mode !== 'live') throw new Error('운영 화면은 live-data만 사용합니다.');
  try {
    const response = await fetch(`${liveBase()}/intelligence.json?t=${Date.now()}`, { cache: 'no-store' });
    if (!response.ok) throw new Error(`TRZIP data ${response.status}`);
    const payload = await response.json();
    if (payload.mode !== 'live' || !Array.isArray(payload.unified_ranking)) {
      throw new Error('실시간 데이터 계약이 올바르지 않습니다.');
    }
    writeJson(CACHE_KEY, payload);
    return {
      source: 'github-live-data',
      stale: false,
      observedAt: payload.window?.to || payload.generated_at,
      trends: payload.unified_ranking.map(normalizeTrend),
      raw: payload,
    };
  } catch (error) {
    const cached = readJson(CACHE_KEY, null);
    if (!cached) throw error;
    return {
      source: 'local-cache',
      stale: true,
      error: String(error),
      observedAt: cached.window?.to || cached.generated_at,
      trends: cached.unified_ranking.map(normalizeTrend),
      raw: cached,
    };
  }
}

export function sortTrends(trends, mode = 'score') {
  const rows = [...trends];
  if (mode === 'persistence') return rows.sort((a, b) => b.persistence - a.persistence || a.rank - b.rank);
  if (mode === 'momentum') return rows.sort((a, b) => b.momentum - a.momentum || a.rank - b.rank);
  return rows.sort((a, b) => a.rank - b.rank);
}

export function listPortfolios() {
  return readJson(PORTFOLIO_KEY, []);
}

export function savePortfolio(input) {
  const portfolios = listPortfolios();
  const record = {
    schemaVersion: 'trzip-portfolio-v1',
    id: input.id || `portfolio-${Date.now()}`,
    name: String(input.name || '새 밈트폴리오').trim(),
    trendTopic: input.trendTopic || null,
    observedAt: input.observedAt || null,
    keywords: [...new Set(input.keywords || [])].slice(0, 10),
    companies: (input.companies || []).slice(0, 10),
    createdAt: input.createdAt || new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  };
  const next = [record, ...portfolios.filter((item) => item.id !== record.id)];
  writeJson(PORTFOLIO_KEY, next);
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
  input: `${DEFAULT_LIVE_BASE}/intelligence.json`,
  cache: CACHE_KEY,
  portfolios: PORTFOLIO_KEY,
  exportSchema: 'trzip-export-v1',
});
