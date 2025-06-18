# appearance_search/searcher.py
import json
import aiofiles
from typing import List, Dict, Any, Set
from nonebot import logger


class TrieNode:
    def __init__(self):
        self.children = {}
        self.is_end = False
        self.items = []


class AsyncTrie:
    def __init__(self):
        self.root = TrieNode()

    def insert(self, word: str, item: Dict[str, Any]) -> None:
        node = self.root
        for char in word:
            if char not in node.children:
                node.children[char] = TrieNode()
            node = node.children[char]
            node.items.append(item)
        node.is_end = True

    def search_prefix(self, prefix: str) -> List[Dict[str, Any]]:
        node = self.root
        for char in prefix:
            if char not in node.children:
                return []
            node = node.children[char]
        return node.items


class AppearanceSearcher:
    def __init__(self):
        self.trie = AsyncTrie()
        self.data = []
        self.is_initialized = False

    async def initialize(self, file_path: str = 'waiguan.json') -> None:
        if self.is_initialized:
            return

        try:
            async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                content = await f.read()
                json_data = json.loads(content)

                # 从'data'键访问数组
                if isinstance(json_data, dict) and 'data' in json_data:
                    raw_data = json_data['data']
                else:
                    logger.error(f"JSON格式错误: 未找到'data'键")
                    raise ValueError("不支持的JSON格式")

                # 提取需要的字段
                self.data = []
                for item in raw_data:
                    if isinstance(item, dict) and 'name' in item and 'category' in item:
                        self.data.append({'name': item['name'], 'category': item['category']})

                await self._build_index()

                self.is_initialized = True
                logger.success(f"外观搜索索引已初始化，共 {len(self.data)} 个物品")

        except Exception as e:
            logger.error(f"初始化外观搜索索引失败: {str(e)}")
            raise

    async def _build_index(self) -> None:
        for item in self.data:
            # 索引名称的每个子串
            for i in range(len(item['name'])):
                self.trie.insert(item['name'][i:].lower(), item)

            # 索引分类的每个子串
            for i in range(len(item['category'])):
                self.trie.insert(item['category'][i:].lower(), item)

    async def search(self, keyword: str, limit: int = 10) -> List[Dict[str, Any]]:
        if not self.is_initialized:
            logger.warning("搜索器未初始化，正在尝试初始化...")
            await self.initialize()

        keyword = keyword.lower()
        raw_results = self.trie.search_prefix(keyword)

        # 去重并限制结果数量
        unique_results = []
        seen: Set[str] = set()

        for item in raw_results:
            item_key = f"{item['name']}_{item['category']}"
            if item_key not in seen and len(unique_results) < limit:
                unique_results.append(item)
                seen.add(item_key)

                if len(unique_results) >= limit:
                    break

        return unique_results


# 创建全局搜索器实例
appearance_searcher = AppearanceSearcher()


async def init_appearance_searcher(file_path: str = 'waiguan.json') -> None:
    await appearance_searcher.initialize(file_path)


async def search_appearance(keyword: str, limit: int = 15) -> List[Dict[str, Any]]:
    """
    既模糊又精确的外观搜索算法，综合多种匹配方式

    Args:
        keyword: 搜索关键词
        limit: 返回结果数量限制

    Returns:
        符合搜索条件的物品列表，按相关度排序
    """
    if not appearance_searcher.is_initialized:
        logger.warning("搜索器未初始化，正在尝试初始化...")
        await appearance_searcher.initialize()

    # 清理关键词
    clean_keyword = keyword.lower().replace('·', '').replace(' ', '')

    # 存储所有结果及其得分
    scored_results = []

    # 遍历所有物品
    for item in appearance_searcher.data:
        clean_name = item['name'].lower().replace('·', '').replace(' ', '')
        clean_category = item['category'].lower().replace('·', '').replace(' ', '')
        score = 0

        # 1. 精确匹配 (最高分)
        if clean_keyword == clean_name:
            score = 1000

        # 2. 前缀匹配 (高分)
        elif clean_name.startswith(clean_keyword):
            score = 800

        # 3. 包含整个关键词 (较高分)
        elif clean_keyword in clean_name:
            score = 600

        # 4. 有序子序列匹配 (适中分数) - 关键词字符按顺序出现，但可以不连续
        elif is_subsequence(clean_keyword, clean_name):
            score = 500

            # 额外加分：字符连续性越高分数越高
            consecutive_bonus = calculate_consecutive_bonus(clean_keyword, clean_name)
            score += consecutive_bonus

        # 5. 分离字符匹配 (低分) - 例如"龙隐金"的所有字符都在名称中，但顺序可能不同
        else:
            # 计算关键词中有多少字符出现在名称中
            char_match_count = sum(1 for char in clean_keyword if char in clean_name)
            match_ratio = char_match_count / len(clean_keyword)

            if match_ratio >= 0.7:  # 至少70%的字符匹配
                # 基础分
                score = 300

                # 根据匹配比例加分
                score += int(match_ratio * 100)

                # 检查有没有关键字组合出现在名称中
                for i in range(len(clean_keyword) - 1):
                    if clean_keyword[i:i + 2] in clean_name:
                        score += 50  # 每有一个2字连续组合加50分

        # 6. 类别匹配 (额外加分)
        if clean_keyword in clean_category:
            score += 100

        # 只记录有分数的结果
        if score > 0:
            scored_results.append((item, score))

    # 按分数降序排序
    scored_results.sort(key=lambda x: x[1], reverse=True)

    # 获取前limit个结果
    top_results = [item for item, _ in scored_results[:limit]]

    return top_results


def is_subsequence(s: str, t: str) -> bool:
    """
    检查s是否是t的子序列(字符按顺序出现但可以不连续)
    """
    i, j = 0, 0
    while i < len(s) and j < len(t):
        if s[i] == t[j]:
            i += 1
        j += 1
    return i == len(s)


def calculate_consecutive_bonus(keyword: str, text: str) -> int:
    """
    计算连续匹配字符的额外分数
    """
    bonus = 0
    current_pos = 0
    consecutive_count = 0

    for char in keyword:
        # 从上一个找到的位置之后开始查找
        pos = text.find(char, current_pos)
        if pos == -1:
            break

        # 如果字符位置连续，增加连续计数
        if pos == current_pos:
            consecutive_count += 1
        else:
            # 重置连续计数
            consecutive_count = 1

        current_pos = pos + 1

    # 连续字符越多，奖励越高
    bonus = consecutive_count * 20
    return bonus