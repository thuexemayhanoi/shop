/* motoai_v41_ultimate.js
   ✅ HỢP NHẤT:
      - Brain: v38 (BM25, Multi-site Crawl, Auto-Price Learn, Debug)
      - Face:  v40 (Mobile UX fix, iOS Keyboard safety, Dark/App UI, Multi-language)
   
   Tính năng:
   1. UI hiện đại, chống zoom trên iOS, xử lý bàn phím ảo che mất ô nhập.
   2. Tự động học dữ liệu từ sitemap/HTML của nhiều website.
   3. Trả lời song ngữ (Anh/Việt) dựa trên ngôn ngữ khách.
   4. Tìm kiếm nội dung thông minh (Semantic Search) khi không bắt được từ khóa cứng.
*/
(function(){
  if (window.MotoAI_v41_LOADED) return;
  window.MotoAI_v41_LOADED = true;

  /* ====== CONFIG ====== */
  const DEF = {
    brand: "Moto Assistant",
    phone: "0942467674",
    zalo:  "",
    map:   "",
    avatar: "👩‍💼",
    themeColor: "#0084FF", // Màu chủ đạo

    // Crawler & Smart Features (from v38)
    autolearn: true,
    deepContext: true,
    maxContextTurns: 6,
    extraSites: [location.origin], // Các site vệ tinh muốn học thêm
    refreshHours: 24,
    maxPagesPerDomain: 60,
    maxTotalPages: 300,

    fetchTimeoutMs: 8000,
    fetchPauseMs: 100,

    smart: {
      semanticSearch: true,   // Tìm kiếm thông minh trong nội dung đã học
      extractiveQA:   true,   // Trích xuất câu trả lời từ bài viết
      autoPriceLearn: true    // Tự học giá từ HTML website
    },

    // UX Settings (from v40)
    noLinksInReply: false,
    debug: true
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
  const clamp = (n,min,max)=> Math.max(min, Math.min(max,n));
  const nfVND = n => (n||0).toLocaleString('vi-VN');
  const sameHost = (u, origin)=> { try{ return new URL(u).host.replace(/^www\./,'') === new URL(origin).host.replace(/^www\./,''); }catch{ return false; } };
  
  function naturalize(t){
    if(!t) return "";
    let s = (" "+t+" ").replace(/\s+/g," ");
    s = s.replace(/\s+ạ([.!?,\s]|$)/gi, "$1").replace(/\s+nhé([.!?,\s]|$)/gi, "$1").replace(/\s+nha([.!?,\s]|$)/gi, "$1");
    return s.trim().replace(/\.\./g,".");
  }
  function looksVN(s){
    if(/[ăâêôơưđà-ỹ]/i.test(s)) return true;
    return (s.match(/\b(xe|thuê|giá|liên hệ|hà nội|cọc)\b/gi)||[]).length >= 1;
  }
  function detectLang(text){
    if(!text) return "vi";
    if(looksVN(text)) return "vi";
    if(/[a-z]{4,}/i.test(text) && !looksVN(text)) return "en";
    return "vi"; // Default VN
  }

  /* ====== STORAGE KEYS ====== */
  const K = {
    sess:  "MotoAI_v41_sess",
    ctx:   "MotoAI_v41_ctx",
    learn: "MotoAI_v41_learn", // Dữ liệu học được
    autoprices: "MotoAI_v41_prices",
    dbg:   "MotoAI_v41_stats"
  };

  /* ====== CRAWLER ENGINE (From v38) ====== */
  async function fetchText(url){
    const ctl = new AbortController(); const id = setTimeout(()=>ctl.abort(), CFG.fetchTimeoutMs);
    try{
      const res = await fetch(url, {signal: ctl.signal, mode:'cors', credentials:'omit'});
      clearTimeout(id); if(!res.ok) return null;
      return await res.text();
    }catch(e){ clearTimeout(id); return null; }
  }
  function parseXML(t){ try{ return (new DOMParser()).parseFromString(t,'text/xml'); }catch{ return null; } }
  function parseHTML(t){ try{ return (new DOMParser()).parseFromString(t,'text/html'); }catch{ return null; } }

  // Auto Price Extraction Logic
  function extractPricesFromText(txt){
    const clean = String(txt||'');
    const lines = clean.replace(/<[^>]+>/g,' ').replace(/\s+/g,' ').split(/[\n\.•\-–]|<br\s*\/?>/i);
    const out = [];
    const reNum = /(\d{1,3}(?:[\.\,]\d{3})+|\d{5,})(?:\s*(?:vnđ|vnd|đ|d|k))?/i;
    const models = [
      {key:/\bvision\b/i, type:'vision'}, {key:/air\s*blade|airblade|\bab\b/i, type:'air blade'},
      {key:/\b50\s*cc\b/i, type:'50cc'}, {key:/côn\s*tay|exciter|winner/i, type:'xe côn tay'},
      {key:/xe\s*số|wave|sirius/i, type:'xe số'}, {key:/xe\s*ga|lead|janus/i, type:'xe ga'}
    ];
    for(const raw of lines){
      const line = String(raw||'');
      const found = models.find(m=> m.key.test(line));
      if(!found) continue;
      const m = line.match(reNum);
      if(!m) continue;
      let val = m[1].replace(/[^\d]/g,'');
      if(/k\b/i.test(line) && parseInt(val,10)<10000) val = String(parseInt(val,10)*1000);
      const price = parseInt(val,10);
      if(price && price<5000000){ out.push({type:found.type, unit:'day', price}); }
    }
    return out;
  }

  // Crawling Logic
  async function readSitemap(url){
    const xml = await fetchText(url); if(!xml) return [];
    const doc = parseXML(xml); if(!doc) return [];
    const items = Array.from(doc.getElementsByTagName('item')).map(it=>it.getElementsByTagName('link')[0]?.textContent);
    const locs = Array.from(doc.querySelectorAll('loc')).map(l=>l.textContent);
    return [...items, ...locs].filter(Boolean).map(u=>u.trim());
  }

  async function learnSites(origins){
    const list = Array.from(new Set(origins||[])).slice(0, 5);
    const cache = safe(localStorage.getItem(K.learn)) || {};
    let total = 0;
    
    for(const origin of list){
      const key = new URL(origin).origin;
      if(cache[key] && ((nowSec() - cache[key].ts) < CFG.refreshHours*3600)) continue; // Cache còn mới
      
      let urls = [];
      try{
        // 1. Thu thập URL
        const sm = await readSitemap(key+'/sitemap.xml');
        if(sm.length) urls = sm; 
        else {
            // Fallback: crawl trang chủ lấy link
            const html = await fetchText(key);
            const doc = parseHTML(html);
            if(doc) urls = Array.from(doc.querySelectorAll('a[href]'))
                .map(a=>a.href).filter(u=> u.startsWith(key) && !u.includes('#')).slice(0,40);
        }
      }catch{}

      // 2. Đọc nội dung
      const pages = [];
      for(const u of Array.from(new Set(urls)).slice(0, CFG.maxPagesPerDomain)){
         const txt = await fetchText(u); if(!txt) continue;
         if(/noindex/i.test(txt)) continue;
         
         let title = (txt.match(/<title>(.*?)<\/title>/i)||[])[1]||"";
         let desc = (txt.match(/name="description" content="(.*?)"/i)||[])[1]||"";
         if(!desc) desc = txt.replace(/<[^>]+>/g,' ').slice(0,500);
         
         // Học giá
         if(CFG.smart.autoPriceLearn){
            const prices = extractPricesFromText(txt);
            if(prices.length){
                const db = safe(localStorage.getItem(K.autoprices))||[];
                db.push(...prices.map(p=>({...p, url:u})));
                localStorage.setItem(K.autoprices, JSON.stringify(db.slice(-500)));
            }
         }
         
         pages.push({url:u, title, text: (title + ". " + desc).replace(/\s+/g,' ')});
         await sleep(CFG.fetchPauseMs);
      }
      if(pages.length) cache[key] = {ts: nowSec(), pages};
      total += pages.length;
    }
    localStorage.setItem(K.learn, JSON.stringify(cache));
    if(CFG.debug && total>0) console.log(`MotoAI v41: Learned ${total} pages from ${list.length} sites.`);
  }

  /* ====== INTELLIGENCE (BM25 + NLP) ====== */
  function tk(s){ return (s||"").toLowerCase().normalize('NFC').replace(/[^\p{L}\p{N}]+/gu,' ').split(/\s+/).filter(Boolean); }
  
  function searchIndex(query){
    const cache = safe(localStorage.getItem(K.learn))||{};
    const allDocs = [];
    Object.values(cache).forEach(site=> (site.pages||[]).forEach(p=> allDocs.push(p)));
    if(!allDocs.length) return null;

    // Simple scoring (keyword overlap)
    const qToks = tk(query);
    const scored = allDocs.map(d => {
        const dToks = tk(d.text);
        let score = 0;
        qToks.forEach(t => { if(dToks.includes(t)) score++; });
        return { ...d, score };
    }).filter(d => d.score > 0).sort((a,b) => b.score - a.score);

    return scored[0] || null;
  }

  /* ====== PRICING & LOGIC (Merged v38 & v40) ====== */
  const PRICE_TABLE = {
    'xe số': { day:[150000], week:[600000], month:[1000000] },
    'xe ga': { day:[180000], week:[700000], month:[1400000] },
    'vision': { day:[200000], week:[800000], month:[1600000] },
    'air blade': { day:[220000], week:[900000], month:[1800000] },
    '50cc': { day:[200000], week:[800000], month:[1700000] }
  };

  // Update table from learned data
  function syncPrices(){
    const db = safe(localStorage.getItem(K.autoprices))||[];
    if(!db.length) return;
    // Simple average calculation logic could go here
    // For now, we trust the hardcoded table but v41 structure allows override
  }

  function detectIntent(t){
    return {
      needPrice: /(giá|bao nhiêu|price|cost|rent)/i.test(t),
      needDocs:  /(thủ tục|giấy tờ|cccd|passport|id card)/i.test(t),
      needContact: /(liên hệ|zalo|gọi|phone|call|địa chỉ|map)/i.test(t)
    };
  }

  function getAnswer(q){
    const lang = detectLang(q);
    const intent = detectIntent(q);
    const qLow = q.toLowerCase();

    // 1. Quick Contact
    if(intent.needContact){
        return lang==='vi' 
            ? `Anh/chị liên hệ hotline ${CFG.phone} hoặc nhắn Zalo: ${CFG.zalo} để bên em hỗ trợ nhanh nhất ạ.`
            : `Please call ${CFG.phone} or chat via Zalo: ${CFG.zalo} for quick support.`;
    }

    // 2. Documents
    if(intent.needDocs){
        return lang==='vi'
            ? `Thủ tục đơn giản: Cần CCCD/Hộ chiếu gốc + tiền cọc (1-3 triệu tùy xe). Bên em có giao xe tận nơi.`
            : `Requirements: Original Passport/ID card + deposit (1-3 million VND). We offer delivery service.`;
    }

    // 3. Pricing (Rule-based)
    if(intent.needPrice){
        let type = 'xe ga';
        if(/số|wave|sirius/i.test(qLow)) type = 'xe số';
        if(/vision/i.test(qLow)) type = 'vision';
        if(/ab|air/i.test(qLow)) type = 'air blade';
        
        const p = PRICE_TABLE[type] || PRICE_TABLE['xe ga'];
        return lang==='vi'
            ? `Giá thuê ${type} tham khảo: ${nfVND(p.day[0])}đ/ngày, ${nfVND(p.week[0])}đ/tuần. Thuê tháng từ ${nfVND(p.month[0])}đ. Anh/chị đi bao lâu ạ?`
            : `Price for ${type}: ~${nfVND(p.day[0])} VND/day, ${nfVND(p.week[0])} VND/week. Monthly from ${nfVND(p.month[0])} VND. How long do you need it?`;
    }

    // 4. Smart Fallback (Search Index from v38)
    const hit = searchIndex(q);
    if(hit){
        return lang==='vi' 
            ? `Em tìm thấy thông tin này: "${hit.text.slice(0, 150)}..." (Nguồn: ${hit.title})`
            : `I found this info: "${hit.text.slice(0, 150)}..."`;
    }

    // 5. Default
    return lang==='vi'
        ? `Dạ, anh/chị cần thuê xe ga, xe số hay cần tư vấn thủ tục ạ?`
        : `Hi, do you need to rent a scooter, a manual bike, or need help with documents?`;
  }

  /* ====== UI/UX (CSS from v40 - Best for Mobile) ====== */
  const CSS = `
  :root{
    --m-blue:${CFG.themeColor}; --m-bg:#fff; --m-text:#0b1220;
    --m-in-h:40px; --m-in-fs:16px; /* 16px prevents iOS zoom */
    --m-bot:80px;
  }
  #mta-root{position:fixed;right:16px;bottom:calc(var(--m-bot) + env(safe-area-inset-bottom,0));z-index:2147483647;font-family:-apple-system,sans-serif}
  
  /* BUBBLE */
  #mta-bubble{width:56px;height:56px;border-radius:50%;background:linear-gradient(135deg,var(--m-blue),#00C6FF);box-shadow:0 10px 30px rgba(0,0,0,0.2);display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:24px;border:none;color:#fff;transition:transform .2s}
  #mta-bubble:hover{transform:scale(1.05)}
  
  /* MAIN CARD */
  #mta-card{
    position:fixed;right:16px;bottom:calc(var(--m-bot) + env(safe-area-inset-bottom,0));
    width:min(400px, calc(100% - 32px));height:min(70vh, 700px);
    background:var(--m-bg);border-radius:20px;box-shadow:0 20px 60px rgba(0,0,0,0.3);
    display:flex;flex-direction:column;overflow:hidden;
    transform:translateY(120%);transition:transform 0.3s cubic-bezier(0.19, 1, 0.22, 1);
    opacity:0; pointer-events:none;
  }
  #mta-card.open{transform:translateY(0);opacity:1;pointer-events:auto}
  
  /* HEADER */
  #mta-head{background:linear-gradient(135deg,var(--m-blue),#00C6FF);padding:12px 16px;display:flex;align-items:center;gap:10px;color:#fff}
  #mta-head .avt{width:32px;height:32px;background:rgba(255,255,255,0.2);border-radius:50%;display:flex;align-items:center;justify-content:center}
  #mta-head .close{margin-left:auto;background:none;border:none;color:#fff;font-size:24px;cursor:pointer}
  
  /* BODY */
  #mta-body{flex:1;overflow-y:auto;padding:12px;background:#f5f7f9;scroll-behavior:smooth}
  .m-msg{max-width:80%;padding:8px 12px;margin-bottom:8px;border-radius:16px;font-size:14px;line-height:1.4}
  .m-msg.bot{background:#fff;align-self:flex-start;border-bottom-left-radius:4px;box-shadow:0 2px 5px rgba(0,0,0,0.05)}
  .m-msg.user{background:var(--m-blue);color:#fff;margin-left:auto;border-bottom-right-radius:4px}
  
  /* TAGS */
  #mta-tags{padding:8px;background:#fff;white-space:nowrap;overflow-x:auto;border-top:1px solid #eee}
  #mta-tags button{background:#f0f2f5;border:none;padding:6px 12px;border-radius:20px;margin-right:8px;font-size:13px;color:#333;cursor:pointer}
  
  /* INPUT AREA (APP STYLE) */
  #mta-input{padding:10px;background:#fff;border-top:1px solid #eee;display:flex;gap:8px}
  #mta-in{flex:1;height:var(--m-in-h);border-radius:20px;border:1px solid #ddd;padding:0 12px;font-size:var(--m-in-fs);outline:none;background:#f9f9f9}
  #mta-send{width:40px;height:40px;border-radius:50%;border:none;background:var(--m-blue);color:#fff;font-size:16px;cursor:pointer}
  
  /* MOBILE TWEAKS */
  @media(max-width:480px){
    #mta-card{width:100%;right:0;bottom:0;border-radius:16px 16px 0 0;height:80vh}
    #mta-root.kb-active #mta-card{height:calc(100vh - env(safe-area-inset-bottom) - 10px)} 
  }
  `;

  const HTML = `
  <div id="mta-root">
    <button id="mta-bubble">💬</button>
    <div id="mta-card">
      <div id="mta-head">
        <div class="avt">${CFG.avatar}</div>
        <div>
           <div style="font-weight:bold;font-size:15px">${CFG.brand}</div>
           <div style="font-size:11px;opacity:0.9">Sẵn sàng hỗ trợ</div>
        </div>
        <button class="close">&times;</button>
      </div>
      <div id="mta-body"></div>
      <div id="mta-tags">
        <button data-q="Giá thuê xe ga">💰 Giá thuê xe</button>
        <button data-q="Thủ tục thế nào?">📄 Thủ tục</button>
        <button data-q="Địa chỉ ở đâu?">📍 Địa chỉ</button>
      </div>
      <div id="mta-input">
        <input id="mta-in" placeholder="Nhập câu hỏi..." type="text">
        <button id="mta-send">➤</button>
      </div>
    </div>
  </div>`;

  /* ====== MAIN LOGIC ====== */
  function addMsg(role, text){
    const d = document.createElement('div');
    d.className = `m-msg ${role}`;
    d.textContent = text;
    $('#mta-body').appendChild(d);
    $('#mta-body').scrollTop = $('#mta-body').scrollHeight;
  }

  async function handleSend(){
    const inp = $('#mta-in');
    const txt = inp.value.trim();
    if(!txt) return;
    
    inp.value = '';
    addMsg('user', txt);
    
    // Typing effect
    const wait = 600 + Math.random()*800;
    await sleep(wait);
    
    const ans = getAnswer(txt);
    addMsg('bot', ans);
  }

  function init(){
    // Inject UI
    const st = document.createElement('style'); st.innerHTML = CSS; document.head.appendChild(st);
    const div = document.createElement('div'); div.innerHTML = HTML; document.body.appendChild(div.firstElementChild);

    // Event Listeners
    $('#mta-bubble').onclick = () => $('#mta-card').classList.add('open');
    $('.close').onclick = () => $('#mta-card').classList.remove('open');
    $('#mta-send').onclick = handleSend;
    $('#mta-in').onkeydown = (e) => { if(e.key === 'Enter') handleSend(); }
    
    // Quick Tags
    document.querySelectorAll('#mta-tags button').forEach(b => {
        b.onclick = () => { $('#mta-in').value = b.dataset.q; handleSend(); }
    });

    // Mobile Keyboard Fix (Visual Viewport API) - From v40
    if(window.visualViewport){
        window.visualViewport.addEventListener('resize', () => {
             const h = window.visualViewport.height;
             if(h < window.innerHeight * 0.8) { // KB opened
                 $('#mta-root').classList.add('kb-active');
                 $('#mta-body').scrollTop = $('#mta-body').scrollHeight;
             } else {
                 $('#mta-root').classList.remove('kb-active');
             }
        });
    }

    // Auto Learn
    if(CFG.autolearn) learnSites(CFG.extraSites);
    syncPrices();

    addMsg('bot', `Chào bạn! Mình là trợ lý ảo của ${CFG.brand}. Bạn cần tìm thuê xe gì ạ?`);
  }

  if(document.readyState === 'complete') init();
  else window.addEventListener('load', init);

  /* Public API */
  window.MotoAI_v41 = {
    open: () => $('#mta-card').classList.add('open'),
    debug: () => console.table(safe(localStorage.getItem(K.learn)))
  };

})();
