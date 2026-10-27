"""permission system（TODO）。

计划：deny list、allow list、发邮件前 check_permission 弹窗确认。现在还没做。
"""

DENY_LIST: list[str] = []      # TODO: permission deny list
ALLOW_LIST: list[str] = []     # TODO: permission allow list


def check_permission(action: str) -> bool:
    # permission check not implemented yet
    return True
