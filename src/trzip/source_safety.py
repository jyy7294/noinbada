from __future__ import annotations

import re


# Obvious solicitation/contact spam sometimes appears inside X's public trend
# module. It is not a cultural event and must not enter the immutable source
# ledger or any ranking calculation.
SPAM_SOLICITATION_PATTERNS = (
    r"출장\s*만남",
    r"빠른\s*이동\s*연락",
    r"군인\s*가능",
    r"사모님.*(?:고수입|상대)",
    r"고수익\s*단기",
    r"(?:라인|카톡|텔레그램)\s*[a-z0-9_]*\d{2,}",
    r"꼬들\s*\d{3,}",
)


def is_spam_solicitation(value: object) -> bool:
    normalized = " ".join(str(value or "").casefold().split())
    return any(re.search(pattern, normalized) for pattern in SPAM_SOLICITATION_PATTERNS)
