import argparse
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    SessionNotCreatedException,
    StaleElementReferenceException,
    TimeoutException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

def resolve_driver_path(use_chromium: bool) -> str:
    if use_chromium:
        for p in (
            "/usr/bin/chromedriver",
            "/usr/lib/chromium/chromedriver",
            "/usr/lib/chromium-browser/chromedriver",
        ):
            if Path(p).is_file():
                return p
        w = shutil.which("chromedriver")
        if w and Path(w).is_file():
            return w
        from webdriver_manager.chrome import ChromeDriverManager
        from webdriver_manager.core.os_manager import ChromeType

        return ChromeDriverManager(chrome_type=ChromeType.CHROMIUM).install()

    env = os.environ.get("CHROMEDRIVER_PATH", "").strip()
    if env and Path(env).is_file():
        return env
    for p in ("/opt/homebrew/bin/chromedriver", "/usr/local/bin/chromedriver"):
        if Path(p).is_file():
            return p
    w = shutil.which("chromedriver")
    if w and Path(w).is_file():
        return w
    from webdriver_manager.chrome import ChromeDriverManager

    return ChromeDriverManager().install()


def start_chrome_driver(opts: Options, use_chromium: bool) -> webdriver.Chrome:
    """Запуск Chrome. Если версия не совпадает с браузером, то используется webdriver-manager"""
    driver_path = resolve_driver_path(use_chromium)
    print("chromedriver:", driver_path)
    try:
        return webdriver.Chrome(service=Service(driver_path), options=opts)
    except SessionNotCreatedException:
        if use_chromium:
            raise
        if os.environ.get("CHROMEDRIVER_PATH", "").strip():
            raise
        from webdriver_manager.chrome import ChromeDriverManager

        alt = ChromeDriverManager().install()
        print(
            "Версия chromedriver не совпала с браузером, ипользуем webdriver-manager",
            alt,
            file=sys.stderr,
        )
        return webdriver.Chrome(service=Service(alt), options=opts)


def main() -> int:
    parser = argparse.ArgumentParser(description="Скачать CSV с Sezam")
    parser.add_argument("--login", default="", help="логин")
    parser.add_argument("--password", default="", help="пароль")
    args = parser.parse_args()

    login = (args.login or os.environ.get("SEZAM_USER", "")).strip()
    password = args.password or os.environ.get("SEZAM_PASSWORD", "")
    if not login or not password:
        print(
            "Укажите логин и пароль -переменные SEZAM_USER и SEZAM_PASSWORD ",
            file=sys.stderr,
        )
        return 1

    script_dir = Path(__file__).resolve().parent
    download_dir = script_dir / "data"
    download_dir.mkdir(parents=True, exist_ok=True)

    opts = Options()
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--remote-allow-origins=*")
    opts.add_argument("--window-size=1280,900")
    opts.add_experimental_option(
        "prefs",
        {
            "download.default_directory": str(download_dir),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
        },
    )

    use_chromium = Path(
        "/usr/bin/chromium-browser"
    ).is_file()

    if platform.system() == "Darwin":
        chrome_mac = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        if chrome_mac.is_file():
            opts.binary_location = str(chrome_mac)
            use_chromium = False

    if use_chromium:
        if Path("/usr/bin/chromium").is_file():
            opts.binary_location = "/usr/bin/chromium"
        elif Path("/usr/bin/chromium-browser").is_file():
            opts.binary_location = "/usr/bin/chromium-browser"

    driver = start_chrome_driver(opts, use_chromium)
    wait = WebDriverWait(driver, 20)

    try:
        driver.get("https://sezam.hse.ru/")
        time.sleep(2)

        if "Авторизация" in driver.title:
            wait.until(EC.visibility_of_element_located((By.ID, "username"))).send_keys(login)
            wait.until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, "input[name='password']"))
            ).send_keys(password)
            try:
                wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button[type='submit']"))).click()
            except TimeoutException:
                wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "input[type='submit']"))).click()
            WebDriverWait(driver, 30).until(lambda d: "Авторизация" not in d.title)
            time.sleep(2)

        title = "Chicago Liquidity Data Bank"
        xpath_card = (
            "//div[contains(@class,'_root_16za9_1')]"
            f"[.//div[contains(@class,'_name_16za9_37') and contains(normalize-space(.), {title!r})]]"
        )
        css_files = "div._files-container_sxqn7_33"
        xpath_csv = (
            "//div[contains(@class,'_files-container_sxqn7_33')]"
            "//div[contains(@class,'_file_sxqn7_33')]"
            "[.//div[contains(normalize-space(.), '.csv')]]"
            "//div[contains(@class,'_download_sxqn7_70')]"
        )

        try:
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, css_files)))
        except TimeoutException:
            card = wait.until(EC.presence_of_element_located((By.XPATH, xpath_card)))
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", card)
            time.sleep(0.5)
            for _ in range(4):
                try:
                    card = wait.until(EC.element_to_be_clickable((By.XPATH, xpath_card)))
                    try:
                        ActionChains(driver).move_to_element(card).pause(0.1).click(card).perform()
                    except ElementClickInterceptedException:
                        driver.execute_script("arguments[0].click();", card)
                    break
                except StaleElementReferenceException:
                    time.sleep(0.3)
            driver.execute_script("arguments[0].click();", card)
            time.sleep(2)

        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, css_files)))

        buttons = driver.find_elements(By.XPATH, xpath_csv)
        if not buttons:
            raise RuntimeError("Нет CSV")

        for btn in buttons:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
            time.sleep(0.1)
            ActionChains(driver).move_to_element(btn).pause(0.05).click(btn).perform()
            time.sleep(0.2)

        for _ in range(600):
            if not list(download_dir.glob("*.crdownload")):
                break
            time.sleep(0.5)

        print("Готово:", download_dir)
        return 0
    finally:
        driver.quit()


if __name__ == "__main__":
    raise SystemExit(main())
