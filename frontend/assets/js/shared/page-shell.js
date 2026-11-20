(function () {
  const SIDEBAR_SPACE_SYNC_KEY = 'fangzhigong_space_sync';
  const SIDEBAR_SPACES_COLLAPSED_KEY = 'fangzhigong_sidebar_spaces_collapsed';
  const STREAK_WIDGET_REFRESH_MS = 60000;
  const STREAK_WIDGET_WEEK_GOAL = 2;

  const telemetrySessionState = {
    pageId: '',
    startedAt: 0,
    stayReported: false
  };

  let sidebarSpaceRequestToken = 0;
  let sidebarSpacesCollapsed = readSidebarSpacesCollapsed();
  let sidebarOpenSpaceMenuId = '';
  let sidebarSpacesCache = [];
  let streakWidgetRequestToken = 0;
  let streakWidgetRefreshTimer = 0;
  let streakWidgetSummary = null;

  function getCurrentPageId() {
    const path = String(window.location.pathname || '').replace(/\\/g, '/');
    const last = path.split('/').pop() || 'index.html';
    return String(last).replace(/\.html$/i, '').trim() || 'index';
  }

  function getTelemetryApiBase() {
    return window.ApiUtils && typeof window.ApiUtils.getApiBase === 'function'
      ? window.ApiUtils.getApiBase()
      : (window.location.origin || '');
  }

  function getTelemetryUserId() {
    return window.UserContext && typeof window.UserContext.getUserId === 'function'
      ? window.UserContext.getUserId()
      : 'default_user';
  }

  function safeJson(value) {
    try {
      return JSON.stringify(value);
    } catch (error) {
      return '{}';
    }
  }

  function esc(text) {
    return String(text || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function postLearningBehavior(payload, preferBeacon) {
    const apiBase = getTelemetryApiBase();
    if (!apiBase) return;

    const body = {
      user_id: getTelemetryUserId(),
      source: 'page_shell',
      ...payload
    };

    const url = `${apiBase}/api/behavior/track`;
    if (preferBeacon && navigator.sendBeacon) {
      try {
        const blob = new Blob([safeJson(body)], { type: 'application/json' });
        navigator.sendBeacon(url, blob);
        return;
      } catch (error) {
        // 回退到 fetch keepalive。
      }
    }

    if (typeof window.fetch !== 'function') return;
    window.fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: safeJson(body),
      keepalive: !!preferBeacon
    }).catch(function () {});
  }

  function normalizeTargetPage(target) {
    const text = String(target || '').trim();
    if (!text) return '';
    const clean = text.split('?')[0].split('#')[0];
    return clean.replace(/^.*\//, '').replace(/\.html$/i, '');
  }

  function isAuthenticatedUser() {
    return !!(
      window.UserContext &&
      typeof window.UserContext.isAuthenticated === 'function' &&
      window.UserContext.isAuthenticated()
    );
  }

  function getSidebarSpaceApi() {
    return window.SpaceCloudStore && typeof window.SpaceCloudStore.listSpaces === 'function'
      ? window.SpaceCloudStore
      : null;
  }

  function getSidebarSpaceBaseLink() {
    return document.querySelector('.global-sidebar a[data-side-link="spaces.html"]');
  }

  function ensureSidebarSpaceSlot() {
    const baseLink = getSidebarSpaceBaseLink();
    if (!baseLink) return null;

    let slot = document.getElementById('globalSidebarSpaces');
    if (!slot) {
      slot = document.createElement('div');
      slot.id = 'globalSidebarSpaces';
      slot.className = 'global-sidebar-spaces';
      baseLink.insertAdjacentElement('afterend', slot);
    }

    return slot;
  }

  function getCurrentSidebarSpaceId() {
    const params = new URLSearchParams(window.location.search || '');
    return String(params.get('space_id') || '').trim();
  }

  function getCachedSidebarSpace(spaceId) {
    const targetId = String(spaceId || '').trim();
    if (!targetId) return null;
    return sidebarSpacesCache.find(function (space) {
      return space && String(space.id || '').trim() === targetId;
    }) || null;
  }

  function buildSidebarSpaceHref(spaceId, options) {
    const opts = options && typeof options === 'object' ? options : {};
    const url = new URL('spaces.html', window.location.href);
    url.searchParams.delete('space_id');
    url.searchParams.delete('item_id');
    url.searchParams.delete('create_space');

    if (opts.createSpace) {
      url.searchParams.set('create_space', '1');
    } else if (spaceId) {
      url.searchParams.set('space_id', String(spaceId).trim());
    }

    return `${url.pathname}${url.search}`;
  }

  function getSidebarSpaceCount(space) {
    if (!space || typeof space !== 'object') return 0;
    const itemCount = Number(space.itemCount);
    if (Number.isFinite(itemCount) && itemCount >= 0) {
      return Math.round(itemCount);
    }
    return Array.isArray(space.items) ? space.items.length : 0;
  }

  function getSidebarSpaceIconMarkup() {
    return [
      '<span class="global-sidebar-space-icon" aria-hidden="true">',
      '<svg viewBox="0 0 24 24" fill="none">',
      '<path d="M12 3.5 19 7.75v8.5L12 20.5 5 16.25v-8.5L12 3.5Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"></path>',
      '<path d="M5 7.75 12 12l7-4.25M12 12v8.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"></path>',
      '</svg>',
      '</span>'
    ].join('');
  }

  function readSidebarSpacesCollapsed() {
    try {
      return window.localStorage.getItem(SIDEBAR_SPACES_COLLAPSED_KEY) === '1';
    } catch (error) {
      return false;
    }
  }

  function isSidebarSpacesRootActive() {
    return getCurrentPageId() === 'spaces' && !getCurrentSidebarSpaceId();
  }

  function buildSidebarSpacesShell(bodyHtml) {
    const collapsedClass = sidebarSpacesCollapsed ? ' is-collapsed' : '';
    const rootActiveClass = isSidebarSpacesRootActive() ? ' active' : '';
    const rootHref = buildSidebarSpaceHref('');
    return `
      <div class="global-sidebar-space-panel${collapsedClass}" data-sidebar-spaces-panel>
        <div class="global-sidebar-space-header">
          <a class="global-sidebar-space-root${rootActiveClass}" href="${esc(rootHref)}">
            <span class="global-sidebar-space-root-mark" aria-hidden="true"></span>
            <span class="global-sidebar-space-root-text">我的空间</span>
          </a>
          <button
            type="button"
            class="global-sidebar-space-toggle${collapsedClass}"
            data-sidebar-space-toggle
            aria-expanded="${sidebarSpacesCollapsed ? 'false' : 'true'}"
            aria-label="${sidebarSpacesCollapsed ? '展开我的空间' : '折叠我的空间'}"
          >
            <svg viewBox="0 0 12 12" fill="none" aria-hidden="true">
              <path d="M2 4.5 6 8l4-3.5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"></path>
            </svg>
          </button>
        </div>
        <div class="global-sidebar-space-body${collapsedClass}" data-sidebar-space-body${sidebarSpacesCollapsed ? ' hidden' : ''}>
          ${bodyHtml}
        </div>
      </div>
    `;
  }

  function syncSidebarSpacesCollapsedUi() {
    const slot = document.getElementById('globalSidebarSpaces');
    if (!slot) return;

    const panel = slot.querySelector('[data-sidebar-spaces-panel]');
    const body = slot.querySelector('[data-sidebar-space-body]');
    const toggle = slot.querySelector('[data-sidebar-space-toggle]');

    if (panel) {
      panel.classList.toggle('is-collapsed', sidebarSpacesCollapsed);
    }
    if (body) {
      body.hidden = sidebarSpacesCollapsed;
      body.classList.toggle('is-collapsed', sidebarSpacesCollapsed);
    }
    if (toggle) {
      toggle.classList.toggle('is-collapsed', sidebarSpacesCollapsed);
      toggle.setAttribute('aria-expanded', sidebarSpacesCollapsed ? 'false' : 'true');
      toggle.setAttribute('aria-label', sidebarSpacesCollapsed ? '展开我的空间' : '折叠我的空间');
    }
  }

  function setSidebarSpaceBaseLinkHidden(baseLink, shouldHide) {
    if (!baseLink) return;
    const hidden = !!shouldHide;
    baseLink.hidden = hidden;
    baseLink.classList.toggle('is-page-shell-hidden', hidden);
    if (hidden) {
      baseLink.setAttribute('aria-hidden', 'true');
      baseLink.setAttribute('tabindex', '-1');
      return;
    }
    baseLink.removeAttribute('aria-hidden');
    baseLink.removeAttribute('tabindex');
  }

  function setSidebarSpacesCollapsed(nextValue) {
    sidebarSpacesCollapsed = !!nextValue;
    try {
      if (sidebarSpacesCollapsed) {
        window.localStorage.setItem(SIDEBAR_SPACES_COLLAPSED_KEY, '1');
      } else {
        window.localStorage.removeItem(SIDEBAR_SPACES_COLLAPSED_KEY);
      }
    } catch (error) {
      // 忽略本地存储不可用的情况。
    }
    syncSidebarSpacesCollapsedUi();
  }

  function renderSidebarSpacesState(html, hideBaseLink) {
    const baseLink = getSidebarSpaceBaseLink();
    const slot = ensureSidebarSpaceSlot();
    if (!baseLink || !slot) return;

    setSidebarSpaceBaseLinkHidden(baseLink, hideBaseLink);

    if (!html) {
      sidebarSpacesCache = [];
      sidebarOpenSpaceMenuId = '';
      slot.hidden = true;
      slot.innerHTML = '';
      return;
    }

    slot.hidden = false;
    slot.innerHTML = buildSidebarSpacesShell(html);
    syncSidebarSpacesCollapsedUi();
  }

  function renderSidebarSpacesList(spaces) {
    const currentSpaceId = getCurrentSidebarSpaceId();
    const sortedSpaces = Array.isArray(spaces)
      ? spaces.slice().sort(function (left, right) {
          const leftTime = Number((left && (left.updatedAt || left.createdAt)) || 0);
          const rightTime = Number((right && (right.updatedAt || right.createdAt)) || 0);
          return rightTime - leftTime;
        })
      : [];
    sidebarSpacesCache = sortedSpaces.slice();
    if (!getCachedSidebarSpace(sidebarOpenSpaceMenuId)) {
      sidebarOpenSpaceMenuId = '';
    }

    const itemsHtml = sortedSpaces.length
      ? sortedSpaces.map(function (space) {
          const spaceId = String((space && space.id) || '').trim();
          const name = String((space && space.name) || '未命名空间').trim() || '未命名空间';
          const count = getSidebarSpaceCount(space);
          const activeClass = currentSpaceId && currentSpaceId === spaceId ? ' active' : '';
          const menuOpenClass = sidebarOpenSpaceMenuId === spaceId ? ' show' : '';
          return `
            <div class="global-sidebar-space-item-row">
              <a class="global-sidebar-space-item${activeClass}" href="${esc(buildSidebarSpaceHref(spaceId))}">
                <span class="global-sidebar-space-item-main">
                  ${getSidebarSpaceIconMarkup()}
                  <span class="global-sidebar-space-item-text">${esc(name)}</span>
                </span>
              </a>
              <div class="global-sidebar-space-item-side">
                <span class="global-sidebar-space-item-count">(${count})</span>
                <div class="global-sidebar-space-menu-wrap">
                  <button
                    type="button"
                    class="global-sidebar-space-menu-btn"
                    data-sidebar-space-menu-toggle="${esc(spaceId)}"
                    aria-label="空间操作：${esc(name)}"
                    aria-haspopup="menu"
                    aria-expanded="${sidebarOpenSpaceMenuId === spaceId ? 'true' : 'false'}"
                  >
                    <svg viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                      <circle cx="10" cy="4" r="1.6"></circle>
                      <circle cx="10" cy="10" r="1.6"></circle>
                      <circle cx="10" cy="16" r="1.6"></circle>
                    </svg>
                  </button>
                  <div class="global-sidebar-space-menu${menuOpenClass}" data-sidebar-space-menu="${esc(spaceId)}" role="menu">
                    <button type="button" class="global-sidebar-space-menu-item" data-sidebar-space-action="rename" data-sidebar-space-id="${esc(spaceId)}">编辑</button>
                    <button type="button" class="global-sidebar-space-menu-item danger" data-sidebar-space-action="delete" data-sidebar-space-id="${esc(spaceId)}">删除</button>
                  </div>
                </div>
              </div>
            </div>
          `;
        }).join('')
      : '<div class="global-sidebar-space-empty">还没有空间，点击“新空间”开始整理资料。</div>';

    renderSidebarSpacesState(`
      <a class="global-sidebar-space-create" href="${esc(buildSidebarSpaceHref('', { createSpace: true }))}">
        <span class="global-sidebar-space-create-plus" aria-hidden="true">+</span>
        <span>新空间</span>
      </a>
      <div class="global-sidebar-space-items">${itemsHtml}</div>
    `, true);
  }

  async function renameSidebarSpace(spaceId) {
    const api = getSidebarSpaceApi();
    const space = getCachedSidebarSpace(spaceId);
    if (!space || !api || typeof api.updateSpace !== 'function') return;

    const currentName = String(space.name || '新空间').trim() || '新空间';
    const nextName = window.prompt('请输入新的空间名称：', currentName);
    if (nextName === null) return;

    const normalizedName = String(nextName || '').trim() || currentName;
    sidebarOpenSpaceMenuId = '';
    renderSidebarSpacesList(sidebarSpacesCache);
    if (normalizedName === currentName) return;

    try {
      await api.updateSpace(getTelemetryUserId(), space.id, { name: normalizedName });
      await refreshSidebarSpaces();
    } catch (error) {
      window.alert(api.withSuggestion
        ? api.withSuggestion('空间重命名失败', error, '请稍后重试')
        : '空间重命名失败，请稍后重试');
      await refreshSidebarSpaces();
    }
  }

  async function deleteSidebarSpace(spaceId) {
    const api = getSidebarSpaceApi();
    const space = getCachedSidebarSpace(spaceId);
    if (!space || !api || typeof api.deleteSpace !== 'function') return;

    const confirmed = window.confirm(`确认删除空间「${space.name || '新空间'}」吗？删除后其中的云端内容也会一起移除。`);
    if (!confirmed) return;

    sidebarOpenSpaceMenuId = '';
    renderSidebarSpacesList(sidebarSpacesCache);

    try {
      await api.deleteSpace(getTelemetryUserId(), space.id);
      if (getCurrentPageId() === 'spaces' && getCurrentSidebarSpaceId() === space.id) {
        window.location.href = buildSidebarSpaceHref('');
        return;
      }
      await refreshSidebarSpaces();
    } catch (error) {
      window.alert(api.withSuggestion
        ? api.withSuggestion('删除空间失败', error, '请稍后重试')
        : '删除空间失败，请稍后重试');
      await refreshSidebarSpaces();
    }
  }

  async function refreshSidebarSpaces() {
    const baseLink = getSidebarSpaceBaseLink();
    if (!baseLink) return;

    const api = getSidebarSpaceApi();
    if (!isAuthenticatedUser() || !api) {
      sidebarSpacesCache = [];
      sidebarOpenSpaceMenuId = '';
      renderSidebarSpacesState('', false);
      return;
    }

    sidebarOpenSpaceMenuId = '';
    renderSidebarSpacesState(
      '<div class="global-sidebar-space-loading">正在加载空间...</div>',
      true
    );

    const requestToken = ++sidebarSpaceRequestToken;

    try {
      const data = await api.listSpaces(getTelemetryUserId());
      if (requestToken !== sidebarSpaceRequestToken) return;
      renderSidebarSpacesList(Array.isArray(data && data.spaces) ? data.spaces : []);
    } catch (error) {
      if (requestToken !== sidebarSpaceRequestToken) return;
      renderSidebarSpacesState(`
        <a class="global-sidebar-space-create" href="${esc(buildSidebarSpaceHref('', { createSpace: true }))}">
          <span class="global-sidebar-space-create-plus" aria-hidden="true">+</span>
          <span>新空间</span>
        </a>
        <div class="global-sidebar-space-empty">空间加载失败，请稍后刷新重试。</div>
      `, true);
    }
  }

  function bindSidebarSpaceEvents() {
    if (document.body.dataset.pageShellSidebarSpacesBound) return;

    if (window.UserContext && typeof window.UserContext.onAuthChange === 'function') {
      window.UserContext.onAuthChange(function () {
        refreshSidebarSpaces();
      });
    }

    document.addEventListener('click', function (event) {
      const clickTarget = event.target && typeof event.target.closest === 'function'
        ? event.target
        : null;
      const toggle = clickTarget ? clickTarget.closest('[data-sidebar-space-toggle]') : null;
      if (!toggle) return;
      event.preventDefault();
      setSidebarSpacesCollapsed(!sidebarSpacesCollapsed);
    });

    document.addEventListener('click', function (event) {
      const clickTarget = event.target && typeof event.target.closest === 'function'
        ? event.target
        : null;
      if (!clickTarget) return;

      const menuToggle = clickTarget.closest('[data-sidebar-space-menu-toggle]');
      if (menuToggle) {
        event.preventDefault();
        event.stopPropagation();
        const spaceId = String(menuToggle.getAttribute('data-sidebar-space-menu-toggle') || '').trim();
        sidebarOpenSpaceMenuId = sidebarOpenSpaceMenuId === spaceId ? '' : spaceId;
        renderSidebarSpacesList(sidebarSpacesCache);
        return;
      }

      const actionBtn = clickTarget.closest('[data-sidebar-space-action]');
      if (actionBtn) {
        event.preventDefault();
        event.stopPropagation();
        const action = String(actionBtn.getAttribute('data-sidebar-space-action') || '').trim();
        const spaceId = String(actionBtn.getAttribute('data-sidebar-space-id') || '').trim();
        if (!spaceId) return;
        if (action === 'rename') {
          renameSidebarSpace(spaceId);
          return;
        }
        if (action === 'delete') {
          deleteSidebarSpace(spaceId);
          return;
        }
      }

      if (sidebarOpenSpaceMenuId && !clickTarget.closest('[data-sidebar-space-menu], [data-sidebar-space-menu-toggle]')) {
        sidebarOpenSpaceMenuId = '';
        renderSidebarSpacesList(sidebarSpacesCache);
      }
    });

    window.addEventListener('spaces:changed', function (event) {
      const detail = event && event.detail && typeof event.detail === 'object'
        ? event.detail
        : {};
      const changedUserId = String(detail.userId || '').trim();
      if (changedUserId && changedUserId !== getTelemetryUserId()) return;
      if (detail.action === 'delete_space' && getCurrentPageId() === 'spaces' && getCurrentSidebarSpaceId() === String(detail.spaceId || '').trim()) {
        window.location.href = buildSidebarSpaceHref('');
        return;
      }
      refreshSidebarSpaces();
    });

    window.addEventListener('storage', function (event) {
      if (event.key === SIDEBAR_SPACES_COLLAPSED_KEY) {
        sidebarSpacesCollapsed = event.newValue === '1';
        syncSidebarSpacesCollapsedUi();
        return;
      }
      if (event.key !== SIDEBAR_SPACE_SYNC_KEY) return;
      refreshSidebarSpaces();
    });

    document.body.dataset.pageShellSidebarSpacesBound = '1';
  }

  function initLearningTelemetry() {
    if (window.__fangzhigongLearningTelemetryInitialized) return;
    window.__fangzhigongLearningTelemetryInitialized = true;

    const pageId = getCurrentPageId();
    const startedAt = Date.now();
    let stayReported = false;
    telemetrySessionState.pageId = pageId;
    telemetrySessionState.startedAt = startedAt;
    telemetrySessionState.stayReported = false;

    postLearningBehavior({
      behavior_type: 'page_view',
      page: pageId,
      title: document.title || pageId,
      label: 'page_view',
      meta: {
        referrer: document.referrer || ''
      }
    }, false);

    function flushPageStay(reason) {
      if (stayReported) return;
      stayReported = true;
      telemetrySessionState.stayReported = true;
      const durationSeconds = Math.max(0, (Date.now() - startedAt) / 1000);
      postLearningBehavior({
        behavior_type: 'page_stay',
        page: pageId,
        title: document.title || pageId,
        label: String(reason || 'pagehide'),
        duration_seconds: Number(durationSeconds.toFixed(3)),
        meta: {
          referrer: document.referrer || ''
        }
      }, true);
    }

    window.addEventListener('pagehide', function () {
      flushPageStay('pagehide');
    });

    document.addEventListener('click', function (event) {
      const target = event.target && typeof event.target.closest === 'function'
        ? event.target.closest('[data-side-link], [data-track-action], a.back-link, .global-sidebar-space-root, .global-sidebar-space-create, .global-sidebar-space-item')
        : null;
      if (!target) return;

      const sideLink = target.getAttribute('data-side-link') || '';
      const href = target.getAttribute('href') || '';
      const action = target.getAttribute('data-track-action') || '';
      const label = (target.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 40);

      postLearningBehavior({
        behavior_type: 'navigation_click',
        page: pageId,
        target: normalizeTargetPage(sideLink || href || action),
        label: label || action || sideLink || href || 'navigation_click',
        title: document.title || pageId
      }, false);
    });
  }

  function markActiveSidebarLink() {
    const path = String(window.location.pathname || '').replace(/\\/g, '/');
    document.querySelectorAll('[data-side-link]').forEach(function (link) {
      const target = String(link.getAttribute('data-side-link') || '');
      if (target && (path.endsWith('/' + target) || path.endsWith(target))) {
        link.classList.add('active');
      }
    });
  }

  function formatLocalDate(date) {
    if (!(date instanceof Date) || Number.isNaN(date.getTime())) return '';
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  }

  function buildDefaultStreakWeekDays() {
    const labels = ['一', '二', '三', '四', '五', '六', '日'];
    const now = new Date();
    if (Number.isNaN(now.getTime())) {
      return labels.map(function (label) {
        return { label: label, active: false, today: false, date: '' };
      });
    }

    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const weekdayIndex = (today.getDay() + 6) % 7;
    const weekStart = new Date(today);
    weekStart.setDate(today.getDate() - weekdayIndex);

    return labels.map(function (label, offset) {
      const nextDay = new Date(weekStart);
      nextDay.setDate(weekStart.getDate() + offset);
      return {
        label: label,
        active: false,
        today: offset === weekdayIndex,
        date: formatLocalDate(nextDay)
      };
    });
  }

  function normalizeStreakSummary(raw) {
    const base = raw && typeof raw === 'object' ? raw : {};
    const goal = Math.max(1, Number(base.week_goal_days) || STREAK_WIDGET_WEEK_GOAL);
    const weekActiveDays = Math.max(0, Number(base.week_active_days) || 0);
    const currentStreak = Math.max(0, Number(base.current_streak) || 0);
    const progressCurrentRaw = Number(base.progress_current);
    const progressCurrent = Number.isFinite(progressCurrentRaw)
      ? Math.max(0, Math.min(goal, Math.round(progressCurrentRaw)))
      : Math.min(goal, weekActiveDays);
    const fallbackWeekDays = buildDefaultStreakWeekDays();

    const weekDays = Array.isArray(base.week_days) && base.week_days.length === 7
      ? base.week_days.map(function (item, index) {
          const fallback = fallbackWeekDays[index] || {};
          return {
            label: String((item && item.label) || fallback.label || '').trim() || fallback.label || '',
            active: !!(item && item.active),
            today: !!(item && item.today),
            date: String((item && item.date) || fallback.date || '').trim()
          };
        })
      : fallbackWeekDays;

    const progressLabel = String(base.progress_label || `${progressCurrent}/${goal}`).trim() || `${progressCurrent}/${goal}`;
    const status = String(base.status || (progressCurrent >= goal ? 'started' : 'warming')).trim() || 'warming';
    const message = String(base.message || (progressCurrent >= goal
      ? '连续登录已开始，继续保持这个节奏。'
      : `本周登录 ${goal} 天以开始你的连续登录。`)).trim();
    const helper = String(base.helper || (progressCurrent >= goal
      ? (currentStreak > 0 ? `已连续登录 ${currentStreak} 天` : `本周已登录 ${weekActiveDays} 天`)
      : `还差 ${Math.max(0, goal - weekActiveDays)} 天即可点亮连续登录`)).trim();

    return {
      weekLabel: String(base.week_label || '本周').trim() || '本周',
      weekGoalDays: goal,
      weekActiveDays: weekActiveDays,
      progressCurrent: progressCurrent,
      progressLabel: progressLabel,
      currentStreak: currentStreak,
      status: status,
      message: message,
      helper: helper,
      weekDays: weekDays
    };
  }

  function getStreakIconMarkup(extraClassName) {
    const extra = String(extraClassName || '').trim();
    const classAttr = extra ? `global-streak-icon ${extra}` : 'global-streak-icon';
    return `
      <svg class="${classAttr}" viewBox="0 0 20 20" fill="none" aria-hidden="true">
        <path d="M10.2 1.7c.4 1.5.1 2.8-.8 3.9-.8 1-1.1 1.9-.9 2.8 2.1-.4 3.6-1.9 4.5-4.4 1.8 2 2.6 4 2.6 5.9 0 3.9-2.9 6.8-6.8 6.8S1.9 13.9 1.9 10.3c0-2.1 1-4.2 2.9-6.3.1 2 .8 3.5 2.1 4.5 0-1 .4-2 1.2-3 .9-1.2 1.6-2.5 2.1-3.8Z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"></path>
        <path d="M10 9.2c1.7 1 2.6 2.1 2.6 3.3 0 1.5-1.2 2.7-2.7 2.7S7.2 14 7.2 12.5c0-.9.5-1.8 1.6-2.8.1.8.5 1.4 1.2 1.8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"></path>
      </svg>
    `;
  }

  function ensureStreakWidget() {
    let root = document.getElementById('globalStreakWidget');
    const dock = document.getElementById('globalStreakDock');
    const host = dock || document.body;

    if (root) {
      if (root.parentNode !== host) {
        host.appendChild(root);
      }
      root.classList.toggle('is-inline-anchor', !!dock);
      return root;
    }

    root = document.createElement('div');
    root.id = 'globalStreakWidget';
    root.className = 'global-streak-widget';
    root.innerHTML = `
      <button
        type="button"
        class="global-streak-trigger"
        id="globalStreakTrigger"
        aria-expanded="false"
        aria-controls="globalStreakPopover"
        aria-label="查看连续登录进度"
      >
        ${getStreakIconMarkup()}
        <span class="global-streak-trigger-text">0/2</span>
      </button>
      <div class="global-streak-popover" id="globalStreakPopover" hidden></div>
    `;
    root.classList.toggle('is-inline-anchor', !!dock);
    host.appendChild(root);

    const trigger = document.getElementById('globalStreakTrigger');
    if (trigger && !trigger.dataset.pageShellBound) {
      trigger.addEventListener('click', function (event) {
        event.preventDefault();
        event.stopPropagation();
        setStreakWidgetOpen(trigger.getAttribute('aria-expanded') !== 'true');
      });
      trigger.dataset.pageShellBound = '1';
    }

    return root;
  }

  function syncStreakWidgetOffset() {
    // 徽章固定在各页面头部左上角的 #globalStreakDock 中，不再按页面冲突元素下移。
    const root = document.getElementById('globalStreakWidget');
    if (!root) return;
    root.style.top = '';
    root.style.right = '';
    root.style.left = '';
  }

  function setStreakWidgetOpen(nextOpen) {
    const trigger = document.getElementById('globalStreakTrigger');
    const popover = document.getElementById('globalStreakPopover');
    if (!trigger || !popover) return;

    const isOpen = !!nextOpen;
    trigger.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    popover.hidden = !isOpen;
    syncStreakWidgetOffset();
  }

  function renderStreakWidget(summary) {
    const root = ensureStreakWidget();
    if (!root) return;

    const trigger = document.getElementById('globalStreakTrigger');
    const label = root.querySelector('.global-streak-trigger-text');
    const popover = document.getElementById('globalStreakPopover');
    const normalized = normalizeStreakSummary(summary);
    streakWidgetSummary = normalized;

    if (label) {
      label.textContent = normalized.progressLabel;
    }
    if (trigger) {
      trigger.setAttribute('aria-label', `${normalized.weekLabel}连续登录进度 ${normalized.progressLabel}`);
    }
    if (popover) {
      popover.innerHTML = `
        <div class="global-streak-card-value">
          ${getStreakIconMarkup()}
          <span>${esc(normalized.progressLabel)}</span>
        </div>
        <div class="global-streak-card-title">${esc(normalized.weekLabel)}</div>
        <div class="global-streak-card-copy">
          <div class="global-streak-card-copy-text">${esc(normalized.message)}</div>
          <span class="global-streak-card-badge">${esc(normalized.progressLabel)}</span>
        </div>
        <div class="global-streak-helper">${esc(normalized.helper)}</div>
        <div class="global-streak-week">
          ${normalized.weekDays.map(function (item) {
            const classNames = ['global-streak-day'];
            if (item.active) classNames.push('active');
            if (item.today) classNames.push('today');
            return `
              <div class="${classNames.join(' ')}" title="${esc(item.date)}">
                <span class="global-streak-day-dot" aria-hidden="true"></span>
                <span class="global-streak-day-label">${esc(item.label)}</span>
              </div>
            `;
          }).join('')}
        </div>
      `;
    }

    syncStreakWidgetOffset();
  }

  async function refreshGlobalStreakWidget() {
    ensureStreakWidget();
    if (!streakWidgetSummary) {
      renderStreakWidget(null);
    }

    const apiBase = getTelemetryApiBase();
    if (!apiBase || typeof window.fetch !== 'function') return;

    const requestToken = ++streakWidgetRequestToken;
    const userId = getTelemetryUserId();
    const url = `${apiBase}/api/dashboard/streak?user_id=${encodeURIComponent(userId)}&_t=${Date.now()}`;

    try {
      const response = await window.fetch(url, { method: 'GET' });
      const payload = window.ApiUtils && typeof window.ApiUtils.parseApiResponse === 'function'
        ? await window.ApiUtils.parseApiResponse(response)
        : await response.json();
      if (requestToken !== streakWidgetRequestToken) return;
      renderStreakWidget(payload && payload.streak ? payload.streak : null);
    } catch (error) {
      if (requestToken !== streakWidgetRequestToken) return;
      renderStreakWidget(streakWidgetSummary);
    }
  }

  function initGlobalStreakWidget() {
    ensureStreakWidget();
    syncStreakWidgetOffset();

    if (window.__fangzhigongGlobalStreakWidgetInitialized) {
      return;
    }
    window.__fangzhigongGlobalStreakWidgetInitialized = true;

    document.addEventListener('click', function (event) {
      const root = document.getElementById('globalStreakWidget');
      if (!root) return;
      if (event.target && root.contains(event.target)) return;
      setStreakWidgetOpen(false);
    });

    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') {
        setStreakWidgetOpen(false);
      }
    });

    window.addEventListener('resize', syncStreakWidgetOffset);
    window.addEventListener('scroll', syncStreakWidgetOffset, { passive: true });
    window.addEventListener('pageshow', function () {
      syncStreakWidgetOffset();
      refreshGlobalStreakWidget();
    });
    window.addEventListener('focus', refreshGlobalStreakWidget);
    document.addEventListener('visibilitychange', function () {
      if (!document.hidden) {
        syncStreakWidgetOffset();
        refreshGlobalStreakWidget();
      }
    });

    if (window.UserContext && typeof window.UserContext.onChange === 'function') {
      window.UserContext.onChange(function () {
        setStreakWidgetOpen(false);
        refreshGlobalStreakWidget();
      });
    }

    if (!streakWidgetRefreshTimer) {
      streakWidgetRefreshTimer = window.setInterval(refreshGlobalStreakWidget, STREAK_WIDGET_REFRESH_MS);
    }

    refreshGlobalStreakWidget();
  }

  function initGlobalSidebar() {
    initGlobalStreakWidget();

    const toggle = document.getElementById('globalSidebarToggle');
    const drawer = document.getElementById('globalSidebar');
    const backdrop = document.getElementById('globalSidebarBackdrop');
    const guestClose = document.getElementById('guestSidebarClose');
    if (!toggle || !drawer || !backdrop) return;

    const syncToggleState = function (isOpen) {
      toggle.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
      toggle.setAttribute('aria-label', isOpen ? '收起侧栏' : '打开侧栏');
    };

    const openDrawer = function () {
      drawer.classList.add('open');
      backdrop.classList.add('show');
      document.body.classList.add('sidebar-open');
      syncToggleState(true);
    };

    const closeDrawer = function () {
      drawer.classList.remove('open');
      backdrop.classList.remove('show');
      document.body.classList.remove('sidebar-open');
      syncToggleState(false);
    };

    if (!toggle.dataset.pageShellBound) {
      toggle.addEventListener('click', function () {
        if (document.body.classList.contains('sidebar-collapsed')
          && window.matchMedia('(min-width: 1280px)').matches) {
          setSidebarDesktopCollapsed(false, true);
          return;
        }
        if (drawer.classList.contains('open')) {
          closeDrawer();
          return;
        }
        openDrawer();
      });
      toggle.dataset.pageShellBound = '1';
    }

    if (!backdrop.dataset.pageShellBound) {
      backdrop.addEventListener('click', closeDrawer);
      backdrop.dataset.pageShellBound = '1';
    }

    if (guestClose && !guestClose.dataset.pageShellBound) {
      guestClose.addEventListener('click', closeDrawer);
      guestClose.dataset.pageShellBound = '1';
    }

    if (!document.body.dataset.pageShellEscBound) {
      document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape') {
          closeDrawer();
        }
      });
      document.body.dataset.pageShellEscBound = '1';
    }

    markActiveSidebarLink();
    bindSidebarSpaceEvents();
    refreshSidebarSpaces();
    syncToggleState(drawer.classList.contains('open'));
  }

  /* ==========================================================
     全局搜索 / 最近使用 / 我的图书馆 / 历史
     ========================================================== */

  const SHELL_RECENT_KEY = 'fangzhigong_shell_recent_v1';
  const SHELL_RECENT_LIMIT = 10;
  const SHELL_RECENT_SIDEBAR_LIMIT = 4;
  const SHELL_PAGES = [
    { id: 'index', label: '添加内容', href: 'index.html', desc: '上传资料、粘贴文本、添加学习链接', icon: 'page' },
    { id: 'chat', label: '智能问答', href: 'chat.html', desc: '与学习助手对话、检索知识库', icon: 'chat' },
    { id: 'question-bank', label: '题库练习', href: 'question-bank.html', desc: '抽题、作答与错题重练', icon: 'chat' },
    { id: 'dashboard', label: '学习仪表盘', href: 'dashboard.html', desc: '掌握度、图谱与认知诊断数据', icon: 'page' },
    { id: 'spaces', label: '我的空间', href: 'spaces.html', desc: '空间与资料管理', icon: 'space' }
  ];
  const SHELL_ICON_PATHS = {
    search: '<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/>',
    library: '<path d="M4 5.5A1.5 1.5 0 0 1 5.5 4H9v16H5.5A1.5 1.5 0 0 1 4 18.5Z"/><path d="M9 4h5.5A1.5 1.5 0 0 1 16 5.5V20H9"/><path d="M16 8l3.2-.8a1.5 1.5 0 0 1 1.8 1.1l2 8.2"/>',
    history: '<path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1"/><path d="M3.5 4.5V9H8"/><path d="M12 8v4.5l3 1.8"/>',
    clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3.2 1.9"/>',
    page: '<path d="M6 3.5h8l4 4V20a1.5 1.5 0 0 1-1.5 1.5h-10A1.5 1.5 0 0 1 5 20V5A1.5 1.5 0 0 1 6.5 3.5Z"/><path d="M14 3.5V8h4"/>',
    space: '<path d="M12 3.5 19 7.75v8.5L12 20.5 5 16.25v-8.5L12 3.5Z"/><path d="M5 7.75 12 12l7-4.25M12 12v8.5"/>',
    chat: '<path d="M21 11.5a8.5 8.5 0 0 1-8.5 8.5H8l-5 3 1.2-5.1A8.5 8.5 0 0 1 12.5 3 8.5 8.5 0 0 1 21 11.5Z"/>'
  };

  const SIDEBAR_DESKTOP_COLLAPSED_KEY = 'fangzhigong_sidebar_collapsed_desktop_v1';
  let sidebarDesktopCollapsed = false;
  let shellSpacesCache = null;
  let shellSpacesPromise = null;
  let shellSpacesLoading = false;

  function readSidebarDesktopCollapsed() {
    try {
      return window.localStorage.getItem(SIDEBAR_DESKTOP_COLLAPSED_KEY) === '1';
    } catch (error) {
      return false;
    }
  }

  function writeSidebarDesktopCollapsed(collapsed) {
    try {
      if (collapsed) {
        window.localStorage.setItem(SIDEBAR_DESKTOP_COLLAPSED_KEY, '1');
      } else {
        window.localStorage.removeItem(SIDEBAR_DESKTOP_COLLAPSED_KEY);
      }
    } catch (error) {
      // 忽略本地存储不可用的情况。
    }
  }

  function syncSidebarCollapseUi() {
    document.body.classList.toggle('sidebar-collapsed', sidebarDesktopCollapsed);

    const collapseButton = document.getElementById('globalSidebarCollapse');
    if (collapseButton) {
      collapseButton.setAttribute('aria-expanded', sidebarDesktopCollapsed ? 'false' : 'true');
      collapseButton.setAttribute('aria-label', sidebarDesktopCollapsed ? '展开侧栏' : '收起侧栏');
      collapseButton.setAttribute('title', sidebarDesktopCollapsed ? '展开侧栏' : '收起侧栏');
    }

    const toggle = document.getElementById('globalSidebarToggle');
    if (toggle) {
      toggle.setAttribute('aria-expanded', 'false');
      toggle.setAttribute('aria-label', '展开侧栏');
    }
  }

  function setSidebarDesktopCollapsed(collapsed, persist) {
    sidebarDesktopCollapsed = !!collapsed;

    if (sidebarDesktopCollapsed) {
      const drawer = document.getElementById('globalSidebar');
      const backdrop = document.getElementById('globalSidebarBackdrop');
      if (drawer) drawer.classList.remove('open');
      if (backdrop) backdrop.classList.remove('show');
      document.body.classList.remove('sidebar-open');
    }

    syncSidebarCollapseUi();

    if (persist !== false) {
      writeSidebarDesktopCollapsed(sidebarDesktopCollapsed);
    }
  }

  function ensureSidebarCollapseButton() {
    const sidebar = document.getElementById('globalSidebar');
    if (!sidebar || document.getElementById('globalSidebarCollapse')) return;

    const button = document.createElement('button');
    button.id = 'globalSidebarCollapse';
    button.type = 'button';
    button.className = 'global-sidebar-collapse';
    button.setAttribute('aria-label', '收起侧栏');
    button.setAttribute('title', '收起侧栏');
    button.setAttribute('aria-expanded', 'true');
    button.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14.5 6.5 9 12l5.5 5.5"/><path d="M19 5v14"/></svg>';
    button.addEventListener('click', function () {
      setSidebarDesktopCollapsed(true, true);
    });
    sidebar.appendChild(button);
  }
  let shellModalMode = 'search';
  let shellModalResults = [];
  let shellModalActiveIndex = 0;
  let shellModalOpen = false;
  let shellRecentCache = null;

  function shellIcon(name) {
    const path = SHELL_ICON_PATHS[name] || SHELL_ICON_PATHS.page;
    return `<svg viewBox="0 0 24 24" aria-hidden="true">${path}</svg>`;
  }

  function readShellJson(key) {
    try {
      const raw = window.localStorage.getItem(key);
      return raw ? JSON.parse(raw) : null;
    } catch (error) {
      return null;
    }
  }

  function writeShellJson(key, value) {
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
      return true;
    } catch (error) {
      return false;
    }
  }

  function getShellPageMeta(pageId) {
    const target = String(pageId || '').trim();
    return SHELL_PAGES.find(function (page) { return page.id === target; }) || null;
  }

  function getShellRecent() {
    if (shellRecentCache) return shellRecentCache.slice();
    const stored = readShellJson(SHELL_RECENT_KEY);
    shellRecentCache = Array.isArray(stored) ? stored.filter(function (item) {
      return item && item.href && item.title;
    }).slice(0, SHELL_RECENT_LIMIT) : [];
    return shellRecentCache.slice();
  }

  function pushShellRecent(entry) {
    if (!entry || !entry.href || !entry.title) return;
    const next = getShellRecent().filter(function (item) {
      return item.id !== entry.id;
    });
    next.unshift({
      id: entry.id || `item:${entry.href}`,
      title: String(entry.title).trim().slice(0, 60),
      href: entry.href,
      tag: entry.tag || '最近',
      at: entry.at || Date.now()
    });
    shellRecentCache = next.slice(0, SHELL_RECENT_LIMIT);
    writeShellJson(SHELL_RECENT_KEY, shellRecentCache);
    renderSidebarRecent();
  }

  function recordShellPageVisit() {
    const pageId = getCurrentPageId();
    const meta = getShellPageMeta(pageId);
    if (!meta) return;

    const params = new URLSearchParams(window.location.search || '');
    const spaceId = String(params.get('space_id') || '').trim();

    if (pageId === 'spaces') {
      const nameNode = document.getElementById('topSpaceName');
      const spaceTitle = String(nameNode ? nameNode.textContent : '').trim() || meta.label;
      pushShellRecent({
        id: spaceId ? `space:${spaceId}` : 'page:spaces',
        title: spaceId ? spaceTitle : meta.label,
        href: `${window.location.pathname}${window.location.search}`,
        tag: spaceId ? '空间' : '页面',
        at: Date.now()
      });
      return;
    }

    pushShellRecent({
      id: `page:${pageId}`,
      title: meta.label,
      href: meta.href,
      tag: '页面',
      at: Date.now()
    });
  }

  function renderHomeRecent() {
    const section = document.getElementById('entryRecentSection');
    const list = document.getElementById('entryRecentList');
    if (!section || !list) return;

    const items = getShellRecent().slice(0, 6);
    if (!items.length) {
      section.hidden = true;
      list.innerHTML = '';
      return;
    }

    section.hidden = false;
    list.innerHTML = items.map(function (item) {
      const tag = String(item.tag || '最近');
      return `
        <a class="entry-recent-item" href="${esc(item.href)}">
          <span class="entry-recent-icon" aria-hidden="true">${shellIcon(tag === '空间' ? 'space' : 'clock')}</span>
          <span class="entry-recent-text">${esc(item.title)}</span>
          <span class="entry-recent-meta">${esc(tag)}</span>
        </a>
      `;
    }).join('');
  }

  function renderSidebarRecent() {
    renderHomeRecent();

    const list = document.getElementById('globalSidebarRecentList');
    if (!list) return;

    const items = getShellRecent().slice(0, SHELL_RECENT_SIDEBAR_LIMIT);
    if (!items.length) {
      list.innerHTML = '<div class="global-sidebar-recent-empty">还没有最近记录</div>';
      return;
    }

    list.innerHTML = items.map(function (item) {
      return `
        <a class="global-sidebar-recent-item" href="${esc(item.href)}">
          <span class="global-sidebar-recent-icon" aria-hidden="true">${shellIcon(item.tag === '空间' ? 'space' : 'clock')}</span>
          <span class="global-sidebar-recent-text">${esc(item.title)}</span>
        </a>
      `;
    }).join('');
  }

  function ensureSidebarTools() {
    if (document.getElementById('globalSidebarTools')) {
      renderSidebarRecent();
      return;
    }

    const baseLink = document.querySelector('.global-sidebar a[data-side-link="index.html"]');
    const logo = document.querySelector('.global-sidebar .global-sidebar-logo');
    const anchor = baseLink || logo;
    if (!anchor) return;

    const tools = document.createElement('div');
    tools.id = 'globalSidebarTools';
    tools.className = 'global-sidebar-tools';
    tools.innerHTML = `
      <button type="button" class="global-sidebar-tool" data-shell-open="search">
        <span class="st-nav-icon" aria-hidden="true">${shellIcon('search')}</span>
        <span class="st-nav-label">搜索</span>
        <span class="global-sidebar-tool-key">Ctrl K</span>
      </button>
      <button type="button" class="global-sidebar-tool" data-shell-open="library">
        <span class="st-nav-icon" aria-hidden="true">${shellIcon('library')}</span>
        <span class="st-nav-label">我的图书馆</span>
      </button>
      <button type="button" class="global-sidebar-tool" data-shell-open="history">
        <span class="st-nav-icon" aria-hidden="true">${shellIcon('history')}</span>
        <span class="st-nav-label">历史</span>
      </button>
      <div class="global-sidebar-recent">
        <div class="global-sidebar-recent-head">
          <span>最近使用</span>
          <button type="button" class="global-sidebar-recent-all" data-shell-open="history">全部</button>
        </div>
        <div class="global-sidebar-recent-list" id="globalSidebarRecentList"></div>
      </div>
    `;
    anchor.insertAdjacentElement('afterend', tools);
    renderSidebarRecent();
  }

  function getShellSpaces(force) {
    if (!isAuthenticatedUser()) return Promise.resolve([]);
    if (shellSpacesCache && !force) return Promise.resolve(shellSpacesCache.slice());
    if (shellSpacesPromise && !force) return shellSpacesPromise;

    const api = getSidebarSpaceApi();
    if (!api || typeof api.listSpaces !== 'function') return Promise.resolve([]);

    shellSpacesLoading = true;

    try {
      shellSpacesPromise = api.listSpaces(getTelemetryUserId()).then(function (data) {
        shellSpacesCache = Array.isArray(data && data.spaces) ? data.spaces : [];
        return shellSpacesCache.slice();
      }).catch(function () {
        shellSpacesCache = [];
        return [];
      }).then(function (spaces) {
        shellSpacesPromise = null;
        shellSpacesLoading = false;
        return spaces;
      });
    } catch (error) {
      shellSpacesPromise = null;
      shellSpacesLoading = false;
      return Promise.resolve([]);
    }

    return shellSpacesPromise;
  }

  function buildSpaceHref(spaceId) {
    const url = new URL('spaces.html', window.location.href);
    url.searchParams.set('space_id', String(spaceId || '').trim());
    return `${url.pathname}${url.search}`;
  }

  function getShellSpacesQuick() {
    return Array.isArray(shellSpacesCache) ? shellSpacesCache : [];
  }

  function readChatHistoryForShell() {
    if (!window.ProjectLocalData || typeof window.ProjectLocalData.getChatStoreKey !== 'function') {
      return [];
    }
    const payload = readShellJson(window.ProjectLocalData.getChatStoreKey(getTelemetryUserId()));
    const sessions = payload && Array.isArray(payload.sessions) ? payload.sessions : [];
    return sessions.filter(function (session) {
      return session && session.id;
    }).sort(function (left, right) {
      return Number(right.updatedAt || 0) - Number(left.updatedAt || 0);
    }).slice(0, 12);
  }

  function formatShellTime(timestamp) {
    const value = Number(timestamp || 0);
    if (!value) return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    const now = new Date();
    const sameDay = date.getFullYear() === now.getFullYear()
      && date.getMonth() === now.getMonth()
      && date.getDate() === now.getDate();
    const hh = String(date.getHours()).padStart(2, '0');
    const mm = String(date.getMinutes()).padStart(2, '0');
    if (sameDay) return `今天 ${hh}:${mm}`;
    return `${date.getMonth() + 1}月${date.getDate()}日 ${hh}:${mm}`;
  }

  function formatShellItemMeta(item) {
    const kindMap = {
      document: '文档',
      pdf: 'PDF',
      image: '图片',
      audio: '音频',
      video: '视频',
      link: '链接'
    };
    const kind = kindMap[String((item && item.kind) || '').toLowerCase()] || '资料';
    const timeLabel = formatShellTime(item && (item.updatedAt || item.addedAt));
    return timeLabel ? `${kind} · ${timeLabel}` : kind;
  }

  function buildShellItemResults(keyword, limit) {
    const normalized = String(keyword || '').trim().toLowerCase();
    const maxItems = Math.max(1, Number(limit || 40));
    const results = [];

    getShellSpacesQuick().forEach(function (space) {
      const items = Array.isArray(space && space.items) ? space.items : [];
      const spaceId = String((space && space.id) || '').trim();
      const spaceName = String((space && space.name) || '未命名空间').trim() || '未命名空间';
      items.forEach(function (item) {
        const name = String((item && item.name) || '').trim();
        if (!name) return;
        if (normalized && name.toLowerCase().indexOf(normalized) < 0) return;
        results.push({
          title: name,
          desc: `${spaceName} · ${formatShellItemMeta(item)}`,
          href: `spaces.html?space_id=${encodeURIComponent(spaceId)}&item_id=${encodeURIComponent(item.id)}`,
          tag: '资料',
          icon: 'page',
          updatedAt: Number((item && (item.updatedAt || item.addedAt)) || 0)
        });
      });
    });

    results.sort(function (left, right) {
      return Number(right.updatedAt || 0) - Number(left.updatedAt || 0);
    });

    return results.slice(0, maxItems);
  }

  function buildShellSearchResults(query) {
    const keyword = String(query || '').trim().toLowerCase();
    const matches = function (text) {
      if (!keyword) return true;
      return String(text || '').toLowerCase().indexOf(keyword) >= 0;
    };

    const pages = SHELL_PAGES.filter(function (page) {
      return matches(page.label) || matches(page.desc);
    }).map(function (page) {
      return {
        title: page.label,
        desc: page.desc,
        href: page.href,
        tag: '页面',
        icon: page.icon
      };
    });

    const spaces = getShellSpacesQuick().filter(function (space) {
      return matches(space && space.name);
    }).map(function (space) {
      const count = getSidebarSpaceCount(space);
      return {
        title: String((space && space.name) || '未命名空间'),
        desc: `${count} 份资料 · 更新于 ${formatShellTime(space && (space.updatedAt || space.createdAt)) || '—'}`,
        href: buildSpaceHref(space && space.id),
        tag: '空间',
        icon: 'space'
      };
    });

    const materials = buildShellItemResults(keyword, keyword ? 30 : 6);

    const recent = getShellRecent().filter(function (item) {
      return matches(item.title);
    }).map(function (item) {
      return {
        title: item.title,
        desc: formatShellTime(item.at) || '最近访问',
        href: item.href,
        tag: '最近',
        icon: item.tag === '空间' ? 'space' : 'clock'
      };
    });

    return pages.concat(spaces).concat(materials).concat(recent);
  }

  function buildShellLibraryResults(query) {
    const keyword = String(query || '').trim().toLowerCase();
    const materials = buildShellItemResults(keyword, 60);
    const spaces = getShellSpacesQuick().filter(function (space) {
      if (!keyword) return true;
      return String((space && space.name) || '').toLowerCase().indexOf(keyword) >= 0;
    }).map(function (space) {
      const count = getSidebarSpaceCount(space);
      return {
        title: String((space && space.name) || '未命名空间'),
        desc: `${count} 份资料 · 更新于 ${formatShellTime(space && (space.updatedAt || space.createdAt)) || '—'}`,
        href: buildSpaceHref(space && space.id),
        tag: '空间',
        icon: 'space'
      };
    });

    return materials.concat(spaces);
  }

  function buildShellHistoryResults(query) {
    const keyword = String(query || '').trim().toLowerCase();
    const matches = function (text) {
      if (!keyword) return true;
      return String(text || '').toLowerCase().indexOf(keyword) >= 0;
    };

    const visits = getShellRecent().filter(function (item) {
      return matches(item.title);
    }).map(function (item) {
      return {
        title: item.title,
        desc: formatShellTime(item.at) || '最近访问',
        href: item.href,
        tag: '最近访问',
        icon: item.tag === '空间' ? 'space' : 'clock'
      };
    });

    const sessions = readChatHistoryForShell().filter(function (session) {
      return matches(session.title);
    }).map(function (session) {
      return {
        title: String(session.title || '新对话'),
        desc: `${(session.messages || []).length} 条消息 · ${formatShellTime(session.updatedAt)}`,
        href: `chat.html?session=${encodeURIComponent(session.id)}`,
        tag: '对话记录',
        icon: 'chat'
      };
    });

    return visits.concat(sessions);
  }

  function getShellModalResults() {
    const input = document.getElementById('globalShellModalInput');
    const query = input ? input.value : '';
    if (shellModalMode === 'library') return buildShellLibraryResults(query);
    if (shellModalMode === 'history') return buildShellHistoryResults(query);
    return buildShellSearchResults(query);
  }

  function renderShellModalBody() {
    const body = document.getElementById('globalShellModalBody');
    const meta = document.getElementById('globalShellModalMeta');
    const title = document.getElementById('globalShellModalTitle');
    const input = document.getElementById('globalShellModalInput');
    if (!body) return;

    const copies = {
      search: { title: '搜索', placeholder: '搜索页面、空间、资料或最近记录…' },
      library: { title: '我的图书馆', placeholder: '筛选资料或空间…' },
      history: { title: '历史记录', placeholder: '筛选访问记录或对话…' }
    };
    const copy = copies[shellModalMode] || copies.search;
    if (title) title.textContent = copy.title;
    if (input) input.placeholder = copy.placeholder;

    shellModalResults = getShellModalResults();
    if (shellModalActiveIndex >= shellModalResults.length) {
      shellModalActiveIndex = shellModalResults.length ? 0 : -1;
    }

    if (!shellModalResults.length) {
      let emptyText = '没有匹配的结果';
      if (shellSpacesLoading && shellModalMode !== 'history') {
        emptyText = '正在加载你的空间与资料…';
      } else if (shellModalMode === 'library' && !isAuthenticatedUser()) {
        emptyText = '登录后即可汇总你的空间与资料。';
      } else if (shellModalMode === 'library') {
        emptyText = '图书馆还没有资料，去首页上传或添加学习内容吧。';
      } else if (shellModalMode === 'history') {
        emptyText = '还没有历史记录，先去逛逛吧。';
      }
      body.innerHTML = `
        <div class="shell-modal-empty">
          <div class="shell-modal-empty-title">${esc(emptyText)}</div>
          ${shellModalMode === 'library' && !isAuthenticatedUser() ? '<a class="shell-modal-empty-link" href="index.html">前往登录</a>' : ''}
        </div>
      `;
    } else {
      let lastTag = '';
      body.innerHTML = shellModalResults.map(function (item, index) {
        const groupLabel = item.tag !== lastTag
          ? `<div class="shell-result-group">${esc(item.tag)}</div>`
          : '';
        lastTag = item.tag;
        return `${groupLabel}
          <a class="shell-result${index === shellModalActiveIndex ? ' is-active' : ''}" href="${esc(item.href)}" data-shell-index="${index}">
            <span class="shell-result-icon" aria-hidden="true">${shellIcon(item.icon)}</span>
            <span class="shell-result-main">
              <span class="shell-result-title">${esc(item.title)}</span>
              <span class="shell-result-desc">${esc(item.desc)}</span>
            </span>
          </a>`;
      }).join('');
    }

    if (meta) {
      if (shellModalMode === 'library') {
        const spaces = getShellSpacesQuick();
        const totalItems = spaces.reduce(function (sum, space) {
          return sum + getSidebarSpaceCount(space);
        }, 0);
        meta.textContent = `${spaces.length} 个空间 · ${totalItems} 份资料`;
      } else if (shellModalMode === 'history') {
        meta.textContent = `${shellModalResults.length} 条记录`;
      } else {
        meta.textContent = `${shellModalResults.length} 条结果`;
      }
    }
  }

  function setShellModalActive(index) {
    if (!shellModalResults.length) return;
    const total = shellModalResults.length;
    shellModalActiveIndex = ((index % total) + total) % total;
    const nodes = document.querySelectorAll('#globalShellModalBody .shell-result');
    nodes.forEach(function (node, nodeIndex) {
      node.classList.toggle('is-active', nodeIndex === shellModalActiveIndex);
      if (nodeIndex === shellModalActiveIndex && typeof node.scrollIntoView === 'function') {
        node.scrollIntoView({ block: 'nearest' });
      }
    });
  }

  function openShellModal(mode) {
    const nextMode = ['search', 'library', 'history'].indexOf(mode) >= 0 ? mode : 'search';
    shellModalMode = nextMode;
    shellModalActiveIndex = 0;
    ensureShellModal();

    const modal = document.getElementById('globalShellModal');
    const input = document.getElementById('globalShellModalInput');
    if (!modal || !input) return;

    modal.hidden = false;
    shellModalOpen = true;
    document.body.classList.add('shell-modal-open');
    input.value = '';

    const needsSpaces = nextMode === 'library' || nextMode === 'search';
    const spacesPromise = needsSpaces ? getShellSpaces() : null;
    renderShellModalBody();
    window.setTimeout(function () { input.focus(); }, 20);

    if (spacesPromise) {
      spacesPromise.then(function () {
        if (shellModalOpen && (shellModalMode === 'library' || shellModalMode === 'search')) {
          renderShellModalBody();
        }
      });
    }
  }

  function closeShellModal() {
    const modal = document.getElementById('globalShellModal');
    if (!modal) return;
    modal.hidden = true;
    shellModalOpen = false;
    document.body.classList.remove('shell-modal-open');
    shellModalMode = 'search';
    shellModalResults = [];
    shellModalActiveIndex = 0;
  }

  function ensureShellModal() {
    if (document.getElementById('globalShellModal')) return;

    const modal = document.createElement('div');
    modal.id = 'globalShellModal';
    modal.className = 'shell-modal';
    modal.hidden = true;
    modal.innerHTML = `
      <div class="shell-modal-backdrop" data-shell-close></div>
      <div class="shell-modal-panel" role="dialog" aria-modal="true" aria-labelledby="globalShellModalTitle">
        <div class="shell-modal-head">
          <span class="shell-modal-head-icon" aria-hidden="true">${shellIcon('search')}</span>
          <div class="shell-modal-title" id="globalShellModalTitle">搜索</div>
          <button type="button" class="shell-modal-esc" data-shell-close>Esc</button>
        </div>
        <input id="globalShellModalInput" class="shell-modal-input" type="text" autocomplete="off" placeholder="搜索页面、空间、资料或最近记录…" />
        <div class="shell-modal-body" id="globalShellModalBody"></div>
        <div class="shell-modal-foot">
          <span>↑ ↓ 选择 · Enter 打开 · Esc 关闭</span>
          <span id="globalShellModalMeta"></span>
        </div>
      </div>
    `;
    document.body.appendChild(modal);

    const input = document.getElementById('globalShellModalInput');
    if (input) {
      input.addEventListener('input', function () {
        shellModalActiveIndex = 0;
        renderShellModalBody();
      });
    }
  }

  function bindShellToolsEvents() {
    if (document.body.dataset.pageShellToolsBound) return;
    document.body.dataset.pageShellToolsBound = '1';

    document.addEventListener('click', function (event) {
      const opener = event.target.closest('[data-shell-open]');
      if (opener) {
        event.preventDefault();
        openShellModal(opener.getAttribute('data-shell-open'));
        return;
      }

      if (event.target.closest('[data-shell-close]')) {
        event.preventDefault();
        closeShellModal();
        return;
      }

      const result = event.target.closest('#globalShellModalBody [data-shell-index]');
      if (result) {
        closeShellModal();
      }
    });

    document.addEventListener('click', function (event) {
      const spaceLink = event.target.closest('.global-sidebar-space-item');
      if (!spaceLink) return;
      const href = spaceLink.getAttribute('href') || '';
      if (!href) return;
      let spaceId = '';
      try {
        spaceId = new URL(href, window.location.href).searchParams.get('space_id') || '';
      } catch (error) {
        spaceId = '';
      }
      if (!spaceId) return;
      const titleNode = spaceLink.querySelector('.global-sidebar-space-item-text');
      const title = (titleNode ? titleNode.textContent : spaceLink.textContent || '').trim();
      pushShellRecent({
        id: `space:${spaceId}`,
        title: title || '我的空间',
        href: href,
        tag: '空间',
        at: Date.now()
      });
    });

    document.addEventListener('keydown', function (event) {
      if ((event.metaKey || event.ctrlKey) && String(event.key || '').toLowerCase() === 'k') {
        event.preventDefault();
        openShellModal('search');
        return;
      }

      if (!shellModalOpen) return;

      if (event.key === 'Escape') {
        event.preventDefault();
        closeShellModal();
        return;
      }

      if ((event.key === 'ArrowDown' || event.key === 'ArrowUp') && shellModalResults.length) {
        event.preventDefault();
        setShellModalActive(shellModalActiveIndex + (event.key === 'ArrowDown' ? 1 : -1));
        return;
      }

      if (event.key === 'Enter' && shellModalResults.length) {
        const target = shellModalResults[shellModalActiveIndex];
        if (!target) return;
        event.preventDefault();
        closeShellModal();
        window.location.href = target.href;
      }
    });
  }

  function initShellTools() {
    ensureSidebarTools();
    ensureShellModal();
    bindShellToolsEvents();
    recordShellPageVisit();
    renderSidebarRecent();

    if (getCurrentPageId() === 'spaces') {
      window.setTimeout(function () {
        recordShellPageVisit();
        renderSidebarRecent();
      }, 1200);
    }
  }

  window.PageShell = {
    closeGlobalSidebar: function () {
      const drawer = document.getElementById('globalSidebar');
      const backdrop = document.getElementById('globalSidebarBackdrop');
      const toggle = document.getElementById('globalSidebarToggle');
      if (!drawer || !backdrop) return;
      drawer.classList.remove('open');
      backdrop.classList.remove('show');
      document.body.classList.remove('sidebar-open');
      if (toggle) {
        toggle.setAttribute('aria-expanded', 'false');
        toggle.setAttribute('aria-label', '打开侧栏');
      }
    },
    openGlobalSidebar: function () {
      const drawer = document.getElementById('globalSidebar');
      const backdrop = document.getElementById('globalSidebarBackdrop');
      const toggle = document.getElementById('globalSidebarToggle');
      if (!drawer || !backdrop) return;
      drawer.classList.add('open');
      backdrop.classList.add('show');
      document.body.classList.add('sidebar-open');
      if (toggle) {
        toggle.setAttribute('aria-expanded', 'true');
        toggle.setAttribute('aria-label', '收起侧栏');
      }
    },
    initGlobalSidebar: initGlobalSidebar,
    markActiveSidebarLink: markActiveSidebarLink,
    refreshSidebarSpaces: refreshSidebarSpaces,
    refreshGlobalStreakWidget: refreshGlobalStreakWidget,
    trackLearningAction: function (action, payload) {
      postLearningBehavior({
        behavior_type: String(action || '').trim() || 'action_click',
        page: getCurrentPageId(),
        ...(payload && typeof payload === 'object' ? payload : {})
      }, false);
    },
    getCurrentPageId: getCurrentPageId,
    getLiveStaySeconds: function (pageId) {
      if (!telemetrySessionState.startedAt || telemetrySessionState.stayReported) return 0;
      if (pageId && String(pageId).trim() !== telemetrySessionState.pageId) return 0;
      return Math.max(0, (Date.now() - telemetrySessionState.startedAt) / 1000);
    },
    openShellModal: openShellModal,
    closeShellModal: closeShellModal,
    refreshShellRecent: function () {
      recordShellPageVisit();
      renderSidebarRecent();
    }
  };

  /* ==========================================================
     移动端底部导航
     直接复用侧边栏的链接、图标与文案，导航配置因此只有一处来源。
     ========================================================== */

  function initMobileTabbar() {
    if (!document.querySelector('.global-sidebar')) return;
    if (document.querySelector('.mobile-tabbar')) return;

    const links = Array.from(document.querySelectorAll('.global-sidebar a[data-side-link]'));
    if (!links.length) return;

    const currentPage = getCurrentPageId();
    const items = links
      .map(function (link) {
        const href = link.getAttribute('href') || '';
        const target = normalizeTargetPage(link.getAttribute('data-side-link') || href);
        const labelNode = link.querySelector('.st-nav-label');
        const iconNode = link.querySelector('.st-nav-icon');
        const label = labelNode ? String(labelNode.textContent || '').trim() : '';
        if (!target || !label) return '';

        const isActive = target === currentPage;
        return [
          '<a class="mobile-tabbar-item' + (isActive ? ' active' : '') + '" href="' + esc(href) + '"',
          isActive ? ' aria-current="page"' : '',
          '>',
          '<span class="mobile-tabbar-icon" aria-hidden="true">' + (iconNode ? iconNode.innerHTML : '') + '</span>',
          '<span class="mobile-tabbar-label">' + esc(label) + '</span>',
          '</a>'
        ].join('');
      })
      .filter(Boolean);

    if (!items.length) return;

    const tabbar = document.createElement('nav');
    tabbar.className = 'mobile-tabbar';
    tabbar.setAttribute('aria-label', '主导航');
    tabbar.innerHTML = items.join('');
    document.body.appendChild(tabbar);
    document.body.classList.add('has-mobile-tabbar');

    bindTabbarSuppression();
  }

  // 输入框聚焦时收起 Tab，避免遮挡聊天与答题的发送按钮。
  function bindTabbarSuppression() {
    if (document.body.dataset.tabbarSuppressBound) return;
    document.body.dataset.tabbarSuppressBound = '1';

    const sync = function (target) {
      const tag = target && target.tagName ? String(target.tagName).toLowerCase() : '';
      const editable = tag === 'input' || tag === 'textarea' || tag === 'select'
        || !!(target && target.isContentEditable);
      document.body.classList.toggle('tabbar-suppressed', editable);
    };

    document.addEventListener('focusin', function (event) { sync(event.target); });
    document.addEventListener('focusout', function () {
      window.setTimeout(function () { sync(document.activeElement); }, 0);
    });
  }

  /* ==========================================================
     PWA：只注册 Service Worker，业务逻辑不依赖它
     HTTP 部署下浏览器不允许注册，因此静默跳过。
     ========================================================== */

  function registerServiceWorker() {
    if (!('serviceWorker' in navigator)) return;
    if (!window.isSecureContext) return;

    window.addEventListener('load', function () {
      navigator.serviceWorker.register('sw.js').catch(function () {
        // 注册失败不影响任何业务功能。
      });
    }, { once: true });
  }

  function initPageShellRuntime() {
    initLearningTelemetry();
    initGlobalStreakWidget();

    if (document.querySelector('.global-sidebar')) {
      document.body.classList.add('has-global-sidebar');
      ensureSidebarCollapseButton();
      setSidebarDesktopCollapsed(readSidebarDesktopCollapsed(), false);
    }

    initShellTools();
    initMobileTabbar();
    registerServiceWorker();
  }

  try {
    if (document.querySelector('.global-sidebar')) {
      document.body.classList.add('has-global-sidebar');
      if (readSidebarDesktopCollapsed()) {
        document.body.classList.add('sidebar-collapsed');
      }
    }
  } catch (error) {
    // 忽略极早期 DOM 不可用的情况。
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initPageShellRuntime, { once: true });
  } else {
    initPageShellRuntime();
  }
})();
