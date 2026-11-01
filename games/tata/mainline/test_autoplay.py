"""No desktop input: exercise deployment readback and stage-transition guards."""
import copy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch,Mock

from autoplay import Runner,WaitTimeout,canonical,card_point,is_preparing,is_chapter,next_stage_id,verified


def ready(stage=829):
    return dict(current_stage_id=stage,controller=dict(stageID=stage,battleMode=1),
        battle=dict(battleID=stage,state=1),prepare=dict(stageID=stage,isShow=True),
        selected=[],pet_list=[11])


def report():
    return dict(stage_id=829,placements=[dict(unit_id=11,x=2,y=4)],
        evaluation=dict(won=True),finalists=[dict(validation=[dict(won=True)]*3)])


class Clock:
    def __init__(self):self.now=0.;self.sleeps=[]
    def monotonic(self):return self.now
    def sleep(self,seconds):self.sleeps.append(seconds);self.now+=seconds


class AutoplayTests(unittest.TestCase):
    def test_chapter_entry_only_opens_preparation_and_verifies_the_expected_stage(self):
        from PIL import Image
        chapter=dict(screen='chapter',current_stage_id=579,chapter=dict(stage_id=579,isCarMoving=False))
        prepared=ready(579)
        runner=Runner.__new__(Runner);runner.automatic=True
        runner.layout=SimpleNamespace(capture=lambda:Image.new('RGB',(856,1568),'white'))
        seen=[]
        current=[chapter]
        def click(*args):seen.append(('click',args));current[0]=prepared
        runner.input=SimpleNamespace(set_reference=lambda *a:seen.append(('reference',a)),click=click)
        runner.snapshot=lambda:current[0];runner.relocate=lambda:seen.append(('relocate',))
        runner.refresh_layout=lambda s:seen.append(('recognized',s['current_stage_id']))
        runner.event=lambda *a,**k:None
        with patch('auto_layout.chapter_start_button',return_value=[25,1415,805,95]),patch('autoplay.time.sleep') as sleep:
            result=runner.enter_chapter(chapter)
            sleep.assert_not_called()
        self.assertTrue(is_preparing(result,579))
        self.assertEqual([row[0] for row in seen],['reference','click','recognized'])
        with self.assertRaises(RuntimeError):runner.enter_chapter(chapter,580)
        self.assertFalse(is_chapter(dict(chapter,controller={'stageID':579})))

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
        runner.event=lambda *args,**kw:None
        victory=dict(current_stage_id=829,battle=dict(battleID=828,state=4,result=1),victory=dict(isShow=True))
        current=[victory]
        def click(*args):calls.append('click');current[0]=ready()
        runner.input=SimpleNamespace(click=click);runner.snapshot=lambda:current[0]
        with patch('autoplay.time.sleep') as sleep:
            self.assertTrue(is_preparing(runner.continue_victory(victory)))
            sleep.assert_not_called()
        self.assertEqual(calls,['click'])
        victory['battle']['result']=2
        with self.assertRaises(RuntimeError):runner.continue_victory(victory)

    def test_result_view_created_after_scan_is_relocated_once(self):
        runner=Runner.__new__(Runner);runner.g={'continue':[276,648]}
        runner.catalog=SimpleNamespace(stages=[dict(id=828),dict(id=829)])
        calls=[];runner.check_stop=lambda:None
        runner.event=lambda *args,**kw:None
        victory=dict(current_stage_id=829,battle=dict(battleID=828,state=4,result=1),victory=dict(isShow=True))
        current=[dict(victory,victory={})];clock=Clock()
        def locate():calls.append('locate');current[0]=victory
        def click(*args):calls.append('click');current[0]=ready()
        runner.relocate=locate;runner.snapshot=lambda:current[0];runner.input=SimpleNamespace(click=click)
        with patch('autoplay.time.monotonic',clock.monotonic),patch('autoplay.time.sleep',clock.sleep):
            runner.continue_victory(victory)
        self.assertEqual(calls,['locate','click'])
        self.assertLess(clock.now,.25)

    def test_action_reads_back_immediately_and_waits_only_for_pending_effect(self):
        for delayed in (False,True):
            runner=Runner.__new__(Runner);runner.preparing=lambda _:ready();runner.refresh_layout=lambda _:None
            runner.input=SimpleNamespace(click=Mock());clock=Clock()
            applied=ready();applied['selected']=[dict(unit_id=11,_gridX=2,_gridY=4)]
            states=iter([ready(),applied] if delayed else [applied])
            runner.snapshot=lambda:next(states)
            with patch('autoplay.time.monotonic',clock.monotonic),patch('autoplay.time.sleep',clock.sleep):
                result=runner.action(829,'click',x=5,y=6,expect=lambda s:bool(s['selected']))
            self.assertEqual(canonical(result['selected']),[(11,2,4)])
            self.assertEqual(clock.sleeps,[.03] if delayed else [])
            runner.input.click.assert_called_once_with(x=5,y=6)

    def test_unapplied_action_times_out_without_repeating_input(self):
        runner=Runner.__new__(Runner);runner.preparing=lambda _:ready();runner.refresh_layout=lambda _:None
        runner.input=SimpleNamespace(click=Mock());runner.snapshot=lambda:ready();clock=Clock()
        with patch('autoplay.time.monotonic',clock.monotonic),patch('autoplay.time.sleep',clock.sleep):
            with self.assertRaises(WaitTimeout):
                runner.action(829,'click',x=5,y=6,expect=lambda s:bool(s['selected']),timeout=.1)
        runner.input.click.assert_called_once()
        runner.snapshot=lambda:ready(830)
        with self.assertRaisesRegex(RuntimeError,'阶段改变'):
            runner.action(829,'click',x=5,y=6,expect=lambda _:False)

    def test_automatic_deployment_uses_real_readback_loop_without_post_action_sleeps(self):
        from PIL import Image
        runner=Runner.__new__(Runner);runner.automatic=True;state=ready();actions=[]
        runner.catalog=SimpleNamespace(units={'11':dict(UnitElement=2)})
        runner.g=dict(grid=[106,371],gridStep=40.5)
        runner.sim=SimpleNamespace(capture=dict(pets=[dict(tid=11)]))
        runner.preparing=lambda _:copy.deepcopy(state);runner.snapshot=lambda:copy.deepcopy(state)
        runner.refresh_layout=lambda _:None;runner.event=lambda *a,**kw:None
        runner.layout=SimpleNamespace(capture=lambda:Image.new('RGB',(400,750)),
            locate_card=lambda *a,**kw:dict(point=[36,479]))
        def click(**args):
            actions.append('click');state['selected']=[dict(unit_id=11,_gridX=1,_gridY=1)]
        def drag(**args):
            actions.append('drag');state['selected']=[dict(unit_id=11,_gridX=2,_gridY=4)]
        runner.input=SimpleNamespace(click=click,drag=drag)
        with patch('autoplay.time.sleep') as sleep:
            runner.deploy_automatic(report())
            sleep.assert_not_called()
        self.assertEqual(actions,['click','drag'])
        self.assertEqual(canonical(state['selected']),[(11,2,4)])

    def test_actual_order_failure_prevents_battle_and_keeps_original_report(self):
        runner=Runner.__new__(Runner);r=report();r.update(engine_fingerprint='test',context={})
        runner.review_mode='full'
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

    def test_preflight_respects_review_mode_and_still_checks_actual_formation(self):
        for mode,seeds in (('light',[123456]),('none',[]),('full',[123456,701,2029,8191])):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as directory:
                runner=Runner.__new__(Runner);runner.review_mode=mode;runner.folder=Path(directory)
                runner.catalog=SimpleNamespace(stage=lambda _:{});runner.check_stop=lambda:None
                runner.event=lambda *args,**kw:None;calls=[]
                def evaluate(stage,order,seed):calls.append(seed);return dict(won=True)
                runner.sim=SimpleNamespace(evaluate=evaluate)
                memory=SimpleNamespace(record=lambda *args:None,close=lambda:None)
                r=report();r.update(engine_fingerprint='test',context={})
                with patch('experience.Experience',return_value=memory),patch('tactics.Tactics'):
                    runner.verify_request_order(829,dict(request_order=r['placements']),r)
                self.assertEqual(calls,seeds)
                self.assertEqual(len(r['actual_order_validation']),len(seeds))
                with self.assertRaisesRegex(RuntimeError,'无法核验'):
                    runner.verify_request_order(829,dict(request_order=[dict(unit_id=11,x=1,y=1)]),r)

    def test_light_preflight_loss_stops_before_start(self):
        runner=Runner.__new__(Runner);runner.review_mode='light';runner.check_stop=lambda:None
        runner.catalog=SimpleNamespace(stage=lambda _:{});runner.sim=SimpleNamespace(evaluate=lambda *args:dict(won=False))
        r=report();r.update(engine_fingerprint='test',context={})
        memory=SimpleNamespace(record=lambda *args:None,close=lambda:None)
        with tempfile.TemporaryDirectory() as directory:
            runner.folder=Path(directory)
            with patch('experience.Experience',return_value=memory),patch('tactics.Tactics'):
                with self.assertRaisesRegex(RuntimeError,'0/1'):
                    runner.verify_request_order(829,dict(request_order=r['placements']),r)
        self.assertNotIn('actual_order_validation',r)

    def test_overnight_roster_change_blocks_deployment(self):
        runner=Runner.__new__(Runner);runner.sim=SimpleNamespace(capture=dict(shared_level=235,pets=[dict(tid=1)]))
        with patch('live_roster.read_live',return_value=dict(shared_level=236,pets=[dict(tid=1)])):
            with self.assertRaisesRegex(RuntimeError,'养成已改变'):runner.verify_roster()

    def test_same_roster_reuses_simulator_but_every_stage_is_evaluated_again(self):
        runner=Runner.__new__(Runner);runner.live=object();runner.review_mode='light';runner.stop_when_verified=True
        runner.catalog=SimpleNamespace(stage=lambda _:dict(stage=dict(DisplayName='测试关卡')))
        runner.compute_stopped=lambda:False;runner.event=lambda *a,**kw:None
        capture=dict(shared_level=234,pets=[dict(tid=11)])
        runner.read_account_capture=lambda:dict(capture)
        memory=SimpleNamespace(record=lambda *a:None,close=lambda:None)
        created=[]
        def create(value,catalog):
            sim=SimpleNamespace(capture=value,engine_fingerprint='test',evaluate=Mock(return_value=dict(won=True)))
            created.append(sim);return sim
        with tempfile.TemporaryDirectory() as directory:
            runner.folder=Path(directory)
            with patch('live_roster.to_roster'),patch('combat.Simulator',side_effect=create),\
                 patch('experience.Experience',return_value=memory),patch('experience.context_for',return_value={}),patch('tactics.Tactics') as tactics:
                tactics.return_value.features.return_value={}
                for stage in (829,830):runner.plan(dict(ready(stage),request_order=report()['placements']))
                self.assertEqual(len(created),1)
                self.assertEqual(created[0].evaluate.call_count,4)
                capture['shared_level']=235
                runner.plan(dict(ready(881),request_order=report()['placements']))
                self.assertEqual(len(created),2)
                self.assertEqual(created[1].evaluate.call_count,2)

    def test_preflight_reuses_only_this_plan_same_runtime_stage_seed_and_exact_entry_order(self):
        runner=Runner.__new__(Runner);runner.review_mode='light';runner.check_stop=lambda:None
        runner.catalog=SimpleNamespace(stage=lambda _:{});runner.event=lambda *a,**kw:None
        runner.sim=SimpleNamespace(evaluate=Mock(return_value=dict(won=True,seed=123456)))
        order=[dict(unit_id=11,x=2,y=4),dict(unit_id=12,x=3,y=4)]
        signature=tuple((p['unit_id'],p['x'],p['y']) for p in order)
        memory=SimpleNamespace(record=lambda *a:None,close=lambda:None)
        with tempfile.TemporaryDirectory() as directory:
            runner.folder=Path(directory)
            for variant in ('same','order','stage','seed','runtime'):
                with self.subTest(variant=variant):
                    runner.sim.evaluate.reset_mock()
                    runtime=object() if variant=='runtime' else runner.sim
                    runner.plan_preflight=(runtime,828 if variant=='stage' else 829,signature,
                        dict(won=True,seed=701 if variant=='seed' else 123456))
                    actual=list(reversed(order)) if variant=='order' else order
                    r=dict(report(),placements=order,engine_fingerprint='test',context={})
                    with patch('experience.Experience',return_value=memory),patch('tactics.Tactics'):
                        runner.verify_request_order(829,dict(request_order=actual),r)
                    self.assertEqual(runner.sim.evaluate.call_count,0 if variant=='same' else 1)


if __name__=='__main__':unittest.main()
