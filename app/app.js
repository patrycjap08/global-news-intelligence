const config = window.GNI_CONFIG || {};
const READ_STATE_KEY = 'gni.topic-read-state.v1';
const BOOKMARK_STATE_KEY = 'gni.topic-bookmarks.v1';
const FILTER_STATE_KEY = 'gni.filters.v1';
// A topic remains matchable by the backend for 36 hours, but stays in the
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
  categoryMatch: 'ANY',
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
let dialogRequestToken = 0;
const REQUEST_TIMEOUT_MS = 15000;
const LOAD_TIMEOUT_MS = 90000;
const SUMMARY_PREVIEW_COLUMNS = 'current_topic:summary->current_summary->topic,current_text:summary->current_summary->summary_pl,publication_version:summary->current_summary->publication_version,current_fact_classification_version:summary->perspective_state->fact_classification_version,fact_classification_version:summary->base_summary->fact_classification_version,current_coverage_mode:summary->perspective_state->coverage_mode,current_shared_available:summary->perspective_state->shared_available,synthesis_coverage_mode:summary->base_summary->synthesis_coverage_mode,perspective_version:summary->base_summary->perspective_version,coverage_mode:summary->base_summary->coverage_mode,shared_available:summary->base_summary->shared_available,topic_id,version,updated_at,base_topic:summary->base_summary->topic,base_text:summary->base_summary->summary_pl,legacy_topic:summary->topic,legacy_text:summary->summary_pl,update_status:summary->latest_update->status,update_text:summary->latest_update->new_information_pl,update_when:summary->latest_update->generated_at,analysis_status:summary->last_analysis->status,legacy_update_status:summary->update->status,legacy_update_text:summary->update->new_information_pl,legacy_update_when:summary->update->generated_at';
const shortDateFormatter = new Intl.DateTimeFormat('pl-PL', { day: '2-digit', month: 'short' });
const updateDateFormatter = new Intl.DateTimeFormat('pl-PL', {
  day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Warsaw',
});

function invalidateViewCache() {
  dataIndexes = null;
  modelCache = null;
}

function restoreFilterPreferences() {
  try {
    const saved = JSON.parse(window.localStorage.getItem(FILTER_STATE_KEY) || 'null');
    if (!saved || typeof saved !== 'object') return;
    if (['current', 'historical', 'saved'].includes(saved.view)) state.view = saved.view;
    if (['articles', 'sources', 'newest'].includes(saved.sort)) state.sort = saved.sort;
    if (typeof saved.hideRead === 'boolean') state.hideRead = saved.hideRead;
    if (saved.profile === 'ALL' || Object.hasOwn(PROFILE_LABELS, saved.profile)) state.profile = saved.profile;
    if (Array.isArray(saved.categories)) state.categories = [...new Set(saved.categories.filter(c => c !== 'ALL' && Object.hasOwn(CATEGORY_LABELS, c)))];
    if (['ANY', 'ALL'].includes(saved.categoryMatch)) state.categoryMatch = saved.categoryMatch;
    if (typeof saved.search === 'string') state.search = saved.search.slice(0, 500);
  } catch (error) { console.warn('Nie udało się odczytać filtrów.', error); }
}

function saveFilterPreferences() {
  try {
    const { view, sort, hideRead, profile, categories, categoryMatch, search } = state;
    window.localStorage.setItem(FILTER_STATE_KEY, JSON.stringify({ view, sort, hideRead, profile, categories, categoryMatch, search }));
  } catch (error) { console.warn('Nie udało się zapisać filtrów.', error); }
}

function syncFilterControls() {
  $('#sort-select').value = state.sort;
  $('#hide-read').checked = state.hideRead;
  $('#hide-read').closest('.read-toggle')?.classList.toggle('is-active', state.hideRead);
  $('#search-input').value = state.search;
  syncSearchClearButton();
  document.querySelectorAll('[data-view]').forEach(button => button.classList.toggle('is-active', button.dataset.view === state.view));
  document.querySelectorAll('[data-category-match]').forEach(button => {
    const selected = button.dataset.categoryMatch === state.categoryMatch;
    button.classList.toggle('is-active', selected); button.setAttribute('aria-pressed', String(selected));
  });
  $('#category-match-help').textContent = state.categoryMatch === 'ALL'
    ? 'Temat musi mieć wszystkie wybrane kategorie. Liczniki pokazują ich wspólne tematy.'
    : 'Temat może mieć dowolną z wybranych kategorii. Liczniki nie zależą od zaznaczonych kategorii.';
}

function syncSearchClearButton() {
  const button = $('#search-clear');
  if (button) button.hidden = state.search.length === 0;
}

function matchesCategories(topic, categories = state.categories, mode = state.categoryMatch) {
  const matches = category => category === 'UNCLASSIFIED' ? !topic.categories.length : topic.categories.includes(category);
  return !categories.length || (mode === 'ALL' ? categories.every(matches) : categories.some(matches));
}

function categoryCounts(baseModels) {
  const counts = { ALL: baseModels.length };
  Object.keys(CATEGORY_LABELS).filter(key => key !== 'ALL').forEach(category => {
    const selection = state.categoryMatch === 'ALL' ? [...new Set([...state.categories, category])] : [category];
    counts[category] = baseModels.filter(topic => matchesCategories(topic, selection, 'ALL')).length;
  });
  return counts;
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

function hasCyrillicTitle(value) {
  return /\p{Script=Cyrillic}/u.test(String(value ?? ''));
}

function allTopicModels() {
  // Data loaders replace these containers; local read/bookmark state is checked
  // at render time. Invalidate explicitly if data is changed in place.
  const inputs = [state.topics, state.articles, state.links, state.summaries, state.history];
  if (!modelCache || inputs.some((value, index) => value !== modelCache.inputs[index])) {
    const models = state.topics.map(topicModel).filter(model => !hasCyrillicTitle(model.title));
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
const STATE_SOURCE_PROFILES = new Set(['STATE_ALIGNED', 'STATE_MEDIA']);

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
    .replace(/<\s*\/?\s*br\s*\/?\s*>/gi, '\n')
    .replace(/\s*}+\s*$/, '');
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
  return STATE_SOURCE_PROFILES.has(profile) || sourceType === 'STATE_MEDIA';
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

function synthesisParagraphs(value) {
  let text = readableEvidenceText(value).trim();
  const paragraphs = text.split(/\n+/).map(p => p.trim()).filter(Boolean);
  if (paragraphs.length > 1 && /^(?:Podsumowując\b|Podsumowanie\s*:)/iu.test(paragraphs.at(-1))) {
    paragraphs.pop(); text = paragraphs.join('\n\n');
  }
  if (!text || text.includes('\n')) return text;
  const boundaries = [...text.matchAll(/[.!?]\s+(?=[A-ZĄĆĘŁŃÓŚŹŻ])/gu)]
    .map(match => match.index + 1)
    .filter(index => !/\b(?:r|np|itd|itp|dr|prof|nr|tzw|ul|godz)\.$/iu.test(text.slice(0, index)));
  if (!boundaries.length) return text;
  const split = boundaries.reduce((best, index) => Math.abs(index - text.length / 2) < Math.abs(best - text.length / 2) ? index : best);
  return text.slice(0, split).trim() + '\n\n' + text.slice(split).trim();
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

// The index carries the first 650 characters of the base synthesis and the
// latest accepted update. Use fields shared by previews and full details;
// article attachments, analysis timestamps and internal versions are not news.
function topicReadContent(model) {
  const update = model.updates?.[0];
  return JSON.stringify({
    base: model.summary?.perspective_version === 1 ? 'perspectives-v1' : String(model.summary?.summary_pl || '').slice(0, 650),
    update: update ? { text: updateText(update), when: update.generated_at || null } : null,
  });
}

function isTopicRead(model) {
  const record = readRecord(model);
  if (!record) return false;
  if (typeof record.content === 'string') return record.content === topicReadContent(model);
  // Preserve earlier read marks. New attachments and NO_NEW_INFORMATION do
  // not invalidate them; only an accepted update published after reading does.
  const readAt = Date.parse(record.read_at || '');
  if (Number.isFinite(readAt)) {
    const updateAt = Date.parse(model.updates?.[0]?.generated_at || '');
    if (Number.isFinite(updateAt)) return updateAt <= readAt;
    return true;
  }
  // Very old records contain only an internal version, without a read date.
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
    content: topicReadContent(model),
    article_ids: topicArticleIds(model),
    read_at: new Date().toISOString(),
  };
  saveReadTopics();
}

function missingSynthesisMessage(summary) {
  const sections = summary.perspective_sections || {};
  const hasAssessments = ['EDITORIAL', 'LEFT', 'RIGHT', 'CENTER'].some(key => (sections[key] || []).length > 0);
  if (summary.fact_classification_version === 1 && !hasAssessments) {
    return 'Nie udało się przygotować syntezy z dostępnych materiałów.';
  }
  return summary.fact_classification_version === 1
    ? 'W zebranych materiałach nie ma neutralnych ustaleń do syntezy. Dostępne są perspektywy źródeł.'
    : 'Brak ustaleń spełniających kryteria tej syntezy. Dodatkowe informacje ze źródeł są poniżej.';
}

function topicModel(topic) {
  const articlesById = articleMap();
  const topicLinks = indexes().linksByTopic.get(topic.topic_id) || [];
  const articles = topicLinks.map((link) => articlesById.get(String(link.article_id))).filter(Boolean);
  const summaryRow = state.summaries.get(topic.topic_id) || {};
  const storedSummary = summaryRow.summary || summaryRow;
  const baseSummary = storedSummary.base_summary || storedSummary;
  const currentSummary = storedSummary.current_summary || baseSummary;
  const summary = { ...currentSummary, ...(storedSummary.perspective_state || {}) };
  summary.facts = uniqueFacts(summary.facts || []);
  summary.background_context = (summary.background_context || []).filter(item => !item.needs_verification && usableDisplayFact(item));
  if (summary.perspective_version === 1) summary.synthesis_coverage_mode = currentSummary.synthesis_coverage_mode ?? currentSummary.coverage_mode;
  const stateOnly = articles.length > 0 && articles.every(isStateSource);
  if (stateOnly) {
    // Apply to previews and historical stored publications as well. Keep
    // the original database record immutable and show only state reports.
    Object.assign(summary, { coverage_mode: 'STATE_ONLY', shared_available: false,
      summary_pl: '', facts: [], background_context: [], synthesis_coverage_mode: 'STATE_ONLY' });
  }
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
  const hasAggregation = sourceCount >= 2 && (hasIndependentSource || summary.perspective_version === 1);
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
    stateOnly,
    isCurrent: topicIsCurrent(topic),
    newestArticleAt,
    profileCounts,
    summary: hasAggregation ? summary : {},
    originalSummary: baseSummary,
    mergedPublications: storedSummary.merged_publications || [],
    latestUpdate: hasAggregation && !stateOnly ? latestUpdate : {},
    latestAnalysisStatus: storedSummary.last_analysis?.status || latestUpdate.status || null,
    updates: hasAggregation && !stateOnly ? updates : [],
    summaryVersion: summaryRow.version || 1,
    summaryUpdatedAt: summaryRow.updated_at || summaryRow.generated_at || topic.last_seen_at,
    history: hasAggregation && !stateOnly ? storedHistory : [],
    title: hasAggregation ? (topic.headline_pl || summaryTopic.headline_pl || 'Temat bez tytułu') : (topic.headline_pl || 'Temat bez tytułu'),
    lead: stateOnly ? 'Dostępne są wyłącznie doniesienia mediów kontrolowanych przez państwo.' : hasAggregation ? readableEvidenceText(summaryTopic.what_happened_one_sentence_pl || summary.summary_pl || (summary.perspective_version === 1 ? 'Zebrane materiały źródłowe są dostępne poniżej.' : 'Opracowanie tego tematu jest jeszcze niedostępne.')) : 'Opracowanie dostępne po pojawieniu się materiałów z co najmniej dwóch źródeł.',
  };
  model.lead = model.lead.replace(/;\s*/g, ', ');
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
    summary: { base_summary: { topic: row.current_topic || row.base_topic || row.legacy_topic || {},
      publication_version: row.publication_version,
      summary_pl: row.current_text ?? row.base_text ?? row.legacy_text ?? '', perspective_version: row.perspective_version, fact_classification_version: row.current_fact_classification_version ?? row.fact_classification_version, coverage_mode: row.current_coverage_mode ?? row.coverage_mode, shared_available: row.current_shared_available ?? row.shared_available, synthesis_coverage_mode: row.synthesis_coverage_mode ?? row.coverage_mode },
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
  const url = new URL(path, new URL(config.staticDataUrl, window.location.href));
  // Pages caches index.json for ten minutes. A fresh manifest must not point
  // to a removed generation from an earlier deployment.
  if (path === 'index.json') url.searchParams.set('refresh', String(Date.now()));
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const controller = new AbortController();
    const abort = () => controller.abort();
    if (signal?.aborted) abort();
    signal?.addEventListener('abort', abort, { once: true });
    const timer = window.setTimeout(abort, REQUEST_TIMEOUT_MS);
    try {
      const response = await fetch(url, { cache: 'no-store', signal: controller.signal });
      if (!response.ok) {
        const error = new Error(`Dane strony: HTTP ${response.status}`);
        error.status = response.status; throw error;
      }
      return await response.json();
    } catch (error) {
      if (signal?.aborted || attempt || (error.status && ![408, 425, 429, 500, 502, 503, 504].includes(error.status))) throw error;
    } finally { window.clearTimeout(timer); signal?.removeEventListener('abort', abort); }
  }
}

async function loadStaticData(options) {
  const data = await fetchStaticJson('index.json', options.signal);
  if (data.schema !== 1 || !['topics', 'articles', 'links', 'summaries'].every((key) => Array.isArray(data[key]))
      || !data.generation || !data.exported_at) throw new Error('Niepoprawny eksport strony.');
  const sameGeneration = state.staticGeneration === data.generation;
  const previousSummaries = state.summaries, previousHistory = state.history;
  const retainedDetails = sameGeneration ? fullSummaryTopics : new Set();
  state.topics = data.topics; state.articles = data.articles; state.links = data.links;
  state.summaries = new Map(data.summaries.map((row) => [row.topic_id,
    retainedDetails.has(row.topic_id) ? previousSummaries.get(row.topic_id) || row : row]));
  fullSummaryTopics = new Set([...retainedDetails].filter(id => state.topics.some(topic => topic.topic_id === id)));
  state.history = new Map([...previousHistory].filter(([id]) => fullSummaryTopics.has(id)));
  topicDetailPromises = sameGeneration ? topicDetailPromises : new Map();
  state.staticGeneration = data.generation;
  if (!sameGeneration) dataRevision += 1; state.latestHarvestStartedAt = data.latest_harvest_started_at;
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
  let revision = dataRevision;
  const promise = (async () => {
    if (config.staticDataUrl) {
      if (!state.staticGeneration) { await loadLiveData(); revision = dataRevision; }
      let detail;
      try {
        detail = await fetchStaticJson(`${state.staticGeneration}/topics/${encodeURIComponent(topicId)}.json`);
      } catch (error) {
        if (error.status !== 404) throw error;
        // The page/cache may still reference an older snapshot after deployment.
        await loadLiveData(); revision = dataRevision;
        detail = await fetchStaticJson(`${state.staticGeneration}/topics/${encodeURIComponent(topicId)}.json`);
      }
      if (revision !== dataRevision) return;
      if (!detail || !Object.hasOwn(detail, 'summary') || (detail.summary &&
          (detail.summary.topic_id !== topicId || !detail.summary.summary || typeof detail.summary.summary !== 'object'))) {
        throw new Error('Niepoprawny plik pełnego opracowania.');
      }
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
      if ($('#story-dialog').open && openDialogTopicId) {
        const id = openDialogTopicId;
        renderTopicDialog(id, fullSummaryTopics.has(id) ? 'ready' : 'loading');
        if (!fullSummaryTopics.has(id)) void fillTopicDialog(id);
      }
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
    saveFilterPreferences(); render();
  }));
}

function renderCategories(models) {
  const counts = categoryCounts(models);
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
    saveFilterPreferences(); render();
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
    <div class="card-meta"><span class="card-badge-group"><span class="card-badge">${hasUpdate && !read ? escapeHtml(perspectiveUpdateLabel(model.latestUpdate)) : index === 0 ? 'NAJWAŻNIEJSZE' : escapeHtml(badge)}</span>${index === 0 ? `<small>${escapeHtml(badge)}</small>` : ''}<span class="card-category-group">${category}</span></span><span class="card-meta-actions"><button class="bookmark-button ${bookmarked ? 'is-saved' : ''}" data-bookmark-topic-id="${escapeHtml(model.topic_id)}" type="button" aria-label="${bookmarked ? 'Usuń temat z zapisanych' : 'Zapisz temat'}" aria-pressed="${bookmarked}">${bookmarked ? '★' : '☆'}</button><span>${formatDate(model.newestArticleAt)}</span></span></div>
    <h4>${escapeHtml(model.title)}</h4>
    <p class="card-dek">${richInlineHtml(model.lead)}</p>
    ${articleProfileBar(model)}
    <div class="card-footer"><div class="perspective-dots">${dots}</div><span class="card-sources">${escapeHtml(model.sources.slice(0, 3).join(' · '))}</span></div>
  </article>`;
}

function displayFactText(item) {
  if (typeof item === 'string') return item;
  if (!item || typeof item !== 'object') return '';
  return item.text_pl || item.text || item.fact_pl || item.fact || item.claim || item.description_pl || item.description || item.explanation_pl || item.agreement_pl || item.agreement || item.point_pl || item.point || item.differences_pl || item.difference_pl || item.difference || item.frame || item.tone_pl || item.tone || item.signal_pl || item.signal || item.reason || item.context_pl || item.context || item.unknown_pl || item.unknown || item.contradiction_pl || item.contradiction || item.event || item.headline_pl || item.what_changed_pl || item.new_information_pl || item.notes_pl || item.notes || item.name || item.term || '';
}

function usableDisplayFact(item) {
  const text = String(displayFactText(item)).trim();
  return Boolean(text) && !/\?\?|\b\d{2,4}\?|\b\d+:\?|\w+\/\w+\?|(?:brak|bez) (?:dodatkowych |nowych )?(?:ustaleń|faktów)/i.test(text)
    && !/^(?:i |oraz |ale |(?:stwierdził|twierdzi|dodał|dodaje|powiedział|podkreśla|podkreślił|uważa|ocenił|zaznaczył|zapewnił)(?=\s|[,.:]|$)|on |ona |oni |to (?:oznacza|potwierdza))/i.test(text);
}

function uniqueFacts(items) {
  const records = new Map();
  for (const item of items.filter(usableDisplayFact)) {
    const text = displayFactText(item);
    const key = normalizeDisplayText(text).replace(/\s+/g, ' ').trim().toLocaleLowerCase('pl').replace(/\.$/, '');
    if (!records.has(key)) records.set(key, typeof item === 'string' ? item : { ...item, article_ids: [...(item.article_ids || [])] });
    else if (typeof item === 'object' && typeof records.get(key) === 'object') {
      const old = records.get(key);
      old.article_ids = [...new Set([...old.article_ids, ...(item.article_ids || [])])];
      old.evidence = { ...(old.evidence || {}), ...(item.evidence || {}) };
    }
  }
  return [...records.values()];
}

function editorialCards(sections) {
  return uniqueFacts(['EDITORIAL', 'LEFT', 'RIGHT', 'CENTER'].flatMap(g => sections?.[g] || []));
}

function editorialCardsHtml(items) {
  const labels = { LEFT: 'Lewicowe', CENTER: 'Centrum', RIGHT: 'Prawicowe', STATE: 'Państwowe' };
  return items.map(item => {
    const profiles = [...new Set((item.article_ids || []).map(id => articleMap().get(String(id))).filter(Boolean).map(editorialGroup))];
    const carried = profiles.map(g => `<span class="profile-share-${g.toLowerCase()}">${labels[g] || g}</span>`).join(' · ');
    return `<div class="editorial-card">${carried ? `<p class="editorial-carried">Przytaczają: ${carried}</p>` : ''}<ul class="insight-list">${listValue([item])}</ul></div>`;
  }).join('');
}

function listValue(value) {
  if (!Array.isArray(value)) return '';
  return uniqueFacts(value).map((item) => {
    if (typeof item === 'string') return `<li class="insight-item">${richTextHtml(item)}</li>`;
    const primary = displayFactText(item);
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

const PERSPECTIVE_LABELS = { COMMON: 'Nowe informacje wspólne', LEFT: 'Nowe informacje w źródłach lewicowych', RIGHT: 'Nowe informacje w źródłach prawicowych', STATE: 'Nowe informacje w mediach kontrolowanych przez państwo' };
const CLASSIFIED_UPDATE_LABELS = { COMMON: 'Nowe ustalenia', LEFT: 'Nowe oceny w źródłach lewicowych', RIGHT: 'Nowe oceny w źródłach prawicowych', CENTER: 'Nowe oceny w źródłach centrowych', STATE: 'Nowe doniesienia mediów kontrolowanych przez państwo' };

function editorialGroup(article) {
  const profile = String(article.source_profile || '').toUpperCase();
  if (isStateSource(article)) return 'STATE';
  if (['LEFT', 'CENTER_LEFT'].includes(profile)) return 'LEFT';
  if (['RIGHT', 'CENTER_RIGHT'].includes(profile)) return 'RIGHT';
  return profile === 'CENTER' ? 'CENTER' : null;
}

function articleProfileBar(model) {
  const counts = { LEFT: 0, CENTER: 0, RIGHT: 0 };
  model.articles.forEach(a => { const group = editorialGroup(a); if (Object.hasOwn(counts, group)) counts[group] += 1; });
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  if (!total) return '';
  const labels = { LEFT: 'Lewicowe', CENTER: 'Centrum', RIGHT: 'Prawicowe' };
  const groups = Object.keys(counts);
  const percentages = Object.fromEntries(groups.map(g => [g, Math.floor(counts[g] * 100 / total)]));
  let remaining = 100 - Object.values(percentages).reduce((a,b) => a+b,0);
  [...groups].sort((a,b) => (counts[b]*100/total%1) - (counts[a]*100/total%1)).forEach(g => { if (remaining > 0) { percentages[g] += 1; remaining -= 1; } });
  const legend = groups.map(g => `<span class="profile-share-${g.toLowerCase()}">${labels[g]} <strong>${percentages[g]}% (${counts[g]})</strong></span>`).join('');
  const bar = groups.map(g => `<span class="profile-share-${g.toLowerCase()}" style="flex:${counts[g]} 1 0%;min-width:${percentages[g] === 0 ? 4 : 2}px"></span>`).join('');
  return `<div class="article-profile-share" aria-label="Udział artykułów według profilu redakcyjnego"><div class="profile-share-legend">${legend}</div><div class="profile-share-bar" aria-hidden="true">${bar}</div></div>`;
}

function coverageNotice(summary, updates = [], latestAnalysisStatus = null) {
  if (summary.coverage_mode === 'STATE_ONLY') return '<p class="coverage-notice">Dostępne są wyłącznie doniesienia mediów kontrolowanych przez państwo.</p>';
  if (summary.perspective_version !== 1) return '';
  const original = { SINGLE_LEFT: 'źródeł lewicowych', SINGLE_RIGHT: 'źródeł prawicowych', SINGLE_CENTER: 'źródeł centrowych' };
  const hasPublishedUpdate = latestAnalysisStatus !== 'NO_NEW_INFORMATION'
    && updates.some(update => update.status !== 'BASE_SUMMARY' && updateText(update));
  if (hasPublishedUpdate && summary.synthesis_coverage_mode && summary.synthesis_coverage_mode !== summary.coverage_mode && original[summary.synthesis_coverage_mode]) return `<p class="coverage-notice">Pierwotna synteza powstała wyłącznie na podstawie ${original[summary.synthesis_coverage_mode]}.</p>`;
  const messages = { SINGLE_LEFT: 'Opracowanie wyłącznie na podstawie źródeł lewicowych.', SINGLE_RIGHT: 'Opracowanie wyłącznie na podstawie źródeł prawicowych.', SINGLE_CENTER: 'Opracowanie wyłącznie na podstawie źródeł centrowych.', STATE_ONLY: 'Dostępne są wyłącznie doniesienia mediów kontrolowanych przez państwo.' };
  return messages[summary.coverage_mode] ? `<p class="coverage-notice">${messages[summary.coverage_mode]}</p>` : '';
}

function perspectiveSectionsHtml(summary, detailsState, updates = []) {
  if (summary.perspective_version !== 1) return '';
  if (detailsState !== 'ready') return '<p class="perspective-pending">Perspektywy będą dostępne po pobraniu pełnego opracowania.</p>';
  const opinions = editorialCards(summary.perspective_sections);
  const stateFacts = uniqueFacts(summary.perspective_sections?.STATE || []);
  return (opinions.length ? `<section class="perspectives-section"><h3>${summary.fact_classification_version ? 'Oceny i interpretacje' : 'Informacje uzupełniające'}</h3><p class="insight-subtitle">Jedna treść może być przytaczana przez źródła o różnych profilach. Samo cytowanie nie oznacza poparcia tej oceny przez redakcję.</p>${editorialCardsHtml(opinions)}</section>` : '')
    + (stateFacts.length ? `<section class="perspectives-section"><h3>Media kontrolowane przez państwo</h3><ul class="insight-list">${listValue(stateFacts)}</ul></section>` : '');
}

function perspectiveUpdateLabel(update) {
  if (!update.perspective_sections && !update.section_counts) return 'AKTUALIZACJA';
  const mapping = update.fact_classification_version === 1 ? CLASSIFIED_UPDATE_LABELS : PERSPECTIVE_LABELS;
  const count = g => update.perspective_sections?.[g]?.length || update.section_counts?.[g] || 0;
  if (update.fact_classification_version === 1) {
    return [count('COMMON') ? 'Nowe ustalenia' : '',
      ['EDITORIAL', 'LEFT', 'CENTER', 'RIGHT'].some(g => count(g)) ? 'Nowe oceny i interpretacje' : '',
      count('STATE') ? 'Nowe doniesienia mediów państwowych' : ''].filter(Boolean).join(' · ') || 'AKTUALIZACJA';
  }
  const labels = Object.keys(mapping).filter(g => count(g)).map(g => mapping[g]);
  if (count('EDITORIAL')) labels.push('Nowe oceny i interpretacje');
  return labels.join(' · ') || 'AKTUALIZACJA';
}

function perspectiveUpdateHtml(update) {
  if (!update.perspective_sections) return richTextHtml(updateText(update));
  const common = uniqueFacts(update.perspective_sections.COMMON || []);
  const opinions = editorialCards(update.perspective_sections);
  const stateFacts = uniqueFacts(update.perspective_sections.STATE || []);
  return (common.length ? `<h4>Nowe ustalenia</h4><ul class="insight-list">${listValue(common)}</ul>` : '')
    + (opinions.length ? `<h4>Nowe oceny i interpretacje</h4>${editorialCardsHtml(opinions)}` : '')
    + (stateFacts.length ? `<h4>Nowe doniesienia mediów państwowych</h4><ul class="insight-list">${listValue(stateFacts)}</ul>` : '');
}

function dialogHtml(model, { detailsState = 'ready' } = {}) {
  const summary = model.summary || {};
  const stateOnly = model.stateOnly || summary.coverage_mode === 'STATE_ONLY';
  const contradictions = Array.isArray(summary.contradictions)
    ? summary.contradictions.filter((item) => !isNonContradictionItem(item))
    : [];
  const bookmarked = isTopicBookmarked(model);
  const sources = model.articles.map((article) => `<div class="evidence-item"><strong>${escapeHtml(article.source_name)}</strong><span><a href="${escapeHtml(article.original_url || '#')}" target="_blank" rel="noreferrer">${escapeHtml(article.title)}</a><br /><small>${humanProfile(article.source_profile)} · ${article.word_count || '—'} słów${article.published_at ? ` · ${formatDate(article.published_at)}` : ''}</small></span></div>`).join('');
  const section = (title, items, className = '', subtitle = '') => Array.isArray(items) && items.length ? `<section class="dialog-section insight-section ${className}"><div class="insight-heading"><div><h3>${title}</h3>${subtitle ? `<p class="insight-subtitle">${subtitle}</p>` : ''}</div><span class="insight-count">${items.length}</span></div><ul class="insight-list">${listValue(items)}</ul></section>` : '';
  const factsOnly = summary.perspective_version === 1 && !summary.summary_pl;
  const summaryPanel = summary.summary_pl
    ? `<section class="dialog-section summary-section"><h3>${detailsState === 'ready' ? (summary.publication_version === 2 ? 'Aktualna synteza' : 'Synteza') : 'Skrócony podgląd syntezy'}</h3><div class="summary-copy">${richTextHtml(synthesisParagraphs(summary.summary_pl))}</div></section>`
    : '<section class="dialog-section summary-section"><p>Brak zapisanej syntezy.</p></section>';
  const factsPanel = detailsState !== 'ready'
    ? `<section class="dialog-section"><h3>Fakty</h3><p>${detailsState === 'error' ? 'Fakty będą dostępne po pobraniu pełnego opracowania. Użyj przycisku „Spróbuj ponownie” u góry.' : 'Trwa pobieranie faktów…'}</p></section>`
    : Array.isArray(summary.facts) && summary.facts.length
    ? section('Fakty', summary.facts, 'insight-facts', summary.fact_classification_version === 1 ? 'Neutralne ustalenia oraz wypowiedzi i zarzuty z przypisaniem do źródeł.' : 'Szczegółowe ustalenia z przypisaniem do źródeł.')
    : '<section class="dialog-section insight-section insight-facts"><div class="insight-heading"><div><h3>Fakty</h3></div></div><p>Brak zapisanych faktów.</p></section>';
  return `<div class="dialog-content"><p class="dialog-kicker">${stateOnly ? 'DONIESIENIA ŹRÓDŁOWE' : model.hasAggregation ? 'OPRACOWANIE WIELOŹRÓDŁOWE' : 'MATERIAŁ'} <span class="coverage-pill">${articleCountLabel(model.articles.length)}</span><span class="dialog-category-pills">${categoryBadges(model.categories, 'category-pill')}</span><button class="dialog-bookmark-button ${bookmarked ? 'is-saved' : ''}" data-bookmark-topic-id="${escapeHtml(model.topic_id)}" type="button" aria-label="${bookmarked ? 'Usuń temat z zapisanych' : 'Zapisz temat'}" aria-pressed="${bookmarked}">${bookmarked ? '★ Zapisane' : '☆ Zapisz'}</button></p>
    ${coverageNotice(summary, model.updates || [], model.latestAnalysisStatus)}
    <h2 id="dialog-title">${escapeHtml(model.title)}</h2>
    <p class="dialog-lead">${richInlineHtml(model.lead)}</p>
    ${articleProfileBar(model)}
    <div class="dialog-rule"></div>
    ${stateOnly || (summary.perspective_version === 1 && summary.shared_available === false) ? `<p class="no-common-facts" role="status">${stateOnly ? 'Dla tematu opartego wyłącznie na mediach kontrolowanych przez państwo nie tworzymy syntezy.' : missingSynthesisMessage(summary)}</p>` : `
    <div class="dialog-tabs" role="tablist" aria-label="Widok opracowania">
      ${factsOnly ? '' : '<button class="dialog-tab is-active" id="dialog-tab-summary" data-dialog-tab="summary" role="tab" type="button" aria-selected="true" aria-controls="dialog-panel-summary">Synteza</button>'}
      <button class="dialog-tab ${factsOnly ? 'is-active' : ''}" id="dialog-tab-facts" data-dialog-tab="facts" role="tab" type="button" aria-selected="${factsOnly}" aria-controls="dialog-panel-facts">Fakty</button>
    </div>
    ${factsOnly ? '' : `<div class="dialog-tab-panel is-active" id="dialog-panel-summary" data-dialog-panel="summary" role="tabpanel" aria-labelledby="dialog-tab-summary">${summaryPanel}</div>`}
    <div class="dialog-tab-panel ${factsOnly ? 'is-active' : ''}" id="dialog-panel-facts" data-dialog-panel="facts" role="tabpanel" aria-labelledby="dialog-tab-facts" ${factsOnly ? '' : 'hidden'}>${factsPanel}</div>
    `}
    ${perspectiveSectionsHtml(summary, detailsState, stateOnly ? [] : model.updates || [])}
    ${!stateOnly && model.originalSummary?.summary_pl && model.originalSummary.summary_pl !== summary.summary_pl ? `<details class="publication-history"><summary>Pierwsza opublikowana synteza</summary><div class="summary-copy">${richTextHtml(synthesisParagraphs(model.originalSummary.summary_pl))}</div></details>` : ''}
    ${!stateOnly && (model.mergedPublications || []).length ? `<details class="publication-history"><summary>Opracowania dołączone przy scalaniu (${model.mergedPublications.length})</summary>${model.mergedPublications.map(p => `<h3>${escapeHtml(p.base_summary?.topic?.headline_pl || '')}</h3><div class="summary-copy">${richTextHtml(p.base_summary?.summary_pl || '')}</div>`).join('')}</details>` : ''}
    <section class="dialog-section"><h3>Materiały źródłowe</h3><div class="evidence-list">${sources || '<p>Brak zapisanych linków źródłowych.</p>'}</div></section>
  </div>`;
}

function renderTopicDialog(topicId, detailsState, preserveTab = true) {
  const model = modelForTopic(topicId);
  if (!model) { $('#story-dialog').close(); return; }
  const dialog = $('#story-dialog');
  const scroll = preserveTab ? dialog.scrollTop : 0;
  const tab = preserveTab ? dialog.querySelector('[data-dialog-tab].is-active')?.dataset.dialogTab : null;
  const perspective = preserveTab ? dialog.querySelector('[data-perspective-tab].is-active')?.dataset.perspectiveTab : null;
  const notice = detailsState === 'loading' ? `<p class="topic-detail-status" role="status">${model.stateOnly ? 'Pobieram doniesienia źródłowe…' : 'Pobieram pełną syntezę i fakty…'}</p>`
    : detailsState === 'error' ? `<div class="topic-detail-error" role="alert"><p>${model.stateOnly ? 'Nie udało się pobrać doniesień źródłowych.' : 'Nie udało się pobrać pełnej syntezy i faktów. Poniżej jest tylko skrócony podgląd.'}</p><button type="button" data-retry-topic-details="${escapeHtml(topicId)}">Spróbuj ponownie</button></div>` : '';
  $('#dialog-content').innerHTML = notice + dialogHtml(model, { detailsState });
  if (tab && dialog.querySelector(`[data-dialog-tab="${tab}"]`)) {
    dialog.querySelectorAll('[data-dialog-tab]').forEach(button => {
      const active = button.dataset.dialogTab === tab;
      button.classList.toggle('is-active', active); button.setAttribute('aria-selected', String(active));
    });
    dialog.querySelectorAll('[data-dialog-panel]').forEach(panel => {
      const active = panel.dataset.dialogPanel === tab; panel.classList.toggle('is-active', active); panel.hidden = !active;
    });
  }
  if (perspective && dialog.querySelector(`[data-perspective-tab="${perspective}"]`)) {
    dialog.querySelectorAll('[data-perspective-tab]').forEach(button => {
      const active = button.dataset.perspectiveTab === perspective; button.classList.toggle('is-active', active); button.setAttribute('aria-selected', String(active));
    });
    dialog.querySelectorAll('[data-perspective-panel]').forEach(panel => { panel.hidden = panel.dataset.perspectivePanel !== perspective; });
  }
  dialog.scrollTop = scroll;
}

async function fillTopicDialog(topicId) {
  const token = ++dialogRequestToken;
  try {
    for (let attempt = 0; attempt < 2 && !fullSummaryTopics.has(topicId); attempt += 1) {
      await loadTopicDetails(topicId);
      if (openDialogTopicId !== topicId || token !== dialogRequestToken || !$('#story-dialog').open) return;
    }
    if (!fullSummaryTopics.has(topicId)) throw new Error('Zestaw danych zmienił się podczas pobierania.');
    if (token !== dialogRequestToken || openDialogTopicId !== topicId || !$('#story-dialog').open) return;
    const model = modelForTopic(topicId);
    if (!model) { $('#story-dialog').close(); return; }
    renderTopicDialog(topicId, 'ready'); markTopicRead(model); render();
  } catch (error) {
    if (token === dialogRequestToken && openDialogTopicId === topicId && $('#story-dialog').open) renderTopicDialog(topicId, 'error');
    console.warn('Pobieranie opracowania nie powiodło się.', error);
  }
}

function openTopic(topicId) {
  const model = modelForTopic(topicId);
  if (!model || !model.hasAggregation || hasCyrillicTitle(model.title)) return;
  openDialogTopicId = topicId;
  const loading = !state.demo && !fullSummaryTopics.has(topicId);
  if (!loading) markTopicRead(model);
  renderTopicDialog(topicId, loading ? 'loading' : 'ready', false);
  const dialog = $('#story-dialog');
  if (typeof dialog.showModal === 'function') dialog.showModal();
  else dialog.setAttribute('open', '');
  render();
  if (loading) void fillTopicDialog(topicId);
}

function filteredModels(allModels = allTopicModels(), { categorySelection = state.categories } = {}) {
  const query = state.search.trim().toLowerCase();
  return allModels.filter((topic) => {
    if (!topic.hasAggregation || hasCyrillicTitle(topic.title || topic.headline_pl)) return false;
    if (state.view === 'current' && !topic.isCurrent) return false;
    if (state.view === 'historical' && topic.isCurrent) return false;
    if (state.view === 'saved' && !isTopicBookmarked(topic)) return false;
    if (state.hideRead && isTopicRead(topic)) return false;
    if (state.profile !== 'ALL' && !topic.articles.some((article) => (article.source_profile || 'UNCLASSIFIED') === state.profile)) return false;
    if (!matchesCategories(topic, categorySelection)) return false;
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
    const allModels = preparedModels.filter((topic) => topic.hasAggregation && !hasCyrillicTitle(topic.title || topic.headline_pl));
    renderStats(allModels);
  }
  // Category facets use the same tab/read/search/profile filters, while
  // category selection is applied by categoryCounts according to ANY/ALL.
  renderProfiles(models);
  renderCategories(filteredModels(preparedModels, { categorySelection: [] }));
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
  restoreFilterPreferences(); syncFilterControls();
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
  const retryDetails = event.target.closest('[data-retry-topic-details]');
  if (retryDetails) {
    event.preventDefault(); const id = retryDetails.dataset.retryTopicDetails;
    renderTopicDialog(id, 'loading'); void fillTopicDialog(id); return;
  }
  const perspectiveTab = event.target.closest('[data-perspective-tab]');
  if (perspectiveTab) {
    event.preventDefault();
    const section = perspectiveTab.closest('.perspectives-section');
    section.querySelectorAll('[data-perspective-tab]').forEach(tab => {
      const active = tab === perspectiveTab; tab.classList.toggle('is-active', active); tab.setAttribute('aria-selected', String(active));
    });
    section.querySelectorAll('[data-perspective-panel]').forEach(panel => { panel.hidden = panel.dataset.perspectivePanel !== perspectiveTab.dataset.perspectiveTab; });
    return;
  }
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
      if (model) renderTopicDialog(model.topic_id, fullSummaryTopics.has(model.topic_id) || state.demo ? 'ready' : 'loading');
    }
    return;
  }
  const viewButton = event.target.closest('[data-view]');
  if (viewButton) { state.view = viewButton.dataset.view; saveFilterPreferences(); document.querySelectorAll('[data-view]').forEach((button) => button.classList.toggle('is-active', button === viewButton)); render(); }
  if (event.target === $('#story-dialog')) $('#story-dialog').close();
});

document.querySelectorAll('[data-category-match]').forEach(button => button.addEventListener('click', () => {
  state.categoryMatch = button.dataset.categoryMatch; saveFilterPreferences(); syncFilterControls(); render();
}));

$('#search-input').addEventListener('input', (event) => { state.search = event.target.value; syncSearchClearButton(); saveFilterPreferences(); scheduleSearchRender(); });
$('#search-clear')?.addEventListener('click', () => {
  window.clearTimeout(searchRenderTimer); searchRenderTimer = null;
  state.search = ''; $('#search-input').value = ''; syncSearchClearButton();
  saveFilterPreferences(); render({ searchOnly: true }); $('#search-input').focus();
});
$('#sort-select').addEventListener('change', (event) => { state.sort = event.target.value; saveFilterPreferences(); render(); });
$('#hide-read').addEventListener('change', (event) => {
  state.hideRead = event.target.checked; saveFilterPreferences();
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
