/* motoai_v39_1_premium_ios_nomarkdown.js
   ✅ UPDATE: UI/UX Premium (Glassmorphism), Animation mượt (Spring physics)
   ✅ FIX: iOS Keyboard overlap (One-time bind), Auto-zoom, Safe-area
   ✅ FIX: Storage Quota Safe, DOM Null Safety, QuickCall Auto-Avoid
   ✅ LOGIC: Giữ nguyên v38.1 (BM25 + Extractive QA + Auto-Price Learn)
   ✅ TÙY BIẾN: KHÔNG Markdown, KHÔNG Link, Ưu tiên Model
*/
(function(){
  if (window.MotoAI_v39_LOADED) return;
  window.MotoAI_v39_LOADED = true;

  /* ====== CONFIG ====== */
  const DEF = {
    brand: "Nguyen Tu",
    phone: "0942467674",
    zalo:  "",
    map:   "",
    avatar: "👩‍💼",
    themeColor: "#007AFF", // Màu xanh chuẩn iOS

    autolearn: true,
    viOnly: true,
    deepContext: true,
    maxContextTurns: 5,

    extraSites: [location.origin],
    crawlDepth: 1,
    refreshHours: 24,
    maxPagesPerDomain: 80,
    maxTotalPages: 300,

    fetchTimeoutMs: 10000,
    fetchPauseMs: 160,
    disableQuickMap: false,

    // Smart flags
    smart: {
      semanticSearch: true,   // BM25
      extractiveQA:   true,   // chích câu “đinh”
      autoPriceLearn: true    // trích giá từ HTML
    },

    // Debug / profiling
    debug: true,

    // Tùy biến theo yêu cầu
    noLinksInReply: true,         // KHÔNG chèn link trong câu trả lời bot
    noMarkdownReply: true,        // KHÔNG dùng markdown trong câu trả lời bot
    preferModelOverFamily: true   // ƯU TIÊN model (vision, wave...) hơn family (xe ga/xe số)
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
    s = s.replace(/\s+ạ([.!?,\s]|$)/gi, "$1").replace(/\s+nhé([.!?,\s]|$)/gi, "$1").replace(/\s+nha([.!?,\s]|$)/gi, "$1");
    s = s.replace(/\s{2,}/g," ").trim(); if(!/[.!?]$/.test(s)) s+="."; return s.replace(/\.\./g,".");
  }
  function looksVN(s){
    if(/[ăâêôơưđà-ỹ]/i.test(s)) return true;
    const hits = (s.match(/\b(xe|thuê|giá|liên hệ|hà nội|cọc|giấy tờ)\b/gi)||[]).length;
    return hits >= 2;
  }

  // Loại bỏ thương hiệu khỏi chuỗi để nhận model chính xác
  const BRANDS = ['honda','yamaha','suzuki','piaggio','vinfast','sym','kymco'];
  function stripBrands(text){
    return String(text||'')
      .replace(new RegExp(`\\b(${BRANDS.join('|')})\\b`, 'ig'), '')
      .replace(/\s{2,}/g,' ')
      .trim();
  }

  // Chuẩn hoá câu trả lời: bỏ markdown/link
  function sanitizeReply(s){
    let out = String(s||'');
    if(CFG.noLinksInReply){
      out = out.replace(/\bhttps?:\/\/\S+/gi,'').replace(/\bwww\.\S+/gi,'');
    }
    if(CFG.noMarkdownReply){
      out = out
        .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '$1') // [txt](url) -> txt
        .replace(/[*_`~>]+/g, '');                 // markdown symbols
    }
    return out.trim();
  }

  /* ====== STORAGE KEYS & SAFE SAVE ====== */
  const K = {
    sess:  "MotoAI_v39_session",
    ctx:   "MotoAI_v39_ctx",
    learn: "MotoAI_v39_learn",
    autoprices: "MotoAI_v39_auto_prices",
    stamp: "MotoAI_v39_learnStamp",
    clean: "MotoAI_v39_lastClean",
    dbg:   "MotoAI_v39_debug_stats"
  };

  // Safe storage with quota handling
  function safeSetItem(key, valStr) {
    try {
      localStorage.setItem(key, valStr);
    } catch(e) {
      if(e.name === 'QuotaExceededError' || e.name === 'NS_ERROR_DOM_QUOTA_REACHED') {
        // Fallback: Thử xóa cache cũ nhất (Learn data)
        try {
          const cache = safe(localStorage.getItem(K.learn)) || {};
          const keys = Object.keys(cache);
          if (keys.length > 0) {
             delete cache[keys[0]]; // Xóa domain đầu tiên
             localStorage.setItem(K.learn, JSON.stringify(cache));
             // Thử lưu lại
             localStorage.setItem(key, valStr);
          } else {
             // Nếu vẫn không được, thử xóa session cũ
             localStorage.removeItem(K.sess);
             localStorage.setItem(key, valStr);
          }
        } catch(e2) {} // Give up silently
      }
    }
  }

  /* ====== UI PREMIUM (Glassmorphism + iOS Fixes) ====== */
  const CSS = `
  :root{
    --mta-z: 2147483647;
    --m-primary: ${CFG.themeColor};
    --m-bg: #ffffff;
    --m-bg-sec: #f2f2f7; /* iOS secondary bg */
    --m-text: #1c1c1e;
    --m-shadow: 0 8px 32px rgba(0, 0, 0, 0.12);
    --m-font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    
    /* Input sizing fix */
    --m-in-h: 44px;         
    --m-in-fs: 16px; /* 16px to prevent iOS zoom */
  }

  #mta-root{
    position:fixed; right:20px; bottom:calc(20px + env(safe-area-inset-bottom, 0));
    z-index:var(--mta-z); font-family:var(--m-font);
    pointer-events:none; /* Để click xuyên qua vùng trống */
    transition: all 0.3s ease;
  }
  #mta-root > * { pointer-events:auto; }

  /* Nút Chat Bubble - Hiệu ứng Pulse nhẹ */
  #mta-bubble{
    width:60px; height:60px; border:none; border-radius:30px;
    background: linear-gradient(135deg, var(--m-primary), #00C6FF);
    box-shadow: 0 4px 14px rgba(0, 122, 255, 0.4);
    display:flex; align-items:center; justify-content:center;
    cursor:pointer; color:#fff; font-size:28px;
    transition: transform 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
  }
  #mta-bubble:active { transform: scale(0.9); }

  /* Backdrop mờ */
  #mta-backdrop{
    position:fixed; inset:0; background:rgba(0,0,0,0.3);
    backdrop-filter: blur(2px); -webkit-backdrop-filter: blur(2px);
    opacity:0; pointer-events:none; transition:opacity 0.3s ease;
  }
  #mta-backdrop.show{ opacity:1; pointer-events:auto; }

  /* Card Chat - Glassmorphism & Spring Animation */
  #mta-card{
    position:fixed; right:20px; bottom:20px;
    width:min(400px, calc(100% - 40px));
    height:75vh; max-height:720px;
    background: var(--m-bg);
    border-radius:24px;
    box-shadow: var(--m-shadow);
    display:flex; flex-direction:column; overflow:hidden;
    
    /* Animation state: Hidden */
    opacity: 0;
    transform: translateY(20px) scale(0.95);
    pointer-events: none;
    transition: 
      transform 0.5s cubic-bezier(0.19, 1, 0.22, 1),
      opacity 0.3s ease;
    
    /* iOS fix bottom keyboard */
    transform-origin: bottom right;
  }
  #mta-card.open{
    opacity: 1;
    transform: translateY(0) scale(1);
    pointer-events: auto;
  }

  /* Header trong suốt mờ (Blur) */
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
    box-shadow: 0 2px 5px rgba(0,0,0,0.05);
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

  /* Body Content */
  #mta-body{
    flex:1; overflow-y:auto; 
    background: var(--m-bg-sec);
    padding: 70px 12px 12px; /* Top padding bù cho header absolute */
    scroll-behavior: smooth;
    -webkit-overflow-scrolling: touch;
    overscroll-behavior: contain;
  }
  
  /* Tin nhắn - Bubble Style */
  .m-msg{
    max-width:80%; margin:6px 0; padding:10px 14px;
    border-radius:18px; line-height:1.45; word-break:break-word; font-size:15px;
    position: relative; animation: msgPop 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
  }
  @keyframes msgPop { from{ opacity:0; transform:translateY(10px) scale(0.95); } to{ opacity:1; transform:translateY(0) scale(1); } }

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

  /* Typing Indicator */
  #mta-typing{ margin:6px 0; padding:8px 12px; background:#fff; border-radius:18px; display:inline-block; border-bottom-left-radius:4px; box-shadow:0 1px 2px rgba(0,0,0,0.04); }
  .dot-flashing {
    position: relative; width: 6px; height: 6px; border-radius: 5px; background-color: #9880ff; color: #9880ff;
    animation: dot-flashing 1s infinite linear alternate; animation-delay: 0.5s;
    display:inline-block; margin: 0 8px;
  }
  .dot-flashing::before, .dot-flashing::after {
    content: ""; display: inline-block; position: absolute; top: 0;
    width: 6px; height: 6px; border-radius: 5px; background-color: #9880ff; color: #9880ff;
    animation: dot-flashing 1s infinite alternate;
  }
  .dot-flashing::before { left: -10px; animation-delay: 0s; }
  .dot-flashing::after { left: 10px; animation-delay: 1s; }
  @keyframes dot-flashing { 0% { background-color: #9880ff; } 50%, 100% { background-color: rgba(152, 128, 255, 0.2); } }

  /* Suggestion Tags */
  #mta-tags{
    background: rgba(255,255,255,0.9); backdrop-filter: blur(10px);
    border-top:1px solid rgba(0,0,0,0.05);
    transition: max-height 0.25s ease, opacity 0.2s ease;
  }
  #mta-tags.hidden{ max-height:0 !important; opacity:0; pointer-events:none; }
  #mta-tags .track{ display:flex; overflow-x:auto; padding:8px 12px; gap:8px; scrollbar-width:none; }
  #mta-tags .track::-webkit-scrollbar { display:none; }
  #mta-tags button{
    flex:0 0 auto; background:#fff; border:1px solid #d1d1d6;
    border-radius:16px; padding:6px 12px; font-size:13px; color:var(--m-text);
    cursor:pointer; transition:all 0.2s; font-weight:500;
  }
  #mta-tags button:active{ background:#e5e5ea; transform:scale(0.96); }

  /* Input Area */
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
    cursor:pointer; font-size:18px; box-shadow:0 2px 6px rgba(0,122,255,0.3);
    transition: transform 0.2s;
  }
  #mta-send:active{ transform:scale(0.9); }

  /* Dark Mode Auto Support */
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

  /* Mobile Fullscreen Logic */
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

  /* ====== SESSION / CONTEXT ====== */
  const MAX_MSG = 10;
  function getSess(){ const arr = safe(localStorage.getItem(K.sess))||[]; return Array.isArray(arr)?arr:[]; }
  function saveSess(a){ safeSetItem(K.sess, JSON.stringify(a.slice(-MAX_MSG))); }
  function addMsg(role,text){
    if(!text) return;
    const body=$("#mta-body"); if(!body) return;
    const el=document.createElement("div"); el.className="m-msg "+(role==="user"?"user":"bot"); el.innerHTML=text.replace(/\n/g,"<br>");
    body.appendChild(el); body.scrollTop=body.scrollHeight;
    const arr=getSess(); arr.push({role,text,t:Date.now()}); saveSess(arr);
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
      const ctx=getCtx(); ctx.turns.push(Object.assign({t:Date.now()}, delta||{}));
      ctx.turns = ctx.turns.slice(-clamp(CFG.maxContextTurns||5,3,8));
      safeSetItem(K.ctx, JSON.stringify(ctx));
    }catch{}
  }

  /* ====== NLP ENGINE (Giữ nguyên logic v38) ====== */
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
    if(!m) return null; const n=parseInt(m[1],10); if(!n) return null;
    let unit="ngày"; if(m[2]){ if(/tuần|tuan|week/i.test(m[2])) unit="tuần"; else if(/tháng|thang|month/i.test(m[2])) unit="tháng"; }
    return {n,unit};
  }
  function detectIntent(t){
    return {
      needPrice:   /(giá|bao nhiêu|thuê|tính tiền|cost|price)/i.test(t),
      needDocs:    /(thủ tục|giấy tờ|cccd|passport|hộ chiếu)/i.test(t),
      needContact: /(liên hệ|zalo|gọi|hotline|sđt|sdt|phone)/i.test(t),
      needDelivery:/(giao|ship|tận nơi|đưa xe|mang xe)/i.test(t),
      needReturn:  /(trả xe|gia hạn|đổi xe|kết thúc thuê)/i.test(t),
      needPolicy:  /(điều kiện|chính sách|bảo hiểm|hư hỏng|sự cố|đặt cọc|cọc)/i.test(t)
    };
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
  PRICE_TABLE['wave']   = PRICE_TABLE['wave']   || { day:[150000], week:[600000,700000], month:[850000,1200000] };
  PRICE_TABLE['sirius'] = PRICE_TABLE['sirius'] || { day:[150000], week:[600000,700000], month:[850000,1200000] };
  PRICE_TABLE['blade']  = PRICE_TABLE['blade']  || { day:[150000], week:[600000,700000], month:[850000,1200000] };
  PRICE_TABLE['jupiter']= PRICE_TABLE['jupiter']|| { day:[150000], week:[600000,700000], month:[850000,1200000] };
  PRICE_TABLE['lead']   = PRICE_TABLE['lead']   || { day:[200000], week:[800000], month:[1600000,1900000] };
  PRICE_TABLE['liberty']= PRICE_TABLE['liberty']|| { day:[220000], week:[900000], month:[1700000,2000000] };
  PRICE_TABLE['vespa']  = PRICE_TABLE['vespa']  || { day:[300000], week:[1200000], month:[2400000,2800000] };
  PRICE_TABLE['grande'] = PRICE_TABLE['grande'] || { day:[220000], week:[900000], month:[1700000,2000000] };
  PRICE_TABLE['janus']  = PRICE_TABLE['janus']  || { day:[200000], week:[800000], month:[1500000,1900000] };
  PRICE_TABLE['sh']     = PRICE_TABLE['sh']     || { day:[450000], week:[1800000], month:[4500000] };

  function baseFor(type,unit){ return baseForModel(type,unit); }
  function modelFamily(model){
    switch((model||'').toLowerCase()){
      case 'vision': case 'air blade': case 'lead': case 'liberty': case 'vespa': case 'grande': case 'janus': case 'sh': return 'xe ga';
      case 'wave': case 'sirius': case 'blade': case 'jupiter': case 'future': case 'dream': return 'xe số';
      default: return null;
    }
  }
  function baseForModel(model, unit){
    if(!model) return null;
    const key = unit==="tuần"?"week":(unit==="tháng"?"month":"day");
    const entry = PRICE_TABLE[model];
    if(entry && entry[key]) return (Array.isArray(entry[key])?entry[key][0]:entry[key]);
    const fam = modelFamily(model);
    if(fam && PRICE_TABLE[fam] && PRICE_TABLE[fam][key]) return (Array.isArray(PRICE_TABLE[fam][key])?PRICE_TABLE[fam][key][0]:PRICE_TABLE[fam][key]);
    return null;
  }

  function extractPricesFromText(txt){
    const clean = String(txt||'');
    const lines = clean.replace(/<[^>]+>/g,' ').replace(/\s+/g,' ').split(/[\n\.•\-–]|<br\s*\/?>/i);
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
      if(price && price>50000 && price<5000000){ out.push({type:found.type, unit:'day', price}); }
    }
    return out;
  }

  /* ====== SEARCH & INDEX ====== */
  function tk(s){ return (s||"").toLowerCase().normalize('NFC').replace(/[^\p{L}\p{N}\s]+/gu,' ').split(/\s+/).filter(Boolean); }
  function loadLearn(){ return safe(localStorage.getItem(K.learn)) || {}; }
  function saveLearn(o){ safeSetItem(K.learn, JSON.stringify(o)); }
  function getIndexFlat(){
    const cache=loadLearn(); const out=[];
    Object.keys(cache).forEach(key=>{ (cache[key].pages||[]).forEach(pg=> out.push(Object.assign({source:key}, pg))); });
    return out;
  }
  function buildBM25(docs){
    const k1=1.5,b=0.75; const df=new Map(), tf=new Map(); let total=0;
    docs.forEach(d=>{
      const toks=tk(d.text); total+=toks.length;
      const map=new Map(); toks.forEach(t=> map.set(t,(map.get(t)||0)+1));
      tf.set(d.id,map); new Set(toks).forEach(t=> df.set(t,(df.get(t)||0)+1));
    });
    const N=docs.length||1, avgdl=total/Math.max(1,N); const idf=new Map();
    df.forEach((c,t)=> idf.set(t, Math.log(1 + (N - c + .5)/(c + .5))));
    function score(query, docId, docLen){
      const qToks=new Set(tk(query)); const map=tf.get(docId)||new Map(); let s=0;
      qToks.forEach(t=>{ const f=map.get(t)||0; if(!f) return; const idfv=idf.get(t)||0;
        s += idfv*(f*(k1+1))/(f + k1*(1 - b + b*(docLen/avgdl)));
      });
      return s;
    }
    return {score, tf, avgdl};
  }
  function searchIndex(query, k=3){
    const idx = getIndexFlat(); if(!idx.length) return [];
    const docs = idx.map((it,i)=>({id:String(i), text:((it.title||'')+' '+(it.text||'')), meta:it}));
    const bm = CFG.smart.semanticSearch ? buildBM25(docs) : null;
    const scored = bm
      ? docs.map(d=>({score: bm.score(query, d.id, tk(d.text).length||1), meta:d.meta}))
            .filter(x=>x.score>0).sort((a,b)=>b.score-a.score).slice(0,k).map(x=>x.meta)
      : idx.map(it=> Object.assign({score: tk(it.title+" "+it.text).filter(t=> tk(query).includes(t)).length}, it)).filter(x=>x.score>0).sort((a,b)=> b.score - a.score).slice(0,k);
    return scored;
  }
  function bestSentences(text, query, k=2){
    const sents = String(text||'').replace(/\s+/g,' ').split(/(?<=[\.\!\?])\s+/).slice(0,80);
    const qToks=new Set(tk(query)); const scored = sents.map(s=>{
      const toks=tk(s); let hit=0; qToks.forEach(t=>{ if(toks.includes(t)) hit++; });
      return {s, score: hit};
    }).filter(x=>x.score>0).sort((a,b)=>b.score-a.score);
    return scored.slice(0,k).map(x=>x.s);
  }

  /* ====== CRAWLER ====== */
  async function fetchText(url){
    const ctl = new AbortController(); const id = setTimeout(()=>ctl.abort(), CFG.fetchTimeoutMs);
    try{ const res = await fetch(url, {signal:ctl.signal}); clearTimeout(id); if(!res.ok) return null; return await res.text(); }
    catch(e){ clearTimeout(id); return null; }
  }
  function parseXML(t){ try{ return (new DOMParser()).parseFromString(t,'text/xml'); }catch{ return null; } }
  function parseHTML(t){ try{ return (new DOMParser()).parseFromString(t,'text/html'); }catch{ return null; } }
  async function readSitemap(url){
    const xml = await fetchText(url); if(!xml) return [];
    const doc = parseXML(xml); if(!doc) return [];
    const items = Array.from(doc.getElementsByTagName('item'));
    if(items.length) return items.map(it=> it.getElementsByTagName('link')[0]?.textContent?.trim()).filter(Boolean);
    const sm = Array.from(doc.getElementsByTagName('sitemap')).map(x=> x.getElementsByTagName('loc')[0]?.textContent?.trim()).filter(Boolean);
    if(sm.length){
      const all=[]; for(const loc of sm){ try{ const child = await readSitemap(loc); if(child && child.length) all.push(...child); }catch{} }
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
      if(!desc) desc = txt.replace(/<script[\s\S]*?<\/script>/gi,' ').replace(/<style[\s\S]*?<\/style>/gi,' ').replace(/<[^>]+>/g,' ').replace(/\s+/g,' ').trim().slice(0,600);
      if(CFG.viOnly && !looksVN(title+' '+desc)) continue;
      if(CFG.smart.autoPriceLearn){
        try{ const autos = extractPricesFromText(txt);
          if(autos.length){
            const stash = safe(localStorage.getItem(K.autoprices))||[];
            stash.push(...autos.map(a=> Object.assign({url:u}, a)));
            safeSetItem(K.autoprices, JSON.stringify(stash.slice(-500)));
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
        for(const c of smc){ try{ const u=await readSitemap(c); if(u && u.length){ urls=u; break; } }catch{} }
        if(!urls.length) urls = await fallbackCrawl(key);
        const uniq = Array.from(new Set(urls.map(u=>{ try{ return new URL(u).toString().split('#')[0]; }catch{ return null; } }).filter(Boolean).filter(u=> sameHost(u, key))));
        const pages = await pullPages(uniq, {urlsSeen:0});
        if(pages.length){
          cache[key]={domain:key, ts:nowSec(), pages};
          try{ saveLearn(cache); }catch{ const ks=Object.keys(cache); if(ks.length) delete cache[ks[0]]; saveLearn(cache); }
          results[key]=cache[key]; total+=pages.length;
        }
        if(total >= CFG.maxTotalPages) break;
      }catch(e){}
    }
    safeSetItem(K.stamp, Date.now()); return results;
  }

  /* ====== ANSWER LOGIC ====== */
  const PREFIX = ["Chào anh/chị,","Xin chào,","Em chào anh/chị,","Em ở "+CFG.brand+" đây,"];
  function polite(s){ s = s || "em chưa nhận được câu hỏi, anh/chị nhập lại giúp em."; return naturalize(`${pick(PREFIX)} ${s}`); }
  function composePrice(model, qty){
    const labelUnit = qty ? (qty.unit==="tuần"?"tuần":(qty.unit==="tháng"?"tháng":"ngày")) : null;
    if(!model && !qty) return naturalize(`Anh/chị thuê theo ngày, tuần hay tháng để em báo đúng giá nhé.`);
    if(!qty) return naturalize(`Anh/chị định thuê ${model||'mẫu xe'} theo ngày, tuần hay tháng để em báo giá chính xác.`);
    const base = baseForModel(model||'xe số', qty.unit);
    if(!base) return naturalize(`Giá thuê ${model||'mẫu xe'} theo ${qty.unit} cần kiểm tra. Anh/chị nhắn Zalo ${CFG.phone} để em chốt theo mẫu xe.`);
    const total = base * qty.n;
    let text = qty.n===1 ? `Giá thuê ${model||'mẫu xe'} 1 ${labelUnit} khoảng ${nfVND(base)}đ` : `Giá thuê ${model||'mẫu xe'} ${qty.n} ${labelUnit} khoảng ${nfVND(total)}đ`;
    if(qty.unit==="ngày" && qty.n>=3) text += " Thuê theo tuần sẽ tiết kiệm hơn";
    return naturalize(`${text}. Anh/chị cần em giữ xe và gửi ảnh xe qua Zalo ${CFG.phone} không?`);
  }
  async function deepAnswer(userText){
    const q = (userText||"").trim(); const intents = detectIntent(q);
    let model = detectType(q); const qty  = detectQty(q);
    if(CFG.deepContext){
      const ctx = getCtx();
      for(let i=ctx.turns.length-1;i>=0;i--){
        const t = ctx.turns[i];
        if(!model && t.type) model=t.type;
        if(!qty && t.qty) return composePrice(model||t.type, t.qty);
        if(model && qty) break;
      }
    }
    if(intents.needContact) return polite(`anh/chị gọi ${CFG.phone} hoặc Zalo ${CFG.zalo||CFG.phone} là có người nhận ngay.`);
    if(intents.needDocs)    return polite(`thủ tục gọn: CCCD/hộ chiếu + cọc theo xe. Có phương án giảm cọc khi đủ giấy tờ.`);
    if(intents.needPolicy)  return polite(`đặt cọc tham khảo: xe số 2–3 triệu; xe ga 2–5 triệu. Liên hệ Zalo ${CFG.phone} để chốt theo mẫu xe.`);
    if(intents.needDelivery)return polite(`thuê 1–4 ngày vui lòng đến cửa hàng; thuê tuần/tháng em giao tận nơi nội thành.`);
    if(intents.needReturn)  return polite(`trả xe tại cửa hàng hoặc hẹn trả tận nơi. Báo trước 30 phút để em sắp xếp.`);
    if(intents.needPrice)   return composePrice(model, qty);
    try{
      const top = searchIndex(q, 3);
      if(top && top.length){
        if(CFG.smart.extractiveQA){ const sn = bestSentences((top[0].title+'. ')+top[0].text, q, 2).join(' '); if(sn) return naturalize(sn); }
        return polite(((top[0].title?top[0].title+' — ':'')+top[0].text).slice(0,180)+'...');
      }
    }catch(e){}
    if(/(chào|xin chào|hello)/i.test(q)) return polite(`em là hỗ trợ viên của ${CFG.brand}. Anh/chị muốn xem Xe số, Xe ga hay Xe điện?`);
    return polite(`anh/chị quan tâm mẫu xe nào (vision, air blade, wave...) và thuê mấy ngày để em báo giá.`);
  }

  function mergeAutoPrices(){
    if(!CFG.smart.autoPriceLearn) return;
    try{
      const autos = safe(localStorage.getItem(K.autoprices))||[]; if(!autos.length) return;
      const byType = autos.reduce((m,a)=>{ (m[a.type]||(m[a.type]=[])).push(a.price); return m; },{});
      Object.keys(byType).forEach(t=>{
        const arr = byType[t].sort((a,b)=>a-b);
        const p50 = arr[Math.floor(arr.length*0.50)];
        if(PRICE_TABLE[t]) PRICE_TABLE[t].day = [p50];
        else PRICE_TABLE[t] = { day: [p50], week:null, month:null };
      });
    }catch{}
  }

  /* ====== CONTROL ====== */
  let isOpen=false, sending=false;
  function showTyping(){
    const body=$("#mta-body"); if(!body) return;
    const box=document.createElement("div"); box.id="mta-typing"; box.innerHTML=`<div class="dot-flashing"></div>`;
    body.appendChild(box); body.scrollTop=body.scrollHeight;
  }
  function hideTyping(){ const t=$("#mta-typing"); if(t) t.remove(); }
  
  async function sendUser(text){
    if(sending) return;
    const v=(text||"").trim(); if(!v) return;
    sending=true; addMsg("user", v);
    pushCtx({from:"user", raw:v, type:detectType(v), qty:detectQty(v)});
    const isMobile = window.innerWidth < 480; const wait = (isMobile? 1200 : 1800) + Math.random()*1000;
    showTyping(); await sleep(wait);
    const ans = await deepAnswer(v);
    hideTyping(); addMsg("bot", sanitizeReply(ans)); pushCtx({from:"bot", raw:sanitizeReply(ans)});
    sending=false;
  }
  
  function openChat(){
    if(isOpen) return;
    $("#mta-card").classList.add("open");
    $("#mta-backdrop").classList.add("show");
    $("#mta-bubble").style.transform = "scale(0) rotate(90deg)"; // Animation ẩn nút
    setTimeout(()=>$("#mta-bubble").style.display="none", 200);
    isOpen=true; renderSess();
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
    // Reset height fix
    const card = $("#mta-card");
    if(card) { card.style.bottom = "20px"; card.style.height = "75vh"; }
  }

  /* ====== IOS KEYBOARD & DOCK FIX ====== */
  let IOS_BOUND = false;
  function adjustForIOS(){
    if(IOS_BOUND || !window.visualViewport) return;
    IOS_BOUND = true; // Mark as bound
    const card = $("#mta-card");
    const view = window.visualViewport;
    function onResize(){
      if(!isOpen) return;
      // Nếu chiều cao viewport giảm mạnh (bàn phím hiện)
      if(view.height < window.innerHeight - 100){
        // Mobile full mode
        if(window.innerWidth <= 480){
          card.style.height = view.height + "px";
          card.style.bottom = "0px";
        } else {
          // Desktop/Tablet mode
          const offset = window.innerHeight - view.height;
          card.style.bottom = (offset + 10) + "px";
        }
        const body=$("#mta-body"); if(body) body.scrollTop=body.scrollHeight;
      } else {
        // Bàn phím ẩn
        card.style.height = window.innerWidth <= 480 ? "100%" : "75vh";
        card.style.bottom = window.innerWidth <= 480 ? "0px" : "20px";
      }
    }
    view.addEventListener("resize", onResize);
    view.addEventListener("scroll", onResize);
  }

  function checkDockOverlap(){
    const root = $("#mta-root");
    const card = $("#mta-card");
    if(!root || !card || CFG.position) return;
    
    // Select common floating elements in bottom-right
    const blockers = document.querySelectorAll("#quick-call, .quick-call, .quickcall, #quick-call-button, .quick-call-btn, .dock-bottom, .dock-right, .bottom-dock, .call-btn-fixed, .hotline-phone-ring-wrap");
    
    let conflict = false;
    blockers.forEach(el => {
      if(!el) return;
      const r = el.getBoundingClientRect();
      // Nếu phần tử nằm ở góc dưới phải (cách phải < 100px và cách đáy < 150px)
      if(r.right > window.innerWidth - 100 && r.bottom > window.innerHeight - 150){
        if(getComputedStyle(el).display !== 'none' && getComputedStyle(el).visibility !== 'hidden'){
          conflict = true;
        }
      }
    });

    if(conflict){
      // Chuyển sang trái
      root.style.right = "auto";
      root.style.left = "20px";
      card.style.right = "auto";
      card.style.left = "20px";
      card.style.transformOrigin = "bottom left"; // Fix animation origin
    }
  }

  function bindEvents(){
    $("#mta-bubble").addEventListener("click", openChat);
    $("#mta-backdrop").addEventListener("click", closeChat);
    $("#mta-close").addEventListener("click", closeChat);
    $("#mta-send").addEventListener("click", ()=>{
      const inp=$("#mta-in"); const v=inp.value.trim(); if(!v) return; inp.value=""; sendUser(v);
    });
    $("#mta-in").addEventListener("keydown", e=>{
      if(e.key==="Enter" && !e.shiftKey){ e.preventDefault(); const v=e.target.value.trim(); if(!v) return; e.target.value=""; sendUser(v); }
      const tags=$("#mta-tags"); if(tags){ if(e.target.value.trim().length>0) tags.classList.add('hidden'); else tags.classList.remove('hidden'); }
    });
    // Check null an toàn cho track
    const track = $("#mta-tag-track");
    if(track){
      track.querySelectorAll("button").forEach(btn=> btn.addEventListener("click", ()=> sendUser(btn.dataset.q||btn.textContent)));
    }
  }

  function ready(fn){ 
    if(document.readyState==="complete"||document.readyState==="interactive") {
      // Đảm bảo body tồn tại
      if(document.body) fn();
      else setTimeout(()=> ready(fn), 50);
    } else {
      document.addEventListener("DOMContentLoaded", ()=> {
         if(document.body) fn();
         else setTimeout(()=> ready(fn), 50);
      });
    }
  }

  ready(async ()=>{
    // Clear old clean
    const lastClean = parseInt(localStorage.getItem(K.clean)||0);
    if(!lastClean || (Date.now()-lastClean) > 7*24*3600*1000){ localStorage.removeItem(K.ctx); safeSetItem(K.clean, Date.now()); }
    
    // Inject HTML Safe
    if(!document.body) return; // double check
    const wrap=document.createElement("div"); wrap.innerHTML=HTML; document.body.appendChild(wrap.firstElementChild);
    const st=document.createElement("style"); st.textContent=CSS; document.head.appendChild(st);
    
    checkDockOverlap(); // Auto avoid quick call
    bindEvents(); 
    adjustForIOS(); 
    mergeAutoPrices();
    
    if(CFG.autolearn){
      const origins = Array.from(new Set([location.origin, ...(CFG.extraSites||[])]));
      const last = parseInt(localStorage.getItem(K.stamp)||0);
      if(!last || (Date.now()-last) >= CFG.refreshHours*3600*1000) await learnSites(origins, false);
    }
  });

  window.MotoAI_v39 = {
    open: openChat, close: closeChat, send: sendUser,
    learnNow: async (sites, force)=> await learnSites(sites||[location.origin], !!force),
    clear: ()=> { localStorage.removeItem(K.learn); localStorage.removeItem(K.autoprices); }
  };
})();
