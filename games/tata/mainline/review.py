"""Shared simulation review choices for search, autoplay and the panel."""
MODES=('light','none','full')
LABELS={'light':'轻量（1次）','none':'关闭（0次）','full':'完整（多种子/顺序）'}


def review_seeds(mode):
    if mode not in MODES:raise ValueError('未知复核方式')
    return {'light':(701,),'none':(),'full':(701,2029,8191)}[mode]


def preflight_seeds(mode):
    review_seeds(mode)
    return {'light':(123456,),'none':(),'full':(123456,701,2029,8191)}[mode]


def passed(candidate):
    checks=candidate.get('validation',[])
    expected=candidate.get('validation_expected',3)
    return (candidate.get('evaluation',{}).get('won') is True
        and candidate.get('validation_complete',False)
        and len(checks)==expected and all(v.get('won') is True for v in checks))
