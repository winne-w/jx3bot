"""
剑三机器人配置文件
包含API Token、URL等
"""
ADMIN_QQ = [595910443]
# API认证凭证
TOKEN = ""
TICKET = ""

# API接口地址
API_URLS = {
    "烟花查询": "https://www.jx3api.com/data/fireworks/records",
    "奇遇查询": "https://www.jx3api.com/data/luck/adventure",
    "装备查询": "https://www.jx3api.com/data/role/attribute",
    "竞技查询": "https://www.jx3api.com/data/arena/recent",
    "副本查询": "https://www.jx3api.com/data/role/teamCdList",
    "名片查询": "https://www.jx3api.com/data/show/card",
    "百战查询": "https://www.jx3api.com/data/role/monster",
    "资历查询": "https://www.jx3api.com/data/tuilan/achievement",
    "竞技场时间查询": "https://m.pvp.xoyo.com/3c/mine/arena/time-tag",
    "竞技场排行榜查询": "https://m.pvp.xoyo.com/3c/mine/arena/top200",

}

# 默认服务器
DEFAULT_SERVER = "梦江南"

# 用户会话配置
SESSION_TIMEOUT = 45  # 用户会话超时时间（秒）

# GET请求缓存时间
SESSION_data = 720

# 名片缓存目录
IMAGE_CACHE_DIR = "mpimg"

# 命令正则表达式模式
REGEX_PATTERNS = {
    "烟花查询": r"^烟花 (?P<value1>[\S]+)$|^烟花 (?P<server>[\S]+) (?P<value2>[\S]+)$",
    "奇遇查询": r"^奇遇 (?P<value1>[\S]+)$|^奇遇 (?P<server>[\S]+) (?P<value2>[\S]+)$",
    "装备查询": r"^(?:属性|装分) (?P<value1>[\S]+)$|^(?:属性|装分) (?P<server>[\S]+) (?P<value2>[\S]+)$",
    "竞技查询": r"^(?:战绩|竞技) (?P<value1>[\S]+)$|^(?:战绩|竞技) (?P<server>[\S]+) (?P<value2>[\S]+)$",
    "副本查询": r"^(?:副本|秘境) (?P<value1>[\S]+)$|^(?:副本|秘境) (?P<server>[\S]+) (?P<value2>[\S]+)$",
    "骗子查询": r"^(?:骗子|查人) (?P<value1>[\S]+)$|^(?:骗子|查人) (?P<server>[\S]+) (?P<value2>[\S]+)$",
    "科举答题": r"^(?:答题|~！) (?P<value1>[\S]+)$|^(?:答题|~！) (?P<server>[\S]+) (?P<value2>[\S]+)$",
    "技改": r"^\s*技改\s*$",
    "更新": r"^\s*更新\s*$",
    "活动": r"^\s*活动\s*$",
    "百战查询": r"^\s*百战\s*$",
    "交易行查询": r"^(?:交易行|交易行) (?P<value1>[\S]+)$|^(?:交易行|交易行) (?P<server>[\S]+) (?P<value2>[\S]+)$",
    "名片查询": r"^名片 (?P<value1>[\S]+)$|^名片 (?P<server>[\S]+) (?P<value2>[\S]+)$",
    "资历查询": r"^(?:资历|资历分布) (?P<value1>[\S]+)$|^(?:资历|资历分布) (?P<server>[\S]+) (?P<value2>[\S]+)$",
    "资历选择": r"^(\d+)$",  # 用于匹配用户回复的数字序号
    "竞技排名": r"^\s*竞技排名(?:统计)?(?:\s+拆分)?(?:\s+(?i:debug))?\s*$"
}

# 定义一个包含文本的列表
texts = ["你是我的土豆，又土又逗。",
         "我喜欢你，像风走了八百里，不问归期。",
         "昔有朝歌夜弦之高楼，上有倾城倾国之舞袖。",
         "若有知音见采，不辞遍唱阳春。",
         "人间最美，不过鲸落，一念百草生，一念山河成。",
         "星星在天上，你在我心里。",
         "你笑起来真像好天气。",
         "我在找一匹马。什么马？你的微信号码。",
         "你是不是喜欢我找出这句话中重复的字。",
         "见什么世面，见见你就好啦。",
         "我给你备注为一行，因为干一行，爱一行。"
         ]


wanbaolou = 50  # 分钟检查价格
# 开服监控API配置
STATUS_check_time = 3   # 分钟检查一次服务器状态
NEWS_records_time = 30  # 分钟检查一次 新闻技改
calendar_time = 9  # 每天9点推送日常
mail = "用于qq掉线提醒 邮箱的tk"
STATUS_check_API = "https://www.jx3api.com/data/server/check"  
# 新闻技改监控配置
NEWS_API_URL = "https://www.jx3api.com/data/news/allnews?limit=3"  # 新闻API地址
SKILL_records_URL = "https://www.jx3api.com/data/skills/records"  # 技改API地址
calendar_URL = "https://www.jx3api.com/data/active/calendar"   #活动日常
jx3box_URL = "https://cms.jx3box.com/api/cms/config/banner?client=std&type=code"   #福利

# 赛季时间定义
CURRENT_SEASON = "山海源流"
CURRENT_SEASON_START = "2025-10-30"

# 心法拼音映射及分类
KUNGFU_META = {
    "lijing": {"name": "离经易道", "category": "healer"},
    "zixia": {"name": "紫霞功", "category": "dps"},
    "beiao": {"name": "北傲诀", "category": "dps"},
    "lingsu": {"name": "灵素", "category": "healer"},
    "huajian": {"name": "花间游", "category": "dps"},
    "fenshan": {"name": "分山劲", "category": "dps"},
    "taixu": {"name": "太虚剑意", "category": "dps"},
    "zhoutian": {"name": "周天功", "category": "dps"},
    "butian": {"name": "补天诀", "category": "healer"},
    "bingxin": {"name": "冰心诀", "category": "dps"},
    "xiangzhi": {"name": "相知", "category": "healer"},
    "jingyu": {"name": "惊羽诀", "category": "dps"},
    "fenying": {"name": "焚影圣诀", "category": "dps"},
    "wufang": {"name": "无方", "category": "dps"},
    "yunshang": {"name": "云裳心经", "category": "healer"},
    "taixuan": {"name": "太玄经", "category": "dps"},
    "dujing": {"name": "毒经", "category": "dps"},
    "gufeng": {"name": "孤锋诀", "category": "dps"},
    "tianluo": {"name": "天罗诡道", "category": "dps"},
    "yijin": {"name": "易筋经", "category": "dps"},
    "aoxue": {"name": "傲血战意", "category": "dps"},
    "mowen": {"name": "莫问", "category": "dps"},
    "xiaochen": {"name": "笑尘诀", "category": "dps"},
    "yinlong": {"name": "隐龙诀", "category": "dps"},
    "linghai": {"name": "凌海诀", "category": "dps"},
    "cangjian": {"name": "山居剑意", "category": "dps"},
    "shanhai": {"name": "山海心诀", "category": "dps"},
    "youluo": {"name": "幽罗引", "category": "dps"},
}
