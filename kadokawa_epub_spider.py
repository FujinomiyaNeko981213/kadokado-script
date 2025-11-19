# -*- coding: utf-8 -*-
"""
台湾角川页面抓取 → EPUB（单章=单页 article.css-vurnku）
- 打开可见浏览器（非无头）
- 抓取 article.css-vurnku 的全部 HTML 内容，写入 EPUB 的一个章节
- 完成后等待 WAIT_SEC 秒，点击 button.css-16mch31 进入下一章
- 循环直到没有“下一章”按钮或达到 MAX_CHAPTERS
"""

# ========= 这里配置参数（仅需改这里） =========
START_URL     = "https://www.kadokado.com.tw/chapter/237486?titleId=24273&ownerId=71334"  # 起始页面（第一章）URL
OUTPUT_PATH   = "天才少女想和我做的十件事.epub"                         # EPUB 输出文件名
MAX_CHAPTERS  = 56                                  # 最大抓取章节数
WAIT_SEC      = 30                                   # 每章完成后的等待秒数（按你要求默认 10s）
TIMEOUT       = 30                                   # 等待元素出现的超时（秒）
CLOSE_DELAY   = 0                                    # 抓取结束后延时关闭浏览器（秒）；设为 0 不自动关闭
USER_AGENT    = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                 "AppleWebKit/537.36 (KHTML, like Gecko) "
                 "Chrome/122.0.0.0 Safari/537.36")
# ============================================

import os
import re
import time
import traceback
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from ebooklib import epub
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager


def safe_filename(name: str) -> str:
    name = re.sub(r"[\\/:*?\"<>|]+", "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name or "chapter"


def sanitize_html(html: str, base_url: str):
    """
    - 规范相对链接为绝对链接
    - 处理懒加载图片
    - 移除 script/style
    - 返回 (soup, image_urls)
    """
    soup = BeautifulSoup(html, "lxml")

    # 链接/图片/资源转绝对路径
    for tag in soup.find_all(["a", "img", "source"]):
        attr = "href" if tag.name == "a" else "src"
        if tag.has_attr(attr):
            tag[attr] = urljoin(base_url, tag[attr])

    # 懒加载图片兜底
    for img in soup.find_all("img"):
        for lazy_attr in ["data-src", "data-original", "data-lazy", "data-url"]:
            if img.get(lazy_attr) and not img.get("src"):
                img["src"] = urljoin(base_url, img[lazy_attr])
        for k in list(img.attrs.keys()):
            if k.lower().startswith("on"):  # 移除 onload 等
                del img[k]

    # 收集图片 URL
    image_urls = []
    for img in soup.find_all("img"):
        src = img.get("src")
        if src and src.startswith(("http://", "https://")):
            image_urls.append(src)

    # 清理脚本/样式
    for s in soup(["script", "style"]):
        s.decompose()

    # 去重保持顺序
    image_urls = list(dict.fromkeys(image_urls))
    return soup, image_urls


def guess_media_type(ext: str) -> str:
    ext = ext.lower()
    return {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".gif": "image/gif",
        ".webp": "image/webp", ".svg": "image/svg+xml"
    }.get(ext, "image/jpeg")


def download_images(image_urls, book, session, chapter_idx):
    """
    下载图片并加入 EPUB 资源，返回 {原url: (epub_path, item_id)}
    """
    mapping = {}
    for i, url in enumerate(image_urls, start=1):
        try:
            path = urlparse(url).path
            ext = os.path.splitext(path)[1].lower() or ".jpg"
            if ext not in [".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"]:
                ext = ".jpg"
            item_id = f"img_{chapter_idx}_{i}"
            epub_path = f"images/{item_id}{ext}"

            headers = {"User-Agent": USER_AGENT}
            resp = session.get(url, headers=headers, timeout=20)
            resp.raise_for_status()

            img_item = epub.EpubItem(
                uid=item_id, file_name=epub_path, media_type=guess_media_type(ext),
                content=resp.content
            )
            book.add_item(img_item)
            mapping[url] = (epub_path, item_id)
        except Exception:
            traceback.print_exc()
    return mapping


def escape_html(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def make_chapter_html(title: str, soup: BeautifulSoup, url2epubpath: dict) -> str:
    # 替换 img 为 EPUB 内部路径，并补 alt
    for img in soup.find_all("img"):
        src = img.get("src")
        if src in url2epubpath:
            img["src"] = url2epubpath[src][0]
        if "alt" not in img.attrs:
            img["alt"] = ""

    body = str(soup)
    xhtml = f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" lang="zh-Hant">
  <head>
    <meta charset="utf-8" />
    <title>{escape_html(title)}</title>
  </head>
  <body>
    <h1>{escape_html(title)}</h1>
    {body}
  </body>
</html>
"""
    return xhtml


def build_driver():
    # 可见浏览器（不要无头）
    chrome_opts = webdriver.ChromeOptions()
    chrome_opts.add_argument("--start-maximized")
    chrome_opts.add_argument(f"user-agent={USER_AGENT}")
    # 如果需要手动登录或保留会话，可以添加用户数据目录：
    # chrome_opts.add_argument(r'--user-data-dir=/path/to/your/chrome-profile')

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_opts)
    return driver


def main():
    driver = build_driver()
    wait = WebDriverWait(driver, TIMEOUT)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    # 初始化 EPUB
    book = epub.EpubBook()
    book.set_identifier(f"tw-kadokawa-{int(time.time())}")
    book.set_title("天才少女想和我做的十件事")
    book.set_language("zh")
    book.add_author("沢谷 暖日")

    spine = ["nav"]
    toc = []

    try:
        driver.get(START_URL)

        for idx in range(1, MAX_CHAPTERS + 1):
            # 等待正文
            try:
                article = wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "article.css-vurnku"))
                )
            except Exception:
                print(f"[WARN] 未找到正文 article.css-vurnku，停止。")
                break

            # 章节标题用页面标题，做个安全清洗
            title = safe_filename(driver.title or f"第{idx}章")

            # 抓取并清洗 HTML
            inner_html = article.get_attribute("innerHTML")
            soup, image_urls = sanitize_html(inner_html, driver.current_url)

            # 下载图片 → 写入 EPUB
            url2epubpath = download_images(image_urls, book, session, idx)
            chapter_html = make_chapter_html(title, soup, url2epubpath)

            chap = epub.EpubHtml(
                title=title, file_name=f"chap_{idx:04d}.xhtml", lang="zh"
            )
            chap.set_content(chapter_html.encode("utf-8"))
            book.add_item(chap)
            spine.append(chap)
            toc.append(chap)
            print(f"[OK] 已保存章节：{title}")

            # 等待 10 秒（或 WAIT_SEC）
            time.sleep(WAIT_SEC)

            # 找“下一章”按钮
            try:
                next_btn = driver.find_element(By.CSS_SELECTOR, "button.css-16mch31")
            except Exception:
                print("[INFO] 未找到下一章按钮，结束。")
                break

            # 滚动并点击
            driver.execute_script(
                "arguments[0].scrollIntoView({behavior:'instant',block:'center'});",
                next_btn
            )
            time.sleep(0.3)
            try:
                next_btn.click()
            except Exception:
                driver.execute_script("arguments[0].click();", next_btn)

            # 等待旧正文失效（页面切换/刷新）
            try:
                wait.until(EC.staleness_of(article))
            except Exception:
                time.sleep(1.5)

        # 组织导航并写出 EPUB
        book.toc = toc
        book.spine = spine
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())

        style = """
        body { font-family: serif; line-height: 1.6; }
        img { max-width: 100%; height: auto; }
        h1 { font-size: 1.4em; margin: 0.6em 0; }
        """
        nav_css = epub.EpubItem(uid="style_nav", file_name="style/nav.css",
                                media_type="text/css", content=style)
        book.add_item(nav_css)

        epub.write_epub(OUTPUT_PATH, book, {})
        print(f"\n[DONE] EPUB 已生成：{OUTPUT_PATH}")

    finally:
        if CLOSE_DELAY > 0:
            try:
                print(f"浏览器将在 {CLOSE_DELAY} 秒后关闭…（如需保留，请 Ctrl+C 中断）")
                time.sleep(CLOSE_DELAY)
            except KeyboardInterrupt:
                print("已保留浏览器窗口。")
                return
        driver.quit()


if __name__ == "__main__":
    main()
