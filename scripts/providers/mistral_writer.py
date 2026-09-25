#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mistral writer provider — real API calls, no fabricated content.

Uses the Mistral chat completions API (stdlib urllib only, no dependencies):

    POST https://api.mistral.ai/v1/chat/completions
    Authorization: Bearer $MISTRAL_API_KEY

Configuration (environment / GitHub Actions Secrets ONLY):
    MISTRAL_API_KEY        required — no key => WriterSecretMissing, never fake
    MISTRAL_WRITER_MODEL   optional — default mistral-large-latest

Resilience:
    - per-request timeout (default 240s)
    - bounded retries with exponential backoff on network / 429 / 5xx
    - clear error classification: retryable vs permanent provider error
"""
import json
import os
import time
import urllib.error
import urllib.request

try:
    from providers import register
except ImportError:  # direct import for unit tests
    register = lambda cls: cls  # noqa: E731


class WriterTimeout(Exception):
    """Provider request timed out after bounded retries."""


class WriterProviderError(Exception):
    """Persistent provider-side error (not retryable within this run)."""


_API_URL = "https://api.mistral.ai/v1/chat/completions"
DEFAULT_MODEL = "mistral-large-latest"
DEFAULT_TIMEOUT = 240
DEFAULT_MAX_RETRIES = 3
RETRYABLE_HTTP = (408, 429, 500, 502, 503, 504)
_BACKOFFS = (5, 15, 45)


@register
class MistralWriter(object):
    name = "mistral"

    def __init__(self, env=None):
        self.env = env if env is not None else os.environ
        self.model = (self.env.get("MISTRAL_WRITER_MODEL") or DEFAULT_MODEL).strip()
        self.timeout = int(self.env.get("MISTRAL_WRITER_TIMEOUT") or DEFAULT_TIMEOUT)
        self.max_retries = int(self.env.get("MISTRAL_WRITER_RETRIES") or DEFAULT_MAX_RETRIES)

    # ------------------------------------------------------------------ cfg
    def is_configured(self):
        return bool((self.env.get("MISTRAL_API_KEY") or "").strip())

    def _require_key(self):
        if not self.is_configured():
            from article_writer import WriterSecretMissing
            raise WriterSecretMissing(
                "MISTRAL_API_KEY is not configured. Refusing to fabricate "
                "article content. Add the secret to GitHub Actions Secrets "
                "(never commit it) and re-run.")

    # ------------------------------------------------------------- API core
    def _chat(self, messages, temperature=0.5):
        """One chat completion with bounded retry/backoff. Never loops forever."""
        self._require_key()
        key = self.env["MISTRAL_API_KEY"].strip()
        payload = json.dumps({
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }).encode("utf-8")
        last_err = None
        for attempt in range(self.max_retries + 1):
            req = urllib.request.Request(
                _API_URL, data=payload, method="POST",
                headers={"Authorization": "Bearer %s" % key,
                         "Content-Type": "application/json",
                         "Accept": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                return body["choices"][0]["message"]["content"]
            except urllib.error.HTTPError as e:
                last_err = "HTTP %d" % e.code
                if e.code in RETRYABLE_HTTP and attempt < self.max_retries:
                    time.sleep(_BACKOFFS[min(attempt, len(_BACKOFFS) - 1)])
                    continue
                raise WriterProviderError(
                    "Mistral API %s after %d attempt(s)" % (last_err, attempt + 1))
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last_err = str(e)
                if attempt < self.max_retries:
                    time.sleep(_BACKOFFS[min(attempt, len(_BACKOFFS) - 1)])
                    continue
                raise WriterTimeout(
                    "Mistral API unreachable: %s" % last_err)
        raise WriterProviderError("Mistral API failed: %s" % last_err)

    # ------------------------------------------------------------- prompts
    def _system_prompt(self, ctx):
        facts = ctx.get("business_facts") or {}
        biz = (facts.get("business") or {})
        return (
            "Bạn là biên tập viên tiếng Việt giàu kinh nghiệm viết bài cho "
            "%s, một tiệm cho thuê xe máy tại %s. "
            "Viết bài chất lượng, hữu ích, tự nhiên, độc lập — KHÔNG quay "
            "vòng mẫu sáo, KHÔNG chèn đoạn filler, KHÔNG bịa đánh giá, số "
            "liệu, thông tin kinh doanh, điều luật, trích dẫn hay nguồn giả. "
            "Tuân thủ tuyệt đối các quy tắc kỹ thuật trong yêu cầu."
            % (biz.get("name", "Mr Tú Motorbike Rental"), biz.get("city", "Hà Nội")))

    def _user_prompt(self, ctx):
        ctx = dict(ctx)
        ctx.setdefault("business_facts", {})
        parts = [
            "Viết MỘT bài viết hoàn chỉnh bằng tiếng Việt (chỉ trả về HTML, "
            "không giải thích, không markdown fence).",
            "",
            "== THÔNG TIN BÀI ==",
            "article_id: %(article_id)s" % ctx,
            "loại: %(category)s" % ctx,
            "tiêu đề làm việc: %(working_title)s" % ctx,
            "từ khoá chính: %(primary_keyword)s (_intent: %(search_intent)s)" % ctx,
            "từ khoá phụ (nếu có): %(secondary_keywords)s" % ctx,
            "file đích: %(output_path)s" % ctx,
            "hub cha: %(parent_hub)s (BẮT BUỘC có đúng 1 link tới hub cha)" % ctx,
        ]
        sk = (ctx.get("secondary_keywords") or "").strip()
        if not sk:
            parts[-1] = "hub cha: %(parent_hub)s (BẮT BUỘC có đúng 1 link tới hub cha)" % ctx
        parts += [
            "",
            "== QUY TẮC BẮT BUỘC ==",
            "- Độ dài: 1600–2000 từ tiếng Việt có nghĩa (nội dung chính, "
            "không tính head/nav). TUYỆT ĐỐI không đệm filler để đạt số từ.",
            "- Liên kết nội bộ ngữ cảnh: 3–5 link trong thân bài (không tính "
            "menu/nav). Đúng 1 link tới hub cha. Tối đa 1 link thương mại "
            "tới: %(commercial_link_target)s" % ctx,
            "- Link cho phép (chỉ dùng các đích này): %(internal_link_targets)s" % ctx,
            "- Anchor mô tả đích, đa dạng; KHÔNG dùng 'xem thêm', 'tại đây', "
            "'click here'; không lặp anchor exact-match.",
            "- Link dùng href TƯƠNG ĐỐI (vd: /shop/kinhnghiem.html hoặc "
            "kinhnghiem.html), trùng với đích cho phép.",
            "",
            "== THÔNG TIN KINH DOANH (chỉ dùng đúng các dữ liệu này) ==",
            json.dumps(ctx.get("business_facts"), ensure_ascii=False),
            "KHÔNG bịa giá cho dòng xe ngoài approved_models; với xe chưa "
            "duyệt giá ghi: 'Liên hệ để xác nhận giá hiện tại'.",
            "Đặt cọc chỉ theo deposit_policy.standard_wording; không phát "
            "biểu thêm về cọc/giấy tờ.",
            "KHÔNG phát biểu giờ mở cửa, giao xe tận nơi, hỗ trợ 24/7 hay "
            "chính sách trả xe trễ — các thông tin này chưa được xác nhận; "
            "chỉ được viết dạng 'liên hệ để xác nhận'.",
            "",
            "== YÊU CẦU NGUỒN ==",
            "requires_sources: %(requires_sources)s" % ctx,
            "source_notes: %(source_notes)s" % ctx,
            "Nếu requires_sources=true: chỉ nêu nội dung pháp lý phổ biến "
            "chính xác và nêu nguồn dạng văn bản ở mục 'Nguồn tham khảo' "
            "cuối bài (tên luật/nghị định + số hiệu chính xác); KHÔNG bịa "
            "số điều, số hiệu, tiền phạt không chắc chắn.",
            "",
            "== BẢO VỆ TỪ KHÓA ==",
            "protected_intents (KHÔNG nhắm tới làm từ khoá chính):",
            json.dumps(ctx.get("protected_intents"), ensure_ascii=False),
            "",
            "== NHẬN BIẾT TRÙNG LẶP (cannibalization) ==",
            "Các bài lân cận trong ma trận có chủ đề gần nhau; bài này phải "
            "KHÔNG trùng chủ đề chính của:",
            json.dumps(ctx.get("neighbor_topics", []), ensure_ascii=False),
            "",
            "== ĐỊNH DẠNG HTML BẮT BUỘC ==",
            "<!DOCTYPE html>\\n<html lang=\"vi\">\\n<head>\\n<meta charset=\"utf-8\">",
            "<title>TITLE</title>",
            "<meta name=\"description\" content=\"MO TẢ 140-160 ký tự\">",
            "<link rel=\"canonical\" href=\"%(canonical_url)s\">" % ctx,
            "<meta name=\"author\" content=\"Mr Tú\">",
            "<meta property=\"article:published_time\" content=\"%(published_date)s\">" % ctx,
            "JSON-LD Article (headline, author Person Mr Tú, datePublished) "
            "trong <script type=\"application/ld+json\">",
            "JSON-LD BreadcrumbList: Trang chủ /shop/ -> %(category_label)s "
            "-> bài này (%(canonical_url)s)" % ctx,
            "</head>\\n<body>\\n<main>\\n<h1>TITLE</h1> ... thân bài ... "
            "</main>\\n</body>\\n</html>",
            "Đúng 1 h1. Thân bài có h2/h3 hợp lý, đoạn văn tự nhiên.",
        ]
        return "\\n".join(parts)

    # ------------------------------------------------------------- public
    def write_article(self, matrix_row, context):
        ctx = dict(context)
        ctx.update({
            "article_id": matrix_row.get("article_id"),
            "category": matrix_row.get("category"),
            "working_title": matrix_row.get("working_title"),
            "primary_keyword": matrix_row.get("primary_keyword"),
            "secondary_keywords": matrix_row.get("secondary_keywords") or "",
            "search_intent": matrix_row.get("search_intent"),
            "output_path": matrix_row.get("output_path"),
            "parent_hub": matrix_row.get("parent_hub"),
            "requires_sources": matrix_row.get("requires_sources"),
            "source_notes": matrix_row.get("source_notes") or "",
            "internal_link_targets": (matrix_row.get("internal_link_targets")
                                       or "").replace(";", ", "),
            "commercial_link_target": matrix_row.get("commercial_link_target") or "",
            "category_label": matrix_row.get("category"),
        })
        if not ctx.get("canonical_url"):
            ctx["canonical_url"] = ctx.get("url_base", "") + "/" + \
                (matrix_row.get("output_path") or "")
        if not ctx.get("published_date"):
            ctx["published_date"] = matrix_row.get("planned_date") or \
                __import__("datetime").date.today().isoformat()
        ctx.setdefault("business_facts", {})
        ctx.setdefault("protected_intents", [])
        ctx.setdefault("neighbor_topics", [])
        ctx.setdefault("secondary_keywords", "")
        content = self._chat([
            {"role": "system", "content": self._system_prompt(ctx)},
            {"role": "user", "content": self._user_prompt(ctx)},
        ])
        return self._validate_html(content)

    def repair_article(self, matrix_row, context, html, qa_report):
        """Repair ONLY the problems the deterministic QA identified."""
        self._require_key()
        msg = (
            "Bài viết dưới đây KHÔNG đạt QA. Sửa CHỈ các vấn đề được liệt kê, "
            "giữ phần còn lại nguyên vẹn. Giữ độ dài 1600–2000 từ và giữ "
            "định dạng HTML đầy đủ. Trả về toàn bộ HTML đã sửa (không giải "
            "thích).\\n\\n== KẾT QUẢ QA ==\\n%s\\n\\n== BÀI GỐC ==\\n%s"
            % (json.dumps(qa_report, ensure_ascii=False, indent=1), html))
        content = self._chat([
            {"role": "system", "content": self._system_prompt(context)},
            {"role": "user", "content": msg},
        ], temperature=0.3)
        return self._validate_html(content)

    def _validate_html(self, content):
        """Reject obviously unusable provider output before it hits QA."""
        if not content or not isinstance(content, str):
            raise WriterProviderError("writer returned empty content")
        c = content.strip()
        if c.startswith("```"):
            c = c.strip("`")
            if c.lower().startswith("html"):
                c = c[4:]
            c = c.strip()
        if "<h1" not in c or "<!DOCTYPE html" not in c.replace("<!DOCTYPE HTML", "<!DOCTYPE html"):
            raise WriterProviderError(
                "writer output missing required full-HTML structure")
        if len(c) < 5000:
            raise WriterProviderError("writer output too short to be a "
                                      "1600-word production article")
        return c
