# -*- coding: utf-8 -*-
"""
kadokawa_cookie_epub_manual_login.py
方案：在登录页面等待用户手动输入账号密码并登录，然后抓取页面正文并打包为 EPUB。
使用：
  python kadokawa_cookie_epub_manual_login.py
"""

import json
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
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# ========== 在这里配置（只改这些） ==========
START_URL = "https://www.kadokado.com.tw/chapter/480155?titleId=33209&ownerId=6479"  # 起始页面（可改为具体章节页面）
LOGIN_URL = "https://account.kadokado.com.tw/signin"  # 登录页面
COOKIES_JSON = "cookies_kadokado.json"  # 你导出的 cookies 文件路径
OUTPUT_PATH = "已婚高中女老師愛上自己班上女學生的故事2.epub"  # 输出 epub 文件名
MAX_CHAPTERS = 36  # 最多抓取章节数
WAIT_SEC = 30  # 每章完成后等待秒数（你要求的 10s）
TIMEOUT = 60  # 元素等待超时（秒）
ARTICLE_SELECTOR = "article.css-vurnku"  # 抓取正文的 CSS 选择器
NEXT_BTN_SELECTOR = "button.css-16mch31"  # 下一章按钮的 CSS 选择器
# ============================================

# ---------- 小工具 ----------
def safe_filename(name: str) -> str:
    name = re.sub(r"[\\/:*?\"<>|]+", "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name or "chapter"

def escape_html(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def sanitize_html(html: str, base_url: str):
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(["a", "img", "source"]):
        attr = "href" if tag.name == "a" else "src"
        if tag.has_attr(attr):
            tag[attr] = urljoin(base_url, tag[attr])
    for img in soup.find_all("img"):
        for lazy_attr in ["data-src", "data-original", "data-lazy", "data-url"]:
            if img.get(lazy_attr) and not img.get("src"):
                img["src"] = urljoin(base_url, img[lazy_attr])
        for k in list(img.attrs.keys()):
            if k.lower().startswith("on"):
                del img[k]
    for s in soup(["script", "style"]):
        s.decompose()
    image_urls = []
    for img in soup.find_all("img"):
        src = img.get("src")
        if src and src.startswith(("http://", "https://")):
            image_urls.append(src)
    image_urls = list(dict.fromkeys(image_urls))
    return soup, image_urls

def guess_media_type(ext: str) -> str:
    ext = ext.lower()
    return {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".gif": "image/gif",
        ".webp": "image/webp", ".svg": "image/svg+xml"
    }.get(ext, "application/octet-stream")

def download_images(image_urls, book, session, chapter_idx):
    mapping = {}
    for i, url in enumerate(image_urls, start=1):
        try:
            parsed = urlparse(url)
            ext = os.path.splitext(parsed.path)[1].lower() or ".jpg"
            if ext not in [".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"]:
                ext = ".jpg"
            item_id = f"img_{chapter_idx}_{i}"
            epub_path = f"images/{item_id}{ext}"
            headers = {"User-Agent": "Mozilla/5.0"}
            resp = session.get(url, headers=headers, timeout=20)
            resp.raise_for_status()
            img_item = epub.EpubItem(uid=item_id, file_name=epub_path,
                                     media_type=guess_media_type(ext),
                                     content=resp.content)
            book.add_item(img_item)
            mapping[url] = (epub_path, item_id)
        except Exception:
            traceback.print_exc()
    return mapping

def make_chapter_html(title: str, soup: BeautifulSoup, url2epubpath: dict) -> str:
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

# ---------- Selenium driver builder ----------
def build_driver():
    opts = webdriver.ChromeOptions()
    opts.add_argument("--start-maximized")
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-default-browser-check")
    service = Service()
    driver = webdriver.Chrome(service=service, options=opts)
    return driver

# ---------- 手动登录辅助 ----------
def wait_for_user_manual_login(driver):
    """
    引导用户在浏览器中手动完成登录，然后在控制台按回车继续。
    登录完成后，最好能看到页面内的 ARTICLE_SELECTOR（脚本会检查）。
    """
    print("\n====== 请在浏览器中完成手动登录 ======")
    print("操作步骤：")
    print("  1) 在打开的浏览器窗口中输入你的帐号/密码并提交（或使用 Google 登录）。")
    print("  2) 登录完成后，回到此终端并按回车继续脚本（脚本会检查是否已能看到正文）。\n")

    # 打开登录页面，等待用户手动登录
    driver.get(LOGIN_URL)
    time.sleep(1.0)

    # 等待用户完成登录并按回车
    input("登录完成后按回车继续...")

    # 登录后给页面一些时间刷新
    time.sleep(1.0)

# ---------- 抓取主流程 ----------
def main():
    driver = build_driver()
    wait = WebDriverWait(driver, TIMEOUT)
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})

    # 初始化 epub
    book = epub.EpubBook()
    book.set_identifier(f"tw-kadokado-{int(time.time())}")
    book.set_title("Kadokado 抓取合輯")
    book.set_language("zh")
    book.add_author("Auto Spider")

    spine = ["nav"]
    toc = []

    try:
        # 1) 先打开登录页面，让用户手动登录
        print(f"[INFO] 打开登录页面：{LOGIN_URL}")
        driver.get(LOGIN_URL)
        wait_for_user_manual_login(driver)

        # 2) 登录完成后访问章节页面
        print(f"[INFO] 登录完成，访问章节页面：{START_URL}")
        driver.get(START_URL)
        time.sleep(1.0)

        # 3) 等待页面加载正文
        try:
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ARTICLE_SELECTOR)))
            print("[INFO] 已检测到正文节点，开始抓取。")
        except Exception:
            print("[WARN] 未检测到正文，脚本将继续尝试，但可能未登录成功。")

        # 4) 抓取循环
        for idx in range(1, MAX_CHAPTERS + 1):
            try:
                article = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ARTICLE_SELECTOR)))
            except Exception:
                print(f"[WARN] 第 {idx} 章：未找到 {ARTICLE_SELECTOR}，结束抓取。")
                break

            title = safe_filename(driver.title or f"第{idx}章")
            inner_html = article.get_attribute("innerHTML")
            soup, image_urls = sanitize_html(inner_html, driver.current_url)

            url2epubpath = download_images(image_urls, book, session, idx)
            chapter_html = make_chapter_html(title, soup, url2epubpath)

            chap = epub.EpubHtml(title=title, file_name=f"chap_{idx:04d}.xhtml", lang="zh")
            chap.set_content(chapter_html.encode("utf-8"))
            book.add_item(chap)
            spine.append(chap)
            toc.append(chap)
            print(f"[OK] 已保存章节：{title}")

            # 等 WAIT_SEC 秒
            time.sleep(WAIT_SEC)

            # 找下一章按钮并点击
            try:
                next_btn = driver.find_element(By.CSS_SELECTOR, NEXT_BTN_SELECTOR)
            except Exception:
                print("[INFO] 找不到下一章按钮，结束抓取。")
                break

            try:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", next_btn)
                time.sleep(0.2)
                next_btn.click()
            except Exception:
                try:
                    driver.execute_script("arguments[0].click();", next_btn)
                except Exception:
                    print("[WARN] 点击下一章失败，尝试通过 JS 导航或结束抓取。")
                    break

            # 等待内容更新
            try:
                wait.until(EC.staleness_of(article))
            except Exception:
                time.sleep(1.5)

        # 写出 EPUB
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
        try:
            print("浏览器将在 5 秒后关闭（如需保留请 Ctrl+C）。")
            time.sleep(5)
        except KeyboardInterrupt:
            print("已保留浏览器窗口。")
            return
        driver.quit()

if __name__ == "__main__":
    main()
