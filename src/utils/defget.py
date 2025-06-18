from playwright.async_api import async_playwright
import aiohttp
from typing import Optional
from datetime import datetime, timedelta
from cacheout import Cache
import aiofiles
import time
import os
import glob
import json
import asyncio
from config import IMAGE_CACHE_DIR,SESSION_data,texts


# 全局变量
SERVER_DATA_FILE = "server_data.json"  # 文件路径
server_data_cache = None  # 缓存
cache = Cache(maxsize=256, ttl=SESSION_data, timer=time.time, default=None)
def jjcdaxiaoxie(timestamp):
    if timestamp == 0:
        return "零"
    if timestamp == 1:
        return "一"
    if timestamp == 2:
        return "二"
    if timestamp == 3:
        return "三"
    if timestamp == 4:
        return "四"
    if timestamp == 5:
        return "五"
    if timestamp == 6:
        return "六"
    if timestamp == 7:
        return "七"
    if timestamp == 8:
        return "八"
    if timestamp == 9:
        return "九"
    if timestamp == 10:
        return "十"
    if timestamp == 11:
        return "十一"
    if timestamp == 12:
        return "十二"
    if timestamp == 13:
        return "十三"
    if timestamp == 14:
        return "十四"
    if timestamp == 15:
        return "十五"
def convert_number(amount):
    thousands = amount // 100000000
    thousands = "" if thousands == 0 else f" {thousands}<img src='http://192.168.100.1:5244/img/qiyu/img/zhuan.png' alt='砖'>"
    remainder = (amount % 100000000) // 10000
    remainder = "" if remainder == 0 else f" {remainder}<img src='http://192.168.100.1:5244/img/qiyu/img/jin.png' alt='金'>"
    billions = (amount % 10000) // 100
    billions = "" if billions == 0 else f" {billions}<img src='http://192.168.100.1:5244/img/qiyu/img/yin.png' alt='银'>"
    return f"{thousands}{remainder}{billions}"
def suijitext():

    # 获取当前时间戳的毫秒部分
    microseconds = int(time.time() * 1000000) % len(texts)


    # 使用毫秒部分作为索引来选择列表中的一个元素
    selected_text = texts[microseconds]
    return selected_text
def timestamp_jjc(timestamp, format="%Y-%m-%d %H:%M:%S"):
    dt_object = datetime.fromtimestamp(timestamp)
    return dt_object.strftime(format)


def time_ago_fenzhong(timestamp):
    if timestamp == 0:
        return "被遗忘的时间"

    now = datetime.now()
    then = datetime.fromtimestamp(timestamp)

    # 计算总时间差（单位：秒）
    total_seconds = int((now - then).total_seconds())

    # 处理未来时间
    if total_seconds < 0:
        return "未来时间"

    # 如果差异小于60秒
    if total_seconds < 60:
        return "刚刚"

    # 计算天、小时、分钟
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60

    # 格式化相对时间字符串
    relative_time = []
    if days > 0:
        relative_time.append(f"{days}天")
    if hours > 0:
        relative_time.append(f"{hours:02d}小时")
    if minutes > 0:
        relative_time.append(f"{minutes:02d}分钟")

    # 连接字符串并返回结果
    return "".join(relative_time) + "前"
def time_ago_filter(timestamp):
    now = datetime.now()
    then = datetime.fromtimestamp(timestamp)
    time_difference = now - then
    # 提取年、月、日、小时等时间差信息（简化计算）
    years = time_difference.days // 365
    months = (time_difference.days % 365) // 30
    days = time_difference.days % 30
    hours = time_difference.seconds // 3600
    # 格式化相对时间字符串
    relative_time = []
    if years > 0:
        relative_time.append(f"{years}年")
    if months > 0:
        relative_time.append(f"{months}月")
    if days > 0:
        relative_time.append(f"{days}天")
    if hours > 0:
        relative_time.append(f"{hours}小时")
    return "".join(relative_time) + "前"
def sum_specified_keys(data, keys_to_sum, keys_to_sum2):
    """
    遍历数据结构，对两组指定键的'total'和'speed'进行累加。

    :param data: 要遍历的数据结构（字典或列表）
    :param keys_to_sum: 第一个包含需要累加的键名的列表
    :param keys_to_sum2: 第二个包含需要累加的键名的列表
    :return: 一个包含四个累加结果的元组，顺序为(keys_to_sum中键的total累加和, keys_to_sum中键的speed累加和, keys_to_sum2中键的total累加和, keys_to_sum2中键的speed累加和)
    """
    # 初始化累加结果
    total_sum1 = 0
    speed_sum1 = 0
    total_sum2 = 0
    speed_sum2 = 0

    def recurse(data):
        nonlocal total_sum1, speed_sum1, total_sum2, speed_sum2

        if isinstance(data, dict):
            for key, value in data.items():
                if key in keys_to_sum and isinstance(value, dict):
                    if 'total' in value and isinstance(value['total'], (int, float)):
                        total_sum1 += value['total']
                    if 'speed' in value and isinstance(value['speed'], (int, float)):
                        speed_sum1 += value['speed']
                elif key in keys_to_sum2 and isinstance(value, dict):
                    if 'total' in value and isinstance(value['total'], (int, float)):
                        total_sum2 += value['total']
                    if 'speed' in value and isinstance(value['speed'], (int, float)):
                        speed_sum2 += value['speed']
                recurse(value)
        elif isinstance(data, list):
            for item in data:
                recurse(item)

    # 开始递归处理
    recurse(data)

    # 返回累加结果
    return speed_sum1,total_sum1, speed_sum2,total_sum2
# get请求函数

async def get(url: str, server: Optional[str] = None, name: Optional[str] = None,
              token: Optional[str] = None, ticket: Optional[str] = None, zili: Optional[str] = None) -> dict:
    """
    异步GET请求方法

    Args:
        url: 请求URL（必填）
        server: 服务器名称（可选）
        name: 角色名称（可选）
        token: 认证令牌（可选）
        ticket: 票据（可选）
        zili: 资历分布（可选）

    Returns:
        dict: 响应数据
    """
    if name is not None:
        name = name.replace('[', '').replace(']', '').replace('&#91;', '').replace('&#93;', '').replace(" ", "")

    params = {}
    if server:
        params['server'] = server
    if name:
         params['name'] = name
    if token:
        params['token'] = token
    if ticket:
        params['ticket'] = ticket
    if zili:
        params['class'] = zili
    if name is not None:
        if 'name' in params:
            params['name'] = name





    cache_data = cache.get(f'{url}{server}{name}')
    if cache_data:
        print("从缓存中获取数据")
        data=cache_data

    else:
        print("获取NEW数据")

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as response:

                data = await response.json()

                cache.set(f'{url}{server}{name}', data)

    return data


# 检查并获取最新的名片图片
async def get_image(server, role_name,free=None):
    """
    检查mpimg目录下是否有指定服务器和角色名的图片，如果有则返回最新的一张（不带目录的路径）

    参数:
    server: 服务器名，如"梦江南"
    role_name: 角色名，如"冽弦"

    返回:
    如果找到图片，返回最新图片的文件名（不带目录）；如果没有找到，返回None
    """
    try:
        # 确保目录存在
        if not os.path.exists(IMAGE_CACHE_DIR):
            os.makedirs(IMAGE_CACHE_DIR, exist_ok=True)
            return None

        # 构建搜索模式
        search_pattern = f"{IMAGE_CACHE_DIR}/{server}-{role_name}-*.png"

        # 获取所有匹配的文件
        matching_files = glob.glob(search_pattern)

        # 如果没有匹配的文件，返回None
        if not matching_files:
            return None

        # 过滤掉不存在或无法访问的文件
        valid_files = [f for f in matching_files if os.path.isfile(f) and os.access(f, os.R_OK)]

        if not valid_files:
            return None

        # 按文件修改时间排序，获取最新的文件
        latest_file = max(valid_files, key=os.path.getmtime)

        # 检查文件大小是否为0

        if os.path.getsize(latest_file) == 0:
            return None


        if free=="1":
            valid_files = [f for f in matching_files if os.path.isfile(f) and os.access(f, os.R_OK) and os.path.getsize(f) > 0]
            return valid_files
        # 返回最新文件的文件名（不带目录）
        return os.path.basename(latest_file)
    except Exception as e:
        print(f"获取名片图片时出错: {str(e)}")
        return None
#交易行get
async def jiaoyiget(url):


    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            data = await response.json()



    return data

#名片get
async def mp_image(url, name):
    headers = {
        'User-Agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
    }

    file_path = f'{IMAGE_CACHE_DIR}/{name}.png'
    # 检查文件是否存在
    if os.path.exists(file_path):
        print("名片已存在，直接跳过发送")
        return None

        # # 异步读取本地文件
        # async with aiofiles.open(file_path, 'rb') as f:
        #     image_content = await f.read()
        # return image_content

    # 如果文件不存在，则下载图片

    file_path = os.path.join(IMAGE_CACHE_DIR, f"{name}.png")
    async with aiohttp.ClientSession(headers=headers) as session:
        if url:
            async with session.get(url) as image_response:
                if image_response.status == 200:
                    image_content = await image_response.read()

                    # 将图片保存到本地文件
                    async with aiofiles.open(file_path, 'wb') as f:
                        await f.write(image_content)
                    print("图片已下载并保存")

                    # 返回图片的二进制内容
                    return image_content
                else:
                    print(f"无法下载图片，状态码：{image_response.status}")
                    return None  # 或者你可以抛出一个异常
        else:
            print("未找到图片URL")
            return None  # 或者你可以抛出一个异常



async def jietu(html_content, width, height):
    # 使用async_playwright来异步地启动Playwright
    async with async_playwright() as p:
        # 启动Chromium浏览器
        browser = await p.chromium.launch(headless=True)  # headless=True表示在无头模式下运行，不会显示浏览器界面
        page = await browser.new_page(
            viewport={"width": 1920, "height": 1080},  # 更高分辨率
            device_scale_factor=1,  # 关键参数：设置DPR为2.0实现高清效果
        )

        # 再用JavaScript确认所有图片已加载
        await page.evaluate('''() => {
                 return new Promise((resolve) => {
                     const images = document.querySelectorAll('img');
                     if (images.length === 0) return resolve(true);

                     let loaded = 0;
                     const checkLoaded = () => {
                         loaded++;
                         if (loaded === images.length) resolve(true);
                     };

                     images.forEach(img => {
                         if (img.complete) checkLoaded();
                         else {
                             img.addEventListener('load', checkLoaded);
                             img.addEventListener('error', checkLoaded);
                         }
                     });
                 });
             }''')

        # 设置页面的内容为传入的HTML内容
        await page.set_content(html_content)
        # 设置视口大小（可选）
        page_height = await page.evaluate('() => document.body.scrollHeight')
        if height=="ck":
            height=page_height
        await page.set_viewport_size({"width": width, "height": height})
        # 截取截图，并指定截图区域（可选，这里截取整个页面）
        # 如果需要截取特定区域，可以传递clip参数，例如：clip={"x": 0, "y": 0, "width": 800, "height": 600}
        # screenshot没有指定路径返回二进制
        screenshot_path = await page.screenshot(full_page=True)
        # 关闭浏览器
        await browser.close()
        # 返回截图路径（或者可以选择返回截图内容的二进制数据）
        return screenshot_path


async def jx3web(url, selector, adjust_top=None, save_path=None):
    """
    截取网页中特定元素的函数，并在底部添加签名，可以保存到本地

    参数:
        url: 要截取的网页URL
        selector: 要截取的元素的CSS选择器
        adjust_top: 可选，调整元素的top值
        save_path: 可选，保存截图的路径，如果为None则只返回二进制数据

    返回:
        如果save_path为None，返回截图的二进制数据
        如果save_path不为None，返回保存的文件路径
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # 访问URL
        await page.goto(url, wait_until="networkidle")

        # 等待选择器出现
        await page.wait_for_selector(selector)

        # 调整元素位置（如果需要）
        if adjust_top is not None:
            await page.evaluate("""(arg) => {
                const element = document.querySelector(arg.selector);
                if (element) {
                    const currentPosition = window.getComputedStyle(element).position;
                    if (currentPosition === 'static') {
                        element.style.position = 'relative';
                    }
                    element.style.top = arg.topValue;
                }
            }""", {"selector": selector, "topValue": adjust_top})
            await page.wait_for_timeout(300)

        # 添加底部签名和创建包装元素
        await page.evaluate("""(arg) => {
            const element = document.querySelector(arg.selector);
            if (!element) return;
            
            const wrapper = document.createElement('div');
            wrapper.id = 'capture-wrapper';
            wrapper.style.width = element.offsetWidth + 'px';
            
            element.parentNode.insertBefore(wrapper, element);
            wrapper.appendChild(element);
            
            const footer = document.createElement('div');
            footer.style.width = '100%';
            footer.style.padding = '15px';
            footer.style.marginTop = '10px';
            footer.style.background = '#f8f9fa';
            footer.style.borderTop = '1px solid #eaeaea';
            footer.style.fontFamily = "'Microsoft YaHei', sans-serif";
            footer.style.fontSize = '14px';
            footer.style.color = '#555';
            footer.style.textAlign = 'center';
            
            const line1 = document.createElement('div');
            line1.textContent = '【夏鸥】bot:';
            line1.style.fontWeight = 'bold';
            line1.style.marginBottom = '5px';
            footer.appendChild(line1);
            
            const line2 = document.createElement('div');
            line2.textContent = '人间最美，不过鲸落，一念百草生，一念山河成。';
            line2.style.fontStyle = 'italic';
            footer.appendChild(line2);
            
            wrapper.appendChild(footer);
        }""", {"selector": selector})

        await page.wait_for_timeout(200)

        # 截取包装容器
        wrapper = await page.wait_for_selector('#capture-wrapper')
        screenshot = await wrapper.screenshot()

        await browser.close()

        # 如果指定了保存路径，保存文件
        if save_path:
            # 确保目录存在
            os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)

            # 写入文件
            with open(save_path, "wb") as f:
                f.write(screenshot)

            return save_path
        else:
            return screenshot

async def idget(server_name):
    """
    检查服务器名称是否存在于服务器数据中

    参数:
        server_name: 要检查的服务器名称

    返回:
        bool: 服务器是否存在
    """
    global server_data_cache, SERVER_DATA_FILE

    # 如果缓存为空，从文件加载数据
    if server_data_cache is None:
        try:
            if os.path.exists(SERVER_DATA_FILE):
                with open(SERVER_DATA_FILE, 'r', encoding='utf-8') as f:
                    server_data_cache = json.load(f)
                print(f"已从{SERVER_DATA_FILE}加载服务器数据")
            else:
                print(f"错误：{SERVER_DATA_FILE}文件不存在")
                return False
        except Exception as e:
            print(f"读取服务器数据文件失败: {e}")
            return False

    # 检查服务器是否存在
    try:
        for server in server_data_cache.get("data", []):
            if server.get("server") == server_name:
                return True
        return False
    except Exception as e:
        print(f"解析服务器数据时出错: {e}")
        return False


async def download_json(url="https://jx3.seasunwbl.com/buyer?t=skin", key_name="skin_appearance_cache_key", output_filename="waiguan.json"):
    """
    从指定网站的localStorage中异步下载特定键的JSON数据（使用Playwright）

    参数:
    url (str): 要访问的网站URL
    key_name (str): localStorage中的键名
    output_filename (str): 输出的JSON文件名
    """
    print(f"开始从 {url} 获取 {key_name} 数据...")

    async with async_playwright() as p:
        # 启动浏览器

        browser = await p.chromium.launch(headless=True)  # 设置headless=True可在后台运行

        try:
            # 创建新页面
            page = await browser.new_page()

            # 访问网站
            await page.goto(url, wait_until="networkidle")


            # 等待确保数据加载到localStorage
            await asyncio.sleep(3)

            # 等待一些额外时间以确保数据加载完成
            # await asyncio.sleep(3)

            # 从localStorage获取数据
            result = await page.evaluate(f"localStorage.getItem('{key_name}')")

            if not result:
                print(f"错误: localStorage中未找到键 '{key_name}'")
                return False

            # 解析JSON并保存
            try:
                data = json.loads(result)
                with open(output_filename, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                print(f"✅ 数据已成功保存到 {os.path.abspath(output_filename)}")
                return True
            except json.JSONDecodeError:
                print(f"错误: 无法解析JSON数据")
                # 保存原始数据以便调试
                with open(f"waiguan.json", 'w', encoding='utf-8') as f:
                    f.write(result)
                print(f"原始数据已保存到 waiguan.json")
                return False

        except Exception as e:
            print(f"错误: {e}")
            return False
        finally:
            # 关闭浏览器
            await browser.close()