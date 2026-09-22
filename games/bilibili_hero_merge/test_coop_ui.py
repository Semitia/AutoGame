import unittest
from games.bilibili_hero_merge.coop_ui import Label, account_name, unique_name, row_action

class CoopUiTests(unittest.TestCase):
    def test_account_name_strips_server(self):
        self.assertEqual(account_name('幽美的竹笋（37服）'), '幽美的竹笋')
    def test_exact_name_and_same_row_action(self):
        labels = [Label('幽美的竹笋（37服）', 170, 142, .99), Label('邀请', 332, 163, .99)]
        self.assertIsNotNone(row_action(labels, '幽美的竹笋', '邀请', 21))
        self.assertIsNone(row_action(labels, '优美的竹笋', '邀请', 21))
    def test_duplicate_name_is_refused(self):
        labels = [Label('幽美的竹笋', 170, 142, .99), Label('幽美的竹笋', 170, 225, .99)]
        self.assertIsNone(unique_name(labels, '幽美的竹笋'))

if __name__ == '__main__': unittest.main()

