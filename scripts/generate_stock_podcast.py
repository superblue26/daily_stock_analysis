import os
import re
import json
import asyncio
import datetime
from pathlib import Path
from email.utils import format_datetime
import urllib.request
from openai import OpenAI
import edge_tts


def clean_for_tts(text: str) -> str:
    """清除 Markdown 符号和链接，避免 TTS 念出星号、井号等符号"""
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[*#`~>|_•·＊＃＿～｜・●◆■★☆※▶►]+", " ", text)
    text = re.sub(r"^\s*[-—–]+\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


bj_now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
today_str = os.getenv("DATE") or bj_now.strftime("%Y-%m-%d")

# 北京时间 15:00 前视为【美股收盘复盘】，15:00 后视为【美股盘前新闻】
session_tag = os.getenv("SESSION_TAG") or ("close" if bj_now.hour < 15 else "premarket")
session_label = "美股收盘复盘" if session_tag == "close" else "美股盘前新闻"

# 1. 查找 reports/ 下最新的分析报告
reports_dir = Path("reports")
report_files = sorted(
    [p for p in reports_dir.rglob("*") if p.is_file() and p.suffix.lower() in {".md", ".txt"}],
    key=lambda p: p.stat().st_mtime,
    reverse=True,
)

if not report_files:
    print("未找到 reports/ 下的分析报告，跳过博客与播客生成。")
    exit(0)

latest_report = report_files[0]
report_text = latest_report.read_text(encoding="utf-8", errors="ignore")

# 2. 写入静态博客目录 docs/
docs_dir = Path("docs")
posts_dir = docs_dir / "posts"
podcast_dir = docs_dir / "podcast"
posts_dir.mkdir(parents=True, exist_ok=True)
podcast_dir.mkdir(parents=True, exist_ok=True)

post_slug = f"{today_str}-{session_tag}"
daily_post_path = posts_dir / f"{post_slug}.md"
daily_post_path.write_text(
    f"# DSA {session_label}（{today_str}）\n\n{report_text}",
    encoding="utf-8",
)

post_links = "\n".join(
    f"- [{p.stem}](./posts/{p.name})"
    for p in sorted(posts_dir.glob("*.md"), reverse=True)[:40]
)
(docs_dir / "index.md").write_text(
    f"""# DSA 每日投研博客

聚焦美股宽基（VOO/VTI/QQQ）、AI 产业链、马斯克相关标的及港股/QDII 的中长线复盘、盘前新闻催化与投资意见。

## 历史投研归档
{post_links}
""",
    encoding="utf-8",
)
