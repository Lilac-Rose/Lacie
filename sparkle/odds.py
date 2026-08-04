import time

_TAPS = 0xB400
_state = (time.time_ns() & 0xFFFF) or 0xACE1


def _shift() -> int:
    global _state
    lsb = _state & 1
    _state >>= 1
    if lsb:
        _state ^= _TAPS
    return lsb


def _roll(max_value: int) -> int:
    value = 0
    for _ in range(17):  # 2^17 > 100000, covers our largest roll range
        value = (value << 1) | _shift()
    return (value % max_value) + 1


def get_sparkle_type(message_id: int, user_id: int) -> str | None:
    global _state
    _state ^= (message_id ^ user_id) & 0xFFFF
    if _state == 0:
        _state = 0xACE1  # all-zero state would lock the LFSR forever

    roll = _roll(100000)
    if roll == 1:
        return "epic"
    if roll <= 10:
        return "rare"
    if roll <= 100:
        return "regular"
    return None
