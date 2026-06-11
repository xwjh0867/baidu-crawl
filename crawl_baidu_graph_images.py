#!/usr/bin/env python3
"""Download image URLs from a Baidu Graph similar-image result HTML page."""

from __future__ import annotations

import argparse
import mimetypes
import re
import sys
import time
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urljoin, urlparse, parse_qs
from urllib.request import Request, urlopen


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0 Safari/537.36"
)

VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


class BaiduGraphImageParser(HTMLParser):
    """Collect img src values inside div.graph-similar-list."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.image_urls: list[str] = []
        self._stack: list[str] = []
        self._target_depth: int | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        class_names = set((attr.get("class") or "").split())

        if self._target_depth is None and "graph-similar-list" in class_names:
            self._target_depth = len(self._stack) + 1

        tag = tag.lower()
        if self._target_depth is not None and tag == "img":
            src = attr.get("src") or attr.get("data-src")
            if src:
                self.image_urls.append(src.strip())

        if tag not in VOID_TAGS:
            self._stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if not self._stack:
            return

        if self._target_depth is not None and len(self._stack) == self._target_depth:
            self._target_depth = None

        # HTMLParser is forgiving; remove the nearest matching tag to keep depth usable.
        tag = tag.lower()
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i] == tag:
                del self._stack[i:]
                break


def read_html(args: argparse.Namespace) -> tuple[str, str]:
    if args.html:
        path = Path(args.html)
        return path.read_text(encoding=args.encoding), path.resolve().as_uri()

    if args.url:
        request = Request(args.url, headers={"User-Agent": args.user_agent})
        with urlopen(request, timeout=args.timeout) as response:
            raw = response.read()
            charset = response.headers.get_content_charset() or args.encoding
        return raw.decode(charset, errors="replace"), args.url

    raise SystemExit("必须提供 --html 或 --url")


def unique_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            result.append(value)
            seen.add(value)
    return result


def normalize_url(src: str, base_url: str) -> str:
    if src.startswith("//"):
        return "https:" + src
    return urljoin(base_url, src)


def extract_baidu_image_urls(html: str, base_url: str) -> list[str]:
    """Fallback for saved DOM fragments or encoded image= URLs in Baidu links."""
    text = unquote(unescape(html))
    patterns = [
        r"(?:https?:)?//mms\d+\.baidu\.com/it/u=[^\"'<> \t\r\n]+?\?w=\d+&h=\d+",
        r"(?:https?:)?//mms\d+\.baidu\.com/it/[^\"'<> \t\r\n]+",
    ]

    matches: list[str] = []
    for pattern in patterns:
        matches.extend(re.findall(pattern, text, flags=re.IGNORECASE))

    cleaned = []
    for url in matches:
        url = re.sub(r"&(?:index|inspire|next|originSign|page|render_type)=.*$", "", url)
        cleaned.append(normalize_url(url, base_url))
    return unique_preserve_order(cleaned)


def suffix_from_url(url: str) -> str:
    parsed = urlparse(url)
    path_suffix = Path(parsed.path).suffix.lower()
    if path_suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}:
        return ".jpg" if path_suffix == ".jpeg" else path_suffix

    query = parse_qs(parsed.query)
    fmt = query.get("f", [""])[0].lower()
    if fmt in {"jpeg", "jpg"}:
        return ".jpg"
    if fmt in {"png", "webp", "gif", "bmp"}:
        return "." + fmt

    decoded_url = unquote(url).lower()
    match = re.search(r"[?&]f=(jpeg|jpg|png|webp|gif|bmp)\b", decoded_url)
    if match:
        fmt = match.group(1)
        return ".jpg" if fmt in {"jpeg", "jpg"} else "." + fmt

    return ".jpg"


def suffix_from_response(content_type: str | None, fallback: str) -> str:
    if not content_type:
        return fallback
    media_type = content_type.split(";", 1)[0].strip().lower()
    guessed = mimetypes.guess_extension(media_type)
    if guessed == ".jpe":
        return ".jpg"
    return guessed or fallback


def download_one(
    url: str,
    output_dir: Path,
    name_prefix: str,
    index: int,
    digits: int,
    timeout: float,
    user_agent: str,
    force_suffix: str | None,
) -> Path:
    fallback_suffix = force_suffix or suffix_from_url(url)
    request = Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Referer": "https://graph.baidu.com/",
        },
    )

    with urlopen(request, timeout=timeout) as response:
        data = response.read()
        suffix = force_suffix or suffix_from_response(
            response.headers.get("Content-Type"), fallback_suffix
        )

    filename = f"{name_prefix}_{index:0{digits}d}{suffix}"
    path = output_dir / filename
    path.write_bytes(data)
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="爬取百度识图结果页 graph-similar-list 里的图片。"
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--html", help="保存好的百度识图结果页 HTML 文件")
    source.add_argument("--url", help="百度识图结果页 URL")
    parser.add_argument("-o", "--output", default="images", help="图片输出目录")
    parser.add_argument("-n", "--name", required=True, help="图片名前缀，例如：宝宝")
    parser.add_argument("--start", type=int, default=0, help="起始编号，默认 0")
    parser.add_argument("--digits", type=int, default=6, help="编号位数，默认 6")
    parser.add_argument("--limit", type=int, default=0, help="最多下载多少张，0 表示不限")
    parser.add_argument("--sleep", type=float, default=0.2, help="每张下载间隔秒数")
    parser.add_argument("--timeout", type=float, default=20, help="请求超时时间秒数")
    parser.add_argument("--encoding", default="utf-8", help="HTML 默认编码")
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    parser.add_argument(
        "--ext",
        choices=["jpg", "png", "webp", "gif", "bmp"],
        help="强制保存扩展名；不设置时按 URL/响应类型判断",
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印图片 URL，不下载")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    html, base_url = read_html(args)

    parser = BaiduGraphImageParser()
    parser.feed(html)
    urls = unique_preserve_order(normalize_url(src, base_url) for src in parser.image_urls)
    if not urls:
        urls = extract_baidu_image_urls(html, base_url)
    if args.limit > 0:
        urls = urls[: args.limit]

    if not urls:
        print(
            "没有找到图片。百度识图结果通常由浏览器 JS 动态渲染，"
            "--url 只能拿到初始 HTML，可能没有 .graph-similar-list。"
            "请在浏览器等图片显示后保存 DOM/HTML，再用 --html test.html。",
            file=sys.stderr,
        )
        return 1

    if args.dry_run:
        for i, url in enumerate(urls, start=args.start):
            print(f"{args.name}_{i:0{args.digits}d}{suffix_from_url(url)}\t{url}")
        return 0

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    force_suffix = f".{args.ext}" if args.ext else None

    success = 0
    for offset, url in enumerate(urls):
        index = args.start + offset
        try:
            path = download_one(
                url=url,
                output_dir=output_dir,
                name_prefix=args.name,
                index=index,
                digits=args.digits,
                timeout=args.timeout,
                user_agent=args.user_agent,
                force_suffix=force_suffix,
            )
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            print(f"[失败] {index:0{args.digits}d} {url} -> {exc}", file=sys.stderr)
            continue

        success += 1
        print(f"[保存] {path}")
        if args.sleep > 0 and offset != len(urls) - 1:
            time.sleep(args.sleep)

    print(f"完成：成功下载 {success}/{len(urls)} 张图片，目录：{output_dir.resolve()}")
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
