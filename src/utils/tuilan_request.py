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

    # 按字母顺序排序参数
    ordered_data = OrderedDict()
    for key in sorted(data.keys()):
        ordered_data[key] = data[key]

    # 确保JSON字符串正确编码
    try:
        json_str = json.dumps(ordered_data, separators=(',', ':'), ensure_ascii=False)
    except UnicodeEncodeError as e:
        print(f"JSON编码错误: {e}")
        # 如果包含无法编码的字符，使用ensure_ascii=True
        json_str = json.dumps(ordered_data, separators=(',', ':'), ensure_ascii=True)
    
    # 推栏签名算法：JSON字符串 + 固定后缀
    input_data = f"{json_str}@#?.#@"

    # 使用HMAC-SHA256计算签名
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

    # 自动添加时间戳 - 推栏API要求的时间戳格式
    # 格式：年月日时分秒毫秒（17位数字）
    data["ts"] = datetime.datetime.now().strftime("%Y%m%d%H%M%S%f")[:17]

    # 计算X-Sk签名
    x_sk, raw_json = calculate_xsk(data)
    
    # 调试信息：打印请求数据（可选，生产环境建议注释掉）
    print(f"请求数据: {raw_json}")
    print(f"X-Sk签名: {x_sk}")

    # 构造请求头 - 推栏API标准请求头
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
    try:
        # 确保数据是UTF-8编码的字节串
        if isinstance(raw_json, str):
            data_bytes = raw_json.encode('utf-8')
        else:
            data_bytes = raw_json
            
        response = requests.post(
            url,
            headers=headers,
            data=data_bytes,
            verify=False
        )
    except UnicodeEncodeError as e:
        print(f"编码错误: {e}")
        # 尝试使用不同的编码方式
        try:
            data_bytes = raw_json.encode('utf-8', errors='ignore')
            response = requests.post(
                url,
                headers=headers,
                data=data_bytes,
                verify=False
            )
        except Exception as e2:
            print(f"备用编码也失败: {e2}")
            return {"error": f"编码错误: {e}"}

    try:
        return response.json()
    except:
        return {"error": "无法解析响应", "text": response.text}


def test_signature():
    """
    测试签名算法是否正确
    """
    # 测试数据
    test_data = {
        "type": "role",
        "ts": "20241201120000000"
    }
    
    print("=== 推栏签名算法测试 ===")
    print(f"测试数据: {test_data}")
    
    signature, json_str = calculate_xsk(test_data)
    print(f"JSON字符串: {json_str}")
    print(f"签名结果: {signature}")
    print(f"签名长度: {len(signature)}")
    
    # 验证签名格式（应该是64位十六进制字符串）
    if len(signature) == 64 and all(c in '0123456789abcdef' for c in signature):
        print("✓ 签名格式正确")
    else:
        print("✗ 签名格式错误")
    
    return signature, json_str


# 导出组件
tuilan_request_module = {
    "calculate_xsk": calculate_xsk,
    "tuilan_request": tuilan_request,
    "test_signature": test_signature
}