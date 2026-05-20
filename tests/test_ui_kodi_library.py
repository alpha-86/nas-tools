"""
Kodi 媒体库 UI 端到端测试（无头浏览器）
验证首页库卡片、媒体服务器设置、同步状态正确展示。

运行: pytest tests/test_ui_kodi_library.py -s
需要: selenium + Chrome/Chromium
"""
import pytest
import time


@pytest.fixture
def driver():
    """创建无头 Chrome WebDriver"""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    opts = Options()
    opts.add_argument('--headless')
    opts.add_argument('--no-sandbox')
    opts.add_argument('--disable-dev-shm-usage')
    opts.add_argument('--disable-gpu')
    opts.binary_location = '/usr/bin/google-chrome'

    d = webdriver.Chrome(options=opts)
    d.set_page_load_timeout(30)
    yield d
    d.quit()


@pytest.fixture
def logged_in_driver(driver):
    """登录后的 WebDriver"""
    from selenium.webdriver.common.by import By

    driver.get('http://192.168.1.103:8097')
    time.sleep(2)
    driver.find_element(By.CSS_SELECTOR, 'input[name="username"]').send_keys('admin')
    driver.find_element(By.CSS_SELECTOR, 'input[name="password"]').send_keys('abcd')
    driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]').click()
    time.sleep(3)
    return driver


class TestKodiLibraryUI:
    """Kodi MySQL 媒体库 UI 测试"""

    def test_login_success(self, logged_in_driver):
        """验证登录后跳转到首页"""
        assert '/web#index' in logged_in_driver.current_url
        assert 'NAStool' in logged_in_driver.title

    def test_library_cards_non_clickable(self, logged_in_driver):
        """验证 Kodi 库卡片不可点击（没有外链）"""
        from selenium.webdriver.common.by import By

        cards = logged_in_driver.find_elements(By.CSS_SELECTOR, '.library-movies, .library-tvshows')
        assert len(cards) == 2, f"期望 2 个库卡片，实际 {len(cards)}"

        for card in cards:
            tag = card.tag_name
            text = card.text.strip()
            assert tag == 'div', f"Kodi 库卡片应为不可点击的 div，实际是 {tag}: {text}"
            assert text in ('电影', '剧集'), f"未知库名称: {text}"

    def test_library_cards_names(self, logged_in_driver):
        """验证库卡片名称为电影和剧集"""
        from selenium.webdriver.common.by import By

        cards = logged_in_driver.find_elements(By.CSS_SELECTOR, '.library-movies, .library-tvshows')
        names = {c.text.strip() for c in cards}
        assert names == {'电影', '剧集'}

    def test_mediaserver_setting_shows_kodi(self, logged_in_driver):
        """验证媒体服务器设置页显示 Kodi"""
        from selenium.webdriver.common.by import By

        logged_in_driver.get('http://192.168.1.103:8097/web#mediaserver')
        time.sleep(3)

        body = logged_in_driver.find_element(By.TAG_NAME, 'body').text
        assert 'Kodi' in body or 'kodi' in body.lower(), "媒体服务器设置页未显示 Kodi"

    def test_no_broken_library_links(self, logged_in_driver):
        """验证没有 href="" 的损坏链接（点击会刷新页面）"""
        from selenium.webdriver.common.by import By

        # 查找所有 class 包含 library 的 a 标签
        links = logged_in_driver.find_elements(By.CSS_SELECTOR, 'a[class*="library"]')
        for link in links:
            href = link.get_attribute('href') or ''
            # a 标签不应有空的 href（或只有 # 的 href）
            assert href and href != '', f"发现损坏的库链接: class={link.get_attribute('class')}"
