"""Public original sprites on synthetic screens. No private screenshot fixtures."""
import unittest
from PIL import Image,ImageDraw
from hunt_paths import ASSETS
from hunt_layout import Layout,LayoutError


class LayoutTests(unittest.TestCase):
    def setUp(self):self.layout=Layout()

    def test_original_item_sprites_follow_current_scale(self):
        for scale in (.6,1,1.4):
            image=Image.new('RGB',(600,1200),'#41435a')
            expected={}
            for name,y in [('rage',890),('lock',1030)]:
                icon=Image.open(ASSETS/(name+'.png')).convert('RGBA').resize((78,86))
                image.paste(icon,(500,y),icon);expected[name]=(539*scale,(y+43)*scale)
            image=image.resize((round(600*scale),round(1200*scale)))
            for name in expected:
                point=self.layout.icon(image,name)
                self.assertAlmostEqual(point[0],expected[name][0],delta=6)
                self.assertAlmostEqual(point[1],expected[name][1],delta=6)

    def test_blank_screen_never_produces_item_exit_or_shoot_point(self):
        image=Image.new('RGB',(600,1200),'white')
        for name in ('rage','lock'):
            with self.assertRaises(LayoutError):self.layout.icon(image,name)
        with self.assertRaises(LayoutError):self.layout.close(image)
        with self.assertRaises(LayoutError):self.layout.aim(image)

    def test_unique_visible_navigation_arrow_and_start_button(self):
        image=Image.new('RGB',(600,1200),'#28223c');draw=ImageDraw.Draw(image)
        draw.polygon([(535,450),(570,480),(535,510)],fill='white')
        self.assertAlmostEqual(self.layout.navigation(image,'next')[0],553,delta=2)
        draw.rounded_rectangle((180,950,500,1030),radius=10,fill='#edc52b')
        self.assertAlmostEqual(self.layout.start(image)[0],340,delta=2)
        draw.polygon([(535,650),(570,680),(535,710)],fill='white')
        with self.assertRaises(LayoutError):self.layout.navigation(image,'next')
