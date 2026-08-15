const LIVE_DATA_BASE = 'https://raw.githubusercontent.com/jyy7294/noinbada/live-data/latest';
const MANIFEST_URL = `${LIVE_DATA_BASE}/manifest.json`;
const INTELLIGENCE_URL = `${LIVE_DATA_BASE}/intelligence.json`;
const STATUS_URL = `${LIVE_DATA_BASE}/status.json`;
const METADATA_URL = `${LIVE_DATA_BASE}/metadata.json`;
const CACHE_KEY = 'trzip:latest-intelligence:v3';
const PORTFOLIO_KEY = 'trzip:portfolios:v1';
const ARCHIVE_URL = './trend-archive.json';
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
              ? `${unavailableSources.join(', ')} 수집이 완료되지 않았습니다.`
              : 'X와 Google Trends 최신 수집을 모두 확인했습니다.',
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

function validatedArchive(payload) {
  if (
    payload?.schema_version !== 'trzip-archive-feed-v1'
    || payload?.data_mode !== 'reconstructed_reference'
    || payload?.display_mode !== 'historical_research_archive'
    || payload?.live_eligible !== false
    || payload?.ranking_eligible !== false
    || payload?.ranking_effect !== 'none'
    || !Array.isArray(payload?.items)
    || payload.items.length !== Number(payload.item_count)
  ) {
    throw new Error('지난 트렌드 자료의 데이터 계약이 올바르지 않습니다.');
  }
  for (const item of payload.items) {
    if (
      !item?.id
      || !item?.display_name
      || !item?.why_now
      || !Array.isArray(item?.evidence_urls)
      || !item.evidence_urls.some((url) => /^https?:\/\//.test(String(url)))
      || !Array.isArray(item?.companies)
      || item.companies.length < 1
      || Object.hasOwn(item, 'rank')
    ) {
      throw new Error('지난 트렌드 항목의 필수 근거가 누락되었습니다.');
    }
  }
  return payload;
}

async function loadArchive() {
  const response = await fetchWithRetry(`${ARCHIVE_URL}?t=${Date.now()}`, { cache: 'no-store' });
  if (!response.ok) throw new Error(`TRZIP archive ${response.status}`);
  return validatedArchive(await response.json());
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
  'verified_safe_svg', 'verified_raster_min_64px', 'initials_fallback',
]);

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
  if (mode === 'initials') {
    return company.logo_asset_source === 'initials_fallback'
      && verification === 'initials_fallback'
      && !logoUrl && !mime && format === 'none'
      && width === 0 && height === 0 && !sha256
      && !String(company.logo_asset_host || '').trim()
      && !String(company.logo_rejected_asset_url || '').trim()
      && (!sourcePageUrl || publicHttpUrl(sourcePageUrl))
      && company.logo_asset_quality === 'fail_closed_initials_no_verified_asset';
  }
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

function validSparseVisualization(item) {
  const visualization = item?.visualization_series || {};
  if (
    visualization.data_mode !== 'observed_sparse'
    || visualization.interpolation !== 'none'
    || visualization.canonical_series_unchanged !== true
    || visualization.ranking_effect !== 'none'
  ) return false;
  return ['1w', '1m', '3m'].every((key) => {
    const window = visualization[key] || {};
    if (
      window.interpolation !== 'none'
      || window.missing_point_policy !== 'preserve_sparse_null_no_reuse'
      || window.ranking_effect !== 'none'
      || !Array.isArray(window.points)
      || window.points.length === 0
      || window.available_point_count !== window.points.length
    ) return false;
    let previousAt = -Infinity;
    const seen = new Set();
    return window.points.every((point) => {
      const at = asDate(point?.at);
      const atMs = at?.getTime();
      const sources = Array.isArray(point?.observed_sources) ? point.observed_sources : [];
      const valueSources = ['x', 'google_trends']
        .filter((source) => point?.[source] != null);
      const values = valueSources.map((source) => Number(point[source]));
      const combined = values.length
        ? Math.round((values.reduce((sum, value) => sum + value, 0) / values.length) * 100) / 100
        : null;
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
        && combined === Number(point?.combined);
      if (valid) {
        previousAt = atMs;
        seen.add(atMs);
      }
      return valid;
    });
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
  const companyIdentities = new Set(companies.map((company) => (
    `${String(company?.exchange || company?.market || '').trim()}\u0000${String(company?.stock_code || company?.ticker || '').trim()}`
  )));
  const keywordNames = new Set(keywordTexts);
  const linkedKeywords = new Set();
  links.forEach((link) => {
    const keyword = normalizedPublicKeyword(link?.keyword);
    const company = String(link?.company || '').trim();
    const evidence = Array.isArray(link?.evidence_urls) ? link.evidence_urls : [];
    if (
      keywordNames.has(keyword)
      && companyNames.has(company)
      && String(link?.connection_explanation || link?.relationship_reason || '').trim()
      && evidence.length > 0
      && evidence.every((url) => publicHttpUrl(url))
    ) linkedKeywords.add(keyword);
  });
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
    && roles.size >= 2
    && roles.size <= 4
    && context.status === 'ready'
    && String(context.trigger_title || '').trim()
    && String(context.why_now || '').trim()
    && Array.isArray(context.evidence_urls)
    && context.evidence_urls.length > 0
    && context.evidence_urls.every((url) => publicHttpUrl(url))
    && linkedKeywords.size >= 2
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
    && logoPolicy.low_resolution_fallback === 'initials'
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
  archive: ARCHIVE_URL,
  cache: CACHE_KEY,
  portfolios: PORTFOLIO_KEY,
  freshForMinutes: FRESH_FOR_MINUTES,
  staleAfterMinutes: STALE_AFTER_MINUTES,
});

globalThis.TRZIP_DATA_API = Object.freeze({
  validatedBundle,
  loadTrends,
  loadArchive,
  validatedArchive,
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
