# 百度识图图片爬取脚本

这个项目用 `crawl_baidu_graph_images.py` 从百度识图结果页 HTML 中提取并下载相似图片。

脚本当前只依赖 Python 标准库，`uv` 环境用于固定 Python 版本要求并提供一键创建虚拟环境的方式。

## 环境准备

安装 `uv` 后，在项目目录执行：

```bash
uv sync
```

这会根据 `pyproject.toml` 创建 `.venv` 环境。项目没有第三方 Python 依赖，所以同步过程只会准备虚拟环境。

## 使用方法

使用本地保存好的百度识图 HTML：

```bash
uv run python crawl_baidu_graph_images.py --html /Users/wangzhihua1/code/baidu-crawl/test.html -o "images/唱歌/image0" -n "唱歌"
```

参数说明：

- `--html`：保存好的百度识图结果页 HTML 文件。
- `--url`：百度识图结果页 URL，和 `--html` 二选一。百度结果常由浏览器 JS 动态渲染，直接用 URL 可能拿不到图片列表。
- `-o, --output`：图片输出目录，默认 `images`。
- `-n, --name`：图片名前缀，必填。
- `--limit`：最多下载多少张，`0` 表示不限。
- `--start`：起始编号，默认 `0`。
- `--digits`：编号位数，默认 `6`。
- `--sleep`：每张下载间隔秒数，默认 `0.2`。
- `--ext`：强制保存扩展名，可选 `jpg`、`png`、`webp`、`gif`、`bmp`。
- `--dry-run`：只打印将要下载的图片 URL，不实际下载。

先检查能提取到哪些图片 URL：

```bash
uv run python crawl_baidu_graph_images.py --html /Users/wangzhihua1/code/baidu-crawl/test.html -o "唱歌/image0" -n "唱歌" --dry-run
```

限制只下载前 20 张：

```bash
uv run python crawl_baidu_graph_images.py --html /Users/wangzhihua1/code/baidu-crawl/test.html -o "唱歌/image0" -n "唱歌" --limit 20
```

## 保存百度识图 HTML

如果 `--url` 找不到图片，通常是因为页面内容由浏览器动态渲染。建议在浏览器中打开百度识图结果页，等图片列表加载完成后保存当前页面 HTML 或 DOM，再用 `--html` 参数运行脚本。
