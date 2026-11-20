/*
 * 中英文界面文案
 *
 * 为什么用"中文原文 → 英文"的映射而不是改写各处模板字符串：
 * 现有 UI 由大量模板字符串与内联 HTML 拼接而成，逐处改成 t('key') 需要改动
 * 上百行且容易漏；这里在渲染后对框架区域做一次文本替换，覆盖面更完整，
 * 也不影响中文模式（中文是原文，不做任何处理）。
 *
 * 覆盖范围：登录/注册弹窗、找回密码、账号设置面板、用户菜单、侧边栏与底部导航。
 * 页面正文（AI 回答、资料内容）不做替换，避免误伤学习内容。
 */

(function () {
  const DICT = {
    // 导航
    '添加内容': 'Add content',
    '智能问答': 'Ask AI',
    '题库练习': 'Practice',
    '学习仪表盘': 'Dashboard',
    '我的空间': 'My spaces',
    '空间': 'Spaces',

    // 登录 / 注册
    '登录': 'Sign in',
    '注册': 'Sign up',
    '账号': 'Account',
    '昵称': 'Display name',
    '密码': 'Password',
    '记住密码': 'Remember password',
    '忘记密码？': 'Forgot password?',
    '欢迎回来': 'Welcome back',
    '让我们继续您的学习之旅。': "Let's continue your learning journey.",
    '创建账号': 'Create account',
    '创建账号后，学习数据会自动绑定到你的身份。': 'Your learning data will be linked to this account.',
    '3-32 位字母、数字或 . _ @ -': '3-32 letters, digits or . _ @ -',
    '请输入昵称': 'Enter a display name',
    '至少 8 位，需包含字母和数字': 'At least 8 characters, with letters and numbers',
    '登录中...': 'Signing in...',
    '注册中...': 'Creating...',
    '注册成功，已自动登录。': 'Account created and signed in.',
    '登录成功。': 'Signed in.',
    '请输入账号和密码。': 'Enter your account and password.',
    '账号格式不正确，请使用 3-32 位字母、数字或 . _ @ -。': 'Invalid account format. Use 3-32 letters, digits or . _ @ -.',
    '密码需至少 8 位，并同时包含字母和数字。': 'Password needs 8+ characters with both letters and digits.',
    '注册成功。请先保存下方恢复码，再关闭此窗口。': 'Account created. Save the recovery code below before closing.',
    '登录失败，请稍后重试': 'Sign-in failed, please try again later',
    '尝试次数过多，请稍后再试。': 'Too many attempts, please try again later.',
    '显示密码': 'Show password',
    '隐藏密码': 'Hide password',

    // 密码强度
    '强度：可用': 'Strength: fair',
    '强度：强': 'Strength: strong',
    '还需': 'Still needs ',
    '至少 8 位': '8+ characters',
    '包含字母': 'letters',
    '包含数字': 'digits',

    // 找回密码
    '用恢复码重置密码': 'Reset password with recovery code',
    '恢复码在注册成功时发放，也可登录后在「设置 → 安全」中重新生成。': 'The recovery code is issued at sign-up; you can regenerate it in Settings → Security.',
    '恢复码': 'Recovery code',
    '需要重置的账号': 'Account to reset',
    '新密码': 'New password',
    '重置密码': 'Reset password',
    '返回登录': 'Back to sign in',
    '请填写账号、恢复码和新密码。': 'Fill in account, recovery code and new password.',
    '新密码需至少 8 位，并同时包含字母和数字。': 'New password needs 8+ characters with letters and digits.',
    '正在校验恢复码...': 'Verifying recovery code...',
    '重置中...': 'Resetting...',
    '密码已重置，请用新密码登录。': 'Password reset. Sign in with the new password.',
    '密码已重置，并已生成新的恢复码，请一并保存。': 'Password reset. A new recovery code was generated, save it too.',
    '重置失败，请稍后重试': 'Reset failed, please try again later',
    '请立即保存恢复码，它只显示这一次': 'Save this recovery code now, it is shown only once',
    '复制': 'Copy',
    '已复制': 'Copied',
    '请手动复制': 'Copy manually',

    // 设置面板
    '设置': 'Settings',
    '账户': 'Account',
    '安全': 'Security',
    '个性化': 'Personalization',
    '数据控制': 'Data control',
    '编辑资料': 'Edit profile',
    '保存': 'Save',
    '保存中...': 'Saving...',
    '修改密码': 'Change password',
    '当前密码': 'Current password',
    '更新密码': 'Update password',
    '更新中...': 'Updating...',
    '更新后，其他设备上的登录会话会立即失效。': 'Other devices will be signed out immediately.',
    '重新生成恢复码': 'Generate new recovery code',
    '新的恢复码，请立即保存': 'New recovery code, save it now',
    '新的恢复码已生成，旧码立即失效。': 'New recovery code generated; the old one is void.',
    '忘记密码时用恢复码重置。恢复码只显示一次，重新生成会让旧码立即失效。': 'Use the recovery code to reset your password. It is shown once; regenerating voids the old one.',
    '生成恢复码失败': 'Failed to generate recovery code',
    '生成恢复码失败，请稍后重试。': 'Failed to generate recovery code, please try again later.',
    '密码与恢复码只保存在本系统内，不会发送到第三方。': 'Passwords and recovery codes stay in this system.',
    '昵称不能为空。': 'Display name cannot be empty.',
    '资料已更新。': 'Profile updated.',
    '资料更新失败': 'Failed to update profile',
    '密码已更新。': 'Password updated.',
    '密码更新失败': 'Failed to update password',
    '请填写当前密码和新密码。': 'Enter current and new password.',
    '主题': 'Theme',
    '浅色': 'Light',
    '深色': 'Dark',
    '语言': 'Language',
    '主题偏好已保存。': 'Theme preference saved.',
    '语言偏好已保存。': 'Language preference saved.',
    '语言切换目前覆盖登录、账号设置与主导航；正文内容仍以中文为主。': 'Language covers sign-in, account settings and navigation; content stays in Chinese.',
    '主题和聊天模式偏好会保存在当前浏览器。': 'Theme preference is saved in this browser.',
    '账号信息会跟随当前登录态自动刷新。': 'Account info refreshes with your session.',
    '删除账户': 'Delete account',
    '删除': 'Delete',
    '删除中...': 'Deleting...',
    '删除账户后会立即清空当前账号数据，并退出登录。': 'Deleting clears this account data and signs you out.',
    '删除账户失败，请稍后重试。': 'Failed to delete account, please try again later.',
    '正在删除账户...': 'Deleting account...',
    '完整简介': 'Profile completeness',
    '个人简介': 'Bio',
    '去完善': 'Complete now',
    '已完成': 'Completed',
    '未填写': 'Not set',
    '写下你的专业、学习目标或感兴趣的领域，AI 会据此调整讲解方式': 'Describe your major, goals or interests; AI will adapt its explanations.',
    '补充个人简介后，AI 会更了解你的专业背景与学习目标。': 'Add a bio so AI understands your background and goals.',
    '个人简介已完善，AI 会结合你的描述给出更贴合的讲解。': 'Your bio is complete; AI will tailor its explanations.',
    '名称': 'Name',
    '创建日期': 'Created',
    '最近登录': 'Last sign-in',
    '会话有效期': 'Session expires',
    '完整': 'Complete',
    '补全账号资料后，系统会更稳定地展示个性化内容。': 'Complete your profile for better personalization.',
    '账号资料已准备完成，可继续获取个性化内容。': 'Profile is complete; personalization is ready.',
    '退出登录': 'Sign out',
    '打开设置': 'Open settings',
    '关闭设置面板': 'Close settings',
    '关闭登录面板': 'Close sign-in',
    '账号菜单': 'Account menu',
    '未登录': 'Not signed in',
    '已登录': 'Signed in',
    '访客模式': 'Guest mode',
    '访客': 'Guest',
    '同学': 'there',
    '当前账号': 'current account',
    '电子邮件': 'Email'
  };

  // 只翻译框架区域，避免误伤 AI 回答与资料正文
  const SCOPE_SELECTORS = [
    '.auth-modal',
    '.auth-settings-modal',
    '.auth-user-menu',
    '.global-sidebar',
    '.mobile-tabbar',
    '.navbar',
    '.auth-status-card',
    '.space-search-panel'
  ];

  const TEXT_ATTRS = ['placeholder', 'title', 'aria-label'];
  const SKIP_TAGS = { SCRIPT: 1, STYLE: 1, CODE: 1, PRE: 1, TEXTAREA: 1 };

  function getLocale() {
    if (window.UserContext && typeof window.UserContext.getLocale === 'function') {
      return String(window.UserContext.getLocale() || 'CN').toUpperCase() === 'EN' ? 'EN' : 'CN';
    }
    return 'CN';
  }

  function isEnglish() {
    return getLocale() === 'EN';
  }

  function translateValue(raw) {
    const key = String(raw || '').trim();
    if (!key) return '';
    return DICT[key] || '';
  }

  function translateTextNodes(root) {
    if (!root || typeof document.createTreeWalker !== 'function') return;

    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);

    nodes.forEach(function (node) {
      const parent = node.parentElement;
      if (!parent || SKIP_TAGS[parent.tagName]) return;

      const raw = node.nodeValue || '';
      const translated = translateValue(raw);
      if (!translated) return;

      // 保留原有前后空白，避免影响行内布局
      const leading = raw.match(/^\s*/)[0];
      const trailing = raw.match(/\s*$/)[0];
      node.nodeValue = leading + translated + trailing;
    });
  }

  function translateAttributes(root) {
    if (!root || !root.querySelectorAll) return;

    root.querySelectorAll('[placeholder], [title], [aria-label]').forEach(function (el) {
      TEXT_ATTRS.forEach(function (attr) {
        const value = el.getAttribute(attr);
        if (!value) return;
        const translated = translateValue(value);
        if (translated) el.setAttribute(attr, translated);
      });
    });
  }

  function translateTree(root) {
    translateTextNodes(root);
    translateAttributes(root);
  }

  /** 全量扫描已存在的框架区域。 */
  function apply() {
    if (!isEnglish()) return;
    SCOPE_SELECTORS.forEach(function (selector) {
      document.querySelectorAll(selector).forEach(function (node) {
        translateTree(node);
      });
    });
  }

  function init() {
    if (!isEnglish()) return;

    apply();

    // 弹窗、侧边栏空间列表等是动态插入的，监听新增节点继续翻译
    if (typeof MutationObserver !== 'function') return;

    const observer = new MutationObserver(function (mutations) {
      mutations.forEach(function (mutation) {
        mutation.addedNodes.forEach(function (node) {
          if (!node || node.nodeType !== 1) return;
          const inScope = SCOPE_SELECTORS.some(function (selector) {
            return node.matches && (node.matches(selector) || node.querySelector(selector));
          });
          if (inScope) translateTree(node);
        });
      });
    });

    observer.observe(document.body, { childList: true, subtree: true });
  }

  window.I18n = {
    t: function (key, fallback) {
      const dict = isEnglish() ? DICT[key] : '';
      return dict || (fallback !== undefined ? fallback : key);
    },
    isEnglish: isEnglish,
    getLocale: getLocale,
    apply: apply
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
