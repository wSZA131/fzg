(function () {
  const DEFAULT_LOCALE = 'CN';
  const THEME_STORAGE_KEY = 'fangzhigong_theme_pref';
  const REMEMBER_STORAGE_KEY = 'fangzhigong_remember_credential';
  let currentMode = 'login';
  let modalBound = false;
  let menuBound = false;
  let settingsBound = false;
  let activeSettingsTab = 'account';
  let settingsMessage = '';
  let activeMenuAnchorId = '';
  let isDeletingAccount = false;
  const MODAL_COPY = {
    login: {
      title: '欢迎回来',
      subtitle: '让我们继续您的学习之旅。'
    },
    register: {
      title: '创建账号',
      subtitle: '创建账号后，学习数据会自动绑定到你的身份。'
    }
  };

  function getApiBase() {
    if (window.ApiUtils && typeof window.ApiUtils.getApiBase === 'function') {
      return window.ApiUtils.getApiBase();
    }
    return window.location.origin || '';
  }

  function esc(text) {
    return String(text || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function safeStorageGet(key, fallback) {
    try {
      const value = localStorage.getItem(key);
      return value === null ? fallback : value;
    } catch (error) {
      return fallback;
    }
  }

  function safeStorageSet(key, value) {
    try {
      localStorage.setItem(key, value);
    } catch (error) {
      // 忽略只读存储或隐私模式错误，保持页面可继续使用。
    }
    return value;
  }

  function formatExpireText(value) {
    const raw = String(value || '').trim();
    if (!raw) return '未提供';
    const date = new Date(raw);
    if (Number.isNaN(date.getTime())) return raw;
    return date.toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit'
    });
  }

  function formatDateText(value) {
    const raw = String(value || '').trim();
    if (!raw) return '未提供';
    const date = new Date(raw);
    if (Number.isNaN(date.getTime())) return raw;
    return date.toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'long',
      day: '2-digit'
    });
  }

  function formatDateTimeText(value) {
    const raw = String(value || '').trim();
    if (!raw) return '未提供';
    const date = new Date(raw);
    if (Number.isNaN(date.getTime())) return raw;
    return date.toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit'
    });
  }

  function getThemePreference() {
    const raw = String(safeStorageGet(THEME_STORAGE_KEY, 'light') || '').trim().toLowerCase();
    return raw === 'dark' ? 'dark' : 'light';
  }

  function setThemePreference(value) {
    const normalized = String(value || '').trim().toLowerCase() === 'dark' ? 'dark' : 'light';
    safeStorageSet(THEME_STORAGE_KEY, normalized);
    applyPreferences();
    return normalized;
  }

  function applyPreferences() {
    const theme = getThemePreference();
    document.documentElement.setAttribute('data-fangzhigong-theme', theme);
    // 同步给原生控件（滚动条、表单、输入法候选框）
    document.documentElement.style.colorScheme = theme === 'dark' ? 'dark' : 'light';
  }

  function getContext() {
    const auth = window.UserContext && typeof window.UserContext.getAuthState === 'function'
      ? window.UserContext.getAuthState()
      : { authenticated: false, user: null };
    const locale = window.UserContext && typeof window.UserContext.getLocale === 'function'
      ? window.UserContext.getLocale()
      : DEFAULT_LOCALE;

    return {
      api: getApiBase(),
      auth,
      locale,
      userId: window.UserContext && typeof window.UserContext.getUserId === 'function'
        ? window.UserContext.getUserId()
        : 'default_user',
      displayName: window.UserContext && typeof window.UserContext.getDisplayName === 'function'
        ? window.UserContext.getDisplayName()
        : '同学',
      userLabel: window.UserContext && typeof window.UserContext.getUserLabel === 'function'
        ? window.UserContext.getUserLabel()
        : '访客',
      theme: getThemePreference()
    };
  }

  function getAuthenticatedDisplayName(ctx) {
    const auth = ctx && ctx.auth;
    if (auth && auth.authenticated && auth.user) {
      return auth.user.display_name || auth.user.username || ctx.displayName || '同学';
    }
    return '登录';
  }

  function isHomePage() {
    const path = String(window.location.pathname || '').replace(/\\/g, '/');
    const last = path.split('/').pop() || 'index.html';
    return !last || last === 'index.html';
  }

  function normalizeSettingsTab(tab) {
    if (tab === 'personalization') return 'personalization';
    if (tab === 'data-control') return 'data-control';
    if (tab === 'security') return 'security';
    return 'account';
  }

  function getMenuAnchorById(id) {
    return id ? document.getElementById(id) : null;
  }

  function ensureTopSlot() {
    const navbar = document.querySelector('.navbar');
    if (!navbar) return null;
    let slot = document.getElementById('authTopSlot');
    if (!slot) {
      slot = document.createElement('div');
      slot.id = 'authTopSlot';
      slot.className = 'auth-top-slot';
      navbar.appendChild(slot);
    }
    return slot;
  }

  function ensureSidebarSlot() {
    const sidebar = document.getElementById('globalSidebar');
    if (!sidebar) return null;
    let slot = document.getElementById('globalSidebarAuth');
    if (!slot) {
      slot = document.createElement('div');
      slot.id = 'globalSidebarAuth';
      slot.className = 'global-sidebar-auth';
      sidebar.appendChild(slot);
    }
    return slot;
  }

  function ensureModal() {
    let modal = document.getElementById('authModal');
    if (modal) return modal;

    document.body.insertAdjacentHTML('beforeend', `
      <div class="auth-modal" id="authModal" aria-hidden="true">
        <div class="auth-modal-panel" role="dialog" aria-modal="true" aria-labelledby="authModalBrand authModalTitle" aria-describedby="authModalSubtitle">
          <button type="button" class="auth-modal-close" id="authModalClose" aria-label="关闭登录面板">×</button>
          <div class="auth-modal-header">
            <div class="auth-modal-brand" id="authModalBrand">
              <span class="auth-modal-brand-mark" aria-hidden="true">
                <span></span>
                <span></span>
                <span></span>
              </span>
              <span class="auth-modal-brand-text">坊知工</span>
            </div>
          </div>
          <div class="auth-modal-copy">
            <div class="auth-modal-title" id="authModalTitle"></div>
            <div class="auth-modal-subtitle" id="authModalSubtitle"></div>
          </div>

          <div class="auth-tabs" id="authTabs">
            <button type="button" class="auth-tab active" data-auth-mode="login">登录</button>
            <button type="button" class="auth-tab" data-auth-mode="register">注册</button>
          </div>

          <form class="auth-form" id="authForm">
            <label class="auth-field">
              <span>账号</span>
              <input id="authUsernameInput" type="text" placeholder="3-32 位字母、数字或 . _ @ -" autocomplete="section-login username">
            </label>

            <label class="auth-field auth-register-only" id="authDisplayNameField" hidden>
              <span>昵称</span>
              <input id="authDisplayNameInput" type="text" placeholder="请输入昵称" autocomplete="section-register nickname">
            </label>

            <label class="auth-field">
              <span>密码</span>
              <div class="auth-password-row">
                <input id="authPasswordInput" type="password" placeholder="至少 8 位，需包含字母和数字" autocomplete="section-login current-password">
                <button type="button" class="auth-password-toggle" id="authPasswordToggle" aria-label="显示密码" aria-pressed="false">${getIconMarkup('eye')}</button>
              </div>
              <div class="auth-strength" id="authStrengthHint" hidden>
                <span class="auth-strength-track" aria-hidden="true"><i id="authStrengthFill"></i></span>
                <span class="auth-strength-text" id="authStrengthText"></span>
              </div>
            </label>

            <label class="auth-field auth-remember" id="authRememberField">
              <input id="authRememberInput" type="checkbox">
              <span>记住密码</span>
            </label>

            <div class="auth-actions">
              <button type="submit" class="auth-submit-btn" id="authSubmitBtn">登录</button>
            </div>

            <div class="auth-link-row">
              <button type="button" class="auth-link-btn" id="authForgotBtn">忘记密码？</button>
            </div>

            <div class="auth-recovery-code" id="authRecoveryCodeBox" hidden>
              <div class="auth-recovery-code-title">请立即保存恢复码，它只显示这一次</div>
              <div class="auth-recovery-code-value" id="authRecoveryCodeValue"></div>
              <button type="button" class="auth-recovery-code-copy" id="authRecoveryCodeCopy">复制</button>
            </div>

            <div class="auth-error" id="authErrorText"></div>
            <div class="auth-tip" id="authTipText" aria-live="polite"></div>
          </form>

          <form class="auth-form auth-recovery-form" id="authRecoveryForm" hidden>
            <div class="auth-recovery-heading">用恢复码重置密码</div>
            <div class="auth-recovery-copy">恢复码在注册成功时发放，也可登录后在「设置 → 安全」中重新生成。</div>

            <label class="auth-field">
              <span>账号</span>
              <input id="authRecoveryUsername" type="text" placeholder="需要重置的账号" autocomplete="off">
            </label>

            <label class="auth-field">
              <span>恢复码</span>
              <input id="authRecoveryCode" type="text" placeholder="XXXX-XXXX" autocomplete="off" spellcheck="false">
            </label>

            <label class="auth-field">
              <span>新密码</span>
              <input id="authRecoveryPassword" type="password" placeholder="至少 8 位，需包含字母和数字" autocomplete="new-password">
            </label>

            <div class="auth-actions">
              <button type="submit" class="auth-submit-btn" id="authRecoverySubmit">重置密码</button>
            </div>

            <div class="auth-link-row">
              <button type="button" class="auth-link-btn" id="authRecoveryBack">返回登录</button>
            </div>

            <div class="auth-error" id="authRecoveryError" hidden></div>
            <div class="auth-tip" id="authRecoveryTip" aria-live="polite"></div>
          </form>
        </div>
      </div>
    `);

    return document.getElementById('authModal');
  }

  function ensureMenu() {
    let menu = document.getElementById('authUserMenu');
    if (menu) return menu;

    document.body.insertAdjacentHTML('beforeend', `
      <div class="auth-user-menu" id="authUserMenu" hidden>
        <div class="auth-user-menu-card" role="menu" aria-label="账号菜单">
          <button type="button" class="auth-user-menu-item" data-auth-menu-action="settings">
            ${getIconMarkup('settings')}
            <span>设置</span>
          </button>
          <button type="button" class="auth-user-menu-item danger" data-auth-menu-action="logout">
            ${getIconMarkup('logout')}
            <span>退出登录</span>
          </button>
        </div>
      </div>
    `);

    return document.getElementById('authUserMenu');
  }

  function ensureSettingsModal() {
    let modal = document.getElementById('authSettingsModal');
    if (modal) return modal;

    document.body.insertAdjacentHTML('beforeend', `
      <div class="auth-settings-modal" id="authSettingsModal" aria-hidden="true">
        <div class="auth-settings-panel" role="dialog" aria-modal="true" aria-labelledby="authSettingsTitle">
          <div class="auth-settings-sidebar">
            <button type="button" class="auth-settings-close" id="authSettingsCloseBtn" aria-label="关闭设置面板">×</button>
            <div class="auth-settings-title" id="authSettingsTitle">设置</div>
            <div class="auth-settings-nav" id="authSettingsNav"></div>
          </div>
          <div class="auth-settings-content">
            <div class="auth-settings-body" id="authSettingsBody"></div>
            <div class="auth-settings-note" id="authSettingsNote"></div>
          </div>
        </div>
      </div>
    `);

    return document.getElementById('authSettingsModal');
  }

  function getIconMarkup(name) {
    switch (name) {
      case 'settings':
        return `
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <circle cx="12" cy="12" r="3.2"></circle>
            <path d="M19.4 15a1.6 1.6 0 0 0 .32 1.76l.06.06a1.92 1.92 0 1 1-2.72 2.72l-.06-.06A1.6 1.6 0 0 0 15 19.4a1.6 1.6 0 0 0-.96 1.46V21a1.92 1.92 0 1 1-3.84 0v-.14A1.6 1.6 0 0 0 9 19.4a1.6 1.6 0 0 0-1.76.32l-.06.06a1.92 1.92 0 1 1-2.72-2.72l.06-.06A1.6 1.6 0 0 0 4.6 15a1.6 1.6 0 0 0-1.46-.96H3a1.92 1.92 0 1 1 0-3.84h.14A1.6 1.6 0 0 0 4.6 9a1.6 1.6 0 0 0-.32-1.76l-.06-.06a1.92 1.92 0 1 1 2.72-2.72l.06.06A1.6 1.6 0 0 0 9 4.6a1.6 1.6 0 0 0 .96-1.46V3a1.92 1.92 0 1 1 3.84 0v.14A1.6 1.6 0 0 0 15 4.6a1.6 1.6 0 0 0 1.76-.32l.06-.06a1.92 1.92 0 1 1 2.72 2.72l-.06.06A1.6 1.6 0 0 0 19.4 9c0 .4.15.78.42 1.07.28.28.66.43 1.07.43H21a1.92 1.92 0 1 1 0 3.84h-.11A1.6 1.6 0 0 0 19.4 15Z"></path>
          </svg>
        `;
      case 'eye':
        return `
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M2.6 12S6.1 5.6 12 5.6 21.4 12 21.4 12 17.9 18.4 12 18.4 2.6 12 2.6 12Z"></path>
            <circle cx="12" cy="12" r="3.1"></circle>
          </svg>
        `;
      case 'eye-off':
        return `
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M3.2 3.2 20.8 20.8"></path>
            <path d="M10.4 6.1A10.4 10.4 0 0 1 12 6c5.9 0 9.4 6 9.4 6a17.6 17.6 0 0 1-3.2 3.7"></path>
            <path d="M6.6 7.9A17.2 17.2 0 0 0 2.6 12s3.5 6 9.4 6a9.7 9.7 0 0 0 4-.85"></path>
            <path d="M9.9 9.9a3.1 3.1 0 0 0 4.2 4.2"></path>
          </svg>
        `;
      case 'security':
        return `
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M12 3l7.5 3v5.5c0 4.6-3.1 8.3-7.5 9.5-4.4-1.2-7.5-4.9-7.5-9.5V6L12 3Z"></path>
            <path d="M9.2 12.1l2 2 3.6-3.9"></path>
          </svg>
        `;
      case 'logout':
        return `
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path>
            <path d="M16 17l5-5-5-5"></path>
            <path d="M21 12H9"></path>
          </svg>
        `;
      case 'account':
        return `
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M20 21a8 8 0 0 0-16 0"></path>
            <circle cx="12" cy="8" r="4"></circle>
          </svg>
        `;
      case 'personalization':
        return `
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M12 3a3 3 0 0 0 0 6"></path>
            <path d="M5.6 5.6a3 3 0 0 0 4.24 4.24"></path>
            <path d="M3 12a3 3 0 0 0 6 0"></path>
            <path d="M5.6 18.4a3 3 0 0 0 4.24-4.24"></path>
            <path d="M12 21a3 3 0 0 0 0-6"></path>
            <path d="M18.4 18.4a3 3 0 0 0-4.24-4.24"></path>
            <path d="M21 12a3 3 0 0 0-6 0"></path>
            <path d="M18.4 5.6a3 3 0 0 0-4.24 4.24"></path>
          </svg>
        `;
      case 'data':
        return `
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <ellipse cx="12" cy="5" rx="7" ry="3"></ellipse>
            <path d="M5 5v14c0 1.66 3.13 3 7 3s7-1.34 7-3V5"></path>
            <path d="M5 12c0 1.66 3.13 3 7 3s7-1.34 7-3"></path>
          </svg>
        `;
      default:
        return '';
    }
  }

  function getDefaultTipText() {
    return '';
  }

  function getAutocompleteValue(field, mode) {
    const normalizedMode = mode === 'register' ? 'register' : 'login';

    if (field === 'username') {
      return normalizedMode === 'register' ? 'section-register username' : 'section-login username';
    }
    if (field === 'password') {
      return normalizedMode === 'register' ? 'section-register new-password' : 'section-login current-password';
    }
    if (field === 'displayName') {
      return 'section-register nickname';
    }
    return 'off';
  }

  function normalizeAuthUsername(value) {
    return String(value || '').trim().toLowerCase();
  }

  function isValidAuthUsername(value) {
    return /^[a-z0-9][a-z0-9_.@-]{2,31}$/.test(normalizeAuthUsername(value));
  }

  function setFeedback(type, message) {
    const errorEl = document.getElementById('authErrorText');
    const tipEl = document.getElementById('authTipText');
    const nextMessage = String(message || '').trim();

    if (errorEl) {
      errorEl.textContent = type === 'error' ? nextMessage : '';
      errorEl.hidden = !(type === 'error' && nextMessage);
    }

    if (tipEl) {
      const tipMessage = type === 'error' ? '' : nextMessage;
      tipEl.textContent = tipMessage;
      tipEl.hidden = !tipMessage;
      tipEl.classList.toggle('is-success', type === 'success');
    }
  }

  function getGuestUserId() {
    if (!window.UserContext || typeof window.UserContext.getUserId !== 'function') return '';
    const userId = String(window.UserContext.getUserId() || '').trim();
    return /^guest_[a-z0-9]{8,40}$/.test(userId) ? userId : '';
  }

  function readRememberedCredential() {
    try {
      const raw = window.localStorage.getItem(REMEMBER_STORAGE_KEY);
      if (!raw) return null;
      const data = JSON.parse(raw);
      if (!data || !data.username || !data.password) return null;
      return data;
    } catch (error) {
      return null;
    }
  }

  function saveRememberedCredential(username, password) {
    try {
      window.localStorage.setItem(REMEMBER_STORAGE_KEY, JSON.stringify({
        username: String(username || ''),
        password: String(password || '')
      }));
    } catch (error) {
      // 隐私模式或存储配额不足时写入会失败，忽略即可
    }
  }

  function clearRememberedCredential() {
    try {
      window.localStorage.removeItem(REMEMBER_STORAGE_KEY);
    } catch (error) {
      // 忽略
    }
  }

  /** 打开登录弹窗时回填已记住的账号密码。 */
  function applyRememberedCredential() {
    const rememberInput = document.getElementById('authRememberInput');
    const credential = readRememberedCredential();

    if (!credential) {
      if (rememberInput) rememberInput.checked = false;
      return;
    }

    const usernameInput = document.getElementById('authUsernameInput');
    const passwordInput = document.getElementById('authPasswordInput');
    if (usernameInput && !usernameInput.value) usernameInput.value = credential.username;
    if (passwordInput && !passwordInput.value) passwordInput.value = credential.password;
    if (rememberInput) rememberInput.checked = true;
  }

  // 与后端 validate_password_strength 保持同一口径：至少 8 位，且同时含字母与数字
  function evaluatePasswordStrength(value) {
    const text = String(value || '');
    if (!text) return { level: 0, label: '', ok: false };

    const longEnough = text.length >= 8;
    const hasLetter = /[A-Za-z]/.test(text);
    const hasDigit = /\d/.test(text);

    if (longEnough && hasLetter && hasDigit) {
      return {
        level: text.length >= 12 ? 3 : 2,
        label: text.length >= 12 ? '强度：强' : '强度：可用',
        ok: true
      };
    }

    const missing = [];
    if (!longEnough) missing.push('至少 8 位');
    if (!hasLetter) missing.push('包含字母');
    if (!hasDigit) missing.push('包含数字');
    return { level: 1, label: '还需' + missing.join('、'), ok: false };
  }

  function updateStrengthHint() {
    const hint = document.getElementById('authStrengthHint');
    const fill = document.getElementById('authStrengthFill');
    const textEl = document.getElementById('authStrengthText');
    const input = document.getElementById('authPasswordInput');
    if (!hint || !fill || !textEl || !input) return;

    if (currentMode !== 'register') {
      hint.hidden = true;
      return;
    }

    const result = evaluatePasswordStrength(input.value);
    hint.hidden = !result.label;
    fill.style.width = (result.level / 3) * 100 + '%';
    fill.setAttribute('data-level', String(result.level));
    textEl.textContent = result.label;
    textEl.setAttribute('data-ok', result.ok ? '1' : '0');
  }

  function togglePasswordVisibility() {
    const input = document.getElementById('authPasswordInput');
    const toggle = document.getElementById('authPasswordToggle');
    if (!input || !toggle) return;

    const willShow = input.type === 'password';
    input.type = willShow ? 'text' : 'password';
    toggle.innerHTML = getIconMarkup(willShow ? 'eye-off' : 'eye');
    toggle.setAttribute('aria-pressed', willShow ? 'true' : 'false');
    toggle.setAttribute('aria-label', willShow ? '隐藏密码' : '显示密码');
  }

  function setRecoveryFeedback(type, message) {
    const errorEl = document.getElementById('authRecoveryError');
    const tipEl = document.getElementById('authRecoveryTip');
    const next = String(message || '').trim();

    if (errorEl) {
      errorEl.textContent = type === 'error' ? next : '';
      errorEl.hidden = !(type === 'error' && next);
    }
    if (tipEl) {
      const text = type === 'error' ? '' : next;
      tipEl.textContent = text;
      tipEl.hidden = !text;
    }
  }

  function showRecoveryView() {
    const form = document.getElementById('authForm');
    const recovery = document.getElementById('authRecoveryForm');
    const tabs = document.getElementById('authTabs');
    if (!form || !recovery) return;

    form.hidden = true;
    recovery.hidden = false;
    if (tabs) tabs.hidden = true;

    const recoveryUsername = document.getElementById('authRecoveryUsername');
    const loginUsername = document.getElementById('authUsernameInput');
    if (recoveryUsername && loginUsername && loginUsername.value) {
      recoveryUsername.value = loginUsername.value;
    }

    setFeedback('tip', '');
    setRecoveryFeedback('tip', '');
    if (recoveryUsername) recoveryUsername.focus();
  }

  function hideRecoveryView() {
    const form = document.getElementById('authForm');
    const recovery = document.getElementById('authRecoveryForm');
    const tabs = document.getElementById('authTabs');
    if (recovery) recovery.hidden = true;
    if (form) form.hidden = false;
    if (tabs) tabs.hidden = false;
    setRecoveryFeedback('tip', '');
    setFeedback('tip', getDefaultTipText());
  }

  function showRecoveryCode(code) {
    const box = document.getElementById('authRecoveryCodeBox');
    const valueEl = document.getElementById('authRecoveryCodeValue');
    if (!box || !valueEl || !code) return;
    valueEl.textContent = code;
    box.hidden = false;
  }

  function hideRecoveryCode() {
    const box = document.getElementById('authRecoveryCodeBox');
    if (box) box.hidden = true;
  }

  function updateModeUI() {
    const tabs = document.querySelectorAll('[data-auth-mode]');
    const form = document.getElementById('authForm');
    const usernameInput = document.getElementById('authUsernameInput');
    const displayNameField = document.getElementById('authDisplayNameField');
    const displayNameInput = document.getElementById('authDisplayNameInput');
    const passwordInput = document.getElementById('authPasswordInput');
    const submitBtn = document.getElementById('authSubmitBtn');
    const titleEl = document.getElementById('authModalTitle');
    const subtitleEl = document.getElementById('authModalSubtitle');
    const copy = MODAL_COPY[currentMode] || MODAL_COPY.login;

    tabs.forEach(function (tab) {
      tab.classList.toggle('active', tab.getAttribute('data-auth-mode') === currentMode);
    });

    if (displayNameField) displayNameField.hidden = currentMode !== 'register';
    if (form) {
      form.setAttribute('autocomplete', currentMode === 'register' ? 'off' : 'on');
    }
    if (usernameInput) {
      usernameInput.setAttribute('autocomplete', getAutocompleteValue('username', currentMode));
    }
    if (displayNameInput) {
      displayNameInput.setAttribute('autocomplete', getAutocompleteValue('displayName', currentMode));
    }
    if (passwordInput) {
      passwordInput.setAttribute('autocomplete', getAutocompleteValue('password', currentMode));
    }
    if (submitBtn) submitBtn.textContent = currentMode === 'register' ? '注册' : '登录';
    if (titleEl) titleEl.textContent = copy.title;
    if (subtitleEl) subtitleEl.textContent = copy.subtitle;

    const forgotBtn = document.getElementById('authForgotBtn');
    if (forgotBtn) forgotBtn.hidden = currentMode === 'register';

    const rememberField = document.getElementById('authRememberField');
    if (rememberField) {
      // 注册后会自动登录，只有登录场景需要"记住密码"
      rememberField.hidden = currentMode === 'register';
    }

    updateStrengthHint();
  }

  function clearCredentialFields() {
    const usernameInput = document.getElementById('authUsernameInput');
    const passwordInput = document.getElementById('authPasswordInput');

    if (usernameInput) usernameInput.value = '';
    if (passwordInput) passwordInput.value = '';
  }

  function resetRegisterCredentials() {
    if (currentMode !== 'register') return;

    clearCredentialFields();

    window.requestAnimationFrame(function () {
      if (currentMode !== 'register') return;
      clearCredentialFields();
    });

    window.setTimeout(function () {
      if (currentMode !== 'register') return;
      clearCredentialFields();
    }, 80);
  }

  function switchAuthMode(mode, options) {
    const opts = options || {};
    const nextMode = mode === 'register' ? 'register' : 'login';
    const changed = currentMode !== nextMode;

    currentMode = nextMode;
    hideRecoveryCode();
    updateModeUI();

    if (nextMode === 'register' && (changed || opts.forceResetCredentials)) {
      resetRegisterCredentials();
    }

    if (!opts.keepFeedback) {
      setFeedback('tip', '');
    }
  }

  function renderTopSlot() {
    // 页面右上角的账号入口已移除，登录/账号入口统一收进侧栏（renderSidebarSlot）。
    const slot = ensureTopSlot();
    if (!slot) return;
    slot.innerHTML = '';
    slot.hidden = true;
  }

  function renderSidebarSlot() {
    const slot = ensureSidebarSlot();
    if (!slot) return;

    const ctx = getContext();
    const auth = ctx.auth;
    const label = esc(getAuthenticatedDisplayName(ctx));
    const buttonClass = auth && auth.authenticated ? 'auth-sidebar-button is-authenticated' : 'auth-sidebar-button';
    const buttonAttrs = auth && auth.authenticated ? 'aria-haspopup="menu" aria-expanded="false"' : '';

    slot.innerHTML = `
      <button type="button" class="${buttonClass}" id="authSidebarActionBtn" ${buttonAttrs}>${label}</button>
    `;

    const btn = document.getElementById('authSidebarActionBtn');
    if (btn) {
      btn.addEventListener('click', function () {
        if (auth && auth.authenticated) {
          openQuickMenu(this);
        } else {
          openModal('login');
        }
      });
    }
  }

  function renderStatusCard() {
    const body = document.getElementById('authStatusCard');
    const actions = document.getElementById('authStatusCardActions');
    if (!body || !actions) return;

    const ctx = getContext();
    const auth = ctx.auth;
    const isLoggedIn = !!(auth && auth.authenticated && auth.user);

    body.innerHTML = isLoggedIn
      ? `
        <div class="auth-status-card">
          <div class="auth-status-badge is-authenticated">已登录</div>
          <div class="auth-status-title">${esc(auth.user.display_name || auth.user.username || '同学')}</div>
          <div class="auth-status-meta">账号：${esc(auth.user.username || ctx.userId)}<br>会话有效期：${esc(formatExpireText(auth.expires_at))}</div>
        </div>
      `
      : `
        <div class="auth-status-card">
          <div class="auth-status-badge is-guest">访客模式</div>
          <div class="auth-status-title">未登录</div>
          <div class="auth-status-meta">当前仍可继续浏览，但学习空间、图谱和计划会以本地访客身份保存。登录后会切换到账号自己的独立数据。</div>
        </div>
      `;

    actions.innerHTML = isLoggedIn
      ? `
        <button type="button" class="auth-mini-btn" id="authCardOpenBtn">打开设置</button>
        <button type="button" class="auth-mini-btn secondary" id="authCardLogoutBtn">退出登录</button>
      `
      : `
        <button type="button" class="auth-mini-btn secondary" id="authCardLoginBtn">打开登录面板</button>
      `;

    const openBtn = document.getElementById('authCardOpenBtn');
    const logoutBtn = document.getElementById('authCardLogoutBtn');
    const loginBtn = document.getElementById('authCardLoginBtn');

    if (openBtn) {
      openBtn.addEventListener('click', function () {
        openSettingsModal('account');
      });
    }

    if (logoutBtn) {
      logoutBtn.addEventListener('click', handleLogout);
    }

    if (loginBtn) {
      loginBtn.addEventListener('click', function () {
        openModal('login');
      });
    }
  }

  /**
   * 资料完成度按"昵称 + 个人简介"两项真实计算。
   * 此前用 created_at 参与计分，导致注册后立刻显示 100%，用户一眼能看出是假的。
   */
  function getProfileCompletion(ctx) {
    const auth = ctx && ctx.auth;
    if (!(auth && auth.authenticated)) return 0;

    const user = auth.user || {};
    const hasName = !!String(user.display_name || '').trim();
    const hasBio = !!String(user.bio || '').trim();
    const filled = (hasName ? 1 : 0) + (hasBio ? 1 : 0);
    return Math.round((filled / 2) * 100);
  }

  function buildSettingsNav() {
    const items = [
      { key: 'account', label: '账户', icon: 'account' },
      { key: 'security', label: '安全', icon: 'security' },
      { key: 'personalization', label: '个性化', icon: 'personalization' },
      { key: 'data-control', label: '数据控制', icon: 'data' }
    ];

    return items.map(function (item) {
      const active = item.key === activeSettingsTab ? 'active' : '';
      return `
        <button type="button" class="auth-settings-nav-btn ${active}" data-settings-tab="${item.key}">
          ${getIconMarkup(item.icon)}
          <span>${item.label}</span>
        </button>
      `;
    }).join('');
  }

  function buildAccountSettings(ctx) {
    const auth = ctx.auth;
    const user = auth && auth.user ? auth.user : {};
    const displayName = user.display_name || user.username || ctx.displayName || '同学';
    const username = user.username || ctx.userId || 'default_user';
    const bio = String(user.bio || '');
    const accountLabel = username.includes('@') ? '电子邮件' : '账号';
    const completion = getProfileCompletion(ctx);
    const heroText = completion >= 100
      ? '个人简介已完善，AI 会结合你的描述给出更贴合的讲解。'
      : '补充个人简介后，AI 会更了解你的专业背景与学习目标。';

    return `
      <section class="auth-settings-pane">
        <div class="auth-settings-subsection" id="authSettingsProfileSection">
          <div class="auth-settings-subsection-title">编辑资料</div>
          <form class="auth-settings-form" id="authSettingsProfileForm">
            <label class="auth-field">
              <span>昵称</span>
              <input id="authSettingsDisplayName" type="text" maxlength="24" value="${esc(displayName)}" placeholder="请输入昵称" autocomplete="nickname">
            </label>
            <label class="auth-field">
              <span>个人简介</span>
              <textarea id="authSettingsBio" class="auth-settings-textarea" rows="4" maxlength="200" placeholder="写下你的专业、学习目标或感兴趣的领域，AI 会据此调整讲解方式">${esc(bio)}</textarea>
              <div class="auth-settings-bio-meta" id="authSettingsBioCount">${bio.length}/200</div>
            </label>
            <div class="auth-actions">
              <button type="submit" class="auth-settings-primary-btn" id="authSettingsProfileSubmit">保存</button>
            </div>
          </form>
        </div>

        <div class="auth-settings-hero">
          <div class="auth-settings-hero-icon"><span>${completion}%</span></div>
          <div class="auth-settings-hero-copy">
            <div class="auth-settings-hero-title">完整简介</div>
            <div class="auth-settings-hero-text">${esc(heroText)}</div>
          </div>
          <button type="button" class="auth-settings-hero-btn" id="authSettingsHeroComplete"${completion >= 100 ? ' disabled' : ''}>${completion >= 100 ? '已完成' : '去完善'}</button>
        </div>

        <div class="auth-settings-list">
          <div class="auth-settings-row">
            <div class="auth-settings-row-label">名称</div>
            <div class="auth-settings-row-value">${esc(displayName)}</div>
          </div>
          <div class="auth-settings-row">
            <div class="auth-settings-row-label">个人简介</div>
            <div class="auth-settings-row-value">${bio ? esc(bio) : '未填写'}</div>
          </div>
          <div class="auth-settings-row">
            <div class="auth-settings-row-label">${accountLabel}</div>
            <div class="auth-settings-row-value">${esc(username)}</div>
          </div>
          <div class="auth-settings-row">
            <div class="auth-settings-row-label">创建日期</div>
            <div class="auth-settings-row-value">${esc(formatDateText(user.created_at))}</div>
          </div>
          <div class="auth-settings-row">
            <div class="auth-settings-row-label">最近登录</div>
            <div class="auth-settings-row-value">${esc(formatDateTimeText(user.last_login_at || auth.expires_at))}</div>
          </div>
          <div class="auth-settings-row">
            <div class="auth-settings-row-label">会话有效期</div>
            <div class="auth-settings-row-value">${esc(formatExpireText(auth.expires_at))}</div>
          </div>
        </div>
      </section>
    `;
  }

  function buildPersonalizationSettings(ctx) {
    const theme = ctx.theme === 'dark' ? 'dark' : 'light';
    const locale = String(ctx.locale || 'CN').toUpperCase() === 'EN' ? 'EN' : 'CN';

    return `
      <section class="auth-settings-pane">
        <div class="auth-settings-list">
          <div class="auth-settings-row auth-settings-row-select">
            <div class="auth-settings-row-label">主题</div>
            <select class="auth-settings-select" id="authSettingsThemeSelect" aria-label="主题">
              <option value="light" ${theme === 'light' ? 'selected' : ''}>浅色</option>
              <option value="dark" ${theme === 'dark' ? 'selected' : ''}>深色</option>
            </select>
          </div>
          <div class="auth-settings-row auth-settings-row-select">
            <div class="auth-settings-row-label">语言</div>
            <select class="auth-settings-select" id="authSettingsLocaleSelect" aria-label="语言">
              <option value="CN" ${locale === 'CN' ? 'selected' : ''}>简体中文</option>
              <option value="EN" ${locale === 'EN' ? 'selected' : ''}>English</option>
            </select>
          </div>
        </div>
        <div class="auth-settings-hint">语言切换目前覆盖登录、账号设置与主导航；正文内容仍以中文为主。</div>
      </section>
    `;
  }

  function buildDataControlSettings(ctx) {
    const auth = ctx && ctx.auth;
    const user = auth && auth.user ? auth.user : {};
    const username = user.username || (ctx && ctx.userId) || '当前账号';

    return `
      <section class="auth-settings-pane">
        <div class="auth-settings-danger">
          <div class="auth-settings-danger-row">
            <div>
              <div class="auth-settings-danger-title">删除账户</div>
              <div class="auth-settings-danger-copy">删除后会清空账号 ${esc(username)} 的学习计划、知识图谱和登录会话，且无法恢复。</div>
            </div>
            <button type="button" class="auth-settings-delete-btn" id="authSettingsDeleteBtn" ${isDeletingAccount ? 'disabled' : ''}>${isDeletingAccount ? '删除中...' : '删除'}</button>
          </div>
        </div>
      </section>
    `;
  }

  function buildSecuritySettings() {
    return `
      <section class="auth-settings-pane">
        <div class="auth-settings-subsection">
          <div class="auth-settings-subsection-title">修改密码</div>
          <form class="auth-settings-form" id="authSettingsPasswordForm">
            <label class="auth-field">
              <span>当前密码</span>
              <input id="authSettingsOldPassword" type="password" autocomplete="current-password" placeholder="请输入当前密码">
            </label>
            <label class="auth-field">
              <span>新密码</span>
              <input id="authSettingsNewPassword" type="password" autocomplete="new-password" placeholder="至少 8 位，需包含字母和数字">
            </label>
            <div class="auth-actions">
              <button type="submit" class="auth-settings-primary-btn" id="authSettingsPasswordSubmit">更新密码</button>
            </div>
          </form>
          <div class="auth-settings-hint">更新后，其他设备上的登录会话会立即失效。</div>
        </div>

        <div class="auth-settings-subsection">
          <div class="auth-settings-subsection-title">恢复码</div>
          <div class="auth-settings-hint">忘记密码时用恢复码重置。恢复码只显示一次，重新生成会让旧码立即失效。</div>
          <div class="auth-actions">
            <button type="button" class="auth-settings-secondary-btn" id="authSettingsIssueRecovery">重新生成恢复码</button>
          </div>
          <div class="auth-recovery-code" id="authSettingsRecoveryBox" hidden>
            <div class="auth-recovery-code-title">新的恢复码，请立即保存</div>
            <div class="auth-recovery-code-value" id="authSettingsRecoveryValue"></div>
          </div>
        </div>
      </section>
    `;
  }

  function getSettingsNoteText() {
    if (settingsMessage) return settingsMessage;
    if (activeSettingsTab === 'security') {
      return '密码与恢复码只保存在本系统内，不会发送到第三方。';
    }
    if (activeSettingsTab === 'personalization') {
      return '主题和聊天模式偏好会保存在当前浏览器。';
    }
    if (activeSettingsTab === 'data-control') {
      return '删除账户后会立即清空当前账号数据，并退出登录。';
    }
    return '账号信息会跟随当前登录态自动刷新。';
  }

  function renderSettingsModal() {
    const modal = ensureSettingsModal();
    const nav = document.getElementById('authSettingsNav');
    const body = document.getElementById('authSettingsBody');
    const note = document.getElementById('authSettingsNote');
    const ctx = getContext();
    const auth = ctx.auth;

    if (!(auth && auth.authenticated && auth.user)) {
      closeSettingsModal();
      openModal('login');
      return;
    }

    if (nav) nav.innerHTML = buildSettingsNav();

    if (body) {
      if (activeSettingsTab === 'security') {
        body.innerHTML = buildSecuritySettings();
      } else if (activeSettingsTab === 'personalization') {
        body.innerHTML = buildPersonalizationSettings(ctx);
      } else if (activeSettingsTab === 'data-control') {
        body.innerHTML = buildDataControlSettings(ctx);
      } else {
        body.innerHTML = buildAccountSettings(ctx);
      }
    }

    if (note) note.textContent = getSettingsNoteText();
    modal.setAttribute('aria-hidden', 'false');
  }

  function openModal(mode) {
    const auth = getContext().auth;
    if (auth && auth.authenticated) {
      openSettingsModal('account');
      return;
    }

    const modal = ensureModal();
    if (isHomePage()) {
      document.body.classList.add('auth-home-preview');
      document.documentElement.classList.add('auth-home-preview-open');
    }
    switchAuthMode(mode, { forceResetCredentials: mode === 'register', keepFeedback: true });
    setFeedback('tip', getDefaultTipText());
    closeQuickMenu();
    closeSettingsModal();
    modal.classList.add('show');
    modal.setAttribute('aria-hidden', 'false');

    applyRememberedCredential();

    const input = document.getElementById('authUsernameInput');
    if (input) {
      setTimeout(function () {
        input.focus();
      }, 20);
    }
  }

  function closeModal() {
    const modal = document.getElementById('authModal');
    if (!modal) return;
    modal.classList.remove('show');
    modal.setAttribute('aria-hidden', 'true');
    if (isHomePage()) {
      document.body.classList.remove('auth-home-preview');
      document.documentElement.classList.remove('auth-home-preview-open');
    }
  }

  function positionUserMenu(anchor) {
    const menu = ensureMenu();
    if (!anchor || menu.hidden) return;

    const rect = anchor.getBoundingClientRect();
    const width = menu.offsetWidth || 248;
    const height = menu.offsetHeight || 150;
    let left = rect.right - width;
    let top = rect.bottom + 12;

    if (left < 12) left = 12;
    if (left + width > window.innerWidth - 12) {
      left = window.innerWidth - width - 12;
    }
    if (top + height > window.innerHeight - 12) {
      top = rect.top - height - 12;
    }
    if (top < 12) top = 12;

    menu.style.left = `${left}px`;
    menu.style.top = `${top}px`;
  }

  function openQuickMenu(anchor) {
    const ctx = getContext();
    if (!(ctx.auth && ctx.auth.authenticated)) {
      openModal('login');
      return;
    }

    const menu = ensureMenu();
    const nextAnchorId = anchor && anchor.id ? anchor.id : '';
    const sameAnchorOpen = !menu.hidden && activeMenuAnchorId === nextAnchorId;
    closeQuickMenu();
    if (sameAnchorOpen) return;

    activeMenuAnchorId = nextAnchorId;
    menu.hidden = false;
    menu.classList.add('show');
    positionUserMenu(anchor);
    if (anchor) anchor.setAttribute('aria-expanded', 'true');
  }

  function closeQuickMenu() {
    const menu = document.getElementById('authUserMenu');
    if (!menu) return;

    const anchor = getMenuAnchorById(activeMenuAnchorId);
    if (anchor) anchor.setAttribute('aria-expanded', 'false');

    activeMenuAnchorId = '';
    menu.hidden = true;
    menu.classList.remove('show');
    menu.style.left = '';
    menu.style.top = '';
  }

  function openSettingsModal(tab) {
    const ctx = getContext();
    if (!(ctx.auth && ctx.auth.authenticated)) {
      openModal('login');
      return;
    }

    activeSettingsTab = normalizeSettingsTab(tab);
    settingsMessage = '';
    closeQuickMenu();
    closeModal();
    const modal = ensureSettingsModal();
    renderSettingsModal();
    modal.classList.add('show');
    modal.setAttribute('aria-hidden', 'false');
  }

  function closeSettingsModal() {
    const modal = document.getElementById('authSettingsModal');
    if (!modal) return;
    modal.classList.remove('show');
    modal.setAttribute('aria-hidden', 'true');
  }

  function isSettingsModalOpen() {
    const modal = document.getElementById('authSettingsModal');
    return !!(modal && modal.classList.contains('show'));
  }

  async function handleAuthSubmit(event) {
    event.preventDefault();
    if (!window.UserContext) return;

    const auth = getContext().auth;
    if (auth && auth.authenticated) {
      openSettingsModal('account');
      return;
    }

    const usernameInput = document.getElementById('authUsernameInput');
    const passwordInput = document.getElementById('authPasswordInput');
    const displayNameInput = document.getElementById('authDisplayNameInput');
    const submitBtn = document.getElementById('authSubmitBtn');

    const username = normalizeAuthUsername((usernameInput && usernameInput.value) || '');
    const password = String((passwordInput && passwordInput.value) || '');
    const displayName = String((displayNameInput && displayNameInput.value) || '').trim();
    if (!username || !password) {
      setFeedback('error', '请输入账号和密码。');
      return;
    }

    if (usernameInput) {
      usernameInput.value = username;
    }

    if (!isValidAuthUsername(username)) {
      setFeedback('error', '账号格式不正确，请使用 3-32 位字母、数字或 . _ @ -。');
      return;
    }

    if (currentMode === 'register' && !evaluatePasswordStrength(password).ok) {
      setFeedback('error', '密码需至少 8 位，并同时包含字母和数字。');
      return;
    }

    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = currentMode === 'register' ? '注册中...' : '登录中...';
    }

    setFeedback('tip', currentMode === 'register' ? '正在创建账号...' : '正在验证登录信息...');

    try {
      const endpoint = currentMode === 'register' ? '/api/auth/register' : '/api/auth/login';
      const guestUserId = getGuestUserId();

      const payload = {
        username,
        password
      };
      if (currentMode === 'register') {
        payload.display_name = displayName;
        // 注册时自动继承访客期间的学习记录，不再让用户手动勾选
        if (guestUserId) payload.guest_user_id = guestUserId;
      }

      const response = await fetch(`${getApiBase()}${endpoint}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        },
        body: JSON.stringify(payload)
      });

      // 账号锁定由后端返回 429，需要在统一错误解析之前单独读取提示语
      if (response.status === 429) {
        let lockedMessage = '尝试次数过多，请稍后再试。';
        try {
          const lockedData = await response.json();
          lockedMessage = lockedData.error_message || lockedData.message || lockedMessage;
        } catch (parseError) {
          // 保留默认提示
        }
        setFeedback('error', lockedMessage);
        return;
      }

      const data = window.ApiUtils
        ? await window.ApiUtils.parseApiResponse(response)
        : await response.json();

      if (data && data.auth && typeof window.UserContext.setAuth === 'function') {
        window.UserContext.setAuth(data.auth);
      }
      if (window.UserContext && typeof window.UserContext.resetGuestUserId === 'function') {
        window.UserContext.resetGuestUserId();
      }

      // 按用户选择记住或清除本机凭据（仅登录场景）
      const rememberInput = document.getElementById('authRememberInput');
      if (currentMode === 'login' && rememberInput) {
        if (rememberInput.checked) {
          saveRememberedCredential(username, password);
        } else {
          clearRememberedCredential();
        }
      }

      if (displayNameInput) displayNameInput.value = '';
      if (passwordInput) passwordInput.value = '';
      updateStrengthHint();

      const binding = (data && data.binding) || {};
      let successMessage = currentMode === 'register' ? '注册成功，已自动登录。' : '登录成功。';
      if (binding.migrated) {
        successMessage += ` 已并入访客记录：${binding.plans || 0} 个计划、`
          + `${binding.concepts || 0} 个知识点、${binding.spaces || 0} 个空间。`;
      }

      // 恢复码只在注册成功时下发一次：先让用户保存，再允许关闭弹窗
      if (currentMode === 'register' && data && data.recovery_code) {
        showRecoveryCode(data.recovery_code);
        setFeedback('success', '注册成功。请先保存下方恢复码，再关闭此窗口。');
        currentMode = 'login';
        renderAll();
        return;
      }

      setFeedback('success', successMessage);
      currentMode = 'login';
      renderAll();

      setTimeout(function () {
        closeModal();
      }, 420);
    } catch (error) {
      const message = error && error.message ? error.message : '登录失败，请稍后重试';
      setFeedback('error', message);
    } finally {
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = currentMode === 'register' ? '注册' : '登录';
      }
    }
  }

  async function handleRecoverySubmit(event) {
    event.preventDefault();

    const usernameInput = document.getElementById('authRecoveryUsername');
    const codeInput = document.getElementById('authRecoveryCode');
    const passwordInput = document.getElementById('authRecoveryPassword');
    const submitBtn = document.getElementById('authRecoverySubmit');

    const username = normalizeAuthUsername((usernameInput && usernameInput.value) || '');
    const recoveryCode = String((codeInput && codeInput.value) || '').trim();
    const newPassword = String((passwordInput && passwordInput.value) || '');

    if (!username || !recoveryCode || !newPassword) {
      setRecoveryFeedback('error', '请填写账号、恢复码和新密码。');
      return;
    }
    if (!evaluatePasswordStrength(newPassword).ok) {
      setRecoveryFeedback('error', '新密码需至少 8 位，并同时包含字母和数字。');
      return;
    }

    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = '重置中...';
    }
    setRecoveryFeedback('tip', '正在校验恢复码...');

    try {
      const response = await fetch(`${getApiBase()}/api/auth/recovery/reset`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        },
        body: JSON.stringify({
          username,
          recovery_code: recoveryCode,
          new_password: newPassword
        })
      });

      if (response.status === 429) {
        let lockedMessage = '尝试次数过多，请稍后再试。';
        try {
          const lockedData = await response.json();
          lockedMessage = lockedData.error_message || lockedData.message || lockedMessage;
        } catch (parseError) {
          // 保留默认提示
        }
        setRecoveryFeedback('error', lockedMessage);
        return;
      }

      const data = window.ApiUtils
        ? await window.ApiUtils.parseApiResponse(response)
        : await response.json();
      const nextCode = (data && data.recovery_code) || '';

      if (codeInput) codeInput.value = '';
      if (passwordInput) passwordInput.value = '';

      hideRecoveryView();
      currentMode = 'login';
      updateModeUI();

      if (nextCode) {
        showRecoveryCode(nextCode);
        setFeedback('success', '密码已重置，并已生成新的恢复码，请一并保存。');
      } else {
        setFeedback('success', '密码已重置，请用新密码登录。');
      }
    } catch (error) {
      const message = error && error.message ? error.message : '重置失败，请稍后重试';
      setRecoveryFeedback('error', message);
    } finally {
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = '重置密码';
      }
    }
  }

  function syncPageAuthState(ctx) {
    const auth = ctx && ctx.auth;
    const isAuthenticated = !!(auth && auth.authenticated);
    const guestHomeLayout = isHomePage() && !isAuthenticated;

    document.body.classList.toggle('guest-home-layout', guestHomeLayout);

    if (!guestHomeLayout) return;

    document.body.classList.remove('sidebar-open');
    const drawer = document.getElementById('globalSidebar');
    const backdrop = document.getElementById('globalSidebarBackdrop');
    if (drawer) drawer.classList.remove('open');
    if (backdrop) backdrop.classList.remove('show');
  }

  /**
   * 语言偏好需要同时落到后端：否则刷新时 /api/auth/me 会用旧的 locale
   * 覆盖本地值，表现为"切换后一会儿又变回中文"。
   */
  async function persistLocalePreference(locale) {
    try {
      await fetch(`${getApiBase()}/api/auth/profile`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        },
        body: JSON.stringify({ locale: locale })
      });
    } catch (error) {
      // 游客或后端不可达时，本地偏好仍然生效
    } finally {
      window.location.reload();
    }
  }

  async function handleUpdateProfile(event) {
    event.preventDefault();

    const input = document.getElementById('authSettingsDisplayName');
    const bioInput = document.getElementById('authSettingsBio');
    const submitBtn = document.getElementById('authSettingsProfileSubmit');
    const displayName = String((input && input.value) || '').trim();
    const bio = String((bioInput && bioInput.value) || '').trim();

    if (!displayName) {
      settingsMessage = '昵称不能为空。';
      renderSettingsModal();
      return;
    }

    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = '保存中...';
    }

    try {
      const response = await fetch(`${getApiBase()}/api/auth/profile`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        },
        body: JSON.stringify({ display_name: displayName, bio: bio })
      });
      const data = window.ApiUtils
        ? await window.ApiUtils.parseApiResponse(response)
        : await response.json();

      const nextUser = data && data.user;
      if (nextUser && window.UserContext && typeof window.UserContext.setAuth === 'function') {
        window.UserContext.setAuth({ authenticated: true, user: nextUser });
      }

      settingsMessage = '资料已更新。';
      renderSettingsModal();
    } catch (error) {
      settingsMessage = (error && error.message) || '资料更新失败';
      renderSettingsModal();
    } finally {
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = '保存';
      }
    }
  }

  async function handleChangePassword(event) {
    event.preventDefault();

    const oldInput = document.getElementById('authSettingsOldPassword');
    const newInput = document.getElementById('authSettingsNewPassword');
    const submitBtn = document.getElementById('authSettingsPasswordSubmit');
    const oldPassword = String((oldInput && oldInput.value) || '');
    const newPassword = String((newInput && newInput.value) || '');

    if (!oldPassword || !newPassword) {
      settingsMessage = '请填写当前密码和新密码。';
      renderSettingsModal();
      return;
    }
    if (!evaluatePasswordStrength(newPassword).ok) {
      settingsMessage = '新密码需至少 8 位，并同时包含字母和数字。';
      renderSettingsModal();
      return;
    }

    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = '更新中...';
    }

    try {
      const response = await fetch(`${getApiBase()}/api/auth/change-password`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        },
        body: JSON.stringify({
          old_password: oldPassword,
          new_password: newPassword
        })
      });
      const data = window.ApiUtils
        ? await window.ApiUtils.parseApiResponse(response)
        : await response.json();

      const revoked = (data && data.revoked_sessions) || 0;
      settingsMessage = revoked > 0
        ? `密码已更新，已退出其他 ${revoked} 个设备。`
        : '密码已更新。';

      renderSettingsModal();
    } finally {
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = '更新密码';
      }
    }
  }

  async function handleIssueRecoveryCode() {
    try {
      const response = await fetch(`${getApiBase()}/api/auth/recovery/issue`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        },
        body: JSON.stringify({})
      });
      const data = window.ApiUtils
        ? await window.ApiUtils.parseApiResponse(response)
        : await response.json();

      const code = (data && data.recovery_code) || '';
      if (!code) {
        settingsMessage = '生成恢复码失败，请稍后重试。';
        renderSettingsModal();
        return;
      }

      settingsMessage = '新的恢复码已生成，旧码立即失效。';
      renderSettingsModal();

      const box = document.getElementById('authSettingsRecoveryBox');
      const valueEl = document.getElementById('authSettingsRecoveryValue');
      if (box && valueEl) {
        valueEl.textContent = code;
        box.hidden = false;
      }
    } catch (error) {
      settingsMessage = (error && error.message) || '生成恢复码失败';
      renderSettingsModal();
    }
  }

  async function handleLogout() {
    closeQuickMenu();
    closeSettingsModal();

    try {
      const response = await fetch(`${getApiBase()}/api/auth/logout`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        }
      });

      if (window.ApiUtils && typeof window.ApiUtils.parseApiResponse === 'function') {
        await window.ApiUtils.parseApiResponse(response);
      }
    } catch (error) {
      // 无论后端是否可达，都清理本地会话，避免卡在假登录状态。
    } finally {
      if (window.UserContext && typeof window.UserContext.clearAuth === 'function') {
        window.UserContext.clearAuth({ reason: 'logout', force: true });
      }
      currentMode = 'login';
      settingsMessage = '';
      renderAll();
      closeModal();

      // 退出后回到未登录首页，避免停留在依赖登录态的页面上
      if (!isHomePage()) {
        window.location.href = 'index.html';
      }
    }
  }

  async function handleDeleteAccount() {
    if (isDeletingAccount) return;

    const ctx = getContext();
    const auth = ctx.auth;
    if (!(auth && auth.authenticated && auth.user)) {
      closeSettingsModal();
      openModal('login');
      return;
    }

    const username = auth.user.username || ctx.userId || '当前账号';
    const label = auth.user.display_name || username;
    const confirmed = window.confirm(`确认删除账户“${label}”吗？\n删除后将清空该账号的学习计划、知识图谱和登录会话，且无法恢复。`);
    if (!confirmed) return;

    isDeletingAccount = true;
    settingsMessage = '正在删除账户...';
    renderSettingsModal();

    try {
      const response = await fetch(`${getApiBase()}/api/auth/account`, {
        method: 'DELETE',
        headers: {
          'Accept': 'application/json'
        }
      });

      if (window.ApiUtils && typeof window.ApiUtils.parseApiResponse === 'function') {
        await window.ApiUtils.parseApiResponse(response);
      } else {
        await response.json();
      }

      if (window.UserContext && typeof window.UserContext.clearAuth === 'function') {
        window.UserContext.clearAuth({ reason: 'account_deleted', force: true });
      }
      currentMode = 'login';
      settingsMessage = '';
      closeQuickMenu();
      closeSettingsModal();
      closeModal();
      renderAll();
      window.alert(`账户 ${username} 已删除，当前已退出登录。`);
    } catch (error) {
      settingsMessage = error && error.message ? error.message : '删除账户失败，请稍后重试。';
      renderSettingsModal();
    } finally {
      isDeletingAccount = false;
      if (isSettingsModalOpen()) {
        renderSettingsModal();
      }
    }
  }

  async function syncSessionSilently() {
    if (!window.UserContext || typeof window.UserContext.isAuthenticated !== 'function') return;
    if (!window.UserContext.isAuthenticated()) return;

    try {
      const response = await fetch(`${getApiBase()}/api/auth/me`, {
        method: 'GET',
        headers: {
          'Accept': 'application/json'
        }
      });
      const data = window.ApiUtils
        ? await window.ApiUtils.parseApiResponse(response)
        : await response.json();

      if (data && data.auth && typeof window.UserContext.setAuth === 'function') {
        window.UserContext.setAuth(data.auth);
      }
    } catch (error) {
      if (
        error &&
        error.code === 'AUTH_REQUIRED' &&
        window.UserContext &&
        typeof window.UserContext.clearAuth === 'function'
      ) {
        window.UserContext.clearAuth({ reason: 'expired' });
      }
    }
  }

  function bindModalEvents() {
    if (modalBound) return;

    const modal = ensureModal();
    const form = document.getElementById('authForm');
    const closeBtn = document.getElementById('authModalClose');
    const tabs = document.querySelectorAll('[data-auth-mode]');

    if (form) {
      form.addEventListener('submit', handleAuthSubmit);
    }

    if (closeBtn) {
      closeBtn.addEventListener('click', closeModal);
    }

    const passwordToggle = document.getElementById('authPasswordToggle');
    if (passwordToggle) {
      passwordToggle.addEventListener('click', togglePasswordVisibility);
    }

    const passwordInput = document.getElementById('authPasswordInput');
    if (passwordInput) {
      passwordInput.addEventListener('input', updateStrengthHint);
    }

    const forgotBtn = document.getElementById('authForgotBtn');
    if (forgotBtn) {
      forgotBtn.addEventListener('click', showRecoveryView);
    }

    const recoveryBack = document.getElementById('authRecoveryBack');
    if (recoveryBack) {
      recoveryBack.addEventListener('click', hideRecoveryView);
    }

    const recoveryForm = document.getElementById('authRecoveryForm');
    if (recoveryForm) {
      recoveryForm.addEventListener('submit', handleRecoverySubmit);
    }

    const copyBtn = document.getElementById('authRecoveryCodeCopy');
    if (copyBtn) {
      copyBtn.addEventListener('click', function () {
        const valueEl = document.getElementById('authRecoveryCodeValue');
        const code = valueEl ? String(valueEl.textContent || '').trim() : '';
        if (!code) return;

        const done = function (text) {
          copyBtn.textContent = text;
          setTimeout(function () {
            copyBtn.textContent = '复制';
          }, 1600);
        };

        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(code).then(function () {
            done('已复制');
          }).catch(function () {
            done('请手动复制');
          });
          return;
        }
        done('请手动复制');
      });
    }

    tabs.forEach(function (tab) {
      tab.addEventListener('click', function () {
        switchAuthMode(this.getAttribute('data-auth-mode'));
      });
    });

    modal.addEventListener('click', function (event) {
      if (event.target === modal) {
        closeModal();
      }
    });

    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') {
        closeQuickMenu();
        closeSettingsModal();
        closeModal();
      }
    });

    modalBound = true;
  }

  function bindMenuEvents() {
    if (menuBound) return;

    const menu = ensureMenu();

    menu.addEventListener('click', function (event) {
      const button = event.target.closest('[data-auth-menu-action]');
      if (!button) return;

      const action = button.getAttribute('data-auth-menu-action');
      if (action === 'settings') {
        closeQuickMenu();
        openSettingsModal('account');
        return;
      }

      if (action === 'logout') {
        closeQuickMenu();
        handleLogout();
      }
    });

    document.addEventListener('click', function (event) {
      const menuEl = document.getElementById('authUserMenu');
      if (!menuEl || menuEl.hidden) return;

      const clickedAnchor = event.target.closest('#authTopActionBtn, #authSidebarActionBtn');
      if (clickedAnchor) return;
      if (!menuEl.contains(event.target)) {
        closeQuickMenu();
      }
    });

    window.addEventListener('resize', function () {
      const anchor = getMenuAnchorById(activeMenuAnchorId);
      if (anchor) {
        positionUserMenu(anchor);
      } else {
        closeQuickMenu();
      }
    });

    window.addEventListener('scroll', function () {
      closeQuickMenu();
    }, true);

    menuBound = true;
  }

  function bindSettingsEvents() {
    if (settingsBound) return;

    const modal = ensureSettingsModal();

    modal.addEventListener('click', function (event) {
      if (event.target === modal) {
        closeSettingsModal();
        return;
      }

      const closeBtn = event.target.closest('#authSettingsCloseBtn');
      if (closeBtn) {
        closeSettingsModal();
        return;
      }

      const tabBtn = event.target.closest('[data-settings-tab]');
      if (tabBtn) {
        activeSettingsTab = normalizeSettingsTab(tabBtn.getAttribute('data-settings-tab'));
        settingsMessage = '';
        renderSettingsModal();        return;
      }

      const deleteBtn = event.target.closest('#authSettingsDeleteBtn');
      if (deleteBtn) {
        handleDeleteAccount();
        return;
      }

      const heroBtn = event.target.closest('#authSettingsHeroComplete');
      if (heroBtn) {
        const section = document.getElementById('authSettingsProfileSection');
        const bioInput = document.getElementById('authSettingsBio');
        if (section) section.scrollIntoView({ behavior: 'smooth', block: 'start' });
        if (bioInput) bioInput.focus();
        return;
      }

      const issueBtn = event.target.closest('#authSettingsIssueRecovery');
      if (issueBtn) {
        handleIssueRecoveryCode();
        return;
      }
    });

    modal.addEventListener('submit', function (event) {
      if (!event.target) return;
      if (event.target.id === 'authSettingsPasswordForm') {
        handleChangePassword(event);
        return;
      }
      if (event.target.id === 'authSettingsProfileForm') {
        handleUpdateProfile(event);
      }
    });

    modal.addEventListener('change', function (event) {
      const target = event.target;
      if (!target) return;

      if (target.id === 'authSettingsThemeSelect') {
        setThemePreference(target.value || 'light');
        settingsMessage = '主题偏好已保存。';
        renderSettingsModal();
        return;
      }

      if (target.id === 'authSettingsLocaleSelect') {
        const locale = String(target.value || 'CN').toUpperCase() === 'EN' ? 'EN' : 'CN';
        if (window.UserContext && typeof window.UserContext.setLocale === 'function') {
          window.UserContext.setLocale(locale);
        }
        persistLocalePreference(locale);
      }
    });

    modal.addEventListener('input', function (event) {
      const target = event.target;
      if (!target || target.id !== 'authSettingsBio') return;
      const countEl = document.getElementById('authSettingsBioCount');
      if (countEl) countEl.textContent = `${target.value.length}/200`;
    });

    settingsBound = true;
  }

  function renderAll() {
    const ctx = getContext();
    closeQuickMenu();
    syncPageAuthState(ctx);
    renderTopSlot();
    renderSidebarSlot();
    renderStatusCard();
    updateModeUI();

    if (isSettingsModalOpen()) {
      renderSettingsModal();
    }
  }

  function init() {
    applyPreferences();
    ensureTopSlot();
    ensureSidebarSlot();
    ensureModal();
    ensureMenu();
    ensureSettingsModal();
    bindModalEvents();
    bindMenuEvents();
    bindSettingsEvents();
    renderAll();
    syncSessionSilently();

    if (window.UserContext && typeof window.UserContext.onChange === 'function') {
      window.UserContext.onChange(function () {
        renderAll();
      });
    }
  }

  window.AuthUI = {
    open: function (mode) {
      openModal(mode === 'register' ? 'register' : 'login');
    },
    openLogin: function () {
      openModal('login');
    },
    openRegister: function () {
      openModal('register');
    }
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
