import unittest

from common.passwords import hash_password, verify_password


class PasswordTests(unittest.TestCase):
    def test_hashes_are_salted_and_verify_without_storing_plaintext(self):
        first = hash_password("a strong test password")
        self.assertNotEqual(first, hash_password("a strong test password"))
        self.assertNotIn("a strong test password", first)
        self.assertTrue(verify_password("a strong test password", first))
        self.assertFalse(verify_password("wrong password", first))

    def test_malformed_hash_and_invalid_password_fail_safely(self):
        self.assertFalse(verify_password("anything", "malformed"))
        for value in ("short", "x" * 129):
            with self.assertRaises(ValueError):
                hash_password(value)
