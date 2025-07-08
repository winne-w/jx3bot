import hashlib
import hmac
import json
import datetime
import requests
import warnings
from collections import OrderedDict
from config import TICKET

# 忽略SSL警告
warnings.filterwarnings('ignore', message='Unverified HTTPS request')


def calculate_xsk(data):
    """
    计算X-Sk签名

    Args:
        data (dict): 请求参数字典

    Returns:
        tuple: (签名, JSON字符串)
    """
    secret_key = "MaYoaMQ3zpWJFWtN9mqJqKpHrkdFwLd9DDlFWk2NnVR1mChVRI6THVe6KsCnhpoR"

    ordered_data = OrderedDict()
    for key in data.keys():
        ordered_data[key] = data[key]

    json_str = json.dumps(ordered_data, separators=(',', ':'), ensure_ascii=False)
    input_data = f"{json_str}@#?.#@"

    signature = hmac.new(
        secret_key.encode('utf-8'),
        input_data.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

    return signature, json_str


def tuilan_request(url, params=None):
    """
    推栏API请求方法

    Args:
        url (str): 请求地址
        params (dict, optional): 请求参数，不包含ts

    Returns:
        dict: 响应结果
    """
    # 构造请求数据
    data = OrderedDict()

    # 添加用户传入的参数
    if params:
        for key, value in params.items():
            data[key] = value

    # 自动添加时间戳
    data["ts"] = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")[:17]

    # 计算X-Sk签名
    x_sk, raw_json = calculate_xsk(data)

    # 构造请求头
    headers = {
        "accept": "application/json",
        "deviceid": "lWrrIG5QpALPiSZ7txB//A==",
        "platform": "android",
        "gamename": "jx3",
        "fromsys": "APP",
        "clientkey": "1",
        "cache-control": "no-cache",
        "apiversion": "3",
        "sign": "true",
        "token": TICKET,
        "Content-Type": "application/json",
        "Host": "m.pvp.xoyo.com",
        "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip",
        "Cookie": "_wsi1=b71125f3741e4eca8746f6c6761f3da931c210a9; __wsi1=b71125f3741e4eca8746f6c6761f3da931c210a9; _wsi2=4ff0e5984f8e972e07ec7b417c122691a47b8044; __wsi2=4ff0e5984f8e972e07ec7b417c122691a47b8044; _wsi3=8cc04958f51e41c511d345eddbb3e7909fce07db; __wsi3=8cc04958f51e41c511d345eddbb3e7909fce07db",
        "User-Agent": "okhttp/3.12.2",
        "X-Sk": x_sk
    }

    # 发送请求
    response = requests.post(
        url,
        headers=headers,
        data=raw_json.encode('utf-8'),
        verify=False
    )

    try:
        return response.json()
    except:
        return {"error": "无法解析响应", "text": response.text}


# 导出组件
tuilan_request_module = {
    "calculate_xsk": calculate_xsk,
    "tuilan_request": tuilan_request
}