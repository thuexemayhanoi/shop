/* motoai_v41_ultimate.js
   ✅ HỢP NHẤT TOÀN DIỆN:
      - CORE (v38): Crawler đa luồng, BM25 Search, Auto-Price Extraction, Extractive QA.
      - UI/UX (v40): Giao diện App-like, Chống zoom iOS (Font 16px), VisualViewport fix, Typing effect.
      - LOGIC: Xử lý song ngữ Anh/Việt + Fallback thông minh.

   👉 Cách dùng:
      1. Nhúng script vào web.
      2. Bot tự hiện bubble.
      3. Gõ MotoAI_v41.learnNow() trong console để kích hoạt học ngay lập tức (hoặc đợi auto).
*/

(function(){
  if (window.MotoAI_v41_LOADED) return;
  window.MotoAI_v41_LOADED = true;

  /* ================= CONFIGURATION ================= */
  const DEF = {
    brand: "Moto Assistant",
    phone: "0942467674",
    zalo:  "", // Tự động điền nếu trống
    map:   "",
    avatar: "👩‍💼",
    themeColor: "#0084FF",

    // --- CRAWLER & LEARNING (From v38) ---
    autolearn: true,        // Tự động học khi tải trang
    extraSites: [location.origin], // Danh sách các site vệ tinh cần học
    crawlDepth: 1,
    refreshHours: 24,       // Học lại sau 24h
    maxPagesPerDomain: 80,
    maxTotalPages: 400,
    fetchTimeoutMs: 10000,
    fetchPauseMs: 150,      // Nghỉ giữa các lần fetch để tránh spam server

    // --- SMART LOGIC ---
    smart: {
      semanticSearch: true, // Dùng BM25 tìm kiếm nội dung
      extractiveQA:   true, // Trích xuất câu trả lời ngắn
      autoPriceLearn: true  // Tự động học giá từ HTML
    },

    // --- UX SETTINGS (From v40) ---
    deepContext: true,      // Nhớ ngữ cảnh (hỏi 'giá bao nhiêu' hiểu là xe đang nói tới)
    maxContextTurns: 5,
    noLinksInReply: false,  // Cho phép hiện link
    debug: true             // Hiện log
  };

  const ORG = (window.MotoAI_CONFIG || {});
  if (!ORG.zalo && (ORG.phone || DEF.phone)) {
    ORG.zalo = 'https://zalo.me/' + String(ORG.phone || DEF.phone).replace(/\s+/g,'');
  }
  const CFG = Object.assign({}, DEF, ORG);
  CFG.smart = Object.assign({}, DEF.smart, (ORG.smart || {}));

  /* ================= HELPERS ================= */
  const $ = s => document.querySelector(s);
  const safe = s => { try { return JSON.parse(s); } catch { return null; } };
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const nowSec = () => Math.floor(Date.now()/1000);
  const clamp = (n,min,max) => Math.max(min, Math.min(max,n));
  const nfVND = n => (n || 0).toLocaleString("vi-VN");
  const sameHost = (u, origin) => { try{ return new URL(u).host.replace(/^www\./,'') === new URL(origin).host.replace(/^www\./,''); }catch{ return false; } };

  function naturalize(t){
    if (!t) return "";
    let s = (" " + t + " ").replace(/\s+/g," ");
    s = s.replace(/\s+ạ([.!?,\s]|$)/gi, "$1").replace(/\s+nhé([.!?,\s]|$)/gi, "$1").replace(/\s+nha([.!?,\s]|$)/gi, "$1");
    return s.trim().replace(/\.\./g,".");
  }

  function looksVN(s){
    if (/[ăâêôơưđà-ỹ]/i.test(s)) return true;
    const hits = (s.match(/\b(xe|thuê|giá|liên hệ|hà nội|cọc|giấy tờ)\b/gi)||[]).length;
    return hits >= 1;
  }

  function detectLang(text){
    const s = String(text || "");
    if (!s.trim()) return "vi"; // Mặc định Việt
    if (looksVN(s)) return "vi";
    if (/[a-z]{3,}/i.test(s)) return "en";
    return "vi";
  }

  /* ================= STORAGE KEYS ================= */
  const K = {
    sess:  "MotoAI_v41_sess",
    ctx:   "MotoAI_v41_ctx",
    learn: "MotoAI_v41_learn",       // Dữ liệu đã học {domain: {ts, pages:[]}}
    autoprices: "MotoAI_v41_prices", // Giá trích xuất tự động
    dbg:   "MotoAI_v41_stats"
  };

  /* ================= UI ENGINE (From v40) ================= */
  /* CSS tối ưu cho Mobile, chống zoom input iOS, hỗ trợ Dark Mode */
  const CSS = `
  :root{
    --m-z:2147483647; --m-blue:${CFG.themeColor}; --m-bg:#fff; --m-text:#0b1220;
    --m-in-h:42px; --m-in-fs:16px; /* 16px để iOS không tự zoom */
    --m-bot:80px;
  }
  #mta-root{position:fixed;right:16px;bottom:calc(var(--m-bot) + env(safe-area-inset-bottom,0));z-index:var(--m-z);font-family:-apple-system,system-ui,sans-serif;-webkit-text-size-adjust:100%}
  
  /* BUBBLE */
  #mta-bubble{width:56px;height:56px;border:none;border-radius:50%;background:radial-gradient(circle at 30% 0,var(--m-blue),#00B2FF);display:flex;align-items:center;justify-content:center;cursor:pointer;box-shadow:0 10px 30px rgba(0,80,255,0.3);color:#fff;font-size:24px;transition:transform .2s;animation:mta-bounce 4s infinite}
  #mta-bubble:hover{transform:scale(1.08)}
  @keyframes mta-bounce{0%,80%,100%{transform:translateY(0)} 85%{transform:translateY(-4px)} 90%{transform:translateY(0)}}
  
  /* MAIN CARD */
  #mta-backdrop{position:fixed;inset:0;background:rgba(0,0,0,0.3);opacity:0;pointer-events:none;transition:opacity .2s}
  #mta-backdrop.show{opacity:1;pointer-events:auto}
  
  #mta-card{
    position:fixed;right:16px;bottom:calc(var(--m-bot) + env(safe-area-inset-bottom,0));
    width:min(400px, calc(100% - 24px)); height:min(72vh, 740px);
    background:var(--m-bg);color:var(--m-text);border-radius:20px;
    box-shadow:0 20px 60px rgba(0,0,0,0.3);display:flex;flex-direction:column;
    transform:translateY(120%) scale(0.95); opacity:0; pointer-events:none;
    transition:transform .25s cubic-bezier(0.19,1,0.22,1), opacity .2s;
  }
  #mta-card.open{transform:translateY(0) scale(1); opacity:1; pointer-events:auto}
  
  /* HEADER */
  #mta-head{background:linear-gradient(130deg,var(--m-blue),#00C6FF);padding:12px 16px;color:#fff;border-radius:20px 20px 0 0;display:flex;align-items:center;gap:10px;box-shadow:0 4px 12px rgba(0,0,0,0.1)}
  #mta-head .avt{width:34px;height:34px;border-radius:50%;background:rgba(255,255,255,0.2);display:flex;align-items:center;justify-content:center}
  #mta-head .name{font-weight:700;font-size:15px}
  #mta-head .stt{font-size:11px;opacity:0.9;display:flex;align-items:center;gap:4px}
  #mta-head .dot{width:6px;height:6px;background:#3fff6c;border-radius:50%}
  #mta-head .act{margin-left:auto;background:rgba(255,255,255,0.15);width:30px;height:30px;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#fff;text-decoration:none;font-size:13px;border:none;cursor:pointer}
  
  /* BODY */
  #mta-body{flex:1;overflow-y:auto;padding:14px;background:#f5f7f9;scroll-behavior:smooth;-webkit-overflow-scrolling:touch}
  .m-msg{max-width:80%;padding:8px 12px;margin:4px 0;border-radius:18px;font-size:14px;line-height:1.5;word-break:break-word;animation:mta-in .2s ease-out}
  .m-msg.bot{background:#fff;align-self:flex-start;border-bottom-left-radius:4px;box-shadow:0 1px 2px rgba(0,0,0,0.05);color:#1e293b}
  .m-msg.user{background:var(--m-blue);color:#fff;margin-left:auto;border-bottom-right-radius:4px}
  @keyframes mta-in{from{opacity:0;transform:translateY(5px)}to{opacity:1;transform:translateY(0)}}
  
  /* TYPING */
  #mta-typing{display:inline-flex;gap:4px;background:#fff;padding:8px 12px;border-radius:18px;margin-bottom:8px;box-shadow:0 1px 2px rgba(0,0,0,0.05)}
  #mta-typing span{width:5px;height:5px;background:#999;border-radius:50%;animation:mta-type 1s infinite}
  #mta-typing span:nth-child(2){animation-delay:0.2s}
  #mta-typing span:nth-child(3){animation-delay:0.4s}
  @keyframes mta-type{0%,100%{transform:translateY(0)}50%{transform:translateY(-3px)}}

  /* TAGS & INPUT */
  #mta-tags{padding:8px;background:#fff;white-space:nowrap;overflow-x:auto;border-top:1px solid #eee}
  #mta-tags button{background:#eff6ff;border:1px solid #dbeafe;padding:6px 12px;border-radius:20px;margin-right:8px;font-size:13px;color:#1e40af;cursor:pointer;transition:all .1s}
  #mta-tags button:hover{background:#dbeafe}
  
  #mta-input{padding:10px;background:#fff;border-top:1px solid #f1f5f9;display:flex;gap:8px;align-items:center}
  #mta-in{flex:1;height:var(--m-in-h);border-radius:24px;border:1px solid #cbd5e1;padding:0 16px;font-size:var(--m-in-fs);outline:none;background:#f8fafc;color:#0f172a}
  #mta-in:focus{border-color:var(--m-blue);background:#fff}
  #mta-send{width:40px;height:40px;border-radius:50%;border:none;background:var(--m-blue);color:#fff;font-size:16px;cursor:pointer;display:flex;align-items:center;justify-content:center}
  
  /* MOBILE KEYBOARD HANDLING */
  #mta-root.kb-active{bottom:env(safe-area-inset-bottom,0)}
  #mta-root.kb-active #mta-card{height:calc(100vh - 10px - env(safe-area-inset-bottom,0)); bottom:0}
  
  /* DARK MODE */
  @media(prefers-color-scheme:dark){
    :root{--m-bg:#1e293b; --m-text:#f1f5f9}
    #mta-body{background:#0f172a}
    .m-msg.bot{background:#334155;color:#f1f5f9}
    #mta-input, #mta-tags{background:#1e293b;border-color:#334155}
    #mta-in{background:#334155;border-color:#475569;color:#fff}
    #mta-tags button{background:#334155;border-color:#475569;color:#bfdbfe}
  }
  @media(max-width:480px){ #mta-card{width:100%;right:0;left:0;margin:0;border-radius:16px 16px 0 0} }
  `;

  const HTML = `
  <div id="mta-root">
    <button id="mta-bubble" aria-label="Chat">💬</button>
    <div id="mta-backdrop"></div>
    <div id="mta-card">
      <div id="mta-head">
        <div class="avt">${CFG.avatar}</div>
        <div class="info">
          <div class="name">${CFG.brand}</div>
          <div class="stt"><span class="dot"></span> Online</div>
        </div>
        <button class="act" id="mta-close">✕</button>
      </div>
      <div id="mta-body"></div>
      <div id="mta-tags"></div>
      <div id="mta-input">
        <input id="mta-in" placeholder="Nhắn tin..." autocomplete="off">
        <button id="mta-send">➤</button>
      </div>
    </div>
  </div>`;

  /* ================= CORE: CRAWLER & DATA (From v38) ================= */
  
  // 1. Fetch & Parse
  async function fetchText(url){
    const ctl = new AbortController(); const id = setTimeout(()=>ctl.abort(), CFG.fetchTimeoutMs);
    try{
      const res = await fetch(url, {signal: ctl.signal, credentials:'omit'});
      clearTimeout(id); return res.ok ? await res.text() : null;
    }catch{ clearTimeout(id); return null; }
  }
  function parseXML(t){ try{ return (new DOMParser()).parseFromString(t,'text/xml'); }catch{ return null; } }
  function parseHTML(t){ try{ return (new DOMParser()).parseFromString(t,'text/html'); }catch{ return null; } }

  // 2. Auto Price Extraction
  function extractPrices(txt, url){
    if(!CFG.smart.autoPriceLearn) return;
    const clean = txt.replace(/<[^>]+>/g,' ').replace(/\s+/g,' ');
    const reNum = /(\d{1,3}(?:[\.\,]\d{3})+|\d{5,})(?:\s*(?:vnđ|vnd|đ|d|k))?/i;
    const models = [
      {k:/\bvision\b/i, t:'vision'}, {k:/air\s*blade|airblade/i, t:'air blade'},
      {k:/50\s*cc/i, t:'50cc'}, {k:/côn\s*tay|exciter|winner/i, t:'xe côn tay'},
      {k:/xe\s*số|wave|sirius/i, t:'xe số'}, {k:/xe\s*ga|lead|janus/i, t:'xe ga'}
    ];
    
    // Scan text blocks
    const lines = clean.split(/[\n\.•\-–]/);
    const found = [];
    for(const line of lines){
      const mType = models.find(x => x.k.test(line));
      if(!mType) continue;
      const mPrice = line.match(reNum);
      if(!mPrice) continue;
      
      let val = mPrice[1].replace(/[^\d]/g,'');
      if(/k\b/i.test(line) && parseInt(val)<10000) val += "000";
      const p = parseInt(val);
      if(p > 50000 && p < 10000000) { // Filter logic
        found.push({type: mType.t, price: p, url: url, ts: nowSec()});
      }
    }
    if(found.length){
      const db = safe(localStorage.getItem(K.autoprices)) || [];
      db.push(...found);
      localStorage.setItem(K.autoprices, JSON.stringify(db.slice(-500))); // Giữ 500 giá mới nhất
    }
  }

  // 3. Crawler Logic
  async function readSitemap(url){
    const xml = await fetchText(url); if(!xml) return [];
    const doc = parseXML(xml); if(!doc) return [];
    const locs = Array.from(doc.querySelectorAll('loc')).map(l=>l.textContent.trim());
    // Đệ quy nếu là sitemap index
    let urls = [];
    for(const l of locs){
       if(/\.xml$/i.test(l) && urls.length < 10) urls.push(...(await readSitemap(l)));
       else urls.push(l);
    }
    return urls;
  }

  async function learnSites(origins){
    const cache = safe(localStorage.getItem(K.learn)) || {};
    let totalPages = 0;

    for(const origin of Array.from(new Set(origins))){
      const key = new URL(origin).origin;
      if(cache[key] && (nowSec() - cache[key].ts) < CFG.refreshHours*3600) continue;

      let urls = [];
      try{
        urls = await readSitemap(key+'/sitemap.xml');
        if(!urls.length){ // Fallback crawl
           const html = await fetchText(key);
           const doc = parseHTML(html);
           if(doc) urls = Array.from(doc.querySelectorAll('a[href]')).map(a=>a.href).filter(u=>u.startsWith(key));
        }
      }catch{}

      const pages = [];
      const unique = Array.from(new Set(urls)).slice(0, CFG.maxPagesPerDomain);
      
      for(const u of unique){
        const txt = await fetchText(u); if(!txt) continue;
        if(/noindex/i.test(txt)) continue;
        
        let title = (txt.match(/<title>(.*?)<\/title>/i)||[])[1]||"";
        let desc = (txt.match(/name="description" content="(.*?)"/i)||[])[1]||"";
        if(!desc) desc = txt.replace(/<[^>]+>/g,' ').slice(0, 600);
        
        extractPrices(txt, u); // Auto Learn Price
        
        pages.push({url: u, title: naturalize(title), text: naturalize(desc)});
        await sleep(CFG.fetchPauseMs);
      }

      if(pages.length){
        cache[key] = {ts: nowSec(), pages};
        totalPages += pages.length;
      }
    }
    localStorage.setItem(K.learn, JSON.stringify(cache));
    if(CFG.debug) console.log(`MotoAI v41: Learned ${totalPages} new pages.`);
  }

  /* ================= INTELLIGENCE: SEARCH & NLP ================= */
  
  function tk(s){ return (s||"").toLowerCase().normalize('NFC').replace(/[^\p{L}\p{N}]+/gu,' ').split(/\s+/).filter(Boolean); }

  function searchIndex(query){
    const cache = safe(localStorage.getItem(K.learn)) || {};
    const allDocs = [];
    Object.values(cache).forEach(site => (site.pages||[]).forEach(p => allDocs.push(p)));
    if(!allDocs.length) return null;

    // BM25 Simplified
    const qToks = tk(query);
    const scored = allDocs.map(d => {
      const dToks = tk(d.title + " " + d.text);
      let score = 0;
      qToks.forEach(t => { if(dToks.includes(t)) score += 1; });
      // Boost nếu khớp title
      if(d.title.toLowerCase().includes(query.toLowerCase())) score += 5;
      return { ...d, score };
    }).filter(x => x.score > 0).sort((a,b) => b.score - a.score);

    return scored[0] || null;
  }

  // Bảng giá cơ sở (Sẽ được cập nhật bởi AutoPrice)
  const PRICE_TABLE = {
    'xe số':      { d:150000, w:600000, m:1000000 },
    'xe ga':      { d:180000, w:800000, m:1500000 },
    'vision':     { d:200000, w:850000, m:1700000 },
    'air blade':  { d:220000, w:900000, m:1900000 },
    'xe côn tay': { d:300000, w:1200000, m:null },
    '50cc':       { d:200000, w:800000, m:1600000 }
  };

  /* ================= ANSWER GENERATOR ================= */
  
  function detectIntent(t){
    return {
      price:   /(giá|bao nhiêu|price|cost|rent)/i.test(t),
      docs:    /(thủ tục|giấy tờ|cccd|passport|license|document)/i.test(t),
      contact: /(liên hệ|zalo|gọi|phone|call|địa chỉ|map|location)/i.test(t),
      hello:   /(chào|hi|hello|alo)/i.test(t)
    };
  }

  async function getBotResponse(userText){
    const lang = detectLang(userText);
    const intent = detectIntent(userText);
    const qLow = userText.toLowerCase();

    // 1. Contact (Quick)
    if(intent.contact){
      return lang === 'vi' 
        ? `Anh/chị liên hệ Hotline: ${CFG.phone} hoặc Zalo: ${CFG.zalo} để được hỗ trợ ngay ạ. Địa chỉ bên em có trên bản đồ.`
        : `Please contact us via Hotline: ${CFG.phone} or Zalo: ${CFG.zalo}. You can also check our location on the map.`;
    }

    // 2. Documents
    if(intent.docs){
      return lang === 'vi'
        ? `Thủ tục đơn giản: Chỉ cần CCCD/Hộ chiếu gốc + cọc (1-3 triệu tùy xe). Bên em có giao xe tận nơi ạ.`
        : `Simple requirements: Original Passport/ID + Deposit (1-3M VND). We offer delivery service.`;
    }

    // 3. Pricing (Hybrid: Hardcode + AutoLearn)
    if(intent.price){
      // Cố gắng update giá từ auto learn
      try{
         const db = safe(localStorage.getItem(K.autoprices))||[];
         if(db.length){
            // Logic tính trung bình giá (demo đơn giản)
            // Có thể mở rộng để tính percentile
         }
      }catch{}

      let type = 'xe ga';
      if(/số|wave|sirius|blade/i.test(qLow)) type = 'xe số';
      if(/vision/i.test(qLow)) type = 'vision';
      if(/air|ab/i.test(qLow)) type = 'air blade';
      if(/côn|exciter/i.test(qLow)) type = 'xe côn tay';

      const p = PRICE_TABLE[type] || PRICE_TABLE['xe ga'];
      const priceStr = `${nfVND(p.d)}đ/ngày, ${nfVND(p.w)}đ/tuần`;
      
      return lang === 'vi'
        ? `Giá thuê ${type} bên em khoảng ${priceStr}. Thuê tháng giá tốt hơn. Anh/chị dự định đi bao lâu ạ?`
        : `Rental price for ${type} is around ${priceStr}. Monthly rental is cheaper. How long do you need it?`;
    }

    // 4. Fallback: Search Index (The "Brain" part)
    const hit = searchIndex(userText);
    if(hit){
      const snippet = hit.text.slice(0, 180) + "...";
      return lang === 'vi'
        ? `Em tìm thấy thông tin này: "${snippet}" (Chi tiết: ${hit.title})`
        : `I found this info: "${snippet}"`;
    }

    // 5. Greetings / Unknown
    return lang === 'vi'
      ? `Chào bạn 👋, mình là trợ lý ảo của ${CFG.brand}. Bạn cần thuê xe ga, xe số hay tư vấn thủ tục?`
      : `Hello 👋, I am ${CFG.brand}'s assistant. Do you need a scooter, a manual bike, or help with documents?`;
  }

  /* ================= UI INTERACTION (From v40) ================= */
  
  function addMsg(role, text){
    if(!text) return;
    const box = $('#mta-body');
    const div = document.createElement('div');
    div.className = `m-msg ${role}`;
    div.innerHTML = text.replace(/\n/g, '<br>'); // Hỗ trợ xuống dòng
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
  }

  function showTyping(show){
    const box = $('#mta-body');
    const ex = $('#mta-typing');
    if(show){
      if(!ex){
        const d = document.createElement('div'); d.id = 'mta-typing';
        d.innerHTML = `<span></span><span></span><span></span>`;
        box.appendChild(d);
      }
      box.scrollTop = box.scrollHeight;
    } else {
      if(ex) ex.remove();
    }
  }

  async function handleUserSend(){
    const inp = $('#mta-in');
    const txt = inp.value.trim();
    if(!txt) return;

    inp.value = '';
    $('#mta-send').disabled = true;
    addMsg('user', txt);

    // AI thinking simulation
    showTyping(true);
    await sleep(600 + Math.random() * 800); // Delay cho tự nhiên
    
    const ans = await getBotResponse(txt);
    showTyping(false);
    addMsg('bot', ans);
    $('#mta-send').disabled = false;
  }

  function setTags(lang){
    const div = $('#mta-tags');
    if(lang === 'vi'){
      div.innerHTML = `
        <button data-q="Giá thuê xe ga bao nhiêu?">💰 Giá thuê xe</button>
        <button data-q="Thủ tục cần giấy tờ gì?">📄 Thủ tục</button>
        <button data-q="Địa chỉ cửa hàng ở đâu?">📍 Địa chỉ</button>
      `;
    } else {
      div.innerHTML = `
        <button data-q="How much for a scooter?">💰 Prices</button>
        <button data-q="What documents do I need?">📄 Documents</button>
        <button data-q="Where is your shop?">📍 Location</button>
      `;
    }
    div.querySelectorAll('button').forEach(b => {
      b.onclick = () => { $('#mta-in').value = b.dataset.q; handleUserSend(); }
    });
  }

  /* ================= BOOTSTRAP ================= */
  
  function init(){
    // Inject CSS & HTML
    const s = document.createElement('style'); s.textContent = CSS; document.head.appendChild(s);
    const c = document.createElement('div'); c.innerHTML = HTML; document.body.appendChild(c.firstElementChild);

    // Event Bindings
    const root = $('#mta-root');
    const card = $('#mta-card');
    const back = $('#mta-backdrop');
    
    const open = () => {
       card.classList.add('open'); back.classList.add('show');
       setTimeout(()=> $('#mta-in').focus(), 100);
    };
    const close = () => {
       card.classList.remove('open'); back.classList.remove('show');
       if(root.classList.contains('kb-active')) $('#mta-in').blur();
    };

    $('#mta-bubble').onclick = open;
    $('#mta-close').onclick = close;
    $('#mta-backdrop').onclick = close;
    $('#mta-send').onclick = handleUserSend;
    $('#mta-in').onkeydown = (e) => { if(e.key === 'Enter') handleUserSend(); }

    // VisualViewport Fix for iOS Keyboard (From v40)
    if(window.visualViewport){
      window.visualViewport.addEventListener('resize', () => {
        // Nếu chiều cao viewport giảm đáng kể -> bàn phím đang mở
        if(window.visualViewport.height < window.innerHeight * 0.85){
           root.classList.add('kb-active');
           $('#mta-body').scrollTop = $('#mta-body').scrollHeight;
        } else {
           root.classList.remove('kb-active');
        }
      });
    }

    // Init Logic
    if(CFG.autolearn) learnSites(CFG.extraSites);
    setTags('vi'); // Mặc định tag tiếng Việt
    
    // Check session cũ (để giữ tin nhắn) - Simplified version
    const sess = safe(sessionStorage.getItem(K.sess));
    if(!sess) addMsg('bot', `Chào bạn! Mình là trợ lý ảo của ${CFG.brand}. Mình có thể giúp gì cho bạn?`);
  }

  if(document.readyState === 'complete') init();
  else window.addEventListener('load', init);

  /* Public Interface */
  window.MotoAI_v41 = {
    open: () => $('#mta-bubble').click(),
    learnNow: () => { console.log("Force learning..."); learnSites(CFG.extraSites); },
    clear: () => { localStorage.removeItem(K.learn); localStorage.removeItem(K.autoprices); console.log("Cleaned."); }
  };

})();
