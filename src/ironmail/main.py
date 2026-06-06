# -*- coding: utf-8 -*-
"""IronMail 图形界面共享的领域逻辑。

这里集中放置发送前的内容检查、字段校验、模板与程序目录解析、
发信错误文案和崩溃日志等纯逻辑，供 `ironmail.gui` 复用。
本模块不包含任何界面交互。
"""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

import pandas as pd

# 设置SSL证书路径（修复Windows上的证书问题）
try:
    import certifi
    os.environ['SSL_CERT_FILE'] = certifi.where()
except ImportError:
    pass

# 多语言敏感词列表（欺诈、诈骗相关）
SENSITIVE_WORDS = {
    # 中文
    '欺诈', '诈骗', '骗局', '传销', '洗钱', '非法集资', '赌博', '色情',
    '钓鱼', '黑客', '病毒', '木马', '勒索', '假冒', '伪造', '走私',
    '贩毒', '恐怖', '暴力', '枪支', '军火', '假币', '信用卡盗刷',
    '账号盗取', '密码窃取', '身份盗用', '虚假中奖', '刷单返利',

    # 英文
    'fraud', 'scam', 'phishing', 'money laundering', 'pyramid scheme',
    'illegal', 'hack', 'virus', 'malware', 'ransomware', 'counterfeit',
    'smuggling', 'drug trafficking', 'terrorism', 'violence', 'gambling',
    'pornography', 'identity theft', 'credit card fraud', 'fake lottery',
    'get rich quick', 'nigerian prince', 'advance fee',

    # 日文
    '詐欺', '詐取', 'フィッシング', 'マネーロンダリング', 'ねずみ講',
    '違法', 'ハッキング', 'ウイルス', 'マルウェア', '偽造', '密輸',
    '麻薬', 'テロ', '暴力', 'ギャンブル', 'ポルノ', '身分詐称',
    '架空請求', 'ワンクリック詐欺', '振り込め詐欺',

    # 德文
    'betrug', 'betrügerisch', 'phishing', 'geldwäsche', 'schneeballsystem',
    'illegal', 'hacking', 'virus', 'malware', 'fälschung', 'schmuggel',
    'drogenhandel', 'terrorismus', 'gewalt', 'glücksspiel', 'pornografie',
    'identitätsdiebstahl', 'kreditkartenbetrug', 'vorschussbetrug',

    # 韩文
    '사기', '피싱', '자금세탁', '다단계', '불법', '해킹', '바이러스',
    '악성코드', '랜섬웨어', '위조', '밀수', '마약', '테러', '폭력',
    '도박', '포르노', '신분도용', '보이스피싱', '스미싱',
}


TEMPLATE_DIR_NAME = "邮件模板"
LEGACY_TEMPLATE_DIR_NAME = "模板"
REQUIRED_WITH_TEMPLATE = ["邮箱"]
REQUIRED_WITHOUT_TEMPLATE = ["邮箱", "邮件主题", "邮件正文"]


def format_send_error(error: Exception) -> str:
    """把常见发信错误转成更容易判断的中文提示。"""
    raw = str(error)
    text = raw.lower()
    if "policy restrictions" in text and "postmaster.gmx.net" in text:
        ip = extract_gmx_policy_ip(raw)
        if ip:
            return f"GMX拒收本次发信：当前出网IP {ip} 被GMX策略限制。程序会尝试切换其他发件邮箱。"
        return "GMX拒收本次发信：服务商返回策略限制。程序会尝试切换其他发件邮箱。"
    return raw


def extract_gmx_policy_ip(message: str) -> str:
    """从GMX错误链接里提取被拦截的出网IP。"""
    match = re.search(r"[?&]v=([0-9a-fA-F:.]+)", message)
    return match.group(1) if match else ""


def check_sensitive_words(text: str) -> Tuple[bool, str]:
    """
    检查文本是否包含敏感词
    返回: (是否包含敏感词, 匹配到的敏感词)
    """
    text_lower = text.lower()
    for word in SENSITIVE_WORDS:
        if word.lower() in text_lower:
            return True, word
    return False, ""


def scan_all_emails(df: pd.DataFrame) -> List[int]:
    """
    扫描所有邮件内容，检查敏感词
    返回: [包含问题内容的行号, ...]
    """
    violations = []
    for index, row in df.iterrows():
        subject = str(row.get('邮件主题', '')).strip()
        body = str(row.get('邮件正文', '')).strip()

        # 检查主题和正文
        has_sensitive_subject, _ = check_sensitive_words(subject)
        has_sensitive_body, _ = check_sensitive_words(body)

        if has_sensitive_subject or has_sensitive_body:
            violations.append(index + 1)

    return violations


def get_app_dir() -> Path:
    """获取项目根目录，兼容源码运行和打包后的exe"""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parents[2]


def get_mails_dir(app_dir: Path) -> Path:
    """获取邮件工作目录。"""
    return app_dir / 'Mails'


def get_template_dir(app_dir: Path) -> Path:
    """获取邮件模板目录，兼容旧目录名。"""
    mails_dir = get_mails_dir(app_dir)
    preferred = mails_dir / TEMPLATE_DIR_NAME
    legacy = mails_dir / LEGACY_TEMPLATE_DIR_NAME
    if preferred.exists():
        return preferred
    if legacy.exists():
        return legacy
    return preferred


def validate_email_dataframe(df: pd.DataFrame, use_template: bool) -> list[str]:
    """检查发送所需字段是否齐全。"""
    required = REQUIRED_WITH_TEMPLATE if use_template else REQUIRED_WITHOUT_TEMPLATE
    missing = [column for column in required if column not in df.columns]
    if missing:
        return [f"缺少必需字段: {', '.join(missing)}"]
    return []


def write_crash_log(traceback_text: str) -> Path | None:
    """写入崩溃日志。"""
    try:
        log_path = get_app_dir() / "logs" / "crash.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as file:
            file.write("\n" + "=" * 72 + "\n")
            file.write(datetime.now().strftime("[%Y-%m-%d %H:%M:%S] 未处理错误\n"))
            file.write(traceback_text)
            if not traceback_text.endswith("\n"):
                file.write("\n")
        return log_path
    except Exception:
        return None
