(function () {
  const DB_NAME = 'fangzhigong_attachment_handoff_v1';
  const STORE_NAME = 'handoffs';
  const MAX_AGE_MS = 2 * 60 * 60 * 1000;
  let dbPromise = null;

  function openDb() {
    if (dbPromise) return dbPromise;
    dbPromise = new Promise(function (resolve, reject) {
      if (!window.indexedDB) {
        reject(new Error('当前浏览器不支持附件传递'));
        return;
      }

      const request = window.indexedDB.open(DB_NAME, 1);
      request.onupgradeneeded = function () {
        const db = request.result;
        if (!db.objectStoreNames.contains(STORE_NAME)) {
          db.createObjectStore(STORE_NAME, { keyPath: 'id' });
        }
      };
      request.onsuccess = function () {
        resolve(request.result);
      };
      request.onerror = function () {
        reject(request.error || new Error('附件存储打开失败'));
      };
    });
    return dbPromise;
  }

  function putRecord(record) {
    return openDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        const tx = db.transaction(STORE_NAME, 'readwrite');
        tx.objectStore(STORE_NAME).put(record);
        tx.oncomplete = function () { resolve(record.id); };
        tx.onerror = function () { reject(tx.error || new Error('附件保存失败')); };
        tx.onabort = function () { reject(tx.error || new Error('附件保存已取消')); };
      });
    });
  }

  function getAndDelete(id) {
    return openDb().then(function (db) {
      return new Promise(function (resolve, reject) {
        const tx = db.transaction(STORE_NAME, 'readwrite');
        const store = tx.objectStore(STORE_NAME);
        const request = store.get(id);
        request.onsuccess = function () {
          const record = request.result;
          if (record) store.delete(id);
          resolve(record || null);
        };
        request.onerror = function () {
          reject(request.error || new Error('附件读取失败'));
        };
      });
    });
  }

  function cleanupOldRecords() {
    openDb().then(function (db) {
      const tx = db.transaction(STORE_NAME, 'readwrite');
      const store = tx.objectStore(STORE_NAME);
      const request = store.openCursor();
      const threshold = Date.now() - MAX_AGE_MS;
      request.onsuccess = function () {
        const cursor = request.result;
        if (!cursor) return;
        const record = cursor.value || {};
        if (Number(record.createdAt || 0) < threshold) {
          cursor.delete();
        }
        cursor.continue();
      };
    }).catch(function () {
      // 清理失败不影响本次附件传递。
    });
  }

  async function save(files, question) {
    const list = Array.from(files || []).filter(function (file) {
      return file instanceof Blob && Number(file.size) > 0;
    });
    if (!list.length) return '';

    const id = `handoff_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;
    const records = list.map(function (file) {
      return {
        name: String(file.name || '未命名文件'),
        type: String(file.type || ''),
        lastModified: Number(file.lastModified || Date.now()),
        blob: file
      };
    });

    await putRecord({
      id: id,
      question: String(question || ''),
      createdAt: Date.now(),
      files: records
    });
    cleanupOldRecords();
    return id;
  }

  async function consume(id) {
    if (!id) return null;
    const record = await getAndDelete(id);
    if (!record || !Array.isArray(record.files)) return null;

    const files = record.files.map(function (item) {
      const blob = item && item.blob;
      if (!blob) return null;
      const name = String(item.name || '未命名文件');
      const type = String(item.type || blob.type || '');
      const lastModified = Number(item.lastModified || Date.now());
      try {
        return new File([blob], name, { type: type, lastModified: lastModified });
      } catch (error) {
        return blob;
      }
    }).filter(Boolean);

    return {
      question: String(record.question || ''),
      files: files
    };
  }

  window.AttachmentHandoff = {
    save: save,
    consume: consume,
    isSupported: !!window.indexedDB
  };
})();
