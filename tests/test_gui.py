"""Offline launcher tests: no ADB, emulator, or battle input."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gui_config as config


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.settings = config.defaults()
        self.settings['python'] = sys.executable
        self.profile = self.settings['profiles']['默认方案']
        self.profile['device'] = 'test-device'

    def build(self):
        return config.build_launch(self.settings, self.profile)

    def coop(self):
        self.profile.update(mode='双人合作', host_device='host-serial', guest_device='guest-serial',
                            host_name='房主 昵称', guest_name='访客昵称',
                            host_tactics=str(config.GAME/'tactics/veteran.json'),
                            guest_tactics=str(config.GAME/'tactics/beginner.json'))

    def test_cache_roundtrip_chinese_and_incomplete_draft(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'cache.json'
            self.profile.update(device='', stage='还没填')
            config.atomic_json(path, self.settings)
            restored = config.load_cache(path)
            self.assertEqual(restored, self.settings)
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_bad_cache_not_silently_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'cache.json'
            path.write_text('{', encoding='utf-8')
            with self.assertRaises(ValueError): config.load_cache(path)
            self.assertEqual(path.read_text(), '{')

    def test_single_launch_is_explicit_and_isolated(self):
        self.profile.update(stage='6', index='1', runtime='runtime/gui/test small', runs='3', stop_on_loss=True)
        args, env, runtime, devices = self.build()
        self.assertIn('blue_planet', args)
        self.assertEqual(args[args.index('--device')+1], 'test-device')
        self.assertEqual(args[args.index('--runs')+1], '3')
        self.assertIn('--start-home', args)
        self.assertIn('--stop-on-loss', args)
        self.assertEqual(env['AUTOGAME_RUNTIME'], str(runtime))
        self.assertEqual(env['AUTOGAME_MUMU_INDEX'], '1')
        self.assertEqual(devices, ['test-device'])

    def test_stamina_excludes_runs(self):
        self.profile.update(until_stamina=True, runs='not used')
        args = self.build()[0]
        self.assertIn('--until-stamina', args)
        self.assertNotIn('--runs', args)

    def test_each_single_entry_and_resume_file(self):
        for entry, flag in [('空棋盘接管', '--empty-board'), ('暂停局接管', '--adopt-paused')]:
            self.profile['entry'] = entry
            args = self.build()[0]
            self.assertIn(flag, args)
            self.assertNotIn('--start-home', args)
        self.profile.update(entry='恢复状态文件', state='missing.json')
        with self.assertRaises(ValueError): self.build()
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)/'state.json'
            state.write_text('{}')
            self.profile['state'] = str(state)
            self.assertIn('--resume-state', self.build()[0])

    def test_stage34_is_a_normal_mainline_level(self):
        self.profile.update(stage='34', minutes='1.5', tactics=str(config.GAME/'tactics/veteran.json'))
        args = self.build()[0]
        self.assertIn('blue_planet', args)
        self.assertEqual(args[args.index('--stage')+1], '34')
        for flag in ('--tactics', '--stage', '--start-home'): self.assertIn(flag, args)

    def test_old_stage34_cache_migrates_to_actual_lineup(self):
        self.profile.update(mode='旧版34关', stage='1')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'gui.json'
            config.atomic_json(path, self.settings)
            migrated = config.load_cache(path)['profiles']['默认方案']
            self.assertEqual(migrated['mode'], '单人战术')
            self.assertEqual(migrated['stage'], '34')
            self.assertEqual([s['hero'] for s in migrated['lineup']['slots']], ['sea', 'sword', 'snow', 'mermaid'])
            config.validate_tactics(migrated['lineup'])

    def test_invalid_numbers_and_device(self):
        for key, value in [('minutes', 'NaN'), ('minutes', 'inf'), ('runs', '0'), ('stage', '-1'), ('index', '-1'), ('device', ''), ('device', 'two devices')]:
            with self.subTest(key=key, value=value):
                p = copy.deepcopy(self.profile)
                p[key] = value
                with self.assertRaises(ValueError): config.build_launch(self.settings, p)

    def test_coop_names_and_profiles_are_explicit(self):
        self.coop()
        args, _, _, devices = self.build()
        self.assertEqual(devices, ['host-serial', 'guest-serial'])
        self.assertIn('房主 昵称', args)
        self.assertNotIn('--runs', args)
        self.assertNotIn('--device', args)

    def test_coop_rejects_duplicate_device_missing_name_and_profile(self):
        self.coop()
        for key, value in [('guest_device', 'host-serial'), ('host_name', ''), ('guest_tactics', '')]:
            p = copy.deepcopy(self.profile)
            p[key] = value
            with self.assertRaises(ValueError): config.build_launch(self.settings, p)

    def test_coop_single_side_and_checkpoint_require_battle_only(self):
        self.coop()
        self.profile['only_side'] = 'guest'
        with self.assertRaises(ValueError): self.build()
        self.profile.update(battle_only=True, host_device='', host_tactics='')
        args, _, _, devices = self.build()
        self.assertEqual(devices, ['guest-serial'])
        self.assertNotIn('--host-device', args)
        self.assertIn('--battle-only', args)
        self.coop()
        self.profile.update(only_side='双方', battle_only=False, guest_state='missing.json')
        with self.assertRaisesRegex(ValueError, '检查点'): self.build()

    def test_invalid_tactics_rejected(self):
        profile = config.read_json(config.GAME/'tactics/beginner.json')
        profile['slots'][1]['hero'] = profile['slots'][0]['hero']
        with self.assertRaises(ValueError): config.validate_tactics(profile)
        profile = config.read_json(config.GAME/'tactics/beginner.json')
        profile['price_ratio']['upgrade'] = float('nan')
        with self.assertRaises(ValueError): config.validate_tactics(profile)


class DesktopTests(unittest.TestCase):
    """Real Qt widgets and signal wiring; subprocesses remain mocked."""
    @classmethod
    def setUpClass(cls):
        import gui
        cls.qt = gui.QApplication.instance() or gui.QApplication([])
        cls.qt.setStyle('Fusion')
        cls.qt.setStyleSheet(gui.STYLE)

    def setUp(self):
        import gui
        self.gui = gui
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cache = Path(self.temp.name)/'gui.json'
        settings = config.defaults()
        settings['python'] = sys.executable
        settings['profiles']['默认方案'].update(device='fake-serial', runtime=str(Path(self.temp.name)/'runtime'))
        for target, value in [('CACHE', self.cache), ('load_cache', lambda: settings)]:
            patcher = patch.object(gui, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        scan_patch = patch.object(gui.App, 'refresh_devices')
        self.scan = scan_patch.start()
        self.addCleanup(scan_patch.stop)
        self.app = gui.App()
        self.app.show()
        self.qt.processEvents()
        self.addCleanup(self.cleanup_window)

    def cleanup_window(self):
        self.app.jobs.clear()
        self.app.save_timer.stop()
        self.app.poll_timer.stop()
        self.app.device_timer.stop()
        self.app.deleteLater()
        self.qt.processEvents()

    def test_mode_visibility_save_and_profile_switch(self):
        self.assertTrue(self.app.lineups['lineup'].isVisible())
        self.app.change_mode('双人合作')
        self.qt.processEvents()
        self.assertEqual(set(self.app.lineups), {'host_lineup', 'guest_lineup'})
        self.assertTrue(self.app.lineups['host_lineup'].isVisible())
        self.assertTrue(self.app.lineups['guest_lineup'].isVisible())
        for _ in range(3): self.qt.processEvents()
        for panel in self.app.lineups.values():
            self.assertGreater(panel.rows[0].height(), 250)
        self.assertGreater(self.app.battle_scroll.verticalScrollBar().maximum(), 0)
        self.app.set_field('host_name', '我的房主')
        self.app.save()
        self.assertEqual(config.read_json(self.cache)['profiles']['默认方案']['host_name'], '我的房主')
        with patch.object(self.gui.QInputDialog, 'getText', return_value=('小号', True)):
            self.app.clone()
        self.assertNotEqual(self.app.data['profiles']['默认方案']['runtime'], self.app.profile['runtime'])
        self.assertEqual(self.app.current, '小号')

    def test_start_rejects_conflicts_and_stop_uses_original_runtime(self):
        fake = Mock(pid=123)
        fake.poll.return_value = None
        with patch.object(self.gui.subprocess, 'Popen', return_value=fake) as launch, patch.object(self.app, 'error') as error:
            self.app.start()
            self.assertEqual(launch.call_count, 1)
            runtime = self.app.jobs[0]['runtime']
            self.app.start()
            self.assertEqual(launch.call_count, 1)
            error.assert_called_once()
            self.app.profile['runtime'] = str(Path(self.temp.name)/'different')
            self.app.stop()
            self.assertTrue((runtime/'STOP').exists())
            self.assertFalse((Path(self.temp.name)/'different/STOP').exists())
            self.app.close()
            self.assertTrue(self.app.isVisible())

    def test_existing_stop_blocks_launch(self):
        runtime = Path(self.app.profile['runtime'])
        runtime.mkdir()
        (runtime/'STOP').touch()
        with patch.object(self.gui.subprocess, 'Popen') as launch:
            self.app.start()
            launch.assert_not_called()

    def test_inline_edits_persist_without_file_dialog_and_preserve_custom_fields(self):
        profile = config.read_json(config.GAME/'tactics/beginner.json')
        profile['hero_definitions'] = {'knight': {'name': '骑士', 'buff_keywords': ['飞斧']}}
        profile['note'] = '保留扩展字段'
        self.app.profile['lineup'] = profile
        self.app.rebuild_battle()
        self.qt.processEvents()
        panel = self.app.lineups['lineup']
        panel.rows[0].minimum.setValue(3)
        panel.rows[0].buffs.setPlainText('测试技能\n第二技能')
        self.app.save()
        result = config.read_json(self.cache)['profiles']['默认方案']['lineup']
        self.assertEqual(result['buff_priority'], profile['buff_priority'])
        self.assertEqual(result['hero_definitions'], profile['hero_definitions'])
        self.assertEqual(result['note'], profile['note'])
        self.assertEqual(result['slots'][0]['min_remaining'], 3)
        self.assertEqual(result['slots'][0]['buff_order'], ['测试技能', '第二技能'])

    def test_launch_snapshot_is_immutable_and_source_not_overwritten(self):
        original = config.read_json(config.GAME/'tactics/beginner.json')
        args, _, _, _ = self.app.launch_spec()
        snapshot = Path(args[args.index('--tactics')+1])
        saved = config.read_json(snapshot)
        self.app.lineups['lineup'].rows[0].minimum.setValue(5)
        self.app.save()
        self.assertEqual(config.read_json(snapshot), saved)
        self.assertEqual(config.read_json(config.GAME/'tactics/beginner.json'), original)

    def test_duplicate_ranks_block_start_and_draft_survives(self):
        self.app.lineups['lineup'].rows[0].rank.setValue(1)
        self.app.save()
        self.assertEqual(config.read_json(self.cache)['profiles']['默认方案']['lineup']['_gui_ranks'], [1, 1, 3, 4])
        with self.assertRaisesRegex(ValueError, '不能重复'): self.app.launch_spec()

    def test_only_mainline_and_coop_modes_are_visible(self):
        self.assertEqual(len(self.app.mode_group.buttons()), 2)
        self.assertFalse(any('34' in b.text() for b in self.app.mode_group.buttons()))

    def test_automatic_device_scan_and_list_survives_mode_and_lineup_rebuild(self):
        self.scan.assert_called_once()
        self.assertTrue(self.app.device_timer.isActive())
        raw = 'List of devices attached\nemulator-5554 device model:One\nemulator-5556 device model:Two\noffline-1 offline\n'
        self.app.events.put(('devices', (self.app.data['adb'], raw)))
        self.app.poll()
        self.assertEqual(self.app.online_devices, ['emulator-5554', 'emulator-5556'])
        self.app.device_boxes[0].setCurrentText('emulator-5556')
        self.assertEqual(self.app.profile['device'], 'emulator-5556')
        self.app.change_mode('双人合作')
        for w in self.app.device_boxes:
            self.assertEqual([w.itemText(i) for i in range(w.count())], self.app.online_devices)
        self.app.device_boxes[0].setCurrentText('emulator-5554')
        self.app.device_boxes[1].setCurrentText('emulator-5556')
        self.app.rebuild_battle()
        self.assertEqual([w.currentText() for w in self.app.device_boxes], ['emulator-5554', 'emulator-5556'])
        self.app.change_mode('单人战术')
        self.assertEqual(self.app.device_boxes[0].currentText(), 'emulator-5556')

    def test_disconnected_devices_removed_without_changing_selected_account(self):
        self.app.profile['device'] = 'emulator-5556'
        self.app.rebuild_battle()
        self.app.events.put(('devices', (self.app.data['adb'], 'emulator-5554 device\nemulator-5556 offline\n')))
        self.app.poll()
        self.assertEqual(self.app.online_devices, ['emulator-5554'])
        self.assertEqual(self.app.profile['device'], 'emulator-5556')
        self.assertEqual(self.app.device_boxes[0].currentData(), 'emulator-5556')
        self.assertIn('未连接', self.app.device_boxes[0].currentText())

    def test_named_devices_store_raw_serial_and_survive_rebuild(self):
        raw = 'emulator-5554 device\nemulator-5556 device\n'
        result = dict(raw=raw, serials=['emulator-5554', 'emulator-5556'], identities={'emulator-5554': '0', 'emulator-5556': '1'},
                      labels={'emulator-5554': '我的大号 · 实例 0（emulator-5554）', 'emulator-5556': '小号 · 实例 1（emulator-5556）'})
        self.app.events.put(('devices', (self.app.data['adb'], result)))
        self.app.poll()
        picker = self.app.device_boxes[0]
        self.assertIn('我的大号', picker.itemText(0))
        picker.setCurrentIndex(1)
        self.assertEqual(self.app.profile['device'], 'emulator-5556')
        self.app.save()
        self.assertEqual(config.read_json(self.cache)['profiles']['默认方案']['device'], 'emulator-5556')
        self.app.rebuild_battle()
        self.assertIn('小号', self.app.device_boxes[0].currentText())
        self.assertEqual(self.app.device_boxes[0].currentData(), 'emulator-5556')
        args, _, _, _ = self.app.launch_spec()
        self.assertEqual(args[args.index('--device')+1], 'emulator-5556')

    def test_old_adb_response_is_discarded_after_path_change(self):
        self.app.device_scan_busy = True
        self.app.events.put(('devices', ('old-adb.exe', 'wrong-device device\n')))
        self.app.poll()
        self.assertEqual(self.app.online_devices, [])
        self.assertFalse(self.app.device_scan_busy)

    def test_wheel_scrolls_page_without_changing_focused_controls(self):
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QWheelEvent
        self.app.change_mode('双人合作')
        self.qt.processEvents()
        row = self.app.lineups['host_lineup'].rows[0]
        for control in (row.hero, row.reserve, self.app.lineups['host_lineup'].upgrade, row.reserve.lineEdit()):
            scrollbar = self.app.battle_scroll.verticalScrollBar()
            scrollbar.setValue(0)
            before = (row.hero.currentIndex(), row.reserve.value(), self.app.lineups['host_lineup'].upgrade.value())
            control.setFocus()
            event = QWheelEvent(QPointF(5,5), QPointF(control.mapToGlobal(QPoint(5,5))), QPoint(), QPoint(0,-120),
                                Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False)
            self.qt.sendEvent(control, event)
            self.assertEqual(before, (row.hero.currentIndex(), row.reserve.value(), self.app.lineups['host_lineup'].upgrade.value()))
            self.assertGreater(scrollbar.value(), 0)

    def test_skill_drag_persists_and_switch_restores_hero_cache(self):
        from PySide6.QtCore import QModelIndex
        row = self.app.lineups['lineup'].rows[0]
        original = row.buffs.values()
        self.assertTrue(row.buffs.model().moveRows(QModelIndex(), 0, 1, QModelIndex(), len(original)))
        expected = original[1:] + original[:1]
        self.assertEqual(self.app.profile['lineup']['slots'][0]['buff_order'], expected)
        row.hero.setCurrentIndex(row.hero.findData('sea'))
        row.hero.setCurrentIndex(row.hero.findData('bomb'))
        self.assertEqual(row.buffs.values(), expected)
        self.app.save()
        self.assertEqual(config.read_json(self.cache)['profiles']['默认方案']['lineup']['slots'][0]['buff_order'], expected)

    def test_changing_hero_clears_previous_skill_preferences(self):
        row = self.app.lineups['lineup'].rows[0]
        self.assertTrue(row.buffs.toPlainText())
        row.hero.setCurrentIndex(row.hero.findData('sea'))
        self.assertEqual(self.app.profile['lineup']['slots'][0]['hero'], 'sea')
        self.assertEqual(self.app.profile['lineup']['slots'][0]['buff_order'], [])

    def test_skill_dialog_claim_and_return_updates_both_lists(self):
        from PySide6.QtCore import QTimer
        row=self.app.lineups['lineup'].rows[0]
        raw='测试新技能 小炮伤害提升'
        self.app.library.record([raw],{'bomb':{'name':'小炮'}})
        failures=[]
        def interact():
            dialog=self.app.findChild(self.gui.QDialog,'skillLibraryDialog')
            try:
                known=dialog.findChild(self.gui.QListWidget,'claimedSkills')
                pending=dialog.findChild(self.gui.QListWidget,'unclaimedSkills')
                self.assertEqual(pending.item(0).text(),'测试新技能\n小炮伤害提升')
                self.assertTrue(pending.wordWrap())
                self.assertEqual(pending.item(0).toolTip(),raw)
                with patch.object(self.gui.QInputDialog,'getText',side_effect=AssertionError('Double-click must not ask for confirmation')) as prompt:
                    pending.itemDoubleClicked.emit(pending.item(0))
                    prompt.assert_not_called()
                self.assertEqual(pending.count(),0)
                self.assertIn('测试新技能',row.buffs.values())
                for i in range(known.count()):
                    if known.item(i).text()=='测试新技能':known.setCurrentRow(i)
                next(b for b in dialog.findChildren(self.gui.QPushButton) if b.text()=='退回未认领').click()
                self.assertEqual(pending.item(0).text(),'测试新技能\n小炮伤害提升')
                self.assertEqual(pending.item(0).toolTip(),raw)
                self.assertNotIn('测试新技能',row.buffs.values())
                self.assertNotIn('测试新技能',self.app.library.choices('小炮'))
            except Exception as error:failures.append(error)
            finally:dialog.accept()
        QTimer.singleShot(0,interact)
        row.pick_skills()
        if failures:raise failures[0]


if __name__ == '__main__':
    unittest.main()
