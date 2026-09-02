from emergency_authorization import EmergencyCallAuthorizer


def test_authorization_is_bound_to_the_issuing_user_and_session():
    authorizer = EmergencyCallAuthorizer()
    token = authorizer.issue("user-1", "session-1")

    assert not authorizer.consume(token, "user-2", "session-1")
    assert authorizer.consume(token, "user-1", "session-1")


def test_authorization_is_single_use():
    authorizer = EmergencyCallAuthorizer()
    token = authorizer.issue("user-1", "session-1")

    assert authorizer.consume(token, "user-1", "session-1")
    assert not authorizer.consume(token, "user-1", "session-1")
