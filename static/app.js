// AI News — 前端交互：主题切换 + 卡片放大详情
(function () {
  // ── 主题 ──
  var saved = null;
  try { saved = localStorage.getItem('ai-news-theme'); } catch (e) {}
  if (saved) document.documentElement.setAttribute('data-theme', saved);
  else if (window.matchMedia('(prefers-color-scheme: dark)').matches)
    document.documentElement.setAttribute('data-theme', 'dark');

  function syncThemeButton() {
    var btn = document.querySelector('.theme-toggle');
    if (btn) btn.textContent = document.documentElement.getAttribute('data-theme') === 'dark' ? '☀' : '🌙';
  }

  window.toggleTheme = function () {
    var next = document.documentElement.getAttribute('data-theme') === 'dark' ? '' : 'dark';
    if (next) document.documentElement.setAttribute('data-theme', next);
    else document.documentElement.removeAttribute('data-theme');
    try { localStorage.setItem('ai-news-theme', next); } catch (e) {}
    syncThemeButton();
  };

  // ── 数据 ──
  var DATA = { items: {}, sections: {} };
  var ICONS = { star: '★', diamond: '◆', building: '■', globe: '●', 'message-circle': '○', flame: '🔥' };
  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function safeUrl(u) { return /^https?:\/\//i.test(u || '') ? u : ''; }

  // 用 DOM API 构建节点，所有文本走 textContent，避免采集内容注入 HTML
  function h(tag, attrs, children) {
    var el = document.createElement(tag);
    if (attrs) for (var k in attrs) {
      var v = attrs[k];
      if (v === null || v === undefined || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k === 'text') el.textContent = v;
      else el.setAttribute(k, v);
    }
    (children || []).forEach(function (c) {
      if (c === null || c === undefined || c === false) return;
      el.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    });
    return el;
  }

  function band(score) { return score >= 85 ? 'a' : score >= 70 ? 'b' : score >= 50 ? 'c' : 'd'; }
  function scoreBadge(score) { return score ? h('span', { class: 'score-badge band-' + band(score), text: String(score) }) : null; }
  function extLink(url, label, cls) {
    var href = safeUrl(url);
    return href ? h('a', { class: cls, href: href, target: '_blank', rel: 'noopener noreferrer' }, [label]) : null;
  }
  function fmtTime(iso) {
    var d = new Date(iso);
    if (isNaN(d)) return '';
    return d.toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
  }

  var META_LABELS = { stars: 'Stars', language: '语言', authors: '作者', upvotes: '点赞', points: '热度', categories: '分类' };

  // ── 视图：条目详情 ──
  function renderItem(item) {
    var metaBits = [
      item.tier ? h('span', { class: 'tier-badge tier-' + item.tier.toLowerCase().replace('.', ''), text: item.tier }) : null,
      item.source ? h('span', { class: 'nc-source', text: item.source }) : null,
      item.section ? h('span', { class: 'nc-section', text: item.section }) : null,
      item.published_at ? h('time', { class: 'nc-time', datetime: item.published_at, title: fmtTime(item.published_at), text: item.published_ago || fmtTime(item.published_at) }) : null,
      h('span', { class: 'nc-spacer' }),
      item.selected ? h('span', { class: 'pick-badge', text: '精选' }) : null,
      scoreBadge(item.score),
    ];

    var href = safeUrl(item.url);
    var title = href
      ? h('a', { class: 'detail-title-link', href: href, target: '_blank', rel: 'noopener noreferrer' }, [item.title, h('span', { class: 'ext', text: '↗' })])
      : h('span', null, [item.title]);

    var body = [
      h('div', { class: 'nc-meta' }, metaBits),
      h('h2', { class: 'detail-title', id: 'modalTitle' }, [title]),
    ];
    if (item.title_original && item.title_original !== item.title)
      body.push(h('p', { class: 'detail-original-title', text: item.title_original }));
    if (item.detail) body.push(h('p', { class: 'detail-summary', text: item.detail }));
    if (item.detail_original && item.detail_original !== item.detail)
      body.push(h('div', { class: 'detail-block' }, [h('div', { class: 'detail-label', text: '原文摘要' }), h('p', { class: 'detail-excerpt', text: item.detail_original })]));

    var meta = item.meta || {};
    var facts = Object.keys(meta).filter(function (k) { return meta[k]; });
    if (facts.length) {
      body.push(h('dl', { class: 'detail-facts' }, facts.reduce(function (acc, k) {
        acc.push(h('dt', { text: META_LABELS[k] || k }), h('dd', { text: String(meta[k]) }));
        return acc;
      }, [])));
    }
    if (item.tags && item.tags.length)
      body.push(h('div', { class: 'detail-tags' }, item.tags.map(function (t) { return h('span', { class: 'tag', text: t }); })));

    if (item.related && item.related.length) {
      body.push(h('div', { class: 'detail-block' }, [
        h('div', { class: 'detail-label', text: '其他报道 · ' + item.related.length }),
        h('ul', { class: 'detail-related' }, item.related.map(function (r) {
          var link = extLink(r.url, r.title, 'related-link') || h('span', { text: r.title });
          return h('li', null, [link, h('span', { class: 'related-src', text: r.source || r.section })]);
        })),
      ]));
    }

    var actions = [];
    if (href) actions.push(extLink(href, '阅读原文 ↗', 'btn btn-primary'));
    (item.links || []).forEach(function (l) { var a = extLink(l.url, l.label + ' ↗', 'btn'); if (a) actions.push(a); });
    if (href && navigator.clipboard) {
      var copy = h('button', { class: 'btn', type: 'button', text: '复制链接' });
      copy.addEventListener('click', function () {
        navigator.clipboard.writeText(href).then(function () { copy.textContent = '已复制'; });
      });
      actions.push(copy);
    }
    if (actions.length) body.push(h('div', { class: 'detail-actions' }, actions));
    if (!href) body.push(h('p', { class: 'detail-note', text: '该条目来自旧版快照，未保存原文链接。' }));

    return { kicker: item.section || '详情', icon: ICONS[item.icon] || '', accent: item.accent, body: body };
  }

  // ── 视图：板块全部条目 ──
  function renderSection(key) {
    var sec = DATA.sections[key];
    if (!sec) return null;
    var list = sec.ids.map(function (id) {
      var item = DATA.items[id];
      if (!item) return null;
      var href = safeUrl(item.url);
      return h('article', { class: 'news-card compact', 'data-open-item': id, tabindex: '0' }, [
        h('div', { class: 'nc-meta' }, [
          item.tier ? h('span', { class: 'tier-badge tier-' + item.tier.toLowerCase().replace('.', ''), text: item.tier }) : null,
          item.source ? h('span', { class: 'nc-source', text: item.source }) : null,
          item.published_ago ? h('span', { class: 'nc-time', text: item.published_ago }) : null,
          h('span', { class: 'nc-spacer' }),
          item.selected ? h('span', { class: 'pick-badge', text: '精选' }) : null,
          scoreBadge(item.score),
        ]),
        h('h3', { class: 'nc-title' }, [href
          ? h('a', { class: 'nc-title-link', href: href, target: '_blank', rel: 'noopener noreferrer' }, [item.title, h('span', { class: 'ext', text: '↗' })])
          : h('span', null, [item.title])]),
        item.detail ? h('p', { class: 'nc-detail', text: item.detail }) : null,
      ]);
    });
    return {
      kicker: sec.label + ' · ' + sec.ids.length + ' 条',
      icon: ICONS[sec.icon] || '●',
      accent: sec.accent,
      body: [h('div', { class: 'modal-list' }, list)],
    };
  }

  // ── 弹窗 ──
  var modal, panel, bodyEl, kickerEl, iconEl, backBtn;
  var stack = [];       // 视图栈：[{type, key}]，支持“板块 → 条目 → 返回”
  var originEl = null;  // 打开时的来源卡片，用于放大 / 缩回动画
  var lastFocus = null;

  function show(view) {
    var v = view.type === 'item' ? (DATA.items[view.key] ? renderItem(DATA.items[view.key]) : null) : renderSection(view.key);
    if (!v) return false;
    kickerEl.textContent = v.kicker;
    iconEl.textContent = v.icon || '';
    panel.className = 'modal' + (v.accent ? ' accent-' + v.accent : '');
    bodyEl.replaceChildren.apply(bodyEl, v.body);
    bodyEl.scrollTop = 0;
    backBtn.hidden = stack.length < 2;
    if (view.type === 'item') history.replaceState(null, '', '#item=' + view.key);
    else history.replaceState(null, '', location.pathname + location.search);
    return true;
  }

  // FLIP：从来源卡片的位置和尺寸放大到弹窗
  function zoom(from, reverse) {
    if (reduceMotion || !from || !from.isConnected) {
      return panel.animate([{ opacity: reverse ? 1 : 0 }, { opacity: reverse ? 0 : 1 }], { duration: 160, easing: 'ease-out' }).finished;
    }
    var a = from.getBoundingClientRect(), b = panel.getBoundingClientRect();
    if (!a.width || !b.width) return Promise.resolve();
    var dx = (a.left + a.width / 2) - (b.left + b.width / 2);
    var dy = (a.top + a.height / 2) - (b.top + b.height / 2);
    var start = 'translate(' + dx + 'px,' + dy + 'px) scale(' + (a.width / b.width) + ',' + (a.height / b.height) + ')';
    var frames = [{ transform: start, opacity: 0.4 }, { transform: 'none', opacity: 1 }];
    if (reverse) frames.reverse();
    return panel.animate(frames, { duration: reverse ? 220 : 340, easing: 'cubic-bezier(.2,.8,.2,1)' }).finished;
  }

  function open(view, from) {
    var opening = modal.hidden;
    if (opening) { stack = []; originEl = from || null; lastFocus = document.activeElement; }
    stack.push(view);
    if (!show(view)) { stack.pop(); return; }
    if (opening) {
      modal.hidden = false;
      document.body.classList.add('modal-open');
      modal.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 200 });
      zoom(originEl, false);
      panel.querySelector('.modal-close').focus({ preventScroll: true });
    }
  }

  function back() {
    if (stack.length < 2) return close();
    stack.pop();
    show(stack[stack.length - 1]);
  }

  function close() {
    if (modal.hidden) return;
    modal.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 200 });
    zoom(originEl, true).then(finish, finish);
    function finish() {
      modal.hidden = true;
      document.body.classList.remove('modal-open');
      history.replaceState(null, '', location.pathname + location.search);
      if (lastFocus && lastFocus.focus) lastFocus.focus({ preventScroll: true });
      stack = [];
    }
  }

  function trigger(target) {
    if (target.closest('a')) return null; // 链接（标题 / ↗）直接跳原文，不拦截
    var itemEl = target.closest('[data-open-item]');
    if (itemEl) return { view: { type: 'item', key: itemEl.getAttribute('data-open-item') }, el: itemEl };
    var secEl = target.closest('[data-open-section]');
    if (secEl) return { view: { type: 'section', key: secEl.getAttribute('data-open-section') }, el: secEl };
    return null;
  }

  document.addEventListener('DOMContentLoaded', function () {
    syncThemeButton();

    var dataEl = document.getElementById('news-data');
    try { if (dataEl) DATA = Object.assign(DATA, JSON.parse(dataEl.textContent || '{}')); } catch (e) {}

    modal = document.getElementById('detailModal');
    if (!modal) return;
    panel = modal.querySelector('.modal');
    bodyEl = document.getElementById('modalBody');
    kickerEl = document.getElementById('modalKicker');
    iconEl = document.getElementById('modalIcon');
    backBtn = modal.querySelector('.modal-back');

    modal.querySelector('.modal-close').addEventListener('click', close);
    backBtn.addEventListener('click', back);
    modal.addEventListener('click', function (e) { if (e.target === modal) close(); });

    // 页面与弹窗内的卡片都走同一个委托
    document.addEventListener('click', function (e) {
      var t = trigger(e.target);
      if (!t) return;
      // 卡片里选中文字时不触发
      if (String(window.getSelection && window.getSelection()).length > 0) return;
      e.preventDefault();
      open(t.view, modal.hidden ? t.el : null);
    });

    document.addEventListener('keydown', function (e) {
      if (!modal.hidden && e.key === 'Escape') { e.preventDefault(); stack.length > 1 ? back() : close(); return; }
      if ((e.key === 'Enter' || e.key === ' ') && e.target.matches && e.target.matches('[data-open-item],[data-open-section]')) {
        var t = trigger(e.target);
        if (t) { e.preventDefault(); open(t.view, modal.hidden ? t.el : null); }
      }
    });

    // 深链接：/#item=<id>
    var m = location.hash.match(/^#item=([\w-]+)/);
    if (m && DATA.items[m[1]]) open({ type: 'item', key: m[1] }, document.querySelector('[data-open-item="' + m[1] + '"]'));
  });
})();
