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
    """彻底清除半角/全角 Markdown 符号、URL 和装饰符，杜绝 TTS 念出'星号''井号'"""
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[*#`~>|_•·＊＃＿～｜・●◆■★☆※▶►]+", " ", text)
    text = re.sub(r"^\s*[-—–]+\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


bj_now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
today_str = os.getenv("DATE") or bj_now.strftime("%Y-%m-%d")

# 自动判断当前是【收盘复盘】还是【盘前新闻】（北京时间 15:00 前视为收盘复盘，15:00 后视为盘前新闻）
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

聚焦美股宽基、AI 产业链、马斯克相关标的及港股/QDII 的中长线复盘、盘前新闻催化与投资意见。

## 历史投研归档
{post_links}
""",
    encoding="utf-8",
)

# 3. 调用 DeepSeek 生成纯口语播客稿 + 金融英文原声精读
api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
base_url = "https://api.deepseek.com" if os.environ.get("DEEPSEEK_API_KEY") else os.environ.get("OPENAI_BASE_URL")

if not api_key:
    print("未检测到 AI API Key，已更新博客但跳过语音合成。")
    exit(0)

client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)

focus_instruction = (
    "重点复盘隔夜美股宽基表现、AI 算力与应用龙头走势、马斯克系标的动态，并给出清晰的中长线持仓、估值评估与分批观察建议。"
    if session_tag == "close"
    else "重点播报美股开盘前最新财经要闻、宏观数据或政策预期、AI 与马斯克系盘前催化剂，以及今日开盘前后的中长线观察重点与风险提示。"
)

prompt = f"""你是一位稳健、专业且中英文发音俱佳的投研播客主播。请根据以下今日《{session_label}》分析素材，撰写一篇适合收听的纯文本播客稿（约 1200-1500 字，约 5 分钟）。

【格式铁律】：
1. 全文必须是纯粹的自然口语段落，绝对禁止出现任何星号、井号、短横线、下划线、括号标签或项目符号，防止语音引擎念出符号。
2. 段落间用空行分隔，便于自然停顿。

【内容结构】：
1. 开场报出日期（{today_str}）与档期（{session_label}）。
2. 核心投研内容：{focus_instruction}
3. 金融英文原声精读：紧扣今日美股或 AI 产业新闻，撰写一段约 80-100 词的地道英文财经新闻原文（内部绝对不夹杂中文），先用一句中文引出并完整朗读英文段落，再用两句中文概括大意，最后精讲 4 个高频英文词汇的中文含义与同义替换词。

分析素材：
{report_text[:15000]}
"""

resp = client.chat.completions.create(
    model="deepseek-chat" if os.environ.get("DEEPSEEK_API_KEY") else (os.environ.get("OPENAI_MODEL") or "gpt-4o-mini"),
    messages=[{"role": "user", "content": prompt}],
    temperature=0.35,
    max_tokens=3000,
)
script_text = clean_for_tts(resp.choices[0].message.content.strip())

mp3_filename = f"dsa-{post_slug}.mp3"
mp3_path = podcast_dir / mp3_filename


async def synthesize():
    communicate = edge_tts.Communicate(script_text, voice="zh-CN-XiaoxiaoNeural", rate="+2%")
    await communicate.save(str(mp3_path))


asyncio.run(synthesize())

# 4. 更新播客 RSS Feed（保留最近 40 期）
repo_owner, repo_name = os.getenv("GITHUB_REPOSITORY", "superblue26/daily_stock_analysis").split("/")
base_url_pages = f"https://{repo_owner.lower()}.github.io/{repo_name}"
podcast_base = f"{base_url_pages}/podcast"
audio_url = f"{podcast_base}/{mp3_filename}"

mp3_files = sorted(podcast_dir.glob("dsa-*.mp3"), reverse=True)[:40]
items_xml = []
for f in mp3_files:
    stem = f.stem.replace("dsa-", "")
    parts = stem.split("-")
    date_part = "-".join(parts[:3])
    tag_part = parts[3] if len(parts) > 3 else "close"
    ep_title = f"DSA {'收盘复盘' if tag_part == 'close' else '盘前新闻'} - {date_part}"
    size_bytes = f.stat().st_size
    pub_dt = datetime.datetime.strptime(date_part, "%Y-%m-%d").replace(
        hour=5 if tag_part == "close" else 21,
        tzinfo=datetime.timezone(datetime.timedelta(hours=8)),
    )
    pub_rfc822 = format_datetime(pub_dt)
    item_url = f"{podcast_base}/{f.name}"
    items_xml.append(
        f"""    <item>
      <title>{ep_title}</title>
      <description>美股宽基、AI 链、马斯克系、港股/QDII 中长线复盘与盘前新闻精读。</description>
      <pubDate>{pub_rfc822}</pubDate>
      <enclosure url="{item_url}" length="{size_bytes}" type="audio/mpeg" />
      <guid>{item_url}</guid>
    </item>"""
    )

rss_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>DSA 每日投研 · 收盘与盘前双播</title>
    <link>{podcast_base}/podcast.xml</link>
    <description>美股收盘复盘与开盘前新闻双档播客，聚焦美股宽基、AI、马斯克系及中长线投资意见。</description>
    <language>zh-cn</language>
    <itunes:author>DSA Research</itunes:author>
    <itunes:explicit>false</itunes:explicit>
{chr(10).join(items_xml)}
  </channel>
</rss>
"""
(podcast_dir / "podcast.xml").write_text(rss_xml, encoding="utf-8")

# 5. 推送博客与音频链接到飞书
feishu_url = os.getenv("FEISHU_WEBHOOK_URL")
if feishu_url:
    payload = {
        "msg_type": "text",
        "content": {
            "text": (
                f"📈 DSA【{session_label}】博客与语音播客已更新 ({today_str})\n\n"
                f"📝 投研博客：{base_url_pages}/\n"
                f"🎧 本期音频：{audio_url}\n"
                f"📡 播客订阅源：{podcast_base}/podcast.xml"
            )
        },
    }
    req = urllib.request.Request(
        feishu_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=10)
        print("飞书通知发送成功！")
    except Exception as e:
        print(f"飞书通知发送失败: {e}")
