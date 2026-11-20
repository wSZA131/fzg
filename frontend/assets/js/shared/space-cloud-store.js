(function () {
  const SPACE_SYNC_KEY = 'fangzhigong_space_sync';

  function getApiBase() {
    if (window.ApiUtils && typeof window.ApiUtils.getApiBase === 'function') {
      return window.ApiUtils.getApiBase();
    }
    return '';
  }

  function parseResponse(response) {
    if (window.ApiUtils && typeof window.ApiUtils.parseApiResponse === 'function') {
      return window.ApiUtils.parseApiResponse(response);
    }
    return response.json();
  }

  function withSuggestion(prefix, error, suggestion) {
    if (window.ApiUtils && typeof window.ApiUtils.withSuggestion === 'function') {
      return window.ApiUtils.withSuggestion(prefix, error, suggestion);
    }
    const reason = error && error.message ? error.message : '未知错误';
    return `${prefix}：${reason}。建议：${suggestion || '请稍后重试'}`;
  }

  function esc(text) {
    return String(text || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function normalizeNumber(value, fallback) {
    const num = Number(value);
    return Number.isFinite(num) ? num : fallback;
  }

  function broadcastSpaceChange(detail) {
    const payload = {
      time: Date.now(),
      ...(detail && typeof detail === 'object' ? detail : {})
    };

    try {
      window.localStorage.setItem(SPACE_SYNC_KEY, JSON.stringify(payload));
    } catch (error) {
      // 忽略只读存储等异常，继续派发同标签页事件。
    }

    try {
      window.dispatchEvent(new CustomEvent('spaces:changed', { detail: payload }));
    } catch (error) {
      // 忽略不支持 CustomEvent 的边界场景。
    }

    return payload;
  }

  function normalizeKnowledgePoints(points) {
    if (!Array.isArray(points)) return [];
    return points.map(function (point) {
      if (typeof point === 'string') {
        const text = point.trim();
        return text ? { title: text, detail: text, weight: 0.3 } : null;
      }
      if (!point || typeof point !== 'object') return null;
      const title = String(point.title || point.name || '').trim();
      const detail = String(point.detail || point.content || title).trim();
      if (!title && !detail) return null;
      return {
        title: title || detail.slice(0, 20),
        detail: detail || title,
        weight: normalizeNumber(point.weight, 0.3)
      };
    }).filter(Boolean);
  }

  function normalizeItem(item) {
    if (!item || typeof item !== 'object') return null;
    const itemId = String(item.id || '').trim();
    if (!itemId) return null;
    const knowledgePoints = normalizeKnowledgePoints(item.knowledgePoints || item.knowledge_points);
    const topics = Array.isArray(item.topics)
      ? item.topics.map(function (topic) { return String(topic || '').trim(); }).filter(Boolean)
      : [];
    return {
      id: itemId,
      name: String(item.name || '未命名文件'),
      kind: String(item.kind || 'document'),
      mime: String(item.mime || ''),
      size: Math.max(0, normalizeNumber(item.size, 0)),
      source: String(item.source || ''),
      content: String(item.content || ''),
      summary: String(item.summary || ''),
      topics: topics,
      knowledgePoints: knowledgePoints,
      knowledgePointCount: knowledgePoints.length,
      textExtractMethod: String(item.textExtractMethod || item.text_extract_method || ''),
      textChunkCount: Math.max(0, normalizeNumber(item.textChunkCount || item.text_chunk_count, 0)),
      retrievalReady: !!item.retrievalReady,
      addedAt: normalizeNumber(item.addedAt || item.added_at, Date.now()),
      updatedAt: normalizeNumber(item.updatedAt || item.updated_at || item.addedAt || item.added_at, Date.now()),
      previewUrl: String(item.previewUrl || item.preview_url || ''),
      previewAvailable: !!(item.previewAvailable || item.preview_available || item.previewUrl || item.preview_url || item.content)
    };
  }

  function normalizeSpace(space) {
    if (!space || typeof space !== 'object') return null;
    const spaceId = String(space.id || '').trim();
    if (!spaceId) return null;
    return {
      id: spaceId,
      name: String(space.name || '新空间'),
      description: String(space.description || ''),
      createdAt: normalizeNumber(space.createdAt || space.created_at, Date.now()),
      updatedAt: normalizeNumber(space.updatedAt || space.updated_at || space.createdAt || space.created_at, Date.now()),
      itemCount: Math.max(0, normalizeNumber(space.itemCount || space.item_count, 0)),
      items: Array.isArray(space.items) ? space.items.map(normalizeItem).filter(Boolean) : []
    };
  }

  async function request(path, options) {
    const response = await fetch(`${getApiBase()}${path}`, options || {});
    return parseResponse(response);
  }

  function buildJsonRequestOptions(method, payload) {
    return {
      method: method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {})
    };
  }

  function shouldRetryWithPost(error) {
    const status = Number(error && error.status);
    return status === 405 || status === 501;
  }

  async function requestWithUpdateFallback(path, payload) {
    try {
      return await request(path, buildJsonRequestOptions('PUT', payload));
    } catch (error) {
      if (!shouldRetryWithPost(error)) {
        throw error;
      }
      return request(path, buildJsonRequestOptions('POST', payload));
    }
  }

  async function listSpaces(userId) {
    const data = await request(`/api/spaces?user_id=${encodeURIComponent(userId)}`);
    return {
      spaces: Array.isArray(data.spaces) ? data.spaces.map(normalizeSpace).filter(Boolean) : [],
      activeEntrySpaceId: String(data.activeEntrySpaceId || data.active_entry_space_id || ''),
      storage: data.storage || {}
    };
  }

  async function createSpace(userId, name) {
    const data = await request('/api/spaces', buildJsonRequestOptions('POST', {
      user_id: userId,
      name: String(name || '')
    }));
    const result = {
      data,
      space: normalizeSpace(data.space)
    };
    broadcastSpaceChange({
      action: 'create_space',
      userId: String(userId || '').trim(),
      spaceId: result.space ? result.space.id : ''
    });
    return result;
  }

  async function updateSpace(userId, spaceId, payload) {
    const data = await requestWithUpdateFallback(`/api/spaces/${encodeURIComponent(spaceId)}`, {
      user_id: userId,
      ...(payload || {})
    });
    const result = {
      data,
      space: normalizeSpace(data.space)
    };
    broadcastSpaceChange({
      action: 'update_space',
      userId: String(userId || '').trim(),
      spaceId: result.space ? result.space.id : String(spaceId || '').trim()
    });
    return result;
  }

  async function deleteSpace(userId, spaceId) {
    const result = await request(`/api/spaces/${encodeURIComponent(spaceId)}?user_id=${encodeURIComponent(userId)}`, {
      method: 'DELETE'
    });
    broadcastSpaceChange({
      action: 'delete_space',
      userId: String(userId || '').trim(),
      spaceId: String(spaceId || '').trim()
    });
    return result;
  }

  async function addItems(userId, spaceId, items) {
    const data = await request(`/api/spaces/${encodeURIComponent(spaceId)}/items`, buildJsonRequestOptions('POST', {
      user_id: userId,
      items: Array.isArray(items) ? items : []
    }));
    const result = {
      data,
      space: normalizeSpace(data.space),
      items: Array.isArray(data.items) ? data.items.map(normalizeItem).filter(Boolean) : []
    };
    broadcastSpaceChange({
      action: 'add_items',
      userId: String(userId || '').trim(),
      spaceId: result.space ? result.space.id : String(spaceId || '').trim()
    });
    return result;
  }

  async function getItem(userId, itemId) {
    const data = await request(`/api/spaces/items/${encodeURIComponent(itemId)}?user_id=${encodeURIComponent(userId)}`);
    return {
      data,
      item: normalizeItem(data.item),
      space: normalizeSpace(data.space)
    };
  }

  async function updateItem(userId, itemId, payload) {
    const data = await requestWithUpdateFallback(`/api/spaces/items/${encodeURIComponent(itemId)}`, {
      user_id: userId,
      ...(payload || {})
    });
    const result = {
      data,
      item: normalizeItem(data.item),
      space: normalizeSpace(data.space),
      sourceSpace: normalizeSpace(data.sourceSpace || data.source_space)
    };
    broadcastSpaceChange({
      action: 'update_item',
      userId: String(userId || '').trim(),
      itemId: String(itemId || '').trim(),
      spaceId: result.space ? result.space.id : '',
      sourceSpaceId: result.sourceSpace ? result.sourceSpace.id : ''
    });
    return result;
  }

  async function moveItem(userId, itemId, targetSpaceId) {
    return updateItem(userId, itemId, {
      targetSpaceId: String(targetSpaceId || '').trim()
    });
  }

  async function deleteItem(userId, itemId) {
    const data = await request(`/api/spaces/items/${encodeURIComponent(itemId)}?user_id=${encodeURIComponent(userId)}`, {
      method: 'DELETE'
    });
    const result = {
      data,
      deleted: !!data.deleted,
      itemId: String(data.itemId || data.item_id || ''),
      spaceId: String(data.spaceId || data.space_id || ''),
      space: normalizeSpace(data.space)
    };
    broadcastSpaceChange({
      action: 'delete_item',
      userId: String(userId || '').trim(),
      itemId: result.itemId || String(itemId || '').trim(),
      spaceId: result.spaceId || (result.space ? result.space.id : '')
    });
    return result;
  }

  function getItemSnippet(item, limit) {
    const maxLen = Math.max(12, Number(limit || 56));
    const raw = String((item && (item.content || item.summary)) || '').replace(/\s+/g, ' ').trim();
    if (!raw) return '点击即可直接预览分析';
    return raw.length > maxLen ? `${raw.slice(0, maxLen)}...` : raw;
  }

  function buildItemPreviewHtml(item) {
    if (!item || typeof item !== 'object') return '';

    const mime = String(item.mime || '').toLowerCase();
    const type = String(item.kind || 'document').toLowerCase();
    const previewUrl = String(item.previewUrl || '').trim();

    if ((type === 'audio' || mime.startsWith('audio/')) && previewUrl) {
      return `<audio controls src="${esc(previewUrl)}"></audio>`;
    }
    if ((type === 'video' || mime.startsWith('video/')) && previewUrl) {
      return `<video controls src="${esc(previewUrl)}"></video>`;
    }
    if (mime.startsWith('image/') && previewUrl) {
      return `<img alt="预览" src="${esc(previewUrl)}">`;
    }
    if ((type === 'pdf' || mime.includes('pdf')) && previewUrl) {
      return `<iframe title="PDF预览" src="${esc(previewUrl)}"></iframe>`;
    }
    if (item.content) {
      return `<pre>${esc(item.content)}</pre>`;
    }
    if (previewUrl) {
      return `<iframe title="文件预览" src="${esc(previewUrl)}"></iframe>`;
    }
    return '';
  }

  async function searchItems(userId, query, limit) {
    const keyword = String(query || '').trim();
    if (!keyword) return { query: '', count: 0, results: [] };

    const params = new URLSearchParams({
      user_id: String(userId || ''),
      q: keyword,
      limit: String(limit || 20)
    });
    const data = await request(`/api/spaces/search?${params.toString()}`);
    return {
      query: String(data.query || keyword),
      count: Number(data.count || 0),
      results: Array.isArray(data.results)
        ? data.results.filter(function (row) { return row && row.item_id; })
        : []
    };
  }

  window.SpaceCloudStore = {
    withSuggestion,
    broadcastSpaceChange,
    normalizeItem,
    normalizeSpace,
    listSpaces,
    createSpace,
    updateSpace,
    deleteSpace,
    addItems,
    getItem,
    updateItem,
    moveItem,
    deleteItem,
    searchItems,
    getItemSnippet,
    buildItemPreviewHtml
  };
})();
