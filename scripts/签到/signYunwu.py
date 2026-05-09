#!/usr/bin/env python3
"""
云雾AI自动签到脚本 - 青龙面板版
支持多账号、Cookie缓存、滑动验证码识别
"""

import base64
import io
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import requests
from PIL import Image

# 配置
API_BASE = 'https://yunwu.ai'
CACHE_FILE = Path(__file__).parent / '.yunwu_cache.json'
ACCOUNT_FILE = Path(__file__).parent / 'account.txt'

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36'


class SliderDetector:
    """滑动验证码识别器"""

    @staticmethod
    def decode_base64_image(base64_str):
        """解码base64图片为numpy数组"""
        if ',' in base64_str:
            base64_str = base64_str.split(',')[1]
        img_data = base64.b64decode(base64_str)
        pil_image = Image.open(io.BytesIO(img_data))
        return np.array(pil_image)

    @staticmethod
    def match_edge_template(bg_base64, slider_base64, tile_y, tile_height):
        """边缘模板匹配"""
        bg = SliderDetector.decode_base64_image(bg_base64)
        slider = SliderDetector.decode_base64_image(slider_base64)

        # 处理滑块，获取形状边缘
        if len(slider.shape) == 3 and slider.shape[2] == 4:
            alpha = slider[:, :, 3]
            _, mask = cv2.threshold(alpha, 127, 255, cv2.THRESH_BINARY)
            slider_edges = cv2.Canny(mask, 100, 200)
        else:
            slider_gray = cv2.cvtColor(slider, cv2.COLOR_RGB2GRAY) if len(slider.shape) == 3 else slider
            slider_edges = cv2.Canny(slider_gray, 100, 200)

        # 处理背景图
        bg_gray = cv2.cvtColor(bg, cv2.COLOR_RGB2GRAY)

        margin = 20
        y_start = max(0, tile_y - margin)
        y_end = min(bg.shape[0], tile_y + tile_height + margin)
        bg_roi = bg_gray[y_start:y_end, :]

        bg_edges = cv2.Canny(bg_roi, 100, 200)

        result = cv2.matchTemplate(bg_edges, slider_edges, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

        x = max_loc[0]
        y = max_loc[1] + y_start

        return x, y, max_val

    @staticmethod
    def detect(bg_base64, slider_base64, tile_y, tile_height):
        """检测滑块位置"""
        x, y, _ = SliderDetector.match_edge_template(bg_base64, slider_base64, tile_y, tile_height)
        return x, y


class YunwuCheckin:
    """云雾AI签到类"""

    def __init__(self):
        self.session = requests.Session()
        self.headers = {
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'cache-control': 'no-store',
            'origin': API_BASE,
            'referer': f'{API_BASE}/console',
            'sec-ch-ua': '"Not:A-Brand";v="99", "Chromium";v="145"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'user-agent': USER_AGENT,
        }

    def get_login_captcha_token(self, max_retries=3):
        """登录前获取验证码token，失败自动重试"""
        login_headers = {
            **self.headers,
            'new-api-user': '-1',
            'referer': f'{API_BASE}/login',
        }

        for attempt in range(max_retries):
            try:
                # 获取验证码
                resp = self.session.get(
                    f'{API_BASE}/api/go-captcha-data/slide-basic',
                    headers=login_headers,
                    timeout=30
                )
                resp.raise_for_status()
                captcha_data = resp.json()

                if captcha_data.get('code') != 0:
                    print(f'  获取登录验证码失败: {captcha_data.get("message", "未知错误")}')
                    continue

                bg_base64, slider_base64, captcha_key = self.parse_captcha_response(captcha_data)
                if not all([bg_base64, slider_base64, captcha_key]):
                    print('  登录验证码数据解析失败')
                    continue

                tile_y = captcha_data.get('tile_y', 0)
                tile_height = captcha_data.get('tile_height', 50)

                # 识别滑块位置
                x, y = SliderDetector.detect(bg_base64, slider_base64, tile_y, tile_height)

                # 提交验证
                verify_headers = {k: v for k, v in login_headers.items() if k.lower() != 'content-type'}
                files = {
                    'point': (None, f'{x},{y}'),
                    'key': (None, captcha_key),
                }
                resp = self.session.post(
                    f'{API_BASE}/api/go-captcha-check-data/slide-basic',
                    headers=verify_headers,
                    files=files,
                    timeout=30
                )
                resp.raise_for_status()
                verify_result = resp.json()

                if verify_result.get('code') == 0 and verify_result.get('token'):
                    return verify_result['token']

                print(f'  登录验证码验证失败 (第{attempt + 1}次)')

            except Exception as e:
                print(f'  登录验证码处理异常 (第{attempt + 1}次): {e}')

            if attempt < max_retries - 1:
                time.sleep(1)

        return None

    def login(self, username, password):
        """登录获取session"""
        # 先完成登录验证码
        captcha_token = self.get_login_captcha_token()
        if not captcha_token:
            return {'success': False, 'message': '登录验证码获取失败'}

        url = f'{API_BASE}/api/user/login?turnstile='
        headers = {
            **self.headers,
            'content-type': 'application/json',
            'origin': API_BASE,
            'referer': f'{API_BASE}/login',
        }

        try:
            resp = self.session.post(
                url,
                json={'username': username, 'password': password, 'captcha_token': captcha_token},
                headers=headers,
                timeout=30
            )
            data = resp.json()

            if data.get('success'):
                # 提取session cookie
                session_cookie = None
                for cookie in self.session.cookies:
                    if cookie.name == 'session':
                        session_cookie = cookie.value
                        break

                user_data = data.get('data', {})
                return {
                    'success': True,
                    'session': session_cookie,
                    'user_id': user_data.get('id'),
                    'username': user_data.get('username', username)
                }

            return {'success': False, 'message': data.get('message', '登录失败')}

        except Exception as e:
            return {'success': False, 'message': str(e)}

    def get_headers_with_cookie(self, cookie_str, user_id):
        """获取带cookie的headers"""
        return {
            **self.headers,
            'cookie': cookie_str,
            'new-api-user': str(user_id),
            'referer': f'{API_BASE}/console/personal',
        }

    def test_cookie_valid(self, cookie_str, user_id):
        """测试cookie是否有效"""
        current_month = datetime.now().strftime('%Y-%m')
        url = f'{API_BASE}/api/user/checkin?month={current_month}'
        headers = self.get_headers_with_cookie(cookie_str, user_id)

        try:
            resp = self.session.get(url, headers=headers, timeout=10)
            return resp.json().get('success') == True
        except:
            return False

    def get_captcha_data(self, cookie_str, user_id):
        """获取滑动验证码数据"""
        url = f'{API_BASE}/api/go-captcha-data/slide-basic'
        headers = self.get_headers_with_cookie(cookie_str, user_id)

        resp = self.session.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def verify_captcha(self, point_x, point_y, captcha_key, cookie_str, user_id):
        """提交验证码验证"""
        url = f'{API_BASE}/api/go-captcha-check-data/slide-basic'
        headers = {k: v for k, v in self.get_headers_with_cookie(cookie_str, user_id).items()
                   if k.lower() != 'content-type'}

        files = {
            'point': (None, f'{point_x},{point_y}'),
            'key': (None, captcha_key),
        }

        resp = self.session.post(url, headers=headers, files=files, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def do_checkin(self, captcha_token, cookie_str, user_id):
        """执行签到"""
        url = f'{API_BASE}/api/user/checkin?captcha_token={captcha_token}'
        headers = self.get_headers_with_cookie(cookie_str, user_id)

        resp = self.session.post(url, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def get_checkin_status(self, cookie_str, user_id):
        """获取签到状态"""
        current_month = datetime.now().strftime('%Y-%m')
        url = f'{API_BASE}/api/user/checkin?month={current_month}'
        headers = self.get_headers_with_cookie(cookie_str, user_id)

        try:
            resp = self.session.get(url, headers=headers, timeout=10)
            return resp.json()
        except:
            return None

    def parse_captcha_response(self, captcha_data):
        """解析验证码响应"""
        bg = None
        slider = None
        key = None

        bg_keys = ['image_base64', 'image', 'bg', 'background', 'master', 'pic']
        for k in bg_keys:
            if k in captcha_data and captcha_data[k]:
                bg = captcha_data[k]
                break

        slider_keys = ['thumb_base64', 'thumb', 'slider', 'block', 'template', 'cut']
        for k in slider_keys:
            if k in captcha_data and captcha_data[k]:
                slider = captcha_data[k]
                break

        key_keys = ['captcha_key', 'key', 'id', 'token']
        for k in key_keys:
            if k in captcha_data and captcha_data[k]:
                key = captcha_data[k]
                break

        return bg, slider, key

    def _do_single_checkin(self, cookie_str, user_id):
        """执行单次签到尝试（不含重试逻辑）"""
        # 获取验证码
        captcha_data = self.get_captcha_data(cookie_str, user_id)
        bg_base64, slider_base64, captcha_key = self.parse_captcha_response(captcha_data)

        if not all([bg_base64, slider_base64, captcha_key]):
            return {'success': False, 'message': '无法解析验证码数据', 'can_retry': False}

        tile_y = captcha_data.get('tile_y', 0)
        tile_height = captcha_data.get('tile_height', 50)

        # 识别滑块位置
        try:
            x, y = SliderDetector.detect(bg_base64, slider_base64, tile_y, tile_height)
        except Exception as e:
            return {'success': False, 'message': f'验证码识别失败: {e}', 'can_retry': True}

        # 提交验证
        verify_result = self.verify_captcha(x, y, captcha_key, cookie_str, user_id)
        if verify_result.get('code') != 0:
            return {'success': False, 'message': f'验证码验证失败', 'can_retry': True}

        captcha_token = verify_result.get('token')
        if not captcha_token:
            return {'success': False, 'message': '未获取到验证token', 'can_retry': True}

        # 执行签到
        checkin_result = self.do_checkin(captcha_token, cookie_str, user_id)

        if checkin_result.get('success'):
            data = checkin_result.get('data', {})
            quota_awarded = data.get('quota_awarded', 0) / 10000000
            return {
                'success': True,
                'already': False,
                'message': '签到成功',
                'checkin_date': data.get('checkin_date', ''),
                'quota_awarded': f'{quota_awarded:.1f}000万',
                'can_retry': False
            }
        else:
            msg = checkin_result.get('message', '未知错误')
            if msg == '今日已签到':
                return {'success': True, 'already': True, 'message': msg, 'can_retry': False}
            return {'success': False, 'message': msg, 'can_retry': True}

    def run_checkin(self, cookie_str, user_id, remark, max_retries=2):
        """执行完整的签到流程，失败后自动重试"""
        # 先检查是否已签到
        status_data = self.get_checkin_status(cookie_str, user_id)
        if status_data and status_data.get('data', {}).get('stats', {}).get('checked_in_today'):
            stats = status_data['data']['stats']
            total_quota = stats.get('total_quota', 0) / 10000000
            return {
                'success': True,
                'already': True,
                'message': '今日已签到',
                'total_checkins': stats.get('total_checkins', 0),
                'total_quota': f'{total_quota:.1f}000万'
            }

        # 尝试签到，失败后重试
        last_result = None
        for attempt in range(max_retries + 1):
            if attempt > 0:
                print(f'  第 {attempt + 1} 次重试...')
                time.sleep(1)  # 重试前等待1秒

            last_result = self._do_single_checkin(cookie_str, user_id)

            if last_result['success']:
                return last_result

            # 如果不可重试，直接返回
            if not last_result.get('can_retry', True):
                return last_result

            if attempt < max_retries:
                print(f'  签到失败: {last_result["message"]}，准备重试...')

        return last_result


def load_cache():
    """加载缓存"""
    try:
        if CACHE_FILE.exists():
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f'缓存读取失败: {e}')
    return {}


def save_cache(cache):
    """保存缓存"""
    try:
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f'缓存保存失败: {e}')


def get_accounts():
    """获取账号列表"""
    accounts = []

    # 优先从青龙环境变量获取
    env_value = os.environ.get('YUNWU_ACCOUNT', '')
    if env_value:
        lines = env_value.replace('&', '\n').split('\n')
        for line in lines:
            line = line.strip()
            if line:
                parts = line.split('###')
                username = parts[0].strip()
                password = parts[1].strip() if len(parts) > 1 else ''
                remark = parts[2].strip() if len(parts) > 2 else username
                if username and password:
                    accounts.append({'username': username, 'password': password, 'remark': remark})

    # 如果环境变量没有，从文件读取
    if not accounts and ACCOUNT_FILE.exists():
        with open(ACCOUNT_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    # 支持空格分隔和###分隔
                    if '###' in line:
                        parts = line.split('###')
                        username = parts[0].strip()
                        password = parts[1].strip() if len(parts) > 1 else ''
                        remark = parts[2].strip() if len(parts) > 2 else username
                    else:
                        parts = line.split()
                        if len(parts) >= 2:
                            username = parts[0].strip()
                            password = parts[1].strip()
                            remark = username
                        else:
                            continue

                    if username and password:
                        accounts.append({'username': username, 'password': password, 'remark': remark})

    return accounts


def get_valid_cookie(checker, account, cache):
    """获取有效的cookie"""
    cache_key = account['username']
    cached = cache.get(cache_key, {})

    if cached.get('session') and cached.get('user_id'):
        cookie_str = f"session={cached['session']}; new-api-user={cached['user_id']}"
        if checker.test_cookie_valid(cookie_str, cached['user_id']):
            print(f"使用缓存的Cookie: {account['remark']}")
            return {'cookie': cookie_str, 'user_id': cached['user_id'], 'from_cache': True}
        print(f"Cookie已失效，重新登录: {account['remark']}")

    print(f"登录获取Cookie: {account['remark']}")
    login_result = checker.login(account['username'], account['password'])

    if not login_result['success']:
        return {'error': login_result['message']}

    cache[cache_key] = {
        'session': login_result['session'],
        'user_id': login_result['user_id'],
        'username': login_result['username'],
        'updated_at': datetime.now().isoformat()
    }
    save_cache(cache)

    cookie_str = f"session={login_result['session']}; new-api-user={login_result['user_id']}"
    return {'cookie': cookie_str, 'user_id': login_result['user_id'], 'from_cache': False}


def send_push_plus(title, content):
    """发送PushPlus推送"""
    token = os.environ.get('PUSH_PLUS_TOKEN') or os.environ.get('PUSHPLUS_TOKEN')
    if not token:
        print('未配置 PushPlus Token，跳过推送')
        return

    try:
        resp = requests.post(
            'https://www.pushplus.plus/send',
            json={
                'token': token,
                'title': title,
                'content': content,
                'template': 'txt'
            },
            timeout=10
        )
        data = resp.json()
        if data.get('code') == 200:
            print('PushPlus 推送成功')
        else:
            print(f'PushPlus 推送失败: {data.get("msg")}')
    except Exception as e:
        print(f'PushPlus 推送错误: {e}')


def main():
    print('========== 云雾AI签到脚本开始 ==========\n')

    accounts = get_accounts()

    if not accounts:
        print('没有找到有效的账号')
        print('请设置环境变量 YUNWU_ACCOUNT 或在 account.txt 中配置账号')
        print('格式: 用户名###密码###备注 或 用户名 密码')
        send_push_plus('云雾AI签到-失败', '未找到有效的账号配置')
        return

    print(f'检测到 {len(accounts)} 个账号\n')

    cache = load_cache()
    checker = YunwuCheckin()

    success_count = 0
    already_count = 0
    fail_count = 0
    details = []

    for i, account in enumerate(accounts):
        print(f'--- 账号 {i + 1}: {account["remark"]} ---')

        auth = get_valid_cookie(checker, account, cache)
        if 'error' in auth:
            print(f'登录失败: {auth["error"]}\n')
            details.append(f'【{account["remark"]}】登录失败\n原因: {auth["error"]}')
            fail_count += 1
            continue

        if auth['from_cache']:
            print('使用缓存Cookie')
        else:
            print('登录成功，已缓存Cookie')

        result = checker.run_checkin(auth['cookie'], auth['user_id'], account['remark'])

        if result['success']:
            if result['already']:
                print(f"今日已签到")
                if 'total_checkins' in result:
                    print(f"累计签到: {result['total_checkins']} 次")
                    print(f"总配额: {result['total_quota']}\n")
                    details.append(f'【{account["remark"]}】今日已签到\n累计签到: {result["total_checkins"]} 次\n总配额: {result["total_quota"]}')
                else:
                    print()
                    details.append(f'【{account["remark"]}】今日已签到')
                already_count += 1
            else:
                print(f"签到成功!")
                print(f"签到日期: {result.get('checkin_date', 'N/A')}")
                print(f"获得配额: {result.get('quota_awarded', 'N/A')}\n")
                details.append(f'【{account["remark"]}】签到成功\n签到日期: {result.get("checkin_date", "N/A")}\n获得配额: {result.get("quota_awarded", "N/A")}')
                success_count += 1
        else:
            print(f"签到失败: {result['message']}\n")
            details.append(f'【{account["remark"]}】签到失败\n原因: {result["message"]}')
            fail_count += 1

    print('========== 签到完成 ==========')
    print(f'成功: {success_count}, 已签到: {already_count}, 失败: {fail_count}')

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    total = len(accounts)
    status_emoji = '❌' if fail_count > 0 else ('✅' if success_count > 0 else '✓')
    title = f'{status_emoji} 云雾AI签到 {success_count}成功 {already_count}已签 {fail_count}失败'

    content = f'''执行时间: {now}
统计: 共{total}个账号 | 成功{success_count} | 已签{already_count} | 失败{fail_count}

{chr(10).join(details)}'''

    send_push_plus(title, content)


if __name__ == '__main__':
    main()
