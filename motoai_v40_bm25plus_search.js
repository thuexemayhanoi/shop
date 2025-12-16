/* motoai_v40_bm25plus_search.js
   ✅ BASE: MotoAI v39 (UI Premium, NLU, Dialog, Auto-Price)
   ✅ UPGRADE: Search Engine replaces BM25 with BM25+ (Adaptive Delta, Synonym, Phrase Boost)
*/
(function(){
  if (window.MotoAI_v40_LOADED) return;
  window.MotoAI_v40_LOADED = true;

  /* ====== CONFIG ====== */
  const DEF = {
    brand: "Mr Tú",
    phone: "0816659199",
    zalo:  "",
    map:   "",
    avatar: "👩‍💼",
    themeColor: "#007AFF",

    autolearn: true,
    viOnly: true,
    deepContext: true,
    maxContextTurns: 8,

    extraSites: [location.origin],
    crawlDepth: 1,
    refreshHours: 24,
    maxPagesPerDomain: 80,
    maxTotalPages: 300,

    fetchTimeoutMs: 10000,
    fetchPauseMs: 160,
    disableQuickMap: false,

    smart: {
      semanticSearch: true,
      extractiveQA:   true,
      autoPriceLearn: true,
      searchThreshold: 1.2
    },
    debug: true,
    noLinksInReply: true,
    noMarkdownReply: true
  };
  const ORG = (window.MotoAI_CONFIG||{});
  if(!ORG.zalo && (ORG.phone||DEF.phone)) ORG.zalo = 'https://zalo.me/' + String(ORG.phone||DEF.phone).replace(/\s+/g,'');
  const CFG = Object.assign({}, DEF, ORG);
  CFG.smart = Object.assign({}, DEF.smart, (ORG.smart||{}));

  /* ====== HELPERS ====== */
  const $  = s => document.querySelector(s);
  const safe = s => { try{ return JSON.parse(s); }catch{ return null; } };
  const sleep = ms => new Promise(r=>setTimeout(r,ms));
  const nowSec = ()=> Math.floor(Date.now()/1000);
  const pick = a => a[Math.floor(Math.random()*a.length)];
  const nfVND = n => (n||0).toLocaleString('vi-VN');
  const clamp = (n,min,max)=> Math.max(min, Math.min(max,n));
  const sameHost = (u, origin)=> { try{ return new URL(u).host.replace(/^www\./,'') === new URL(origin).host.replace(/^www\./,''); }catch{ return false; } };

  function naturalize(t){
    if(!t) return t;
    let s = " "+t+" ";
    s = s.replace(/\s+ạ([.!?,\s]|$)/gi, "$1")
         .replace(/\s+nhé([.!?,\s]|$)/gi, "$1")
         .replace(/\s+nha([.!?,\s]|$)/gi, "$1");
    s = s.replace(/\s{2,}/g," ").trim();
    if(!/[.!?]$/.test(s)) s+=".";
    return s.replace(/\.\./g,".");
  }
  function looksVN(s){
    if(/[ăâêôơưđà-ỹ]/i.test(s)) return true;
    const hits = (s.match(/\b(xe|thuê|giá|liên hệ|hà nội|cọc|giấy tờ)\b/gi)||[]).length;
    return hits >= 2;
  }
  function escapeHtml(s){
    return String(s||'')
      .replace(/&/g,'&amp;')
      .replace(/</g,'&lt;')
      .replace(/>/g,'&gt;')
      .replace(/"/g,'&quot;')
      .replace(/'/g,'&#39;');
  }
  const BRANDS = ['honda','yamaha','suzuki','piaggio','vinfast','sym','kymco'];
  function stripBrands(text){
    return String(text||'')
      .replace(new RegExp(`\\b(${BRANDS.join('|')})\\b`, 'ig'), '')
      .replace(/\s{2,}/g,' ')
      .trim();
  }
  function sanitizeReply(s){
    let out = String(s||'');
    if(CFG.noLinksInReply){
      out = out.replace(/\bhttps?:\/\/\S+/gi,'').replace(/\bwww\.\S+/gi,'');
    }
    if(CFG.noMarkdownReply){
      out = out.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '$1').replace(/[*_`~>]+/g, '');
    }
    return out.trim();
  }

  /* ====== STORAGE KEYS ====== */
  const K = {
    sess:  "MotoAI_v39_session",
    ctx:   "MotoAI_v39_ctx",
    learn: "MotoAI_v39_learn",
    autoprices: "MotoAI_v39_auto_prices",
    stamp: "MotoAI_v39_learnStamp",
    clean: "MotoAI_v39_lastClean"
  };

  /* ====== UI PREMIUM (Glassmorphism + iOS) ====== */
  const CSS = `
  :root{
    --mta-z: 2147483647;
    --m-primary: ${CFG.themeColor};
    --m-bg: #ffffff;
    --m-bg-sec: #f2f2f7;
    --m-text: #1c1c1e;
    --m-shadow: 0 8px 32px rgba(0, 0, 0, 0.12);
    --m-font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    --m-in-h: 44px;
    --m-in-fs: 16px;
  }
  #mta-root{
    position:fixed; right:20px; bottom:calc(20px + env(safe-area-inset-bottom, 0));
    z-index:var(--mta-z); font-family:var(--m-font);
    pointer-events:none;
  }
  #mta-root > * { pointer-events:auto; }
  #mta-bubble{
    width:60px; height:60px; border:none; border-radius:30px;
    background: linear-gradient(135deg, var(--m-primary), #00C6FF);
    box-shadow: 0 4px 14px rgba(0, 122, 255, 0.4);
    display:flex; align-items:center; justify-content:center;
    cursor:pointer; color:#fff; font-size:28px;
    transition: transform 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
  }
  #mta-bubble:active { transform: scale(0.9); }
  #mta-backdrop{
    position:fixed; inset:0; background:rgba(0,0,0,0.3);
    backdrop-filter: blur(2px); -webkit-backdrop-filter: blur(2px);
    opacity:0; pointer-events:none; transition:opacity 0.3s ease;
  }
  #mta-backdrop.show{ opacity:1; pointer-events:auto; }
  #mta-card{
    position:fixed; right:20px; bottom:20px;
    width:min(400px, calc(100% - 40px)); height:75vh; max-height:720px;
    background: var(--m-bg); border-radius:24px; box-shadow: var(--m-shadow);
    display:flex; flex-direction:column; overflow:hidden;
    opacity: 0; transform: translateY(20px) scale(0.95); pointer-events: none;
    transition: transform 0.5s cubic-bezier(0.19, 1, 0.22, 1), opacity 0.3s ease;
    transform-origin: bottom right;
  }
  #mta-card.open{ opacity: 1; transform: translateY(0) scale(1); pointer-events: auto; }
  #mta-header{
    background: rgba(255, 255, 255, 0.85);
    backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
    border-bottom: 1px solid rgba(0,0,0,0.05);
    position: absolute; top:0; left:0; right:0; z-index: 10;
  }
  #mta-header .bar{ display:flex; align-items:center; gap:12px; padding:12px 16px; }
  #mta-header .avatar{
    width:36px; height:36px; border-radius:50%;
    background: linear-gradient(135deg, #e0e0e0, #ffffff);
    display:flex; align-items:center; justify-content:center; font-size:18px;
  }
  #mta-header .info{ flex:1; display:flex; flex-direction:column; }
  #mta-header .name{ font-weight:600; font-size:15px; color:var(--m-text); }
  #mta-header .status{ font-size:12px; color:#34C759; display:flex; align-items:center; gap:4px; font-weight:500; }
  #mta-header .actions{ display:flex; gap:8px; }
  #mta-header .act{
    width:32px; height:32px; border-radius:50%;
    background: rgba(0,0,0,0.04);
    display:flex; align-items:center; justify-content:center;
    color: var(--m-primary); text-decoration:none; font-size:16px;
    transition: background 0.2s;
  }
  #mta-header .act:hover{ background: rgba(0,0,0,0.08); }
  #mta-close{
    background:none; border:none; color:#8e8e93; font-size:24px;
    cursor:pointer; margin-left:4px; padding:0 4px;
  }
  #mta-body{
    flex:1; overflow-y:auto;
    background: var(--m-bg-sec);
    padding: 70px 12px 12px;
    scroll-behavior: smooth;
    -webkit-overflow-scrolling: touch;
    overscroll-behavior: contain;
  }
  .m-msg{
    max-width:80%; margin:6px 0; padding:10px 14px;
    border-radius:18px; line-height:1.45; word-break:break-word; font-size:15px;
    position: relative; animation: msgPop 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
  }
  @keyframes msgPop {
    from{ opacity:0; transform:translateY(10px) scale(0.95); }
    to{ opacity:1; transform:translateY(0) scale(1); }
  }
  .m-msg.bot{
    background: #fff; color: var(--m-text);
    border-bottom-left-radius: 4px;
    box-shadow: 0 1px 2px rgba(0,0,0,0.04);
  }
  .m-msg.user{
    background: var(--m-primary); color: #fff;
    margin-left: auto; border-bottom-right-radius: 4px;
    box-shadow: 0 2px 8px rgba(0, 122, 255, 0.25);
  }
  #mta-typing{
    margin:6px 0; padding:8px 12px; background:#fff;
    border-radius:18px; display:inline-block;
    border-bottom-left-radius:4px;
    box-shadow:0 1px 2px rgba(0,0,0,0.04);
  }
  .dot-flashing {
    position: relative; width: 6px; height: 6px; border-radius: 5px;
    background-color: #9880ff; color: #9880ff;
    animation: dot-flashing 1s infinite linear alternate; animation-delay: 0.5s;
    display:inline-block; margin: 0 8px;
  }
  .dot-flashing::before, .dot-flashing::after {
    content: ""; display: inline-block; position: absolute; top: 0;
    width: 6px; height: 6px; border-radius: 5px;
    background-color: #9880ff; color: #9880ff;
    animation: dot-flashing 1s infinite alternate;
  }
  .dot-flashing::before { left: -10px; animation-delay: 0s; }
  .dot-flashing::after { left: 10px; animation-delay: 1s; }
  @keyframes dot-flashing {
    0% { background-color: #9880ff; }
    50%, 100% { background-color: rgba(152, 128, 255, 0.2); }
  }
  #mta-tags{
    background: rgba(255,255,255,0.9); backdrop-filter: blur(10px);
    border-top:1px solid rgba(0,0,0,0.05);
    transition: max-height 0.25s ease, opacity 0.2s ease;
  }
  #mta-tags.hidden{ max-height:0 !important; opacity:0; pointer-events:none; }
  #mta-tags .track{
    display:flex; overflow-x:auto; padding:8px 12px; gap:8px;
    scrollbar-width:none;
  }
  #mta-tags .track::-webkit-scrollbar { display:none; }
  #mta-tags button{
    flex:0 0 auto; background:#fff; border:1px solid #d1d1d6;
    border-radius:16px; padding:6px 12px; font-size:13px;
    color:var(--m-text); cursor:pointer; transition:all 0.2s; font-weight:500;
  }
  #mta-tags button:active{ background:#e5e5ea; transform:scale(0.96); }
  #mta-input{
    background: rgba(255,255,255,0.95);
    padding: 8px 12px calc(8px + env(safe-area-inset-bottom, 0));
    display:flex; gap:10px; align-items:center;
    border-top: 1px solid rgba(0,0,0,0.06);
  }
  #mta-in{
    flex:1; height:var(--m-in-h); border:1px solid #d1d1d6; border-radius:22px;
    padding:0 16px; font-size:var(--m-in-fs); background:#fff; color:var(--m-text);
    outline:none; -webkit-appearance:none; transition: border-color 0.2s;
  }
  #mta-in:focus{ border-color:var(--m-primary); }
  #mta-send{
    width:40px; height:40px; border:none; border-radius:50%;
    background:var(--m-primary); color:#fff;
    display:flex; align-items:center; justify-content:center;
    cursor:pointer; font-size:18px;
    box-shadow:0 2px 6px rgba(0,122,255,0.3);
    transition: transform 0.2s;
  }
  #mta-send:active{ transform:scale(0.9); }
  @media(prefers-color-scheme:dark){
    :root{ --m-bg: #1c1c1e; --m-bg-sec: #000000; --m-text: #ffffff; --m-shadow: 0 8px 32px rgba(0, 0, 0, 0.4); }
    #mta-header{ background: rgba(28, 28, 30, 0.85); border-bottom:1px solid rgba(255,255,255,0.1); }
    #mta-header .name{ color:#fff; }
    #mta-header .act{ background:rgba(255,255,255,0.1); color:#fff; }
    .m-msg.bot{ background:#2c2c2e; color:#fff; }
    #mta-input{ background:#1c1c1e; border-top:1px solid rgba(255,255,255,0.1); }
    #mta-in{ background:#2c2c2e; border-color:#3a3a3c; color:#fff; }
    #mta-tags{ background:rgba(28,28,30,0.9); border-top:1px solid rgba(255,255,255,0.1); }
    #mta-tags button{ background:#2c2c2e; border-color:#3a3a3c; color:#fff; }
    #mta-typing{ background:#2c2c2e; }
  }
  @media(max-width:480px){
    #mta-card{
      right:0; left:0; bottom:0; width:100%; height:100%; max-height:none;
      border-radius:0; border-top-left-radius:20px; border-top-right-radius:20px;
    }
  }`;

  const HTML = `
  <div id="mta-root" aria-live="polite">
    <button id="mta-bubble" aria-label="Chat">💬</button>
    <div id="mta-backdrop"></div>
    <section id="mta-card" role="dialog" aria-hidden="true">
      <header id="mta-header">
        <div class="bar">
          <div class="avatar">${CFG.avatar}</div>
          <div class="info">
            <div class="name">${CFG.brand}</div>
            <div class="status">● Trực tuyến</div>
          </div>
          <div class="actions">
            ${CFG.phone?`<a class="act" href="tel:${CFG.phone}">📞</a>`:""}
            ${CFG.zalo?`<a class="act" href="${CFG.zalo}" target="_blank">Z</a>`:""}
            ${CFG.map?`<a class="act q-map" href="${CFG.map}" target="_blank">📍</a>`:""}
          </div>
          <button id="mta-close">✕</button>
        </div>
      </header>
      <main id="mta-body"></main>
      <div id="mta-tags">
        <div class="track" id="mta-tag-track">
          <button data-q="Giá thuê xe máy">💰 Giá thuê</button>
          <button data-q="Thuê xe ga">🛵 Xe ga</button>
          <button data-q="Thuê xe số">🏍 Xe số</button>
          <button data-q="Thuê theo tháng">📆 Theo tháng</button>
          <button data-q="Thủ tục">📄 Thủ tục</button>
          <button data-q="Đặt cọc">💳 Đặt cọc</button>
        </div>
      </div>
      <footer id="mta-input">
        <input id="mta-in" placeholder="Nhắn tin..." autocomplete="off" enterkeyhint="send"/>
        <button id="mta-send">➤</button>
      </footer>
    </section>
  </div>`;

  /* ====== SESSION & CONTEXT ====== */
  const MAX_MSG = 12;
  function getSess(){ const arr = safe(localStorage.getItem(K.sess))||[]; return Array.isArray(arr)?arr:[]; }
  function saveSess(a){ try{ localStorage.setItem(K.sess, JSON.stringify(a.slice(-MAX_MSG))); }catch{} }
  function addMsg(role, text){
    if(!text) return;
    const body = $("#mta-body"); if(!body) return;
    const el = document.createElement("div");
    el.className = "m-msg " + (role==="user" ? "user" : "bot");
    el.innerHTML = escapeHtml(text).replace(/\n/g,"<br>");
    body.appendChild(el);
    body.scrollTop = body.scrollHeight;

    const arr = getSess();
    arr.push({role, text, t: Date.now()});
    saveSess(arr);
  }
  function renderSess(){
    const body=$("#mta-body"); body.innerHTML="";
    const arr=getSess();
    if(arr.length) arr.forEach(m=> addMsg(m.role,m.text));
    else addMsg("bot", naturalize(`Xin chào, em là hỗ trợ viên của ${CFG.brand}. Anh/chị cần thuê xe gì ạ?`));
  }
  function getCtx(){ return safe(localStorage.getItem(K.ctx)) || {turns:[]}; }
  function pushCtx(delta){
    try{
      const ctx=getCtx();
      if(delta && delta.name) ctx.name = delta.name;
      ctx.turns.push(Object.assign({t:Date.now()}, delta||{}));
      ctx.turns = ctx.turns.slice(-clamp(CFG.maxContextTurns||8,3,10));
      localStorage.setItem(K.ctx, JSON.stringify(ctx));
    }catch{}
  }

  /* ====== NLU & ENTITIES ====== */
  const TYPE_MAP = [
    {k:'air blade', re:/\bair\s*blade\b|airblade|\bab\b/i,    canon:'air blade'},
    {k:'vision',    re:/\bvision\b/i,                         canon:'vision'},
    {k:'wave',      re:/\bwave\b/i,                           canon:'wave'},
    {k:'sirius',    re:/\bsirius\b/i,                         canon:'sirius'},
    {k:'blade',     re:/\bblade\b/i,                          canon:'blade'},
    {k:'jupiter',   re:/\bjupiter\b/i,                        canon:'jupiter'},
    {k:'lead',      re:/\blead\b/i,                           canon:'lead'},
    {k:'liberty',   re:/\bliberty\b/i,                        canon:'liberty'},
    {k:'vespa',     re:/\bvespa\b/i,                          canon:'vespa'},
    {k:'grande',    re:/\bgrande\b/i,                         canon:'grande'},
    {k:'janus',     re:/\bjanus\b/i,                          canon:'janus'},
    {k:'sh',        re:/\bsh\b/i,                             canon:'sh'},
    {k:'xe côn tay',re:/côn\s*tay|tay\s*côn|exciter|winner|raider|cb150|cbf190|w175|msx/i, canon:'xe côn tay'},
    {k:'50cc',      re:/\b50\s*cc\b|\b50cc\b/i,               canon:'50cc'},
    {k:'xe điện',   re:/xe\s*điện|vinfast|yadea|dibao|gogo|klara/i, canon:'xe điện'},
    {k:'xe ga',     re:/\bxe\s*ga\b/i,                        canon:'xe ga'},
    {k:'xe số',     re:/\bxe\s*số\b/i,                        canon:'xe số'}
  ];
  function detectType(t){
    const raw = String(t||'');
    const nobrand = stripBrands(raw);
    for(const it of TYPE_MAP){ if(it.re.test(nobrand)) return it.canon; }
    for(const it of TYPE_MAP){ if(it.re.test(raw)) return it.canon; }
    return null;
  }
  function detectQty(t){
    const m=(t||"").match(/(\d+)\s*(ngày|day|tuần|tuan|week|tháng|thang|month)?/i);
    if(!m) return null;
    const n=parseInt(m[1],10); if(!n) return null;
    let unit="ngày";
    if(m[2]){
      if(/tuần|tuan|week/i.test(m[2])) unit="tuần";
      else if(/tháng|thang|month/i.test(m[2])) unit="tháng";
    }
    return {n,unit};
  }
  function detectArea(t){
    const s = (t||"").toLowerCase();
    if(/phố cổ|phoco|old quarter/.test(s)) return 'Phố Cổ';
    if(/hoàn kiếm|hoan kiem/.test(s)) return 'Hoàn Kiếm';
    if(/long biên|long bien/.test(s)) return 'Long Biên';
    if(/tây hồ|tay ho/.test(s)) return 'Tây Hồ';
    return null;
  }
  function detectName(t){
    const m = (t||"").match(/\b(tên|name|là)\s+(em|mình|tớ|anh|chị)?\s*([A-ZÀ-Ỹ][a-zà-ỹ]+(\s[A-ZÀ-Ỹ][a-zà-ỹ]+)*)/);
    if(m && m[3]) return m[3];
    return null;
  }
  // Intent scoring
  function detectIntent(t){
    const text = (t||"").toLowerCase();
    const rules = {
      needPrice:   [/giá\b/,/bao nhiêu/,/thuê\b/,/\brent\b/,/tính tiền/,/cost/,/price/],
      needDocs:    [/thủ tục/,/giấy tờ/,/cccd/,/passport/,/hộ chiếu/],
      needContact: [/liên hệ/,/\bzalo\b/,/gọi/,/hotline/,/\bsđt\b/,/\bsdt\b/,/phone/],
      needDelivery:[/giao/,/ship/,/tận nơi/,/đưa xe/,/mang xe/,/địa điểm/,/địa chỉ/],
      needReturn:  [/trả xe/,/gia hạn/,/đổi xe/,/kết thúc thuê/],
      needPolicy:  [/điều kiện/,/chính sách/,/bảo hiểm/,/hư hỏng/,/sự cố/,/đặt cọc/,/\bcọc\b/]
    };
    const scores = {};
    for(const k in rules){
      scores[k] = rules[k].reduce((sum,re)=> sum + (re.test(text) ? 1 : 0), 0);
    }
    return scores;
  }

  /* ====== PRICE TABLE ====== */
  const PRICE_TABLE = {
    'xe số':      { day:[150000],          week:[600000,700000], month:[850000,1200000] },
    'xe ga':      { day:[150000,200000],   week:[600000,1000000], month:[1100000,2000000] },
    'air blade':  { day:[200000],          week:[800000], month:[1600000,1800000] },
    'vision':     { day:[200000],          week:[700000,850000], month:[1400000,1900000] },
    'xe điện':    { day:[170000],          week:[800000], month:[1600000] },
    '50cc':       { day:[200000],          week:[800000], month:[1700000] },
    'xe côn tay': { day:[300000],          week:[1200000], month:null }
  };
  ['wave','sirius','blade','jupiter'].forEach(k=> PRICE_TABLE[k] = PRICE_TABLE[k]||PRICE_TABLE['xe số']);
  ['lead','liberty','vespa','grande','janus'].forEach(k=> PRICE_TABLE[k] = PRICE_TABLE[k]||PRICE_TABLE['xe ga']);
  PRICE_TABLE['sh'] = { day:[450000], week:[1800000], month:[4500000] };

  function modelFamily(model){
    const m = (model||'').toLowerCase();
    if(['vision','air blade','lead','liberty','vespa','grande','janus','sh'].includes(m)) return 'xe ga';
    if(['wave','sirius','blade','jupiter','future','dream'].includes(m)) return 'xe số';
    return null;
  }
  function baseForModel(model, unit){
    if(!model) return null;
    const key = unit==="tuần"?"week":(unit==="tháng"?"month":"day");
    const entry = PRICE_TABLE[model] || PRICE_TABLE[modelFamily(model)];
    if(entry && entry[key]) return (Array.isArray(entry[key])?entry[key][0]:entry[key]);
    return null;
  }

  function composePrice(model, qty){
    // Overview: chỉ có model
    if(model && !qty){
      const m = PRICE_TABLE[model] || PRICE_TABLE[modelFamily(model)] || PRICE_TABLE['xe số'];
      if(!m) return naturalize(`Giá ${model} bên em linh động, anh/chị nhắn Zalo ${CFG.phone} để em báo chi tiết.`);
      const day = Array.isArray(m.day)?m.day[0]:m.day;
      const week = m.week ? (Array.isArray(m.week)?m.week[0]:m.week) : null;
      const month= m.month? (Array.isArray(m.month)?m.month[0]:m.month): null;
      let parts = [];
      if(day)   parts.push(`ngày khoảng ${nfVND(day)}đ`);
      if(week)  parts.push(`tuần từ ${nfVND(week)}đ`);
      if(month) parts.push(`tháng từ ${nfVND(month)}đ`);
      return naturalize(`Giá thuê ${model} ${parts.join(", ")}. Anh/chị thuê mấy ngày ạ?`);
    }

    if(!model && !qty) return naturalize(`Anh/chị định thuê xe gì và trong bao lâu để em tính giá ạ?`);

    const unitLabel = qty ? (qty.unit==="tuần"?"tuần":(qty.unit==="tháng"?"tháng":"ngày")) : "ngày";
    const base = qty ? baseForModel(model||'xe số', qty.unit) : null;
    if(qty && !base){
      if(!model) return naturalize(`Anh/chị cho em xin mẫu xe (vision, air blade, wave...) để em tính giá chính xác.`);
      return naturalize(`Giá thuê ${model} theo ${qty.unit} cần check kho. Anh/chị nhắn Zalo ${CFG.phone} giúp em.`);
    }
    if(!qty){
      return naturalize(`Anh/chị định thuê ${model||'xe'} trong bao lâu (1–2 ngày, 1 tuần, 1 tháng...) để em tính giá tốt nhất.`);
    }

    const total = base * qty.n;
    let text;
    if(qty.n===1){
      text = `Giá thuê ${model||'xe'} 1 ${unitLabel} là khoảng ${nfVND(base)}đ.`;
    }else{
      text = `Tổng tiền thuê ${model||'xe'} ${qty.n} ${unitLabel} khoảng ${nfVND(total)}đ.`;
    }
    if(qty.unit==="ngày" && qty.n>=3 && qty.n<7) text += " Thuê tuần sẽ rẻ hơn đấy ạ.";
    return naturalize(`${text} Anh/chị chốt thì báo em giữ xe nhé.`);
  }

  /* ====== SEARCH & INDEX (BM25+ UPGRADED) ====== */
  function tk(s){ return (s||"").toLowerCase().normalize('NFC').replace(/[^\p{L}\p{N}\s]+/gu,' ').split(/\s+/).filter(Boolean); }
  function loadLearn(){ return safe(localStorage.getItem(K.learn)) || {}; }
  function saveLearn(o){ try{ localStorage.setItem(K.learn, JSON.stringify(o)); }catch{} }

  // 1. Synonym Map (Mở rộng từ khóa)
  const SEARCH_SYNONYMS = {
    "xe ga": ["vision", "lead", "air blade", "sh", "janus", "grande", "liberty"],
    "xe số": ["wave", "sirius", "blade", "jupiter", "future"],
    "xe điện": ["vinfast", "klara", "yadea", "evo"],
    "thủ tục": ["giấy tờ", "cccd", "passport", "hộ chiếu", "bằng lái"],
    "bảng giá": ["giá thuê", "giá xe", "bao nhiêu tiền", "chi phí"]
  };

  // 2. Score Helpers
  function scoreDocMeta(meta, query){
    let bonus = 0;
    const url = (meta.url||"").toLowerCase();
    const ti  = (meta.title||"").toLowerCase();
    const q   = (query||"").toLowerCase();
    if(/banggia|bảng giá|gia-thue|gia_xe/.test(url+ti) && /giá|thuê|tiền|price|cost/.test(q)) bonus += 2.0;
    if(/thutuc|thủ tục|thu-tuc/.test(url+ti) && /thủ tục|giấy tờ|cccd|passport|hộ chiếu/.test(q)) bonus += 2.0;
    if(/loaixe|dòng xe|loai-xe/.test(url+ti)) bonus += 0.5;
    return bonus;
  }

  function adaptiveDelta(dl, avgdl) {
    if (dl > avgdl * 1.4) return 1.4;   // bài rất dài
    if (dl > avgdl)       return 1.1;   // bài dài
    if (dl < avgdl * 0.6) return 0.6;   // bài ngắn
    return 0.9;
  }

  function phraseBoost(text, query) {
    if (!text || !query) return 0;
    const t = text.toLowerCase();
    const q = query.toLowerCase();
    if (t.includes(q)) return 1.8; // Khớp nguyên câu
    if (q.split(" ").every(w => t.includes(w))) return 0.6; // Khớp mọi từ
    return 0;
  }

  function synonymBoost(text, query) {
    let bonus = 0;
    const t = text.toLowerCase();
    const q = query.toLowerCase();
    for (const key in SEARCH_SYNONYMS) {
      if (q.includes(key)) {
        SEARCH_SYNONYMS[key].forEach(s => {
          if (t.includes(s)) bonus += 0.4;
        });
      }
    }
    return bonus;
  }

  function freshnessBoost(meta) {
    if (!meta || !meta.url) return 0;
    const ts = meta.ts || 0; // Nếu crawler lưu ts cho page, nếu không thì bỏ qua
    // Ở đây dùng mẹo: nếu url chứa ngày tháng năm hiện tại (dạng blog)
    // Hoặc giả lập đơn giản:
    return 0; // Tạm tắt nếu chưa có trường ts trong page struct
  }

  // 3. Main Search Function (BM25+)
  function searchIndex(query, k = 3) {
    const cache = loadLearn();
    const docs = [];

    Object.values(cache).forEach(site =>
      (site.pages || []).forEach(p =>
        docs.push({
          id: p.url,
          text: (p.title || '') + ' ' + (p.text || ''),
          meta: p
        })
      )
    );

    if (!docs.length) return [];

    /* BM25+ Params */
    const k1 = 1.5;
    const b  = 0.75;

    /* Stats */
    const df = new Map();
    const tf = new Map();
    let totalLen = 0;

    docs.forEach(d => {
      const toks = tk(d.text);
      totalLen += toks.length;

      const freq = new Map();
      toks.forEach(t => freq.set(t, (freq.get(t) || 0) + 1));
      tf.set(d.id, freq);

      new Set(toks).forEach(t =>
        df.set(t, (df.get(t) || 0) + 1)
      );
    });

    const avgdl = totalLen / Math.max(1, docs.length);
    const N = docs.length;
    const qToks = new Set(tk(query));

    /* Scoring */
    const scored = docs.map(d => {
      const freq = tf.get(d.id) || new Map();
      const dl = freq.size || 1; // dùng số từ độc nhất hoặc tổng số từ
      // Thực tế BM25 dùng tổng số từ (toks.length)
      const realDl = tk(d.text).length || 1; 
      
      let score = 0;
      const delta = adaptiveDelta(realDl, avgdl);

      qToks.forEach(term => {
        const f = freq.get(term) || 0;
        const c = df.get(term) || 0;
        if (!c) return;

        const idf = Math.log(1 + (N - c + 0.5) / (c + 0.5));
        
        // BM25+ Formula
        const norm = f + k1 * (1 - b + b * (realDl / avgdl));
        const bm25plus = (f * (k1 + 1)) / norm + delta;

        score += idf * bm25plus;
      });

      // Cộng các điểm boost bổ sung
      score += scoreDocMeta(d.meta, query);
      score += phraseBoost(d.text, query);
      score += synonymBoost(d.text, query);
      score += freshnessBoost(d.meta);

      return { score, meta: d.meta };
    });

    return scored
      .filter(x => x.score > (CFG.smart.searchThreshold || 1.0))
      .sort((a, b) => b.score - a.score)
      .slice(0, k)
      .map(x => x.meta);
  }

  function bestSentences(text, query, k=2){
    const sents = String(text||'').replace(/\s+/g,' ').split(/(?<=[\.\!\?])\s+/).slice(0,60);
    const qToks=new Set(tk(query));
    return sents
      .map(s=>({s, sc: tk(s).reduce((a,w)=>a + (qToks.has(w)?1:0),0)}))
      .filter(x=>x.sc>0)
      .sort((a,b)=>b.sc-a.sc)
      .slice(0,k)
      .map(x=>x.s);
  }

  /* ====== CRAWLER & AUTOPRICE (full như v39_1) ====== */
  async function fetchText(url){
    const ctl = new AbortController();
    const id = setTimeout(()=>ctl.abort(), CFG.fetchTimeoutMs);
    try{
      const res = await fetch(url, {signal:ctl.signal});
      clearTimeout(id);
      if(!res.ok) return null;
      return await res.text();
    }catch(e){
      clearTimeout(id);
      return null;
    }
  }
  function parseXML(t){ try{ return (new DOMParser()).parseFromString(t,'text/xml'); }catch{ return null; } }
  function parseHTML(t){ try{ return (new DOMParser()).parseFromString(t,'text/html'); }catch{ return null; } }

  function extractPricesFromText(txt){
    const clean = String(txt||'');
    const lines = clean
      .replace(/<script[\s\S]*?<\/script>/gi,' ')
      .replace(/<style[\s\S]*?<\/style>/gi,' ')
      .split(/[\n\.•\-–]|<br\s*\/?>/i);
    const out = [];
    const models = [
      {key:/\bair\s*blade\b|airblade|\bab\b/i,  type:'air blade'},
      {key:/\bvision\b/i,                       type:'vision'},
      {key:/\bwave\b/i,                         type:'wave'},
      {key:/\bsirius\b/i,                       type:'sirius'},
      {key:/\bblade\b/i,                        type:'blade'},
      {key:/\bjupiter\b/i,                      type:'jupiter'},
      {key:/\blead\b/i,                         type:'lead'},
      {key:/\bliberty\b/i,                      type:'liberty'},
      {key:/\bvespa\b/i,                        type:'vespa'},
      {key:/\bgrande\b/i,                       type:'grande'},
      {key:/\bjanus\b/i,                        type:'janus'},
      {key:/\bsh\b/i,                           type:'sh'},
      {key:/\b50\s*cc\b|\b50cc\b/i,             type:'50cc'},
      {key:/côn\s*tay|tay\s*côn|exciter|winner|raider|cb150|cbf190|w175|msx/i, type:'xe côn tay'},
      {key:/xe\s*điện|vinfast|yadea|dibao|gogo|klara/i, type:'xe điện'},
      {key:/\bxe\s*số\b/i,                      type:'xe số'},
      {key:/\bxe\s*ga\b/i,                      type:'xe ga'}
    ];
    const reNum = /(\d+(?:[.,]\d+)?)(?:\s*(k|tr|triệu|million))?|\b(\d{1,3}(?:[.,]\d{3})+)\b/i;
    function parseVND(line){
      const m = line.match(reNum); if(!m) return null;
      let val = 0;
      if(m[3]) val = parseInt(m[3].replace(/[^\d]/g,''),10);
      else{
        const num = parseFloat(String(m[1]||'0').replace(',','.'));
        const unit = (m[2]||'').toLowerCase();
        if(unit==='k') val = Math.round(num*1000);
        else if(unit==='tr' || unit==='triệu' || unit==='million') val = Math.round(num*1000000);
        else val = Math.round(num);
      }
      return val;
    }
    for(const raw of lines){
      const line = String(raw||'');
      const found = models.find(m=> m.key.test(line));
      if(!found) continue;
      if(/\b(tuần|week|tháng|month)\b/i.test(line)) continue;
      const price = parseVND(line);
      if(price && price>50000 && price<5000000){
        out.push({type:found.type, unit:'day', price});
      }
    }
    return out;
  }

  async function readSitemap(url){
    const xml = await fetchText(url); if(!xml) return [];
    const doc = parseXML(xml); if(!doc) return [];
    const items = Array.from(doc.getElementsByTagName('item'));
    if(items.length) return items.map(it=> it.getElementsByTagName('link')[0]?.textContent?.trim()).filter(Boolean);
    const sm = Array.from(doc.getElementsByTagName('sitemap')).map(x=> x.getElementsByTagName('loc')[0]?.textContent?.trim()).filter(Boolean);
    if(sm.length){
      const all=[]; 
      for(const loc of sm){
        try{
          const child = await readSitemap(loc);
          if(child && child.length) all.push(...child);
        }catch{}
      }
      return Array.from(new Set(all));
    }
    return Array.from(doc.getElementsByTagName('url')).map(u=> u.getElementsByTagName('loc')[0]?.textContent?.trim()).filter(Boolean);
  }

  async function fallbackCrawl(origin){
    const start = origin.endsWith('/')? origin : origin + '/';
    const html = await fetchText(start); if(!html) return [start];
    const doc = parseHTML(html); if(!doc) return [start];
    const links = Array.from(doc.querySelectorAll('a[href]')).map(a=> a.getAttribute('href')).filter(Boolean);
    const set = new Set([start]);
    for(const href of links){
      try{
        const u = new URL(href, start).toString().split('#')[0];
        if(sameHost(u, origin)) set.add(u);
        if(set.size>=40) break;
      }catch{}
    }
    return Array.from(set);
  }

  async function pullPages(urls, stats){
    const out=[]; stats.urlsSeen += urls.length;
    for(const u of urls.slice(0, CFG.maxPagesPerDomain)){
      const txt = await fetchText(u); if(!txt) continue;
      if (/\bname=(?:"|')robots(?:"|')[^>]*content=(?:"|')[^"']*noindex/i.test(txt)) continue;
      let title = (txt.match(/<title[^>]*>([^<]+)<\/title>/i)||[])[1]||"";
      let desc = (txt.match(/<meta[^>]+name=(?:"|')description(?:"|')[^>]+content=(?:"|')([\s\S]*?)(?:"|')/i)||[])[1]||"";
      if(!desc) desc = txt.replace(/<script[\s\S]*?<\/script>/gi,' ')
                          .replace(/<style[\s\S]*?<\/style>/gi,' ')
                          .replace(/<[^>]+>/g,' ')
                          .replace(/\s+/g,' ')
                          .trim()
                          .slice(0,600);
      if(CFG.viOnly && !looksVN(title+' '+desc)) continue;
      if(CFG.smart.autoPriceLearn){
        try{
          const autos = extractPricesFromText(txt);
          if(autos.length){
            const stash = safe(localStorage.getItem(K.autoprices))||[];
            stash.push(...autos.map(a=> Object.assign({url:u}, a)));
            localStorage.setItem(K.autoprices, JSON.stringify(stash.slice(-500)));
          }
        }catch{}
      }
      out.push({url:u, title, text:desc});
      await sleep(CFG.fetchPauseMs);
    }
    return out;
  }

  async function learnSites(origins, force){
    const list = Array.from(new Set(origins||[])).slice(0, 12);
    const cache = loadLearn(); const results = {}; let total=0;
    for(const origin of list){
      try{
        const key = new URL(origin).origin;
        if(!force && cache[key] && ((nowSec()-cache[key].ts)/3600)<CFG.refreshHours && cache[key].pages?.length){
          results[key]=cache[key]; total+=cache[key].pages.length; if(total>=CFG.maxTotalPages) break; continue;
        }
        let urls=[];
        const smc = [key+'/sitemap.xml', key+'/sitemap_index.xml'];
        for(const c of smc){
          try{
            const u=await readSitemap(c);
            if(u && u.length){ urls=u; break; }
          }catch{}
        }
        if(!urls.length) urls = await fallbackCrawl(key);
        const uniq = Array.from(new Set(
          urls
            .map(u=>{ try{ return new URL(u).toString().split('#')[0]; }catch{ return null; } })
            .filter(Boolean)
            .filter(u=> sameHost(u, key))
        ));
        const pages = await pullPages(uniq, {urlsSeen:0});
        if(pages.length){
          cache[key]={domain:key, ts:nowSec(), pages};
          try{ saveLearn(cache); }
          catch{
            const ks=Object.keys(cache); if(ks.length) delete cache[ks[0]];
            saveLearn(cache);
          }
          results[key]=cache[key]; total+=pages.length;
        }
        if(total >= CFG.maxTotalPages) break;
      }catch(e){}
    }
    localStorage.setItem(K.stamp, Date.now());
    return results;
  }

  function mergeAutoPrices(){
    if(!CFG.smart.autoPriceLearn) return;
    try{
      const autos = safe(localStorage.getItem(K.autoprices))||[];
      if(!autos.length) return;
      const byType = autos.reduce((m,a)=>{ (m[a.type]||(m[a.type]=[])).push(a.price); return m; },{});
      Object.keys(byType).forEach(t=>{
        const arr = byType[t].sort((a,b)=>a-b);
        const p50 = arr[Math.floor(arr.length*0.50)];
        if(PRICE_TABLE[t]) PRICE_TABLE[t].day = [p50];
        else PRICE_TABLE[t] = { day:[p50], week:null, month:null };
      });
    }catch{}
  }

  /* ====== ANSWER LOGIC (STATEFUL) ====== */
  const PREFIX = ["Chào anh/chị,","Dạ,","Em chào anh/chị,","Dạ vâng,"];
  function polite(s){ return naturalize(`${pick(PREFIX)} ${s}`); }

  async function deepAnswer(userText){
    const q = (userText||"").trim();
    const ctx = getCtx();

    const intents = detectIntent(q);
    const newModel = detectType(q);
    const newQty   = detectQty(q);
    const newName  = detectName(q);
    const area     = detectArea(q);

    if(newName){
      ctx.name = newName;
      try{ localStorage.setItem(K.ctx, JSON.stringify(ctx)); }catch{}
    }

    // Lấy model hiện tại từ context nếu user không nói lại
    let currentModel = newModel;
    if(!currentModel){
      for(let i=ctx.turns.length-1;i>=0;i--){
        if(ctx.turns[i].type){ currentModel = ctx.turns[i].type; break; }
      }
    }

    // Tìm lượt bot gần nhất có state
    let lastBotState = null;
    for(let i=ctx.turns.length-1;i>=0;i--){
      const t = ctx.turns[i];
      if(t.from === "bot" && t.state){
        lastBotState = t;
        break;
      }
    }

    // Xử lý trả lời cho câu hỏi treo (multi-step)
    if(lastBotState && lastBotState.state === "ASK_DURATION" && newQty){
      const modelUse = currentModel || lastBotState.type || null;
      const ans = composePrice(modelUse, newQty);
      pushCtx({from:"bot", raw:ans, state:null, type:modelUse, qty:newQty});
      return ans;
    }
    if(lastBotState && lastBotState.state === "ASK_MODEL" && newModel){
      const qtyUse = lastBotState.qty || newQty || null;
      const ans = composePrice(newModel, qtyUse);
      pushCtx({from:"bot", raw:ans, state:null, type:newModel, qty:qtyUse});
      return ans;
    }

    // Chọn intent mạnh nhất
    let topIntent = null, topScore = 0;
    Object.entries(intents).forEach(([k,v])=>{ if(v>topScore){ topScore=v; topIntent=k; } });
    const hasIntent = topScore > 0;

    // Greeting
    if(!hasIntent && /(chào|xin chào|hello|hi\b)/i.test(q)){
      const n = ctx.name ? ` ${ctx.name}` : "";
      const ans = polite(`em là AI của ${CFG.brand}. Anh/chị${n} cần thuê xe mẫu nào ạ?`);
      pushCtx({from:"bot", raw:ans, state:null});
      return ans;
    }

    // Hỏi giá (hoặc user gõ đủ model + qty dù không có từ "giá")
    if(topIntent === 'needPrice' || (currentModel && newQty)){
      const qtyUse = newQty || null;
      const ans = composePrice(currentModel, qtyUse);
      pushCtx({from:"bot", raw:ans, state:null, type:currentModel, qty:qtyUse});
      return ans;
    }

    // Liên hệ
    if(topIntent === 'needContact'){
      const ans = polite(`anh/chị cần hỗ trợ gấp vui lòng gọi ${CFG.phone} hoặc nhắn Zalo ${CFG.zalo||CFG.phone} ạ.`);
      pushCtx({from:"bot", raw:ans, state:null});
      return ans;
    }

    // Giao xe
    if(topIntent === 'needDelivery'){
      let ans;
      if(area){
        ans = polite(`bên em có thể giao xe ở khu vực ${area}. Anh/chị thuê mấy ngày và cần xe gì ạ?`);
      }else{
        ans = polite(`bên em giao xe tận nơi nội thành cho hợp đồng từ 3 ngày. Anh/chị đang ở khu vực nào (Phố Cổ, Hoàn Kiếm, Long Biên...)?`);
      }
      pushCtx({from:"bot", raw:ans, state:"ASK_DURATION", type:currentModel||null});
      return ans;
    }

    // Thủ tục / Policy
    if(topIntent === 'needDocs'){
      const ans = polite(`thủ tục đơn giản: cần CCCD gắn chip hoặc Passport + tiền cọc (2–3tr xe số, 3–5tr xe ga). Có giấy tờ đầy đủ có thể giảm cọc ạ.`);
      pushCtx({from:"bot", raw:ans, state:null});
      return ans;
    }
    if(topIntent === 'needPolicy'){
      const ans = polite(`đặt cọc: xe số khoảng 2–3tr, xe ga 3–5tr. Lỗi máy móc do xe bên em chịu, các phát sinh như xịt lốp, ngã xe thì khách phụ giúp chi phí ạ.`);
      pushCtx({from:"bot", raw:ans, state:null});
      return ans;
    }

    // SEARCH từ website
    try{
      const top = searchIndex(q, 3);
      if(top && top.length){
        if(CFG.smart.extractiveQA){
          const sn = bestSentences((top[0].title+'. ')+top[0].text, q, 2).join(' ');
          if(sn && sn.length>20){
            const ans = naturalize(sn);
            pushCtx({from:"bot", raw:ans, state:null});
            return ans;
          }
        }
        const ans = polite(((top[0].title?top[0].title+' — ':'')+top[0].text).slice(0,160)+'...');
        pushCtx({from:"bot", raw:ans, state:null});
        return ans;
      }
    }catch(e){}

    // Fallback thông minh với state
    if(currentModel && !newQty){
      const ans = polite(`anh/chị định thuê xe ${currentModel} trong bao lâu để em tính giá tốt nhất ạ?`);
      pushCtx({from:"bot", raw:ans, state:"ASK_DURATION", type:currentModel});
      return ans;
    }

    const ans = polite(`anh/chị đang quan tâm mẫu xe nào (Vision, Air Blade, Wave...) và dự định thuê mấy ngày ạ?`);
    pushCtx({from:"bot", raw:ans, state:"ASK_MODEL"});
    return ans;
  }

  /* ====== CONTROLLER & EVENTS ====== */
  let isOpen=false, sending=false, vvBound=false;

  function showTyping(){
    const body = $("#mta-body"); if(!body) return;
    if($("#mta-typing")) return;
    const box = document.createElement("div");
    box.id = "mta-typing";
    box.innerHTML = `<div class="dot-flashing"></div>`;
    body.appendChild(box);
    body.scrollTop = body.scrollHeight;
  }
  function hideTyping(){ const t=$("#mta-typing"); if(t) t.remove(); }

  async function sendUser(text){
    if(sending) return;
    const v=(text||"").trim(); if(!v) return;
    sending=true;
    addMsg("user", v);

    // Lưu turn user trước (để history có đủ raw), state sẽ xử lý bằng last bot state
    const t = detectType(v); const q = detectQty(v); const n = detectName(v);
    pushCtx({from:"user", raw:v, type:t, qty:q, name:n});

    const isMobile = window.innerWidth < 480;
    showTyping();
    await sleep((isMobile?800:1200) + Math.random()*500);

    const ans = await deepAnswer(v);
    hideTyping();
    addMsg("bot", sanitizeReply(ans));

    sending=false;
  }

  function openChat(){
    if(isOpen) return;
    $("#mta-card").classList.add("open");
    $("#mta-backdrop").classList.add("show");
    $("#mta-bubble").style.transform = "scale(0) rotate(90deg)";
    setTimeout(()=>$("#mta-bubble").style.display="none", 200);
    isOpen=true;
    renderSess();
    setTimeout(()=>{ const i=$("#mta-in"); if(i) i.focus(); }, 300);
    adjustForIOS();
  }

  function closeChat(){
    if(!isOpen) return;
    $("#mta-card").classList.remove("open");
    $("#mta-backdrop").classList.remove("show");
    $("#mta-bubble").style.display="flex";
    setTimeout(()=>$("#mta-bubble").style.transform="scale(1) rotate(0)", 10);
    isOpen=false; hideTyping();
    const card = $("#mta-card");
    if(card){ card.style.bottom="20px"; card.style.height="75vh"; }
  }

  function adjustForIOS(){
    if(!window.visualViewport) return;
    if(vvBound) return;
    const card = $("#mta-card");
    const view = window.visualViewport;

    function onResize(){
      if(!isOpen) return;
      if(view.height < window.innerHeight - 100){
        if(window.innerWidth <= 480){
          card.style.height = view.height + "px";
          card.style.bottom = "0px";
        } else {
          const offset = window.innerHeight - view.height;
          card.style.bottom = (offset + 10) + "px";
        }
        const body=$("#mta-body"); if(body) body.scrollTop=body.scrollHeight;
      } else {
        card.style.height = window.innerWidth <= 480 ? "100%" : "75vh";
        card.style.bottom = window.innerWidth <= 480 ? "0px" : "20px";
      }
    }

    view.addEventListener("resize", onResize);
    view.addEventListener("scroll", onResize);
    vvBound = true;
  }

  function bindEvents(){
    $("#mta-bubble").addEventListener("click", openChat);
    $("#mta-backdrop").addEventListener("click", closeChat);
    $("#mta-close").addEventListener("click", closeChat);
    $("#mta-send").addEventListener("click", ()=>{
      const inp=$("#mta-in"); const v=inp.value.trim(); if(!v) return; inp.value=""; sendUser(v);
    });
    $("#mta-in").addEventListener("keydown", e=>{
      if(e.key==="Enter" && !e.shiftKey){
        e.preventDefault();
        const v=e.target.value.trim(); if(!v) return;
        e.target.value=""; sendUser(v);
      }
      const tags=$("#mta-tags");
      if(tags){
        if(e.target.value.trim().length>0) tags.classList.add('hidden');
        else tags.classList.remove('hidden');
      }
    });
    const track = $("#mta-tag-track");
    if(track){
      track.querySelectorAll("button").forEach(btn=>{
        btn.addEventListener("click", ()=> sendUser(btn.dataset.q||btn.textContent));
      });
    }
  }

  function ready(fn){
    if(document.readyState==="complete"||document.readyState==="interactive") fn();
    else document.addEventListener("DOMContentLoaded", fn);
  }

  ready(async ()=>{
    const lastClean = parseInt(localStorage.getItem(K.clean)||0);
    if(!lastClean || (Date.now()-lastClean) > 7*24*3600*1000){
      localStorage.removeItem(K.ctx);
      localStorage.setItem(K.clean, Date.now());
    }

    const wrap=document.createElement("div"); wrap.innerHTML=HTML; document.body.appendChild(wrap.firstElementChild);
    const st=document.createElement("style"); st.textContent=CSS; document.head.appendChild(st);
    bindEvents(); adjustForIOS(); mergeAutoPrices();

    if(CFG.autolearn){
      const origins = Array.from(new Set([location.origin, ...(CFG.extraSites||[])]));
      const last = parseInt(localStorage.getItem(K.stamp)||0);
      if(!last || (Date.now()-last) >= CFG.refreshHours*3600*1000){
        await learnSites(origins, false);
      }
    }
  });

  window.MotoAI_v40 = {
    open: openChat,
    close: closeChat,
    send: sendUser,
    learnNow: async (sites, force)=> await learnSites(sites||[location.origin], !!force),
    clear: ()=> { localStorage.removeItem(K.learn); localStorage.removeItem(K.autoprices); localStorage.removeItem(K.ctx); }
  };
})();
