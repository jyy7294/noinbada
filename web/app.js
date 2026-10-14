/* TR ZIP mobile surface. Observations and claims come only from the runtime API. */
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const names = {google:'Google', youtube:'YouTube'};
const eventPattern = /^(evt_[a-f0-9]{20}|yt_[A-Za-z0-9_-]{1,30})$/;
const publicationPattern = /^[a-f0-9]{24}$/;
const bookmark = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3h12v18l-6-4-6 4z"/></svg>';
const folderIcon = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 7V5h7l2 2h9v13H3z"/></svg>';
const date = value => {
  const d = new Date(value);
  return value && Number.isFinite(d.getTime()) ? new Intl.DateTimeFormat('ko-KR', {timeZone:'Asia/Seoul',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false}).format(d)+' KST' : '확인 전';
};
const safeURL = value => {
  try { const url = new URL(value, location.origin); return ['https:','http:'].includes(url.protocol) && !url.username && !url.password ? url.href : '#'; }
  catch { return '#'; }
};
const safeImage = value => {
  try { const url = new URL(value, location.origin); return url.origin === location.origin && url.pathname.startsWith('/api/media/') ? url.pathname : ''; }
  catch { return ''; }
};
const hasSaved = id => Object.hasOwn(saved, id);
let data = null, view = 'dial', filter = 'all', dialIndex = 0, selectedId = null;
let activeScreen = 'home', route = {page:'home'}, renderToken = 0, detailRecord = null, connectionFailed = false;
const scrollPositions = new Map(), folderStates = new Map();
let saved = {}, storageReadable = true;
try {
  const stored = JSON.parse(localStorage.getItem('trzip.saved.v2') || '{}');
  if (!stored || typeof stored !== 'object' || Array.isArray(stored)) throw new Error('Invalid saved store');
  saved = stored;
} catch { storageReadable = false; }

// Lucian UX/UI Prompt #070, MIT © 2026 Seokwoooo. Demo notices and timed fake success are removed.
function toast(message, error = false) {
  const stack = $('toast-stack'), node = document.createElement('div');
  node.className = `toast ${error ? 'toast-error' : 'toast-ok'}`;
  const text = document.createElement('span'); text.textContent = message;
  const close = document.createElement('button'); close.type = 'button'; close.textContent = '×'; close.setAttribute('aria-label','알림 닫기');
  const remove = () => { node.classList.add('leaving'); setTimeout(() => node.remove(), 200); };
  close.addEventListener('click', remove); node.append(text,close); stack.append(node);
  while (stack.children.length > 3) stack.firstElementChild.remove();
  setTimeout(remove, error ? 6500 : 3500);
}

function toggleSave(item) {
  if (!item || !eventPattern.test(item.event_id)) return;
  if (!storageReadable) { toast('기존 저장 공간을 읽지 못했습니다. 브라우저 저장 설정을 확인해 주세요.', true); return; }
  const next = {...saved}, removing = hasSaved(item.event_id);
  if (removing) delete next[item.event_id];
  else next[item.event_id] = {title:item.title, saved_at:new Date().toISOString()};
  try { localStorage.setItem('trzip.saved.v2', JSON.stringify(next)); }
  catch { toast('저장하지 못했습니다. 브라우저 저장 공간을 확인해 주세요.', true); return; }
  saved = next;
  toast(removing ? '저장을 해제했습니다.' : '이 브라우저에 저장했습니다.');
  document.querySelectorAll('[data-save]').forEach(button => {
    const id = button.dataset.save; button.setAttribute('aria-pressed',String(hasSaved(id)));
    const title = data?.items.find(row => row.event_id === id)?.title || item.title;
    button.setAttribute('aria-label',`${title} ${hasSaved(id) ? '저장 해제' : '저장'}`);
  });
  if (detailRecord) updateDetailSave(detailRecord.item);
  renderSaved();
}

async function request(url) {
  let response;
  try { response = await fetch(url,{signal:AbortSignal.timeout(12000),cache:'no-store'}); }
  catch { throw new Error('서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.'); }
  if (!response.ok) {
    throw new Error(response.status === 404 ? '이 게시본을 더 이상 확인할 수 없습니다. 홈에서 새로 고침해 주세요.' : response.status === 503 ? '아직 사용할 수 있는 수집 데이터가 없습니다. 잠시 후 다시 확인해 주세요.' : '데이터를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.');
  }
  return response.json();
}

async function refresh() {
  const button = $('refresh'); if (button.disabled) return;
  button.disabled = true; button.textContent = '확인 중';
  try {
    const result = await request('/api/trends?limit=500');
    if (!publicationPattern.test(result.publication_id) || !Array.isArray(result.items) || !Array.isArray(result.sources)) throw new Error('데이터 형식을 확인하지 못했습니다.');
    data = result; connectionFailed = false; $('home-error').hidden = true;
    renderStatus(); renderHome(); renderSearch(); renderSaved();
  } catch (error) {
    connectionFailed = true; $('home-error').hidden = false; $('home-error').textContent = error.message;
    $('freshness').textContent = data ? '연결 지연 · 마지막 수신 내용' : '서버 연결 확인 필요'; $('signal').className = 'signal';
    if (!data) {
      $('scope').textContent = '수집 성공 여부를 확인하지 못했습니다.';
      $('dial-title').textContent = '연결을 기다리고 있어요';
      $('dial-source').textContent = '새로 고침으로 다시 확인하세요';
      $('dial-focus').disabled = true; $('dial').setAttribute('aria-busy','false');
      $('home-list').innerHTML = empty('데이터 연결을 기다리고 있습니다. 홈에서 새로 고침해 주세요.');
      renderSearch(); renderSaved();
    } else { renderHome(); renderSearch(); renderSaved(); }
  } finally { button.disabled = false; button.textContent = '새로 고침'; }
}

function renderStatus() {
  const fresh = data.sources.some(source => source.fresh) && !connectionFailed;
  $('signal').className = `signal${fresh ? ' fresh' : ''}`;
  $('freshness').textContent = fresh ? '자동 수집 · 10분마다 확인' : '수집 지연 · 마지막 성공 내용';
  $('observed').textContent = '기준 '+date(data.observed_at); $('observed').dateTime = data.observed_at || '';
  $('scope').textContent = data.sources.map(s => `${s.scope_label} ${s.row_count}개${s.coverage === 'limited' ? ' · 제한된 공개 목록' : ''}`).join(' / ') || '확인된 출처 없음';
  $('release-badge').textContent = data.mode === 'production' ? '공개 운영' : '운영 검증 중';
  $('ranking-note').textContent = data.sources.length === 1 && data.sources[0].coverage === 'limited' ? 'RSS 노출 순서입니다. 한국 전체 검색량 순위를 뜻하지 않습니다.' : '출처가 공개한 목록 순서입니다. 기업 연결은 순위를 바꾸지 않습니다.';
  $('count').textContent = `· ${data.items.length}개`;
  $('notice').textContent = data.mode === 'production' ? '출처별 관측 시각과 관계 근거를 확인하세요.' : '72시간 연속 운영 검증 중 · 실제 수집 데이터를 제공합니다.';
}

const empty = message => `<p class="empty-state">${esc(message)}</p>`;
const mainItems = () => data ? data.items.filter(item => item.lane !== 'issue').slice(0,10) : [];
function rows(items) {
  return items.map(item => `<article class="trend-row"><span class="row-rank">${esc(item.rank)}</span>${safeImage(item.image?.url) ? `<img class="trend-thumb" src="${esc(safeImage(item.image.url))}" alt="" loading="lazy">` : ''}<div class="row-copy"><button class="row-title" data-event="${esc(item.event_id)}">${esc(item.title)}</button><p class="row-meta">${esc(item.sources.map(s => names[s.source] || s.source).join(' · '))} · ${connectionFailed ? '마지막 수신 내용' : item.fresh ? '수집 확인' : '수집 지연'}${item.companies.length ? `<span>기업 ${item.companies.length}곳</span>` : item.lane === 'issue' ? '<span>사회·이슈</span>' : ''}</p></div><button class="row-save icon-button bookmark-button" data-save="${esc(item.event_id)}" aria-label="${esc(item.title)} ${hasSaved(item.event_id) ? '저장 해제' : '저장'}" aria-pressed="${hasSaved(item.event_id)}">${bookmark}</button></article>`).join('');
}

function renderHome() {
  if (!data) return;
  const items = mainItems(), previous = items.findIndex(item => item.event_id === selectedId);
  dialIndex = previous >= 0 ? previous : Math.min(dialIndex, Math.max(0, items.length - 1));
  $('home-list').innerHTML = items.length ? rows(items) : empty('현재 주요 목록에 표시할 트렌드가 없습니다. 전체 탐색을 확인하세요.');
  $('dial').setAttribute('aria-busy','false');
  $('dial-empty').hidden = !!items.length;
  $('dial-empty').textContent = '현재 주요 목록에 표시할 트렌드가 없습니다.';
  $('dial-focus').hidden = !items.length; $('dial-items').hidden = !items.length;
  $('dial-items').innerHTML = items.map((item,index) => `<button type="button" class="dial-chip" data-dial-index="${index}" aria-label="공개 목록 ${item.rank}번째 ${esc(item.title)} 선택" aria-pressed="false"><span class="dial-chip-dot"></span><span class="dial-chip-label">${esc(item.title)}</span></button>`).join('');
  selectDial(dialIndex); applyView(); bindImageFallbacks($('home-list'));
}

function selectDial(index) {
  const items = mainItems(); if (!items.length) return;
  dialIndex = ((index % items.length) + items.length) % items.length;
  const selected = items[dialIndex]; selectedId = selected.event_id;
  $('dial-focus').disabled = false; $('dial-focus').setAttribute('aria-label',`${selected.title} 상세 보기`);
  $('dial-rank').textContent = `공개 목록 ${selected.rank}번째`;
  $('dial-source').textContent = connectionFailed ? '연결 지연 · 마지막 수신 내용' : selected.fresh ? selected.sources.map(s => names[s.source] || s.source).join(' · ') : '수집 지연 · 마지막 성공 내용';
  $('dial-title').textContent = selected.title;
  Array.from($('dial-items').children).forEach((button,i) => {
    let offset = (i - dialIndex + items.length) % items.length;
    if (offset > Math.floor((items.length - 1) / 2)) offset -= items.length;
    button.className = `dial-chip dial-offset-${offset < 0 ? 'minus-' : ''}${Math.abs(offset)}${offset === 0 ? ' selected' : ''}${Math.abs(offset) > 3 ? ' dial-distant' : ''}`;
    button.setAttribute('aria-pressed',String(offset === 0)); button.tabIndex = Math.abs(offset) > 3 ? -1 : 0;
  });
}

// Lucian UX/UI Prompt #039, MIT © 2026 Seokwoooo. The selection indicator follows the real view state.
function applyView() {
  $('dial').hidden = view !== 'dial'; $('dial-help').hidden = view !== 'dial'; $('home-list').hidden = view !== 'list';
  document.querySelector('.view-tabs').dataset.view = view;
  document.querySelectorAll('[data-view]').forEach(button => button.setAttribute('aria-pressed',String(button.dataset.view === view)));
}

function renderSearch() {
  const query = $('search').value.trim().toLocaleLowerCase(); $('search-clear').hidden = !$('search').value;
  if (!data) { $('search-list').innerHTML = empty('아직 수집 목록을 불러오지 못했습니다. 홈에서 새로 고침해 주세요.'); return; }
  let items = data.items.filter(item => !query || item.title.toLocaleLowerCase().includes(query) || item.companies.some(c => c.name.toLocaleLowerCase().includes(query)));
  if (filter === 'company') items = items.filter(item => item.companies.length);
  if (filter === 'issue') items = items.filter(item => item.lane === 'issue');
  $('search-results').textContent = `${items.length}개 표시${connectionFailed ? ' · 마지막 수신 내용' : ''}`;
  $('search-list').innerHTML = items.length ? rows(items) : empty(filter === 'company' && !query ? '현재 근거까지 확인된 기업 연결이 없습니다. 기업 확인은 수집 이후 별도로 진행됩니다.' : '검색 조건에 맞는 트렌드가 없습니다.');
  bindImageFallbacks($('search-list'));
}

function renderSaved() {
  const entries = Object.entries(saved).filter(([id,r]) => eventPattern.test(id) && r && typeof r.title === 'string');
  $('saved-count').textContent = `저장한 항목 ${entries.length}개`;
  if (!storageReadable) { $('saved-list').innerHTML = empty('기존 저장 공간을 읽지 못했습니다. 데이터를 덮어쓰지 않았습니다. 브라우저 저장 설정을 확인해 주세요.'); return; }
  if (!entries.length) { $('saved-list').innerHTML = empty('아직 저장한 트렌드가 없습니다. 상세 화면의 저장 버튼을 눌러 보세요.'); return; }
  const current = data ? data.items.filter(item => hasSaved(item.event_id)) : [];
  const archived = entries.filter(([id]) => !current.some(item => item.event_id === id));
  $('saved-list').innerHTML = rows(current) + (archived.length ? `<div class="historical-note"><strong>${data ? '현재 목록에서 벗어난 저장 항목' : '저장한 제목'}</strong><p>${data ? '과거에 저장한 제목입니다. 현재 트렌드로 표시하지 않습니다.' : '현재 수집 여부는 서버 연결 후 확인할 수 있습니다.'}</p></div>${archived.map(([id,r]) => `<article class="archived-row"><div class="row-copy"><strong>${esc(r.title)}</strong><p class="row-meta">저장 ${date(r.saved_at)}</p></div><button class="row-save icon-button bookmark-button" data-unsave="${esc(id)}" aria-label="${esc(r.title)} 저장 해제" aria-pressed="true">${bookmark}</button></article>`).join('')}` : '');
  bindImageFallbacks($('saved-list'));
}

function bindImageFallbacks(root) {
  root.querySelectorAll('img').forEach(img => img.addEventListener('error',() => { img.hidden = true; },{once:true}));
}

function parseRoute() {
  const value = location.hash.slice(1) || 'home', split = value.split('?'), parts = split[0].split('/');
  const params = new URLSearchParams(split[1] || '');
  let id; try { id = decodeURIComponent(parts[1] || ''); } catch { return {page:'home'}; }
  if (['home','search','saved','status'].includes(parts[0])) return {page:parts[0]};
  const publication = params.get('p');
  if (['trend','companies','company'].includes(parts[0]) && eventPattern.test(id) && publicationPattern.test(publication || '')) {
    return {page:parts[0],id,publication,ticker:params.get('ticker') || ''};
  }
  return {page:'home'};
}
function routeHash(next) {
  if (!next.id) return '#'+next.page;
  const params = new URLSearchParams({p:next.publication}); if (next.ticker) params.set('ticker',next.ticker);
  return `#${next.page}/${encodeURIComponent(next.id)}?${params}`;
}
function screenKey(next) { return `${next.page}:${next.id || ''}:${next.publication || ''}`; }
function rememberScroll() { if (!['status','company'].includes(route.page)) scrollPositions.set(screenKey(route),window.scrollY); }
function navigate(next, replace = false) {
  rememberScroll();
  const state = {trzip:true,depth:replace ? 0 : (history.state?.trzip ? history.state.depth : 0) + 1};
  history[replace ? 'replaceState' : 'pushState'](state,'',routeHash(next)); showRoute(next);
}
function back() { if (history.state?.trzip && history.state.depth > 0) history.back(); else navigate({page:'home'},true); }
function setScreen(page, next) {
  activeScreen = page;
  document.querySelectorAll('.screen').forEach(screen => screen.hidden = screen.id !== `screen-${page}`);
  const title = $(`${page === 'search' ? 'search' : page}-title`);
  title?.focus({preventScroll:true});
  requestAnimationFrame(() => window.scrollTo({top:scrollPositions.get(screenKey(next)) || 0,behavior:'instant'}));
}

async function loadDetail(next) {
  // Revisit immutable editions through the API: freshness and company expiry use server time.
  const result = await request(`/api/trends/${encodeURIComponent(next.id)}?publication=${next.publication}`);
  if (result.publication_id !== next.publication || result.item?.event_id !== next.id) throw new Error('게시본이 일치하지 않아 표시를 보류했습니다. 홈에서 다시 확인해 주세요.');
  return result;
}

async function showRoute(next) {
  const previousRoute = route;
  route = next; const token = ++renderToken;
  if (next.page !== 'company' && $('company-sheet').open) $('company-sheet').close();
  if (next.page !== 'status' && $('status-dialog').open) $('status-dialog').close();
  if (next.page === 'status') { setScreen('home',{page:'home'}); await showStatus(); return; }
  if (['home','search','saved'].includes(next.page)) {
    setScreen(next.page,next);
    if (next.page === 'search') renderSearch();
    if (next.page === 'saved') renderSaved();
    if (previousRoute.page === 'status' && next.page === 'home') $('status-open').focus({preventScroll:true});
    return;
  }
  const page = next.page === 'trend' ? 'detail' : 'companies';
  const destination = page === 'detail' ? $('detail-body') : $('companies-body');
  setScreen(page,next); destination.innerHTML = empty('같은 게시본의 내용을 확인하고 있습니다.');
  $('detail-save').disabled = true;
  try {
    const result = await loadDetail(next); if (token !== renderToken) return;
    detailRecord = result;
    if (page === 'detail') renderDetail(result); else renderCompanies(result,next);
    requestAnimationFrame(() => {
      window.scrollTo({top:scrollPositions.get(screenKey(next.page === 'company' ? {...next,page:'companies'} : next)) || 0,behavior:'instant'});
      if (previousRoute.page === 'company' && next.page === 'companies') {
        Array.from($('companies-body').querySelectorAll('[data-company]')).find(button => button.dataset.company === previousRoute.ticker)?.focus({preventScroll:true});
      }
    });
    if (next.page === 'company') await showCompany(result,next,token);
  } catch (error) { if (token === renderToken) destination.innerHTML = empty(error.message); }
}

function updateDetailSave(item) {
  const button = $('detail-save'); button.disabled = false;
  button.setAttribute('aria-label',`${item.title} ${hasSaved(item.event_id) ? '저장 해제' : '저장'}`); button.setAttribute('aria-pressed',String(hasSaved(item.event_id)));
}
const companyMessage = item => ({pending:'기업 관계를 확인하고 있습니다. 확인 전 후보는 표시하지 않습니다.',no_verified_relation:'현재 상장기업과의 직접 관계를 확인하지 못했습니다. 관련 업종만으로 연결하지 않습니다.',register_unavailable:'상장기업 목록을 확인하지 못해 기업 연결을 보류했습니다.',issue_excluded:'사회·안전 이슈에는 수혜 기업을 연결하지 않습니다.'}[item.company_status] || '검증된 기업 연결이 없습니다.');

function renderDetail(result) {
  const item = result.item; updateDetailSave(item);
  const image = safeImage(item.image?.url);
  $('detail-body').innerHTML = `<div class="detail-hero"><p class="detail-kicker">공개 목록 ${esc(item.rank)}번째 · ${esc(item.sources.map(s => names[s.source] || s.source).join(' · '))}</p><h2 class="detail-heading">${esc(item.title)}</h2><p class="detail-meta">${item.fresh ? '최근 수집 확인' : '수집 지연 · 마지막 성공 내용'} · ${date(item.sources[0]?.observed_at)}</p>${image ? `<img class="detail-image" src="${esc(image)}" alt="${esc(item.image.kind === 'text' ? '자동 생성 텍스트 카드' : '공식 기업 이미지')}">` : ''}<p class="detail-image-caption">${esc(item.image?.attribution)}</p></div><div class="detail-content"><button class="company-cta" id="companies-open"><span><strong>관련 기업 알아보기</strong><small>${item.companies.length ? `근거가 확인된 상장기업 ${item.companies.length}곳` : '기업 관계 확인 상태 보기'}</small></span><span aria-hidden="true">→</span></button><section class="content-section"><h3>어디에서 확인했나요?</h3>${item.sources.map(source => `<div class="source-card"><strong>${esc(names[source.source] || source.source)} · 목록 ${esc(source.position)}번째</strong><p>${esc(source.rank_basis)}<br>${date(source.observed_at)}</p><a href="${esc(safeURL(source.source_url))}" target="_blank" rel="noopener noreferrer">출처에서 직접 확인 ↗</a></div>`).join('')}${item.volume_text ? `<p class="source-note">출처에 표시된 검색량: ${esc(item.volume_text)}${item.growth_text ? ' · '+esc(item.growth_text) : ''}<br>실시간 정확한 검색 횟수를 뜻하지 않습니다.</p>` : ''}</section><section class="content-section"><h3>공개 목록에서의 변화</h3><div id="history-chart"></div></section>${item.related_terms.length ? `<section class="content-section"><h3>함께 확인된 검색어</h3><div class="chips">${item.related_terms.slice(0,15).map(term => `<span>${esc(term)}</span>`).join('')}</div></section>` : ''}<section class="content-section"><h3>관련 보도</h3>${item.articles.length ? `<ul class="article-list">${item.articles.map(article => `<li><a href="${esc(safeURL(article.url))}" target="_blank" rel="noopener noreferrer">${esc(article.title)} ↗</a><small>${esc(article.publisher)} · Google RSS 제공 링크</small></li>`).join('')}</ul>` : '<p class="muted">연결된 기사 원문이 아직 없습니다.</p>'}</section><p class="source-note">게시 ${date(result.published_at)} · 출처별 수집 시각은 다를 수 있습니다.</p></div>`;
  $('companies-open').addEventListener('click',() => navigate({page:'companies',id:item.event_id,publication:result.publication_id}));
  bindImageFallbacks($('detail-body')); drawHistory(item.history);
}

function drawHistory(points) {
  const target = $('history-chart');
  if (points.length < 3) { target.innerHTML = '<p class="muted">같은 수집 방식의 관측이 3회 이상 쌓이면 순서 변화를 표시합니다.</p>'; return; }
  const sample = points.filter((_,i) => i % Math.max(1,Math.ceil(points.length / 40)) === 0 || i === points.length - 1);
  const max = Math.max(2,...sample.map(point => point.position));
  const coordinates = sample.map((point,i) => `${18+i*564/(sample.length-1)},${15+(point.position-1)*75/(max-1)}`).join(' ');
  target.innerHTML = `<svg class="history-chart" viewBox="0 0 600 110" role="img" aria-label="위쪽일수록 공개 목록의 앞 순서. 같은 수집 방식의 최근 ${sample.length}회, 현재 ${sample.at(-1).position}번째"><polyline points="${coordinates}" fill="none" stroke="#7B3FF2" stroke-width="2.5"/></svg><div class="history-labels"><span>${date(sample[0].observed_at)}</span><span>${date(sample.at(-1).observed_at)}</span></div><p class="source-note">위쪽일수록 공개 목록의 앞 순서입니다.</p>`;
}

function renderCompanies(result,next) {
  const item = result.item, groups = new Map();
  item.companies.forEach(company => {
    const label = company.relation || '직접 관계 확인'; if (!groups.has(label)) groups.set(label,[]); groups.get(label).push(company);
  });
  $('companies-body').innerHTML = `<div class="company-intro"><p class="detail-kicker">${esc(item.title)}</p><h2>트렌드에서 기업까지</h2><p>${item.companies.length ? '공식 관계와 현재 상장 여부를 함께 확인했습니다.' : '기업 관계 확인 상태를 안내합니다.'}<br>기업 연결은 투자 추천을 뜻하지 않습니다.</p></div>${groups.size ? Array.from(groups.entries()).map(([label,companies],i) => `<details class="company-folder" data-folder="${i}" ${folderStates.get(`${result.publication_id}/${item.event_id}/${i}`) !== false ? 'open' : ''}><summary>${folderIcon}<span class="folder-title">${esc(label)}</span><span class="folder-count">${companies.length}</span></summary><div class="folder-content">${companies.map(company => `<button class="company-row" data-company="${esc(company.ticker)}"><span class="company-row-copy"><strong>${esc(company.name)}</strong><span class="company-symbol">${esc(company.exchange)} · ${esc(company.ticker)}</span><span class="company-relation">${esc(company.relation)}</span></span><span aria-hidden="true">↗</span></button>`).join('')}</div></details>`).join('') : `<div class="company-empty">${empty(companyMessage(item))}</div>`}<p class="source-note">게시 ${date(result.published_at)} · ${item.companies.length}곳 확인</p>`;
  $('companies-body').querySelectorAll('details').forEach(folder => folder.addEventListener('toggle',() => folderStates.set(`${result.publication_id}/${item.event_id}/${folder.dataset.folder}`,folder.open)));
  $('companies-body').querySelectorAll('[data-company]').forEach(button => button.addEventListener('click',() => navigate({...next,page:'company',ticker:button.dataset.company})));
}

async function showCompany(result,next,token) {
  const company = result.item.companies.find(c => c.ticker === next.ticker);
  if (!company) throw new Error('이 트렌드에서 확인된 기업이 아닙니다.');
  const sheet = $('company-sheet'); $('company-body').innerHTML = empty('같은 게시본의 기업 근거를 확인하고 있습니다.');
  if (!sheet.open) sheet.showModal();
  try {
    const lookup = await request(`/api/companies/${encodeURIComponent(company.ticker)}?publication=${result.publication_id}`);
    if (token !== renderToken || !sheet.open) return;
    if (lookup.publication_id !== result.publication_id || lookup.company?.ticker !== company.ticker) throw new Error('기업 게시본이 일치하지 않아 표시를 보류했습니다.');
    // The company endpoint is an identity lookup. Relation evidence belongs to the selected trend.
    $('company-body').innerHTML = `<p class="detail-kicker">${esc(result.item.title)}와의 관계</p><h3>${esc(company.name)}</h3><p class="company-symbol">${esc(company.country)} · ${esc(company.exchange)} · ${esc(company.ticker)}</p><div class="evidence-card"><strong>${esc(company.relation)}</strong><p>${esc(company.evidence_text)}</p><div class="evidence-links"><a href="${esc(safeURL(company.evidence_url))}" target="_blank" rel="noopener noreferrer">관계 근거 원문 ↗</a><a href="${esc(safeURL(company.listing_source))}" target="_blank" rel="noopener noreferrer">상장 근거 원문 ↗</a>${company.homepage ? `<a href="${esc(safeURL(company.homepage))}" target="_blank" rel="noopener noreferrer">기업 홈페이지 ↗</a>` : ''}</div></div><p class="source-note">상장 확인 ${date(company.listing_observed_at)}<br>관계 확인 ${date(company.relation_verified_at)}<br>게시 ${date(result.published_at)}</p><p class="muted">이 관계는 주가 상승이나 투자 적합성을 뜻하지 않습니다.</p>`;
  } catch (error) { if (token === renderToken && sheet.open) $('company-body').innerHTML = empty(error.message); }
}

async function showStatus() {
  const dialog = $('status-dialog'); $('status-body').textContent = '운영 기록을 확인하고 있습니다.';
  if (!dialog.open) dialog.showModal(); const token = renderToken;
  try {
    const status = await request('/api/status'); if (token !== renderToken || !dialog.open) return;
    const labels = {fresh:'최근 수집 성공',stale:'수집 지연',not_configured:'연결되지 않음',failed:'수집 실패'};
    $('status-body').innerHTML = `<p class="muted">서버 응답과 데이터 수집 상태를 구분해 확인합니다.</p>${status.sources.map(source => `<div class="status-row"><strong>${esc(names[source.source] || source.source)}</strong><span>${esc(labels[source.status] || source.status)}<br>${date(source.last_success_at)}</span></div>`).join('')}<div class="status-row"><strong>X</strong><span>비활성 · 무료 운영 범위에서 제외</span></div><h3>연속 운영 검증</h3><p>관찰 ${esc(status.observation_hours)} / 72시간<br>예정 수집 구간 성공률 ${(status.scheduled_slot_coverage * 100).toFixed(1)}%<br>시작 ${date(status.started_at)}</p><ul>${status.release_gate.requires.map(requirement => `<li>${esc(requirement)}</li>`).join('')}</ul><p class="muted">복구 시험과 모바일·PC 화면 검증을 함께 확인합니다.</p>`;
  } catch (error) { if (token === renderToken && dialog.open) $('status-body').textContent = error.message; }
}

document.addEventListener('click',event => {
  const element = event.target.closest('button'); if (!element) return;
  if (element.hasAttribute('data-back')) { back(); return; }
  if (element.dataset.event && data) { navigate({page:'trend',id:element.dataset.event,publication:data.publication_id}); return; }
  if (element.dataset.save) { const item = data?.items.find(row => row.event_id === element.dataset.save); if (item) toggleSave(item); return; }
  if (element.dataset.unsave) { toggleSave({event_id:element.dataset.unsave}); return; }
  if (element.dataset.dialIndex !== undefined) selectDial(Number(element.dataset.dialIndex));
});
$('dial-focus').addEventListener('click',() => { if (selectedId && data) navigate({page:'trend',id:selectedId,publication:data.publication_id}); });
$('detail-save').addEventListener('click',() => { if (detailRecord && route.page === 'trend') toggleSave(detailRecord.item); });
document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click',() => { view = button.dataset.view; applyView(); }));
$('search-open').addEventListener('click',() => { navigate({page:'search'}); $('search').focus({preventScroll:true}); });
$('explore-open').addEventListener('click',() => navigate({page:'search'}));
$('saved-open').addEventListener('click',() => navigate({page:'saved'}));
$('refresh').addEventListener('click',refresh);
$('search-form').addEventListener('submit',event => { event.preventDefault(); $('search').blur(); });
$('search').addEventListener('input',renderSearch);
$('search-clear').addEventListener('click',() => { $('search').value = ''; renderSearch(); $('search').focus(); });
document.querySelectorAll('[data-filter]').forEach(button => button.addEventListener('click',() => { filter = button.dataset.filter; document.querySelectorAll('[data-filter]').forEach(b => b.setAttribute('aria-pressed',String(b === button))); renderSearch(); }));
$('status-open').addEventListener('click',() => navigate({page:'status'}));
$('company-close').addEventListener('click',back); $('status-close').addEventListener('click',back);
for (const id of ['company-sheet','status-dialog']) {
  const dialog = $(id);
  dialog.addEventListener('cancel',event => { event.preventDefault(); back(); });
  dialog.addEventListener('click',event => {
    if (event.target !== dialog) return;
    const rect = dialog.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) back();
  });
}

let drag = null;
$('dial').addEventListener('pointerdown',event => {
  if (event.button !== 0 || !mainItems().length || event.target.closest('#dial-focus')) return;
  drag = {id:event.pointerId,y:event.clientY,index:dialIndex,moved:false};
});
$('dial').addEventListener('pointermove',event => {
  if (!drag || drag.id !== event.pointerId) return;
  const distance = event.clientY - drag.y;
  if (Math.abs(distance) < 14 && !drag.moved) return;
  drag.moved = true; $('dial').setPointerCapture(event.pointerId);
  selectDial(drag.index - Math.round(distance / 56));
});
function endDrag(event) {
  if (!drag || drag.id !== event.pointerId) return;
  if (drag.moved) {
    const stopClick = click => { click.preventDefault(); click.stopPropagation(); };
    $('dial').addEventListener('click',stopClick,{capture:true,once:true});
    setTimeout(() => $('dial').removeEventListener('click',stopClick,true),50);
  }
  if ($('dial').hasPointerCapture(event.pointerId)) $('dial').releasePointerCapture(event.pointerId);
  drag = null;
}
$('dial').addEventListener('pointerup',endDrag); $('dial').addEventListener('pointercancel',endDrag);
$('dial').addEventListener('keydown',event => {
  if (event.target.closest('#dial-focus')) return;
  if (['ArrowDown','ArrowUp','Home','End'].includes(event.key)) {
    event.preventDefault();
    selectDial(event.key === 'Home' ? 0 : event.key === 'End' ? mainItems().length - 1 : dialIndex + (event.key === 'ArrowDown' ? 1 : -1));
    // Follow the visible choice: the old focused chip can rotate out of the stage.
    $('dial-items').querySelector('.dial-chip.selected')?.focus({preventScroll:true});
  }
});
window.addEventListener('popstate',() => { rememberScroll(); showRoute(parseRoute()); });
history.replaceState({trzip:true,depth:0},'',routeHash(parseRoute()));
showRoute(parseRoute()); refresh();
setInterval(() => { if (!document.hidden && ['home','search','saved'].includes(route.page) && !drag) refresh(); },60000);
