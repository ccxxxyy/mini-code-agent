from validators import is_valid_email, is_valid_port, normalize_phone


def test_email_needs_domain():
    assert is_valid_email("a@b.com") is True
    assert is_valid_email("a@") is False
    assert is_valid_email("@b.com") is False
    assert is_valid_email("noat") is False


def test_port_excludes_zero():
    assert is_valid_port(1) is True
    assert is_valid_port(65535) is True
    assert is_valid_port(0) is False
    assert is_valid_port(70000) is False


def test_phone_keeps_leading_zeros():
    assert normalize_phone("(010) 1234-5678") == "01012345678"
