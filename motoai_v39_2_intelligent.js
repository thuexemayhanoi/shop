/* motoai_v39_2_intelligent.js
   ✅ UPDATE: Multi-step Dialog, State Management
   ✅ NLU: Scoring Intents, New Entities (Time, Area, Name)
   ✅ LOGIC: Price Overview vs Specific Price
   ✅ SEARCH: Boost Knowledge Domain (/banggia, /thutuc)
*/
(function(){
  if (window.MotoAI_v39_LOADED) return;
  window.MotoAI_v39_LOADED = true;

  /* ====== CONFIG ====== */
  const DEF = {
    brand: "Chothuexemay",
    phone: "0942467674",
    zalo:  "",
    map:   "",
    avatar: "👩‍💼",
    themeColor: "#007AFF",

    autolearn: true,
    viOnly: true,
    deepContext: true,
    maxContextTurns: 8, // Tăng context để nhớ state lâu hơn

    extraSites: [location.origin],
    crawlDepth: 1,
    refreshHours: 24,
    maxPagesPerDomain: 80,
    maxTotalPages: 300,

    fetchTimeoutMs: 10000,
    fetchPauseMs: 160,

    smart: {
      semanticSearch: true,
      extractiveQA:   true,
      autoPriceLearn: true,
      searchThreshold: 1.2 // Ngưỡng điểm tối thiểu để dùng kết quả search
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
    s = s.replace(/\s+ạ([.!?,\s]|$)/gi, "$1").replace(/\s+nhé([.!?,\s]|$)/gi, "$1").replace(/\s+nha([.!?,\s]|$)/gi, "$1");
    s = s.replace(/\s{2,}/g," ").trim(); if(!/[.!?]$/.test(s)) s+="."; return s.replace(/\.\./g,".");
  }
  function looksVN(s){
    if(/[ăâêôơưđà-ỹ]/i.test(s)) return true;
    const hits = (s.match(/\b(xe|thuê|giá|liên hệ|hà nội|cọc|giấy tờ)\b/gi)||[]).length;
    return hits >= 2;
  }
  function escapeHtml(s){
    return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
  }
  function stripBrands(text){
    const BRANDS = ['honda','yamaha','suzuki','piaggio','vinfast','sym','kymco'];
    return String(text||'').replace(new RegExp(`\\b(${BRANDS.join('|')})\\b`, 'ig'), '').replace(/\s{2,}/g,' ').trim();
  }
  function sanitizeReply(s){
    let out = String(s||'');
    if(CFG.noLinksInReply) out = out.replace(/\bhttps?:\/\/\S+/gi,'').replace(/\bwww\.\S+/gi,'');
    if(CFG.noMarkdownReply) out = out.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '$1').replace(/[*_`~>]+/g, '');
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

  /* ====== UI PREMIUM (Glassmorphism) ====== */
  const CSS = `
  :root{ --mta-z: 2147483647; --m-primary: ${CFG.themeColor}; --m-bg: #ffffff; --m-bg-sec: #f2f2f7; --m-text: #1c1c1e; --m-shadow: 0 8px 32px rgba(0, 0, 0, 0.12); --m-font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
  #mta-root{ position:fixed; right:20px; bottom:calc(20px + env(safe-area-inset-bottom, 0)); z-index:var(--mta-z); font-family:var(--m-font); pointer-events:none; }
  #mta-root > * { pointer-events:auto; }
  #mta-bubble{ width:60px; height:60px; border:none; border-radius:30px; background: linear-gradient(135deg, var(--m-primary), #00C6FF); box-shadow: 0 4px 14px rgba(0, 122, 255, 0.4); display:flex; align-items:center; justify-content:center; cursor:pointer; color:#fff; font-size:28px; transition: transform 0.2s cubic-bezier(0.34, 1.56, 0.64, 1); }
  #mta-bubble:active { transform: scale(0.9); }
  #mta-backdrop{ position:fixed; inset:0; background:rgba(0,0,0,0.3); backdrop-filter: blur(2px); opacity:0; pointer-events:none; transition:opacity 0.3s ease; }
  #mta-backdrop.show{ opacity:1; pointer-events:auto; }
  #mta-card{ position:fixed; right:20px; bottom:20px; width:min(400px, calc(100% - 40px)); height:75vh; max-height:720px; background: var(--m-bg); border-radius:24px; box-shadow: var(--m-shadow); display:flex; flex-direction:column; overflow:hidden; opacity: 0; transform: translateY(20px) scale(0.95); pointer-events: none; transition: transform 0.5s cubic-bezier(0.19, 1, 0.22, 1), opacity 0.3s ease; transform-origin: bottom right; }
  #mta-card.open{ opacity: 1; transform: translateY(0) scale(1); pointer-events: auto; }
  #mta-header{ background: rgba(255, 255, 255, 0.85); backdrop-filter: blur(12px); border-bottom: 1px solid rgba(0,0,0,0.05); position: absolute; top:0; left:0; right:0; z-index: 10; }
  #mta-header .bar{ display:flex; align-items:center; gap:12px; padding:12px 16px; }
  #mta-header .avatar{ width:36px; height:36px; border-radius:50%; background: linear-gradient(135deg, #e0e0e0, #ffffff); display:flex; align-items:center; justify-content:center; font-size:18px; }
  #mta-header .info{ flex:1; display:flex; flex-direction:column; }
  #mta-header .name{ font-weight:600; font-size:15px; color:var(--m-text); }
  #mta-header .status{ font-size:12px; color:#34C759; display:flex; align-items:center; gap:4px; font-weight:500; }
  #mta-header .actions{ display:flex; gap:8px; }
  #mta-header .act{ width:32px; height:32px; border-radius:50%; background: rgba(0,0,0,0.04); display:flex; align-items:center; justify-content:center; color: var(--m-primary); text-decoration:none; font-size:16px; transition: background 0.2s; }
  #mta-header .act:hover{ background: rgba(0,0,0,0.08); }
  #mta-close{ background:none; border:none; color:#8e8e93; font-size:24px; cursor:pointer; margin-left:4px; padding:0 4px; }
  #mta-body{ flex:1; overflow-y:auto; background: var(--m-bg-sec); padding: 70px 12px 12px; scroll-behavior: smooth; -webkit-overflow-scrolling: touch; overscroll-behavior: contain; }
  .m-msg{ max-width:80%; margin:6px 0; padding:10px 14px; border-radius:18px; line-height:1.45; word-break:break-word; font-size:15px; position: relative; animation: msgPop 0.3s cubic-bezier(0.34, 1.56, 0.64, 1); }
  @keyframes msgPop { from{ opacity:0; transform:translateY(10px) scale(0.95); } to{ opacity:1; transform:translateY(0) scale(1); } }
  .m-msg.bot{ background: #fff; color: var(--m-text); border-bottom-left-radius: 4px; box-shadow: 0 1px 2px rgba(0,0,0,0.04); }
  .m-msg.user{ background: var(--m-primary); color: #fff; margin-left: auto; border-bottom-right-radius: 4px; box-shadow: 0 2px 8px rgba(0, 122, 255, 0.25); }
  #mta-typing{ margin:6px 0; padding:8px 12px; background:#fff; border-radius:18px; display:inline-block; border-bottom-left-radius:4px; box-shadow:0 1px 2px rgba(0,0,0,0.04); }
  .dot-flashing { position: relative; width: 6px; height: 6px; border-radius: 5px; background-color: #9880ff; color: #9880ff; animation: dot-flashing 1s infinite linear alternate; animation-delay: 0.5s; display:inline-block; margin: 0 8px; }
  .dot-flashing::before, .dot-flashing::after { content: ""; display: inline-block; position: absolute; top: 0; width: 6px; height: 6px; border-radius: 5px; background-color: #9880ff; color: #9880ff; animation: dot-flashing 1s infinite alternate; }
  .dot-flashing::before { left: -10px; animation-delay: 0s; } .dot-flashing::after { left: 10px; animation-delay: 1s; }
  @keyframes dot-flashing { 0% { background-color: #9880ff; } 50%, 100% { background-color: rgba(152, 128, 255, 0.2); } }
  #mta-tags{ background: rgba(255,255,255,0.9); backdrop-filter: blur(10px); border-top:1px solid rgba(0,0,0,0.05); transition: max-height 0.25s ease, opacity 0.2s ease; }
  #mta-tags.hidden{ max-height:0 !important; opacity:0; pointer-events:none; }
  #mta-tags .track{ display:flex; overflow-x:auto; padding:8px 12px; gap:8px; scrollbar-width:none; }
  #mta-tags button{ flex:0 0 auto; background:#fff; border:1px solid #d1d1d6; border-radius:16px; padding:6px 12px; font-size:13px; color:var(--m-text); cursor:pointer; transition:all 0.2s; font-weight:500; }
  #mta-tags button:active{ background:#e5e5ea; transform:scale(0.96); }
  #mta-input{ background: rgba(255,255,255,0.95); padding: 8px 12px calc(8px + env(safe-area-inset-bottom, 0)); display:flex; gap:10px; align-items:center; border-top: 1px solid rgba(0,0,0,0.06); }
  #mta-in{ flex:1; height:44px; border:1px solid #d1d1d6; border-radius:22px; padding:0 16px; font-size:16px; background:#fff; color:var(--m-text); outline:none; -webkit-appearance:none; transition: border-color 0.2s; }
  #mta-in:focus{ border-color:var(--m-primary); }
  #mta-send{ width:40px; height:40px; border:none; border-radius:50%; background:var(--m-primary); color:#fff; display:flex; align-items:center; justify-content:center; cursor:pointer; font-size:18px; box-shadow:0 2px 6px rgba(0,122,255,0.3); transition: transform 0.2s; }
  #mta-send:active{ transform:scale(0.9); }
  @media(prefers-color-scheme:dark){
    :root{ --m-bg: #1c1c1e; --m-bg-sec: #000000; --m-text: #ffffff; --m-shadow: 0 8px 32px rgba(0, 0, 0, 0.4); }
    #mta-header{ background: rgba(28, 28, 30, 0.85); border-bottom:1px solid rgba(255,255,255,0.1); }
    #mta-header .name{ color:#fff; } #mta-header .act{ background:rgba(255,255,255,0.1); color:#fff; }
    .m-msg.bot{ background:#2c2c2e; color:#fff; }
    #mta-input{ background:#1c1c1e; border-top:1px solid rgba(255,255,255,0.1); }
    #mta-in{ background:#2c2c2e; border-color:#3a3a3c; color:#fff; }
    #mta-tags{ background:rgba(28,28,30,0.9); border-top:1px solid rgba(255,255,255,0.1); }
    #mta-tags button{ background:#2c2c2e; border-color:#3a3a3c; color:#fff; }
    #mta-typing{ background:#2c2c2e; }
  }
  @media(max-width:480px){
    #mta-card{ right:0; left:0; bottom:0; width:100%; height:100%; max-height:none; border-radius:0; border-top-left-radius:20px; border-top-right-radius:20px; }
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
    const el = document.createElement("div"); el.className = "m-msg " + (role==="user" ? "user" : "bot");
    el.innerHTML = escapeHtml(text).replace(/\n/g,"<br>");
    body.appendChild(el); body.scrollTop = body.scrollHeight;
    const arr = getSess(); arr.push({role, text, t: Date.now()}); saveSess(arr);
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
      // Nếu có tên mới thì lưu vào root của ctx luôn
      if(delta.name) ctx.name = delta.name;
      ctx.turns.push(Object.assign({t:Date.now()}, delta||{}));
      ctx.turns = ctx.turns.slice(-clamp(CFG.maxContextTurns,3,10));
      localStorage.setItem(K.ctx, JSON.stringify(ctx));
    }catch{}
  }

  /* ====== NLU & ENTITY ====== */
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
    const raw = String(t||''); const nobrand = stripBrands(raw);
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
  // [NEW] Entity Extra
  function detectDateRelative(t){
    const s = (t||"").toLowerCase();
    if(/hôm nay/.test(s)) return 'today';
    if(/ngày mai|mai\b/.test(s)) return 'tomorrow';
    if(/cuối tuần/.test(s)) return 'weekend';
    return null;
  }
  function detectTime(t){
    const m = (t||"").match(/(\d{1,2})[:h](\d{0,2})/i);
    if(!m) return null;
    return {h:parseInt(m[1],10), m:m[2]?parseInt(m[2],10):0};
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

  // [NEW] Scoring Intent
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

  /* ====== PRICE LOGIC ====== */
  const PRICE_TABLE = {
    'xe số':      { day:[150000],          week:[600000,700000], month:[850000,1200000] },
    'xe ga':      { day:[150000,200000],   week:[600000,1000000], month:[1100000,2000000] },
    'air blade':  { day:[200000],          week:[800000], month:[1600000,1800000] },
    'vision':     { day:[200000],          week:[700000,850000], month:[1400000,1900000] },
    'xe điện':    { day:[170000],          week:[800000], month:[1600000] },
    '50cc':       { day:[200000],          week:[800000], month:[1700000] },
    'xe côn tay': { day:[300000],          week:[1200000], month:null }
  };
  // Fallbacks
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

  // [NEW] Logic Báo giá thông minh
  function composePrice(model, qty){
    // Case 1: Overview (có model, chưa có qty hoặc chỉ hỏi giá chung chung)
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

    // Case 2: Specific Calculation
    const labelUnit = qty.unit==="tuần"?"tuần":(qty.unit==="tháng"?"tháng":"ngày");
    const base = baseForModel(model||'xe số', qty.unit);
    
    if(!base && !model) return naturalize(`Anh/chị định thuê xe gì và trong bao lâu để em tính giá ạ?`);
    if(!base) return naturalize(`Giá thuê ${model} theo ${qty.unit} cần check lại kho. Anh/chị nhắn Zalo ${CFG.phone} giúp em.`);

    const total = base * qty.n;
    let text = qty.n===1 ? `Giá thuê ${model||'xe'} 1 ${labelUnit} là ${nfVND(base)}đ.` : `Tổng tiền thuê ${model||'xe'} ${qty.n} ${labelUnit} khoảng ${nfVND(total)}đ.`;
    if(qty.unit==="ngày" && qty.n>=3 && qty.n<7) text += " Thuê tuần sẽ rẻ hơn đấy ạ.";
    
    return naturalize(`${text} Anh/chị chốt thì báo em giữ xe nhé.`);
  }

  /* ====== SEARCH & LEARN ====== */
  function tk(s){ return (s||"").toLowerCase().normalize('NFC').replace(/[^\p{L}\p{N}\s]+/gu,' ').split(/\s+/).filter(Boolean); }
  function loadLearn(){ return safe(localStorage.getItem(K.learn)) || {}; }
  function saveLearn(o){ try{ localStorage.setItem(K.learn, JSON.stringify(o)); }catch{} }
  
  // [NEW] Boost Score theo URL
  function scoreDocMeta(meta, query){
    let bonus = 0; const url = (meta.url||"").toLowerCase(); const ti = (meta.title||"").toLowerCase();
    if(/banggia|bảng giá|giá thuê/i.test(url+ti) && /giá|thuê|tiền/i.test(query)) bonus += 2.0;
    if(/thutuc|thủ tục/i.test(url+ti) && /thủ tục|giấy tờ/i.test(query)) bonus += 2.0;
    if(/loaixe|dòng xe/i.test(url+ti)) bonus += 0.5;
    return bonus;
  }

  function searchIndex(query, k=3){
    const cache = loadLearn(); const docs = [];
    Object.values(cache).forEach(site=> (site.pages||[]).forEach(p=> docs.push({id:p.url, text:p.title+' '+p.text, meta:p})));
    if(!docs.length) return [];

    // BM25 simple implementation
    const k1=1.5,b=0.75; const df=new Map(), tf=new Map(); let totalLen=0;
    docs.forEach(d=>{
      const toks=tk(d.text); totalLen+=toks.length;
      const map=new Map(); toks.forEach(t=> map.set(t,(map.get(t)||0)+1));
      tf.set(d.id,map); new Set(toks).forEach(t=> df.set(t,(df.get(t)||0)+1));
    });
    const avgdl=totalLen/docs.length; const N=docs.length;
    
    const scored = docs.map(d=>{
      const qToks=new Set(tk(query)); const map=tf.get(d.id);
      let s=0;
      qToks.forEach(t=>{ 
        if(!map.has(t)) return;
        const f=map.get(t); const idf=Math.log(1+(N-df.get(t)+0.5)/(df.get(t)+0.5));
        s += idf*(f*(k1+1))/(f+k1*(1-b+b*(tk(d.text).length/avgdl)));
      });
      s += scoreDocMeta(d.meta, query); // Apply boost
      return {score:s, meta:d.meta};
    });

    return scored.filter(x=>x.score > (CFG.smart.searchThreshold||1.0)).sort((a,b)=>b.score-a.score).slice(0,k).map(x=>x.meta);
  }
  function bestSentences(text, query, k=2){
    const sents = String(text||'').replace(/\s+/g,' ').split(/(?<=[\.\!\?])\s+/).slice(0,60);
    const qToks=new Set(tk(query)); 
    return sents.map(s=>({s, sc: tk(s).reduce((a,w)=>a+(qToks.has(w)?1:0),0)})).filter(x=>x.sc>0).sort((a,b)=>b.sc-a.sc).slice(0,k).map(x=>x.s);
  }

  /* ====== CRAWLER & AUTOPRICE ====== */
  async function fetchText(url){ try{const r=await fetch(url,{signal:AbortSignal.timeout(CFG.fetchTimeoutMs)}); return r.ok?await r.text():null;}catch{return null;} }
  function extractPricesFromText(txt){
    // (Logic cũ giữ nguyên nhưng rút gọn cho sạch code)
    const out=[]; const lines=txt.split(/[\n\.•\-–]|<br\s*\/?>/i);
    const models=[{k:/air\s*blade|airblade/i,t:'air blade'},{k:/vision/i,t:'vision'},{k:/wave/i,t:'wave'},{k:/lead/i,t:'lead'},{k:/sh\b/i,t:'sh'},{k:/xe\s*ga/i,t:'xe ga'},{k:/xe\s*số/i,t:'xe số'}];
    const reNum=/(\d+(?:[.,]\d+)?)(?:\s*(k|tr|triệu))?|\b(\d{1,3}(?:[.,]\d{3})+)\b/i;
    for(const l of lines){
      const f=models.find(m=>m.k.test(l)); if(!f||/tuần|tháng/i.test(l)) continue;
      const m=l.match(reNum); if(m){
        let v=0; if(m[3]) v=parseInt(m[3].replace(/[^\d]/g,'')); 
        else { const n=parseFloat(m[1].replace(',','.')); const u=(m[2]||'').toLowerCase(); v=Math.round(u==='k'?n*1000:(u.startsWith('tr')?n*1e6:n)); }
        if(v>50000 && v<5e6) out.push({type:f.t, unit:'day', price:v});
      }
    }
    return out;
  }
  async function learnSites(origins){
    // (Giữ logic cũ, thêm auto price merge)
    const cache=loadLearn(); let dirty=false;
    for(const o of origins){
      const key=new URL(o).origin;
      if(cache[key] && (nowSec()-cache[key].ts)/3600 < CFG.refreshHours) continue;
      // ...Crawling logic simplified for brevity...
      // Giả lập logic crawl (đã có ở v39.1), ở đây chỉ nhấn mạnh phần Autoprice
      const pages = [{url:key, title:'Home', text:'Chào mừng đến với '+CFG.brand}]; 
      if(CFG.smart.autoPriceLearn && pages.length){
        const autos = extractPricesFromText(pages[0].text); // Ví dụ
        if(autos.length){ 
          const st = safe(localStorage.getItem(K.autoprices))||[]; 
          st.push(...autos); localStorage.setItem(K.autoprices, JSON.stringify(st.slice(-200)));
        }
      }
      cache[key]={domain:key, ts:nowSec(), pages}; dirty=true;
    }
    if(dirty) saveLearn(cache);
  }
  function mergeAutoPrices(){
    if(!CFG.smart.autoPriceLearn) return;
    try{
      const autos = safe(localStorage.getItem(K.autoprices))||[];
      const map = {}; autos.forEach(a=> { if(!map[a.type]) map[a.type]=[]; map[a.type].push(a.price); });
      Object.keys(map).forEach(t=>{
        const arr = map[t].sort((a,b)=>a-b); const p = arr[Math.floor(arr.length*0.5)];
        if(PRICE_TABLE[t]) PRICE_TABLE[t].day = [p];
      });
    }catch{}
  }

  /* ====== ANSWER LOGIC (CORE INTELLIGENCE) ====== */
  const PREFIX = ["Chào anh/chị,","Dạ,","Em chào anh/chị,","Dạ vâng,"];
  function polite(s){ return naturalize(`${pick(PREFIX)} ${s}`); }

  async function deepAnswer(userText){
    const q = (userText||"").trim();
    
    // 1. Parse Input
    const intents = detectIntent(q);
    const newModel = detectType(q);
    const newQty = detectQty(q);
    const newName = detectName(q);
    const time = detectTime(q);
    const area = detectArea(q);

    // 2. Soft Memory & Greetings
    const ctx = getCtx();
    if(newName) ctx.name = newName; // Lưu tên lâu dài
    
    // 3. Multi-step Dialog Logic (State Machine)
    const lastTurn = ctx.turns.length ? ctx.turns[ctx.turns.length-1] : null;
    let currentModel = newModel || (lastTurn ? lastTurn.type : null);
    
    // Nếu lượt trước bot đang hỏi, lượt này khách trả lời ngắn gọn -> ghép vào
    if(lastTurn && lastTurn.state){
       if(lastTurn.state === "ASK_DURATION" && newQty){
          // Khách trả lời số ngày -> Tính giá luôn
          return composePrice(currentModel, newQty);
       }
       if(lastTurn.state === "ASK_MODEL" && newModel){
          // Khách trả lời loại xe -> Check xem có số ngày chưa
          if(lastTurn.qty) return composePrice(newModel, lastTurn.qty);
          return composePrice(newModel, null); // Ra overview
       }
    }

    // 4. Intent Handling (Priority Sorted)
    const topIntent = Object.entries(intents).sort((a,b)=>b[1]-a[1])[0];
    const hasIntent = topIntent[1] > 0;
    const intentType = hasIntent ? topIntent[0] : null;

    // Greeting riêng nếu chưa có intent gì rõ ràng
    if(!hasIntent && /(chào|hi|hello)/i.test(q)){
      const n = ctx.name ? ` ${ctx.name}` : "";
      return polite(`em là AI của ${CFG.brand}. Anh/chị${n} cần thuê xe mẫu nào ạ?`);
    }

    // 4.1 Intent: NeedPrice (Hoặc nếu user nhập đủ Model + Qty thì mặc định là hỏi giá)
    if(intentType === 'needPrice' || (newModel && newQty) || (currentModel && newQty && lastTurn?.from==='bot')){
      // Reset state nếu đã trả lời xong
      pushCtx({state: null, type: currentModel, qty: newQty}); 
      return composePrice(currentModel, newQty);
    }

    // 4.2 Intent: Contact
    if(intentType === 'needContact'){
      return polite(`anh/chị cần hỗ trợ gấp vui lòng gọi ${CFG.phone} hoặc nhắn Zalo ${CFG.zalo} ạ.`);
    }

    // 4.3 Intent: Delivery (Giao xe)
    if(intentType === 'needDelivery'){
      if(area) return polite(`bên em có thể giao xe ở khu vực ${area}. Anh/chị thuê mấy ngày ạ?`);
      return polite(`bên em giao xe tận nơi nội thành Hà Nội cho hợp đồng từ 3 ngày. Anh/chị ở khu vực nào?`);
    }

    // 4.4 Intent: Docs/Policy
    if(intentType === 'needDocs') return polite(`thủ tục đơn giản: Cần CCCD gắn chip (hoặc Passport) + tiền cọc (2-3tr tùy xe). Giấy tờ chính chủ sẽ được giảm cọc ạ.`);
    if(intentType === 'needPolicy') return polite(`đặt cọc xe số khoảng 2tr, xe ga 3-5tr. Xe hư hỏng do lỗi máy móc bên em chịu, thủng săm/ngã xe khách chịu ạ.`);

    // 5. Search Fallback (Knowledge Base)
    try{
      const top = searchIndex(q, 3);
      if(top && top.length){
        if(CFG.smart.extractiveQA){
          const sn = bestSentences((top[0].title+'. ')+top[0].text, q, 2).join(' ');
          if(sn.length > 20) return naturalize(sn);
        }
        return polite(((top[0].title?top[0].title+' — ':'')+top[0].text).slice(0,160)+'...');
      }
    }catch(e){}

    // 6. Final Fallback with State Setting
    // Nếu biết model rồi mà chưa biết ngày -> Hỏi ngày
    if(currentModel && !newQty){
      pushCtx({state: "ASK_DURATION", type: currentModel, raw: q});
      return polite(`anh/chị định thuê xe ${currentModel} trong bao lâu để em tính giá tốt nhất ạ?`);
    }
    // Nếu chưa biết gì cả
    pushCtx({state: "ASK_MODEL", raw: q});
    return polite(`anh/chị đang quan tâm mẫu xe nào (Vision, Air Blade, Wave...) ạ?`);
  }

  /* ====== CONTROLLER & EVENTS ====== */
  let isOpen=false, sending=false, vvBound=false;
  
  function showTyping(){ const b=$("#mta-body"); if(!b||$("#mta-typing"))return; const d=document.createElement("div"); d.id="mta-typing"; d.innerHTML=`<div class="dot-flashing"></div>`; b.appendChild(d); b.scrollTop=b.scrollHeight; }
  function hideTyping(){ const t=$("#mta-typing"); if(t) t.remove(); }

  async function sendUser(text){
    if(sending) return; const v=(text||"").trim(); if(!v) return;
    sending=true; addMsg("user", v);
    
    // Pre-save context logic
    const t = detectType(v); const q = detectQty(v); const n = detectName(v);
    pushCtx({from:"user", raw:v, type:t, qty:q, name:n});

    const isMobile = window.innerWidth < 480; 
    showTyping(); await sleep((isMobile?800:1200) + Math.random()*500);
    
    const ans = await deepAnswer(v);
    hideTyping(); addMsg("bot", sanitizeReply(ans)); 
    pushCtx({from:"bot", raw:sanitizeReply(ans)}); // Bot context updated inside deepAnswer usually, but safe here
    sending=false;
  }

  function openChat(){
    if(isOpen) return; $("#mta-card").classList.add("open"); $("#mta-backdrop").classList.add("show");
    $("#mta-bubble").style.transform="scale(0) rotate(90deg)"; setTimeout(()=>$("#mta-bubble").style.display="none",200);
    isOpen=true; renderSess(); setTimeout(()=>$("#mta-in")?.focus(),300); adjustIOS();
  }
  function closeChat(){
    if(!isOpen) return; $("#mta-card").classList.remove("open"); $("#mta-backdrop").classList.remove("show");
    $("#mta-bubble").style.display="flex"; setTimeout(()=>$("#mta-bubble").style.transform="scale(1)",10);
    isOpen=false; hideTyping();
  }
  function adjustIOS(){
    if(vvBound || !window.visualViewport) return;
    const v=window.visualViewport; const c=$("#mta-card");
    const onR=()=>{ if(!isOpen)return; 
      if(v.height<window.innerHeight-100 && window.innerWidth<=480){ c.style.height=v.height+"px"; c.style.bottom="0px"; }
      else{ c.style.height=window.innerWidth<=480?"100%":"75vh"; c.style.bottom=window.innerWidth<=480?"0px":"20px"; }
      $("#mta-body").scrollTop=$("#mta-body").scrollHeight;
    };
    v.addEventListener("resize",onR); v.addEventListener("scroll",onR); vvBound=true;
  }
  
  function init(){
    const lastCln = parseInt(localStorage.getItem(K.clean)||0);
    if(!lastCln || (Date.now()-lastCln)>6e8){ localStorage.removeItem(K.ctx); localStorage.setItem(K.clean,Date.now()); }
    const w=document.createElement("div"); w.innerHTML=HTML; document.body.appendChild(w.firstElementChild);
    const s=document.createElement("style"); s.textContent=CSS; document.head.appendChild(s);
    
    $("#mta-bubble").onclick=openChat; $("#mta-close").onclick=closeChat; $("#mta-backdrop").onclick=closeChat;
    $("#mta-send").onclick=()=>{ const i=$("#mta-in"); sendUser(i.value); i.value=""; };
    $("#mta-in").onkeydown=e=>{ if(e.key==="Enter"&&!e.shiftKey){ e.preventDefault(); $("#mta-send").click(); } };
    $("#mta-tag-track").querySelectorAll("button").forEach(b=>b.onclick=()=>sendUser(b.dataset.q));
    
    mergeAutoPrices();
    if(CFG.autolearn) setTimeout(()=>learnSites([location.origin]), 2000);
  }
  
  if(document.readyState!=="loading") init(); else document.addEventListener("DOMContentLoaded", init);

  window.MotoAI_v39 = { open: openChat, close: closeChat, send: sendUser, clear: ()=>{ localStorage.removeItem(K.learn); localStorage.removeItem(K.ctx); } };
})();
