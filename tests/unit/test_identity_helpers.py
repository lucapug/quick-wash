"""The pure half of the identity layer (issue #9): hashing, expiry, single use, the accepted fields.

These are the pieces a unit test is shorter and sharper on than an end-to-end one (docs/spec.md,
Testing Decisions): inputs and outputs are data, no repository and no mock. The HTTP outcomes of the
same rules are in `tests/integration/test_otp_identity.py` and
`tests/integration/test_identity_layer.py`.
"""

from datetime import datetime, timedelta

from src import identity

START = datetime(2026, 11, 12, 9, 0)


def test_the_code_is_numeric_and_its_stored_form_is_a_hash():
    code = identity.new_otp()
    assert len(code) == identity.OTP_LENGTH and code.isdigit()
    assert identity.hash_code(code) != code                       # what the repository can hold
    assert identity.hash_code(code) == identity.hash_code(code)   # the match a verify runs on


def test_the_two_codes_are_different_shapes_so_they_can_never_be_confused():
    # AC6: the unlock code is the booking's numeric code, 4 digits; the sign-in code is 6.
    assert identity.OTP_LENGTH > 4
    assert identity.is_numeric_code("1001") and identity.is_numeric_code("483920")
    assert not identity.is_numeric_code("M1")


def test_the_code_expires_at_the_minute_of_its_ten_minute_ttl():
    expires = identity.expires_at(START)
    assert expires - START == timedelta(minutes=10)
    assert not identity.is_expired(expires, START + timedelta(minutes=9))
    assert identity.is_expired(expires, START + timedelta(minutes=10))   # AC4: at 10, not after 10


def test_single_use_is_a_fact_of_the_row():
    assert not identity.is_spent({"used_at": None})
    assert identity.is_spent({"used_at": "2026-11-12T09:05:00"})


def test_the_two_steps_accept_their_own_fields_and_a_password_field_does_not_exist():
    assert identity.SIGN_IN_FIELDS == ("email",)
    assert identity.unexpected({"email": "anna@example.com"}, identity.SIGN_IN_FIELDS) == []
    assert identity.unexpected({"email": "anna@example.com", "password": "topsecret"},
                               identity.SIGN_IN_FIELDS) == ["password"]
    assert identity.unexpected({"email": "anna@example.com", "otp": "483920"}, identity.VERIFY_FIELDS) == []
    # A password field that is quietly ignored is still a password field: it is refused instead.
    assert identity.unexpected({"email": "anna@example.com", "otp": "483920", "code": "1001"},
                               identity.VERIFY_FIELDS) == ["code"]


def test_the_session_token_is_opaque_and_carries_no_customer_data():
    token = identity.new_token()
    assert len(token) >= 16 and "@" not in token
    assert token != identity.new_token()          # two visits, two tokens, one identity
