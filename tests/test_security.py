from app.security import SecurityManager


def test_password_hash_is_salted_and_verifiable():
    first = SecurityManager.hash_password("correct horse battery staple")
    second = SecurityManager.hash_password("correct horse battery staple")

    assert first != second
    assert SecurityManager.verify_password("correct horse battery staple", first)
    assert not SecurityManager.verify_password("wrong", first)


def test_session_tokens_are_opaque_and_hashable():
    token = SecurityManager.generate_session_token()
    assert len(token) >= 64
    assert SecurityManager.hash_session_token(token) != token
    assert SecurityManager.hash_session_token(token) == SecurityManager.hash_session_token(token)
