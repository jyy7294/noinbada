const DEFAULT_LIVE_DATA_BASE = 'https://raw.githubusercontent.com/jyy7294/noinbada/live-data/latest';
// Local browser QA may point at the freshly generated immutable publication.
// The override is deliberately disabled on every non-local hostname so a URL
// parameter can never redirect production users to an untrusted data source.
const LOCAL_QA_DATA_BASE = ['127.0.0.1', 'localhost'].includes(globalThis.location?.hostname)
  ? new URLSearchParams(globalThis.location.search).get('dataBase')
  : null;
const LIVE_DATA_BASE = LOCAL_QA_DATA_BASE
  ? new URL(LOCAL_QA_DATA_BASE, globalThis.location.href).href.replace(/\/$/, '')
  : DEFAULT_LIVE_DATA_BASE;
const MANIFEST_URL = `${LIVE_DATA_BASE}/manifest.json`;
const INTELLIGENCE_URL = `${LIVE_DATA_BASE}/intelligence.json`;
const STATUS_URL = `${LIVE_DATA_BASE}/status.json`;
const METADATA_URL = `${LIVE_DATA_BASE}/metadata.json`;
const CACHE_KEY = 'trzip:latest-intelligence:v3';
const PORTFOLIO_KEY = 'trzip:portfolios:v1';
const SHOWCASE_MANIFEST_URL = './showcase/manifest.json';
// The public home feed is an immutable daily publication created at 06:00 KST,
// not an hourly endpoint. Keep a successful publication current until the next
// daily slot, then allow a short delivery grace period before failing closed.
const FRESH_FOR_MINUTES = 24 * 60;
const STALE_AFTER_MINUTES = 26 * 60;

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
      ? '네트워크가 원활하지 않아 최근 공개 데이터를 표시합니다.'
      : snapshotMismatch
        ? '순위와 수집 상태의 기준시각이 일치하지 않습니다.'
        : !observedAt
          ? '관측 기준시각을 확인할 수 없습니다.'
          : ageMinutes > STALE_AFTER_MINUTES
            ? `마지막 관측 후 ${ageMinutes}분이 지나 최신 상태가 아닙니다.`
            : delayed
              ? `마지막 관측 후 ${ageMinutes}분이 지나 다음 수집을 기다리고 있습니다.`
            : partial
              ? '일부 원천 수집이 완료되지 않아 통합 결과를 확인하고 있습니다.'
              : '최신 통합 트렌드 수집을 확인했습니다.',
  };
}

function rankMovement(item, presentationItem) {
  const explicit = item.rank_movement;
  if (
    explicit
    && ['new', 'unchanged', 'up', 'down'].includes(explicit.status)
    && typeof explicit.label === 'string'
  ) {
    return explicit;
  }
  if (presentationItem) {
    return {
      current_rank: Number(item.presentation_position || item.current_rank || 0),
      previous_rank: null,
      delta: null,
      status: 'new',
      label: 'NEW',
      basis: 'previous_published_presentation_feed',
    };
  }
  const periodChange = Number.isFinite(item.rank_change) ? Number(item.rank_change) : null;
  const sourceValues = Object.values(item.rank_change_by_source || {}).filter(Number.isFinite);
  const change = periodChange == null && sourceValues.length
    ? [...sourceValues].sort((a, b) => Math.abs(b) - Math.abs(a))[0]
    : periodChange;
  if (change == null || item.rank_change_status === 'new_in_period') {
    return { status: 'new', label: 'NEW', delta: null, previous_rank: null };
  }
  if (change === 0) {
    return { status: 'unchanged', label: '유지', delta: 0 };
  }
  return {
    status: change > 0 ? 'up' : 'down',
    label: change > 0 ? `▲${change}` : `▼${Math.abs(change)}`,
    delta: change,
  };
}

function normalizeTrend(item) {
  const presentationItem = ['observed_reference', 'observed_live'].includes(item.data_mode);
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
  const movement = rankMovement(item, presentationItem);
  return {
    id: topic,
    topic,
    displayName: item.display_name || topic,
    shortDisplayName: item.short_display_name || item.display_name || topic,
    rank,
    rankLabel: String(rank || '--').padStart(2, '0'),
    category: item.category,
    categoryKo: item.category_label || CATEGORY_KO[item.category] || '기타',
    delta: movement.label,
    rankMovement: movement,
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
      label: '관심지수 추이',
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

const LIVE_COMPANY_ROLES = new Set([
  'manufacturing_development', 'raw_materials_components', 'content_production',
  'distribution', 'retail_sales', 'brand_marketing', 'platform_service',
  'ownership_investment', 'event_sponsorship',
]);
const LIVE_LOGO_VERIFICATIONS = new Set([
  'verified_safe_svg', 'verified_raster_min_64px',
]);
const LIVE_LISTING_EVIDENCE_TYPES = new Set([
  'exchange_current_security_universe', 'official_current_security_register',
]);
const LIVE_PUBLIC_MARKET_SESSION_COUNT = 30;
const LIVE_LISTING_FRESHNESS_DAYS = 4;
const LIVE_LISTING_POST_OBSERVATION_AUDIT_DAYS = 1;
const LIVE_MARKET_FIELD_POST_OBSERVATION_AUDIT_DAYS = 1;
const LIVE_MARKET_FIELD_FRESHNESS_DAYS = Object.freeze({
  price_series: 7,
  market_cap_krw: 7,
  per: 14,
  pbr: 14,
  roe_pct: 400,
});
const LIVE_PER_UNAVAILABLE_STATUSES = new Set([
  'unavailable_loss_making', 'unavailable_not_reported', 'unavailable_stale',
]);
const LIVE_ATTENTION_WINDOW_SPECS = Object.freeze({
  '1w': { hours: 168, label: '1주' },
  '1m': { hours: 720, label: '1개월' },
  '3m': { hours: 2160, label: '3개월' },
});
const LIVE_RANK_RESPONSIVE_FORMULA_VERSION = 'observed-rank-response-v2';
const LIVE_RANK_RESPONSIVE_FORMULA_WEIGHTS = Object.freeze({
  source_rank_position: 0.45,
  rank_change: 0.20,
  observation_persistence: 0.15,
  presentation_position: 0.20,
});
const LIVE_RANK_RESPONSIVE_DERIVATION = Object.freeze({
  formula: 'mean_by_observed_source(weighted_sum(source_rank_position,rank_change,observation_persistence,presentation_position))',
  input_fields: Object.freeze([
    'observed_source_rank',
    'observed_source_rank_change',
    'observation_persistence',
    'presentation_position',
    'previous_published_presentation_position',
  ]),
  missing_component_policy: 'neutral_50_for_unavailable_rank_change',
  neutral_rank_change_index: 50.0,
  formula_weight_sum: 1.0,
  display_only: true,
  canonical_ranking_effect: 'none',
  display_rank_effect: 'display_value_only',
  market_data_affected: false,
  canonical_series_unchanged: true,
  missing_point_policy: 'preserve_sparse_null_no_reuse',
});

function publicHttpUrl(value, { httpsOnly = false } = {}) {
  try {
    const parsed = new URL(String(value || '').trim());
    return Boolean(parsed.hostname)
      && (httpsOnly ? parsed.protocol === 'https:' : ['http:', 'https:'].includes(parsed.protocol));
  } catch (_) {
    return false;
  }
}

function normalizedPublicKeyword(value) {
  return String(value || '').trim().replace(/\s+/gu, ' ');
}

function keywordFitsPublicLabel(value) {
  const text = normalizedPublicKeyword(value);
  return text.length > 0 && [...text.replace(/\s+/gu, '')].length <= 6;
}

function ontologyPathReachesCompany(path, companyName) {
  if (!Array.isArray(path) || path.length < 2) return false;
  const target = normalizedPublicKeyword(companyName).toLocaleLowerCase();
  return path.some((step) => {
    const values = typeof step === 'string'
      ? [step]
      : (step && typeof step === 'object'
        ? ['to', 'target', 'label', 'name'].map((key) => step[key]) : []);
    return values.some((value) => value
      && normalizedPublicKeyword(value).toLocaleLowerCase() === target);
  });
}

function validLiveLogo(company) {
  if (!company || typeof company !== 'object') return false;
  const mode = String(company.logo_render_mode || '').trim();
  const logoUrl = String(company.logo_url || '').trim();
  const sourcePageUrl = String(company.logo_source_page_url || '').trim();
  const mime = String(company.logo_asset_mime || '').trim().toLowerCase();
  const format = String(company.logo_asset_format || '').trim().toLowerCase();
  const sha256 = String(company.logo_asset_sha256 || '').trim().toLowerCase();
  const verification = String(company.logo_asset_verification || '').trim();
  const width = company.logo_asset_width;
  const height = company.logo_asset_height;
  const provenance = company.logo_provenance;
  if (
    company.logo_quality_policy !== 'avatar-sharpness-v1'
    || company.logo_minimum_dimension !== 64
    || company.logo_runtime_probe_required !== false
    || !LIVE_LOGO_VERIFICATIONS.has(verification)
    || !provenance || typeof provenance !== 'object'
    || (provenance.source_page_url || '') !== sourcePageUrl
    || (provenance.asset_url || '') !== logoUrl
    || (provenance.mime || '') !== mime
    || provenance.width !== width
    || provenance.height !== height
    || (provenance.sha256 || '') !== sha256
    || provenance.verification !== verification
  ) return false;
  if (mode !== 'image' || !['verified_safe_svg', 'verified_raster_min_64px'].includes(verification)) {
    return false;
  }
  let logo;
  let page;
  try {
    logo = new URL(logoUrl);
    page = new URL(sourcePageUrl);
  } catch (_) {
    return false;
  }
  const dimensionsValid = Number.isInteger(width) && Number.isInteger(height)
    && width > 0 && height > 0
    && (verification === 'verified_safe_svg'
      ? format === 'svg'
      : width >= 64 && height >= 64 && ['png', 'jpeg', 'gif', 'webp', 'bmp', 'ico'].includes(format));
  return company.logo_asset_source === 'official_page_asset'
    && logo.protocol === 'https:' && Boolean(logo.hostname)
    && ['http:', 'https:'].includes(page.protocol) && Boolean(page.hostname)
    && String(company.official_domain || '').trim().toLowerCase() === page.hostname.toLowerCase()
    && String(company.logo_asset_host || '').trim().toLowerCase() === logo.hostname.toLowerCase()
    && mime.startsWith('image/') && /^[0-9a-f]{64}$/.test(sha256)
    && dimensionsValid
    && !String(company.logo_rejected_asset_url || '').trim()
    && ['verified_vector', 'verified_raster_min_64px'].includes(company.logo_asset_quality);
}

function finitePublicNumber(value, { positive = false } = {}) {
  return typeof value === 'number'
    && Number.isFinite(value)
    && (!positive || value > 0);
}

function publicCalendarDayMs(value) {
  const text = String(value || '').trim();
  const match = /^(\d{4})-(\d{2})-(\d{2})/u.exec(text);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const timestamp = Date.UTC(year, month - 1, day);
  const parsed = new Date(timestamp);
  return parsed.getUTCFullYear() === year
    && parsed.getUTCMonth() === month - 1
    && parsed.getUTCDate() === day
    ? timestamp : null;
}

function validLiveMarketFieldDate(value, field, observedAt) {
  const observed = asDate(observedAt);
  const fieldDay = publicCalendarDayMs(value);
  const maxAgeDays = LIVE_MARKET_FIELD_FRESHNESS_DAYS[field];
  if (!observed || fieldDay == null || !Number.isFinite(maxAgeDays)) return false;
  const observedDay = Date.UTC(
    observed.getUTCFullYear(), observed.getUTCMonth(), observed.getUTCDate(),
  );
  const ageDays = (observedDay - fieldDay) / (24 * 60 * 60 * 1000);
  return ageDays >= -LIVE_MARKET_FIELD_POST_OBSERVATION_AUDIT_DAYS
    && ageDays <= maxAgeDays;
}

function validLiveListingVerification(verification, company, observedAt) {
  if (!verification || typeof verification !== 'object') return false;
  const observed = asDate(observedAt);
  const verifiedDay = publicCalendarDayMs(verification.as_of);
  if (!observed || verifiedDay == null) return false;
  const observedDay = Date.UTC(
    observed.getUTCFullYear(), observed.getUTCMonth(), observed.getUTCDate(),
  );
  const ageDays = (observedDay - verifiedDay) / (24 * 60 * 60 * 1000);
  const expectedExchange = String(company?.exchange || company?.market || '').trim().toUpperCase();
  const expectedCode = String(company?.stock_code || company?.ticker || '').trim().toUpperCase();
  return verification.status === 'verified_current'
    && verification.current_listed === true
    && LIVE_LISTING_EVIDENCE_TYPES.has(verification.evidence_type)
    && String(verification.evidence_owner || '').trim()
    && publicHttpUrl(verification.evidence_url)
    && verification.synthetic === false
    && verification.estimated === false
    && verification.ranking_effect === 'none'
    && String(verification.exchange || '').trim().toUpperCase() === expectedExchange
    && String(verification.stock_code || '').trim().toUpperCase() === expectedCode
    && ageDays >= -LIVE_LISTING_POST_OBSERVATION_AUDIT_DAYS
    && ageDays <= LIVE_LISTING_FRESHNESS_DAYS;
}

function validObservedMarketSessions(points) {
  if (!Array.isArray(points) || points.length !== LIVE_PUBLIC_MARKET_SESSION_COUNT) return false;
  const dates = points.map((row) => (row && typeof row === 'object'
    ? String(row.date || '').trim() : ''));
  return dates.every(Boolean)
    && dates.every((date, index) => index === 0 || dates[index - 1] < date)
    && new Set(dates).size === LIVE_PUBLIC_MARKET_SESSION_COUNT
    && points.every((row) => finitePublicNumber(row?.close, { positive: true }));
}

function validLiveMarketSnapshot(company, observedAt) {
  const snapshot = company?.market_snapshot;
  if (!snapshot || typeof snapshot !== 'object') return false;
  const points = snapshot.price_points;
  const series = snapshot.price_series;
  if (
    !validObservedMarketSessions(points)
    || !Array.isArray(series)
    || series.length !== LIVE_PUBLIC_MARKET_SESSION_COUNT
    || !series.every((value, index) => value === points[index].close)
  ) return false;
  const provenance = snapshot.field_provenance;
  if (!provenance || typeof provenance !== 'object') return false;
  const validProvenance = [
    'price_series', 'market_cap_krw', 'pbr', 'roe_pct',
  ].every((field) => {
    const row = provenance[field];
    return row && typeof row === 'object'
      && String(row.provider || '').trim()
      && String(row.as_of || '').trim()
      && publicHttpUrl(row.source_url)
      && row.synthetic === false
      && row.estimated === false
      && validLiveMarketFieldDate(row.as_of, field, observedAt);
  });
  const perStatus = String(snapshot.per_status || '').trim();
  const perProvenance = provenance.per;
  const validPer = perStatus === 'observed'
    ? finitePublicNumber(snapshot.per, { positive: true })
      && publicHttpUrl(snapshot.per_source_url)
      && perProvenance && typeof perProvenance === 'object'
      && String(perProvenance.provider || '').trim()
      && publicHttpUrl(perProvenance.source_url)
      && perProvenance.synthetic === false
      && perProvenance.estimated === false
      && validLiveMarketFieldDate(perProvenance.as_of, 'per', observedAt)
    : LIVE_PER_UNAVAILABLE_STATUSES.has(perStatus) && snapshot.per == null;
  return validProvenance
    && validPer
    && snapshot.status === 'observed'
    && snapshot.synthetic === false
    && snapshot.estimated === false
    && snapshot.display_only === true
    && snapshot.ranking_effect === 'none'
    && String(snapshot.provider || '').trim()
    && String(snapshot.source || '').trim()
    && String(snapshot.as_of || '').trim()
    && publicHttpUrl(snapshot.source_url)
    && publicHttpUrl(snapshot.price_source_url)
    && finitePublicNumber(snapshot.market_cap_krw, { positive: true })
    && snapshot.market_cap === snapshot.market_cap_krw
    && snapshot.market_cap_currency === 'KRW'
    && finitePublicNumber(snapshot.native_market_cap, { positive: true })
    && finitePublicNumber(snapshot.fx_rate_to_krw, { positive: true })
    && String(snapshot.fx_as_of || '').trim()
    && String(snapshot.fx_provider || '').trim()
    && publicHttpUrl(snapshot.fx_source_url)
    && publicHttpUrl(snapshot.market_cap_source_url)
    && finitePublicNumber(snapshot.pbr, { positive: true })
    && finitePublicNumber(snapshot.roe_pct)
    && publicHttpUrl(snapshot.pbr_source_url)
    && publicHttpUrl(snapshot.roe_source_url)
    && validLiveListingVerification(company.listing_verification, company, observedAt);
}

function validObservedSeries(item, observedAt) {
  const end = asDate(observedAt);
  if (!end) return false;
  const startMs = end.getTime() - (23 * 60 * 60 * 1000);
  return Array.isArray(item?.series) && item.series.some((point) => {
    const at = asDate(point?.at);
    return at
      && at.getTime() >= startMs
      && at.getTime() <= end.getTime()
      && point?.provenance === 'observed'
      && ['x', 'google_trends'].includes(point?.source)
      && Number.isFinite(Number(point?.value))
      && Number(point.value) >= 0
      && Number(point.value) <= 100;
  });
}

function validNormalizedIndex(value) {
  if (value == null || value === '' || typeof value === 'boolean') return false;
  const numeric = Number(value);
  return Number.isFinite(numeric) && numeric >= 0 && numeric <= 100;
}

function validRankResponsiveFormulaWeights(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const keys = Object.keys(LIVE_RANK_RESPONSIVE_FORMULA_WEIGHTS);
  return Object.keys(value).sort().join('|') === keys.slice().sort().join('|')
    && keys.every((key) => Number(value[key]) === LIVE_RANK_RESPONSIVE_FORMULA_WEIGHTS[key]);
}

function sameContractValue(left, right) {
  if (left === right) return true;
  if (Array.isArray(left) || Array.isArray(right)) {
    return Array.isArray(left) && Array.isArray(right)
      && left.length === right.length
      && left.every((value, index) => sameContractValue(value, right[index]));
  }
  if (!left || !right || typeof left !== 'object' || typeof right !== 'object') return false;
  const leftKeys = Object.keys(left).sort();
  const rightKeys = Object.keys(right).sort();
  return leftKeys.join('|') === rightKeys.join('|')
    && leftKeys.every((key) => sameContractValue(left[key], right[key]));
}

function validRankResponsiveDerivation(value) {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
    && sameContractValue(value, LIVE_RANK_RESPONSIVE_DERIVATION);
}

function validRankResponsiveSourceComponent(component, pointValue, presentationPosition) {
  if (!component || typeof component !== 'object' || Array.isArray(component)) return false;
  const integerValue = (value) => value !== ''
    && typeof value !== 'boolean'
    && Number.isInteger(Number(value));
  const positiveInteger = (value) => integerValue(value) && Number(value) > 0;
  const optionalInteger = (value) => value == null || integerValue(value);
  const componentKeys = [
    'rank', 'snapshot_size', 'position_index', 'rank_basis', 'previous_rank',
    'rank_change', 'rank_change_index', 'source_rank_change_index',
    'public_rank_change_index', 'rank_change_basis',
    'observation_persistence_index', 'presentation_position',
    'presentation_position_index', 'presentation_rank_change', 'display_index',
  ];
  const rankChangeBasis = Array.isArray(component.rank_change_basis)
    ? component.rank_change_basis : [];
  const sourceBasis = rankChangeBasis[0];
  const publicBasis = rankChangeBasis[1];
  const sourceBasisValid = ['previous_observed_source_rank', 'neutral_unavailable_source_rank_change']
    .includes(sourceBasis);
  const publicBasisValid = [
    'previous_published_presentation_position',
    'neutral_unavailable_public_rank_change',
    'neutral_public_change_not_latest_point',
  ].includes(publicBasis);
  return Object.keys(component).sort().join('|') === componentKeys.slice().sort().join('|')
    && positiveInteger(component.rank)
    && positiveInteger(component.snapshot_size)
    && Number(component.snapshot_size) >= Number(component.rank)
    && validNormalizedIndex(component.position_index)
    && ['explicit_observed_source_rank', 'legacy_101_minus_rank_proxy']
      .includes(component.rank_basis)
    && (component.previous_rank == null || positiveInteger(component.previous_rank))
    && optionalInteger(component.rank_change)
    && validNormalizedIndex(component.rank_change_index)
    && validNormalizedIndex(component.source_rank_change_index)
    && validNormalizedIndex(component.public_rank_change_index)
    && rankChangeBasis.length === 2
    && new Set(rankChangeBasis).size === 2
    && sourceBasisValid
    && publicBasisValid
    && (sourceBasis !== 'neutral_unavailable_source_rank_change'
      || Number(component.source_rank_change_index) === 50)
    && (!publicBasis.startsWith('neutral_')
      || Number(component.public_rank_change_index) === 50)
    && (!(sourceBasis === 'neutral_unavailable_source_rank_change'
      && publicBasis.startsWith('neutral_'))
      || Number(component.rank_change_index) === 50)
    && validNormalizedIndex(component.observation_persistence_index)
    && Number(component.presentation_position) === presentationPosition
    && Number.isInteger(Number(component.presentation_position))
    && presentationPosition >= 1 && presentationPosition <= 10
    && validNormalizedIndex(component.presentation_position_index)
    && optionalInteger(component.presentation_rank_change)
    && (component.presentation_rank_change == null
      || (Number(component.presentation_rank_change) >= -9
        && Number(component.presentation_rank_change) <= 9))
    && validNormalizedIndex(component.display_index)
    && Number(component.display_index) === Number(pointValue);
}

function validSparseVisualization(item) {
  const visualization = item?.visualization_series || {};
  const hasRankResponsiveMetadata = visualization.data_mode === 'rank_responsive_display'
    || visualization.display_only != null
    || visualization.formula_version != null
    || visualization.formula_weights != null
    || visualization.derivation != null
    || visualization.presentation_position != null
    || visualization.presentation_rank_movement != null
    || visualization.canonical_ranking_effect != null
    || visualization.display_rank_effect != null
    || visualization.market_data_affected != null;
  const rankResponsive = visualization.data_mode === 'rank_responsive_display'
    && visualization.display_only === true
    && visualization.formula_version === LIVE_RANK_RESPONSIVE_FORMULA_VERSION;
  const presentationPosition = Number(visualization.presentation_position);
  if (
    visualization.data_mode !== (rankResponsive ? 'rank_responsive_display' : 'observed_sparse')
    || visualization.interpolation !== 'none'
    || visualization.canonical_series_unchanged !== true
    || visualization.ranking_effect !== 'none'
  ) return false;
  if (
    hasRankResponsiveMetadata
    && (!rankResponsive
      || !validRankResponsiveFormulaWeights(visualization.formula_weights)
      || visualization.metric !== 'normalized_attention_index'
      || !validRankResponsiveDerivation(visualization.derivation)
      || !Number.isInteger(presentationPosition)
      || presentationPosition < 1
      || presentationPosition > 10
      || presentationPosition !== Number(item?.presentation_position)
      || !sameContractValue(visualization.presentation_rank_movement, item?.rank_movement)
      || visualization.canonical_ranking_effect !== 'none'
      || visualization.display_rank_effect !== 'display_value_only'
      || visualization.market_data_affected !== false)
  ) return false;
  const attention = Array.isArray(item?.attention_windows) ? item.attention_windows : [];
  if (
    attention.length !== 3
    || attention.some((row, index) => row?.key !== Object.keys(LIVE_ATTENTION_WINDOW_SPECS)[index])
  ) return false;
  return Object.entries(LIVE_ATTENTION_WINDOW_SPECS).every(([key, spec], windowIndex) => {
    const window = visualization[key] || {};
    if (
      window.interpolation !== 'none'
      || window.missing_point_policy !== 'preserve_sparse_null_no_reuse'
      || window.ranking_effect !== 'none'
      || (rankResponsive && (
        window.display_only !== true
        || window.formula_version !== LIVE_RANK_RESPONSIVE_FORMULA_VERSION
        || window.canonical_ranking_effect !== 'none'
        || window.display_rank_effect !== 'display_value_only'
        || window.market_data_affected !== false
      ))
      || !Array.isArray(window.points)
      || window.points.length === 0
      || window.available_point_count !== window.points.length
    ) return false;
    let previousAt = -Infinity;
    const seen = new Set();
    const pointsValid = window.points.every((point) => {
      const at = asDate(point?.at);
      const atMs = at?.getTime();
      const sources = Array.isArray(point?.observed_sources) ? point.observed_sources : [];
      const valueSources = ['x', 'google_trends']
        .filter((source) => point?.[source] != null);
      const values = valueSources.map((source) => Number(point[source]));
      const combined = values.length
        ? Math.round((values.reduce((sum, value) => sum + value, 0) / values.length) * 100) / 100
        : null;
      const sourceComponents = point?.source_components;
      const rankResponsivePointValid = !rankResponsive || (
        point?.display_only === true
        && point?.formula_version === LIVE_RANK_RESPONSIVE_FORMULA_VERSION
        && point?.canonical_ranking_effect === 'none'
        && point?.display_rank_effect === 'display_value_only'
        && point?.market_data_affected === false
        && point?.ranking_effect === 'none'
        && Number.isFinite(Number(point?.observation_density))
        && Number(point.observation_density) >= 0
        && Number(point.observation_density) <= 1
        && sourceComponents && typeof sourceComponents === 'object'
        && !Array.isArray(sourceComponents)
        && Object.keys(sourceComponents).sort().join('|') === sources.slice().sort().join('|')
        && sources.every((source) => validRankResponsiveSourceComponent(
          sourceComponents[source], point[source], presentationPosition,
        ))
      );
      const valid = Number.isFinite(atMs)
        && atMs >= previousAt
        && !seen.has(atMs)
        && sources.length > 0
        && new Set(sources).size === sources.length
        && sources.every((source) => ['x', 'google_trends'].includes(source))
        && sources.length === valueSources.length
        && valueSources.every((source) => sources.includes(source))
        && values.length > 0
        && values.every((value) => Number.isFinite(value) && value >= 0 && value <= 100)
        && combined === Number(point?.combined)
        && rankResponsivePointValid;
      if (valid) {
        previousAt = atMs;
        seen.add(atMs);
      }
      return valid;
    });
    if (!pointsValid) return false;
    const firstAt = asDate(window.points[0]?.at)?.getTime();
    const lastAt = asDate(window.points.at(-1)?.at)?.getTime();
    const observedHours = window.points.length;
    const observedSpanHours = Math.round(((lastAt - firstAt) / (60 * 60 * 1000)) * 100) / 100;
    const minimumSpanHours = Math.round((spec.hours * 0.8) * 100) / 100;
    const minimumObservedHours = Math.max(2, Math.ceil(spec.hours * 0.2));
    const coverageRatio = Math.round((observedHours / spec.hours) * 10000) / 10000;
    const measurementReady = observedSpanHours >= minimumSpanHours
      && observedHours >= minimumObservedHours;
    const expectedStatus = measurementReady ? 'measured' : 'insufficient_observed_history';
    const firstCombined = Number(window.points[0]?.combined);
    const lastCombined = Number(window.points.at(-1)?.combined);
    const attentionStatus = !measurementReady
      ? 'insufficient_observed_history'
      : firstCombined === 0 ? 'unavailable_zero_baseline' : 'measured';
    const expectedPercent = attentionStatus === 'measured'
      ? Math.round((((lastCombined - firstCombined) / firstCombined) * 100) * 10) / 10
      : null;
    const expectedBasis = attentionStatus === 'measured'
      ? 'first_and_last_qualified_observed_point'
      : attentionStatus === 'unavailable_zero_baseline'
        ? 'unavailable_zero_baseline'
        : 'insufficient_window_span_or_coverage';
    const attentionRow = attention[windowIndex] || {};
    return window.status === expectedStatus
      && window.available_point_count === observedHours
      && window.available_from === window.points[0]?.at
      && window.available_to === window.points.at(-1)?.at
      && window.expected_window_hours === spec.hours
      && window.observed_span_hours === observedSpanHours
      && window.observed_hour_count === observedHours
      && window.coverage_ratio === coverageRatio
      && window.minimum_span_hours === minimumSpanHours
      && window.minimum_observed_hours === minimumObservedHours
      && attentionRow.key === key
      && attentionRow.label === spec.label
      && attentionRow.metric === 'normalized_attention_index_change'
      && attentionRow.status === attentionStatus
      && attentionRow.percent === expectedPercent
      && attentionRow.basis === expectedBasis
      && attentionRow.is_absolute_mention_count === false
      && attentionRow.ranking_effect === 'none';
  });
}

function validLiveCard(item, observedAt) {
  const keywords = Array.isArray(item?.related_keywords)
    ? item.related_keywords : (Array.isArray(item?.keywords) ? item.keywords : []);
  const companies = Array.isArray(item?.companies) ? item.companies : [];
  const links = Array.isArray(item?.keyword_company_links) ? item.keyword_company_links : [];
  const context = item?.context_research || {};
  const itemEvidence = Array.isArray(item?.evidence_urls) ? item.evidence_urls : [];
  const keywordTexts = keywords
    .map((keyword) => normalizedPublicKeyword(keyword?.text || keyword?.term || keyword))
    .filter(Boolean);
  const companyNames = new Set(
    companies.map((company) => String(company?.company || company?.name || '').trim()).filter(Boolean),
  );
  const companyByName = new Map(
    companies.map((company) => [
      String(company?.company || company?.name || '').trim(), company,
    ]),
  );
  const companyIdentities = new Set(companies.map((company) => (
    `${String(company?.exchange || company?.market || '').trim()}\u0000${String(company?.stock_code || company?.ticker || '').trim()}`
  )));
  const keywordNames = new Set(keywordTexts);
  const linkedKeywords = new Set();
  const linkedCompanies = new Set();
  const linkKeywordsByCompany = new Map(
    [...companyNames].map((company) => [company, new Set()]),
  );
  const linkPairs = new Set();
  let validLinks = true;
  links.forEach((link) => {
    const keyword = normalizedPublicKeyword(link?.keyword);
    const company = String(link?.company || '').trim();
    const evidence = Array.isArray(link?.evidence_urls) ? link.evidence_urls : [];
    const companyRow = companyByName.get(company);
    const pair = `${keyword}\u0000${company}`;
    const valid = Boolean(
      keywordNames.has(keyword)
      && companyRow
      && String(link?.connection_explanation || link?.relationship_reason || '').trim()
      && evidence.length > 0
      && evidence.every((url) => publicHttpUrl(url))
      && String(link?.stock_code || '').trim()
        === String(companyRow?.stock_code || companyRow?.ticker || '').trim()
      && String(link?.company_role_category || '').trim()
        === String(companyRow?.company_role_category || '').trim()
      && String(link?.company_role_label || '').trim()
        === String(companyRow?.company_role_label || '').trim()
      && !linkPairs.has(pair)
    );
    if (!valid) {
      validLinks = false;
      return;
    }
    linkPairs.add(pair);
    linkedKeywords.add(keyword);
    linkedCompanies.add(company);
    linkKeywordsByCompany.get(company)?.add(keyword);
  });
  const matchedKeywordsValid = companies.every((company) => {
    const companyName = String(company?.company || company?.name || '').trim();
    const matched = Array.isArray(company?.matched_keywords)
      ? company.matched_keywords.map(normalizedPublicKeyword).filter(Boolean) : [];
    const matchedSet = new Set(matched);
    const linked = linkKeywordsByCompany.get(companyName) || new Set();
    return matched.length > 0
      && matchedSet.size === matched.length
      && [...matchedSet].every((keyword) => keywordNames.has(keyword) && linked.has(keyword))
      && [...linked].every((keyword) => matchedSet.has(keyword));
  });
  const coverage = item?.keyword_company_link_coverage || {};
  const declaredCoverageValid = coverage.policy_version === 'public-keyword-company-link-coverage-v1'
    && coverage.status === 'ready'
    && coverage.ready === true
    && coverage.keyword_count === 5
    && coverage.company_count === 10
    && Number.isInteger(coverage.valid_link_count)
    && coverage.valid_link_count === linkPairs.size
    && coverage.valid_link_count >= 10
    && coverage.linked_keyword_count === 5
    && coverage.linked_company_count === 10
    && ['unlinked_keywords', 'unlinked_companies', 'matched_keyword_mismatches', 'invalid_link_indexes', 'duplicate_pairs']
      .every((field) => Array.isArray(coverage[field]) && coverage[field].length === 0)
    && coverage.ranking_effect === 'none';
  const roles = new Set(companies.map((company) => company?.company_role_category).filter((role) => LIVE_COMPANY_ROLES.has(role)));
  return item?.selection_origin === 'canonical_validated_home_feed'
    && item?.lane === 'main'
    && item?.data_mode === 'observed_live'
    && item?.ranking_effect === 'none'
    && item?.observed_within_24h === true
    && Array.isArray(item?.sources)
    && item.sources.length > 0
    && new Set(item.sources).size === item.sources.length
    && item.sources.every((source) => ['x', 'google_trends'].includes(source))
    && validObservedSeries(item, observedAt)
    && validSparseVisualization(item)
    && String(item?.trend_definition || '').trim()
    && String(item?.why_now || '').trim()
    && itemEvidence.length > 0
    && itemEvidence.every((url) => publicHttpUrl(url))
    && keywords.length === 5
    && keywordTexts.length === 5
    && keywordNames.size === 5
    && keywordTexts.every(keywordFitsPublicLabel)
    && companies.length === 10
    && companyIdentities.size === 10
    && roles.size >= 3
    && roles.size <= 4
    && context.status === 'ready'
    && String(context.trigger_title || '').trim()
    && String(context.why_now || '').trim()
    && Array.isArray(context.evidence_urls)
    && context.evidence_urls.length > 0
    && context.evidence_urls.every((url) => publicHttpUrl(url))
    && links.length >= 10
    && validLinks
    && linkedKeywords.size === 5
    && linkedCompanies.size === 10
    && matchedKeywordsValid
    && declaredCoverageValid
    && companies.every((company) => company
      && LIVE_COMPANY_ROLES.has(company.company_role_category)
      && String(company.company || company.name || '').trim()
      && String(company.stock_code || '').trim()
      && String(company.exchange || '').trim()
      && String(company.company_description || '').trim()
      && String(company.connection_explanation || company.reason || '').trim()
      && String(company.company_role_label || '').trim()
      && company.ontology_complete === true
      && ontologyPathReachesCompany(company.ontology_path, company.company || company.name)
      && Array.isArray(company.evidence_sources)
      && company.evidence_sources.length > 0
      && company.evidence_sources.every((source) => publicHttpUrl(source?.url))
      && validLiveListingVerification(company.listing_verification, company, observedAt)
      && validLiveMarketSnapshot(company, observedAt)
      && validLiveLogo(company));
}

function selectLiveHomeRows(payload, { fromCache = false, stale = false } = {}) {
  const feed = payload?.presentation_feed || {};
  const items = Array.isArray(feed.items) ? feed.items : [];
  const logoPolicy = feed.logo_policy || {};
  const validLogoPolicy = logoPolicy.version === 'avatar-sharpness-v1'
    && logoPolicy.avatar_size_px === 44
    && logoPolicy.minimum_raster_dimension_px === 64
    && logoPolicy.vector_assets_allowed === true
    && logoPolicy.low_resolution_fallback === 'card_excluded'
    && logoPolicy.runtime_probe_for_generic_favicons === false
    && logoPolicy.official_page_resolver_required === true
    && logoPolicy.asset_sha256_required === true;
  const validStatus = (feed.status === 'empty' && items.length === 0)
    || (feed.status === 'ready' && items.length > 0 && items.length <= 10);
  const eventKeys = items.map((item) => String(item?.event_key || '').trim());
  const validItemIdentities = eventKeys.every(Boolean)
    && new Set(eventKeys).size === eventKeys.length
    && items.every((item, index) => item?.presentation_position === index + 1);
  const eligible = !fromCache
    && !stale
    && feed.schema_version === 'trzip-presentation-feed-v4'
    && feed.frontend_default === true
    && feed.selection_policy === 'validated_live_home_feed_v1'
    && asDate(feed.observed_at) != null
    && validLogoPolicy
    && feed.transition?.synthetic_data_used === false
    && feed.transition?.supplemental_display_data_used === false
    && feed.transition?.fallback_used === false
    && feed.transition?.padding_forbidden === true
    && feed.transition?.canonical_ranking_affected === false
    && validStatus
    && validItemIdentities
    && items.every((item) => validLiveCard(item, feed.observed_at));
  return { eligible, items: eligible ? items : [] };
}

function viewModel(bundle, { source, fromCache }) {
  const { payload, metadata, runtimeStatus, publication } = bundle;
  const status = dataStatus(payload, metadata, runtimeStatus, { fromCache });
  const liveHomeSelection = selectLiveHomeRows(payload, {
    fromCache,
    stale: status.stale,
  });
  const liveHomeEligible = liveHomeSelection.eligible;
  // An explicitly published empty feed is meaningful. Never refill it from an
  // older public_top10 array because that would leak stale topics into home.
  const publicRows = liveHomeSelection.items;
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
    liveHomeEligible,
  };
}

async function loadTrends({ mode = 'live' } = {}) {
  if (mode === 'showcase') return loadShowcase();
  if (mode !== 'live') throw new Error('지원하지 않는 데이터 모드입니다.');
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

function kstFloorHourIso(now = new Date()) {
  const shifted = new Date(now.getTime() + (9 * 60 * 60 * 1000));
  const pad = (value) => String(value).padStart(2, '0');
  return `${shifted.getUTCFullYear()}-${pad(shifted.getUTCMonth() + 1)}-${pad(shifted.getUTCDate())}`
    + `T${pad(shifted.getUTCHours())}:00:00+09:00`;
}

function validateShowcasePayload(payload, manifest) {
  if (!payload || payload.schema_version !== 'trzip-showcase-live-simulation-v1'
    || payload.mode !== 'showcase_live_simulation'
    || payload.display_status !== 'NOW'
    || payload.display_time_policy !== 'client_kst_floor_hour'
    || payload.source_ranking_mode !== 'actual_full_ledger_no_recency'
    || payload.enrichment_mode !== 'reconstructed_demo') {
    throw new Error('공개 데이터 계약을 확인할 수 없습니다.');
  }
  const cards = Array.isArray(payload.cards) ? payload.cards : [];
  if (cards.length !== 10 || Number(manifest.card_count) !== cards.length) {
    throw new Error('공개 카드 수가 올바르지 않습니다.');
  }
  const eventKeys = new Set();
  const allStockCodes = [];
  let totalCompanyCount = 0;
  cards.forEach((card, index) => {
    const companies = Array.isArray(card.companies) ? card.companies : [];
    const keywords = Array.isArray(card.related_keywords) ? card.related_keywords : [];
    const roles = new Set(companies.map((company) => String(company.company_role_category || '')));
    const stockCodes = new Set(companies.map((company) => (
      String(company.market || 'KRX') + ':' + String(company.stock_code || '')
    )));
    const eventKey = String(card.event_key || '');
    if (!eventKey || eventKeys.has(eventKey)
      || Number(card.presentation_order) !== index + 1
      || !Number.isInteger(Number(card.full_ledger_rank))
      || !Number.isFinite(Number(card.full_ledger_score))
      || keywords.length !== 5
      || new Set(keywords.map((keyword) => String(keyword.text || ''))).size !== 5
      || companies.length < 5 || companies.length > 10
      || stockCodes.size !== companies.length
      || roles.size < 3 || roles.size > 4
      || card.enrichment_mode !== 'reconstructed_demo'
      || card.ranking_effect !== 'none'
      || companies.some((company) => company.relationship_status !== 'reconstructed_demo'
        || company.ranking_effect !== 'none'
        || !String(company.connection_explanation || '').trim()
        || !/^https:\/\//.test(String(company.company_identity_url || ''))
        || !validLiveLogo(company)
        || !validLiveMarketSnapshot(company, payload.source_observed_at))) {
      throw new Error(`공개 카드 계약 오류: ${eventKey || index + 1}`);
    }
    totalCompanyCount += companies.length;
    allStockCodes.push(...stockCodes);
    eventKeys.add(eventKey);
  });
  if (Number(manifest.market_data && manifest.market_data.snapshot_count) !== totalCompanyCount
    || Number(manifest.market_data && manifest.market_data.unique_security_count) !== new Set(allStockCodes).size) {
    throw new Error('공개 기업 시장 데이터 개수가 일치하지 않습니다.');
  }
  return cards;
}

async function loadShowcase() {
  const nonce = Date.now();
  const manifestResponse = await fetchWithRetry(`${SHOWCASE_MANIFEST_URL}?t=${nonce}`, { cache: 'no-store' });
  if (!manifestResponse.ok) throw new Error(`TRZIP showcase manifest ${manifestResponse.status}`);
  const manifest = await manifestResponse.json();
  const entry = manifest && manifest.showcase;
  if (manifest.schema_version !== 'trzip-showcase-delivery-v1'
    || manifest.mode !== 'showcase_live_simulation'
    || manifest.display_status !== 'NOW'
    || manifest.display_time_policy !== 'client_kst_floor_hour'
    || Number(manifest.card_count) !== 10
    || Number(manifest.approval && manifest.approval.approved_count) !== 10
    || !manifest.market_data
    || manifest.market_data.status !== 'observed'
    || manifest.market_data.provider !== 'pykrx+yahoo_finance'
    || Number(manifest.market_data.snapshot_count) < 50
    || Number(manifest.market_data.snapshot_count) > 100
    || Number(manifest.market_data.unique_security_count) < 5
    || manifest.market_data.synthetic !== false
    || manifest.market_data.estimated !== false
    || manifest.market_data.ranking_effect !== 'none'
    || !manifest.company_logos
    || manifest.company_logos.status !== 'verified'
    || Number(manifest.company_logos.image_count) !== Number(manifest.market_data.snapshot_count)
    || Number(manifest.company_logos.fallback_count) !== 0
    || manifest.company_logos.source !== 'official_page_asset'
    || !entry || entry.path !== 'showcase.json'
    || !/^[a-f0-9]{64}$/i.test(String(entry.sha256 || ''))) {
    throw new Error('공개 manifest 계약을 확인할 수 없습니다.');
  }
  const payloadResponse = await fetchWithRetry(`./showcase/${entry.path}?t=${nonce}`, { cache: 'no-store' });
  if (!payloadResponse.ok) throw new Error(`TRZIP showcase ${payloadResponse.status}`);
  const payloadText = await payloadResponse.text();
  if ((await sha256Hex(payloadText)) !== String(entry.sha256).toLowerCase()) {
    throw new Error('공개 데이터 해시가 일치하지 않습니다.');
  }
  const payload = JSON.parse(payloadText);
  const cards = validateShowcasePayload(payload, manifest);
  return {
    source: 'showcase-publication',
    showcase: true,
    displayAsOf: kstFloorHourIso(),
    observedAt: payload.source_observed_at,
    cards,
    manifest,
    raw: payload,
  };
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
    emoji: String(record.emoji || '💜').trim().slice(0, 8) || '💜',
    trendTopic: record.trendTopic || null,
    observedAt: record.observedAt || null,
    keywords: Array.isArray(record.keywords)
      ? record.keywords.map((keyword) => String(keyword).slice(0, 6)).slice(0, 6) : [],
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

const UNSAFE_PORTFOLIO_TEXT = [
  /대통령|선거|정당|국회의원|정치인|정치\s*테마/i,
  /살인|성범죄|사망|참사|재난|사생활|폭로|신상\s*털/i,
  /혐오|비하|멸칭|장애인\s*비하|여성\s*혐오|남성\s*혐오/i,
  /무조건\s*오른|급등\s*보장|수익\s*보장|매수\s*추천|리딩방|작전주|상한가\s*보장/i,
];

function validatePortfolioContent(input = {}) {
  const text = [input.name, ...(input.keywords || [])]
    .map((value) => String(value || '').normalize('NFKC'))
    .join(' ');
  if (UNSAFE_PORTFOLIO_TEXT.some((pattern) => pattern.test(text))) {
    throw new Error('정치·범죄·혐오·수익 보장 표현은 공개할 수 없습니다.');
  }
  return true;
}

function savePortfolio(input) {
  validatePortfolioContent(input);
  const portfolios = listPortfolios();
  const keywords = [...new Set((input.keywords || [])
    .map((keyword) => String(keyword).trim().slice(0, 6))
    .filter(Boolean))]
    .slice(0, 6);
  const id = input.id || globalThis.crypto?.randomUUID?.() || `portfolio-${Date.now()}`;
  const record = normalizePortfolio({
    schemaVersion: 'trzip-portfolio-v1',
    id,
    name: String(input.name || '새 밈트폴리오').trim().slice(0, 80) || '새 밈트폴리오',
    emoji: String(input.emoji || '💜').trim().slice(0, 8) || '💜',
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

function deletePortfolio(id) {
  const target = String(id || '').trim();
  if (!target) throw new Error('삭제할 밈트폴리오를 찾지 못했습니다.');
  const current = listPortfolios();
  const next = current.filter((portfolio) => portfolio.id !== target);
  if (next.length === current.length) return false;
  if (!writeJson(PORTFOLIO_KEY, next)) {
    throw new Error('밈트폴리오를 삭제하지 못했습니다.');
  }
  return true;
}

const dataContract = Object.freeze({
  manifest: MANIFEST_URL,
  intelligence: INTELLIGENCE_URL,
  status: STATUS_URL,
  metadata: METADATA_URL,
  showcase: SHOWCASE_MANIFEST_URL,
  cache: CACHE_KEY,
  portfolios: PORTFOLIO_KEY,
  freshForMinutes: FRESH_FOR_MINUTES,
  staleAfterMinutes: STALE_AFTER_MINUTES,
});

globalThis.TRZIP_DATA_API = Object.freeze({
  validatedBundle,
  loadTrends,
  loadShowcase,
  sortTrends,
  listPortfolios,
  getPortfolio,
  savePortfolio,
  deletePortfolio,
  validatePortfolioContent,
  selectLiveHomeRows,
  dataStatus,
  dataContract,
});
