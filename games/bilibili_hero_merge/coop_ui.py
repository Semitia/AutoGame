"""Observed co-op lobby UI. All coordinates use the 432 x 768 reference."""
import re
import time
from dataclasses import dataclass

import cv2
import numpy as np
from vision import Reader


@dataclass(frozen=True)
class Label:
    text: str
    x: float
    y: float
    confidence: float = 1.0


def account_name(text):
    return re.sub(r'[（(]\d+服[）)]$', '', ''.join(text.split()))


def unique_name(labels, name):
    matches = [p for p in labels if account_name(p.text) == name and p.confidence >= .92]
    return matches[0] if len(matches) == 1 else None


def row_action(labels, name, action, y_offset=0):
    """Never use substring/fuzzy name matching or a global invite button."""
    person = unique_name(labels, name)
    if person is None:
        return None
    buttons = [p for p in labels if p.text == action and p.confidence >= .9
               and p.x > person.x + 60 and abs(p.y-person.y-y_offset) < 16]
    return buttons[0] if len(buttons) == 1 else None


class Screen:
    def __init__(self, platform, output):
        self.platform = platform
        self.output = output
        self.reader = Reader()
        self.labels = []

    def shot(self):
        native = cv2.imdecode(np.frombuffer(self.platform.screenshot(), np.uint8), 1)
        if native is None or abs(native.shape[1]/native.shape[0] - 9/16) > .01:
            raise RuntimeError('Expected a portrait 9:16 Android screen')
        self.height, self.width = native.shape[:2]
        self.raw = cv2.resize(native, (1080, 1920), interpolation=cv2.INTER_AREA)
        cv2.imwrite(str(self.output/'latest.png'), self.raw)
        return self.raw

    def scan(self):
        self.shot()
        result, _ = self.reader.ocr(self.raw, use_cls=False)
        self.labels = [Label(''.join(text.split()),
                            sum(p[0] for p in box)/len(box)/2.5,
                            sum(p[1] for p in box)/len(box)/2.5, float(confidence))
                       for box, text, confidence in result or []]
        return self.labels

    def tap(self, x, y):
        self.platform.tap(round(x*self.width/432), round(y*self.height/768))

    def click(self, label):
        self.tap(label.x, label.y)
        time.sleep(.7)

    def find(self, text):
        matches = [p for p in self.labels if p.text == text and p.confidence >= .9]
        return matches[0] if len(matches) == 1 else None

    def room(self, host, guest, floor):
        return (unique_name(self.labels, host) is not None
                and unique_name(self.labels, guest) is not None
                and self.find(f'第{floor}层') is not None
                and self.find('队长') is not None
                and not self.find('组队邀请') and not self.find('战斗邀请')
                and not self.find('装备掉率') and not self.find('体力购买'))


def setup_pair(host, guest, host_name, guest_name, floor, log, stopped, timeout=120):
    """Join only the named two accounts; stop before spending the challenge ticket."""
    deadline = time.monotonic()+timeout
    sent_at = 0
    verified = set()
    while time.monotonic() < deadline:
        if stopped():
            raise RuntimeError('Stopped during team setup')
        host.scan(); guest.scan()
        if host.room(host_name, guest_name, floor) and guest.room(host_name, guest_name, floor):
            log('team_verified', host=host_name, guest=guest_name, floor=floor)
            return
        # Verify each device's own left-side identity before sending anything.
        for role, screen, name in [('host', host, host_name), ('guest', guest, guest_name)]:
            own = unique_name(screen.labels, name)
            if own and own.x < 190 and 510 < own.y < 570 and screen.find('队长'):
                verified.add(role)
            start = screen.find('开始挑战')
            if start:
                if role == 'host' and not screen.find(f'第{floor}层'):
                    raise RuntimeError('Host is not on the requested co-op floor')
                screen.click(start)
                break
        else:
            if guest.find('战斗邀请'):
                button = row_action(guest.labels, host_name, '接受')
                if button and guest.find(f'第{floor}层') and sent_at:
                    guest.click(button); log('invite_accepted', host=host_name)
                    continue
            invite_notice = next((p for p in guest.labels if p.text.startswith('合作邀请') and p.x > 300), None)
            if invite_notice and sent_at:
                guest.click(invite_notice); continue
            if host.find('组队邀请'):
                # A restarted coordinator must re-verify the host on its room.
                if 'host' not in verified:
                    host.tap(395,76); time.sleep(.7); continue
                if verified != {'host','guest'}:
                    raise RuntimeError('Guest identity was not verified on its own device')
                friends = next((p for p in host.labels if p.text=='好友' and p.y>700), None)
                button = row_action(host.labels, guest_name, '邀请', y_offset=21)
                if button and time.monotonic()-sent_at > 62:
                    host.click(button); sent_at=time.monotonic()
                    log('invite_sent', guest=guest_name)
                    # The game may close the modal on acceptance. Re-observe
                    # before closing it; never enqueue a stale close tap.
                    host.scan()
                    if host.find('组队邀请'):
                        host.tap(395,76); time.sleep(.5)
                    continue
                if friends and not unique_name(host.labels,guest_name):
                    host.click(friends)
                    host.scan()
                    if not unique_name(host.labels,guest_name):
                        raise RuntimeError('Exact friend name not visible; refusing other invite buttons')
                    continue
            if verified == {'host','guest'} and not sent_at:
                button=host.find('邀请')
                if button:
                    host.click(button); continue
            if sent_at and time.monotonic()-sent_at > 62:
                button=host.find('邀请')
                if button:
                    host.click(button); continue
        time.sleep(.5)
    raise RuntimeError('Co-op setup timed out')
