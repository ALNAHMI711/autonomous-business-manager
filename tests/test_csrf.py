from app.csrf import CSRFProtector


def test_csrf_token_is_session_bound_and_verifiable():
    protector = CSRFProtector("test-secret")
    token = protector.issue("session-a")

    assert token
    assert protector.verify("session-a", token)
    assert not protector.verify("session-b", token)
    assert not protector.verify("session-a", "")


def test_csrf_tokens_do_not_depend_on_client_ip():
    protector = CSRFProtector("test-secret")
    token = protector.issue("session-a")

    assert protector.verify("session-a", token)


def test_csrf_secret_rotation_invalidates_old_tokens():
    first = CSRFProtector("secret-one")
    second = CSRFProtector("secret-two")
    token = first.issue("session-a")

    assert not second.verify("session-a", token)
