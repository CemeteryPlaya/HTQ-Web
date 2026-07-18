import bcrypt
import pytest

from apps.users.models import User, UserStatus


@pytest.mark.django_db
def test_raw_bcrypt_hash_verifies_and_upgrades():
    raw = bcrypt.hashpw(b"S3cret!", bcrypt.gensalt(rounds=12)).decode()
    u = User.objects.create(username="fa", email="fa@htq.test",
                            password=raw, status=UserStatus.ACTIVE)
    assert u.check_password("S3cret!") is True
    u.refresh_from_db()
    assert u.password.startswith("pbkdf2_sha256$")  # апгрейд произошёл
    assert u.check_password("S3cret!") is True      # и новый хэш работает


@pytest.mark.django_db
def test_wrong_password_rejected_for_bcrypt():
    raw = bcrypt.hashpw(b"S3cret!", bcrypt.gensalt(rounds=12)).decode()
    u = User.objects.create(username="fb", email="fb@htq.test", password=raw)
    assert u.check_password("wrong") is False


@pytest.mark.django_db
def test_is_active_follows_status():
    u = User.objects.create(username="fc", email="fc@htq.test",
                            password="x", status=UserStatus.PENDING)
    assert u.is_active is False
