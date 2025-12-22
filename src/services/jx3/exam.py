from __future__ import annotations

from typing import Any


def format_questions_reply(response: dict[str, Any] | None) -> str:
    if response is None:
        return "错误：未收到数据"

    reply = ""
    try:
        code = response.get("code")
        msg = response.get("msg", "")

        if code != 200 or str(msg).lower() != "success":
            reply += f"请求状态码：{code}\n"
            reply += f"状态：{msg}\n"
            return reply + "请求失败，请稍后再试"

        if "data" not in response or not response["data"]:
            return "没有找到题目数据"

        questions = response["data"]
        reply += f"找到 {len(questions)} 道题目\n"

        for i, question in enumerate(questions, 1):
            q_id = question.get("id", "未知ID")
            q_text = question.get("question", "未知问题")
            q_answer = question.get("answer", "未知答案")
            q_correctness = question.get("correctness")

            if q_correctness == 1:
                status = "✓ 正确"
            elif q_correctness == 0:
                status = "✗ 错误"
            else:
                status = "- 未知"

            reply += f"{i}. 题目ID: {q_id}\n"
            reply += f"   问题: {q_text}\n"
            reply += f"   答案: {q_answer}\n"
            reply += f"   状态: {status}\n"

            if i < len(questions):
                reply += "------------------------\n"

    except Exception as exc:
        return f"处理数据时出错: {str(exc)}"

    return reply

