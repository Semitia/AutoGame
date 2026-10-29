"""No desktop input: exercise deployment readback and stage-transition guards."""
import copy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from autoplay import Runner,WaitTimeout,canonical,card_point,is_preparing,next_stage_id,verified


def ready(stage=829):
    return dict(current_stage_id=stage,controller=dict(stageID=stage,battleMode=1),
        battle=dict(battleID=stage,state=1),prepare=dict(stageID=stage,isShow=True),
        selected=[],pet_list=[11])


def report():
    return dict(stage_id=829,placements=[dict(unit_id=11,x=2,y=4)],
        evaluation=dict(won=True),finalists=[dict(validation=[dict(won=True)]*3)])


class AutoplayTests(unittest.TestCase):
    def test_requires_training_and_three_successful_rechecks(self):
        r=report();self.assertTrue(verified(r))
        for checks in ([],[dict(won=True)]*2,[dict(won=True)]*2+[dict(won=False)]):
            r['finalists'][0]['validation']=checks;self.assertFalse(verified(r))
        r=report();r['evaluation']['won']=False;self.assertFalse(verified(r))

    def test_server_progress_is_not_ui_progress(self):
        state=ready();self.assertTrue(is_preparing(state))
        state['battle']=dict(battleID=828,state=4,result=1)
        self.assertFalse(is_preparing(state))
        state['battle']=dict(battleID=829,state=1);state['prepare']['stageID']=828
        self.assertFalse(is_preparing(state))
        state['prepare']=dict(stageID=829,isShow=False);self.assertTrue(is_preparing(state))
        del state['selected'];self.assertFalse(is_preparing(state))

    def test_cards_are_column_major_and_bounded(self):
        g=dict(card=[36,479],cardStep=61,cardRowStep=67)
        self.assertEqual(card_point(3,g),(97,546))
        for index in (-1,12):
            with self.assertRaises(ValueError):card_point(index,g)
        g['cardRight']=308
        self.assertEqual(card_point(12,g,total=14,tail=True),(308,479))
        self.assertEqual(card_point(13,g,total=14,tail=True),(308,546))
        with self.assertRaises(ValueError):card_point(0,g,total=14,tail=True)

    def test_chapter_transition_uses_configured_ids_with_gaps(self):
        catalog=SimpleNamespace(stages=[dict(id=830),dict(id=881),dict(id=829)])
        self.assertEqual(next_stage_id(catalog,829),830)
        self.assertEqual(next_stage_id(catalog,830),881)
        with self.assertRaises(ValueError):next_stage_id(catalog,881)

    def driver(self,wrong_drag=False):
        runner=Runner.__new__(Runner);state=ready()
        runner.g=dict(grid=[106,371],gridStep=40.5,card=[36,479],cardStep=61,cardRowStep=67,clear=[348,347])
        runner.catalog=SimpleNamespace(units={'11':dict(UnitElement=2)})
        runner.preparing=lambda stage:copy.deepcopy(state)
        runner.event=lambda *args,**kw:None
        runner.actions=[]
        def action(stage,kind,**args):
            runner.actions.append(kind)
            if kind=='click':state['selected']=[dict(unit_id=11,_gridX=1,_gridY=1)]
            elif not wrong_drag:state['selected']=[dict(unit_id=11,_gridX=2,_gridY=4)]
            return copy.deepcopy(state)
        runner.action=action
        return runner,state

    def test_deploy_uses_actual_auto_placement_then_verifies_drag(self):
        runner,state=self.driver();runner.deploy(report())
        self.assertEqual(runner.actions,['click','drag'])
        self.assertEqual(canonical(state['selected']),[(11,2,4)])
        runner.deploy(report());self.assertEqual(len(runner.actions),2)

    def test_failed_drop_stops_before_any_battle_input(self):
        runner,_=self.driver(wrong_drag=True)
        with self.assertRaisesRegex(RuntimeError,'拖动未核验'):runner.deploy(report())
        self.assertEqual(runner.actions,['click','drag'])

    def test_last_page_scroll_preserves_deployment_and_uses_tail_card(self):
        runner,state=self.driver();state['pet_list']=list(range(100,112))+[11,112]
        runner.catalog.units.update({str(i):dict(UnitElement=2) for i in state['pet_list']})
        runner.g.update(cardRight=308,gallerySwipe=[300,516,55,516])
        original=runner.action
        def action(stage,kind,**args):
            if kind=='drag' and args['from_y']==516:
                runner.actions.append('scroll');return copy.deepcopy(state)
            if kind=='click':self.assertEqual((args['x'],args['y']),(308,479))
            return original(stage,kind,**args)
        runner.action=action
        with patch('autoplay.time.sleep'):runner.deploy(report())
        self.assertEqual(runner.actions,['scroll','click','drag'])
        self.assertEqual(canonical(state['selected']),[(11,2,4)])

    def test_continuation_requires_visible_victory_and_real_preparation(self):
        runner=Runner.__new__(Runner);runner.g={'continue':[276,648]}
        runner.catalog=SimpleNamespace(stages=[dict(id=828),dict(id=829)])
        calls=[];runner.check_stop=lambda:None;runner.relocate=lambda:calls.append('locate')
        runner.input=SimpleNamespace(click=lambda *args:calls.append('click'))
        runner.event=lambda *args,**kw:None
        victory=dict(current_stage_id=829,battle=dict(battleID=828,state=4,result=1),victory=dict(isShow=True))
        def wait(predicate,timeout):
            if calls.count('locate')==1:self.assertTrue(predicate(victory));return victory
            self.assertFalse(predicate(victory));self.assertTrue(predicate(ready()));return ready()
        runner.wait=wait
        with patch('autoplay.time.sleep'):self.assertTrue(is_preparing(runner.continue_victory(victory)))
        self.assertEqual(calls,['locate','click','locate'])
        victory['battle']['result']=2
        with self.assertRaises(RuntimeError):runner.continue_victory(victory)

    def test_result_view_created_after_scan_is_relocated_once(self):
        runner=Runner.__new__(Runner);runner.g={'continue':[276,648]}
        runner.catalog=SimpleNamespace(stages=[dict(id=828),dict(id=829)])
        calls=[];runner.check_stop=lambda:None;runner.relocate=lambda:calls.append('locate')
        runner.event=lambda *args,**kw:None;runner.input=SimpleNamespace(click=lambda *args:calls.append('click'))
        victory=dict(current_stage_id=829,battle=dict(battleID=828,state=4,result=1),victory=dict(isShow=True))
        def wait(predicate,timeout):
            if calls.count('locate')==1:raise WaitTimeout()
            state=ready() if calls.count('locate')==3 else victory
            self.assertTrue(predicate(state));return state
        runner.wait=wait
        with patch('autoplay.time.sleep'):runner.continue_victory(victory)
        self.assertEqual(calls,['locate','locate','click','locate'])

    def test_actual_order_failure_prevents_battle_and_keeps_original_report(self):
        runner=Runner.__new__(Runner);r=report();r.update(engine_fingerprint='test',context={})
        runner.catalog=SimpleNamespace(stage=lambda _:{});runner.check_stop=lambda:None
        seeds=[]
        def evaluate(stage,order,seed):
            seeds.append(seed);return dict(won=seed!=701)
        runner.sim=SimpleNamespace(evaluate=evaluate)
        memory=SimpleNamespace(record=lambda *args:None,close=lambda:None)
        with tempfile.TemporaryDirectory() as directory:
            runner.folder=Path(directory)
            with patch('experience.Experience',return_value=memory),patch('tactics.Tactics') as tactics:
                tactics.return_value.features.return_value={}
                with self.assertRaisesRegex(RuntimeError,'实际入场顺序复核未通过'):
                    runner.verify_request_order(829,dict(request_order=r['placements']),r)
            self.assertTrue((runner.folder/'preflight-829.json').exists())
        self.assertEqual(seeds,[123456,701,2029,8191])
        self.assertNotIn('actual_order_validation',r)

    def test_overnight_roster_change_blocks_deployment(self):
        runner=Runner.__new__(Runner);runner.sim=SimpleNamespace(capture=dict(shared_level=235,pets=[dict(tid=1)]))
        with patch('live_roster.read_live',return_value=dict(shared_level=236,pets=[dict(tid=1)])):
            with self.assertRaisesRegex(RuntimeError,'养成已改变'):runner.verify_roster()


if __name__=='__main__':unittest.main()
