from pathlib import Path
import re
import sys

ROOT = Path(".")

html_files = sorted(
    f for f in ROOT.glob("*.html")
    if f.is_file()
)

if len(html_files) != 25:
    print(
        f"FAIL: expected 25 root HTML files, "
        f"found {len(html_files)}"
    )
    print([f.name for f in html_files])
    sys.exit(1)

img_files = sorted(
    f.name
    for f in ROOT.glob("IMG_*.jpeg")
    if f.is_file()
)

protected_tokens = (
    b"motoai",
    b"MOTO_AI",
    b"motoAI",
    b"AI_Guide",
    b"AI_Matchmaker",
)

IMG_TAG_RE = re.compile(
    rb"<img[^>]*>",
    re.IGNORECASE,
)

H1_RE = re.compile(
    rb"<h1[^>]*>.*?</h1>",
    re.IGNORECASE | re.DOTALL,
)


def protected_lines(data):
    return [
        line
        for line in data.splitlines(keepends=True)
        if any(token in line for token in protected_tokens)
    ]


def motoai_script_lines(data):
    result = []

    for line in data.splitlines(keepends=True):
        lower = line.lower()

        if (
            b"<script" in lower
            and b"src=" in lower
            and b"motoai" in lower
        ):
            result.append(line)

    return result


render_count = 0
image_count = 0
decoding_count = 0
changed_files = []

for path in html_files:
    original = path.read_bytes()

    marker = b"</head>"

    if original.count(marker) != 1:
        print(
            f"FAIL: {path.name} contains "
            f"{original.count(marker)} </head> markers"
        )
        sys.exit(1)

    head, tail = original.split(marker, 1)
    modified_tail = tail

    original_h1 = H1_RE.findall(original)
    original_protected = protected_lines(original)
    original_moto_scripts = motoai_script_lines(original)

    old_render = (
        b"document.addEventListener("
        b"'DOMContentLoaded', "
        b"() => Render.init());"
    )

    new_render = b"Render.init();"

    render_occurrences = modified_tail.count(old_render)

    if render_occurrences > 1:
        print(
            f"FAIL: {path.name}: Render init pattern "
            f"appears {render_occurrences} times"
        )
        sys.exit(1)

    if render_occurrences == 1:
        modified_tail = modified_tail.replace(
            old_render,
            new_render,
            1,
        )

        render_count += 1

    for img_name in img_files:
        old_attr = (
            'src="https://raw.githubusercontent.com/'
            'thuexemayhanoi/shop/main/'
            + img_name
            + '"'
        ).encode("utf-8")

        new_attr = (
            'src="./'
            + img_name
            + '"'
        ).encode("utf-8")

        count = modified_tail.count(old_attr)

        if count:
            modified_tail = modified_tail.replace(
                old_attr,
                new_attr,
            )

            image_count += count

    def optimize_img(match):
        global decoding_count

        tag = match.group(0)
        lower = tag.lower()

        if b'loading="lazy"' not in lower:
            return tag

        if b"decoding=" in lower:
            return tag

        decoding_count += 1

        return (
            tag[:-1]
            + b' decoding="async">'
        )

    modified_tail = IMG_TAG_RE.sub(
        optimize_img,
        modified_tail,
    )

    new_content = (
        head
        + marker
        + modified_tail
    )

    new_head, _ = new_content.split(marker, 1)

    if new_head != head:
        print(
            f"FAIL: {path.name}: HEAD changed"
        )
        sys.exit(1)

    if H1_RE.findall(new_content) != original_h1:
        print(
            f"FAIL: {path.name}: H1 changed"
        )
        sys.exit(1)

    if protected_lines(new_content) != original_protected:
        print(
            f"FAIL: {path.name}: "
            f"MotoAI protected content changed"
        )
        sys.exit(1)

    if (
        motoai_script_lines(new_content)
        != original_moto_scripts
    ):
        print(
            f"FAIL: {path.name}: "
            f"MotoAI external script changed"
        )
        sys.exit(1)

    if new_content != original:
        path.write_bytes(new_content)
        changed_files.append(path.name)
        print(f"CHANGED: {path.name}")
    else:
        print(f"UNCHANGED: {path.name}")

if not changed_files:
    print("FAIL: NO PRODUCTION CHANGES")
    sys.exit(1)

print("")
print("PERFORMANCE BATCH 1 SUMMARY")
print(f"HTML inspected: {len(html_files)}")
print(f"HTML changed: {len(changed_files)}")
print(f"Render.init replacements: {render_count}")
print(f"BODY image src conversions: {image_count}")
print(f'decoding="async" additions: {decoding_count}')
print("HEAD unchanged: YES")
print("H1 unchanged: YES")
print("MotoAI untouched: YES")
