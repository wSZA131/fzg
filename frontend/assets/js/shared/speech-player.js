/*
 * 朗读 / 听讲解
 *
 * 只用浏览器原生 SpeechSynthesis，不引入任何 TTS 服务与依赖，因此没有额外费用，
 * 也不上传学习内容。代价是音色取决于用户设备自带的语音包。
 *
 * 用法：
 *   <button data-speak-toggle>朗读</button>      自动读取相邻 .message-text
 *   <button data-speak-toggle data-speak-text="…">朗读</button>   指定文本
 *
 * 长文本会被切成句子逐段朗读，避免浏览器对单条 utterance 的长度限制。
 */
(function () {
  const SUPPORTED = typeof window !== 'undefined'
    && 'speechSynthesis' in window
    && typeof window.SpeechSynthesisUtterance === 'function';

  const DEFAULT_LANG = 'zh-CN';
  const DEFAULT_RATE = 1.0;
  const CHUNK_MAX_CHARS = 120;
  const ICON_PLAY = '▶';
  const ICON_STOP = '■';

  let activeButton = null;
  let activeChunks = [];
  let activeIndex = 0;
  let activeRate = DEFAULT_RATE;
  let speaking = false;

  function isSupported() {
    return SUPPORTED;
  }

  function pickVoice() {
    if (!SUPPORTED) return null;
    const voices = window.speechSynthesis.getVoices() || [];
    if (!voices.length) return null;

    const zhVoices = voices.filter(function (voice) {
      return /^zh([-_]|$)/i.test(String(voice.lang || ''));
    });
    if (!zhVoices.length) return null;

    const preferred = zhVoices.find(function (voice) {
      return /Xiaoxiao|Xiaoyi|Tingting|Huihui|Yaoyao|female|女/i.test(String(voice.name || ''));
    });
    return preferred || zhVoices[0];
  }

  /** 把 Markdown / LaTeX 转成适合朗读的纯文本。 */
  function toSpeakableText(raw) {
    let text = String(raw || '');
    if (!text) return '';

    text = text.replace(/```[\s\S]*?```/g, '。代码片段略。');
    text = text.replace(/\$\$[\s\S]*?\$\$/g, '。公式。');
    text = text.replace(/\$[^$\n]{1,80}\$/g, '公式');
    text = text.replace(/!\[[^\]]*\]\([^)]*\)/g, '');
    text = text.replace(/\[([^\]]*)\]\([^)]*\)/g, '$1');
    text = text.replace(/^[\s]*[-*+]\s+/gm, '');
    text = text.replace(/^[\s]*#{1,6}\s*/gm, '');
    text = text.replace(/^[\s]*>\s?/gm, '');
    text = text.replace(/[*_~`]/g, '');
    text = text.replace(/\|/g, '，');
    text = text.replace(/[ \t]+/g, ' ');
    text = text.replace(/\n{2,}/g, '\n');
    return text.trim();
  }

  /** 按句末标点切分，超长句再按逗号切，最后兜底硬切。 */
  function splitIntoChunks(text) {
    const source = String(text || '').trim();
    if (!source) return [];

    const sentences = source.match(/[^。！？!?；;\n]+[。！？!?；;\n]?/g) || [source];
    const chunks = [];

    sentences.forEach(function (sentence) {
      const piece = sentence.trim();
      if (!piece) return;
      if (piece.length <= CHUNK_MAX_CHARS) {
        chunks.push(piece);
        return;
      }

      let buffer = '';
      piece.split(/(?<=[，,、])/).forEach(function (part) {
        if (!part) return;
        if ((buffer + part).length > CHUNK_MAX_CHARS && buffer) {
          chunks.push(buffer);
          buffer = part;
        } else {
          buffer += part;
        }
      });
      if (buffer) {
        while (buffer.length > CHUNK_MAX_CHARS) {
          chunks.push(buffer.slice(0, CHUNK_MAX_CHARS));
          buffer = buffer.slice(CHUNK_MAX_CHARS);
        }
        if (buffer) chunks.push(buffer);
      }
    });

    return chunks;
  }

  function setButtonState(button, isSpeaking) {
    if (!button) return;
    const iconEl = button.querySelector('.message-action-icon');
    const labelEl = button.querySelector('.message-action-label');
    button.classList.toggle('is-speaking', !!isSpeaking);
    button.setAttribute('aria-pressed', isSpeaking ? 'true' : 'false');
    button.setAttribute('aria-label', isSpeaking ? '停止朗读' : '朗读这段内容');
    if (iconEl) iconEl.textContent = isSpeaking ? ICON_STOP : ICON_PLAY;
    if (labelEl) labelEl.textContent = isSpeaking ? '停止' : '朗读';
  }

  function resetActive() {
    if (activeButton) setButtonState(activeButton, false);
    activeButton = null;
    activeChunks = [];
    activeIndex = 0;
    speaking = false;
  }

  function stop() {
    if (!SUPPORTED) return;
    speaking = false;
    try {
      window.speechSynthesis.cancel();
    } catch (error) {
      // 某些浏览器在无语音时 cancel 会抛错，忽略即可
    }
    resetActive();
  }

  function speakChunk() {
    if (!speaking) return;

    if (activeIndex >= activeChunks.length) {
      resetActive();
      return;
    }

    const utterance = new window.SpeechSynthesisUtterance(activeChunks[activeIndex]);
    utterance.lang = DEFAULT_LANG;
    utterance.rate = activeRate;
    utterance.pitch = 1.0;

    const voice = pickVoice();
    if (voice) utterance.voice = voice;

    utterance.onend = function () {
      if (!speaking) return;
      activeIndex += 1;
      speakChunk();
    };
    utterance.onerror = function () {
      // 用户切换或系统中断时也会触发 error，这里统一收尾
      resetActive();
    };

    try {
      window.speechSynthesis.speak(utterance);
    } catch (error) {
      resetActive();
    }
  }

  /**
   * 朗读一段文本。
   * @param {string} text 原始文本（可以是 Markdown）
   * @param {{button?: HTMLElement, rate?: number}} options
   */
  function speak(text, options) {
    if (!SUPPORTED) return false;

    const opts = options || {};
    const speakable = toSpeakableText(text);
    if (!speakable) return false;

    const chunks = splitIntoChunks(speakable);
    if (!chunks.length) return false;

    stop();

    activeButton = opts.button || null;
    activeChunks = chunks;
    activeIndex = 0;
    activeRate = typeof opts.rate === 'number' && opts.rate > 0 ? opts.rate : DEFAULT_RATE;
    speaking = true;

    setButtonState(activeButton, true);
    speakChunk();
    return true;
  }

  function resolveText(button) {
    const explicit = button.getAttribute('data-speak-text') || '';
    if (explicit) return explicit;

    const bubble = button.closest('.message-bubble');
    if (bubble) {
      const textEl = bubble.querySelector('.message-text');
      if (textEl) return textEl.textContent || '';
    }

    const scopeSelector = button.getAttribute('data-speak-source') || '';
    if (scopeSelector) {
      const scope = document.querySelector(scopeSelector);
      if (scope) return scope.textContent || '';
    }

    return '';
  }

  function handleToggle(button) {
    if (!SUPPORTED) return;

    if (button === activeButton && speaking) {
      stop();
      return;
    }

    const text = resolveText(button);
    if (!text) return;
    speak(text, { button: button });
  }

  function init() {
    if (!SUPPORTED) {
      // 不支持朗读时隐藏入口，避免出现点了没反应的按钮
      document.querySelectorAll('[data-speak-toggle]').forEach(function (button) {
        button.hidden = true;
      });
      return;
    }

    // 部分浏览器首次 getVoices() 为空，预热一次
    pickVoice();
    if (typeof window.speechSynthesis.onvoiceschanged !== 'undefined') {
      window.speechSynthesis.onvoiceschanged = pickVoice;
    }

    document.addEventListener('click', function (event) {
      const button = event.target && event.target.closest
        ? event.target.closest('[data-speak-toggle]')
        : null;
      if (!button) return;
      event.preventDefault();
      handleToggle(button);
    });

    // 离开页面时释放语音队列
    window.addEventListener('pagehide', stop);
  }

  window.SpeechPlayer = {
    isSupported: isSupported,
    speak: speak,
    stop: stop,
    toSpeakableText: toSpeakableText,
    splitIntoChunks: splitIntoChunks
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
