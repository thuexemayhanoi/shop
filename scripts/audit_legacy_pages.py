#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Legacy root-page SEO / technical audit.

Audits every root-level .html page (including lienhe.html) and writes
reports/seo/legacy-pages-audit-run.json. Standard library only, no AI API.

Checks per page: H1 count, title, meta description, canonical, heading
hierarchy, contextual link count, broken local links, stale business-fact
claims, JSON-LD validity, visible word count, duplicate title/meta/content.
Exit code 0 when no blocking issue remains, 1 otherwise.
"""
import glob
import hashlib
import html
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "reports", "seo")
SITE = "https://thuexemayhanoi.github.io/shop/"
FACTS_CONFIG = os.path.join(ROOT, "config", "business-facts.json")

# Pages whose canonical intentionally points at the homepage.
INTENTIONAL_HOME_CANONICAL = {"nhap.html"}

# Stale-claim patterns (business facts not trusted in config/business-facts.json).
STALE_PATTERNS = [
    ("24_7", re.compile(r"24/7|24-7|Hotline 24|hỗ trợ 24", re.I)),
    ("fixed_15p", re.compile(r"15\s*p\b|15\s*phút|15\s*-\s*20\s*phút|15\s*-\s*30\s*phút", re.I)),
    ("fixed_p", re.compile(r"\b(?:5|10|15|20|45)[-–]?(?:60)?\s*p\b", re.I)),
    ("fixed_timing", re.compile(
        r"\b(5|10|20|30)\s*-\s*(10|15|20|30)\s*phút|"
        r"(giao|nhận|có)\s*xe[^.<]{0,40}\b(5|10|15|20|30)\s*phút|"
        r"trong\s+(5|10|15|20|30)\s*phút|sau\s+(5|10|15|20|30)\s*phút|"
        r"chỉ\s+(?:trong\s+|mất\s+khoảng\s+)?(5|10|15|20|30)\s*phút", re.I)),
    ("xe_moi_100", re.compile(r"xe mới 100%|xe mới 2024|dàn xe mới 100%", re.I)),
    ("uy_tin_so_1", re.compile(r"uy tín số\s*1|uy tín nhất", re.I)),
    ("deposit_lie", re.compile(r"miễn cọc|không cần cọc|không phải cọc|giảm cọc", re.I)),
    ("fake_promo", re.compile(r"giảm 30%|voucher|khuyến mãi cố định|miễn phí thay dầu|miễn phí bảo dưỡng|đổi xe miễn phí|giao xe miễn phí|MIỄN PHÍ trong vòng|Số lượng xe ưu đãi có hạn|giá cực sốc", re.I)),
    ("schema_stale", re.compile(r"priceRange|streetAddress|openingHoursSpecification")),
    ("address_seo", re.compile(r"17 Phúc Tân")),
    ("support_hours", re.compile(r"kể cả 2h sáng|phản hồi trong vòng 24h", re.I)),
]
# Benign sentences allowed to contain timing words (customer advice, not promises).
BENIGN = [re.compile(r"dành 5 phút để kiểm tra", re.I)]

# ---------------------------------------------------------------------------
# Config-aware fact-safety checks (pass 3).
#
# Fields under requires_owner_confirmation that are still null are UNVERIFIED:
# production pages must not assert them as hard facts. The checks below are
# built dynamically from config/business-facts.json so the gate can never
# report a false "stale fact pages = 0" while unverified claims remain.
# ---------------------------------------------------------------------------
# Neutral conditional wording that is always allowed (allowlist).
FACT_SAFETY_ALLOWLIST = re.compile(
    r"liên hệ[^.]{0,60}xác nhận"
    r"|vui lòng liên hệ trước"
    r"|xác nhận khả năng giao/nhận"
    r"|xác nhận thời gian hỗ trợ"
    r"|xác nhận điều kiện áp dụng"
    r"|xác nhận hình thức nhận xe"
    r"|theo thỏa thuận", re.I)
# Hard numeric/hour tokens are never excused by nearby conditional wording.
FACT_SAFETY_HARD = re.compile(r"8h\s*[-–]\s*17h|08\s*:\s*00|17\s*:\s*00", re.I)


def load_owner_confirmation(path=FACTS_CONFIG):
    """Return the requires_owner_confirmation mapping from business-facts.json."""
    try:
        with io.open(path, encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg.get("requires_owner_confirmation") or {}
    except Exception:
        return {}


def fact_safety_patterns(conf):
    """Build (flag_key, regex) checks for every unverified (null) fact field."""
    pats = []
    if conf.get("opening_hours") is None:
        pats.append(("unverified_opening_hours", re.compile(
            r"8h\s*[-–]\s*17h|08\s*:\s*00|17\s*:\s*00|giờ mở cửa|"
            r"cửa hàng đang mở|ngoài giờ mở cửa|mở cửa hằng ngày", re.I)))
    if conf.get("support_hours") is None:
        pats.append(("unverified_support_hours", re.compile(
            r"hỗ trợ\s*24/7|24/7|hỗ trợ online 24|hotline 24|"
            r"phản hồi siêu tốc", re.I)))
    if conf.get("delivery_or_pickup") is None:
        pats.append(("unverified_delivery", re.compile(
            r"giao xe tận sảnh|tận sảnh|giao xe? tận nơi|giao tận nơi|giao tận nhà|"
            r"giao tận cửa|giao xe tận cửa|giao xe theo lịch hẹn|"
            r"giao nhận xe theo lịch hẹn|mạng lưới giao xe|"
            r"khu vực giao xe|giao xe nhanh|giao xe tại|"
            r"đón khách tại|chi nhánh", re.I)))
    if conf.get("late_return_policy") is None:
        pats.append(("unverified_late_return", re.compile(
            r"trả xe trễ[^.]{0,50}(phí|theo giờ|tính)|trả xe muộn[^.]{0,50}(phí|tính)|"
            r"phí theo giờ|phí phạt quá giờ|late fee", re.I)))
    return pats


def fact_safety_flags(text, conf=None):
    """Flag hard claims about unverified facts in any text segment.

    A match is excused only when the surrounding context uses the neutral
    conditional allowlist AND the match is not a hard hour/number token.
    """
    if conf is None:
        conf = load_owner_confirmation()
    flags = []
    for key, pat in fact_safety_patterns(conf):
        for m in pat.finditer(text):
            frag = text[max(0, m.start() - 100):m.end() + 100]
            if FACT_SAFETY_ALLOWLIST.search(frag) and not FACT_SAFETY_HARD.search(frag):
                continue
            flags.append(key)
            break
    return flags


INTENTS = {
    "index.html": "thuê xe máy hà nội (umbrella)",
    "phoco.html": "thuê xe máy phố cổ",
    "hoankiem.html": "thuê xe máy hoàn kiếm",
    "banggia.html": "giá thuê xe máy hà nội",
    "ngay.html": "thuê xe máy theo ngày",
    "tuan.html": "thuê xe máy theo tuần",
    "thang.html": "thuê xe máy theo tháng",
    "thutuc.html": "thủ tục thuê xe máy",
    "badinh.html": "thuê xe máy ba đình",
    "caugiay.html": "thuê xe máy cầu giấy",
    "dongda.html": "thuê xe máy đống đa",
    "haibatrung.html": "thuê xe máy hai bà trưng",
    "longbien.html": "thuê xe máy long biên",
    "tayho.html": "thuê xe máy tây hồ",
    "thanhxuan.html": "thuê xe máy thanh xuân",
    "gahn.html": "thuê xe máy ga hà nội",
    "kinhnghiem.html": "cẩm nang kinh nghiệm",
    "antoan.html": "an toàn giao thông",
    "xemay.html": "cẩm nang xe máy",
    "dulich.html": "du lịch hà nội",
    "cungduong.html": "cung đường phượt",
    "hoidap.html": "hỏi đáp",
    "faq.html": "faq",
    "gioithieu.html": "giới thiệu",
    "chinhsach.html": "chính sách bảo mật",
    "dieukhoan.html": "điều khoản sử dụng",
    "mangxahoi.html": "mạng xã hội",
    "uudai.html": "ưu đãi thuê xe",
    "nhap.html": "trang nhập (entry, non-canonical)",
    "lienhe.html": "liên hệ thuê xe máy",
}


def strip_noise(t):
    t = re.sub(r"<script[\s\S]*?</script>", " ", t, flags=re.I)
    t = re.sub(r"<style[\s\S]*?</style>", " ", t, flags=re.I)
    t = re.sub(r"<!--[\s\S]*?-->", " ", t)
    return t


def visible(t):
    t = strip_noise(t)
    t = re.sub(r"<head[\s\S]*?</head>", " ", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def main_slice(t):
    m = re.search(r"<main[\s\S]*?</main>", t, re.I)
    return m.group(0) if m else t


def audit_page(path, texts, local_files):
    name = os.path.basename(path)
    with io.open(path, encoding="utf-8") as f:
        raw = f.read()
    clean = strip_noise(raw)

    title = re.search(r"<title[^>]*>([\s\S]*?)</title>", clean, re.I)
    meta = re.search(r'<meta\s+name="description"\s+content="([^"]*)"', clean, re.I)
    canonical = re.search(r'rel="canonical"\s+href="([^"]*)"', raw, re.I)
    h1s = re.findall(r"<h1[^>]*>([\s\S]*?)</h1>", clean, re.I)

    heads = re.findall(r"<(h[1-6])[^>]*>", clean, re.I)
    heading_errors, prev = [], 0
    for h in heads:
        lvl = int(h[1])
        if prev and lvl > prev + 1:
            heading_errors.append("H%d->H%d" % (prev, lvl))
        prev = lvl
    heading_levels = sorted({"H%s" % int(h[1]) for h in heads})

    can = canonical.group(1) if canonical else None
    if not can:
        can_status = "missing"
    elif name == "index.html" and can.rstrip("/") == SITE.rstrip("/"):
        can_status = "self"
    elif can.rstrip("/").endswith("/" + name):
        can_status = "self"
    elif name in INTENTIONAL_HOME_CANONICAL and can.rstrip("/") == SITE.rstrip("/"):
        can_status = "intentional_home"
    else:
        can_status = "unexpected"

    vis = visible(raw)
    flags = []
    segments = {
        "title": title.group(1) if title else "",
        "meta": meta.group(1) if meta else "",
        "og": " ".join(re.findall(r'og:(?:title|description)"\s+content="([^"]*)"', raw)),
        "twitter": " ".join(re.findall(r'twitter:(?:title|description)"\s+content="([^"]*)"', raw)),
        "body": vis,
        "schema": " ".join(re.findall(r'<script type="application/ld\+json">([\s\S]*?)</script>', raw, re.I)),
    }
    for label, seg in segments.items():
        if label == "schema":
            if not seg:
                continue
            for key, pat in STALE_PATTERNS:
                if key in ("schema_stale", "address_seo", "24_7") and pat.search(seg):
                    flags.append("schema:" + key)
            continue
        for key, pat in STALE_PATTERNS:
            if key == "schema_stale":
                continue
            for m in pat.finditer(seg):
                frag = seg[max(0, m.start() - 30):m.end() + 30]
                if any(b.search(frag) for b in BENIGN):
                    continue
                flags.append(label + ":" + key)
                break

    # Config-aware fact-safety checks (unverified business facts),
    # applied to every content segment AND inline JavaScript (status
    # widgets, chatbot strings) so JS-rendered claims cannot hide.
    conf = load_owner_confirmation()
    for label, seg in segments.items():
        for key in fact_safety_flags(seg, conf):
            flags.append(label + ":" + key)
    inline_js = " ".join(
        blk for blk in re.findall(r"<script[^>]*>([\s\S]*?)</script>", raw, re.I)
        if "application/ld+json" not in blk)
    for key in fact_safety_flags(inline_js, conf):
        flags.append("js:" + key)

    jsonld_valid = True
    for blk in re.findall(r'<script type="application/ld\+json">([\s\S]*?)</script>', raw, re.I):
        try:
            json.loads(blk)
        except Exception:
            jsonld_valid = False

    main_txt = main_slice(clean)
    broken, ctx = [], 0
    for m in re.finditer(r'<a\s[^>]*href="([^"#]+)"[^>]*>', main_txt):
        href = m.group(1)
        if href.startswith(("http", "tel:", "mailto:", "data:")):
            continue
        target = href.split("#")[0].split("?")[0].strip()
        if not target or target.endswith((".css", ".js", ".jpeg", ".jpg", ".png", ".svg")):
            continue
        norm = re.sub(r"^(\./|/shop/|/)", "", target)
        if norm in ("", "."):
            norm = "index.html"
        if norm not in local_files:
            broken.append(href)
        if not re.search(r'class="[^"\']*f-link|class="[^"\']*app-item', m.group(0)):
            ctx += 1

    dups = []
    for para in re.findall(r"<(?:p|li)[^>]*>([\s\S]*?)</(?:p|li)>", main_slice(clean)):
        q = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", para))).strip()
        if len(q.split()) < 15:
            continue
        if "giấy tờ và mức đặt cọc" in q or "Đặt xe trước qua Zalo" in q:
            continue
        h = hashlib.md5(q.lower().encode("utf-8")).hexdigest()
        for other, ohashes in texts.items():
            if other != name and h in ohashes:
                dups.append((other, q[:60]))
                break

    issues = []
    if len(h1s) != 1:
        issues.append("h1_count=%d" % len(h1s))
    if not title:
        issues.append("missing_title")
    if not meta or len(meta.group(1).strip()) < 50:
        issues.append("missing_or_short_meta")
    if can_status in ("missing", "unexpected"):
        issues.append("canonical_" + can_status)
    if heading_errors:
        issues.append("heading_hierarchy")
    if broken:
        issues.append("broken_links")
    if not jsonld_valid:
        issues.append("invalid_jsonld")
    if flags:
        issues.append("stale_claims")

    return {
        "path": name,
        "primary_intent": INTENTS.get(name, ""),
        "title": title.group(1) if title else None,
        "meta_description": meta.group(1) if meta else None,
        "h1_count": len(h1s),
        "h1": re.sub(r"<[^>]+>", " ", h1s[0]).strip() if h1s else None,
        "canonical": can,
        "canonical_status": can_status,
        "heading_levels": heading_levels,
        "heading_errors": heading_errors,
        "visible_word_count": len(vis.split()),
        "contextual_links": ctx,
        "broken_links": broken,
        "duplicate_title": None,
        "duplicate_meta": None,
        "duplicate_content_flags": [{"page": o, "fragment": f} for o, f in dups][:5],
        "business_fact_flags": flags,
        "jsonld_valid": jsonld_valid,
        "status": "REVIEW" if issues else "PASS",
        "issues": issues,
    }


def collect_texts(pages):
    texts = {}
    for p in pages:
        with io.open(os.path.join(ROOT, p), encoding="utf-8") as f:
            raw = f.read()
        body = main_slice(strip_noise(raw))
        hs = set()
        for para in re.findall(r"<(?:p|li)[^>]*>([\s\S]*?)</(?:p|li)>", body):
            q = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", para))).strip()
            if len(q.split()) >= 15 and "giấy tờ và mức đặt cọc" not in q and "Đặt xe trước qua Zalo" not in q:
                hs.add(hashlib.md5(q.lower().encode("utf-8")).hexdigest())
        texts[p] = hs
    return texts


def main():
    pages = sorted(os.path.basename(p) for p in glob.glob(os.path.join(ROOT, "*.html")))
    texts = collect_texts(pages)
    results = [audit_page(os.path.join(ROOT, p), texts, set(pages)) for p in pages]

    by_title, by_meta = {}, {}
    for r in results:
        by_title.setdefault(r["title"], []).append(r["path"])
        by_meta.setdefault(r["meta_description"], []).append(r["path"])
    for r in results:
        if r["title"] and len(by_title[r["title"]]) > 1:
            r["duplicate_title"] = by_title[r["title"]]
        if r["meta_description"] and len(by_meta[r["meta_description"]]) > 1:
            r["duplicate_meta"] = by_meta[r["meta_description"]]
        if (r["duplicate_title"] or r["duplicate_meta"]) and "duplicate_title_meta" not in r["issues"]:
            r["issues"].append("duplicate_title_meta")
            r["status"] = "REVIEW"

    os.makedirs(OUT_DIR, exist_ok=True)
    fact_keys = {r["path"]: sorted({f.split(":", 1)[1] for f in r["business_fact_flags"]
                                    if f.split(":", 1)[1].startswith("unverified_")})
                 for r in results}
    report = {
        "generated_by": "scripts/audit_legacy_pages.py",
        "fact_safety": {
            "config": "config/business-facts.json",
            "unverified_fields": [k for k, v in sorted(load_owner_confirmation().items()) if v is None],
            "pages_with_fact_safety_flags": {k: v for k, v in fact_keys.items() if v},
        },
        "pages_audited": len(results),
        "pages": results,
    }
    with io.open(os.path.join(OUT_DIR, "legacy-pages-audit-run.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    blocking = [r for r in results if r["status"] == "REVIEW"]
    print("pages audited: %d" % len(results))
    if blocking:
        print("pages needing review: %d" % len(blocking))
        for r in blocking:
            print("  %s: %s" % (r["path"], ", ".join(r["issues"])))
            print("      flags: %s" % (r["business_fact_flags"],))
    else:
        print("no blocking issues")
        fs = [r["path"] for r in results
              if any(f.split(":", 1)[1].startswith("unverified_") for f in r["business_fact_flags"])]
        print("stale fact pages (config-aware): %d" % len(fs))
        for r in results:
            if r["path"] in fs:
                print("  %s: %s" % (r["path"], sorted({f.split(":", 1)[1] for f in r["business_fact_flags"]})))
    return 0 if not blocking else 1


if __name__ == "__main__":
    sys.exit(main())
