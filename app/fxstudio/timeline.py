"""时长、帧号、关键帧方案。帧号规则与原工作流完全一致（25fps，总帧数 24×秒数+1）。"""
from __future__ import annotations

FPS = 25
SCHEMES = {0: "只用首帧", 1: "首帧 + 尾帧", 2: "每秒一帧"}


def total_frames(seconds: int) -> int:
    if not 1 <= int(seconds) <= 5:
        raise ValueError("时长只支持 1–5 秒")
    return 24 * int(seconds) + 1


def last_index(seconds: int) -> int:
    return total_frames(seconds) - 1


def scheme_indices(seconds: int, scheme: int) -> list[int]:
    """原工作流的三种方案：首帧 0；中间帧 25/49/73/97（8k+1）；尾帧 = 总帧数-1。"""
    last = last_index(seconds)
    if scheme == 0:
        return [0]
    if scheme == 1:
        return [0, last]
    mids = [24 * s + 1 for s in range(1, int(seconds))]
    return [0] + mids + [last]


def grid_positions(seconds: int) -> list[int]:
    """允许的关键帧位置（G4 吸附网格）：0、8k+1、尾帧。"""
    last = last_index(seconds)
    pos = [0] + list(range(1, last, 8)) + [last]
    return sorted(set(pos))


def snap(index: int, seconds: int) -> int:
    g = grid_positions(seconds)
    return min(g, key=lambda p: (abs(p - index), p))


def frame_label(index: int, seconds: int) -> str:
    if index == 0:
        return "首帧"
    if index == last_index(seconds):
        return "尾帧"
    return f"{index / FPS:.2f}s"
