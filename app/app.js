const config = window.GNI_CONFIG || {};
const READ_STATE_KEY = 'gni.topic-read-state.v1';
const BOOKMARK_STATE_KEY = 'gni.topic-bookmarks.v1';
// A topic remains matchable by the backend for 48 hours, but stays in the
// current view for 24 hours without a new article.
const TOPIC_VALIDITY_HOURS = 24;

const state = {
  topics: [],
  articles: [],
  links: [],
  summaries: new Map(),
  history: new Map(),
  view: 'current',
  sort: 'articles',
  hideRead: false,
  profile: 'ALL',
  categories: [],
  search: '',
  readTopics: loadReadTopics(),
  bookmarkedTopics: loadBookmarkedTopics(),
  latestHarvestStartedAt: null,
  demo: false,
  connection: 'loading',
  loadedAt: null,
};

let dataIndexes = null;
let modelCache = null;
let searchRenderTimer = null;
let liveLoadPromise = null;
let refreshPromise = null;
let liveLoadController = null;
let liveLoadStartedAt = 0;
let dataRevision = 0;
let fullSummaryTopics = new Set();
let topicDetailPromises = new Map();
let openDialogTopicId = null;
const REQUEST_TIMEOUT_MS = 15000;
const LOAD_TIMEOUT_MS = 90000;
const SUMMARY_PREVIEW_COLUMNS = 'topic_id,version,updated_at,base_topic:summary->base_summary->topic,base_text:summary->base_summary->summary_pl,legacy_topic:summary->topic,legacy_text:summary->summary_pl,update_status:summary->latest_update->status,update_text:summary->latest_update->new_information_pl,update_when:summary->latest_update->generated_at,analysis_status:summary->last_analysis->status,legacy_update_status:summary->update->status,legacy_update_text:summary->update->new_information_pl,legacy_update_when:summary->update->generated_at';
const shortDateFormatter = new Intl.DateTimeFormat('pl-PL', { day: '2-digit', month: 'short' });
const updateDateFormatter = new Intl.DateTimeFormat('pl-PL', {
  day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Warsaw',
});

function invalidateViewCache() {
  dataIndexes = null;
  modelCache = null;
}

function indexes() {
  if (!dataIndexes || dataIndexes.articles !== state.articles || dataIndexes.links !== state.links) {
    const articlesById = new Map();
    const sourceById = new Map();
    const linksByTopic = new Map();
    state.articles.forEach((article) => {
      articlesById.set(String(article.article_id), article);
      if (article.source_id && article.source_name) sourceById.set(String(article.source_id), article.source_name);
    });
    state.links.forEach((link) => {
      const links = linksByTopic.get(link.topic_id) || [];
      links.push(link);
      linksByTopic.set(link.topic_id, links);
    });
    dataIndexes = { articles: state.articles, links: state.links, articlesById, sourceById, linksByTopic };
  }
  return dataIndexes;
}

function allTopicModels() {
  // Data loaders replace these containers; local read/bookmark state is checked
  // at render time. Invalidate explicitly if data is changed in place.
  const inputs = [state.topics, state.articles, state.links, state.summaries, state.history];
  if (!modelCache || inputs.some((value, index) => value !== modelCache.inputs[index])) {
    const models = state.topics.map(topicModel);
    modelCache = { inputs, models, byId: new Map(models.map((model) => [model.topic_id, model])) };
  }
  modelCache.models.forEach((model) => { model.isCurrent = topicIsCurrent(model); });
  return modelCache.models;
}

function modelForTopic(topicId) {
  allTopicModels();
  return modelCache.byId.get(topicId);
}

function scheduleSearchRender() {
  window.clearTimeout(searchRenderTimer);
  searchRenderTimer = window.setTimeout(() => {
    searchRenderTimer = null;
    render({ searchOnly: true });
  }, 100);
}

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
const STATE_SOURCE_PROFILES = new Set(['STATE_ALIGNED', 'STATE_MEDIA', 'GOVERNMENT_AGENCY']);

const CATEGORY_LABELS = {
  ALL: 'Wszystkie kategorie',
  POLSKA: 'Polska',
  POLITYKA: 'Polityka',
  SWIAT: 'Świat',
  GOSPODARKA: 'Gospodarka',
  SPOLECZENSTWO: 'Społeczeństwo',
  TECHNOLOGIA: 'Technologia',
  ZDROWIE: 'Zdrowie',
  KULTURA_SPORT: 'Kultura i sport',
  UNCLASSIFIED: 'Bez kategorii',
};

const CATEGORY_COLORS = {
  POLSKA: 'category-poland',
  POLITYKA: 'category-politics',
  SWIAT: 'category-world',
  GOSPODARKA: 'category-economy',
  SPOLECZENSTWO: 'category-society',
  TECHNOLOGIA: 'category-tech',
  ZDROWIE: 'category-health',
  KULTURA_SPORT: 'category-culture',
  UNCLASSIFIED: 'category-unclassified',
};

const DEMO = {
  topics: [
    { topic_id: 'demo-1', headline_pl: 'Przykładowy temat wieloźródłowy', categories: ['POLITYKA'], status: 'ACTIVE', article_count: 4, source_count: 3, coverage_status: 'MULTI_SOURCE', last_seen_at: new Date().toISOString() },
    { topic_id: 'demo-2', headline_pl: 'Jak państwa reagują na nową decyzję gospodarczą?', categories: ['GOSPODARKA', 'POLITYKA'], status: 'ACTIVE', article_count: 3, source_count: 2, coverage_status: 'MULTI_SOURCE', last_seen_at: new Date().toISOString() },
    { topic_id: 'demo-3', headline_pl: 'Jedno źródło, osobna historia', categories: ['SWIAT'], status: 'ACTIVE', article_count: 1, source_count: 1, coverage_status: 'SINGLE_ARTICLE', last_seen_at: new Date().toISOString() },
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

function loadReadTopics() {
  try {
    const value = JSON.parse(window.localStorage.getItem(READ_STATE_KEY) || '{}');
    return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  } catch (error) {
    console.warn('Nie udało się odczytać lokalnego statusu przeczytania tematów.', error);
    return {};
  }
}

function saveReadTopics() {
  try {
    window.localStorage.setItem(READ_STATE_KEY, JSON.stringify(state.readTopics));
  } catch (error) {
    console.warn('Nie udało się zapisać lokalnego statusu przeczytania tematów.', error);
  }
}

function loadBookmarkedTopics() {
  try {
    const value = JSON.parse(window.localStorage.getItem(BOOKMARK_STATE_KEY) || '{}');
    if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
    return Object.fromEntries(Object.entries(value).filter(([, record]) => (
      record && typeof record === 'object' && !Array.isArray(record)
    )));
  } catch (error) {
    console.warn('Nie udało się odczytać zapisanych tematów.', error);
    return {};
  }
}

function saveBookmarkedTopics() {
  try {
    window.localStorage.setItem(BOOKMARK_STATE_KEY, JSON.stringify(state.bookmarkedTopics));
  } catch (error) {
    console.warn('Nie udało się zapisać bookmarka tematu.', error);
  }
}

function normalizeDisplayText(value) {
  return String(value ?? '')
    // Handle summaries where a JSON/storage layer left line breaks escaped.
    .replace(/\\r\\n/g, '\n')
    .replace(/\\n/g, '\n')
    .replace(/\\r/g, '\n')
    .replace(/\r\n?/g, '\n')
    .replace(/<\s*\/?\s*br\s*\/?\s*>/gi, '\n');
}

function escapeHtml(value) {
  return normalizeDisplayText(value).replace(/[&<>'"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char]));
}

function formatDate(value) {
  if (!value) return 'brak daty';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 10);
  return shortDateFormatter.format(date).replace('.', '');
}

function formatDateTime(value) {
  if (!value) return 'brak danych';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'brak danych';
  return updateDateFormatter.format(date);
}

function polishCount(count, one, few, many) {
  const value = Math.abs(Number(count) || 0);
  if (value === 1) return one;
  if (value % 10 >= 2 && value % 10 <= 4 && (value % 100 < 12 || value % 100 > 14)) return few;
  return many;
}

function articleCountLabel(count) {
  return `${count} ${polishCount(count, 'artykuł', 'artykuły', 'artykułów')}`;
}

function sourceCountLabel(count) {
  return `${count} ${polishCount(count, 'źródło', 'źródła', 'źródeł')}`;
}

function topicCountLabel(count) {
  return String(count) + ' ' + polishCount(count, 'temat', 'tematy', 'tematów');
}

function humanProfile(profile) { return PROFILE_LABELS[profile] || PROFILE_LABELS.UNCLASSIFIED; }
function normalizedCategories(value) {
  const values = Array.isArray(value) ? value : [value];
  return [...new Set(values.filter((category) => CATEGORY_LABELS[category] && category !== 'ALL' && category !== 'UNCLASSIFIED'))];
}
function humanCategory(category) { return CATEGORY_LABELS[category] || CATEGORY_LABELS.UNCLASSIFIED; }
function isStateSource(article) {
  const profile = String(article?.source_profile || '').trim().toUpperCase();
  const sourceType = String(article?.source_type || '').trim().toUpperCase();
  return STATE_SOURCE_PROFILES.has(profile) || STATE_SOURCE_PROFILES.has(sourceType);
}
function articleMap() { return indexes().articlesById; }
function updateText(summaryOrUpdate) {
  const nestedUpdate = summaryOrUpdate?.update;
  const update = nestedUpdate && typeof nestedUpdate === 'object'
    ? nestedUpdate
    : (summaryOrUpdate || {});
  if (update.status === 'NO_NEW_INFORMATION') return '';
  return normalizeDisplayText(update.new_information_pl || update.what_changed_pl || '').trim();
}

function collectTopicUpdates(storedSummary, historyRows) {
  const candidates = [];
  const addFromStored = (stored, fallback = {}) => {
    if (!stored || typeof stored !== 'object') return;
    const cumulative = Array.isArray(stored.updates) ? stored.updates : [];
    const values = cumulative.length
      ? cumulative
      : [stored.latest_update || stored.update].filter(Boolean);
    values.forEach((value) => {
      if (!value || !updateText(value)) return;
      candidates.push({
        ...value,
        generated_at: value.generated_at || fallback.generated_at || null,
        run_id: value.run_id || fallback.run_id || null,
        version: value.version || fallback.version || null,
      });
    });
  };
  addFromStored(storedSummary);
  (historyRows || []).forEach((row) => addFromStored(row.summary || {}, row));
  const unique = new Map();
  candidates.forEach((update) => {
    const key = update.update_id || update.run_id || JSON.stringify({
      text: updateText(update),
      articles: update.new_article_ids || [],
    });
    const previous = unique.get(key);
    if (!previous || String(update.generated_at || '') > String(previous.generated_at || '')) {
      unique.set(key, update);
    }
  });
  return [...unique.values()].sort((a, b) =>
    String(b.generated_at || '').localeCompare(String(a.generated_at || ''))
  );
}

function topicArticleIds(model) {
  if (model.evidenceIds) return model.evidenceIds;
  return [
    ...model.articles.map((article) => `article:${article.article_id}`),
  ].sort();
}

function topicIsCurrent(topic) {
  // Derive from time so an older database view or cached flag cannot keep
  // a topic current beyond the application's 24-hour window.
  const timestamp = Date.parse(topic.last_seen_at || '');
  return Number.isFinite(timestamp) && Date.now() - timestamp < TOPIC_VALIDITY_HOURS * 60 * 60 * 1000;
}

function readRecord(model) {
  const value = state.readTopics[model.topic_id];
  if (value && typeof value === 'object' && !Array.isArray(value)) return value;
  if (Number.isFinite(Number(value))) return { version: Number(value) };
  return null;
}

function readableEvidenceText(value) {
  const { articlesById, sourceById } = indexes();
  const sourceNameForId = (identifier) => {
    const article = articlesById.get(String(identifier));
    return article?.source_name || sourceById.get(String(identifier)) || 'źródło';
  };
  return normalizeDisplayText(value)
    .replace(/\b[0-9a-f]{24,64}\b/gi, sourceNameForId)
    .replace(/\(\s*[,;]?\s*\)/g, '')
    .replace(/\(\s*[,;]\s*/g, '(')
    .replace(/\s*[,;]\s*\)/g, ')')
    .replace(/[ \t]{2,}/g, ' ')
    .replace(/[ \t]+\n/g, '\n')
    .trim();
}

function richTextHtml(value) {
  const text = readableEvidenceText(value).trim();
  if (!text) return '';
  // Prefer blank-line paragraphs. If an older response has only single line
  // breaks, treat those as paragraph boundaries too instead of collapsing the
  // whole synthesis into one dense block.
  const paragraphs = text.includes('\n\n') ? text.split(/\n{2,}/) : text.split(/\n+/);
  return paragraphs
    .filter((paragraph) => paragraph.trim())
    .map((paragraph) => {
      const safe = escapeHtml(paragraph)
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        .replace(/__([^_]+)__/g, '<strong>$1</strong>')
        .replace(/\n/g, '<br />');
      return `<p>${safe}</p>`;
    })
    .join('');
}

function richInlineHtml(value) {
  const text = readableEvidenceText(value).trim();
  if (!text) return '';
  return escapeHtml(text)
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/__([^_]+)__/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br />');
}

function itemArticleSources(item) {
  if (!item || typeof item !== 'object' || !Array.isArray(item.article_ids)) return [];
  const articles = articleMap();
  return [...new Set(item.article_ids.map((id) => articles.get(String(id))?.source_name).filter(Boolean))];
}

function isTopicRead(model) {
  const record = readRecord(model);
  if (!record) return false;
  if (Array.isArray(record.article_ids)) {
    const readArticles = new Set(record.article_ids.map(String));
    return topicArticleIds(model).every((evidenceId) => {
      if (readArticles.has(evidenceId)) return true;
      // Compatibility with the previous format, which stored bare article IDs.
      return evidenceId.startsWith('article:') && readArticles.has(evidenceId.slice(8));
    });
  }
  // Compatibility with the earlier local format, which stored only a version.
  return Number(record.version || 0) >= Number(model.summaryVersion || 1);
}

function bookmarkedKeyForTopic(model) {
  if (state.bookmarkedTopics[model.topic_id]) return model.topic_id;
  const evidence = new Set(topicArticleIds(model));
  return Object.entries(state.bookmarkedTopics).find(([, record]) => {
    const savedEvidence = Array.isArray(record.evidence_ids) ? record.evidence_ids : [];
    return savedEvidence.some((evidenceId) => evidence.has(String(evidenceId)));
  })?.[0] || null;
}

function isTopicBookmarked(model) {
  return Boolean(bookmarkedKeyForTopic(model));
}

function toggleTopicBookmark(topicId) {
  const model = modelForTopic(topicId);
  if (!model) return;
  const existingKey = bookmarkedKeyForTopic(model);
  if (existingKey) {
    delete state.bookmarkedTopics[existingKey];
    saveBookmarkedTopics();
    showToast('Usunięto z zapisanych.');
  } else {
    state.bookmarkedTopics[topicId] = {
      topic_id: topicId,
      evidence_ids: topicArticleIds(model),
      saved_at: new Date().toISOString(),
    };
    saveBookmarkedTopics();
    showToast('Zapisano temat.');
  }
  render();
}

function markTopicRead(model) {
  state.readTopics[model.topic_id] = {
    version: Number(model.summaryVersion || 1),
    article_ids: topicArticleIds(model),
    read_at: new Date().toISOString(),
  };
  saveReadTopics();
}

function topicModel(topic) {
  const articlesById = articleMap();
  const topicLinks = indexes().linksByTopic.get(topic.topic_id) || [];
  const articles = topicLinks.map((link) => articlesById.get(String(link.article_id))).filter(Boolean);
  const summaryRow = state.summaries.get(topic.topic_id) || {};
  const storedSummary = summaryRow.summary || summaryRow;
  const summary = storedSummary.base_summary || storedSummary;
  const storedHistory = state.history.get(topic.topic_id) || [];
  const updates = collectTopicUpdates(storedSummary, storedHistory);
  const latestUpdate = updates[0] || {};
  const summaryTopic = summary.topic || {};
  const categories = normalizedCategories(topic.categories || topic.category);
  const profileCounts = {};
  const sources = new Set();
  articles.forEach((article) => {
    const profile = article.source_profile || 'UNCLASSIFIED';
    profileCounts[profile] = (profileCounts[profile] || 0) + 1;
    if (article.source_name) sources.add(article.source_name);
  });
  const sourceCount = new Set(articles.map((article) => article.source_id || article.source_name).filter(Boolean)).size;
  const hasIndependentSource = articles.some((article) => !isStateSource(article));
  const hasAggregation = sourceCount >= 2 && hasIndependentSource;
  const articleTimestamps = articles
    .map((article) => Date.parse(article.published_at || article.fetched_at || ''))
    .filter(Number.isFinite);
  const newestArticleAt = articleTimestamps.length
    ? new Date(Math.max(...articleTimestamps)).toISOString()
    : topic.last_seen_at;
  const model = {
    ...topic,
    categories,
    articles,
    sources: [...sources],
    sourceCount,
    hasAggregation,
    isCurrent: topicIsCurrent(topic),
    newestArticleAt,
    profileCounts,
    summary: hasAggregation ? summary : {},
    latestUpdate: hasAggregation ? latestUpdate : {},
    latestAnalysisStatus: storedSummary.last_analysis?.status || latestUpdate.status || null,
    updates: hasAggregation ? updates : [],
    summaryVersion: summaryRow.version || 1,
    summaryUpdatedAt: summaryRow.updated_at || summaryRow.generated_at || topic.last_seen_at,
    history: hasAggregation ? storedHistory : [],
    title: hasAggregation ? (topic.headline_pl || summaryTopic.headline_pl || 'Temat bez tytułu') : (topic.headline_pl || 'Temat bez tytułu'),
    lead: hasAggregation ? readableEvidenceText(summaryTopic.what_happened_one_sentence_pl || summary.summary_pl || 'Opracowanie tego tematu jest jeszcze niedostępne.') : 'Opracowanie dostępne po pojawieniu się materiałów z co najmniej dwóch źródeł.',
  };
  model.searchText = `${model.title} ${model.lead} ${model.sources.join(' ')}`.toLowerCase();
  model.evidenceIds = articles.map((article) => `article:${article.article_id}`).sort();
  return model;
}

async function fetchTable(table, query = '', { signal, timeoutMs = REQUEST_TIMEOUT_MS, attempts = 3 } = {}) {
  const url = `${String(config.supabaseUrl).replace(/\/$/, '')}/rest/v1/${table}${query}`;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    if (signal?.aborted) throw new Error('Pobieranie danych zostało przerwane.');
    const controller = new AbortController();
    const abort = () => controller.abort();
    signal?.addEventListener('abort', abort, { once: true });
    const timer = window.setTimeout(abort, timeoutMs);
    let retryDelay = 300 * (attempt + 1);
    try {
      const response = await fetch(url, { cache: 'no-store', signal: controller.signal,
        headers: { apikey: config.supabasePublishableKey, Authorization: `Bearer ${config.supabasePublishableKey}` } });
      if (!response.ok) {
        const error = new Error(`${table}: HTTP ${response.status}`);
        error.retryable = [408, 425, 429, 500, 502, 503, 504].includes(response.status);
        const retryAfter = Number(response.headers?.get('retry-after'));
        if (retryAfter > 0) retryDelay = Math.min(3000, retryAfter * 1000);
        throw error;
      }
      const data = await response.json();
      if (!Array.isArray(data)) throw new Error(`${table}: niepoprawny format danych.`);
      return data;
    } catch (error) {
      if (signal?.aborted || error.retryable === false || attempt + 1 >= attempts) throw error;
    } finally {
      window.clearTimeout(timer);
      signal?.removeEventListener('abort', abort);
    }
    await new Promise((resolve) => window.setTimeout(resolve, retryDelay));
  }
}

async function fetchAllRows(table, query = '', options = {}) {
  const pageSize = 500;
  const rows = [];
  let offset = 0;
  while (true) {
    const separator = query.includes('?') ? '&' : '?';
    const page = await fetchTable(table, `${query}${separator}limit=${pageSize}&offset=${offset}`, options);
    rows.push(...page);
    if (page.length < pageSize) return rows;
    offset += page.length;
  }
}

async function fetchRowsForIds(table, column, ids, query, options) {
  const unique = [...new Set(ids.map(String))];
  const batches = [];
  for (let offset = 0; offset < unique.length; offset += 80) batches.push(unique.slice(offset, offset + 80));
  const results = new Array(batches.length);
  let next = 0;
  await Promise.all(Array.from({ length: Math.min(3, batches.length) }, async () => {
    while (next < batches.length) {
      const index = next++;
      const filter = encodeURIComponent(`in.(${batches[index].join(',')})`);
      results[index] = await fetchAllRows(table, `${query}&${column}=${filter}`, options);
    }
  }));
  return results.flat();
}

function summaryPreview(row) {
  if (row.summary) return row;
  return { topic_id: row.topic_id, version: row.version, updated_at: row.updated_at,
    summary: { base_summary: { topic: row.base_topic || row.legacy_topic || {},
      summary_pl: row.base_text || row.legacy_text || '' },
      latest_update: { status: row.update_status || row.legacy_update_status, new_information_pl: row.update_text || row.legacy_update_text || '', generated_at: row.update_when || row.legacy_update_when },
      last_analysis: { status: row.analysis_status || row.update_status || row.legacy_update_status } } };
}

// IndexedDB is asynchronous: saving a large snapshot must not freeze typing.
// Cache failures (including private browsing/storage limits) never block the app.
function snapshotStorage(mode, snapshot) {
  if (!window.indexedDB) return Promise.resolve(null);
  return new Promise((resolve) => {
    let db;
    let settled = false;
    let result = null;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timer);
      db?.close();
      resolve(value);
    };
    const timer = window.setTimeout(() => finish(null), 1200);
    try {
      const request = window.indexedDB.open('gni-data-cache', 1);
      request.onupgradeneeded = () => request.result.createObjectStore('snapshots');
      request.onerror = () => finish(null);
      request.onsuccess = () => {
        db = request.result;
        if (settled) { db.close(); return; }
        try {
          const transaction = db.transaction('snapshots', mode === 'read' ? 'readonly' : 'readwrite');
          const store = transaction.objectStore('snapshots');
          const key = config.staticDataUrl || String(config.supabaseUrl).replace(/\/$/, '');
          const operation = mode === 'read' ? store.get(key) : store.put(snapshot, key);
          operation.onsuccess = () => { result = operation.result; };
          transaction.oncomplete = () => finish(result);
          transaction.onerror = transaction.onabort = () => finish(null);
        } catch (error) { finish(null); }
      };
    } catch (error) { finish(null); }
  });
}

function saveSnapshot() {
  return snapshotStorage('write', { schema: 1, savedAt: state.loadedAt,
    topics: state.topics, articles: state.articles, links: state.links,
    summaries: [...state.summaries], history: [...state.history], fullSummaryTopics: [...fullSummaryTopics], staticGeneration: state.staticGeneration,
    latestHarvestStartedAt: state.latestHarvestStartedAt });
}

async function restoreSnapshot() {
  const snapshot = await snapshotStorage('read');
  if (!snapshot || snapshot.schema !== 1 || !Number.isFinite(Date.parse(snapshot.savedAt))
      || !['topics', 'articles', 'links', 'summaries', 'history'].every((key) => Array.isArray(snapshot[key]))) return false;
  try {
    const summaries = new Map(snapshot.summaries), history = new Map(snapshot.history);
    const fullTopics = new Set(Array.isArray(snapshot.fullSummaryTopics) ? snapshot.fullSummaryTopics : []);
    state.topics = snapshot.topics; state.articles = snapshot.articles; state.links = snapshot.links;
    state.summaries = summaries; state.history = history; state.staticGeneration = snapshot.staticGeneration;
    fullSummaryTopics = fullTopics;
    state.latestHarvestStartedAt = snapshot.latestHarvestStartedAt;
    state.loadedAt = snapshot.savedAt; state.demo = false; state.connection = 'cached';
    dataRevision += 1;
    invalidateViewCache();
    return true;
  } catch (error) { return false; }
}

async function fetchStaticJson(path, signal) {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (signal?.aborted) abort();
  signal?.addEventListener('abort', abort, { once: true });
  const timer = window.setTimeout(abort, REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(new URL(path, new URL(config.staticDataUrl, window.location.href)), { cache: 'no-store', signal: controller.signal });
    if (!response.ok) throw new Error(`Dane strony: HTTP ${response.status}`);
    return await response.json();
  } finally { window.clearTimeout(timer); signal?.removeEventListener('abort', abort); }
}

async function loadStaticData(options) {
  const data = await fetchStaticJson('index.json', options.signal);
  if (data.schema !== 1 || !['topics', 'articles', 'links', 'summaries'].every((key) => Array.isArray(data[key]))
      || !data.generation || !data.exported_at) throw new Error('Niepoprawny eksport strony.');
  state.topics = data.topics; state.articles = data.articles; state.links = data.links;
  state.summaries = new Map(data.summaries.map((row) => [row.topic_id, row]));
  state.history = new Map(); fullSummaryTopics = new Set(); topicDetailPromises = new Map();
  state.staticGeneration = data.generation;
  dataRevision += 1; state.latestHarvestStartedAt = data.latest_harvest_started_at;
  state.loadedAt = data.exported_at; state.demo = false; state.connection = 'live';
  invalidateViewCache(); void saveSnapshot();
}

function loadLiveData() {
  if (liveLoadPromise) return liveLoadPromise;
  const controller = new AbortController();
  liveLoadController = controller;
  liveLoadStartedAt = Date.now();
  const deadline = window.setTimeout(() => controller.abort(), LOAD_TIMEOUT_MS);
  const options = { signal: controller.signal };
  liveLoadPromise = (async () => {
    try {
      if (config.staticDataUrl) { await loadStaticData(options); return; }
      // The UI displays multi-source topics. Do not download thousands of
      // one-article candidates, unrelated articles or full version archives.
      const topics = await fetchAllRows('app_topics', '?select=*&source_count=gte.2&order=topic_id.asc', options);
      const topicIds = topics.map((topic) => topic.topic_id);
      const [links, previews, latestRuns] = await Promise.all([
        fetchRowsForIds('app_topic_articles', 'topic_id', topicIds, '?select=topic_id,article_id,confidence&order=topic_id.asc,article_id.asc', options),
        fetchRowsForIds('app_topic_summaries', 'topic_id', topicIds, `?select=${SUMMARY_PREVIEW_COLUMNS}&order=topic_id.asc`, options),
        fetchTable('app_latest_harvest', '?select=run_id,started_at&limit=1', { ...options, attempts: 1 })
          .catch(() => [{ started_at: state.latestHarvestStartedAt }]),
      ]);
      const articles = await fetchRowsForIds('app_articles', 'article_id', links.map((link) => link.article_id),
        '?select=article_id,source_id,source_name,source_profile,source_type,title,original_url,published_at,fetched_at,word_count&order=article_id.asc', options);
      if (controller.signal.aborted) throw new Error('Przekroczono czas pobierania danych.');
      // Commit one complete snapshot: a failed refresh leaves the last good
      // data intact, instead of mixing different partially fetched versions.
      state.topics = topics; state.articles = articles; state.links = links;
      state.summaries = new Map(previews.map((row) => [row.topic_id, summaryPreview(row)]));
      state.history = new Map();
      fullSummaryTopics = new Set(previews.filter((row) => row.summary).map((row) => row.topic_id));
      topicDetailPromises = new Map();
      dataRevision += 1;
      state.latestHarvestStartedAt = latestRuns[0]?.started_at || null;
      state.loadedAt = new Date().toISOString();
      state.demo = false; state.connection = 'live';
      invalidateViewCache();
      void saveSnapshot();
    } catch (error) {
      controller.abort();
      throw error;
    } finally {
      window.clearTimeout(deadline);
      liveLoadController = null;
      liveLoadPromise = null;
    }
  })();
  return liveLoadPromise;
}

function loadTopicDetails(topicId) {
  if (state.demo || fullSummaryTopics.has(topicId)) return Promise.resolve();
  if (topicDetailPromises.has(topicId)) return topicDetailPromises.get(topicId);
  const revision = dataRevision;
  const promise = (async () => {
    if (config.staticDataUrl) {
      const detail = await fetchStaticJson(`${state.staticGeneration}/topics/${encodeURIComponent(topicId)}.json`);
      if (revision !== dataRevision) return;
      state.summaries = new Map(state.summaries);
      if (detail.summary) state.summaries.set(topicId, detail.summary);
      state.history = new Map(state.history); state.history.set(topicId, detail.history || []);
      fullSummaryTopics.add(topicId); invalidateViewCache(); void saveSnapshot(); return;
    }
    const rows = await fetchTable('app_topic_summaries', `?select=topic_id,version,summary,updated_at&topic_id=eq.${encodeURIComponent(topicId)}&limit=1`);
    const row = rows[0];
    let versions = [];
    // Modern summaries contain all accepted updates. Only legacy summaries
    // need the optional version table to recover their earlier updates.
    if (row && !Array.isArray(row.summary?.updates)) {
      try {
        const raw = await fetchAllRows('app_topic_summary_versions',
          `?select=topic_id,version,updates:summary->updates,latest_update:summary->latest_update,update:summary->update,generated_at&topic_id=eq.${encodeURIComponent(topicId)}&order=version.asc`, { attempts: 1 });
        versions = raw.map((version) => ({ ...version, summary: { updates: version.updates, latest_update: version.latest_update, update: version.update } }));
      } catch (error) { console.warn('Nie udało się pobrać historii tego wątku.', error); }
    }
    if (revision !== dataRevision) return;
    state.summaries = new Map(state.summaries);
    if (row) state.summaries.set(topicId, row);
    state.history = new Map(state.history); state.history.set(topicId, versions);
    fullSummaryTopics.add(topicId);
    invalidateViewCache();
    void saveSnapshot();
  })().finally(() => {
    if (topicDetailPromises.get(topicId) === promise) topicDetailPromises.delete(topicId);
  });
  topicDetailPromises.set(topicId, promise);
  return promise;
}

function refreshData({ notify = false } = {}) {
  if (refreshPromise) return refreshPromise;
  if (!config.staticDataUrl && (!config.supabaseUrl || !config.supabasePublishableKey)) {
    showToast('Podgląd nie jest jeszcze połączony z bazą.');
    return Promise.resolve(false);
  }
  if (state.demo) {
    state.topics = []; state.articles = []; state.links = [];
    state.summaries = new Map(); state.history = new Map(); state.demo = false;
    invalidateViewCache();
  }
  const button = $('#refresh-button');
  button.disabled = true; button.textContent = 'Odświeżam…';
  state.connection = 'loading'; setStatus();
  refreshPromise = (async () => {
    try {
      await loadLiveData();
      setStatus(); render();
      if (notify) showToast('Dane zostały odświeżone.');
      return true;
    } catch (error) {
      state.connection = state.loadedAt ? 'cached' : 'error';
      state.demo = false;
      setStatus(); render();
      showToast(state.loadedAt ? 'Nie udało się odświeżyć. Zachowuję ostatnie pobrane dane.' : 'Nie udało się połączyć. Spróbuj „Odśwież dane”.');
      console.warn('Pobieranie danych nie powiodło się.', error);
      return false;
    } finally {
      button.disabled = false; button.textContent = 'Odśwież dane';
      refreshPromise = null;
    }
  })();
  return refreshPromise;
}

function loadDemoData(message) {
  state.topics = DEMO.topics;
  state.articles = DEMO.articles;
  state.links = DEMO.links;
  state.summaries = new Map(DEMO.summaries);
  state.history = new Map();
  state.demo = true;
  state.connection = 'demo';
  state.loadedAt = null;
  invalidateViewCache();
  if (message) showToast(message);
}

function setStatus() {
  const status = $('#data-status');
  status.textContent = state.demo ? 'Podgląd interfejsu'
    : state.connection === 'loading' ? (state.loadedAt ? 'Odświeżam · ostatnie dane dostępne' : (config.staticDataUrl ? 'Pobieranie danych…' : 'Łączenie z bazą…'))
    : state.connection === 'cached' ? 'Ostatnie zapisane dane · brak aktualizacji'
    : state.connection === 'error' ? 'Nie udało się połączyć'
    : `Połączono · ${formatDate(new Date())}`;
  $('#harvest-time').textContent = state.demo ? 'Dane demonstracyjne' : `Dane z: ${formatDateTime(state.latestHarvestStartedAt)}`;
  $('#footer-updated').textContent = state.demo ? 'Tryb podglądu — skonfiguruj połączenie z bazą.'
    : state.loadedAt ? `Ostatnie poprawne odświeżenie: ${formatDateTime(state.loadedAt)}` : 'Dane nie zostały jeszcze pobrane.';
}

function renderStats(models) {
  const currentModels = models.filter((topic) => topic.isCurrent);
  const historicalModels = models.filter((topic) => !topic.isCurrent);
  const articleCount = (topicModels) => new Set(
    topicModels.flatMap((topic) => topic.articles.map((article) => article.article_id)),
  ).size;
  $('#stat-current-topics').textContent = currentModels.length;
  $('#stat-historical-topics').textContent = historicalModels.length;
  $('#stat-current-articles').textContent = articleCount(currentModels);
  $('#stat-historical-articles').textContent = articleCount(historicalModels);
  $('#stat-sources').textContent = new Set(models.flatMap((topic) => topic.articles.map((article) => article.source_name))).size;
}

function renderProfiles(models) {
  const counts = {};
  models.forEach((topic) => {
    const profiles = new Set(topic.articles.map((article) => article.source_profile || 'UNCLASSIFIED'));
    profiles.forEach((profile) => {
      counts[profile] = (counts[profile] || 0) + 1;
    });
  });
  const rows = [
    ['ALL', 'Wszystkie tematy', models.length],
    ...Object.entries(PROFILE_LABELS)
      .map(([key, label]) => [key, label, counts[key] || 0]),
  ];
  $('#profile-filters').innerHTML = rows.map(([key, label, count]) => `<button class="filter-button ${state.profile === key ? 'is-active' : ''}" data-profile="${key}" type="button"><span class="filter-name">${key === 'ALL' ? '' : `<i class="perspective-dot ${PROFILE_COLORS[key] || 'dot-unclassified'}" aria-hidden="true"></i>`}<span>${label}</span></span><span>${count}</span></button>`).join('');
  $('#profile-filters').querySelectorAll('[data-profile]').forEach((button) => button.addEventListener('click', () => {
    state.profile = button.dataset.profile;
    render();
  }));
}

function renderCategories(models) {
  const counts = {};
  models.forEach((topic) => {
    const categories = topic.categories.length ? topic.categories : ['UNCLASSIFIED'];
    categories.forEach((category) => {
      counts[category] = (counts[category] || 0) + 1;
    });
  });
  const rows = [
    ['ALL', CATEGORY_LABELS.ALL, models.length],
    ...Object.keys(CATEGORY_LABELS)
      .filter((key) => !['ALL', 'UNCLASSIFIED'].includes(key))
      .map((key) => [key, CATEGORY_LABELS[key], counts[key] || 0]),
    ['UNCLASSIFIED', CATEGORY_LABELS.UNCLASSIFIED, counts.UNCLASSIFIED || 0],
  ];
  const allCategoriesSelected = state.categories.length === 0;
  $('#category-filters').innerHTML = rows.map(([key, label, count]) => {
    const isActive = key === 'ALL' ? allCategoriesSelected : state.categories.includes(key);
    const pressed = key === 'ALL' ? allCategoriesSelected : isActive;
    return `<button class="filter-button category-filter ${isActive ? 'is-active' : ''}" data-category="${key}" type="button" aria-pressed="${pressed}"><span class="filter-name"><i class="category-swatch ${CATEGORY_COLORS[key] || 'category-all'}" aria-hidden="true"></i><span>${label}</span></span><span>${count}</span></button>`;
  }).join('');
  $('#category-filters').querySelectorAll('[data-category]').forEach((button) => button.addEventListener('click', () => {
    const category = button.dataset.category;
    if (category === 'ALL') {
      state.categories = [];
    } else if (state.categories.includes(category)) {
      state.categories = state.categories.filter((value) => value !== category);
    } else {
      state.categories = [...state.categories, category];
    }
    render();
  }));
}

function renderSources(models) {
  const counts = {};
  models.forEach((topic) => {
    topic.articles.forEach((article) => {
      const source = article.source_name || 'Nieznane źródło';
      const entry = counts[source] || { articles: 0 };
      entry.articles += 1;
      counts[source] = entry;
    });
  });
  const sources = Object.entries(counts)
    .sort(([nameA, a], [nameB, b]) => (b.articles - a.articles) || nameA.localeCompare(nameB, 'pl'));
  const maxArticles = Math.max(1, ...sources.map(([, count]) => count.articles));
  $('#source-list').innerHTML = sources.length ? sources.map(([source, count]) => {
    const relativeShare = Math.round(count.articles / maxArticles * 100);
    const articleLabel = count.articles === 1 ? 'artykuł' : (count.articles < 5 ? 'artykuły' : 'artykułów');
    return `<div class="source-row"><span>${escapeHtml(source)}</span><small>${count.articles} ${articleLabel}</small><div class="source-bar"><i style="width:${relativeShare}%"></i></div></div>`;
  }).join('') : '<span class="muted">Brak danych</span>';
}

function categoryBadges(categories, className = '') {
  const values = categories.length ? categories : ['UNCLASSIFIED'];
  return values.map((category) => `<span class="category-tag ${className} ${CATEGORY_COLORS[category] || 'category-unclassified'}">${humanCategory(category)}</span>`).join('');
}

function cardHtml(model, index) {
  const profiles = Object.keys(model.profileCounts);
  const badge = model.hasAggregation
    ? `${articleCountLabel(model.articles.length)} · ${sourceCountLabel(model.sources.length)}`
    : 'Materiał oczekujący na drugie źródło';
  const hasUpdate = model.latestAnalysisStatus !== 'NO_NEW_INFORMATION' && Boolean(updateText(model.latestUpdate));
  const bookmarked = isTopicBookmarked(model);
  const read = isTopicRead(model);
  const dots = profiles.map((profile) => `<i class="perspective-dot ${PROFILE_COLORS[profile] || 'dot-unclassified'}" title="${humanProfile(profile)}"></i>`).join('');
  const category = categoryBadges(model.categories, 'card-category-tag');
  return `<article class="topic-card ${index === 0 ? 'featured' : ''} ${!model.hasAggregation ? 'is-single' : ''} ${read ? 'is-read' : 'is-unread'}" data-topic-id="${escapeHtml(model.topic_id)}" tabindex="0" role="button" aria-label="${read ? 'Przeczytany' : 'Nieprzeczytany'} temat: ${escapeHtml(model.title)}">
    <div class="card-meta"><span class="card-badge-group"><span class="card-badge">${hasUpdate && !read ? 'AKTUALIZACJA' : index === 0 ? 'NAJWAŻNIEJSZE' : escapeHtml(badge)}</span>${index === 0 ? `<small>${escapeHtml(badge)}</small>` : ''}<span class="card-category-group">${category}</span></span><span class="card-meta-actions"><button class="bookmark-button ${bookmarked ? 'is-saved' : ''}" data-bookmark-topic-id="${escapeHtml(model.topic_id)}" type="button" aria-label="${bookmarked ? 'Usuń temat z zapisanych' : 'Zapisz temat'}" aria-pressed="${bookmarked}">${bookmarked ? '★' : '☆'}</button><span>${formatDate(model.newestArticleAt)}</span></span></div>
    <h4>${escapeHtml(model.title)}</h4>
    <p class="card-dek">${richInlineHtml(model.lead)}</p>
    <div class="card-footer"><div class="perspective-dots">${dots}</div><span class="card-sources">${escapeHtml(model.sources.slice(0, 3).join(' · '))}</span></div>
  </article>`;
}

function listValue(value) {
  if (!Array.isArray(value)) return '';
  return value.map((item) => {
    if (typeof item === 'string') return `<li class="insight-item">${richTextHtml(item)}</li>`;
    const primary = item.text_pl || item.text || item.fact_pl || item.fact || item.claim || item.description_pl || item.description || item.explanation_pl || item.agreement_pl || item.agreement || item.point_pl || item.point || item.differences_pl || item.difference_pl || item.difference || item.frame || item.tone_pl || item.tone || item.signal_pl || item.signal || item.reason || item.context_pl || item.context || item.unknown_pl || item.unknown || item.contradiction_pl || item.contradiction || item.event || item.headline_pl || item.what_changed_pl || item.new_information_pl || '';
    const notes = item.notes_pl || item.notes || '';
    const text = primary && notes && primary !== notes ? `${primary} ${notes}` : primary || notes;
    const marker = item.date || item.time || item.period || item.name || item.term || '';
    const rendered = marker && text ? `${marker} — ${text}` : text || marker || JSON.stringify(item);
    const sources = itemArticleSources(item);
    const sourceHtml = sources.length ? `<div class="insight-sources">${escapeHtml(sources.join(' · '))}</div>` : '';
    return `<li class="insight-item">${richTextHtml(rendered)}${sourceHtml}</li>`;
  }).join('');
}

function isNonContradictionItem(item) {
  const text = typeof item === 'string'
    ? item
    : item && (
      item.text_pl || item.text || item.contradiction_pl || item.contradiction
      || item.reason || item.difference_pl || item.difference || ''
    );
  const normalized = String(text || '').toLocaleLowerCase('pl-PL').replace(/\s+/g, ' ');
  if (!/(sprzecz|kontradyk|wyklucz)/.test(normalized)) return false;
  return /(?:brak|żadne|nie ma|nie występuj|nie wyłaniaj|nie wynikaj)/.test(normalized)
    || /(?:różnic|rozbieżn).{0,100}(?:nie oznacz|nie są|nie stanow).{0,60}(?:sprzecz|kontradyk)/.test(normalized);
}

function dialogHtml(model) {
  const summary = model.summary || {};
  const contradictions = Array.isArray(summary.contradictions)
    ? summary.contradictions.filter((item) => !isNonContradictionItem(item))
    : [];
  const bookmarked = isTopicBookmarked(model);
  const sources = model.articles.map((article) => `<div class="evidence-item"><strong>${escapeHtml(article.source_name)}</strong><span><a href="${escapeHtml(article.original_url || '#')}" target="_blank" rel="noreferrer">${escapeHtml(article.title)}</a><br /><small>${humanProfile(article.source_profile)} · ${article.word_count || '—'} słów${article.published_at ? ` · ${formatDate(article.published_at)}` : ''}</small></span></div>`).join('');
  const section = (title, items, className = '', subtitle = '') => Array.isArray(items) && items.length ? `<section class="dialog-section insight-section ${className}"><div class="insight-heading"><div><h3>${title}</h3>${subtitle ? `<p class="insight-subtitle">${subtitle}</p>` : ''}</div><span class="insight-count">${items.length}</span></div><ul class="insight-list">${listValue(items)}</ul></section>` : '';
  const updatesHtml = (model.updates || []).map((update, index) => {
    const newArticleIds = Array.isArray(update.new_article_ids) ? update.new_article_ids.map(String) : [];
    const newArticleIdSet = new Set(newArticleIds);
    const newArticleSources = [...new Set(model.articles.filter((article) => newArticleIdSet.has(String(article.article_id))).map((article) => article.source_name).filter(Boolean))];
    const updateCopy = updateText(update);
    const when = update.generated_at ? ` · ${formatDateTime(update.generated_at)}` : '';
    return `<section class="update-section ${index > 0 ? 'older-update' : ''}"><p class="update-label">AKTUALIZACJA${when}</p><h3>${index === 0 ? 'Co nowego od poprzedniej wersji?' : 'Wcześniejsza aktualizacja'}</h3><div class="rich-copy">${richTextHtml(updateCopy)}</div>${newArticleIds.length ? `<small>Nowe materiały${newArticleSources.length ? `: ${escapeHtml(newArticleSources.join(', '))}` : ''} · ${articleCountLabel(newArticleIds.length)}</small>` : ''}</section>`;
  }).join('');
  const summaryPanel = summary.summary_pl
    ? `<section class="dialog-section summary-section"><h3>Synteza</h3><div class="summary-copy">${richTextHtml(summary.summary_pl)}</div></section>`
    : '<section class="dialog-section summary-section"><p>Brak zapisanej syntezy.</p></section>';
  const factsPanel = Array.isArray(summary.facts) && summary.facts.length
    ? section('Fakty', summary.facts, 'insight-facts', 'Szczegółowe ustalenia z przypisaniem do źródeł.')
    : '<section class="dialog-section insight-section insight-facts"><div class="insight-heading"><div><h3>Fakty</h3></div></div><p>Brak zapisanych faktów.</p></section>';
  return `<div class="dialog-content"><p class="dialog-kicker">${model.hasAggregation ? 'OPRACOWANIE WIELOŹRÓDŁOWE' : 'MATERIAŁ'} <span class="coverage-pill">${articleCountLabel(model.articles.length)}</span><span class="dialog-category-pills">${categoryBadges(model.categories, 'category-pill')}</span><button class="dialog-bookmark-button ${bookmarked ? 'is-saved' : ''}" data-bookmark-topic-id="${escapeHtml(model.topic_id)}" type="button" aria-label="${bookmarked ? 'Usuń temat z zapisanych' : 'Zapisz temat'}" aria-pressed="${bookmarked}">${bookmarked ? '★ Zapisane' : '☆ Zapisz'}</button></p>
    <h2 id="dialog-title">${escapeHtml(model.title)}</h2>
    <p class="dialog-lead">${richInlineHtml(model.lead)}</p>
    <div class="dialog-rule"></div>
    ${updatesHtml}
    <div class="dialog-tabs" role="tablist" aria-label="Widok opracowania">
      <button class="dialog-tab is-active" id="dialog-tab-summary" data-dialog-tab="summary" role="tab" type="button" aria-selected="true" aria-controls="dialog-panel-summary">Synteza</button>
      <button class="dialog-tab" id="dialog-tab-facts" data-dialog-tab="facts" role="tab" type="button" aria-selected="false" aria-controls="dialog-panel-facts">Fakty</button>
    </div>
    <div class="dialog-tab-panel is-active" id="dialog-panel-summary" data-dialog-panel="summary" role="tabpanel" aria-labelledby="dialog-tab-summary">${summaryPanel}</div>
    <div class="dialog-tab-panel" id="dialog-panel-facts" data-dialog-panel="facts" role="tabpanel" aria-labelledby="dialog-tab-facts" hidden>${factsPanel}</div>
    ${section('Różne dane lub akcenty', summary.differences, 'insight-differences', 'Rozbieżności, które nie muszą oznaczać sprzeczności.')}
    ${section('Sprzeczne relacje', contradictions, 'insight-contradictions', 'Materiały podają wzajemnie wykluczające się wersje.')}
    ${section('Co warto zweryfikować', summary.potential_manipulation_signals, 'insight-verification', 'Obserwowalne sygnały wymagające dodatkowego sprawdzenia — nie werdykt o źródle.')}
    ${section('Kontekst', summary.background_context, 'insight-context')}
    <section class="dialog-section"><h3>Materiały źródłowe</h3><div class="evidence-list">${sources || '<p>Brak zapisanych linków źródłowych.</p>'}</div></section>
  </div>`;
}

function openTopic(topicId) {
  const model = modelForTopic(topicId);
  if (!model || !model.hasAggregation) return;
  openDialogTopicId = topicId;
  markTopicRead(model);
  const loading = !state.demo && !fullSummaryTopics.has(topicId);
  $('#dialog-content').innerHTML = `${loading ? '<p role="status">Ładuję pełne opracowanie…</p>' : ''}${dialogHtml(model)}`;
  const dialog = $('#story-dialog');
  if (typeof dialog.showModal === 'function') dialog.showModal();
  else dialog.setAttribute('open', '');
  render();
  if (loading) {
    const revision = dataRevision;
    loadTopicDetails(topicId).then(() => {
      if (revision === dataRevision && dialog.open && openDialogTopicId === topicId) {
        const updated = modelForTopic(topicId);
        $('#dialog-content').innerHTML = dialogHtml(updated);
        markTopicRead(updated);
        render();
      }
    }).catch((error) => {
      if (dialog.open && openDialogTopicId === topicId) showToast('Nie udało się pobrać pełnego opracowania. Otwórz temat ponownie, aby spróbować jeszcze raz.');
      console.warn('Pobieranie opracowania nie powiodło się.', error);
    });
  }
}

function filteredModels(allModels = allTopicModels()) {
  const query = state.search.trim().toLowerCase();
  return allModels.filter((topic) => {
    if (!topic.hasAggregation) return false;
    if (state.view === 'current' && !topic.isCurrent) return false;
    if (state.view === 'historical' && topic.isCurrent) return false;
    if (state.view === 'saved' && !isTopicBookmarked(topic)) return false;
    if (state.hideRead && isTopicRead(topic)) return false;
    if (state.profile !== 'ALL' && !topic.articles.some((article) => (article.source_profile || 'UNCLASSIFIED') === state.profile)) return false;
    if (state.categories.length && !state.categories.some((category) => (
      category === 'UNCLASSIFIED' ? !topic.categories.length : topic.categories.includes(category)
    ))) return false;
    if (query && !topic.searchText.includes(query)) return false;
    return true;
  }).sort((a, b) => {
    if (state.sort === 'articles') {
      return (b.articles.length - a.articles.length) || new Date(b.newestArticleAt) - new Date(a.newestArticleAt);
    }
    if (state.sort === 'sources') {
      return (b.sourceCount - a.sourceCount) || new Date(b.newestArticleAt) - new Date(a.newestArticleAt);
    }
    return new Date(b.newestArticleAt) - new Date(a.newestArticleAt);
  });
}

function render({ searchOnly = false } = {}) {
  const preparedModels = allTopicModels();
  const models = filteredModels(preparedModels);
  if (!searchOnly) {
    const allModels = preparedModels.filter((topic) => topic.hasAggregation);
    renderStats(allModels);
  }
  // Counters describe the same visible topics as the cards, including search.
  renderProfiles(models);
  renderCategories(models);
  renderSources(models);
  $('#result-count').textContent = topicCountLabel(models.length);
  $('#results-heading').textContent = state.view === 'historical'
    ? 'Historyczne agregacje'
    : state.view === 'saved' ? 'Zapisane tematy' : 'Aktualne historie';
  $('#topic-grid').innerHTML = models.map(cardHtml).join('');
  $('#empty-state').hidden = models.length > 0;
  if (!models.length) {
    $('#empty-state h3').textContent = state.connection === 'error' ? 'Nie udało się pobrać tematów' : state.connection === 'loading' ? 'Pobieram tematy…' : 'Nie znaleziono tematów';
    $('#empty-state p').textContent = state.connection === 'error' ? 'Kliknij „Odśwież dane”, aby spróbować ponownie.' : state.connection === 'loading' ? 'Dane pojawią się po zakończeniu pobierania.' : 'Spróbuj zmienić filtr albo wyszukiwane hasło.';
  }
  $('#topic-grid').querySelectorAll('[data-topic-id]').forEach((card) => {
    card.addEventListener('click', (event) => {
      if (event.target.closest('[data-bookmark-topic-id]')) return;
      openTopic(card.dataset.topicId);
    });
    card.addEventListener('keydown', (event) => {
      if (event.target.closest('[data-bookmark-topic-id]')) return;
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); openTopic(card.dataset.topicId); }
    });
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
  if (config.staticDataUrl || (config.supabaseUrl && config.supabasePublishableKey)) {
    if (await restoreSnapshot()) { setStatus(); render(); }
    await refreshData();
  } else {
    loadDemoData('To jest podgląd interfejsu. Skonfiguruj połączenie z bazą, aby zobaczyć dane.');
    setStatus(); render();
  }
}

document.addEventListener('click', (event) => {
  const dialogTab = event.target.closest('[data-dialog-tab]');
  if (dialogTab) {
    event.preventDefault();
    const dialogRoot = dialogTab.closest('.story-dialog');
    const selectedTab = dialogTab.dataset.dialogTab;
    dialogRoot?.querySelectorAll('[data-dialog-tab]').forEach((tab) => {
      const isSelected = tab === dialogTab;
      tab.classList.toggle('is-active', isSelected);
      tab.setAttribute('aria-selected', String(isSelected));
    });
    dialogRoot?.querySelectorAll('[data-dialog-panel]').forEach((panel) => {
      const isSelected = panel.dataset.dialogPanel === selectedTab;
      panel.classList.toggle('is-active', isSelected);
      panel.hidden = !isSelected;
    });
    return;
  }
  const bookmarkButton = event.target.closest('[data-bookmark-topic-id]');
  if (bookmarkButton) {
    event.preventDefault();
    event.stopPropagation();
    toggleTopicBookmark(bookmarkButton.dataset.bookmarkTopicId);
    const dialog = $('#story-dialog');
    if (dialog?.open) {
      const model = modelForTopic(bookmarkButton.dataset.bookmarkTopicId);
      if (model) $('#dialog-content').innerHTML = dialogHtml(model);
    }
    return;
  }
  const viewButton = event.target.closest('[data-view]');
  if (viewButton) { state.view = viewButton.dataset.view; document.querySelectorAll('[data-view]').forEach((button) => button.classList.toggle('is-active', button === viewButton)); render(); }
  if (event.target === $('#story-dialog')) $('#story-dialog').close();
});

$('#search-input').addEventListener('input', (event) => { state.search = event.target.value; scheduleSearchRender(); });
$('#sort-select').addEventListener('change', (event) => { state.sort = event.target.value; render(); });
$('#hide-read').addEventListener('change', (event) => {
  state.hideRead = event.target.checked;
  event.target.closest('.read-toggle')?.classList.toggle('is-active', state.hideRead);
  render();
});
$('#dialog-close').addEventListener('click', () => $('#story-dialog').close());
$('#refresh-button').addEventListener('click', () => { void refreshData({ notify: true }); });
window.addEventListener('online', () => { if (!state.demo) void refreshData(); });
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState !== 'visible' || state.demo) return;
  if (liveLoadPromise && Date.now() - liveLoadStartedAt > LOAD_TIMEOUT_MS) {
    liveLoadController?.abort();
    const activeRefresh = refreshPromise || liveLoadPromise;
    activeRefresh.then(() => refreshData(), () => refreshData());
  } else if (!liveLoadPromise && ['cached', 'error'].includes(state.connection)) {
    void refreshData();
  }
});

init();
