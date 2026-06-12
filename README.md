# 百度识图图片爬取脚本

这个项目用 `crawl_baidu_graph_images.py` 从百度识图结果页 HTML 中提取并下载相似图片。

脚本支持两种方式：

- 直接解析已经保存好的百度识图 HTML。
- 使用 Playwright 自动打开百度识图、上传本地图片、获取渲染后的 HTML，再下载相似图片。

## 环境准备

安装 `uv` 后，在项目目录执行：

```bash
uv sync
```

这会根据 `pyproject.toml` 创建 `.venv` 环境并安装 Python 依赖。

首次使用 Playwright 上传模式时，还需要安装浏览器内核：

```bash
uv run playwright install chromium
```

## 使用方法

### 使用本地 HTML

```bash
uv run python crawl_baidu_graph_images.py --html /Users/wangzhihua1/code/baidu-crawl/test.html -o "images/唱歌/image0" -n "唱歌"
```

参数说明：

- `--html`：保存好的百度识图结果页 HTML 文件。
- `--url`：百度识图结果页 URL，和 `--html` 二选一。百度结果常由浏览器 JS 动态渲染，直接用 URL 可能拿不到图片列表。
- `-o, --output`：图片输出目录，默认 `images`。
- `-n, --name`：图片名前缀。`--html/--url` 模式必填；上传目录时不填则使用源图片文件名。
- `--limit`：最多下载多少张，`0` 表示不限。
- `--start`：起始编号，默认 `0`。
- `--digits`：编号位数，默认 `6`。
- `--sleep`：每张下载间隔秒数，默认 `0.2`。
- `--ext`：强制保存扩展名，可选 `jpg`、`png`、`webp`、`gif`、`bmp`。
- `--dry-run`：只打印将要下载的图片 URL，不实际下载。
- `--upload-image`：用 Playwright 上传单张本地图片并爬取结果。
- `--upload-dir`：用 Playwright 逐张上传目录里的图片并爬取结果。
- `--max-images`：配合 `--upload-dir` 限制上传图片数量。
- `--recursive`：配合 `--upload-dir` 递归读取图片。
- `--save-html-dir`：保存 Playwright 获取到的渲染后 HTML，便于排查。
- `--preserve-tree`：上传模式保留源图片在 `--tree-root` 下的父目录结构。
- `--tree-root`：目录树根目录；默认使用 `--upload-dir`。
- `--headed`：显示浏览器窗口，便于观察上传过程。
- `--browser-channel chrome`：使用本机 Chrome，而不是 Playwright 下载的 Chromium。
- `--scrolls`：上传后向下滚动次数，用于加载更多结果，默认 `3`。
- `--scroll-pixels`：每次滚动像素数，默认 `2000`。
- `--scroll-wait`：每次滚动后等待毫秒数，默认 `3000`。
- `--no-progress`：关闭进度条，适合把输出重定向到日志文件时使用。
- `--workers`：并发上传源图片的 Playwright worker 数，默认 `1`。
- `--download-workers`：每张源图相似图片下载并发数，默认 `1`。

先检查能提取到哪些图片 URL：

```bash
uv run python crawl_baidu_graph_images.py --html /Users/wangzhihua1/code/baidu-crawl/test.html -o "唱歌/image0" -n "唱歌" --dry-run
```

限制只下载前 20 张：

```bash
uv run python crawl_baidu_graph_images.py --html /Users/wangzhihua1/code/baidu-crawl/test.html -o "唱歌/image0" -n "唱歌" --limit 20
```

### 自动上传单张图片

```bash
uv run python crawl_baidu_graph_images.py \
  --upload-image /path/to/input.jpg \
  -o "images/result0" \
  -n "result" \
  --save-html-dir "html"
```

### 自动上传目录里的图片

下面的命令会逐张上传目录中的图片。每张源图片会在 `images/viewangle/` 下生成一个同名子目录，保存对应的相似图片结果。

```bash
uv run python crawl_baidu_graph_images.py \
  --upload-dir /Users/wangzhihua1/Downloads/tetras_cls_errors_thumbs/thumbnails/FN/Activity/ViewAngle \
  -o "images/viewangle2" \
  --scrolls 6 \
  --scroll-pixels 3000 \
  --scroll-wait 5000 \
  --save-html-dir "html/viewangle"
```

脚本会按“上传 1 张 -> 保存这 1 张的 HTML -> 解析并下载这 1 张的结果”的顺序处理，不会等全部 HTML 保存完再开始爬取。

上传目录时会显示两个进度条：外层是源图片处理进度，内层是当前源图片的相似图片下载进度。

图片很多时可以开启并发。建议先从较小并发开始，避免百度页面风控或本机浏览器实例占用过高：

```bash
uv run python crawl_baidu_graph_images.py \
  --upload-dir /Users/wangzhihua1/code/baidu-crawl/thumbnails_v2/FN \
  --recursive \
  --preserve-tree \
  -o "images/thumbnails_v2/FN" \
  --save-html-dir "html/thumbnails_v2/FN" \
  --workers 2 \
  --download-workers 4
```

`--workers` 会启动多个 Playwright browser worker 并发上传源图；`--download-workers` 只影响每张源图解析出的相似图片下载。

### 保留源目录树

如果要保留 `/Users/wangzhihua1/code/baidu-crawl/thumbnails_v2/FN` 后面的目录树，使用 `--upload-dir` 指向这个根目录，并加上 `--recursive --preserve-tree`：

```bash
uv run python crawl_baidu_graph_images.py \
  --upload-dir /Users/wangzhihua1/code/baidu-crawl/uncrawled_9_categories.txt \
  --recursive \
  --preserve-tree \
  -o "images/thumbnails_FN2/" \
  --save-html-dir "html/thumbnails_FN2" \
  --scrolls 3 \
  --scroll-pixels 3000 \
  --scroll-wait 5000 \
  --workers 2 \
  --download-workers 4

```

例如源图片：

```text
thumbnails_v2/FN/包/ExtremeLighting/包_000001.jpg
```

对应输出目录会是：

```text
images/thumbnails_v2/FN/包/ExtremeLighting/包_000001/
html/thumbnails_v2/FN/包/ExtremeLighting/包_000001.html
```

先只测试 1 张，并只打印 URL 不下载：

```bash
uv run python crawl_baidu_graph_images.py \
  --upload-dir /Users/wangzhihua1/Downloads/tetras_cls_errors_thumbs/thumbnails/FN/Activity/ViewAngle \
  -o "images/viewangle" \
  --max-images 1 \
  --limit 5 \
  --dry-run \
  --headed
```

## 保存百度识图 HTML

如果 `--url` 找不到图片，通常是因为页面内容由浏览器动态渲染。建议在浏览器中打开百度识图结果页，等图片列表加载完成后保存当前页面 HTML 或 DOM，再用 `--html` 参数运行脚本。

上传模式默认使用这个选择器定位上传控件：

```text
input[type="file"][accept*="image"]
```

如果百度页面结构变了，可以用 `--upload-selector` 指定新的 `input[type=file]` 选择器。

例如使用页面里的上传控件 class：

```bash
--upload-selector 'input.general-upload-file[name="file"]'
```
