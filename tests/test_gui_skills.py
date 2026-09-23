import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'games/bilibili_hero_merge'))
from skill_library import SkillLibrary


class LibraryTests(unittest.TestCase):
    def test_claim_return_reclaim_and_repeated_battle_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'skills.sqlite3';lib=SkillLibrary(path)
            raw='新技能 造成伤害'
            lib.record([raw],{'a':{'name':'甲'}})
            lib.claim('甲','新技能',raw)
            lib.remember('甲',['新技能'],True)
            lib.record([raw],{'b':{'name':'乙'}})
            self.assertEqual(lib.observations('甲'),[])
            self.assertEqual(lib.observations('乙'),[])
            lib.unclaim('甲','新技能')
            lib=SkillLibrary(path)
            self.assertEqual(lib.observations('乙'),[raw])
            self.assertEqual(lib.choices('甲'),[])
            lib.remember('甲',['新技能'],True)  # old profile cannot resurrect it
            self.assertEqual(lib.choices('甲'),[])
            self.assertEqual(lib.preferred('甲'),[])
            lib.claim('乙','新技能',raw)
            self.assertEqual(lib.observations('甲'),[])
            self.assertEqual(lib.choices('乙'),['新技能'])
            with self.assertRaises(ValueError):lib.claim('甲','新技能',raw)

    def test_legacy_exact_title_migration_and_return_is_not_reclaimed(self):
        with tempfile.TemporaryDirectory() as directory:
            lib=SkillLibrary(Path(directory)/'skills.sqlite3')
            lib.record(['巨型飞斧 骑士伤害提高'],{'k':{'name':'骑士'}})
            lib.remember('骑士',['巨型飞斧'])
            lib.migrate_legacy_claims()
            self.assertEqual(lib.observations('骑士'),[])
            lib.unclaim('骑士','巨型飞斧')
            lib.migrate_legacy_claims()
            self.assertEqual(lib.observations('其他英雄'),['巨型飞斧 骑士伤害提高'])

    def test_shared_workers_deduplicate_and_preserve_manual_order(self):
        with tempfile.TemporaryDirectory() as directory:
            lib = SkillLibrary(Path(directory)/'skills.sqlite3')
            lib.remember('新英雄', ['技能乙', '技能甲'], True)
            heroes = {'custom': {'name':'新英雄','buff_keywords':[]}, 'other': {'name':'骑士'}}
            cards = ['新技能 新英雄 伤害提高', '飞斧 伤害提高', '新英雄 骑士 两个名字']
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(lambda _: lib.record(cards, heroes), range(6)))
            self.assertEqual(len(lib.observations('新英雄')), 3)
            self.assertEqual(len(lib.observations('骑士')), 2)
            self.assertEqual(lib.preferred('新英雄'), ['技能乙', '技能甲'])
            self.assertNotIn('新技能', lib.choices('新英雄'))
            lib.add_hero({'name':'新英雄','buff_keywords':[]})
            self.assertEqual(len(lib.definitions()), 1)
            lib.remember('新英雄', [], True)
            self.assertEqual(lib.preferred('新英雄'), [])
            self.assertEqual(len(lib.choices('新英雄')), 2)
