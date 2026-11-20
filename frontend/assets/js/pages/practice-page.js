(function () {
  const API_BASE = window.ApiUtils && typeof window.ApiUtils.getApiBase === 'function'
    ? window.ApiUtils.getApiBase()
    : (window.location.origin || '');
  const parseApiResponse = window.ApiUtils && typeof window.ApiUtils.parseApiResponse === 'function'
    ? window.ApiUtils.parseApiResponse
    : async function (response) {
        const data = await response.json();
        if (!response.ok || data.success === false) {
          throw new Error((data && (data.error_message || data.message)) || ('请求失败(' + response.status + ')'));
        }
        return data;
      };
  const withSuggestion = window.ApiUtils && typeof window.ApiUtils.withSuggestion === 'function'
    ? window.ApiUtils.withSuggestion
    : function (prefix, error, suggestion) {
        const reason = (error && error.message) ? error.message : '未知错误';
        return prefix + '：' + reason + '。建议：' + (suggestion || '请稍后重试');
      };

  const STORE_PREFIX = 'fangzhigong_practice_history_v1';
  const SETUP_KEY = 'fangzhigong_practice_setup_v2';
  const SIDEBAR_KEY_PREFIX = 'fangzhigong_practice_sidebar_collapsed_';
  const MAX_HISTORY = 20;

  const state = {
    history: [],
    practice: null,
    view: 'setup',
    busy: false,
    selectedKeys: [],
    hintLoading: false,
    timerBase: 0,
    timerStartedAt: 0,
    timerId: 0,
    currentUserId: '',
    sidebarCollapsed: false,
    materialPoints: [],
    selectedMaterialPoint: null,
    materialStats: { itemTotal: 0, textReady: 0 }
  };

  function buildMaterialEmptyText() {
    if (state.materialStats.itemTotal > 0 && state.materialStats.textReady === 0) {
      return `已上传 ${state.materialStats.itemTotal} 份资料，但还没有可提取的文字内容（图片需要可用的 OCR 服务）。请上传 TXT、PDF、DOCX 等文本资料，或直接在「粘贴」里录入文字。`;
    }
    if (state.materialStats.textReady > 0) {
      return '资料已提取到文字，但还没有结构化知识点。可以继续用「上传/粘贴」补充更系统的笔记，或直接在下方填写知识点开始练习。';
    }
    return '还没有可用的资料知识点，先去「添加内容」上传资料，系统会自动抽取知识点。';
  }

  function getUserId() {
    return window.UserContext && typeof window.UserContext.getUserId === 'function'
      ? window.UserContext.getUserId()
      : 'default_user';
  }

  function getUserLabel() {
    return window.UserContext && typeof window.UserContext.getUserLabel === 'function'
      ? window.UserContext.getUserLabel()
      : '访客';
  }

  function escapeHtml(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (char) {
      const entityMap = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
      };
      return entityMap[char] || char;
    });
  }

  function formatMultiline(value) {
    return escapeHtml(value).replace(/\n/g, '<br>');
  }

  function toNumber(value, fallback) {
    const num = Number(value);
    return Number.isFinite(num) ? num : (typeof fallback === 'number' ? fallback : 0);
  }

  function setText(id, value) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = value == null || value === '' ? '--' : String(value);
  }

  function readJson(key) {
    try {
      const raw = window.localStorage.getItem(key);
      return raw ? JSON.parse(raw) : null;
    } catch (error) {
      return null;
    }
  }

  function writeJson(key, value) {
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
      return true;
    } catch (error) {
      return false;
    }
  }

  function getHistoryKey() {
    return `${STORE_PREFIX}_${getUserId()}`;
  }

  function getSidebarKey() {
    return `${SIDEBAR_KEY_PREFIX}${getUserId()}`;
  }

  function nowLabel(timestamp) {
    const d = new Date(Number(timestamp) || Date.now());
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const dd = String(d.getDate()).padStart(2, '0');
    const hh = String(d.getHours()).padStart(2, '0');
    const min = String(d.getMinutes()).padStart(2, '0');
    return `${mm}-${dd} ${hh}:${min}`;
  }

  function formatDuration(seconds) {
    const total = Math.max(0, Math.round(Number(seconds) || 0));
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    if (h > 0) {
      return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
    }
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  }

  function getDifficultyLabel(value) {
    const normalized = String(value || '').trim().toLowerCase();
    if (normalized === 'easy') return '简单';
    if (normalized === 'hard') return '困难';
    return '中等';
  }

  function getQuestionTypeLabel(value) {
    const normalized = String(value || '').trim().toLowerCase();
    if (normalized === 'multiple_choice' || normalized === 'multi_choice') return '多选题';
    if (normalized === 'fill_blank' || normalized === 'fill') return '填空题';
    if (normalized === 'term_definition') return '名词解释';
    if (normalized === 'step' || normalized === 'comprehensive') return '解答题';
    if (normalized === 'short_answer') return '解答题';
    if (normalized === 'retry') return '错题重练';
    return '单选题';
  }

  function matchesTypeFilter(questionType, filter) {
    const type = String(questionType || '').trim().toLowerCase();
    const target = String(filter || 'mixed').trim().toLowerCase();
    if (!target || target === 'mixed') return true;
    if (target === 'short_answer') {
      return ['short_answer', 'step', 'comprehensive', 'term_definition', 'retry'].indexOf(type) >= 0;
    }
    if (target === 'multiple_choice') {
      return type === 'multiple_choice' || type === 'multi_choice';
    }
    return type === target;
  }

  function normalizeScope(value) {
    const scope = String(value || '').trim().toLowerCase();
    if (scope === 'ai' || scope === 'mine' || scope === 'both') return scope;
    return 'both';
  }

  function normalizeQuestion(question, fallbackScope) {
    if (!question || typeof question !== 'object') return null;
    const id = String(question.id || '').trim();
    const stem = String(question.question || '').trim();
    if (!id || !stem) return null;
    return {
      id: id,
      concept: String(question.concept || '综合').trim() || '综合',
      difficulty: String(question.difficulty || 'medium').trim().toLowerCase() || 'medium',
      question_type: String(question.question_type || 'single_choice').trim().toLowerCase() || 'single_choice',
      question: stem,
      options: Array.isArray(question.options)
        ? question.options.map(function (item) { return String(item || '').trim(); }).filter(Boolean)
        : [],
      scope: normalizeScope(question.scope || fallbackScope || 'both')
    };
  }

  function normalizeQuestionStem(text) {
    return String(text || '').toLowerCase()
      .replace(/[（(]\s*扩展题\s*\d+\s*[)）]/g, '')
      .replace(/\s+/g, '')
      .replace(/[，。；：、,.!?！？;:'"“”‘’（）()【】\[\]{}<>·]/g, '');
  }

  function parseOption(raw, index) {
    let key = '';
    let text = '';
    if (raw && typeof raw === 'object') {
      key = String(raw.key || raw.label || raw.option || '').trim();
      text = String(raw.text || raw.value || raw.content || raw.option || '').trim();
    } else {
      text = String(raw || '').trim();
    }
    const match = text.match(/^([A-Fa-f])\s*[\.\、\)．:：]\s*(.*)$/);
    if (match) {
      key = match[1];
      text = match[2];
    }
    if (!key) key = String.fromCharCode(65 + index);
    return {
      key: key.toUpperCase(),
      text: text || `选项 ${key.toUpperCase()}`
    };
  }

  function isChoiceQuestion(item) {
    if (!item || !Array.isArray(item.options) || item.options.length < 2) return false;
    const type = String(item.question_type || '').trim().toLowerCase();
    return type === 'single_choice' || type === 'multiple_choice' || type === 'multi_choice';
  }

  function isMultipleChoice(item) {
    const type = String(item && item.question_type || '').trim().toLowerCase();
    return type === 'multiple_choice' || type === 'multi_choice';
  }

  function isFillBlank(item) {
    const type = String(item && item.question_type || '').trim().toLowerCase();
    return type === 'fill_blank' || type === 'fill';
  }

  function getExpectedOptionKeys(item, expectedAnswer) {
    const text = String(expectedAnswer || '').toUpperCase();
    if (!text || !item || !Array.isArray(item.options)) return [];
    const validKeys = item.options.map(function (option, index) {
      return parseOption(option, index).key;
    });
    const letters = text.match(/[A-F]/g) || [];
    return Array.from(new Set(letters.filter(function (key) {
      return validKeys.indexOf(key) >= 0;
    })));
  }

  function formatAnswerDisplay(item, value) {
    const text = String(value || '').trim();
    if (!text) return '未作答';
    if (isChoiceQuestion(item)) {
      const letters = text.toUpperCase().match(/[A-F]/g) || [];
      const parts = [];
      letters.forEach(function (key) {
        for (let i = 0; i < item.options.length; i += 1) {
          const option = parseOption(item.options[i], i);
          if (option.key === key) {
            parts.push(`${option.key}. ${option.text}`);
            break;
          }
        }
      });
      if (parts.length) return parts.join('；');
    }
    return text;
  }

  function renderMath(el) {
    if (!el || typeof window.renderMathInElement !== 'function') return;
    try {
      window.renderMathInElement(el, {
        delimiters: [
          { left: '$$', right: '$$', display: true },
          { left: '$', right: '$', display: false },
          { left: '\\(', right: '\\)', display: false },
          { left: '\\[', right: '\\]', display: true }
        ],
        throwOnError: false
      });
    } catch (error) {
      // 数学公式渲染失败时保留原始文本。
    }
  }

  /* ---------------- 计时 ---------------- */

  function getElapsedSeconds() {
    const base = Math.max(0, Number(state.timerBase) || 0);
    const running = state.timerStartedAt ? (Date.now() - state.timerStartedAt) / 1000 : 0;
    return Math.max(0, Math.round(base + running));
  }

  function updateTimerLabel() {
    const el = document.getElementById('practiceTimer');
    if (el) el.textContent = formatDuration(getElapsedSeconds());
  }

  function startTimer() {
    if (state.timerId) {
      window.clearInterval(state.timerId);
      state.timerId = 0;
    }
    state.timerStartedAt = Date.now();
    updateTimerLabel();
    state.timerId = window.setInterval(updateTimerLabel, 1000);
  }

  function stopTimer() {
    if (state.timerId) {
      window.clearInterval(state.timerId);
      state.timerId = 0;
    }
    if (state.practice) {
      state.practice.elapsedSeconds = getElapsedSeconds();
    }
    state.timerStartedAt = 0;
    state.timerBase = state.practice ? state.practice.elapsedSeconds : 0;
  }

  /* ---------------- 历史记录 ---------------- */

  function isValidSession(session) {
    return !!(session
      && session.id
      && Array.isArray(session.items)
      && session.items.length
      && session.answers
      && typeof session.answers === 'object');
  }

  function loadHistory() {
    const stored = readJson(getHistoryKey());
    state.history = Array.isArray(stored)
      ? stored.filter(isValidSession).slice(0, MAX_HISTORY)
      : [];
  }

  function saveHistory() {
    state.history = state.history
      .filter(isValidSession)
      .sort(function (left, right) {
        return Number(right.updatedAt || 0) - Number(left.updatedAt || 0);
      })
      .slice(0, MAX_HISTORY);
    writeJson(getHistoryKey(), state.history);
  }

  function findSession(sessionId) {
    return state.history.find(function (session) {
      return session.id === sessionId;
    }) || null;
  }

  function restoreSidebarState() {
    try {
      state.sidebarCollapsed = window.localStorage.getItem(getSidebarKey()) === '1';
    } catch (error) {
      state.sidebarCollapsed = false;
    }
  }

  function saveSidebarState() {
    try {
      window.localStorage.setItem(getSidebarKey(), state.sidebarCollapsed ? '1' : '0');
    } catch (error) {
      // 忽略本地存储异常。
    }
  }

  function renderSidebarHistory() {
    const section = document.getElementById('sidebarHistorySection');
    const toggle = document.getElementById('sidebarHistoryToggle');
    const count = document.getElementById('sidebarHistoryCount');
    const list = document.getElementById('conversationList');

    if (section) section.classList.toggle('collapsed', state.sidebarCollapsed);
    if (toggle) toggle.setAttribute('aria-expanded', String(!state.sidebarCollapsed));
    if (count) count.textContent = `${state.history.length} 条`;
    if (!list) return;

    if (!state.history.length) {
      list.innerHTML = '<div class="conversation-empty">暂无练习记录</div>';
      return;
    }

    list.innerHTML = state.history.map(function (session) {
      const active = state.practice && state.practice.id === session.id;
      const answered = Object.keys(session.answers || {}).length;
      const statusText = session.status === 'completed' ? '已完成' : '进行中';
      const statusClass = session.status === 'completed' ? 'is-completed' : '';
      return `
        <div class="sidebar-conversation-item ${active ? 'active' : ''}" data-practice-session="${escapeHtml(session.id)}">
          <button type="button" class="sidebar-conversation-main" data-practice-open="${escapeHtml(session.id)}">
            <div class="sidebar-conversation-title-row">
              <div class="sidebar-conversation-title">${escapeHtml(session.title || '练习')}</div>
              <span class="conversation-status-pill ${statusClass}">${statusText}</span>
            </div>
            <div class="sidebar-conversation-time">${escapeHtml(nowLabel(session.updatedAt))} · ${answered}/${session.items.length} 已答</div>
          </button>
        </div>
      `;
    }).join('');

    list.querySelectorAll('[data-practice-open]').forEach(function (button) {
      button.addEventListener('click', function () {
        openSession(this.getAttribute('data-practice-open'));
      });
    });
  }

  /* ---------------- 视图切换 ---------------- */

  function showView(view) {
    state.view = view;
    const setup = document.getElementById('practiceSetupView');
    const question = document.getElementById('practiceQuestionView');
    const result = document.getElementById('practiceResultView');
    if (setup) setup.hidden = view !== 'setup';
    if (question) question.hidden = view !== 'question';
    if (result) result.hidden = view !== 'result';
    closeSheet();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function setSetupNote(message, isError) {
    const note = document.getElementById('practiceSetupNote');
    if (!note) return;
    note.textContent = message || '';
    note.classList.toggle('is-error', !!isError);
  }

  function setSetupBusy(busy) {
    const ids = ['startPracticeBtn', 'practiceResumeBtn', 'openManageFromSetupBtn'];
    ids.forEach(function (id) {
      const el = document.getElementById(id);
      if (el) el.disabled = !!busy;
    });
  }

  /* ---------------- 配置 ---------------- */

  function getDefaultSetup() {
    return {
      concept: '',
      scope: 'both',
      count: 5,
      difficulty: '',
      type: 'mixed'
    };
  }

  function readSetupForm() {
    const concept = document.getElementById('practiceConcept');
    const scope = document.getElementById('practiceScope');
    const count = document.getElementById('practiceCount');
    const difficulty = document.getElementById('practiceDifficulty');
    const type = document.getElementById('practiceType');
    return {
      concept: String(concept ? concept.value : '').trim(),
      scope: normalizeScope(scope ? scope.value : 'both'),
      count: Math.max(1, Math.min(20, Number(count ? count.value : 5) || 5)),
      difficulty: String(difficulty ? difficulty.value : '').trim().toLowerCase(),
      type: String(type ? type.value : 'mixed').trim().toLowerCase() || 'mixed'
    };
  }

  function applyUrlSetup() {
    let params = null;
    try {
      params = new URLSearchParams(window.location.search || '');
    } catch (error) {
      params = null;
    }
    if (!params) return;
    const concept = String(params.get('concept') || '').trim();
    if (!concept) return;
    const conceptInput = document.getElementById('practiceConcept');
    if (!conceptInput) return;
    conceptInput.value = concept;
    saveSetup();
    setSetupNote(`已从资料知识点带入「${concept}」，选择题量后即可开始练习。`);
  }

  function applySetup(config) {
    const setup = Object.assign(getDefaultSetup(), config || {});
    const concept = document.getElementById('practiceConcept');
    const scope = document.getElementById('practiceScope');
    const count = document.getElementById('practiceCount');
    const difficulty = document.getElementById('practiceDifficulty');
    const type = document.getElementById('practiceType');
    if (concept) concept.value = setup.concept || '';
    if (scope) scope.value = normalizeScope(setup.scope);
    if (count) count.value = String(setup.count || 5);
    if (difficulty) difficulty.value = setup.difficulty || '';
    if (type) type.value = setup.type || 'mixed';
  }

  function saveSetup() {
    writeJson(SETUP_KEY, readSetupForm());
  }

  function restoreSetup() {
    const stored = readJson(SETUP_KEY);
    applySetup(stored || getDefaultSetup());
  }

  /* ---------------- 抽题 ---------------- */

  async function fetchAvailableQuestionTypes(config) {
    try {
      const params = new URLSearchParams({
        user_id: getUserId(),
        concept: config.concept,
        bank_scope: config.scope
      });
      if (config.difficulty) params.set('difficulty', config.difficulty);
      const response = await fetch(`${API_BASE}/api/question_bank/questions?${params.toString()}`, {
        headers: { Accept: 'application/json' }
      });
      const data = await parseApiResponse(response);
      const questions = Array.isArray(data.questions) ? data.questions : [];
      const types = new Set();
      questions.forEach(function (item) {
        const type = String(item && item.question_type || '').trim().toLowerCase();
        if (type === 'multiple_choice' || type === 'multi_choice') {
          types.add('multiple_choice');
        } else if (type === 'fill_blank' || type === 'fill') {
          types.add('fill_blank');
        } else if (type === 'single_choice') {
          types.add('single_choice');
        } else if (['short_answer', 'step', 'comprehensive', 'term_definition', 'retry'].indexOf(type) >= 0) {
          types.add('short_answer');
        }
      });
      return Array.from(types);
    } catch (error) {
      return [];
    }
  }

  async function drawQuestionBatch(config) {
    const target = Math.max(1, Number(config.count) || 5);
    const items = [];
    const seenIds = new Set();
    const seenStems = new Set();
    const maxAttempts = Math.max(target * 3, 10);
    const availableTypes = config.type === 'mixed' ? await fetchAvailableQuestionTypes(config) : [];
    const mixedPlan = availableTypes.length >= 2 ? availableTypes : [];
    let mixedCursor = Math.floor(Math.random() * Math.max(1, mixedPlan.length));
    let attempts = 0;
    let consecutiveFailures = 0;

    while (items.length < target && attempts < maxAttempts) {
      attempts += 1;
      setSetupNote(`正在抽题 ${items.length}/${target}…`);

      const desiredType = config.type === 'mixed'
        ? (mixedPlan.length ? mixedPlan[mixedCursor % mixedPlan.length] : '')
        : config.type;
      mixedCursor += 1;

      try {
        const params = new URLSearchParams({
          user_id: getUserId(),
          concept: config.concept,
          bank_scope: config.scope
        });
        if (config.difficulty) params.set('difficulty', config.difficulty);
        if (['single_choice', 'multiple_choice', 'fill_blank', 'short_answer'].indexOf(desiredType) >= 0) {
          params.set('question_type', desiredType);
        }

        const response = await fetch(`${API_BASE}/api/question_bank/draw?${params.toString()}`, {
          headers: { Accept: 'application/json' }
        });
        const data = await parseApiResponse(response);
        const question = normalizeQuestion(data.question, config.scope);
        if (!question) {
          consecutiveFailures += 1;
          if (config.type !== 'mixed' && consecutiveFailures >= 3) break;
          continue;
        }
        consecutiveFailures = 0;
        const stemKey = `${question.concept || ''}::${normalizeQuestionStem(question.question)}`;
        if (seenIds.has(question.id) || seenStems.has(stemKey)) continue;
        if (!matchesTypeFilter(question.question_type, config.type)) continue;
        seenIds.add(question.id);
        seenStems.add(stemKey);
        items.push(question);
      } catch (error) {
        consecutiveFailures += 1;
        if (config.type !== 'mixed' && consecutiveFailures >= 3) break;
      }
    }

    return items;
  }

  function createSession(config, items) {
    return {
      id: `practice_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
      title: `${config.concept} · ${items.length} 题`,
      concept: config.concept,
      scope: config.scope,
      difficulty: config.difficulty,
      type: config.type,
      requestedCount: config.count,
      items: items,
      answers: {},
      currentIndex: 0,
      status: 'active',
      startedAt: Date.now(),
      updatedAt: Date.now(),
      elapsedSeconds: 0,
      userId: getUserId()
    };
  }

  function activateSession(session) {
    if (!session) return;
    state.practice = session;
    state.selectedKeys = [];
    if (!findSession(session.id)) {
      state.history.unshift(session);
    }
    saveHistory();
    renderSidebarHistory();
  }

  async function startPractice(config) {
    if (state.busy) return;
    if (!config || !config.concept) {
      setSetupNote('请先填写要考察的知识点。', true);
      const input = document.getElementById('practiceConcept');
      if (input) input.focus();
      return;
    }

    state.busy = true;
    setSetupBusy(true);
    setSetupNote(`正在抽题 0/${config.count}…`);
    try {
      const items = await drawQuestionBatch(config);
      if (!items.length) {
        setSetupNote('没有抽到符合条件的题目，请调整知识点、题库范围、难度或题型后重试。', true);
        return;
      }

      const session = createSession(config, items);
      state.timerBase = 0;
      activateSession(session);
      showView('question');
      renderQuestion();
      startTimer();

      if (items.length < config.count) {
        setSetupNote(`题库中只抽到 ${items.length} 道符合条件的题目，已按实际题量开始。`);
      } else {
        setSetupNote('');
      }
    } catch (error) {
      setSetupNote(withSuggestion('开始练习失败', error, '确认后端服务后重试'), true);
    } finally {
      state.busy = false;
      setSetupBusy(false);
    }
  }

  function startPracticeFromForm() {
    const config = readSetupForm();
    if (!config.concept) {
      setSetupNote('请先填写要考察的知识点。', true);
      const input = document.getElementById('practiceConcept');
      if (input) input.focus();
      return;
    }
    saveSetup();
    startPractice(config);
  }

  /* ---------------- 资料知识点（上传资料驱动出题） ---------------- */

  function setMaterialHint(text, isError) {
    const hint = document.getElementById('practiceMaterialHint');
    if (!hint) return;
    hint.textContent = text;
    hint.style.color = isError ? '#b42318' : '';
  }

  function renderMaterialChips() {
    const chips = document.getElementById('practiceMaterialChips');
    const generateBtn = document.getElementById('practiceMaterialGenerateBtn');
    if (!chips) return;

    if (!state.materialPoints.length) {
      chips.innerHTML = `<span class="practice-material-empty">${escapeHtml(buildMaterialEmptyText())}</span>`;
      if (generateBtn) generateBtn.hidden = true;
      return;
    }

    chips.innerHTML = state.materialPoints.map(function (point, index) {
      const active = state.selectedMaterialPoint && state.selectedMaterialPoint.id === point.id;
      return `<button type="button" class="practice-material-chip ${active ? 'is-active' : ''}" data-material-point="${index}" title="${escapeHtml(point.detail || point.title || '')}">${escapeHtml(point.title || '未命名知识点')}</button>`;
    }).join('');

    if (generateBtn) {
      generateBtn.hidden = !state.selectedMaterialPoint;
      generateBtn.textContent = state.selectedMaterialPoint
        ? `用「${state.selectedMaterialPoint.title}」出题并开始`
        : '用该知识点出题并开始';
    }
  }

  async function loadMaterialKnowledgePoints(silent) {
    const block = document.getElementById('practiceMaterialBlock');
    const chips = document.getElementById('practiceMaterialChips');
    if (!block || !chips) return;
    block.hidden = false;
    if (!silent) {
      setMaterialHint('正在读取上传资料的知识点…');
    }

    try {
      const params = new URLSearchParams({ user_id: getUserId(), limit: '24' });
      const response = await fetch(`${API_BASE}/api/spaces/knowledge-points?${params.toString()}`, {
        headers: { Accept: 'application/json' }
      });
      const data = await parseApiResponse(response);
      const points = Array.isArray(data.points) ? data.points : [];
      state.materialPoints = points.map(function (point) {
        return {
          id: String(point.id || point.title || ''),
          title: String(point.title || '').trim(),
          detail: String(point.detail || '').trim(),
          itemId: String(point.itemId || ''),
          itemName: String(point.itemName || ''),
          spaceId: String(point.spaceId || '')
        };
      }).filter(function (point) { return point.title; });
      if (state.selectedMaterialPoint) {
        const matched = state.materialPoints.find(function (point) {
          return point.id === state.selectedMaterialPoint.id;
        });
        state.selectedMaterialPoint = matched || null;
      }
      state.materialStats = {
        itemTotal: Number(data.item_total) || 0,
        textReady: Number(data.text_ready) || 0
      };
      setMaterialHint(state.materialPoints.length
        ? `已抽取 ${state.materialPoints.length} 个资料知识点，点击即可用于出题`
        : (state.materialStats.itemTotal > 0 && state.materialStats.textReady === 0
            ? `已上传 ${state.materialStats.itemTotal} 份资料，但还没有可提取的文字内容（图片需要可用的 OCR 服务）`
            : (state.materialStats.textReady > 0
                ? `已提取到 ${state.materialStats.textReady} 份资料的文字，但未识别到结构化知识点`
                : '还没有可用的资料知识点，先去「添加内容」上传资料')));
      renderMaterialChips();
    } catch (error) {
      state.materialPoints = [];
      const reason = (error && error.message) ? String(error.message) : '';
      setMaterialHint(
        reason
          ? `资料知识点读取失败：${reason}（请确认后端服务已启动并重启过）`
          : '资料知识点读取失败，请稍后刷新重试',
        true
      );
      renderMaterialChips();
    }
  }

  function selectMaterialPoint(index) {
    const point = state.materialPoints[Number(index)];
    if (!point) return;
    state.selectedMaterialPoint = point;
    const conceptInput = document.getElementById('practiceConcept');
    if (conceptInput) conceptInput.value = point.title;
    renderMaterialChips();
    saveSetup();
    setMaterialHint(point.itemName
      ? `已选择「${point.title}」，来源：${point.itemName}`
      : `已选择「${point.title}」`);
  }

  async function generatePracticeFromMaterial() {
    const point = state.selectedMaterialPoint;
    if (!point) {
      setMaterialHint('请先点击一个资料知识点', true);
      return;
    }
    if (state.busy) return;

    const generateBtn = document.getElementById('practiceMaterialGenerateBtn');
    const config = readSetupForm();
    const count = Math.max(1, Math.min(10, Number(config.count) || 5));
    const difficulty = config.difficulty || '';

    if (generateBtn) {
      generateBtn.disabled = true;
      generateBtn.textContent = '正在根据资料出题…';
    }
    setMaterialHint(`正在根据「${point.title}」生成练习题…`);

    try {
      const response = await fetch(`${API_BASE}/api/question_bank/generate_from_material`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({
          user_id: getUserId(),
          item_id: point.itemId,
          space_id: point.spaceId,
          knowledge_point: point.title,
          difficulty: difficulty,
          count: count
        })
      });
      const data = await parseApiResponse(response);
      const concept = String(data.concept || point.title || '').trim();
      const conceptInput = document.getElementById('practiceConcept');
      if (conceptInput) conceptInput.value = concept;
      saveSetup();
      setMaterialHint(`已根据资料生成 ${Number(data.generated_count) || 0} 道题目，正在开始练习…`);
      await startPractice({
        concept: concept,
        scope: 'both',
        count: count,
        difficulty: difficulty,
        type: 'mixed'
      });
    } catch (error) {
      setMaterialHint(withSuggestion('资料出题失败', error, '请确认资料已上传成功后再试'), true);
    } finally {
      if (generateBtn) {
        generateBtn.disabled = false;
      }
      renderMaterialChips();
    }
  }

  /* ---------------- 题目渲染 ---------------- */

  function getCurrentItem() {
    const session = state.practice;
    if (!session || !Array.isArray(session.items)) return null;
    return session.items[session.currentIndex] || null;
  }

  function renderOptions(item, answer) {
    const container = document.getElementById('practiceOptions');
    if (!container) return;
    container.innerHTML = '';

    if (!isChoiceQuestion(item)) {
      container.hidden = true;
      return;
    }

    container.hidden = false;
    const userKeys = answer ? (String(answer.value || '').toUpperCase().match(/[A-F]/g) || []) : [];
    let expectedKeys = answer ? getExpectedOptionKeys(item, answer.expectedAnswer) : [];
    if (answer && answer.correct && !expectedKeys.length) {
      expectedKeys = userKeys.slice();
    }

    item.options.forEach(function (raw, index) {
      const option = parseOption(raw, index);
      const button = document.createElement('button');
      button.type = 'button';
      button.className = `practice-option${isMultipleChoice(item) ? ' is-multiple' : ''}`;
      button.dataset.key = option.key;
      button.innerHTML = `<span class="practice-option-key">${escapeHtml(option.key)}</span><span class="practice-option-text">${escapeHtml(option.text)}</span>`;

      if (answer) {
        button.disabled = true;
        if (expectedKeys.indexOf(option.key) >= 0) {
          button.classList.add('is-correct');
        } else if (userKeys.indexOf(option.key) >= 0) {
          button.classList.add('is-wrong');
        }
      } else {
        button.addEventListener('click', function () {
          selectOption(option.key);
        });
      }

      container.appendChild(button);
    });

    renderMath(container);
  }

  function renderFeedback(item, answer) {
    const el = document.getElementById('practiceFeedback');
    if (!el) return;
    el.hidden = false;
    el.className = `practice-feedback ${answer.correct ? 'is-correct' : 'is-wrong'}`;

    const scorePct = Math.round(toNumber(answer.score, 0) * 100);
    const lines = [
      `<div class="practice-feedback-title">${answer.correct ? '回答正确' : '待改进'} · ${scorePct} 分</div>`
    ];

    if (answer.feedback) {
      lines.push(`<div class="practice-feedback-body">${formatMultiline(answer.feedback)}</div>`);
    }

    if (!answer.correct && answer.expectedAnswer) {
      const expectedText = formatAnswerDisplay(item, answer.expectedAnswer);
      lines.push(`<div class="practice-feedback-answer"><b>参考答案：</b>${formatMultiline(expectedText)}</div>`);
    }

    const meta = [];
    const mastery = answer.mastery || {};
    if (mastery['知识点']) {
      const masteryPct = Math.round(toNumber(mastery['掌握度'], 0) * 100);
      meta.push(`知识掌握：${escapeHtml(mastery['知识点'])} · ${masteryPct}%${mastery['状态'] ? `（${escapeHtml(mastery['状态'])}）` : ''}`);
    }
    const diagnosis = answer.diagnosis || {};
    if (diagnosis.error_type) {
      meta.push(`错误归因：${escapeHtml(diagnosis.error_type)}`);
    }
    const advice = answer.advice || {};
    if (advice['建议']) {
      meta.push(`学习建议：${escapeHtml(advice['建议'])}`);
    }
    if (Array.isArray(advice['推荐行动']) && advice['推荐行动'].length) {
      meta.push(`推荐行动：${escapeHtml(advice['推荐行动'].join('、'))}`);
    }
    if (meta.length) {
      lines.push(`<div class="practice-feedback-meta">${meta.join('<br>')}</div>`);
    }

    el.innerHTML = lines.join('');
    renderMath(el);
  }

  function renderQuestion() {
    const session = state.practice;
    if (!session || !Array.isArray(session.items) || !session.items.length) return;

    session.currentIndex = Math.max(0, Math.min(session.items.length - 1, Number(session.currentIndex) || 0));
    const item = getCurrentItem();
    if (!item) return;

    const index = session.currentIndex;
    setText('practiceSessionTitle', session.title);
    setText('practiceProgressText', `${index + 1} / ${session.items.length}`);
    const fill = document.getElementById('practiceProgressFill');
    if (fill) fill.style.width = `${((index + 1) / session.items.length) * 100}%`;

    setText('practiceQuestionConcept', item.concept || '综合');
    setText('practiceQuestionType', getQuestionTypeLabel(item.question_type));
    setText('practiceQuestionDifficulty', getDifficultyLabel(item.difficulty));

    const stem = document.getElementById('practiceStem');
    if (stem) {
      stem.textContent = item.question;
      renderMath(stem);
    }

    const answer = session.answers[item.id];
    renderOptions(item, answer);

    const isChoice = isChoiceQuestion(item);
    const fillBlank = isFillBlank(item);
    const subjective = !isChoice && !fillBlank;

    const shortWrap = document.getElementById('practiceShortAnswerWrap');
    const input = document.getElementById('practiceAnswerInput');
    if (shortWrap) shortWrap.hidden = !subjective;
    if (input) {
      input.disabled = !!answer;
      input.value = answer && subjective ? String(answer.value || '') : '';
    }

    const fillWrap = document.getElementById('practiceFillBlankWrap');
    const fillInput = document.getElementById('practiceFillBlankInput');
    if (fillWrap) fillWrap.hidden = !fillBlank;
    if (fillInput) {
      fillInput.disabled = !!answer;
      fillInput.value = answer && fillBlank ? String(answer.value || '') : '';
    }

    const choiceNote = document.getElementById('practiceChoiceNote');
    if (choiceNote) {
      choiceNote.hidden = !(isChoice && isMultipleChoice(item));
    }

    const hint = document.getElementById('practiceHintPanel');
    const hintBody = document.getElementById('practiceHintBody');
    if (hint) hint.hidden = true;
    if (hintBody) hintBody.textContent = '';
    state.hintLoading = false;

    const feedback = document.getElementById('practiceFeedback');
    if (answer) {
      renderFeedback(item, answer);
    } else if (feedback) {
      feedback.hidden = true;
      feedback.innerHTML = '';
      feedback.className = 'practice-feedback';
    }

    const submitBtn = document.getElementById('practiceSubmitBtn');
    const nextBtn = document.getElementById('practiceNextBtn');
    const prevBtn = document.getElementById('practicePrevBtn');
    const hintBtn = document.getElementById('practiceHintBtn');
    const isLast = index >= session.items.length - 1;

    if (submitBtn) {
      submitBtn.hidden = !!answer;
      submitBtn.disabled = !answer && isChoice && !state.selectedKeys.length;
    }
    if (nextBtn) {
      nextBtn.hidden = !answer;
      nextBtn.textContent = isLast ? '查看结果' : '下一题';
    }
    if (prevBtn) prevBtn.disabled = index <= 0;
    if (hintBtn) hintBtn.disabled = false;

    renderSheet();

    const notice = document.getElementById('practiceSessionNotice');
    if (notice) {
      const requested = Number(session.requestedCount) || 0;
      if (requested && session.items.length < requested) {
        notice.hidden = false;
        notice.textContent = `题库中可用的不重复题目只有 ${session.items.length} 道，已按实际题量开始。`;
      } else {
        notice.hidden = true;
        notice.textContent = '';
      }
    }
  }

  function selectOption(key) {
    const session = state.practice;
    const item = getCurrentItem();
    if (!session || !item || session.answers[item.id] || !isChoiceQuestion(item)) return;

    const normalized = String(key || '').toUpperCase();
    if (isMultipleChoice(item)) {
      const index = state.selectedKeys.indexOf(normalized);
      if (index >= 0) {
        state.selectedKeys.splice(index, 1);
      } else {
        state.selectedKeys.push(normalized);
      }
      state.selectedKeys.sort();
    } else {
      state.selectedKeys = [normalized];
    }

    const buttons = document.querySelectorAll('#practiceOptions .practice-option');
    buttons.forEach(function (button) {
      button.classList.toggle('is-selected', state.selectedKeys.indexOf(button.dataset.key) >= 0);
    });
    const submitBtn = document.getElementById('practiceSubmitBtn');
    if (submitBtn) submitBtn.disabled = !state.selectedKeys.length;
    const feedback = document.getElementById('practiceFeedback');
    if (feedback && feedback.classList.contains('is-wrong')) {
      feedback.hidden = true;
      feedback.innerHTML = '';
      feedback.className = 'practice-feedback';
    }
  }

  function collectAnswer(item) {
    if (isChoiceQuestion(item)) {
      return isMultipleChoice(item)
        ? state.selectedKeys.slice().sort().join('')
        : String(state.selectedKeys[0] || '').trim();
    }
    if (isFillBlank(item)) {
      const fillInput = document.getElementById('practiceFillBlankInput');
      return String(fillInput ? fillInput.value : '').trim();
    }
    const input = document.getElementById('practiceAnswerInput');
    return String(input ? input.value : '').trim();
  }

  function showInlineError(message) {
    const feedback = document.getElementById('practiceFeedback');
    if (!feedback) return;
    feedback.hidden = false;
    feedback.className = 'practice-feedback is-wrong';
    feedback.innerHTML = `<div class="practice-feedback-title">提示</div><div class="practice-feedback-body">${escapeHtml(message)}</div>`;
  }

  async function submitCurrentAnswer() {
    if (state.busy) return;
    const session = state.practice;
    const item = getCurrentItem();
    if (!session || !item || session.answers[item.id]) return;

    const answerText = collectAnswer(item);
    if (!answerText) {
      showInlineError(isChoiceQuestion(item) ? '请先选择一个选项。' : '请先写下你的答案。');
      return;
    }

    state.busy = true;
    const submitBtn = document.getElementById('practiceSubmitBtn');
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = '提交中…';
    }

    try {
      const response = await fetch(`${API_BASE}/api/question_bank/answer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: getUserId(),
          question_id: item.id,
          user_answer: answerText
        })
      });
      const data = await parseApiResponse(response);

      session.answers[item.id] = {
        value: answerText,
        correct: !!data.is_correct,
        score: toNumber(data.score, 0),
        feedback: String(data.feedback || ''),
        expectedAnswer: String(data.expected_answer || ''),
        mastery: data.mastery_assessment || {},
        diagnosis: data.diagnosis || {},
        advice: data.learning_advice || {},
        nextAction: String(data.next_action || '')
      };
      session.updatedAt = Date.now();
      state.selectedKeys = [];
      saveHistory();
      renderQuestion();
      renderSidebarHistory();
    } catch (error) {
      showInlineError(withSuggestion('提交失败', error, '稍后重试'));
    } finally {
      state.busy = false;
      if (submitBtn) {
        submitBtn.textContent = '提交答案';
        submitBtn.disabled = !!session.answers[item.id];
      }
    }
  }

  async function requestHint() {
    const session = state.practice;
    const item = getCurrentItem();
    if (!session || !item || state.hintLoading) return;

    const panel = document.getElementById('practiceHintPanel');
    const body = document.getElementById('practiceHintBody');
    const hintBtn = document.getElementById('practiceHintBtn');
    if (!panel || !body) return;

    panel.hidden = false;
    body.textContent = 'AI 正在生成提示…';
    state.hintLoading = true;
    if (hintBtn) hintBtn.disabled = true;

    const promptParts = [
      '你现在是练题辅导老师，请只给启发式提示，不要直接给出完整答案或最终选项。',
      '请优先给出：关键知识点、审题方向、第一步该怎么做。',
      '',
      `知识点：${item.concept || '综合'}｜难度：${getDifficultyLabel(item.difficulty)}｜题型：${getQuestionTypeLabel(item.question_type)}`,
      item.question
    ];
    if (isChoiceQuestion(item)) {
      item.options.forEach(function (raw, index) {
        const option = parseOption(raw, index);
        promptParts.push(`${option.key}. ${option.text}`);
      });
    }
    promptParts.push('');
    promptParts.push('请给我一个提示，先不要公布答案。');

    try {
      let response = await fetch(`${API_BASE}/api/ask`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question: promptParts.join('\n'),
          user_id: getUserId()
        })
      });
      if (response.status === 405) {
        const query = new URLSearchParams({
          question: promptParts.join('\n'),
          user_id: getUserId()
        });
        response = await fetch(`${API_BASE}/api/ask?${query.toString()}`, { method: 'GET' });
      }
      const data = await parseApiResponse(response);
      body.innerHTML = formatMultiline(String(data.answer || '暂时没有生成提示，请稍后重试。'));
      renderMath(body);
    } catch (error) {
      body.textContent = withSuggestion('提示生成失败', error, '稍后重试');
    } finally {
      state.hintLoading = false;
      if (hintBtn) hintBtn.disabled = false;
    }
  }

  /* ---------------- 答题卡 ---------------- */

  function renderSheet() {
    const session = state.practice;
    const grid = document.getElementById('practiceSheetGrid');
    const progress = document.getElementById('practiceSheetProgress');
    if (!session || !grid) return;

    grid.innerHTML = session.items.map(function (item, index) {
      const answer = session.answers[item.id];
      const classes = ['practice-sheet-cell'];
      if (index === session.currentIndex) classes.push('is-current');
      if (answer) classes.push(answer.correct ? 'is-correct' : 'is-wrong');
      return `<button type="button" class="${classes.join(' ')}" data-question-index="${index}">${index + 1}</button>`;
    }).join('');

    grid.querySelectorAll('[data-question-index]').forEach(function (button) {
      button.addEventListener('click', function () {
        goToQuestion(Number(this.getAttribute('data-question-index')));
      });
    });

    const answered = session.items.filter(function (item) {
      return !!session.answers[item.id];
    }).length;
    if (progress) progress.textContent = `${answered} / ${session.items.length} 已答`;
  }

  function openSheet() {
    const sheet = document.getElementById('practiceSheet');
    const backdrop = document.getElementById('practiceSheetBackdrop');
    if (sheet) sheet.classList.add('is-open');
    if (backdrop) backdrop.hidden = false;
    document.body.classList.add('practice-sheet-open');
  }

  function closeSheet() {
    const sheet = document.getElementById('practiceSheet');
    const backdrop = document.getElementById('practiceSheetBackdrop');
    if (sheet) sheet.classList.remove('is-open');
    if (backdrop) backdrop.hidden = true;
    document.body.classList.remove('practice-sheet-open');
  }

  /* ---------------- 题目导航 ---------------- */

  function goToQuestion(index) {
    const session = state.practice;
    if (!session) return;
    const nextIndex = Math.max(0, Math.min(session.items.length - 1, Number(index) || 0));
    session.currentIndex = nextIndex;
    session.updatedAt = Date.now();
    saveHistory();
    state.selectedKeys = [];
    closeSheet();
    renderQuestion();
  }

  function goPrev() {
    const session = state.practice;
    if (!session || session.currentIndex <= 0) return;
    goToQuestion(session.currentIndex - 1);
  }

  function goNext() {
    const session = state.practice;
    if (!session) return;
    if (session.currentIndex >= session.items.length - 1) {
      finishPractice();
      return;
    }
    goToQuestion(session.currentIndex + 1);
  }

  function exitPractice() {
    if (state.busy) return;
    const session = state.practice;
    if (!session) {
      showView('setup');
      return;
    }
    if (!window.confirm('退出当前练习？进度会保留在左侧练习记录中。')) return;
    session.elapsedSeconds = getElapsedSeconds();
    session.updatedAt = Date.now();
    stopTimer();
    saveHistory();
    state.practice = null;
    state.selectedKeys = [];
    renderSidebarHistory();
    renderResumeButton();
    showView('setup');
  }

  function finishPractice() {
    if (state.busy) return;
    const session = state.practice;
    if (!session) return;
    if (session.status === 'completed') {
      renderResult();
      showView('result');
      return;
    }
    const unanswered = session.items.filter(function (item) {
      return !session.answers[item.id];
    }).length;
    if (unanswered > 0 && !window.confirm(`还有 ${unanswered} 题未作答，确认结束并查看结果吗？`)) {
      return;
    }
    session.status = 'completed';
    session.completedAt = Date.now();
    session.updatedAt = Date.now();
    session.elapsedSeconds = getElapsedSeconds();
    stopTimer();
    saveHistory();
    void syncPracticeSession(session);
    renderSidebarHistory();
    renderResult();
    showView('result');
  }

  /* 练习汇总上报：本地仍是主存储，服务端留档用于跨设备追溯与统计。 */
  async function syncPracticeSession(session) {
    if (!session || !API_BASE) return;
    try {
      const response = await fetch(`${API_BASE}/api/question_bank/practice-session`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({
          user_id: getUserId(),
          session: {
            id: session.id,
            title: session.title,
            concept: session.concept,
            scope: session.scope,
            difficulty: session.difficulty,
            items: session.items,
            answers: session.answers,
            elapsedSeconds: session.elapsedSeconds,
            completedAt: session.completedAt
          }
        })
      });
      if (typeof parseApiResponse === 'function') {
        await parseApiResponse(response);
      }
    } catch (error) {
      // 上报失败不阻断本地结果页，用户仍能看到本次成绩。
    }
  }

  /* ---------------- 结果页 ---------------- */

  function renderResult() {
    const session = state.practice;
    if (!session) return;

    const items = session.items;
    const answeredItems = items.filter(function (item) { return !!session.answers[item.id]; });
    const correctCount = answeredItems.filter(function (item) { return !!session.answers[item.id].correct; }).length;
    const wrongCount = answeredItems.length - correctCount;
    const unansweredCount = items.length - answeredItems.length;
    const accuracy = items.length ? Math.round((correctCount / items.length) * 100) : 0;
    const totalScore = items.reduce(function (sum, item) {
      const answer = session.answers[item.id];
      return sum + (answer ? toNumber(answer.score, 0) : 0);
    }, 0);
    const score = items.length ? Math.round((totalScore / items.length) * 100) : 0;

    setText('practiceResultTitle', session.title);
    setText('practiceResultMeta', `${items.length} 题 · 用时 ${formatDuration(session.elapsedSeconds)} · ${session.concept || '综合'}`);
    setText('practiceScore', score);
    setText('practiceCorrectCount', correctCount);
    setText('practiceWrongCount', wrongCount);
    setText('practiceUnansweredCount', unansweredCount);
    setText('practiceAccuracy', `${accuracy}%`);

    const weakConcepts = [];
    items.forEach(function (item) {
      const answer = session.answers[item.id];
      if (answer && answer.correct) return;
      const concept = item.concept || '综合';
      if (weakConcepts.indexOf(concept) < 0) weakConcepts.push(concept);
    });

    const weakRow = document.getElementById('practiceWeakRow');
    const weakTags = document.getElementById('practiceWeakTags');
    if (weakRow) weakRow.hidden = !weakConcepts.length;
    if (weakTags) {
      weakTags.innerHTML = weakConcepts.map(function (concept) {
        return `<span class="practice-weak-tag">${escapeHtml(concept)}</span>`;
      }).join('');
    }

    const retryBtn = document.getElementById('practiceRetryWrongBtn');
    if (retryBtn) retryBtn.hidden = wrongCount + unansweredCount === 0;

    const reviewList = document.getElementById('practiceReviewList');
    if (!reviewList) return;

    reviewList.innerHTML = items.map(function (item, index) {
      const answer = session.answers[item.id];
      const status = !answer ? 'unanswered' : (answer.correct ? 'correct' : 'wrong');
      const statusText = !answer ? '未作答' : (answer.correct ? '正确' : '错误');
      const userAnswer = answer ? formatAnswerDisplay(item, answer.value) : '未作答';
      let expectedAnswer = '—';
      if (answer) {
        if (answer.expectedAnswer) {
          expectedAnswer = formatAnswerDisplay(item, answer.expectedAnswer);
        } else if (answer.correct) {
          expectedAnswer = userAnswer;
        }
      }
      const explanation = answer
        ? (answer.feedback || answer.nextAction || '暂无解析')
        : '本题未作答，暂无判题解析。';

      return `
        <article class="practice-review-item">
          <div class="practice-review-head-row">
            <div class="practice-review-title">第 ${index + 1} 题 · ${escapeHtml(item.concept || '综合')} · ${escapeHtml(getQuestionTypeLabel(item.question_type))}</div>
            <span class="practice-review-status ${status}">${statusText}</span>
          </div>
          <div class="practice-review-stem">${escapeHtml(item.question)}</div>
          <div class="practice-review-grid">
            <div class="practice-review-cell"><b>你的答案</b>${escapeHtml(userAnswer)}</div>
            <div class="practice-review-cell"><b>参考答案</b>${escapeHtml(expectedAnswer)}</div>
          </div>
          <div class="practice-review-explanation">${escapeHtml(explanation)}</div>
        </article>
      `;
    }).join('');
    renderMath(reviewList);
  }

  async function retryWrongQuestions() {
    const session = state.practice;
    if (!session) return;

    let wrongItems = session.items.filter(function (item) {
      const answer = session.answers[item.id];
      return !answer || !answer.correct;
    });
    let titleSuffix = '错题重练';

    // 当前会话没有错题时，回退到服务端历史错题库（此前只在当前会话内筛选）
    if (!wrongItems.length) {
      setSetupNote('正在从错题库加载历史错题…');
      const records = await fetchWrongQuestionsFromServer();
      wrongItems = buildItemsFromWrongQuestions(records);
      titleSuffix = '历史错题重练';

      if (!wrongItems.length) {
        setSetupNote('错题库中还没有可重练的题目，先做几道题吧。', true);
        window.alert('错题库中还没有可重练的题目。');
        return;
      }
      setSetupNote(`已从错题库载入 ${wrongItems.length} 道历史错题。`);
    }

    const config = {
      concept: `${session.concept || '综合'} · 错题`,
      scope: session.scope,
      difficulty: session.difficulty,
      type: 'mixed',
      count: wrongItems.length
    };
    const nextSession = createSession(config, wrongItems.map(function (item) { return Object.assign({}, item); }));
    nextSession.title = `${session.concept || '综合'} · ${titleSuffix}`;
    state.timerBase = 0;
    activateSession(nextSession);
    showView('question');
    renderQuestion();
    startTimer();
  }

  async function fetchWrongQuestionsFromServer() {
    if (!API_BASE) return [];
    try {
      const response = await fetch(
        `${API_BASE}/api/wrong_questions?user_id=${encodeURIComponent(getUserId())}`,
        { headers: { Accept: 'application/json' } }
      );
      const data = await parseApiResponse(response);
      return Array.isArray(data.items) ? data.items : [];
    } catch (error) {
      return [];
    }
  }

  /**
   * 历史错题只保存了题干与参考答案，没有选项。
   * 统一按解答题重练，避免渲染出空选项；判分走主观题要点覆盖。
   */
  function buildItemsFromWrongQuestions(records) {
    const seen = new Set();
    const items = [];

    (Array.isArray(records) ? records : []).forEach(function (record, index) {
      if (!record || !record.question) return;

      const dedupeKey = String(record.question_id || record.question).trim();
      if (!dedupeKey || seen.has(dedupeKey)) return;
      seen.add(dedupeKey);

      items.push({
        id: `wrong_${record.question_id || record.id || index}`,
        question_id: String(record.question_id || ''),
        question: String(record.question || ''),
        concept: String(record.concept || '错题'),
        difficulty: String(record.difficulty || 'medium'),
        question_type: 'short_answer',
        options: [],
        answer: String(record.expected_answer || ''),
        source: 'wrong_question',
        previous_answer: String(record.user_answer || '')
      });
    });

    return items.slice(0, 10);
  }

  function restartPractice() {
    const session = state.practice;
    if (!session) return;
    const config = {
      concept: session.concept,
      scope: session.scope,
      difficulty: session.difficulty,
      type: session.type || 'mixed',
      count: session.requestedCount || session.items.length
    };
    applySetup(config);
    state.practice = null;
    showView('setup');
    renderResumeButton();
    startPractice(config);
  }

  function backToSetup() {
    state.practice = null;
    state.selectedKeys = [];
    renderSidebarHistory();
    renderResumeButton();
    showView('setup');
    loadMaterialKnowledgePoints(true);
  }

  /* ---------------- 继续练习 ---------------- */

  function renderResumeButton() {
    const button = document.getElementById('practiceResumeBtn');
    if (!button) return;
    const latest = state.history.find(function (session) {
      return session && session.status === 'active' && Array.isArray(session.items) && session.items.length;
    });
    if (!latest) {
      button.hidden = true;
      return;
    }
    const answered = Object.keys(latest.answers || {}).length;
    button.hidden = false;
    button.textContent = `继续：${latest.concept || '上次练习'} · ${answered}/${latest.items.length} 已答`;
    button.onclick = function () {
      openSession(latest.id);
    };
  }

  function openSession(sessionId) {
    const session = findSession(sessionId);
    if (!session) return;

    if (state.timerId) {
      stopTimer();
    }

    state.practice = session;
    state.selectedKeys = [];
    state.timerBase = Math.max(0, Number(session.elapsedSeconds) || 0);
    state.timerStartedAt = 0;
    renderSidebarHistory();

    if (session.status === 'completed') {
      renderResult();
      showView('result');
      return;
    }

    showView('question');
    renderQuestion();
    startTimer();
  }

  /* ---------------- 题库管理弹窗 ---------------- */

  function setManageStatus(text, isError) {
    const status = document.getElementById('qbManageStatus');
    if (!status) return;
    status.textContent = text || '';
    status.classList.toggle('error', !!isError);
  }

  function renderMyQuestionBankList(items) {
    const counter = document.getElementById('questionBankCounter');
    const summary = document.getElementById('questionBankModalCount');
    const list = document.getElementById('questionBankRecentList');
    const rows = Array.isArray(items) ? items : [];

    if (counter) counter.textContent = `${rows.length} 题`;
    if (summary) {
      summary.textContent = rows.length
        ? `当前共 ${rows.length} 题，预览展示最近 ${Math.min(rows.length, 6)} 题`
        : '你的题库还是空的，可以先手动新增或批量导入';
    }
    if (!list) return;

    if (!rows.length) {
      list.innerHTML = '<div class="question-bank-empty">你的题库还没有题目。新增后就可以在“我的题库”或“全部题库”中开始练习。</div>';
      return;
    }

    list.innerHTML = rows.slice(-6).reverse().map(function (item) {
      return `
        <div class="question-bank-item">
          <div class="question-bank-item-head">
            <div class="question-bank-item-concept">${escapeHtml(item.concept || '综合')}</div>
            <div class="question-bank-item-meta">${escapeHtml(getDifficultyLabel(item.difficulty))} · ${escapeHtml(getQuestionTypeLabel(item.question_type))}</div>
          </div>
          <div class="question-bank-item-question">${escapeHtml(item.question || '')}</div>
        </div>
      `;
    }).join('');
  }

  async function refreshMyQuestionBankList() {
    const response = await fetch(
      `${API_BASE}/api/question_bank/questions?user_id=${encodeURIComponent(getUserId())}&bank_scope=mine`
    );
    const data = await parseApiResponse(response);
    const questions = Array.isArray(data.questions) ? data.questions : [];
    renderMyQuestionBankList(questions);
    return questions;
  }

  function openQuestionBankModal() {
    const modal = document.getElementById('questionBankManageModal');
    if (!modal) return;
    const sidebar = modal.querySelector('.question-bank-sidebar');
    const editor = modal.querySelector('.question-bank-editor-scroll');
    if (sidebar) sidebar.scrollTop = 0;
    if (editor) editor.scrollTop = 0;
    setManageStatus('');
    modal.classList.add('show');
    document.body.classList.add('question-bank-modal-open');
    refreshMyQuestionBankList().catch(function (error) {
      setManageStatus(withSuggestion('题库加载失败', error, '稍后刷新重试'), true);
    });
  }

  function closeQuestionBankModal() {
    const modal = document.getElementById('questionBankManageModal');
    if (modal) modal.classList.remove('show');
    document.body.classList.remove('question-bank-modal-open');
  }

  function initQuestionBankModal() {
    const modal = document.getElementById('questionBankManageModal');
    const openButtons = [
      document.getElementById('manageQuestionBankBtn'),
      document.getElementById('openManageFromSetupBtn')
    ];
    const closeBtn = document.getElementById('questionBankModalCloseBtn');
    const refreshBtn = document.getElementById('questionBankModalRefreshBtn');
    const importBtn = document.getElementById('qbImportBtn');
    const importText = document.getElementById('qbImportText');
    const addBtn = document.getElementById('qbAddBtn');
    const conceptEl = document.getElementById('qbConcept');
    const difficultyEl = document.getElementById('qbDifficulty');
    const typeEl = document.getElementById('qbType');
    const questionEl = document.getElementById('qbQuestion');
    const optionsEl = document.getElementById('qbOptions');
    const answerEl = document.getElementById('qbAnswer');
    const analysisEl = document.getElementById('qbAnalysis');

    openButtons.forEach(function (button) {
      if (button && !button.dataset.bound) {
        button.addEventListener('click', openQuestionBankModal);
        button.dataset.bound = '1';
      }
    });

    if (closeBtn && !closeBtn.dataset.bound) {
      closeBtn.addEventListener('click', closeQuestionBankModal);
      closeBtn.dataset.bound = '1';
    }

    if (refreshBtn && !refreshBtn.dataset.bound) {
      refreshBtn.addEventListener('click', function () {
        setManageStatus('正在刷新题库...');
        refreshMyQuestionBankList()
          .then(function () { setManageStatus('题库已刷新。'); })
          .catch(function (error) { setManageStatus(withSuggestion('题库刷新失败', error, '稍后重试'), true); });
      });
      refreshBtn.dataset.bound = '1';
    }

    if (modal && !modal.dataset.bound) {
      modal.addEventListener('click', function (event) {
        if (event.target === modal) closeQuestionBankModal();
      });
      modal.dataset.bound = '1';
    }

    if (typeEl && optionsEl && !typeEl.dataset.bound) {
      const updateOptionsState = function () {
        const currentType = String(typeEl.value || 'single_choice');
        const isChoice = currentType === 'single_choice' || currentType === 'multiple_choice';
        optionsEl.disabled = !isChoice;
        optionsEl.style.opacity = isChoice ? '1' : '0.55';
      };
      typeEl.addEventListener('change', updateOptionsState);
      updateOptionsState();
      typeEl.dataset.bound = '1';
    }

    if (importBtn && importText && !importBtn.dataset.bound) {
      importBtn.addEventListener('click', async function () {
        const text = importText.value.trim();
        if (!text) {
          setManageStatus('请先粘贴要导入的题目内容。', true);
          return;
        }
        importBtn.disabled = true;
        importBtn.textContent = '导入中...';
        setManageStatus('正在导入题目...');
        try {
          const response = await fetch(`${API_BASE}/api/question_bank/import`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: getUserId(), text: text })
          });
          const data = await parseApiResponse(response);
          importText.value = '';
          setManageStatus(`导入成功：新增 ${data.imported_count || 0} 题。`);
          await refreshMyQuestionBankList();
        } catch (error) {
          setManageStatus(withSuggestion('导题失败', error, '检查格式后重试'), true);
        } finally {
          importBtn.disabled = false;
          importBtn.textContent = '粘贴导入';
        }
      });
      importBtn.dataset.bound = '1';
    }

    if (addBtn && !addBtn.dataset.bound) {
      addBtn.addEventListener('click', async function () {
        const concept = conceptEl.value.trim();
        const difficulty = difficultyEl.value;
        const questionType = typeEl.value;
        const question = questionEl.value.trim();
        const answer = answerEl.value.trim();
        const analysis = analysisEl.value.trim();
        const options = optionsEl.value.split('\n').map(function (line) { return line.trim(); }).filter(Boolean);

        if (!concept || !question || !answer) {
          setManageStatus('请至少填写知识点、题干和标准答案。', true);
          return;
        }
        if ((questionType === 'single_choice' || questionType === 'multiple_choice') && options.length < 2) {
          setManageStatus('选择题至少需要 2 个选项。', true);
          return;
        }
        if (questionType === 'multiple_choice' && String(answer).replace(/[^A-Za-z]/g, '').length < 2) {
          setManageStatus('多选题答案请填写至少 2 个正确选项字母，如 AC。', true);
          return;
        }

        addBtn.disabled = true;
        addBtn.textContent = '保存中...';
        setManageStatus('正在保存题目...');
        try {
          const response = await fetch(`${API_BASE}/api/question_bank/questions`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              user_id: getUserId(),
              concept: concept,
              difficulty: difficulty,
              question_type: questionType,
              question: question,
              options: options,
              answer: answer,
              analysis: analysis,
              is_public: false
            })
          });
          const data = await parseApiResponse(response);
          questionEl.value = '';
          optionsEl.value = '';
          answerEl.value = '';
          analysisEl.value = '';
          setManageStatus(`已加入题库：${(data.question && data.question.id) || '新题目'}`);
          await refreshMyQuestionBankList();
        } catch (error) {
          setManageStatus(withSuggestion('题目保存失败', error, '检查输入后重试'), true);
        } finally {
          addBtn.disabled = false;
          addBtn.textContent = '加入题库';
        }
      });
      addBtn.dataset.bound = '1';
    }
  }

  /* ---------------- 初始化 ---------------- */

  function updateUserBadge() {
    const badge = document.getElementById('chatUserBadge');
    if (badge) badge.textContent = `当前身份：${getUserLabel()}`;
  }

  function bindEvents() {
    const startBtn = document.getElementById('startPracticeBtn');
    if (startBtn) startBtn.addEventListener('click', startPracticeFromForm);

    const exitBtn = document.getElementById('practiceExitBtn');
    if (exitBtn) exitBtn.addEventListener('click', exitPractice);

    const finishBtn = document.getElementById('practiceFinishBtn');
    if (finishBtn) finishBtn.addEventListener('click', finishPractice);

    const submitBtn = document.getElementById('practiceSubmitBtn');
    if (submitBtn) submitBtn.addEventListener('click', submitCurrentAnswer);

    const hintBtn = document.getElementById('practiceHintBtn');
    if (hintBtn) hintBtn.addEventListener('click', requestHint);

    const prevBtn = document.getElementById('practicePrevBtn');
    if (prevBtn) prevBtn.addEventListener('click', goPrev);

    const nextBtn = document.getElementById('practiceNextBtn');
    if (nextBtn) nextBtn.addEventListener('click', goNext);

    const sheetToggle = document.getElementById('practiceSheetToggle');
    if (sheetToggle) sheetToggle.addEventListener('click', openSheet);

    const sheetClose = document.getElementById('practiceSheetClose');
    if (sheetClose) sheetClose.addEventListener('click', closeSheet);

    const sheetBackdrop = document.getElementById('practiceSheetBackdrop');
    if (sheetBackdrop) sheetBackdrop.addEventListener('click', closeSheet);

    const retryBtn = document.getElementById('practiceRetryWrongBtn');
    if (retryBtn) retryBtn.addEventListener('click', retryWrongQuestions);

    const restartBtn = document.getElementById('practiceRestartBtn');
    if (restartBtn) restartBtn.addEventListener('click', restartPractice);

    const backBtn = document.getElementById('practiceBackSetupBtn');
    if (backBtn) backBtn.addEventListener('click', backToSetup);

    const historyToggle = document.getElementById('sidebarHistoryToggle');
    if (historyToggle) {
      historyToggle.addEventListener('click', function () {
        state.sidebarCollapsed = !state.sidebarCollapsed;
        saveSidebarState();
        renderSidebarHistory();
      });
    }

    ['practiceConcept', 'practiceScope', 'practiceCount', 'practiceDifficulty', 'practiceType'].forEach(function (id) {
      const el = document.getElementById(id);
      if (!el) return;
      el.addEventListener('change', saveSetup);
      if (el.tagName === 'INPUT') el.addEventListener('input', saveSetup);
    });

    const conceptInput = document.getElementById('practiceConcept');
    if (conceptInput) {
      conceptInput.addEventListener('keydown', function (event) {
        if (event.key === 'Enter') {
          event.preventDefault();
          startPracticeFromForm();
        }
      });
      conceptInput.addEventListener('input', function () {
        if (!state.selectedMaterialPoint) return;
        if (conceptInput.value.trim() === state.selectedMaterialPoint.title) return;
        state.selectedMaterialPoint = null;
        renderMaterialChips();
      });
    }

    const materialChips = document.getElementById('practiceMaterialChips');
    if (materialChips) {
      materialChips.addEventListener('click', function (event) {
        const chip = event.target && event.target.closest ? event.target.closest('[data-material-point]') : null;
        if (!chip) return;
        selectMaterialPoint(chip.getAttribute('data-material-point'));
      });
    }

    const materialRefreshBtn = document.getElementById('practiceMaterialRefreshBtn');
    if (materialRefreshBtn) {
      materialRefreshBtn.addEventListener('click', function () {
        loadMaterialKnowledgePoints(false);
      });
    }

    const materialGenerateBtn = document.getElementById('practiceMaterialGenerateBtn');
    if (materialGenerateBtn) {
      materialGenerateBtn.addEventListener('click', generatePracticeFromMaterial);
    }

    document.addEventListener('keydown', function (event) {
      if (state.view !== 'question' || state.busy) return;
      const tagName = String((event.target && event.target.tagName) || '').toUpperCase();
      if (tagName === 'INPUT' || tagName === 'TEXTAREA' || tagName === 'SELECT') return;

      const item = getCurrentItem();
      if (!item || !state.practice) return;
      const answer = state.practice.answers[item.id];
      if (!answer && isChoiceQuestion(item)) {
        const key = String(event.key || '').toUpperCase();
        if (/^[A-F]$/.test(key)) {
          const exists = item.options.some(function (raw, index) {
            return parseOption(raw, index).key === key;
          });
          if (exists) {
            event.preventDefault();
            selectOption(key);
          }
        }
      }

      if (event.key === 'Enter') {
        if (tagName === 'BUTTON') return;
        const nextBtn = document.getElementById('practiceNextBtn');
        const submitBtn = document.getElementById('practiceSubmitBtn');
        if (nextBtn && !nextBtn.hidden) {
          event.preventDefault();
          goNext();
        } else if (submitBtn && !submitBtn.hidden && !submitBtn.disabled) {
          event.preventDefault();
          submitCurrentAnswer();
        }
      }
    });

    const media = window.matchMedia('(min-width: 1101px)');
    const handleMedia = function (event) {
      if (event.matches) closeSheet();
    };
    if (typeof media.addEventListener === 'function') {
      media.addEventListener('change', handleMedia);
    }
  }

  function init() {
    state.currentUserId = getUserId();
    updateUserBadge();
    restoreSidebarState();
    loadHistory();
    renderSidebarHistory();
    restoreSetup();
    applyUrlSetup();
    bindEvents();
    initQuestionBankModal();
    renderResumeButton();
    showView('setup');
    loadMaterialKnowledgePoints(true);

    if (window.PageShell && typeof window.PageShell.initGlobalSidebar === 'function') {
      window.PageShell.initGlobalSidebar();
    }

    if (window.UserContext && typeof window.UserContext.onChange === 'function') {
      window.UserContext.onChange(function () {
        const nextUserId = getUserId();
        if (state.currentUserId && nextUserId !== state.currentUserId) {
          stopTimer();
          state.practice = null;
          state.selectedKeys = [];
          showView('setup');
        }
        state.currentUserId = nextUserId;
        updateUserBadge();
        restoreSidebarState();
        loadHistory();
        renderSidebarHistory();
        renderResumeButton();
      });
    }

    window.addEventListener('storage', function (event) {
      if (event.key === getHistoryKey()) {
        loadHistory();
        renderSidebarHistory();
        renderResumeButton();
      }
    });

    window.addEventListener('beforeunload', function () {
      if (state.practice && state.practice.status === 'active') {
        state.practice.elapsedSeconds = getElapsedSeconds();
        state.practice.updatedAt = Date.now();
        saveHistory();
      }
    });

    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState === 'hidden' && state.practice && state.practice.status === 'active') {
        state.practice.elapsedSeconds = getElapsedSeconds();
        state.practice.updatedAt = Date.now();
        saveHistory();
      }
    });
  }

  document.addEventListener('DOMContentLoaded', init);
})();
