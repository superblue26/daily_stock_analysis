import datetime
import json
import os
import urllib.request
import xml.etree.ElementTree as ET
from openai import OpenAI

# 覆盖 5 大方向的权威财经 RSS 源（无需额外依赖，单源超时不影响整体）
RSS_FEEDS = [
    ("Yahoo Finance", "https://finance.yahoo.com/news/rssindex"),
    ("CNBC Finance", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664"),
    ("CNBC Tech", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=19854910"),
    ("CNBC Economy", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258"),
    ("Investing Macro", "https://www.investing.com/rss/news_25.rss"),
    ("Investing Commodities", "https://www.investing.com/rss/news_11.rss"),
    ("Investing Forex", "https://www.investing.com/rss/news_1.rss"),
]


def fetch_rss_items(max_per_feed=8):
    """抓取最新财经与宏观资讯"""
    items = []
    headers = {"User-Agent": "Mozilla/5.0 (compatible; WeekendReportBot/1.0)"}
    for source_name, url in RSS_FEEDS:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=12) as resp:
                xml_data = resp.read()
            root = ET.fromstring(xml_data)
            count = 0
            for item in root.findall(".//item"):
                title = (item.findtext("title") or "").strip()
                desc = (item.findtext("description") or "").strip()[:200]
                if title:
                    items.append(f"[{source_name}] {title} | {desc}")
                    count += 1
                if count >= max_per_feed:
                    break
        except Exception as e:
            print(f"抓取 {source_name} 失败（已跳过）: {e}")
    return "\n".join(items)[:10000] if items else "暂无最新 RSS 素材，请结合近期宏观与市场主线进行深度梳理。"


def generate_weekend_report(news_text, date_str, edition):
    """优先使用 gemini-3.8-flash，失败自动降级到 deepseek-chat"""
    prompt = f"""你是一位资深宏观经济与跨市场金融首席分析师。现在是 {date_str}（{edition}）。
请基于以下最新国际与国内财经资讯，撰写一份逻辑严密、数据导向的《周末深度金融研报》。

必须严格按以下 5 大板块输出（每板块提炼 2-3 条核心洞察，拒绝空话套话，直接给事实、数据逻辑和影响传导）：
1. **美股科技与 AI**：核心算力/大模型动态、头部科技股财报或资本开支动向、纳指情绪。
2. **A 股与宏观政策**：国内货币/财政政策信号、重要产业政策、北向/市场流动性与板块主线。
3. **黄金与大宗商品**：现货黄金、原油及工业金属走势逻辑、避险情绪与供需变化。
4. **美联储利率与汇率**：美联储表态、降息/加息预期概率、美债收益率、美元指数及人民币汇率动态。
5. **进出口贸易**：全球贸易摩擦/关税动向、中美欧进出口数据变化及供应链影响。

最后增加一个 **【下周重磅事件与观察清单】**，列出 3 条最值得盯盘的宏观数据或事件。
格式要求：纯文本分段清晰，适合在飞书直接阅读，总字数控制在 1200-1600 字。

参考最新资讯素材：
{news_text}
"""

    gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("AI_API_KEY")
    if gemini_key:
        try:
            client = OpenAI(
                api_key=gemini_key,
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            )
            resp = client.chat.completions.create(
                model="gemini-3.8-flash",
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            print(f"Gemini 调用失败，切换 DeepSeek: {e}")

    deepseek_key = os.getenv("DEEPSEEK_API_KEY")
    if deepseek_key:
        try:
            client = OpenAI(
                api_key=deepseek_key,
                base_url="https://api.deepseek.com",
            )
            resp = client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            print(f"DeepSeek 调用失败: {e}")

    return "⚠️ 本次周末研报生成失败：请检查仓库 Secrets 中的 GEMINI_API_KEY 或 DEEPSEEK_API_KEY 配置。"


def push_to_feishu(title, content):
    webhook = os.getenv("FEISHU_WEBHOOK_URL")
    if not webhook:
        raise ValueError("未配置 FEISHU_WEBHOOK_URL，无法推送到飞书。")

    payload = {
        "msg_type": "text",
        "content": {"text": f"{title}\n{'━' * 20}\n{content}"},
    }
    req = urllib.request.Request(
        webhook,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        print("飞书推送状态:", resp.status)


def main():
    tz_cn = datetime.timezone(datetime.timedelta(hours=8))
    now_cn = datetime.datetime.now(tz_cn)
    date_str = now_cn.strftime("%Y-%m-%d %H:%M")
    edition = "早间深度版" if now_cn.hour < 15 else "晚间更新版"

    news_text = fetch_rss_items()
    report = generate_weekend_report(news_text, date_str, edition)
    title = f"📊 周末深度金融研报（{now_cn.strftime('%m-%d')} {edition}）"
    push_to_feishu(title, report)
    print("✅ 周末深度研报推送完成")


if __name__ == "__main__":
    main()
