(function () {
  const EMBED_PAGE = 'chat.html';
  const EXPAND_ICON = `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="M8 3H5a2 2 0 0 0-2 2v3"></path>
      <path d="M16 3h3a2 2 0 0 1 2 2v3"></path>
      <path d="M8 21H5a2 2 0 0 1-2-2v-3"></path>
      <path d="M16 21h3a2 2 0 0 0 2-2v-3"></path>
    </svg>
  `;
  const COLLAPSE_ICON = `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="M8 3v3a2 2 0 0 1-2 2H3"></path>
      <path d="M16 3v3a2 2 0 0 0 2 2h3"></path>
      <path d="M8 21v-3a2 2 0 0 0-2-2H3"></path>
      <path d="M16 21v-3a2 2 0 0 1 2-2h3"></path>
    </svg>
  `;

  let triggerButton = null;
  let panel = null;
  let frame = null;
  let closeButton = null;
  let addButton = null;
  let fullscreenButton = null;

  function buildEmbedUrl() {
    try {
      const target = new URL(EMBED_PAGE, window.location.href);
      const current = new URL(window.location.href);
      const apiBase = current.searchParams.get('api_base');
      if (apiBase) target.searchParams.set('api_base', apiBase);
      target.searchParams.set('embed', '1');
      return target.toString();
    } catch (error) {
      return `${EMBED_PAGE}?embed=1`;
    }
  }

  function buildPanel() {
    if (panel) return;

    panel = document.createElement('aside');
    panel.className = 'study-panel';
    panel.id = 'studyDrawer';
    panel.setAttribute('role', 'complementary');
    panel.setAttribute('aria-label', '学习标签');
    panel.setAttribute('aria-hidden', 'true');
    panel.innerHTML = `
      <div class="study-panel-head">
        <button type="button" class="study-panel-close" aria-label="关闭学习标签">×</button>
        <div class="study-panel-tabs">
          <span class="study-panel-tab is-active">
            <i class="study-panel-dot"></i>
            <span>学习标签</span>
          </span>
          <button type="button" class="study-panel-add" title="新建学习标签" aria-label="新建学习标签">+</button>
        </div>
        <button type="button" class="study-panel-fullscreen" title="全屏" aria-label="全屏">${EXPAND_ICON}</button>
      </div>
      <div class="study-panel-body">
        <iframe class="study-panel-frame" title="学习助手对话" loading="lazy"></iframe>
      </div>
    `;

    document.body.appendChild(panel);

    frame = panel.querySelector('.study-panel-frame');
    closeButton = panel.querySelector('.study-panel-close');
    addButton = panel.querySelector('.study-panel-add');
    fullscreenButton = panel.querySelector('.study-panel-fullscreen');

    if (closeButton) closeButton.addEventListener('click', closePanel);
    if (addButton) addButton.addEventListener('click', startNewStudyTab);
    if (fullscreenButton) fullscreenButton.addEventListener('click', toggleFullscreen);

    if (frame) {
      frame.addEventListener('load', function () {
        try {
          const frameDocument = frame.contentDocument;
          if (!frameDocument) return;
          frameDocument.addEventListener('keydown', function (event) {
            if (event.key === 'Escape') closePanel();
          });
          if (panel.classList.contains('is-open')) {
            focusFrameComposer();
          }
        } catch (error) {
          // 跨域或文档尚未就绪时忽略。
        }
      });
    }
  }

  function isOpen() {
    return !!(panel && panel.classList.contains('is-open'));
  }

  function focusFrameComposer() {
    if (!frame || !isOpen()) return;
    try {
      const frameDocument = frame.contentDocument;
      const input = frameDocument && frameDocument.getElementById('questionInput');
      if (input) input.focus({ preventScroll: true });
    } catch (error) {
      // 忽略输入框聚焦失败。
    }
  }

  function openPanel() {
    buildPanel();
    if (isOpen()) return;

    if (frame && !frame.getAttribute('src')) {
      frame.src = buildEmbedUrl();
    }

    panel.classList.add('is-open');
    panel.setAttribute('aria-hidden', 'false');
    document.body.classList.add('study-panel-open');
    if (triggerButton) triggerButton.setAttribute('aria-expanded', 'true');

    window.setTimeout(focusFrameComposer, 80);
  }

  function closePanel() {
    if (!panel) return;

    panel.classList.remove('is-open');
    panel.classList.remove('is-fullscreen');
    panel.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('study-panel-open');
    document.body.classList.remove('study-panel-fullscreen');
    if (triggerButton) {
      triggerButton.setAttribute('aria-expanded', 'false');
      triggerButton.focus({ preventScroll: true });
    }
    updateFullscreenButton(false);
  }

  function togglePanel() {
    if (isOpen()) {
      closePanel();
    } else {
      openPanel();
    }
  }

  function updateFullscreenButton(isFullscreen) {
    if (!fullscreenButton) return;
    fullscreenButton.innerHTML = isFullscreen ? COLLAPSE_ICON : EXPAND_ICON;
    fullscreenButton.setAttribute('aria-label', isFullscreen ? '退出全屏' : '全屏');
    fullscreenButton.title = isFullscreen ? '退出全屏' : '全屏';
  }

  function toggleFullscreen() {
    if (!panel) return;
    const isFullscreen = panel.classList.toggle('is-fullscreen');
    document.body.classList.toggle('study-panel-fullscreen', isFullscreen);
    updateFullscreenButton(isFullscreen);
    focusFrameComposer();
  }

  function startNewStudyTab() {
    if (!frame) return;
    try {
      const frameDocument = frame.contentDocument;
      const newChatButton = frameDocument && frameDocument.getElementById('newChatBtn');
      if (newChatButton) {
        newChatButton.click();
        focusFrameComposer();
        return;
      }
    } catch (error) {
      // 如果无法直接操作嵌入页，则重新加载一个新的问答页。
    }

    try {
      const target = new URL(buildEmbedUrl(), window.location.href);
      target.searchParams.set('t', String(Date.now()));
      frame.src = target.toString();
    } catch (error) {
      frame.src = `${EMBED_PAGE}?embed=1&t=${Date.now()}`;
    }
  }

  function init() {
    triggerButton = document.getElementById('studyLauncherBtn');
    if (!triggerButton || triggerButton.dataset.studyPanelBound === '1') return;
    triggerButton.dataset.studyPanelBound = '1';
    buildPanel();
    triggerButton.addEventListener('click', togglePanel);

    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && isOpen()) {
        closePanel();
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
