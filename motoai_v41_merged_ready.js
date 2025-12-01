/* motoai_v41_merged_ready.js
   ✅ PHIÊN BẢN HỢP NHẤT HOÀN CHỈNH (v38 Logic + v40 UI):
   
   1. UI/UX:
      - Mobile-first, App-like UI.
      - Fix lỗi iOS: Chống zoom (font 16px), VisualViewport (keyboard đẩy input).
      - Backdrop tối, Toggle đóng/mở, Auto-focus.
   
   2. TRÍ TUỆ (CORE):
      - Crawler đa luồng: Ưu tiên moto_sitemap.json > sitemap_index.xml > Fallback crawl.
      - Search Engine: BM25 (xếp hạng văn bản) + Extractive QA (trích xuất câu trả lời ngắn).
      - Auto-Price: Học giá từ HTML -> Tính trung vị -> Cập nhật bảng giá realtime.
      - Context: Nhớ ngữ cảnh hội thoại (Deep Context).
      
   3. AN TOÀN:
      - Prune Cache: Tự động cắt giảm dữ liệu cũ để tránh tràn LocalStorage.
*/

(function(){
  if (window.MotoAI_v41_LOADED) return;
  window.MotoAI_v41_LOADED = true;

  /* ================= CONFIGURATION ================= */
  const DEF = {
    brand: "Moto Assistant",
    phone: "0942467674",
    zalo:  "", 
    map:   "",
    avatar: "👩‍💼",
    themeColor: "#0084FF",

    // --- CRAWLER & LEARNING ---
    autolearn: true,
    extraSites: [location.origin], 
    refreshHours: 24,
    maxPagesPerDomain: 60,   // Giới hạn số trang học mỗi domain
    maxTotalPages: 300,      // Tổng giới hạn toàn bộ cache
    fetchTimeoutMs: 8000,
    fetchPauseMs: 150,

    // --- SMART LOGIC ---
    smart: {
      semanticSearch: true,  // BM25
      extractiveQA:   true,  // Trích xuất câu trả lời
      autoPriceLearn: true   // Học giá tự động
    },

    // --- UX SETTINGS ---
    deepContext: true,       // Nhớ ngữ cảnh (hỏi 'giá bao nhiêu' hiểu là xe đang nói tới)
    maxContextTurns: 6,
    debug: true
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
  
  function naturalize(t){
    if (!t) return "";
    return (" " + t + " ").replace(/\s+/g," ")
      .replace(/\s+ạ([.!?,\s]|$)/gi, "$1")
      .replace(/\s+nhé([.!?,\s]|$)/gi, "$1")
      .replace(/\s+nha([.!?,\s]|$)/gi, "$1")
      .trim().replace(/\.\./g,".");
  }

  function detectLang(text){
    const s = String(text || "");
    if (!s.trim()) return "vi";
    if (/[ăâêôơưđà-ỹ]/i.test(s)) return "vi";
    // Nếu có nhiều từ tiếng Anh > 4 ký tự và không có dấu hiệu tiếng Việt
    if (/[a-z]{4,}/i.test(s) && !/[ăâêôơưđà-ỹ]/.test(s)) return "en";
    return "vi";
  }

  /* ================= STORAGE & SESSION ================= */
  const K = {
    sess:  "MotoAI_v41_sess",
    ctx:   "MotoAI_v41_ctx",
    learn: "MotoAI_v41_learn",
    autoprices: "MotoAI_v41_prices"
  };

  function getSess(){ return safe(sessionStorage.getItem(K.sess)) || []; }
  function saveSess(arr){ try{ sessionStorage.setItem(K.sess, JSON.stringify(arr.slice(-30))); }catch{} }
  function addSess(role, text){
    const arr = getSess();
    arr.push({role, text, t: Date.now()});
    saveSess(arr);
  }

  function getCtx(){ return safe(localStorage.getItem(K.ctx)) || {turns:[]}; }
  function pushCtx(delta){
    try{
      const ctx = getCtx();
      ctx.turns.push(Object.assign({t:Date.now()}, delta||{}));
      ctx.turns = ctx.turns.slice(-clamp(CFG.maxContextTurns, 3, 10));
      localStorage.setItem(K.ctx, JSON.stringify(ctx));
    }catch(e){}
  }

  /* ================= INTELLIGENCE ENGINE (BM25 + QA) ================= */
  
  function tkTokens(s){ 
    return (s||"").toLowerCase().normalize('NFC').replace(/[^\p{L}\p{N}]+/gu,' ').split(/\s+/).filter(t => t.length > 1); 
  }

  // 1. BM25 Search Algorithm
  function buildBM25(docs){
    const k1=1.5, b=0.75; 
    const df=new Map(), tf=new Map(); 
    let totalLen=0;
    
    docs.forEach(d=>{
      const toks = tkTokens(d.title + " " + d.text);
      totalLen += toks.length;
      const map = new Map();
      toks.forEach(t => map.set(t, (map.get(t)||0) + 1));
      tf.set(d.url, map); // Use URL as ID
      new Set(toks).forEach(t => df.set(t, (df.get(t)||0) + 1));
    });
    
    const N = docs.length || 1;
    const avgdl = totalLen / N;
    const idf = new Map();
    df.forEach((c,t)=> idf.set(t, Math.log(1 + (N - c + 0.5)/(c + 0.5))));
    
    function score(query, docId, docLen){
      const qToks = Array.from(new Set(tkTokens(query)));
      const map = tf.get(docId) || new Map();
      let s = 0;
      qToks.forEach(t => {
        const f = map.get(t) || 0;
        if(!f) return;
        const idfv = idf.get(t) || 0;
        s += idfv * (f * (k1 + 1)) / (f + k1 * (1 - b + b * (docLen / avgdl)));
      });
      return s;
    }
    return { score };
  }

  // 2. Extractive QA (Tìm câu trả lời tốt nhất trong văn bản)
  function bestSentences(text, query, k=1){
    const sents = String(text||'').replace(/\s+/g,' ').split(/(?<=[\.\!\?])\s+/);
    const qToks = new Set(tkTokens(query));
    
    const scored = sents.map(s => {
      const toks = tkTokens(s);
      if(toks.length < 3) return {s, score: 0}; // Bỏ câu quá ngắn
      let hit = 0;
      qToks.forEach(t => { if(toks.includes(t)) hit++; });
      // Thưởng cho câu ngắn gọn súc tích
      const lenp = Math.max(0.5, 15 / Math.max(15, toks.length)); 
      return { s, score: hit * lenp };
    }).filter(x => x.score > 0).sort((a,b) => b.score - a.score);
    
    return scored.slice(0, k).map(x => x.s);
  }

  function searchIndex(query){
    const cache = safe(localStorage.getItem(K.learn)) || {};
    const allDocs = [];
    Object.values(cache).forEach(site => (site.pages||[]).forEach(p => allDocs.push(p)));
    if(!allDocs.length) return null;

    // Run BM25
    const bm25 = buildBM25(allDocs);
    const scored = allDocs.map(d => {
      const len = tkTokens(d.title + " " + d.text).length || 1;
      const s = bm25.score(query, d.url, len);
      // Boost nhẹ nếu title khớp query
      const boost = d.title.toLowerCase().includes(query.toLowerCase()) ? 2 : 0;
      return { ...d, score: s + boost };
    }).filter(d => d.score > 1.5).sort((a,b) => b.score - a.score);

    return scored[0] || null;
  }

  /* ================= CRAWLER & DATA (Threaded) ================= */
  
  async function fetchText(url){
    const ctl = new AbortController(); 
    const id = setTimeout(()=>ctl.abort(), CFG.fetchTimeoutMs);
    try{
      const res = await fetch(url, {signal: ctl.signal, credentials:'omit'});
      clearTimeout(id); 
      return res.ok ? await res.text() : null;
    }catch(e){ 
      clearTimeout(id); 
      // CORS warning fallback
      if(CFG.debug && e.name !== 'AbortError') console.warn("MotoAI fetch error (likely CORS):", url);
      return null; 
    }
  }
  function parseXML(t){ try{ return (new DOMParser()).parseFromString(t,'text/xml'); }catch{ return null; } }
  function parseHTML(t){ try{ return (new DOMParser()).parseFromString(t,'text/html'); }catch{ return null; } }

  // Extract Price from Text
  function extractPrices(txt, url){
    if(!CFG.smart.autoPriceLearn) return;
    const clean = txt.replace(/<[^>]+>/g,' ').replace(/\s+/g,' ');
    const reNum = /(\d{1,3}(?:[\.\,]\d{3})+|\d{5,})(?:\s*(?:vnđ|vnd|đ|d|k))?/i;
    const models = [
      {k:/\bvision\b/i, t:'vision'}, {k:/air\s*blade|airblade/i, t:'air blade'},
      {k:/50\s*cc/i, t:'50cc'}, {k:/côn\s*tay|exciter|winner/i, t:'xe côn tay'},
      {k:/xe\s*số|wave|sirius/i, t:'xe số'}, {k:/xe\s*ga|lead|janus/i, t:'xe ga'}
    ];
    
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
      if(p > 50000 && p < 10000000) {
        found.push({type: mType.t, price: p, url: url, ts: nowSec()});
      }
    }
    if(found.length){
      const db = safe(localStorage.getItem(K.autoprices)) || [];
      db.push(...found);
      localStorage.setItem(K.autoprices, JSON.stringify(db.slice(-600))); // Keep 600 latest
    }
  }

  // Advanced Sitemap Reader (JSON + XML Index)
  async function tryMotoJSON(origin){
    try{
      const jurl = origin.replace(/\/$/,'') + '/moto_sitemap.json';
      const r = await fetch(jurl);
      if(!r.ok) return [];
      const json = await r.json();
      return [...(json.categories?.pages?.list||[]), ...(json.categories?.datasets?.list||[])];
    }catch{ return []; }
  }

  async function readSitemapAll(url){
    const xml = await fetchText(url); if(!xml) return [];
    const doc = parseXML(xml); if(!doc) return [];
    // Check sitemap index
    const sitems = Array.from(doc.getElementsByTagName('sitemap')).map(s=> s.getElementsByTagName('loc')[0]?.textContent).filter(Boolean);
    if(sitems.length){
      const out = [];
      for(const s of sitems){ try{ const child = await readSitemapAll(s); if(child) out.push(...child); }catch{} }
      return out;
    }
    // Check urlset
    const urls = Array.from(doc.getElementsByTagName('url')).map(u=> u.getElementsByTagName('loc')[0]?.textContent).filter(Boolean);
    return urls.map(u=>u.trim());
  }

  function pruneLearnCache(){
    try{
      const cache = safe(localStorage.getItem(K.learn)) || {};
      const out = {};
      let total = 0;
      Object.keys(cache).forEach(k=>{
        // Keep limited pages per domain & limit text length
        const pages = (cache[k].pages||[]).slice(0, CFG.maxPagesPerDomain).map(p=>({
          url: p.url, title: p.title, text: (p.text||'').slice(0, 3000)
        }));
        out[k] = {ts: cache[k].ts, pages};
        total += pages.length;
      });
      localStorage.setItem(K.learn, JSON.stringify(out));
      if(CFG.debug) console.log('MotoAI: Pruned cache, current pages:', total);
    }catch(e){}
  }

  async function learnSites(origins){
    const cache = safe(localStorage.getItem(K.learn)) || {};
    
    for(const origin of Array.from(new Set(origins))){
      const key = new URL(origin).origin;
      if(cache[key] && (nowSec() - cache[key].ts) < CFG.refreshHours*3600) continue;

      let urls = await tryMotoJSON(key);
      if(!urls.length){
        try { urls = await readSitemapAll(key+'/sitemap.xml'); } catch{}
      }
      if(!urls.length || urls.length < 3){
         // Fallback crawl
         const html = await fetchText(key);
         const doc = parseHTML(html);
         if(doc) urls = Array.from(doc.querySelectorAll('a[href]')).map(a=>a.href).filter(u=>u.startsWith(key));
      }

      const pages = [];
      const unique = Array.from(new Set(urls)).slice(0, CFG.maxPagesPerDomain);
      
      for(const u of unique){
        if(u.includes('#') || /\.(jpg|png|pdf)$/i.test(u)) continue;
        const txt = await fetchText(u); if(!txt) continue;
        if(/noindex/i.test(txt)) continue;
        
        let title = (txt.match(/<title>(.*?)<\/title>/i)||[])[1]||"";
        let desc = (txt.match(/name="description" content="(.*?)"/i)||[])[1]||"";
        if(!desc) desc = txt.replace(/<[^>]+>/g,' ').slice(0, 800);
        
        extractPrices(txt, u);
        pages.push({url: u, title: naturalize(title), text: naturalize(desc)});
        await sleep(CFG.fetchPauseMs);
      }

      if(pages.length) cache[key] = {ts: nowSec(), pages};
    }
    localStorage.setItem(K.learn, JSON.stringify(cache));
    pruneLearnCache();
  }

  /* ================= PRICING LOGIC ================= */
  
  const PRICE_TABLE = {
    'xe số':      { d:150000, w:600000, m:1000000 },
    'xe ga':      { d:180000, w:800000, m:1500000 },
    'vision':     { d:200000, w:850000, m:1700000 },
    'air blade':  { d:220000, w:900000, m:1900000 },
    'xe côn tay': { d:300000, w:1200000, m:null },
    '50cc':       { d:200000, w:800000, m:1600000 }
  };

  function mergeAutoPrices(){
    try{
      const samples = safe(localStorage.getItem(K.autoprices)) || [];
      if(!samples.length) return;
      const byType = {};
      samples.forEach(s => { (byType[s.type] = byType[s.type]||[]).push(s.price); });
      
      Object.keys(byType).forEach(type => {
        const arr = byType[type].sort((a,b)=>a-b);
        // Calculate Median & 75th percentile
        const p50 = arr[Math.floor(arr.length*0.5)] || arr[0];
        const p75 = arr[Math.floor(arr.length*0.75)] || arr[arr.length-1];
        
        // Update TABLE safely
        if(PRICE_TABLE[type]){
          PRICE_TABLE[type].d = p50;
          PRICE_TABLE[type].w = p50 * 5; // Ước lượng
          PRICE_TABLE[type].m = p50 * 20;
        }
      });
      if(CFG.debug) console.log('MotoAI: Prices updated from learned data.');
    }catch(e){}
  }

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

    // Context Check
    let type = null;
    if(CFG.deepContext){
      const ctx = getCtx();
      // Look back last 3 turns
      for(let i=ctx.turns.length-1; i>=Math.max(0, ctx.turns.length-3); i--){
        const t = ctx.turns[i];
        if(t.type) { type = t.type; break; }
      }
    }
    // Update Context Type if found in current query
    if(/số|wave|sirius/i.test(qLow)) type = 'xe số';
    else if(/vision/i.test(qLow)) type = 'vision';
    else if(/air|ab/i.test(qLow)) type = 'air blade';
    else if(/côn|exciter/i.test(qLow)) type = 'xe côn tay';
    else if(/50cc/i.test(qLow)) type = '50cc';

    if(type) pushCtx({ type }); // Update context

    // 1. Contact (Quick)
    if(intent.contact){
      return lang === 'vi' 
        ? `Anh/chị liên hệ Hotline: <a href="tel:${CFG.phone}">${CFG.phone}</a> hoặc Zalo: <a href="${CFG.zalo}" target="_blank">Chat Zalo</a> ạ.`
        : `Please call <a href="tel:${CFG.phone}">${CFG.phone}</a> or <a href="${CFG.zalo}" target="_blank">Chat Zalo</a> for quick support.`;
    }

    // 2. Documents
    if(intent.docs){
      return lang === 'vi'
        ? `Thủ tục đơn giản: Cần CCCD/Hộ chiếu gốc + tiền cọc (1-3 triệu tùy xe). Bên em có giao xe tận nơi.`
        : `Requirements: Original Passport/ID + Deposit (1-3M VND). We offer delivery service.`;
    }

    // 3. Pricing (Hybrid)
    if(intent.price){
      mergeAutoPrices(); // Sync latest prices
      const tUse = type || 'xe ga';
      const p = PRICE_TABLE[tUse] || PRICE_TABLE['xe ga'];
      const priceStr = `${nfVND(p.d)}đ/ngày`;
      
      return lang === 'vi'
        ? `Giá thuê ${tUse} khoảng ${priceStr}. Thuê tuần/tháng sẽ rẻ hơn. Anh/chị cần thuê bao lâu ạ?`
        : `Rental price for ${tUse} is around ${priceStr}. Weekly/Monthly is cheaper. How long do you need it?`;
    }

    // 4. Fallback: Search Index (BM25 + QA)
    const hit = searchIndex(userText);
    if(hit){
      let answer = "";
      if(CFG.smart.extractiveQA){
        const best = bestSentences(hit.text, userText, 1);
        if(best && best.length) answer = best[0];
      }
      if(!answer) answer = hit.text.slice(0, 160) + "...";

      return lang === 'vi'
        ? `Em tìm thấy thông tin này: "${answer}" (Nguồn: <a href="${hit.url}" target="_blank">Xem thêm</a>)`
        : `I found this: "${answer}" (<a href="${hit.url}" target="_blank">Read more</a>)`;
    }

    // 5. Default
    return lang === 'vi'
      ? `Chào bạn 👋, mình là trợ lý ảo của ${CFG.brand}. Bạn cần thuê xe ga, xe số hay tư vấn thủ tục?`
      : `Hello 👋, I am ${CFG.brand}'s assistant. Do you need a scooter, a manual bike, or help with documents?`;
  }

  /* ================= UI ENGINE (From v40) ================= */
  
  const CSS = `
  :root{
    --m-z:2147483647; --m-blue:${CFG.themeColor}; --m-bg:#fff; --m-text:#0b1220;
    --m-in-h:44px; --m-in-fs:16px; /* 16px prevents iOS zoom */
    --m-bot:80px;
  }
  #mta-root{position:fixed;right:16px;bottom:calc(var(--m-bot) + env(safe-area-inset-bottom,0));z-index:var(--m-z);font-family:-apple-system,system-ui,sans-serif}
  #mta-bubble{width:58px;height:58px;border:none;border-radius:50%;background:radial-gradient(circle at 30% 0,var(--m-blue),#00B2FF);display:flex;align-items:center;justify-content:center;cursor:pointer;box-shadow:0 8px 24px rgba(0,80,255,0.35);color:#fff;font-size:26px;transition:transform .2s}
  #mta-bubble:hover{transform:scale(1.05)}
  
  #mta-backdrop{position:fixed;inset:0;background:rgba(0,0,0,0.25);opacity:0;pointer-events:none;transition:opacity .2s;z-index:var(--m-z)}
  #mta-backdrop.show{opacity:1;pointer-events:auto}
  
  #mta-card{
    position:fixed;right:16px;bottom:calc(var(--m-bot) + env(safe-area-inset-bottom,0));
    width:min(380px, calc(100% - 24px)); height:min(72vh, 740px);
    background:var(--m-bg);color:var(--m-text);border-radius:24px;
    box-shadow:0 20px 60px rgba(0,0,0,0.25);display:flex;flex-direction:column;
    transform:translateY(120%) scale(0.95); opacity:0; pointer-events:none;
    transition:transform .3s cubic-bezier(0.19,1,0.22,1), opacity .2s;
    z-index:calc(var(--m-z) + 1); overflow:hidden;
  }
  #mta-card.open{transform:translateY(0) scale(1); opacity:1; pointer-events:auto}
  
  #mta-head{background:linear-gradient(135deg,var(--m-blue),#00C6FF);padding:14px 16px;color:#fff;display:flex;align-items:center;gap:12px}
  #mta-head .avt{width:36px;height:36px;border-radius:50%;background:rgba(255,255,255,0.2);display:flex;align-items:center;justify-content:center}
  #mta-head .act{margin-left:auto;background:none;border:none;color:#fff;font-size:20px;cursor:pointer;padding:4px}
  
  #mta-body{flex:1;overflow-y:auto;padding:12px;background:#f4f6f8;scroll-behavior:smooth}
  .m-msg{max-width:82%;padding:10px 14px;margin:6px 0;border-radius:18px;font-size:14px;line-height:1.5;word-break:break-word;animation:mta-slide .25s ease-out}
  .m-msg.bot{background:#fff;align-self:flex-start;border-bottom-left-radius:4px;box-shadow:0 2px 4px rgba(0,0,0,0.04);color:#334155}
  .m-msg.user{background:var(--m-blue);color:#fff;margin-left:auto;border-bottom-right-radius:4px}
  .m-msg a{color:inherit;text-decoration:underline;font-weight:500}
  @keyframes mta-slide{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
  
  #mta-typing{display:inline-flex;gap:4px;padding:8px 12px;background:#fff;border-radius:18px;margin-bottom:8px}
  #mta-typing span{width:6px;height:6px;background:#cbd5e1;border-radius:50%;animation:mta-type 1s infinite}
  #mta-typing span:nth-child(2){animation-delay:0.2s}
  #mta-typing span:nth-child(3){animation-delay:0.4s}
  @keyframes mta-type{0%,100%{transform:translateY(0)}50%{transform:translateY(-4px)}}

  #mta-tags{padding:8px 12px;background:#fff;white-space:nowrap;overflow-x:auto;border-top:1px solid #f1f5f9}
  #mta-tags button{background:#eff6ff;border:1px solid #dbeafe;padding:8px 14px;border-radius:20px;margin-right:8px;font-size:13px;color:#1d4ed8;cursor:pointer}
  
  #mta-input{padding:10px;background:#fff;border-top:1px solid #f1f5f9;display:flex;gap:8px;align-items:center}
  #mta-in{flex:1;height:var(--m-in-h);border-radius:22px;border:1px solid #e2e8f0;padding:0 16px;font-size:var(--m-in-fs);outline:none;background:#f8fafc;color:#0f172a;transition:border .2s}
  #mta-in:focus{border-color:var(--m-blue);background:#fff}
  #mta-send{width:44px;height:44px;border-radius:50%;border:none;background:var(--m-blue);color:#fff;font-size:18px;cursor:pointer;display:flex;align-items:center;justify-content:center}
  #mta-send:disabled{opacity:0.6;cursor:not-allowed}

  /* Mobile Fixes */
  #mta-root.kb-active{bottom:0}
  #mta-root.kb-active #mta-card{height:100%;bottom:0;border-radius:0}
  @media(max-width:480px){ #mta-card{width:100%;right:0;margin:0;border-radius:24px 24px 0 0} }
  @media(prefers-color-scheme:dark){
    :root{--m-bg:#1e293b; --m-text:#f8fafc}
    #mta-body{background:#0f172a}
    .m-msg.bot{background:#334155;color:#f1f5f9}
    #mta-tags, #mta-input{background:#1e293b;border-color:#334155}
    #mta-tags button{background:#334155;border-color:#475569;color:#93c5fd}
    #mta-in{background:#334155;border-color:#475569;color:#fff}
  }
  `;

  const HTML = `
  <div id="mta-root">
    <button id="mta-bubble" aria-label="Chat">💬</button>
    <div id="mta-backdrop"></div>
    <div id="mta-card">
      <div id="mta-head">
        <div class="avt">${CFG.avatar}</div>
        <div>
           <div style="font-weight:700;font-size:15px">${CFG.brand}</div>
           <div style="font-size:12px;opacity:0.9">Online</div>
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

  /* ================= BOOTSTRAP & EVENTS ================= */
  
  function addMsg(role, text){
    if(!text) return;
    const box = $('#mta-body');
    const div = document.createElement('div');
    div.className = `m-msg ${role}`;
    div.innerHTML = text.replace(/\n/g, '<br>');
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

  async function handleSend(){
    const inp = $('#mta-in');
    const txt = inp.value.trim();
    if(!txt) return;

    inp.value = '';
    $('#mta-send').disabled = true;
    addMsg('user', txt);
    addSess('user', txt);

    showTyping(true);
    await sleep(500 + Math.random() * 600);
    
    const ans = await getBotResponse(txt);
    showTyping(false);
    
    addMsg('bot', ans);
    addSess('bot', ans);
    $('#mta-send').disabled = false;
  }

  function setTags(){
    const div = $('#mta-tags');
    div.innerHTML = `
      <button data-q="Giá thuê xe ga?">💰 Giá thuê</button>
      <button data-q="Thủ tục thế nào?">📄 Thủ tục</button>
      <button data-q="Địa chỉ ở đâu?">📍 Địa chỉ</button>
    `;
    div.querySelectorAll('button').forEach(b => {
      b.onclick = () => { $('#mta-in').value = b.dataset.q; handleSend(); }
    });
  }

  function init(){
    // Inject CSS & HTML
    const s = document.createElement('style'); s.textContent = CSS; document.head.appendChild(s);
    const c = document.createElement('div'); c.innerHTML = HTML; document.body.appendChild(c.firstElementChild);

    // Handlers
    const card = $('#mta-card'), back = $('#mta-backdrop'), root = $('#mta-root');
    
    const toggle = () => {
       if(card.classList.contains('open')){
         card.classList.remove('open'); back.classList.remove('show');
         if(root.classList.contains('kb-active')) $('#mta-in').blur();
       } else {
         card.classList.add('open'); back.classList.add('show');
         setTimeout(()=> $('#mta-in').focus(), 150);
       }
    };

    $('#mta-bubble').onclick = toggle;
    $('#mta-close').onclick = toggle;
    $('#mta-backdrop').onclick = toggle;
    $('#mta-send').onclick = handleSend;
    $('#mta-in').onkeydown = (e) => { if(e.key === 'Enter') handleSend(); }

    // VisualViewport (Fix iOS Keyboard)
    if(window.visualViewport){
      window.visualViewport.addEventListener('resize', () => {
        if(window.visualViewport.height < window.innerHeight * 0.85){
           root.classList.add('kb-active');
           setTimeout(()=> $('#mta-body').scrollTop = $('#mta-body').scrollHeight, 100);
        } else {
           root.classList.remove('kb-active');
        }
      });
    }

    // Load History
    const sess = getSess();
    if(sess.length) sess.forEach(m => addMsg(m.role, m.text));
    else addMsg('bot', `Chào bạn! Mình là trợ lý ảo của ${CFG.brand}. Bạn cần tìm thuê xe gì ạ?`);
    
    setTags();
    
    // AutoLearn
    if(CFG.autolearn) learnSites(CFG.extraSites);
  }

  if(document.readyState === 'complete') init();
  else window.addEventListener('load', init);

  /* Public API */
  window.MotoAI_v41 = {
    open: () => $('#mta-bubble').click(),
    learnNow: () => { console.log("Learning started..."); learnSites(CFG.extraSites); },
    clear: () => { localStorage.clear(); sessionStorage.clear(); console.log("Reset done."); }
  };

})();
