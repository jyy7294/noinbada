const LIVE_DATA_BASE = 'https://raw.githubusercontent.com/jyy7294/noinbada/live-data/latest';
const MANIFEST_URL = `${LIVE_DATA_BASE}/manifest.json`;
const INTELLIGENCE_URL = `${LIVE_DATA_BASE}/intelligence.json`;
const STATUS_URL = `${LIVE_DATA_BASE}/status.json`;
const METADATA_URL = `${LIVE_DATA_BASE}/metadata.json`;
const CACHE_KEY = 'trzip:latest-intelligence:v3';
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
  // Immutable rankings publish a distinct generation timestamp, which can be
  // several minutes after the exact-hour observation. Freshness and snapshot
  // consistency must therefore compare observation timestamps first; using
  // generated_at here incorrectly labels a healthy publication as a saved copy.
  const payloadAt = asDate(payload.observed_at || payload.window?.to || payload.generated_at);
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
  const presentationItem = item.data_mode === 'observed_reference';
  const topic = item.topic || item.event_key || item.display_name;
  const rank = Number(item.presentation_position || item.rank || 0);
  const companyEligible = presentationItem
    ? Array.isArray(item.companies) && item.companies.length > 0
    : Boolean(item.company_eligible);
  const keywords = presentationItem
    ? (item.keywords || []).slice(0, 5)
    : (item.keywords || [])
      .filter((row) => row.status === 'observed_source_expression')
      .slice(0, 5);
  const companies = companyEligible && Array.isArray(item.companies)
    ? item.companies.map((company) => ({
      ...company,
      stock_code: company.stock_code || company.ticker,
      market: company.market || company.exchange,
      relation_category: company.company_role_label || company.relation_category || '역할 미확정',
      company_role: company.company_role_label || company.company_role || '역할 미확정',
      reason: company.connection_explanation || company.relationship_reason || company.reason,
    }))
    : [];
  const trendStage = item.trend_stage || item.trend_story?.diffusion?.trend_stage || null;
  const observedDayLabel = item.observed_day_label
    || item.trend_story?.diffusion?.observed_day_label
    || null;
  return {
    id: topic,
    topic,
    displayName: item.display_name || topic,
    shortDisplayName: item.short_display_name || item.display_name || topic,
    rank,
    rankLabel: String(rank || '--').padStart(2, '0'),
    category: item.category,
    categoryKo: item.category_label || CATEGORY_KO[item.category] || '기타',
    delta: presentationItem ? '발행 순번' : rankDelta(item),
    rankKind: presentationItem ? 'publication' : 'observed',
    lifecycle: item.lifecycle,
    lifecycleLabel: item.lifecycle_reason,
    summary: item.trend_definition || item.phenomenon_summary,
    selectionReason: item.selection_reason,
    confidence: item.data_confidence,
    contextStatus: item.context_status,
    homeContextStatus: item.home_context_status || 'resolved',
    reviewRequired: item.home_context_status === 'review_required',
    sourceBadge: item.source_badge,
    scoreComponents: item.score_components || {},
    keywords,
    keywordCandidates: (item.keywords || [])
      .filter((row) => row.status === 'operator_candidate_not_rank_evidence')
      .slice(0, 5),
    keywordEvidence: presentationItem
      ? { status: 'reviewed', reason: '검수된 관련어 5개' }
      : (item.keyword_evidence || {}),
    companies,
    companyEligible,
    companyResolution: item.company_resolution || {
      candidate_count: companies.length,
      reason: item.company_card_status === 'ready'
        ? '근거가 확인된 상장기업 연결'
        : `검증 기업 ${companies.length}개`,
    },
    companyCardStatus: item.company_card_status,
    sources: item.latest_source_ranks || {},
    sourceList: Array.isArray(item.sources) ? item.sources : Object.keys(item.latest_source_ranks || {}),
    sourceCount: Number(item.source_count || (Array.isArray(item.sources) ? item.sources.length : 0)),
    trendStage,
    observedDayLabel,
    attentionLift: item.attention_lift || item.trend_story?.diffusion?.attention_lift || null,
    attentionWindows: item.attention_windows || item.trend_story?.diffusion?.attention_windows || [],
    seriesMetric: item.series_metric || {
      key: 'normalized_attention_index',
      label: '언급량 추이 · 관심지수',
      is_absolute_mention_count: false,
    },
    firstSeenAt: item.first_seen_at,
    lastSeenAt: item.last_seen_at,
    ageHours: Number(item.age_hours || 0),
    persistence: Number(item.persistence || 0),
    momentum: Number(item.momentum || 0),
    score: Number(item.score || 0),
    series: Array.isArray(item.series) ? item.series : [],
    visualizationSeries: item.visualization_series || {},
    raw: item,
  };
}

function sameInstant(values) {
  const timestamps = values.map((value) => asDate(value)?.getTime());
  return timestamps.every(Number.isFinite) && new Set(timestamps).size === 1;
}

function publicationIdentity(payload, metadata, runtimeStatus) {
  const documents = [payload, metadata].concat(runtimeStatus ? [runtimeStatus] : []);
  const publicationIds = documents.map((document) => document.publication_id || null);
  const hasPublicationId = publicationIds.some(Boolean);
  if (hasPublicationId) {
    if (!runtimeStatus || publicationIds.some((value) => !value) || new Set(publicationIds).size !== 1) {
      throw new Error('실시간 게시 묶음의 publication_id가 일치하지 않습니다.');
    }
    const generatedAt = documents.map((document) => document.generated_at);
    if (!sameInstant(generatedAt)) {
      throw new Error('실시간 게시 묶음의 generated_at이 일치하지 않습니다.');
    }
    return {
      id: publicationIds[0],
      generatedAt: asDate(generatedAt[0]).toISOString(),
      validationMode: 'publication_id',
      legacy: false,
    };
  }

  const generatedAt = documents.map((document) => document.generated_at);
  if (generatedAt.every(Boolean)) {
    if (!sameInstant(generatedAt)) {
      throw new Error('기존 게시 묶음의 generated_at이 일치하지 않습니다.');
    }
    return {
      id: null,
      generatedAt: asDate(generatedAt[0]).toISOString(),
      validationMode: 'generated_at',
      legacy: true,
    };
  }

  // publication_id 도입 전 데이터는 intelligence.generated_at이 없었다.
  // 이 경우에만 관측 시각 일치로 읽되 같은 시간대 재게시 혼합까지는 검출할 수 없다.
  const observedAt = [payload.window?.to, metadata.observed_at]
    .concat(runtimeStatus ? [runtimeStatus.observed_at] : []);
  if (!sameInstant(observedAt)) {
    throw new Error('기존 게시 묶음의 observed_at이 일치하지 않습니다.');
  }
  return {
    id: null,
    generatedAt: null,
    validationMode: 'legacy_observed_at',
    legacy: true,
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
  const publication = publicationIdentity(payload, metadata, runtimeStatus);
  return { payload, metadata, runtimeStatus, publication };
}

async function sha256Hex(text) {
  if (!globalThis.crypto?.subtle) {
    throw new Error('브라우저가 발행 파일 SHA-256 검증을 지원하지 않습니다.');
  }
  const digest = await globalThis.crypto.subtle.digest(
    'SHA-256',
    new TextEncoder().encode(text),
  );
  return [...new Uint8Array(digest)]
    .map((value) => value.toString(16).padStart(2, '0'))
    .join('');
}

const FETCH_TIMEOUT_MS = 6500;
const FETCH_ATTEMPTS = 3;

async function fetchWithRetry(url, options = {}) {
  let lastError = null;
  for (let attempt = 0; attempt < FETCH_ATTEMPTS; attempt += 1) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
    try {
      const response = await fetch(url, { ...options, signal: controller.signal });
      if (response.ok || attempt === FETCH_ATTEMPTS - 1) return response;
      lastError = new Error(`TRZIP request ${response.status}`);
    } catch (error) {
      lastError = error;
    } finally {
      clearTimeout(timer);
    }
    await new Promise((resolve) => setTimeout(resolve, 250 * (attempt + 1)));
  }
  throw lastError || new Error('TRZIP request failed');
}

async function fetchManifestRankings(nonce) {
  const manifestResponse = await fetchWithRetry(`${MANIFEST_URL}?t=${nonce}`, { cache: 'no-store' });
  if (!manifestResponse.ok) throw new Error(`TRZIP manifest ${manifestResponse.status}`);
  const manifest = await manifestResponse.json();
  const entry = manifest?.bundle?.presentation || manifest?.bundle?.rankings || {};
  const relativePath = String(entry.path || '').replace(/^latest\//, '');
  if (!/^delivery\/[A-Za-z0-9._-]+\/(presentation|rankings)\.json$/.test(relativePath)) {
    throw new Error('TRZIP manifest의 순위 파일 경로가 올바르지 않습니다.');
  }
  if (!/^[a-f0-9]{64}$/i.test(String(entry.sha256 || ''))) {
    throw new Error('TRZIP manifest의 순위 파일 해시가 올바르지 않습니다.');
  }
  const rankingsResponse = await fetchWithRetry(
    `${LIVE_DATA_BASE}/${relativePath}?t=${nonce}`,
    { cache: 'no-store' },
  );
  if (!rankingsResponse.ok) throw new Error(`TRZIP rankings ${rankingsResponse.status}`);
  const rankingsText = await rankingsResponse.text();
  if ((await sha256Hex(rankingsText)) !== String(entry.sha256).toLowerCase()) {
    throw new Error('TRZIP 순위 파일의 SHA-256이 manifest와 일치하지 않습니다.');
  }
  const rankings = JSON.parse(rankingsText);
  if (
    rankings.publication_id !== manifest.publication_id
    || rankings.generated_at !== manifest.generated_at
    || rankings.observed_at !== manifest.observed_at
  ) {
    throw new Error('TRZIP manifest와 순위 파일의 발행 식별자가 일치하지 않습니다.');
  }
  return rankings;
}

function viewModel(bundle, { source, fromCache }) {
  const { payload, metadata, runtimeStatus, publication } = bundle;
  const status = dataStatus(payload, metadata, runtimeStatus, { fromCache });
  const presentationRows = payload.presentation_feed?.frontend_default
    ? (payload.presentation_feed.items || [])
    : [];
  const rankingByTopic = new Map(payload.unified_ranking.map((item) => [item.topic, item]));
  const publicRows = presentationRows.length
    ? presentationRows
    : (payload.public_top10 || [])
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
    publication,
    metadata,
    raw: payload,
  };
}

async function loadTrends({ mode = 'live' } = {}) {
  if (mode !== 'live') throw new Error('운영 화면은 live-data만 사용합니다.');
  try {
    const nonce = Date.now();
    const [rankings, statusResponse, metadataResponse] = await Promise.all([
      fetchManifestRankings(nonce),
      fetchWithRetry(`${STATUS_URL}?t=${nonce}`, { cache: 'no-store' }),
      fetchWithRetry(`${METADATA_URL}?t=${nonce}`, { cache: 'no-store' }),
    ]);
    if (!statusResponse.ok) throw new Error(`TRZIP status ${statusResponse.status}`);
    if (!metadataResponse.ok) throw new Error(`TRZIP metadata ${metadataResponse.status}`);
    const bundle = validatedBundle(
      rankings,
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

function sortTrends(trends, mode = 'score') {
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

function listPortfolios() {
  const stored = readJson(PORTFOLIO_KEY, []);
  return Array.isArray(stored) ? stored.map(normalizePortfolio).filter(Boolean) : [];
}

function getPortfolio(id) {
  return listPortfolios().find((portfolio) => portfolio.id === String(id)) || null;
}

function savePortfolio(input) {
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

const dataContract = Object.freeze({
  manifest: MANIFEST_URL,
  intelligence: INTELLIGENCE_URL,
  status: STATUS_URL,
  metadata: METADATA_URL,
  cache: CACHE_KEY,
  portfolios: PORTFOLIO_KEY,
  freshForMinutes: FRESH_FOR_MINUTES,
  staleAfterMinutes: STALE_AFTER_MINUTES,
});

globalThis.TRZIP_DATA_API = Object.freeze({
  validatedBundle,
  loadTrends,
  sortTrends,
  listPortfolios,
  getPortfolio,
  savePortfolio,
  dataContract,
});
