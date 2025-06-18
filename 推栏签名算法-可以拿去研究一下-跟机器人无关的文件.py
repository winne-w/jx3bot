import hashlib
import hmac
import json
import datetime
import requests
import warnings
from collections import OrderedDict

# 忽略SSL警告
warnings.filterwarnings('ignore', message='Unverified HTTPS request')

# 配置参数 - 修改这里控制显示数量
PERSON_ID = "ce6357408d204997abb10c7d92e44fc0"
SIZE = 100  # 每页显示的记录数量，可以设置为5-50之间的值
CURSOR = 0  # 起始位置，0表示第一页


def calculate_xsk(data):
    """计算X-Sk签名"""
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


def get_person_match_history(person_id=PERSON_ID, size=SIZE, cursor=CURSOR):
    """获取个人比赛历史记录"""
    # 构造请求数据
    data = OrderedDict([
        ("person_id", person_id),
        ("size", size),
        ("cursor", cursor),
        ("ts", datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")[:17])
    ])

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
        "token": "推栏tk",
        "Content-Type": "application/json",
        "Host": "m.pvp.xoyo.com",
        "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip",
        "Cookie": "_wsi1=b71125f3741e4eca8746f6c6761f3da931c210a9; __wsi1=b71125f3741e4eca8746f6c6761f3da931c210a9; _wsi2=4ff0e5984f8e972e07ec7b417c122691a47b8044; __wsi2=4ff0e5984f8e972e07ec7b417c122691a47b8044; _wsi3=8cc04958f51e41c511d345eddbb3e7909fce07db; __wsi3=8cc04958f51e41c511d345eddbb3e7909fce07db",
        "User-Agent": "okhttp/3.12.2",
        "X-Sk": x_sk
    }

    # 发送请求
    url = "https://m.pvp.xoyo.com/mine/match/person-history"
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


# 主函数
if __name__ == "__main__":
    # 获取比赛历史数据
    result = get_person_match_history()

    # 直接输出JSON结果
    print(json.dumps(result, ensure_ascii=False, indent=2))