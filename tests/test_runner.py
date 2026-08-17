import unittest
from unittest.mock import patch

from pumplify.config import Settings
from pumplify.followback import (
    choose_follow_back_count,
    sample_follow_back_entries,
)
from pumplify.profile import (
    clean_username_base,
    extract_profile_address,
    extract_profile_username,
    make_username,
    profile_identifier,
)


FOLLOWBACK_BUCKETS = (
    (90, 3, 8),
    (8, 9, 20),
    (2, 21, 40),
)


class UsernameTests(unittest.TestCase):
    def test_configured_username_used_exactly_when_unique_disabled(self):
        settings = Settings(username="katakama", auto_unique_username=False)

        self.assertEqual(make_username(settings), "katakama")

    def test_data_override_username_is_used_as_unique_base(self):
        settings = Settings(username="katakama", auto_unique_username=True)

        with patch("pumplify.profile.random_suffix", return_value="9x"):
            self.assertEqual(make_username(settings, "roshiiiii"), "roshiiiii9x")

    def test_unique_username_is_capped_at_15_characters(self):
        settings = Settings(username="katakama", auto_unique_username=True)

        with patch("pumplify.profile.random_suffix", return_value="tj"):
            self.assertEqual(make_username(settings, "miaumiaulia"), "miaumiauliatj")
        with patch("pumplify.profile.random_suffix", return_value="8x"):
            self.assertEqual(make_username(settings, "snortingramash"), "snortingramas8x")

    def test_data_override_username_can_be_exact_when_unique_disabled(self):
        settings = Settings(username="katakama", auto_unique_username=False)

        self.assertEqual(make_username(settings, "roshiiiii"), "roshiiiii")

    def test_exact_username_is_sanitized_and_capped(self):
        settings = Settings(username="katakama", auto_unique_username=False)

        self.assertEqual(make_username(settings, "bad-name!!!1234567890"), "bad_name_123456")

    def test_empty_username_falls_back_to_safe_base(self):
        self.assertEqual(clean_username_base("!!!"), "user")

    def test_extract_profile_username_from_top_level_response(self):
        class Response:
            def json(self):
                return {"username": "roshiiiii9x"}

        self.assertEqual(extract_profile_username(Response()), "roshiiiii9x")

    def test_extract_profile_address_from_top_level_response(self):
        class Response:
            def json(self):
                return {"address": "BBGQ1U3D51njGgKJjB42HW2LUs4rr7GGdZ7zcgpCjP8D"}

        self.assertEqual(
            extract_profile_address(Response()),
            "BBGQ1U3D51njGgKJjB42HW2LUs4rr7GGdZ7zcgpCjP8D",
        )

    def test_profile_identifier_accepts_profile_url(self):
        self.assertEqual(
            profile_identifier("https://pump.fun/profile/manawinss"),
            "manawinss",
        )

    def test_profile_identifier_accepts_plain_username(self):
        self.assertEqual(profile_identifier("manawinss"), "manawinss")


class FollowBackTests(unittest.TestCase):
    def test_common_follow_back_bucket_is_3_to_8(self):
        with patch("pumplify.followback.random.randint", side_effect=[90, 6]):
            self.assertEqual(choose_follow_back_count(100, FOLLOWBACK_BUCKETS), 6)

    def test_rare_follow_back_bucket_can_reach_40(self):
        with patch("pumplify.followback.random.randint", side_effect=[100, 40]):
            self.assertEqual(choose_follow_back_count(200, FOLLOWBACK_BUCKETS), 40)

    def test_follow_back_count_is_capped_by_available_accounts(self):
        with patch("pumplify.followback.random.randint", side_effect=[100, 40]):
            self.assertEqual(choose_follow_back_count(12, FOLLOWBACK_BUCKETS), 12)

    def test_sample_follow_back_entries_uses_subset(self):
        entries = [{"publicAddress": str(i)} for i in range(30)]

        with patch("pumplify.followback.random.sample", return_value=entries[:12]) as sample:
            selected = sample_follow_back_entries(entries, 12)

        self.assertEqual(selected, entries[:12])
        sample.assert_called_once_with(entries, 12)


if __name__ == "__main__":
    unittest.main()
