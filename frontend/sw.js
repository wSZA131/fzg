/*
 * 坊知工 Service Worker
 *
 * 目标只有一个：让弱网/断网时演示不白屏。因此只缓存静态资源，
 * 业务数据一律走网络（/api/ 请求完全绕过，避免读到过期数据）。
 *
 * 策略：
 *   - 页面导航      network-first，失败回落 offline.html
 *   - 同源静态资源  stale-while-revalidate
 *   - CDN 静态资源  stale-while-revalidate（仅白名单域名）
 *   - 其余         直接放行
 */

const CACHE_NAME = 'fzg-static-v1';
const OFFLINE_URL = 'offline.html';
const PRECACHE_URLS = [
  OFFLINE_URL,
  'manifest.webmanifest',
  'assets/images/app-icon.svg'
];

// 只接管已知的静态资源域名，其余跨域请求原样放行。
const CDN_HOSTS = [
  'cdn.jsdelivr.net',
  'fastly.jsdelivr.net',
  'fonts.googleapis.com',
  'fonts.gstatic.com'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.addAll(PRECACHE_URLS))
      .catch(() => undefined)
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)))
      )
      .then(() => self.clients.claim())
  );
});

function isSameOriginStatic(url) {
  return url.origin === self.location.origin && !url.pathname.startsWith('/api/');
}

function isCdnStatic(url) {
  return CDN_HOSTS.includes(url.hostname);
}

async function cacheFirst(request) {
  const cache = await caches.open(CACHE_NAME);
  const cached = await cache.match(request);
  if (cached) return cached;

  const response = await fetch(request);
  if (response && response.ok) {
    cache.put(request, response.clone()).catch(() => undefined);
  }
  return response;
}

// 先返回缓存保证秒开，同时在后台刷新，下次访问即为最新。
async function staleWhileRevalidate(request) {
  const cache = await caches.open(CACHE_NAME);
  const cached = await cache.match(request);

  const network = fetch(request)
    .then((response) => {
      if (response && response.ok) {
        cache.put(request, response.clone()).catch(() => undefined);
      }
      return response;
    })
    .catch(() => null);

  if (cached) return cached;

  const response = await network;
  if (response) return response;
  throw new Error('offline and not cached');
}

async function networkFirstNavigation(request) {
  try {
    // no-cache 而非 no-store：强制校验服务端版本，命中 304 时仍省流量。
    const response = await fetch(request, { cache: 'no-cache' });
    if (response && response.ok) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, response.clone()).catch(() => undefined);
    }
    return response;
  } catch (error) {
    const cache = await caches.open(CACHE_NAME);
    const cached = await cache.match(request);
    if (cached) return cached;
    const offline = await cache.match(OFFLINE_URL);
    if (offline) return offline;
    throw error;
  }
}

self.addEventListener('fetch', (event) => {
  const request = event.request;

  if (request.method !== 'GET') return;

  let url;
  try {
    url = new URL(request.url);
  } catch (error) {
    return;
  }

  if (url.protocol !== 'http:' && url.protocol !== 'https:') return;

  // Range 请求（音视频拖动）交给浏览器直连，避免缓存不完整分片。
  if (request.headers.get('range')) return;

  if (request.mode === 'navigate') {
    event.respondWith(networkFirstNavigation(request));
    return;
  }

  if (isSameOriginStatic(url) || isCdnStatic(url)) {
    const useCacheFirst = url.pathname.includes('/assets/images/');
    event.respondWith(
      (useCacheFirst ? cacheFirst(request) : staleWhileRevalidate(request)).catch(
        () => fetch(request)
      )
    );
  }
});
