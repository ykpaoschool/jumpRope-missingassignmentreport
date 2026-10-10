"""收件人地址的拆分与校验。

一个单元格里可能放了多个家长邮箱（JumpRope 导出里逗号和分号都见过，中英文标点都要认）。
拆分规则必须只有这一处：解析时用它统计「这列有多少邮箱」，发信时用它决定「这封发给谁」，
两边一旦不一致，就会出现「界面说有 2 个地址、实际只发了 1 个」这种事后查不出来的偏差。
"""

from __future__ import annotations

import re

# 空格不参与拆分：`Zhang <a@x.com>` 这类写法含有空格，切开会把它变成两个片段。
SEPARATORS = re.compile(r"[,;，；\r\n]+")

# 判定「像一个邮箱地址」：本地部分与域名都不含空白，域名带点。
# 同时用于列识别统计与发送前校验，所以它也是「什么样的值会被拦下」的定义。
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def split(value) -> list[str]:
    """把一个或多个地址的文本拆成地址列表。

    去空白、丢空项、按小写去重（保留首次出现的大小写与顺序）——
    「A@x.com; a@x.com」是同一个收件人，不能因此发两遍或算两个地址。

    只接受字符串：传进一个列表会被 `str()` 成 `"['a@x.com']"` 这种谁也看不出的垃圾地址，
    不如当场报错。已经拆好的列表请直接交给 join()。
    """
    if value is None:
        return []
    if not isinstance(value, str):
        raise TypeError(f"split() 只接受字符串，收到 {type(value).__name__}：{value!r}")
    out: list[str] = []
    seen: set[str] = set()
    for part in SEPARATORS.split(value):
        addr = part.strip()
        if not addr:
            continue
        key = addr.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(addr)
    return out


def join(value) -> str:
    """规范化成一行文本：写 To 头、界面展示与发送日志都用它。

    字符串先按本模块的规则拆开再拼（`a@x.com;b@y.com` → `a@x.com, b@y.com`），
    列表则直接连接——解析时手里已经是拆好的地址列表。
    两种输入都收，是因为把列表当字符串处理会产生 `"['a@x.com']"` 这种静默的垃圾值。
    """
    addrs = list(value) if isinstance(value, (list, tuple)) else split(value)
    return ", ".join(addrs)


def is_address(token: str) -> bool:
    """单个片段是否像一个邮箱地址。"""
    return bool(EMAIL_RE.match(token.strip()))


def invalid(value) -> list[str]:
    """拆开后不属于邮箱地址的片段（保持顺序、去重）。空单元格返回空列表。"""
    return [a for a in split(value) if not is_address(a)]
