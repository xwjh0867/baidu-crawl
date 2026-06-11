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

from tqdm import tqdm


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0 Safari/537.36"
)

DEFAULT_BAIDU_GRAPH_URL = "https://graph.baidu.com/pcpage/index"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}

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


def iter_image_files(directory: Path, recursive: bool) -> list[Path]:
    pattern = "**/*" if recursive else "*"
    return sorted(
        path
        for path in directory.glob(pattern)
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )


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


def parse_image_urls(html: str, base_url: str) -> list[str]:
    parser = BaiduGraphImageParser()
    parser.feed(html)
    urls = unique_preserve_order(normalize_url(src, base_url) for src in parser.image_urls)
    if not urls:
        urls = extract_baidu_image_urls(html, base_url)
    return urls


def iter_uploaded_htmls(
    image_paths: list[Path], args: argparse.Namespace
) -> Iterable[tuple[Path, str, str]]:
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise SystemExit(
            "缺少 Playwright 依赖。请先执行：uv sync && uv run playwright install chromium"
        ) from exc

    launch_kwargs: dict[str, object] = {"headless": not args.headed}
    if args.browser_channel:
        launch_kwargs["channel"] = args.browser_channel

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**launch_kwargs)
        context = browser.new_context(user_agent=args.user_agent)
        page = context.new_page()

        try:
            for image_path in image_paths:
                tqdm.write(f"[上传] {image_path}", file=sys.stderr)
                page.goto(
                    args.baidu_url,
                    wait_until="domcontentloaded",
                    timeout=args.browser_timeout,
                )
                page.locator(args.upload_selector).first.set_input_files(str(image_path))

                try:
                    page.wait_for_selector(
                        args.wait_selector,
                        state="attached",
                        timeout=args.browser_timeout,
                    )
                except PlaywrightTimeoutError:
                    tqdm.write(
                        f"[警告] {image_path.name} 上传后没有等到 {args.wait_selector}，"
                        "仍会尝试解析当前页面 HTML。",
                        file=sys.stderr,
                    )

                for _ in range(args.scrolls):
                    page.mouse.wheel(0, args.scroll_pixels)
                    page.wait_for_timeout(args.scroll_wait)

                try:
                    page.wait_for_load_state("networkidle", timeout=args.browser_timeout)
                except PlaywrightTimeoutError:
                    pass

                yield image_path, page.content(), page.url
        finally:
            context.close()
            browser.close()


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


def relative_parent_for_image(source_image: Path, tree_root: Path | None) -> Path:
    if tree_root is None:
        return Path()
    tree_root = tree_root.expanduser()
    try:
        return source_image.resolve().parent.relative_to(tree_root.resolve())
    except ValueError as exc:
        raise SystemExit(f"{source_image} 不在目录树根目录 {tree_root} 下面") from exc


def output_dir_for_image(output_dir: Path, source_image: Path, args: argparse.Namespace) -> Path:
    current_output_dir = output_dir
    if args.preserve_tree:
        current_output_dir = current_output_dir / relative_parent_for_image(
            source_image, Path(args.tree_root).expanduser()
        )
    if args.upload_dir:
        current_output_dir = current_output_dir / source_image.stem
    return current_output_dir


def save_uploaded_html(
    html: str,
    source_image: Path,
    save_html_dir: Path | None,
    encoding: str,
    args: argparse.Namespace,
) -> None:
    if save_html_dir is None:
        return
    if args.preserve_tree:
        save_html_dir = save_html_dir / relative_parent_for_image(
            source_image, Path(args.tree_root).expanduser()
        )
    save_html_dir.mkdir(parents=True, exist_ok=True)
    html_path = save_html_dir / f"{source_image.stem}.html"
    html_path.write_text(html, encoding=encoding)
    tqdm.write(f"[HTML] {html_path}")


def crawl_urls(
    urls: list[str],
    output_dir: Path,
    name_prefix: str,
    args: argparse.Namespace,
) -> int:
    if args.limit > 0:
        urls = urls[: args.limit]

    if not urls:
        print(
            "没有找到图片。百度识图结果通常由浏览器 JS 动态渲染，"
            "--url 只能拿到初始 HTML，可能没有 .graph-similar-list。"
            "请使用 --upload-image/--upload-dir 自动上传图片，或在浏览器等图片显示后保存 DOM/HTML。",
            file=sys.stderr,
        )
        return 1

    if args.dry_run:
        for i, url in enumerate(urls, start=args.start):
            print(f"{name_prefix}_{i:0{args.digits}d}{suffix_from_url(url)}\t{url}")
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)
    force_suffix = f".{args.ext}" if args.ext else None

    success = 0
    progress = tqdm(
        urls,
        desc=f"下载 {name_prefix}",
        disable=args.no_progress,
        unit="张",
        leave=False,
    )
    for offset, url in enumerate(progress):
        index = args.start + offset
        try:
            path = download_one(
                url=url,
                output_dir=output_dir,
                name_prefix=name_prefix,
                index=index,
                digits=args.digits,
                timeout=args.timeout,
                user_agent=args.user_agent,
                force_suffix=force_suffix,
            )
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            tqdm.write(f"[失败] {index:0{args.digits}d} {url} -> {exc}", file=sys.stderr)
            continue

        success += 1
        if args.no_progress:
            print(f"[保存] {path}")
        else:
            progress.set_postfix_str(f"成功 {success}/{len(urls)}")
        if args.sleep > 0 and offset != len(urls) - 1:
            time.sleep(args.sleep)

    print(f"完成：成功下载 {success}/{len(urls)} 张图片，目录：{output_dir.resolve()}")
    return 0 if success else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="爬取百度识图结果页 graph-similar-list 里的图片。"
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--html", help="保存好的百度识图结果页 HTML 文件")
    source.add_argument("--url", help="百度识图结果页 URL")
    source.add_argument("--upload-image", help="用 Playwright 上传单张图片并爬取结果")
    source.add_argument("--upload-dir", help="用 Playwright 逐张上传目录里的图片并爬取结果")
    parser.add_argument("-o", "--output", default="images", help="图片输出目录")
    parser.add_argument("-n", "--name", help="图片名前缀，例如：宝宝；上传目录时不填则使用源图片文件名")
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
    parser.add_argument("--recursive", action="store_true", help="配合 --upload-dir 递归读取图片")
    parser.add_argument("--max-images", type=int, default=0, help="配合 --upload-dir 限制上传图片数量，0 表示不限")
    parser.add_argument("--save-html-dir", help="保存 Playwright 上传后渲染出的 HTML")
    parser.add_argument("--preserve-tree", action="store_true", help="上传模式保留源图片在 --tree-root 下的父目录结构")
    parser.add_argument("--tree-root", help="目录树根目录；默认使用 --upload-dir")
    parser.add_argument("--baidu-url", default=DEFAULT_BAIDU_GRAPH_URL, help="百度识图上传页 URL")
    parser.add_argument(
        "--upload-selector",
        default='input[type="file"][accept*="image"]',
        help="上传 input 的 CSS 选择器",
    )
    parser.add_argument(
        "--wait-selector",
        default=".graph-similar-list img",
        help="上传后等待出现的结果 CSS 选择器",
    )
    parser.add_argument("--browser-timeout", type=float, default=30000, help="Playwright 等待超时毫秒数")
    parser.add_argument("--headed", action="store_true", help="显示浏览器窗口，便于调试")
    parser.add_argument(
        "--browser-channel",
        help="使用本机浏览器渠道，例如 chrome；不设置则使用 Playwright Chromium",
    )
    parser.add_argument("--scrolls", type=int, default=3, help="上传后向下滚动次数，用于加载更多结果")
    parser.add_argument("--scroll-pixels", type=int, default=2000, help="每次滚动像素数")
    parser.add_argument("--scroll-wait", type=int, default=3000, help="每次滚动后等待毫秒数")
    parser.add_argument("--no-progress", action="store_true", help="关闭 tqdm 进度条")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output)

    if args.html or args.url:
        if not args.name:
            raise SystemExit("--html/--url 模式必须提供 -n/--name")
        html, base_url = read_html(args)
        return crawl_urls(parse_image_urls(html, base_url), output_dir, args.name, args)

    if args.upload_image:
        image_paths = [Path(args.upload_image).expanduser()]
    else:
        upload_dir = Path(args.upload_dir).expanduser()
        image_paths = iter_image_files(upload_dir, args.recursive)
        if args.max_images > 0:
            image_paths = image_paths[: args.max_images]

    if not image_paths:
        raise SystemExit("没有找到可上传的图片文件")

    if args.preserve_tree and not args.tree_root:
        if args.upload_dir:
            args.tree_root = str(Path(args.upload_dir).expanduser())
        else:
            raise SystemExit("--upload-image 使用 --preserve-tree 时必须提供 --tree-root")

    save_html_dir = Path(args.save_html_dir).expanduser() if args.save_html_dir else None
    exit_code = 0
    with tqdm(
        total=len(image_paths),
        desc="源图片",
        disable=args.no_progress,
        unit="张",
    ) as source_progress:
        for image_path, html, base_url in iter_uploaded_htmls(image_paths, args):
            try:
                if not args.no_progress:
                    source_progress.set_postfix_str(image_path.name[:40])
                save_uploaded_html(html, image_path, save_html_dir, args.encoding, args)
                name_prefix = args.name or image_path.stem
                current_output_dir = output_dir_for_image(output_dir, image_path, args)
                urls = parse_image_urls(html, base_url)
                result = crawl_urls(urls, current_output_dir, name_prefix, args)
                if result != 0:
                    exit_code = result
            finally:
                source_progress.update(1)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
