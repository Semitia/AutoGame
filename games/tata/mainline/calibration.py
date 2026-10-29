"""Legacy geometry validation and passive capture; default runs recognize layouts automatically."""
import math
from PIL import ImageGrab



def geometry_from_points(points, cells, size):
    a, b = points['grid_a'], points['grid_b']
    (ax, ay), (bx, by) = cells
    if ax == bx or ay == by:
        raise ValueError('地图校准需要两个横纵坐标都不同的格子')
    sx, sy = (b[0]-a[0])/(bx-ax), (a[1]-b[1])/(by-ay)
    if sx <= 0 or sy <= 0 or abs(sx-sy) > .12*max(sx, sy):
        raise ValueError('地图格子间距不一致，请重新选择两只塔塔脚下的格子中心')
    step = (sx+sy)/2
    first, second, lower = points['card'], points['card_next'], points['card_lower']
    card_step, row_step = second[0]-first[0], lower[1]-first[1]
    if card_step <= 10 or row_step <= 10 or abs(second[1]-first[1]) > row_step*.2 or abs(lower[0]-first[0]) > card_step*.2:
        raise ValueError('卡片行列位置不一致，请重选第一列上下两张和第二列上方卡片中心')
    g = dict(schema_version=2, calibration_source='user-preview', width=size[0], height=size[1],
             physical_size=list(size), grid=[a[0]-(ax-1)*step, a[1]+(ay-1)*step], gridStep=step,
             card=first, cardStep=card_step, cardRowStep=row_step,
             clear=points['clear'], start=points['start'],
             filters={str(i): points[f'filter_{i}'] for i in range(2, 7)})
    g['calibration_points']=points;g['calibration_cells']=cells
    if 'card_tail' in points:
        g['cardRight'] = points['card_tail'][0]
        columns = math.floor((g['cardRight']-first[0])/card_step+.1)+1
        if columns < 2:
            raise ValueError('列表末页最右卡片必须在第一张卡片右边')
        g['visible_cards'] = columns*2
        middle = (first[1]+lower[1])/2
        g['gallerySwipe'] = [g['cardRight'], middle, first[0], middle]
    if 'continue' in points:g['continue'] = points['continue']
    validate_geometry(g)
    return g


def validate_geometry(g):
    width, height = g['width'], g['height']
    if any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in (width, height, g['gridStep'], g['cardStep'], g['cardRowStep'])):
        raise ValueError('窗口校准尺寸或间距无效')
    points = [g['card'], g['clear'], g['start'], *g['filters'].values()]
    if 'continue' in g:points.append(g['continue'])
    if set(g['filters']) != {str(i) for i in range(2, 7)}:
        raise ValueError('缺少元素筛选按钮校准')
    if any(len(p) != 2 or not all(type(v) in (int, float) and math.isfinite(v) for v in p) or not (0 <= p[0] < width and 0 <= p[1] < height) for p in points):
        raise ValueError('窗口校准点超出截图边界')


def capture_visible_game():
    # Only capture an already visible window. Never restore, activate or move it.
    from desktop_input import DesktopWindow, find_game_window, user, W
    hwnd = find_game_window()
    left, top, width, height = DesktopWindow(hwnd).bounds()
    for ix in range(1, 8):
        for iy in range(1, 12):
            point = W.POINT(left+width*ix//8, top+height*iy//12)
            if user.GetAncestor(user.WindowFromPoint(point), 2) != hwnd:
                raise ValueError('游戏被其他窗口挡住，当前只读检查无法取得完整画面；工具不会抢前台。运行自动推关时会按启动操作切到游戏。')
    image=ImageGrab.grab(bbox=(left, top, left+width, top+height))
    if DesktopWindow(hwnd).bounds()!=(left,top,width,height):
        raise ValueError('窗口正在移动或缩放，等窗口稳定后重试即可，无需标点')
    return image
