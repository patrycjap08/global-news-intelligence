const config = window.GNI_CONFIG || {};

const state = {
  topics: [],
  articles: [],
  links: [],
  summaries: new Map(),
  view: 'all',
  profile: 'ALL',
  search: '',
  demo: false,
};

const PROFILE_LABELS = {
  LEFT: 'Lewicowe',
  CENTER_LEFT: 'Centrolewicowe',
  CENTER: 'Centrowe',
  CENTER_RIGHT: 'Centroprawicowe',
  RIGHT: 'Prawicowe',
  STATE_ALIGNED: 'Państwowe',
  UNCLASSIFIED: 'Nieprzypisane',
};

const PROFILE_COLORS = {
  LEFT: 'dot-left',
  CENTER_LEFT: 'dot-center-left',
  CENTER: 'dot-center',
  CENTER_RIGHT: 'dot-center-right',
  RIGHT: 'dot-right',
  STATE_ALIGNED: 'dot-state',
  UNCLASSIFIED: 'dot-unclassified',
};

const DEMO = {
  topics: [
    { topic_id: 'demo-1', headline_pl: 'Przykładowy temat wieloźródłowy', status: 'ACTIVE', article_count: 4, source_count: 3, coverage_status: 'MULTI_SOURCE', last_seen_at: new Date().toISOString() },
    { topic_id: 'demo-2', headline_pl: 'Jak państwa reagują na nową decyzję gospodarczą?', status: 'ACTIVE', article_count: 3, source_count: 2, coverage_status: 'MULTI_SOURCE', last_seen_at: new Date().toISOString() },
    { topic_id: 'demo-3', headline_pl: 'Jedno źródło, osobna historia', status: 'ACTIVE', article_count: 1, source_count: 1, coverage_status: 'SINGLE_ARTICLE', last_seen_at: new Date().toISOString() },
  ],
  articles: [
    { article_id: 'demo-a1', source_id: 'source-a', source_name: 'BBC', source_profile: 'CENTER', title: 'Przykładowy artykuł o głównym wydarzeniu', original_url: 'https://www.bbc.com/', published_at: new Date().toISOString(), word_count: 800 },
    { article_id: 'demo-a2', source_id: 'source-b', source_name: 'Fox News', source_profile: 'RIGHT', title: 'Druga perspektywa tej samej historii', original_url: 'https://www.foxnews.com/', published_at: new Date().toISOString(), word_count: 700 },
    { article_id: 'demo-a3', source_id: 'source-c', source_name: 'Guardian', source_profile: 'LEFT', title: 'Kontekst i reakcje na wydarzenie', original_url: 'https://www.theguardian.com/', published_at: new Date().toISOString(), word_count: 900 },
    { article_id: 'demo-a4', source_id: 'source-a', source_name: 'BBC', source_profile: 'CENTER', title: 'Nowsze fakty w sprawie', original_url: 'https://www.bbc.com/', published_at: new Date().toISOString(), word_count: 750 },
    { article_id: 'demo-a5', source_id: 'source-d', source_name: 'Reuters', source_profile: 'CENTER', title: 'Reakcja rynków i instytucji', original_url: 'https://www.reuters.com/', published_at: new Date().toISOString(), word_count: 650 },
    { article_id: 'demo-a6', source_id: 'source-b', source_name: 'Fox News', source_profile: 'RIGHT', title: 'Komentarze polityczne po decyzji', original_url: 'https://www.foxnews.com/', published_at: new Date().toISOString(), word_count: 540 },
    { article_id: 'demo-a7', source_id: 'source-e', source_name: 'PAP', source_profile: 'CENTER', title: 'Jedna historia do samodzielnego śledzenia', original_url: 'https://pap.pl/', published_at: new Date().toISOString(), word_count: 360 },
  ],
  links: [
    { topic_id: 'demo-1', article_id: 'demo-a1' }, { topic_id: 'demo-1', article_id: 'demo-a2' }, { topic_id: 'demo-1', article_id: 'demo-a3' }, { topic_id: 'demo-1', article_id: 'demo-a4' },
    { topic_id: 'demo-2', article_id: 'demo-a5' }, { topic_id: 'demo-2', article_id: 'demo-a6' }, { topic_id: 'demo-2', article_id: 'demo-a2' },
    { topic_id: 'demo-3', article_id: 'demo-a7' },
  ],
  summaries: [
    ['demo-1', { topic: { headline_pl: 'Przykładowy temat wieloźródłowy', what_happened_one_sentence_pl: 'To jest demonstracyjne opracowanie pokazujące sposób prezentowania wielu perspektyw w jednym temacie.' }, summary_pl: 'W podglądzie interfejsu każda teza może być powiązana z konkretnymi materiałami źródłowymi. Właściwe dane pojawią się po podłączeniu Supabase.', agreement: ['Źródła opisują to samo główne wydarzenie.'], differences: ['Różnią się akcenty i dobór kontekstu.'], potential_manipulation_signals: ['Porównaj język nagłówków z treścią artykułów.'], sources: [] }],
    ['demo-2', { topic: { headline_pl: 'Jak państwa reagują na nową decyzję gospodarczą?', what_happened_one_sentence_pl: 'Kilka redakcji opisuje gospodarcze skutki tej samej decyzji, ale podkreśla inne konsekwencje.' }, summary_pl: 'To przykładowy tekst podsumowania z miejscem na kontekst i fakty.', agreement: ['Wspólny fakt zostanie pokazany tutaj.'], differences: ['Różne oceny skutków decyzji.'], potential_manipulation_signals: [], sources: [] }],
  ],
};

const $ = (selector) => document.querySelector(selector);

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char]));
}

function formatDate(value) {
  if (!value) return 'brak daty';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 10);
  return new Intl.DateTimeFormat('pl-PL', { day: '2-digit', month: 'short' }).format(date).replace('.', '');
}

function humanProfile(profile) { return PROFILE_LABELS[profile] || PROFILE_LABELS.UNCLASSIFIED; }
function articleMap() { return new Map(state.articles.map((article) => [article.article_id, article])); }

function topicModel(topic) {
  const articlesById = articleMap();
  const topicLinks = state.links.filter((link) => link.topic_id === topic.topic_id);
  const articles = topicLinks.map((link) => articlesById.get(link.article_id)).filter(Boolean);
  const summary = state.summaries.get(topic.topic_id) || {};
  const summaryTopic = summary.topic || {};
  const profileCounts = {};
  const sources = new Set();
  articles.forEach((article) => {
    const profile = article.source_profile || 'UNCLASSIFIED';
    profileCounts[profile] = (profileCounts[profile] || 0) + 1;
    if (article.source_name) sources.add(article.source_name);
  });
  return {
    ...topic,
    articles,
    sources: [...sources],
    profileCounts,
    summary,
    title: summaryTopic.headline_pl || topic.headline_pl || 'Temat bez tytułu',
    lead: summaryTopic.what_happened_one_sentence_pl || summary.summary_pl || 'Opracowanie tego tematu jest jeszcze niedostępne.',
  };
}

async function fetchTable(table, query = '') {
  const url = `${String(config.supabaseUrl).replace(/\/$/, '')}/rest/v1/${table}${query}`;
  const response = await fetch(url, { cache: 'no-store', headers: { apikey: config.supabasePublishableKey, Authorization: `Bearer ${config.supabasePublishableKey}` } });
  if (!response.ok) throw new Error(`${table}: HTTP ${response.status}`);
  return response.json();
}

async function loadLiveData() {
  const [topics, articles, links, summaries] = await Promise.all([
    fetchTable('app_topics', '?select=*&order=last_seen_at.desc'),
    fetchTable('app_articles', '?select=article_id,source_id,source_name,source_profile,source_type,title,original_url,published_at,word_count,description&order=published_at.desc'),
    fetchTable('app_topic_articles', '?select=topic_id,article_id,confidence'),
    fetchTable('app_topic_summaries', '?select=topic_id,version,summary,updated_at'),
  ]);
  state.topics = topics;
  state.articles = articles;
  state.links = links;
  state.summaries = new Map(summaries.map((summary) => [summary.topic_id, summary.summary || {}]));
  state.demo = false;
}

function loadDemoData(message) {
  state.topics = DEMO.topics;
  state.articles = DEMO.articles;
  state.links = DEMO.links;
  state.summaries = new Map(DEMO.summaries);
  state.demo = true;
  if (message) showToast(message);
}

function setStatus() {
  const status = $('#data-status');
  status.textContent = state.demo ? 'Podgląd interfejsu' : `Połączono · ${formatDate(new Date())}`;
  $('#footer-updated').textContent = state.demo ? 'Tryb podglądu — skonfiguruj app/config.js, aby zobaczyć dane z Supabase.' : `Ostatnie odświeżenie: ${new Date().toLocaleTimeString('pl-PL', { hour: '2-digit', minute: '2-digit' })}`;
}

function renderStats(models) {
  const multi = models.filter((topic) => topic.articles.length > 1).length;
  $('#stat-topics').textContent = models.length;
  $('#stat-multi').textContent = multi;
  $('#stat-articles').textContent = new Set(models.flatMap((topic) => topic.articles.map((article) => article.article_id))).size;
  $('#stat-sources').textContent = new Set(models.flatMap((topic) => topic.articles.map((article) => article.source_name))).size;
}

function renderProfiles(models) {
  const counts = {};
  models.flatMap((topic) => topic.articles).forEach((article) => {
    const profile = article.source_profile || 'UNCLASSIFIED';
    counts[profile] = (counts[profile] || 0) + 1;
  });
  const total = Object.values(counts).reduce((sum, count) => sum + count, 0) || 1;
  const rows = [['ALL', 'Wszystkie', models.flatMap((topic) => topic.articles).length], ...Object.entries(PROFILE_LABELS).map(([key, label]) => [key, label, counts[key] || 0]).filter(([, , count]) => count > 0)];
  $('#profile-filters').innerHTML = rows.map(([key, label, count]) => `<button class="filter-button ${state.profile === key ? 'is-active' : ''}" data-profile="${key}" type="button"><span>${label}</span><span>${count}</span></button>`).join('');
  $('#profile-filters').querySelectorAll('[data-profile]').forEach((button) => button.addEventListener('click', () => {
    state.profile = button.dataset.profile;
    render();
  }));
  return total;
}

function renderSources(models) {
  const counts = {};
  models.flatMap((topic) => topic.articles).forEach((article) => { counts[article.source_name] = (counts[article.source_name] || 0) + 1; });
  const topSources = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 5);
  const max = topSources[0]?.[1] || 1;
  $('#source-list').innerHTML = topSources.length ? topSources.map(([source, count]) => `<div class="source-row"><span>${escapeHtml(source)}</span><strong>${count}</strong><small>${Math.round(count / max * 100)}% udziału w widoku</small><div class="source-bar"><i style="width:${count / max * 100}%"></i></div></div>`).join('') : '<span class="muted">Brak danych</span>';
}

function cardHtml(model, index) {
  const profiles = Object.keys(model.profileCounts);
  const badge = model.articles.length > 1 ? `${model.articles.length} artykuły · ${model.sources.length} źródła` : 'Jedno źródło';
  const dots = profiles.map((profile) => `<i class="perspective-dot ${PROFILE_COLORS[profile] || 'dot-unclassified'}" title="${humanProfile(profile)}"></i>`).join('');
  return `<article class="topic-card ${index === 0 ? 'featured' : ''} ${model.articles.length === 1 ? 'is-single' : ''}" data-topic-id="${escapeHtml(model.topic_id)}" tabindex="0" role="button" aria-label="Otwórz opracowanie: ${escapeHtml(model.title)}">
    <div class="card-meta"><span class="card-badge">${index === 0 ? 'NAJWAŻNIEJSZE' : escapeHtml(badge)}</span><span>${formatDate(model.last_seen_at)}</span></div>
    <h4>${escapeHtml(model.title)}</h4>
    <p class="card-dek">${escapeHtml(model.lead)}</p>
    <div class="card-footer"><div class="perspective-dots">${dots}</div><span class="card-sources">${escapeHtml(model.sources.slice(0, 3).join(' · '))}</span></div>
  </article>`;
}

function listValue(value) {
  if (!Array.isArray(value)) return '';
  return value.map((item) => `<li>${escapeHtml(typeof item === 'string' ? item : item.text_pl || item.text || item.claim || item.description || item.headline_pl || JSON.stringify(item))}</li>`).join('');
}

function dialogHtml(model) {
  const summary = model.summary || {};
  const sources = model.articles.map((article) => `<div class="evidence-item"><strong>${escapeHtml(article.source_name)}</strong><span><a href="${escapeHtml(article.original_url || '#')}" target="_blank" rel="noreferrer">${escapeHtml(article.title)}</a><br /><small>${humanProfile(article.source_profile)} · ${article.word_count || '—'} słów${article.published_at ? ` · ${formatDate(article.published_at)}` : ''}</small></span></div>`).join('');
  const section = (title, items, className = '') => Array.isArray(items) && items.length ? `<section class="dialog-section ${className}"><h3>${title}</h3><ul>${listValue(items)}</ul></section>` : '';
  return `<div class="dialog-content"><p class="dialog-kicker">${model.articles.length > 1 ? 'OPRACOWANIE WIELOŹRÓDŁOWE' : 'POJEDYNCZY MATERIAŁ'} <span class="coverage-pill">${model.articles.length} artykuł${model.articles.length === 1 ? '' : 'y'}</span></p>
    <h2 id="dialog-title">${escapeHtml(model.title)}</h2>
    <p class="dialog-lead">${escapeHtml(model.lead)}</p>
    <div class="dialog-rule"></div>
    ${summary.summary_pl ? `<section class="dialog-section"><h3>Synteza</h3><p>${escapeHtml(summary.summary_pl)}</p></section>` : ''}
    ${section('Co łączy źródła', summary.agreement)}
    ${section('Różnice i sprzeczności', summary.differences)}
    ${section('Oś wydarzeń', summary.timeline)}
    ${section('Sposób przedstawienia i ton', summary.framing_and_tone)}
    ${section('Sygnały języka lub możliwej manipulacji', summary.potential_manipulation_signals)}
    ${section('Kontekst i niewiadome', summary.background_context)}
    <section class="dialog-section"><h3>Materiały źródłowe</h3><div class="evidence-list">${sources || '<p>Brak zapisanych linków źródłowych.</p>'}</div></section>
  </div>`;
}

function openTopic(topicId) {
  const model = state.topics.map(topicModel).find((topic) => topic.topic_id === topicId);
  if (!model) return;
  $('#dialog-content').innerHTML = dialogHtml(model);
  const dialog = $('#story-dialog');
  if (typeof dialog.showModal === 'function') dialog.showModal();
  else dialog.setAttribute('open', '');
}

function filteredModels() {
  const query = state.search.trim().toLowerCase();
  return state.topics.map(topicModel).filter((topic) => {
    if (state.view === 'multi' && topic.articles.length < 2) return false;
    if (state.view === 'single' && topic.articles.length !== 1) return false;
    if (state.profile !== 'ALL' && !topic.articles.some((article) => (article.source_profile || 'UNCLASSIFIED') === state.profile)) return false;
    if (query && !`${topic.title} ${topic.lead} ${topic.sources.join(' ')}`.toLowerCase().includes(query)) return false;
    return true;
  }).sort((a, b) => (b.articles.length - a.articles.length) || new Date(b.last_seen_at) - new Date(a.last_seen_at));
}

function render() {
  const models = filteredModels();
  const allModels = state.topics.map(topicModel);
  renderStats(allModels);
  renderProfiles(allModels);
  renderSources(models);
  $('#result-count').textContent = `${models.length} ${models.length === 1 ? 'temat' : 'tematów'}`;
  $('#results-heading').textContent = state.view === 'multi' ? 'Tematy wieloźródłowe' : state.view === 'single' ? 'Historie z jednego źródła' : 'Dzisiejsze tematy';
  $('#topic-grid').innerHTML = models.map(cardHtml).join('');
  $('#empty-state').hidden = models.length > 0;
  $('#topic-grid').querySelectorAll('[data-topic-id]').forEach((card) => {
    card.addEventListener('click', () => openTopic(card.dataset.topicId));
    card.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); openTopic(card.dataset.topicId); } });
  });
}

function showToast(message) {
  const toast = $('#toast');
  toast.textContent = message;
  toast.classList.add('is-visible');
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.remove('is-visible'), 4200);
}

async function init() {
  $('#edition-date').textContent = new Intl.DateTimeFormat('pl-PL', { weekday: 'long', day: 'numeric', month: 'long' }).format(new Date()).toUpperCase();
  if (config.supabaseUrl && config.supabasePublishableKey) {
    try { await loadLiveData(); }
    catch (error) { loadDemoData('Nie udało się pobrać danych z Supabase. Pokazuję podgląd interfejsu.'); console.warn(error); }
  } else {
    loadDemoData('To jest podgląd interfejsu. Dodaj app/config.js, aby połączyć aplikację z Supabase.');
  }
  setStatus();
  render();
}

document.addEventListener('click', (event) => {
  const viewButton = event.target.closest('[data-view]');
  if (viewButton) { state.view = viewButton.dataset.view; document.querySelectorAll('[data-view]').forEach((button) => button.classList.toggle('is-active', button === viewButton)); render(); }
  if (event.target === $('#story-dialog')) $('#story-dialog').close();
});

$('#search-input').addEventListener('input', (event) => { state.search = event.target.value; render(); });
$('#dialog-close').addEventListener('click', () => $('#story-dialog').close());
$('#refresh-button').addEventListener('click', async () => { if (state.demo) return showToast('Podgląd nie jest jeszcze połączony z Supabase.'); $('#refresh-button').textContent = 'Odświeżam…'; try { await loadLiveData(); setStatus(); render(); showToast('Dane zostały odświeżone.'); } catch (error) { showToast('Nie udało się odświeżyć danych.'); console.warn(error); } finally { $('#refresh-button').textContent = 'Odśwież dane'; } });

init();
