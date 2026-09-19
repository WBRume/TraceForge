import os
import re
import sys
import unittest


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.domains.task.services import avatar_service  # noqa: E402


GRADIENT_ID_PATTERN = re.compile(r'<linearGradient id="([^"]+)"')


class AvatarServiceGradientIdTest(unittest.TestCase):
    def test_default_avatar_uses_per_user_gradient_id(self):
        first = avatar_service.build_default_avatar_svg("test", "test@example.com", "u1")
        second = avatar_service.build_default_avatar_svg("test2", "test2@example.com", "u2")

        first_id = GRADIENT_ID_PATTERN.search(first).group(1)
        second_id = GRADIENT_ID_PATTERN.search(second).group(1)

        self.assertNotEqual(first_id, "bg")
        self.assertNotEqual(first_id, second_id)
        self.assertIn(f'fill="url(#{first_id})"', first)
        self.assertIn(f'fill="url(#{second_id})"', second)
        self.assertNotIn("url(#bg)", first)

    def test_soft_style_uses_per_user_gradient_id(self):
        svg = avatar_service.build_default_avatar_svg(
            "test", "test@example.com", "u1", style="soft"
        )
        gradient_id = GRADIENT_ID_PATTERN.search(svg).group(1)

        self.assertNotEqual(gradient_id, "bg")
        self.assertIn(f'fill="url(#{gradient_id})"', svg)
        self.assertNotIn("url(#bg)", svg)

    def test_gradient_id_is_deterministic_for_the_same_user(self):
        first = avatar_service.build_default_avatar_svg("test", "test@example.com", "u1")
        second = avatar_service.build_default_avatar_svg("test", "test@example.com", "u1")
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
