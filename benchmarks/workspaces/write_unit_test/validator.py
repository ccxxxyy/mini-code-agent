def is_valid_email(email: str) -> bool:
    if not email or "@" not in email:
        return False
    local, domain = email.rsplit("@", 1)
    if not local or not domain:
        return False
    if "." not in domain:
        return False
    return True
