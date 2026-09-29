const config = window.GNI_CONFIG || {};
const READ_STATE_KEY = 'gni.topic-read-state.v1';
const BOOKMARK_STATE_KEY = 'gni.topic-bookmarks.v1';
// A topic remains matchable by the backend for 55 hours, but stays in the
// current view for 30 hours without a new article.
const TOPIC_VALIDITY_HOURS = 30;

const state = {
  topics: [],
  articles: [],
  links: [],
  xPosts: [],
  xLinks: [],
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
  return new Intl.DateTimeFormat('pl-PL', { day: '2-digit', month: 'short' }).format(date).replace('.', '');
}

function formatDateTime(value) {
  if (!value) return 'brak danych';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'brak danych';
  return new Intl.DateTimeFormat('pl-PL', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
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
function articleMap() { return new Map(state.articles.map((article) => [String(article.article_id), article])); }
function xPostMap() { return new Map(state.xPosts.map((post) => [post.post_id, post])); }
function updateText(summaryOrUpdate) {
  const nestedUpdate = summaryOrUpdate?.update;
  const update = nestedUpdate && typeof nestedUpdate === 'object'
    ? nestedUpdate
    : (summaryOrUpdate || {});
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
    const key = update.run_id || JSON.stringify({
      text: updateText(update),
      articles: update.new_article_ids || [],
      posts: update.new_x_post_ids || [],
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
  return [
    ...model.articles.map((article) => `article:${article.article_id}`),
    ...model.xPosts.map((post) => `x:${post.post_id}`),
  ].sort();
}

function topicIsCurrent(topic) {
  if (typeof topic.is_current === 'boolean') return topic.is_current;
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
  const articles = state.articles || [];
  const sourceById = new Map();
  articles.forEach((article) => {
    if (article.source_id && article.source_name) sourceById.set(String(article.source_id), article.source_name);
  });
  const sourceNameForId = (identifier) => {
    const article = articleMap().get(String(identifier));
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
  const model = state.topics.map(topicModel).find((topic) => topic.topic_id === topicId);
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
  const topicLinks = state.links.filter((link) => link.topic_id === topic.topic_id);
  const articles = topicLinks.map((link) => articlesById.get(link.article_id)).filter(Boolean);
  const postsById = xPostMap();
  const xPosts = state.xLinks
    .filter((link) => link.topic_id === topic.topic_id)
    .map((link) => postsById.get(link.post_id))
    .filter(Boolean);
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
  const hasAggregation = sourceCount >= 2;
  const articleTimestamps = articles
    .map((article) => Date.parse(article.published_at || article.fetched_at || ''))
    .filter(Number.isFinite);
  const newestArticleAt = articleTimestamps.length
    ? new Date(Math.max(...articleTimestamps)).toISOString()
    : topic.last_seen_at;
  return {
    ...topic,
    categories,
    articles,
    xPosts,
    sources: [...sources],
    sourceCount,
    hasAggregation,
    isCurrent: topicIsCurrent(topic),
    newestArticleAt,
    profileCounts,
    summary: hasAggregation ? summary : {},
    latestUpdate: hasAggregation ? latestUpdate : {},
    updates: hasAggregation ? updates : [],
    summaryVersion: summaryRow.version || 1,
    summaryUpdatedAt: summaryRow.updated_at || summaryRow.generated_at || topic.last_seen_at,
    history: hasAggregation ? storedHistory : [],
    title: hasAggregation ? (topic.headline_pl || summaryTopic.headline_pl || 'Temat bez tytułu') : (topic.headline_pl || 'Temat bez tytułu'),
    lead: hasAggregation ? readableEvidenceText(summaryTopic.what_happened_one_sentence_pl || summary.summary_pl || 'Opracowanie tego tematu jest jeszcze niedostępne.') : 'Opracowanie dostępne po pojawieniu się materiałów z co najmniej dwóch źródeł.',
  };
}

async function fetchTable(table, query = '') {
  const url = `${String(config.supabaseUrl).replace(/\/$/, '')}/rest/v1/${table}${query}`;
  const response = await fetch(url, { cache: 'no-store', headers: { apikey: config.supabasePublishableKey, Authorization: `Bearer ${config.supabasePublishableKey}` } });
  if (!response.ok) throw new Error(`${table}: HTTP ${response.status}`);
  return response.json();
}

async function fetchAllRows(table, query = '') {
  const pageSize = 1000;
  const rows = [];
  let offset = 0;
  while (true) {
    const separator = query.includes('?') ? '&' : '?';
    const page = await fetchTable(table, `${query}${separator}limit=${pageSize}&offset=${offset}`);
    rows.push(...page);
    if (page.length < pageSize) return rows;
    offset += page.length;
  }
}

async function loadLiveData() {
  const [topics, articles, links, summaries] = await Promise.all([
    fetchAllRows('app_topics', '?select=*&order=last_seen_at.desc'),
    fetchAllRows('app_articles', '?select=article_id,source_id,source_name,source_profile,source_type,title,original_url,published_at,fetched_at,word_count,description&order=published_at.desc'),
    fetchAllRows('app_topic_articles', '?select=topic_id,article_id,confidence'),
    fetchAllRows('app_topic_summaries', '?select=topic_id,version,summary,updated_at'),
  ]);
  state.topics = topics;
  state.articles = articles;
  state.links = links;
  state.summaries = new Map(summaries.map((summary) => [summary.topic_id, summary]));
  try {
    const [xPosts, xLinks] = await Promise.all([
      fetchAllRows('app_x_posts', '?select=post_id,username,display_name,category,editorial_profile,text,posted_at,url'),
      fetchAllRows('app_topic_x_posts', '?select=topic_id,post_id,confidence,assigned_at'),
    ]);
    state.xPosts = xPosts;
    state.xLinks = xLinks;
  } catch (error) {
    state.xPosts = [];
    state.xLinks = [];
    console.warn('Wpisy z X nie są jeszcze dostępne.', error);
  }
  try {
    const latestRuns = await fetchTable('app_latest_harvest', '?select=run_id,started_at&limit=1');
    state.latestHarvestStartedAt = latestRuns[0]?.started_at || null;
  } catch (error) {
    state.latestHarvestStartedAt = null;
    console.warn('Data ostatniego pobrania nie jest jeszcze dostępna.', error);
  }
  try {
    const versions = await fetchAllRows('app_topic_summary_versions', '?select=topic_id,version,summary,new_article_ids,generated_at&order=version.asc');
    state.history = new Map();
    versions.forEach((version) => {
      const versionsForTopic = state.history.get(version.topic_id) || [];
      versionsForTopic.push(version);
      state.history.set(version.topic_id, versionsForTopic);
    });
  } catch (error) {
    // The history migration is optional for an older deployment.
    state.history = new Map();
    console.warn('Historia wersji tematów jest jeszcze niedostępna.', error);
  }
  state.demo = false;
}

function loadDemoData(message) {
  state.topics = DEMO.topics;
  state.articles = DEMO.articles;
  state.links = DEMO.links;
  state.summaries = new Map(DEMO.summaries);
  state.history = new Map();
  state.xPosts = [];
  state.xLinks = [];
  state.demo = true;
  if (message) showToast(message);
}

function setStatus() {
  const status = $('#data-status');
  status.textContent = state.demo ? 'Podgląd interfejsu' : `Połączono · ${formatDate(new Date())}`;
  $('#harvest-time').textContent = state.demo ? 'Dane demonstracyjne' : `Dane z: ${formatDateTime(state.latestHarvestStartedAt)}`;
  $('#footer-updated').textContent = state.demo ? 'Tryb podglądu — skonfiguruj app/config.js, aby zobaczyć dane z Supabase.' : `Ostatnie odświeżenie: ${new Date().toLocaleTimeString('pl-PL', { hour: '2-digit', minute: '2-digit' })}`;
}

function renderStats(models) {
  $('#stat-topics').textContent = models.length;
  $('#stat-articles').textContent = new Set(models.flatMap((topic) => topic.articles.map((article) => article.article_id))).size;
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
      .map(([key, label]) => [key, label, counts[key] || 0])
      .filter(([, , count]) => count > 0),
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
      .map((key) => [key, CATEGORY_LABELS[key], counts[key] || 0])
      // Keep the Poland filter visible even before the first POLSKA category
      // has been written to Supabase. Otherwise the filter disappears and
      // there is no way to tell whether the category is supported.
      .filter(([key, , count]) => key === 'POLSKA' || count > 0),
    ...(counts.UNCLASSIFIED ? [['UNCLASSIFIED', CATEGORY_LABELS.UNCLASSIFIED, counts.UNCLASSIFIED]] : []),
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
    const topicSources = new Set();
    topic.articles.forEach((article) => {
      const source = article.source_name || 'Nieznane źródło';
      const entry = counts[source] || { topics: 0, articles: 0 };
      entry.articles += 1;
      counts[source] = entry;
      topicSources.add(source);
    });
    topicSources.forEach((source) => {
      counts[source].topics += 1;
    });
  });
  const totalTopics = models.length || 1;
  const topSources = Object.entries(counts)
    .sort(([, a], [, b]) => (b.topics - a.topics) || (b.articles - a.articles))
    .slice(0, 5);
  $('#source-list').innerHTML = topSources.length ? topSources.map(([source, count]) => {
    const percent = Math.round(count.topics / totalTopics * 100);
    const topicLabel = count.topics === 1 ? 'temat' : (count.topics < 5 ? 'tematy' : 'tematów');
    const articleLabel = count.articles === 1 ? 'artykuł' : (count.articles < 5 ? 'artykuły' : 'artykułów');
    return `<div class="source-row"><span>${escapeHtml(source)}</span><strong>${count.topics}</strong><small>${count.topics} z ${models.length} ${topicLabel} · ${count.articles} ${articleLabel} · ${percent}% obecności</small><div class="source-bar"><i style="width:${percent}%"></i></div></div>`;
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
  const hasUpdate = Boolean(updateText(model.latestUpdate));
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
  const xMaterials = model.xPosts.map((post) => `<div class="evidence-item social-evidence"><strong>${escapeHtml(post.display_name)} · X</strong><span><a href="${escapeHtml(post.url || '#')}" target="_blank" rel="noreferrer">${escapeHtml(post.text)}</a><br /><small>@${escapeHtml(post.username)}${post.posted_at ? ` · ${formatDate(post.posted_at)}` : ''} · wypowiedź autora, nie niezależne źródło prasowe</small></span></div>`).join('');
  const updatesHtml = (model.updates || []).map((update, index) => {
    const newXPostIds = Array.isArray(update.new_x_post_ids) ? update.new_x_post_ids.map(String) : [];
    const xPostIdSet = new Set(newXPostIds);
    const xPostSources = [...new Set(model.xPosts.filter((post) => xPostIdSet.has(String(post.post_id))).map((post) => `@${post.username}`))];
    const newArticleIds = Array.isArray(update.new_article_ids) ? update.new_article_ids.map(String) : [];
    const newArticleIdSet = new Set(newArticleIds);
    const newArticleSources = [...new Set(model.articles.filter((article) => newArticleIdSet.has(String(article.article_id))).map((article) => article.source_name).filter(Boolean))];
    const updateCopy = updateText(update);
    const when = update.generated_at ? ` · ${formatDate(update.generated_at)}` : '';
    return `<section class="update-section ${index > 0 ? 'older-update' : ''}"><p class="update-label">AKTUALIZACJA${when}</p><h3>${index === 0 ? 'Co nowego od poprzedniej wersji?' : 'Wcześniejsza aktualizacja'}</h3><div class="rich-copy">${richTextHtml(updateCopy)}</div>${newArticleIds.length ? `<small>Nowe materiały${newArticleSources.length ? `: ${escapeHtml(newArticleSources.join(', '))}` : ''} · ${articleCountLabel(newArticleIds.length)}</small>` : ''}${newXPostIds.length ? `<small>Nowe wpisy z X${xPostSources.length ? `: ${escapeHtml(xPostSources.join(', '))}` : ''}</small>` : ''}</section>`;
  }).join('');
  return `<div class="dialog-content"><p class="dialog-kicker">${model.hasAggregation ? 'OPRACOWANIE WIELOŹRÓDŁOWE' : 'MATERIAŁ'} <span class="coverage-pill">${articleCountLabel(model.articles.length)}</span><span class="dialog-category-pills">${categoryBadges(model.categories, 'category-pill')}</span><button class="dialog-bookmark-button ${bookmarked ? 'is-saved' : ''}" data-bookmark-topic-id="${escapeHtml(model.topic_id)}" type="button" aria-label="${bookmarked ? 'Usuń temat z zapisanych' : 'Zapisz temat'}" aria-pressed="${bookmarked}">${bookmarked ? '★ Zapisane' : '☆ Zapisz'}</button></p>
    <h2 id="dialog-title">${escapeHtml(model.title)}</h2>
    <p class="dialog-lead">${richInlineHtml(model.lead)}</p>
    <div class="dialog-rule"></div>
    ${updatesHtml}
    ${summary.summary_pl ? `<section class="dialog-section summary-section"><h3>Synteza</h3><div class="summary-copy">${richTextHtml(summary.summary_pl)}</div></section>` : ''}
    ${section('Ustalenia z pojedynczych źródeł', summary.facts, 'insight-facts', 'Informacje obecne tylko w wybranych materiałach.')}
    ${section('Wspólne ustalenia', summary.agreement, 'insight-agreement', 'Punkty, co do których materiały są zgodne.')}
    ${section('Różne dane lub akcenty', summary.differences, 'insight-differences', 'Rozbieżności, które nie muszą oznaczać sprzeczności.')}
    ${section('Sprzeczne relacje', contradictions, 'insight-contradictions', 'Materiały podają wzajemnie wykluczające się wersje.')}
    ${section('Co warto zweryfikować', summary.potential_manipulation_signals, 'insight-verification', 'Obserwowalne sygnały wymagające dodatkowego sprawdzenia — nie werdykt o źródle.')}
    ${section('Kontekst', summary.background_context, 'insight-context')}
    <section class="dialog-section"><h3>Materiały źródłowe</h3><div class="evidence-list">${sources || '<p>Brak zapisanych linków źródłowych.</p>'}</div></section>
    ${xMaterials ? `<section class="dialog-section"><h3>Powiązane wypowiedzi na X</h3><div class="evidence-list">${xMaterials}</div></section>` : ''}
  </div>`;
}

function openTopic(topicId) {
  const model = state.topics.map(topicModel).find((topic) => topic.topic_id === topicId);
  if (!model || !model.hasAggregation) return;
  markTopicRead(model);
  $('#dialog-content').innerHTML = dialogHtml(model);
  const dialog = $('#story-dialog');
  if (typeof dialog.showModal === 'function') dialog.showModal();
  else dialog.setAttribute('open', '');
  render();
}

function filteredModels() {
  const query = state.search.trim().toLowerCase();
  return state.topics.map(topicModel).filter((topic) => {
    if (!topic.hasAggregation) return false;
    if (state.view === 'current' && !topic.isCurrent) return false;
    if (state.view === 'historical' && topic.isCurrent) return false;
    if (state.view === 'saved' && !isTopicBookmarked(topic)) return false;
    if (state.hideRead && isTopicRead(topic)) return false;
    if (state.profile !== 'ALL' && !topic.articles.some((article) => (article.source_profile || 'UNCLASSIFIED') === state.profile)) return false;
    if (state.categories.length && !state.categories.some((category) => (
      category === 'UNCLASSIFIED' ? !topic.categories.length : topic.categories.includes(category)
    ))) return false;
    if (query && !`${topic.title} ${topic.lead} ${topic.sources.join(' ')}`.toLowerCase().includes(query)) return false;
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

function render() {
  const models = filteredModels();
  const allModels = state.topics.map(topicModel).filter((topic) => topic.hasAggregation);
  renderStats(allModels);
  renderProfiles(allModels);
  renderCategories(allModels);
  renderSources(models);
  $('#result-count').textContent = topicCountLabel(models.length);
  $('#results-heading').textContent = state.view === 'historical'
    ? 'Historyczne agregacje'
    : state.view === 'saved' ? 'Zapisane tematy' : 'Aktualne historie';
  $('#topic-grid').innerHTML = models.map(cardHtml).join('');
  $('#empty-state').hidden = models.length > 0;
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
  const bookmarkButton = event.target.closest('[data-bookmark-topic-id]');
  if (bookmarkButton) {
    event.preventDefault();
    event.stopPropagation();
    toggleTopicBookmark(bookmarkButton.dataset.bookmarkTopicId);
    const dialog = $('#story-dialog');
    if (dialog?.open) {
      const model = state.topics.map(topicModel).find((topic) => topic.topic_id === bookmarkButton.dataset.bookmarkTopicId);
      if (model) $('#dialog-content').innerHTML = dialogHtml(model);
    }
    return;
  }
  const viewButton = event.target.closest('[data-view]');
  if (viewButton) { state.view = viewButton.dataset.view; document.querySelectorAll('[data-view]').forEach((button) => button.classList.toggle('is-active', button === viewButton)); render(); }
  if (event.target === $('#story-dialog')) $('#story-dialog').close();
});

$('#search-input').addEventListener('input', (event) => { state.search = event.target.value; render(); });
$('#sort-select').addEventListener('change', (event) => { state.sort = event.target.value; render(); });
$('#hide-read').addEventListener('change', (event) => {
  state.hideRead = event.target.checked;
  event.target.closest('.read-toggle')?.classList.toggle('is-active', state.hideRead);
  render();
});
$('#dialog-close').addEventListener('click', () => $('#story-dialog').close());
$('#refresh-button').addEventListener('click', async () => { if (state.demo) return showToast('Podgląd nie jest jeszcze połączony z Supabase.'); $('#refresh-button').textContent = 'Odświeżam…'; try { await loadLiveData(); setStatus(); render(); showToast('Dane zostały odświeżone.'); } catch (error) { showToast('Nie udało się odświeżyć danych.'); console.warn(error); } finally { $('#refresh-button').textContent = 'Odśwież dane'; } });

init();
