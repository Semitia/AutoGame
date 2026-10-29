import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from calibration import geometry_from_points, validate_geometry
from autoplay import card_point, grid_point


class CalibrationTests(unittest.TestCase):
    def points(self):
        return dict(grid_a=[60,340],grid_b=[220,260],card=[35,500],card_next=[95,500],card_lower=[35,570],
                    filter_2=[90,620],filter_3=[150,620],filter_4=[210,620],filter_5=[270,620],filter_6=[330,620],
                    clear=[350,400],start=[280,700],card_tail=[335,500])

    def test_preview_coordinates_reproduce_grid_and_visible_cards(self):
        g=geometry_from_points(self.points(),[(1,2),(5,4)],(400,750))
        self.assertEqual(grid_point(1,2,g),(60,340))
        self.assertEqual(grid_point(5,4,g),(220,260))
        self.assertEqual(card_point(3,g),(95,570))
        self.assertEqual(g['visible_cards'],12)
        self.assertNotIn('continue',g)
        self.assertEqual(g['physical_size'],[400,750])

    def test_bad_geometry_is_rejected_before_saving_or_input(self):
        points=self.points();points['grid_b']=[220,100]
        with self.assertRaisesRegex(ValueError,'间距'):geometry_from_points(points,[(1,2),(5,4)],(400,750))
        points=self.points();points['start']=[500,700]
        with self.assertRaisesRegex(ValueError,'边界'):geometry_from_points(points,[(1,2),(5,4)],(400,750))
        g=geometry_from_points(self.points(),[(1,2),(5,4)],(400,750));g['gridStep']=float('nan')
        with self.assertRaises(ValueError):validate_geometry(g)

    def test_one_stage_stops_at_victory_without_needing_a_continue_point(self):
        from autoplay import Runner
        from test_autoplay import ready,report
        from model import read_json
        with tempfile.TemporaryDirectory() as directory:
            runner=Runner.__new__(Runner);runner.folder=Path(directory)
            state=ready();state['selected']=[dict(unit_id=11,_gridX=2,_gridY=4)]
            victory=dict(current_stage_id=829,battle=dict(battleID=829,state=4,result=1))
            runner.snapshot=lambda:state
            def wait(predicate,timeout=15):
                for candidate in (state,victory):
                    if predicate(candidate):return candidate
                raise AssertionError('不应等待下一关')
            runner.wait=wait;runner.max_stages=1;runner.completed=[]
            r=report();r.update(engine_fingerprint='test',context_hash='test')
            runner.plan=lambda _:r;runner.verify_roster=lambda:None;runner.deploy=lambda _:None
            runner.preparing=lambda _:state;runner.verify_request_order=lambda *args:None
            runner.g={'start':[200,700]};clicked=[]
            runner.input=SimpleNamespace(click=lambda *point:clicked.append(point))
            runner.event=lambda *args,**kwargs:None
            runner.continue_victory=lambda _:self.fail('达到关数上限不应点击继续')
            memory=SimpleNamespace(record_feedback=lambda *a,**k:None,close=lambda:None)
            with patch('experience.Experience',return_value=memory):runner.run()
            self.assertEqual(clicked,[(200,700)])
            self.assertEqual(runner.completed,[829])

    def test_confirmed_win_is_counted_even_if_next_screen_transition_fails(self):
        from autoplay import Runner
        from test_autoplay import ready,report
        with tempfile.TemporaryDirectory() as directory:
            runner=Runner.__new__(Runner);runner.folder=Path(directory)
            state=ready();state['selected']=[dict(unit_id=11,_gridX=2,_gridY=4)]
            victory=dict(current_stage_id=830,battle=dict(battleID=829,state=4,result=1))
            runner.snapshot=lambda:state
            def wait(predicate,timeout=15):
                return next(candidate for candidate in (state,victory) if predicate(candidate))
            runner.wait=wait;runner.max_stages=2;runner.completed=[]
            runner.catalog=SimpleNamespace(stages=[dict(id=829),dict(id=830)])
            r=report();r.update(engine_fingerprint='test',context_hash='test')
            runner.plan=lambda _:r;runner.verify_roster=lambda:None;runner.deploy=lambda _:None
            runner.preparing=lambda _:state;runner.verify_request_order=lambda *args:None
            runner.g={'start':[200,700]};runner.input=SimpleNamespace(click=lambda *point:None)
            runner.event=lambda *args,**kwargs:None
            def failed(_):raise RuntimeError('未识别到继续按钮')
            runner.continue_victory=failed
            memory=SimpleNamespace(record_feedback=lambda *a,**k:None,close=lambda:None)
            with patch('experience.Experience',return_value=memory),self.assertRaisesRegex(RuntimeError,'继续按钮'):runner.run()
            self.assertEqual(runner.completed,[829])
