"""Check the extracted transport without touching a live emulator."""
import unittest
from unittest.mock import patch
from farmer import Bot
from autogame.platforms.mumu import MuMuPlatform

class PlatformTests(unittest.TestCase):
 def test_adb_capture_and_inputs_use_selected_device(self):
  platform=MuMuPlatform(device='test-device')
  with patch('autogame.platforms.mumu.subprocess.check_output',return_value=b'png') as call:
   self.assertEqual(platform.screenshot(),b'png')
   self.assertEqual(call.call_args.args[0],[platform.adb,'-s','test-device','exec-out','screencap','-p'])
   platform.swipe(1,2,3,4,650)
   self.assertEqual(call.call_args.args[0], [platform.adb,'-s','test-device','shell','input','swipe','1','2','3','4','650'])
 def test_game_reference_coordinates_become_android_pixels(self):
  bot=Bot.__new__(Bot);bot.platform=MuMuPlatform(device='test-device')
  with patch.object(bot.platform,'tap') as tap:
   bot.tap(216,400)
   tap.assert_called_once_with(540,1000)

if __name__=='__main__':unittest.main()
