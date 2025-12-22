from __future__ import annotations


def convert_number(amount: int) -> str:
    thousands = amount // 100000000
    thousands = (
        ""
        if thousands == 0
        else f" {thousands}<img src='http://192.168.100.1:5244/img/qiyu/img/zhuan.png' alt='砖'>"
    )
    remainder = (amount % 100000000) // 10000
    remainder = (
        ""
        if remainder == 0
        else f" {remainder}<img src='http://192.168.100.1:5244/img/qiyu/img/jin.png' alt='金'>"
    )
    billions = (amount % 10000) // 100
    billions = (
        ""
        if billions == 0
        else f" {billions}<img src='http://192.168.100.1:5244/img/qiyu/img/yin.png' alt='银'>"
    )
    return f"{thousands}{remainder}{billions}"

